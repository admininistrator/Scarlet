"""Hai cửa sổ trượt của quota — đọc, dọn, và tính `retry_after` (§10.3).

KH tham chiếu: §10.2, §10.3, ADR-08, UC-07 · CLAUDE.md A3, A7 · tasks.md
T-2.11, T-2.12, T-2.13, B-65.

§10.3 viết ra đúng một bảng, và cả file này là nó:

    | Cửa sổ | Cấu trúc                             | Đọc            | Dọn                 |
    | 5 giờ  | ZSET `quota:5h:{uid}`, score = epoch  | ZRANGEBYSCORE  | ZREMRANGEBYSCORE    |
    |        |                                       | rồi cộng       | trước mỗi lần đọc   |
    | 7 ngày | ZSET `quota:7d:{uid}`                 | tương tự       | tương tự            |

    "`retry_after` tính chính xác bằng: thời điểm mà tổng trong cửa sổ tụt
     xuống dưới hạn mức = `score` của phần tử cũ nhất cần rơi ra + độ dài cửa
     sổ − now."

╔══════════════════════════════════════════════════════════════════════════╗
║  MEMBER MANG CẢ CHI PHÍ — LỆCH MỘT CHỮ SO VỚI §10.3, VÀ BỊ ÉP PHẢI LỆCH  ║
╚══════════════════════════════════════════════════════════════════════════╝

§10.3 viết `member = {usage_id}` và ngay dòng bên cạnh viết "`ZRANGEBYSCORE`
rồi **cộng**". Hai câu đó không đứng cùng nhau được: `score` đã là **epoch**
(cột "Dọn" đòi thế — `ZREMRANGEBYSCORE -inf now-18000` chỉ chạy khi score là
thời điểm), nên nếu member chỉ có `usage_id` thì trong ZSET **không còn chỗ
nào** giữ số tiền, và "cộng" không cộng được gì. (§10.2 viết
`ZADD quota:5h:{uid} <ts> <cost>` — tức member là `<cost>`; như vậy hai lượt
sinh cùng giá sẽ đè lên nhau thành **một** member và tiền của một lượt biến
mất.)

Vì vậy member ở đây là **`{usage_id}:{cost}`**: `usage_id` giữ tính duy nhất
mà §10.3 cần, `cost` là thứ phép cộng cần, và cả hai nằm trong đúng một cấu
trúc. Ngả còn lại — ZSET cho thời gian + HASH cho tiền — là hai khoá phải dọn
khớp nhau ở ba chỗ (ghi, dọn theo cửa sổ, `rebuild_quota`), và chỗ lệch đầu
tiên sẽ là một hoá đơn sai mà không ai truy được.

`encode_member`/`parse_member` là **hợp đồng giữa ba task**: T-2.11 đọc (file
này), T-2.12 ghi, T-2.13 dựng lại từ `usage_events`. Cả ba đi qua đúng hai hàm
dưới đây, không ai tự nối chuỗi.

╔══════════════════════════════════════════════════════════════════════════╗
║  DỌN TRƯỚC KHI ĐỌC, KHÔNG PHẢI SAU                                       ║
╚══════════════════════════════════════════════════════════════════════════╝

Thứ tự này là chữ của §10.3 ("`ZREMRANGEBYSCORE` **trước mỗi lần đọc**") và nó
không phải chuyện gọn gàng: phép đọc lấy `ZRANGEBYSCORE cutoff +inf` nên bản
thân nó đã bỏ qua phần tử quá hạn — dọn trước hay sau đều ra cùng một con số
tiền. Cái khác nằm ở **`retry_after`**: nó đi từ phần tử **cũ nhất còn trong
cửa sổ**, và nếu rác quá hạn còn nằm đó thì phần tử cũ nhất là một phần tử đã
chết, tức hẹn người dùng quay lại vào một thời điểm đã trôi qua.

Không có tiến trình nền nào dọn hộ, và cũng không cần: khoá của một người chỉ
lớn lên khi chính họ chat, mà đường chat nào cũng đi qua hàm đọc ở đây.
"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
from typing import TYPE_CHECKING

from app.config.settings import settings

if TYPE_CHECKING:  # pragma: no cover - chỉ dùng cho kiểu
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

#: Tiền tố khoá ZSET. Cùng luật với `TIER_CACHE_PREFIX`, `RL_*_PREFIX`: không
#: ai tự nối chuỗi ở chỗ khác. Một tiền tố gõ lệch ở đây là một cửa sổ **rỗng**
#: — tức một người dùng không có trần chi tiêu, và im lặng.
QUOTA_PREFIX = "quota:"

#: Số chữ số thập phân khi ghi tiền vào member. Đúng bằng `NUMERIC(12,6)` của
#: `usage_events.cost_usd` (Phụ lục A): con số đi vòng qua Redis rồi về phải là
#: **đúng** con số Postgres giữ, nếu không thì phép đối chiếu của DoD T-2.12
#: ("`SUM(cost_usd)` khớp tổng ZSET ±0.000001") đo chính sai số của mình.
COST_DECIMALS = 6

#: Bước nhỏ nhất của một con số tiền, dẫn xuất từ `COST_DECIMALS` chứ không gõ
#: lại `Decimal("0.000001")`: hai chỗ viết ra cùng một độ chính xác là hai chỗ
#: để lệch, và chỗ lệch ấy đúng bằng sai số mà DoD T-2.12 dòng 5 đo (`SUM(
#: cost_usd)` Postgres khớp tổng ZSET Redis ±0.000001).
COST_QUANTUM = Decimal(1).scaleb(-COST_DECIMALS)


class LimitType(StrEnum):
    """`limit_type` trong body `429` — UC-07 chốt đúng hai giá trị này.

    Là `StrEnum` chứ không phải hai chuỗi rời: FE rẽ nhánh theo nó ("hết quota
    5 giờ" và "hết quota tuần" là hai câu khác nhau cho người dùng), và một
    hợp đồng FE chỉ có ích khi tìm được nó bằng cách đọc một danh sách — cùng
    lý lẽ với `ApiErrorCode`.
    """

    SHORT = "5h"
    LONG = "weekly"


@dataclass(frozen=True, slots=True)
class Window:
    """Một cửa sổ trượt: tên trong hợp đồng API + độ dài tính bằng giây."""

    limit_type: LimitType
    #: Hằng `.env` được đọc ở **lúc gọi** chứ không lúc import — cùng lý do đã
    #: ghi ở `gioi_han_theo_user`: một test hạ nó xuống phải thấy hiệu lực ngay.
    seconds: int

    def key(self, user_id: uuid.UUID) -> str:
        """`quota:5h:{uid}` / `quota:weekly:{uid}`.

        Dùng `limit_type` làm mảnh giữa chứ không phải `5h`/`7d` như §10.3 viết
        ở cột "Cấu trúc": tên cửa sổ đã có **một** chỗ để sống (hợp đồng API,
        UC-07), và đặt tên khoá Redis theo một bảng chữ thứ hai là mời hai
        bảng ấy lệch nhau. Xem "Lệch kế hoạch" trong báo cáo T-2.11.
        """
        return f"{QUOTA_PREFIX}{self.limit_type.value}:{user_id}"


def windows() -> tuple[Window, Window]:
    """Hai cửa sổ của §10.3, theo đúng thứ tự kiểm của §10.2 (5 giờ trước).

    Là một **hàm** chứ không phải một hằng module: hai con số đến từ `Settings`
    (A3), và một hằng dựng lúc import sẽ đóng băng giá trị của lần import đầu
    tiên — đúng thứ làm một test hạ `QUOTA_WINDOW_SHORT_S` xuống mà không thấy
    gì đổi.
    """
    return (
        Window(LimitType.SHORT, settings.QUOTA_WINDOW_SHORT_S),
        Window(LimitType.LONG, settings.QUOTA_WINDOW_LONG_S),
    )


def encode_member(usage_id: uuid.UUID, cost_usd: Decimal) -> str:
    """`{usage_id}:{cost}` — hình dạng member DUY NHẤT của hai ZSET.

    T-2.12 gọi hàm này khi `ZADD`. Nó nằm ở đây, cạnh `parse_member`, để hai
    nửa của một định dạng không bao giờ ở hai file (bài học cùng loại với
    `ToolCall.to_wire()` của `app/llm/client.py`).
    """
    return f"{usage_id}:{cost_usd:.{COST_DECIMALS}f}"


def quantize_cost(cost_usd: Decimal) -> Decimal:
    """Ép một con số tiền về đúng `NUMERIC(12,6)` của `usage_events.cost_usd`.

    Gọi **một lần**, rồi dùng đúng kết quả đó cho cả `INSERT` lẫn `ZADD` — đó
    là toàn bộ lý do hàm này tồn tại. Không gọi thì phép làm tròn xảy ra **hai
    lần ở hai nơi bằng hai luật khác nhau**: Postgres cắt `NUMERIC(12,6)` theo
    kiểu làm tròn nửa-ra-xa-số-không, còn `encode_member` dùng `f"{…:.6f}"` tức
    làm tròn nửa-về-chẵn của Python. Hai luật ấy lệch nhau ở đúng những giá trị
    kết thúc bằng 5 — và DoD T-2.12 dòng 5 đo chính khoảng lệch đó.

    `ROUND_HALF_UP` chứ không `ROUND_UP`: đây là phép **làm tròn**, không phải
    một biên an toàn. Cửa chặn TRƯỚC (`estimator.py`) mới là chỗ nghiêng về
    phía an toàn; sổ sách thì phải trung tính, nếu không thì mọi hoá đơn đều
    lệch lên một chiều và không ai đối chiếu được với hoá đơn provider (S13).
    """
    return cost_usd.quantize(COST_QUANTUM, rounding=ROUND_HALF_UP)


def parse_member(member: str) -> Decimal | None:
    """Chi phí trong một member, hoặc `None` nếu member không đọc được.

    `None` chứ không phải `Decimal(0)` và cũng không phải một exception: một
    member hỏng là **dữ liệu**, không phải lỗi lập trình, và nó đến được đây
    bằng một đường có thật — ai đó `ZADD` bằng tay, hoặc một phiên bản sau đổi
    định dạng và còn 5 giờ member cũ nằm trong Redis. Ném ra giữa một lượt
    chat là đổi một con số hơi thiếu lấy một cửa chat đóng hẳn.

    Người gọi phân biệt được hai ca nhờ `None`, và `read_window` dùng khác
    biệt đó để **không** im lặng: nó đếm số member hỏng rồi ghi WARNING một
    lần cho cả cửa sổ.
    """
    _, _, raw = member.rpartition(":")
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


@dataclass(frozen=True, slots=True)
class WindowState:
    """Trạng thái một cửa sổ tại thời điểm đọc.

    `entries` giữ **cả** danh sách `(score, cost)` chứ không chỉ tổng, vì
    `retry_after` của §10.3 không tính được từ tổng: nó phải biết phần tử nào
    rơi ra lúc nào. Danh sách đã sắp theo `score` tăng dần (Redis trả thế), và
    `retry_after_s` dựa vào đúng thứ tự đó.
    """

    window: Window
    spent: Decimal
    entries: tuple[tuple[float, Decimal], ...]

    def retry_after_s(self, *, need_to_free: Decimal, now: float) -> int | None:
        """Bao nhiêu giây nữa thì cửa sổ nhả đủ `need_to_free` USD (§10.3).

        Đi từ phần tử **cũ nhất**, cộng dồn, dừng ở phần tử đầu tiên làm tổng
        đã nhả vượt `need_to_free`; thời điểm nó rơi ra là `score + độ dài cửa
        sổ`. Làm tròn **lên**, tối thiểu 1 — cùng luật `_giay_len` của
        `core/ratelimit.py`: một `Retry-After` làm tròn xuống là mời client
        quay lại vào đúng lúc vẫn còn bị chặn, và `0` nghĩa là "thử ngay đi",
        tức một vòng lặp bận.

        Trả **`None`** khi nhả hết cả cửa sổ vẫn không đủ. Ca đó có thật và nó
        là ca của DoD dòng 1: hạ `limit_5h_usd` xuống 0.001 thì **một** lượt
        sinh cũng đã vượt trần, nên không có thời điểm nào để hẹn. Đoán một
        con số ở đây là nói dối bằng một header mà client sẽ tin — cùng lý lẽ
        đã chốt cho `TOO_MANY_STREAMS` (§10.6), nơi `Retry-After` cũng cố ý
        vắng mặt.
        """
        if need_to_free <= 0:
            return None
        da_nha = Decimal(0)
        for score, cost in self.entries:
            da_nha += cost
            if da_nha >= need_to_free:
                return max(1, math.ceil(score + self.window.seconds - now))
        return None


async def read_window(
    redis: Redis, window: Window, *, user_id: uuid.UUID, now: float
) -> WindowState:
    """Dọn phần quá hạn rồi đọc phần còn trong cửa sổ. Ngoại lệ Redis KHÔNG bị nuốt.

    Cùng lối `take_token`/`dem_va_kiem` của `core/ratelimit.py`: chỗ gọi mới
    biết phải trả lời người dùng thế nào, nên module này không tự dựng
    `ApiError`.

    Hai lệnh, không phải một pipeline. `ZREMRANGEBYSCORE` rồi `ZRANGEBYSCORE`
    chạy tách rời là **không** có đua: phép đọc tự lọc theo `cutoff` nên một
    `ZADD` chen vào giữa chỉ có thể thêm một phần tử **trong** cửa sổ, tức một
    phần tử đúng ra phải được đếm.
    """
    key = window.key(user_id)
    cutoff = now - window.seconds

    await redis.zremrangebyscore(key, "-inf", f"({cutoff}")
    raw = await redis.zrangebyscore(key, cutoff, "+inf", withscores=True)

    entries: list[tuple[float, Decimal]] = []
    hong = 0
    for member, score in raw:
        cost = parse_member(member if isinstance(member, str) else member.decode())
        if cost is None:
            hong += 1
            continue
        entries.append((float(score), cost))

    if hong:
        logger.warning(
            "cua so %s cua user %s co %d member khong doc duoc — bo qua, "
            "chi phi cua chung KHONG duoc tinh",
            window.limit_type.value,
            user_id,
            hong,
        )

    return WindowState(
        window=window,
        spent=sum((cost for _, cost in entries), Decimal(0)),
        entries=tuple(entries),
    )


async def add_to_windows(
    redis: Redis,
    *,
    user_id: uuid.UUID,
    usage_id: uuid.UUID,
    cost_usd: Decimal,
    now: float,
) -> None:
    """Ghi chi phí của MỘT `usage_events` vào **cả hai** cửa sổ (§10.2 vế SAU).

    Đối xứng với `read_window`: ở trên là bên đọc, đây là bên ghi, và cả hai
    đi qua cùng `Window.key` + `encode_member` nên không có chỗ nào gõ tay một
    tiền tố hay một dấu hai chấm. Đó là điều B-156 đòi bằng chữ: *"T-2.12 phải
    `ZADD` bằng `encode_member` — tự nối chuỗi ở `workers/` là dựng bản hiện
    thực thứ hai của một định dạng, đúng loại lỗi mà một hoá đơn sai không truy
    ngược được"*.

    **Ghi cả khi `cost_usd` bằng 0.** Một model chưa có giá (`manual_pricing`
    còn trống, B-65) vẫn sinh ra một dòng `usage_events`, và bỏ nó khỏi ZSET
    sẽ phá vỡ bất biến duy nhất nối hai kho: *mỗi dòng `usage_events` có đúng
    một member trong mỗi cửa sổ*. `rebuild_quota` của T-2.13 dựng lại ZSET
    bằng cách đọc thẳng `usage_events`, nên bất biến ấy chính là thứ khiến bản
    dựng lại **bằng** bản gốc chứ không chỉ gần bằng.

    **`EXPIRE` ở mỗi lần ghi** — nửa (b) của B-156. Hai khoá tự co lại mỗi lần
    đọc (`ZREMRANGEBYSCORE` trong `read_window`), nhưng người dùng ngừng chat
    thì không ai đọc nữa và member quá hạn nằm đó vô thời hạn. TTL dùng
    **`window.seconds`** chứ không phải `QUOTA_WINDOW_LONG_S` cho cả hai khoá
    như chữ của B-156: mọi member trong khoá đều có `score ≤ now`, nên sau
    đúng một độ dài cửa sổ kể từ lần ghi cuối thì **không** member nào còn nằm
    trong cửa sổ — hết hạn cả khoá lúc đó không mất một đồng nào, và với khoá
    5 giờ thì nó dọn sớm hơn 33 lần. Hai cách đều đúng; cách này chặt hơn và
    vẫn là một dòng.

    Ngoại lệ Redis **không** bị nuốt ở đây, cùng lối `read_window`: chỗ gọi
    (`workers/generate.py`) mới biết một lượt sinh đã xong có được phép chết vì
    một lỗi ghi sổ hay không.
    """
    member = encode_member(usage_id, cost_usd)
    for window in windows():
        key = window.key(user_id)
        await redis.zadd(key, {member: now})
        await redis.expire(key, window.seconds)
