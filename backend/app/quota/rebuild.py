"""Dựng lại hai ZSET quota từ `usage_events` — RR-7, §10.3 (T-2.13).

KH tham chiếu: §10.3, RR-7, A7 · CLAUDE.md A3, A7 · tasks.md T-2.13, B-155,
B-156 · NQ-53.

§10.3 viết ra đúng hai câu cho file này:

    "**Redis là cache, Postgres là sự thật.** Khi Redis mất dữ liệu, quota
     được dựng lại bằng một truy vấn `SUM(cost_usd)` trên `usage_events` (có
     index `(user_id, created_at)`), rồi nạp lại ZSET. Hàm `rebuild_quota(
     user_id)` phải tồn tại và có test — không phải để phòng xa, mà vì
     `docker compose down -v` khi dev sẽ xảy ra thường xuyên."

RR-7 nói cùng điều ấy từ phía rủi ro: *"Redis mất dữ liệu → quota reset"* —
và một quota reset **không tự khai báo**. Nó trông y hệt một người dùng mới.
Cạm bẫy của T-2.13 viết thẳng hệ quả: *"bạn sẽ không phát hiện cho tới khi ai
đó lợi dụng"*.

╔══════════════════════════════════════════════════════════════════════════╗
║  `SUM` KHÔNG DỰNG LẠI ĐƯỢC ZSET — PHẢI ĐỌC TỪNG DÒNG                     ║
╚══════════════════════════════════════════════════════════════════════════╝

Chữ của §10.3 là "một truy vấn `SUM(cost_usd)`", nhưng một tổng không nạp lại
được thứ mà §10.3 mô tả ở bảng ngay phía trên nó: ZSET có `score` là **epoch
của từng khoản**, và cột "Dọn" (`ZREMRANGEBYSCORE`) chỉ chạy được nhờ đúng
con số ấy. Nạp một tổng vào ZSET thì phải chọn cho nó **một** `score`, và mọi
lựa chọn đều sai:

* `score = now` ⇒ tiền tiêu 4 giờ trước được gia hạn thêm 5 giờ nữa, tức
  người dùng bị phạt hai lần cho cùng một khoản.
* `score = cutoff` ⇒ cả tổng rơi khỏi cửa sổ ở giây kế tiếp, tức quota vẫn
  reset, chỉ chậm hơn một nhịp.

Vì vậy hàm này đọc **từng dòng** (`list_since`) và nạp lại **từng member**,
giữ nguyên `created_at` làm `score`. Đó cũng là thứ khiến bất biến mà DoD
T-2.12 dòng 5 đo được vẫn đúng sau khi dựng lại: *số member trong mỗi cửa sổ
bằng số dòng sổ trong cửa sổ đó*, không chỉ "tổng tiền bằng nhau".

╔══════════════════════════════════════════════════════════════════════════╗
║  HỢP (ZADD) CHỨ KHÔNG THAY (DEL + ZADD) — CHỖ TỐN SUY NGHĨ NHẤT CỦA FILE ║
╚══════════════════════════════════════════════════════════════════════════╝

"Dựng lại" nghe như *xoá rồi ghi lại*, nhưng hàm này **không** `DEL` khoá.
Hai lý do, và lý do thứ nhất là một khoản tiền thật:

1. **Giữa `DEL` và `ZADD` có một khe.** Worker ghi sổ bằng `add_to_windows`
   bất cứ lúc nào (§10.2 vế SAU), và một lượt sinh khép sổ đúng trong khe ấy
   sẽ bị xoá khỏi ZSET trong khi dòng `usage_events` của nó vẫn nằm trong
   Postgres — tức mất tiền theo đúng cái cách mà hàm này sinh ra để vá. Gói
   hai lệnh vào `MULTI/EXEC` chỉ thu hẹp khe chứ không đóng được nó: ảnh chụp
   Postgres đã được lấy **trước** đó.
2. **Ghi lại một member là một phép toán không đổi.** `encode_member` chỉ phụ
   thuộc `usage_id` và `cost_usd`, mà cả hai đều bất biến (A7: *"đổi giá trong
   catalog KHÔNG được làm đổi lịch sử"*). Nạp lại một dòng đã có trong ZSET vì
   vậy **ghi đè đúng chính nó** — chạy `rebuild_quota` mười lần cho ra đúng
   một kết quả với chạy một lần.

Cái mất khi không `DEL`: một member "ma" — nằm trong Redis mà không có dòng sổ
nào — sẽ sống sót qua mọi lần dựng lại. Ca ấy đòi hoặc một `ZADD` bằng tay,
hoặc một `DELETE FROM usage_events` mà A7 đã cấm; và nó hỏng về phía **chặt
hơn** (người dùng bị tính thừa, không phải chạy miễn phí). Đổi một rủi ro mất
tiền lấy một rủi ro tính thừa, trong một ca không có đường đi hợp lệ nào tạo
ra được, là cùng chiều với mọi quyết định khác của §10.2.

╔══════════════════════════════════════════════════════════════════════════╗
║  TỰ GỌI KHI NÀO: ZSET RỖNG **VÀ** POSTGRES CÓ DỮ LIỆU TRONG CỬA SỔ       ║
╚══════════════════════════════════════════════════════════════════════════╝

Cả hai vế đều cần, và vế thứ hai là vế rẻ:

* Chỉ "ZSET rỗng" thì mọi request của một người chưa tiêu gì (người mới, hoặc
  người vừa nghỉ hơn 5 giờ) đều kéo theo một lượt đọc cả cửa sổ để nạp lại
  **không** dòng nào.
* Chỉ "Postgres có dữ liệu" thì mỗi request là một lượt ghi đè toàn bộ ZSET —
  đúng nhưng vô nghĩa, và nó biến một phép sửa hiếm thành một phép chạy nóng.

`has_events_since` (một `LIMIT 1`) là cửa vào, `list_since` là phần đắt, và
thứ tự ấy giữ cho ca thường — ZSET rỗng vì người ta thật sự chưa tiêu gì —
chỉ tốn một câu truy vấn trả về không hàng nào.

**Không** tự gọi khi ZSET *thiếu một phần*. Không có cách nào rẻ để biết
"thiếu" mà không đếm cả hai kho ở mọi request, và ca mất-một-phần không có
đường đi nào tạo ra nó: Redis mất dữ liệu theo cả khoá (`FLUSHDB`,
`down -v`, hết hạn TTL), không theo từng member. Cần quét toàn bộ thì đó là
việc của lệnh CLI, chạy khi có người bấm.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import LedgerEntry, UsageEventRepository
from app.quota.windows import (
    LimitType,
    Window,
    WindowState,
    encode_member,
    quantize_cost,
    read_window,
    windows,
)

if TYPE_CHECKING:  # pragma: no cover - chỉ dùng cho kiểu
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

#: Bao nhiêu member một lệnh `ZADD` mang theo. DoD dòng 3 đòi 10k dòng sổ dựng
#: xong dưới 2 giây; một `ZADD` cho mỗi dòng là 20 000 vòng đi-về (hai cửa sổ)
#: và chỉ riêng độ trễ mạng đã ăn hết ngân sách ấy.
#:
#: **Không** vào `.env`, khác `QUOTA_WINDOW_*`: A3 cấm hardcode *giới hạn* và
#: *giá* — những con số đổi **kết quả**. Con số này không đổi kết quả của bất
#: cứ thứ gì, chỉ đổi số lệnh dùng để đạt cùng kết quả đó; đặt nó vào `.env`
#: là mời người vận hành chỉnh một thứ họ không có cách nào đo.
ZADD_BATCH = 1000


@dataclass(frozen=True, slots=True)
class WindowRebuild:
    """Kết quả dựng lại MỘT cửa sổ của MỘT người."""

    limit_type: LimitType
    #: Số member đã nạp — bằng số dòng `usage_events` trong cửa sổ.
    members: int
    spent: Decimal


@dataclass(frozen=True, slots=True)
class RebuildReport:
    """Kết quả dựng lại cả hai cửa sổ của MỘT người.

    Trả về thay vì chỉ ghi log: lệnh CLI in nó ra, và test khẳng định vào nó.
    Một hàm chỉ ghi log là một hàm mà phép kiểm duy nhất là đọc chuỗi.
    """

    user_id: uuid.UUID
    windows: tuple[WindowRebuild, ...]

    @property
    def members(self) -> int:
        """Tổng số member đã nạp trên **cả hai** cửa sổ."""
        return sum(w.members for w in self.windows)


def cutoff_at(window: Window, now: float) -> datetime:
    """Biên dưới của cửa sổ, dạng `datetime` để so với `usage_events.created_at`.

    Cùng một biên với `read_window` (`now - window.seconds`), chỉ khác đơn vị:
    Redis so bằng epoch, Postgres so bằng `timestamptz`. Hai chỗ tính biên là
    hai chỗ để lệch, nên biên nằm ở **một** hàm và cả hai đường đi qua nó.

    `UTC` tường minh: container chạy UTC nhưng một `datetime` trần đi vào
    `timestamptz` là một phép so sánh do driver đoán hộ — cùng bài học đã ghi
    ở NQ-50 ⑦ cho bảng giá theo khung giờ.
    """
    return datetime.fromtimestamp(now - window.seconds, tz=UTC)


async def rebuild_quota(
    session: AsyncSession, redis: Redis, *, user_id: uuid.UUID, now: float
) -> RebuildReport:
    """Nạp lại hai ZSET của một người từ `usage_events`. Xem docstring module.

    Không xoá gì, và không tự hỏi "có cần dựng lại không" — nó dựng. Người gọi
    quyết định khi nào: `refill_if_empty` cho đường tự động, `app/cli.py` cho
    đường có người bấm.

    Raise:
        Ngoại lệ của Postgres hoặc Redis đi thẳng ra ngoài, cùng lối
        `read_window`/`add_to_windows`: chỗ gọi mới biết một lần dựng lại hỏng
        có được phép làm hỏng cả request hay không.
    """
    repo = UsageEventRepository(session)
    ket_qua: list[WindowRebuild] = []

    for window in windows():
        entries = await repo.list_since(user_id=user_id, since=cutoff_at(window, now))
        spent = await _nap_lai(redis, window, user_id=user_id, entries=entries)
        ket_qua.append(
            WindowRebuild(limit_type=window.limit_type, members=len(entries), spent=spent)
        )

    report = RebuildReport(user_id=user_id, windows=tuple(ket_qua))
    logger.info(
        "da dung lai quota cua user %s tu usage_events: %s",
        user_id,
        " · ".join(
            f"{w.limit_type.value}={w.members} member/{w.spent} USD" for w in report.windows
        ),
    )
    return report


async def refill_if_empty(
    session: AsyncSession,
    redis: Redis,
    state: WindowState,
    *,
    user_id: uuid.UUID,
    now: float,
) -> WindowState:
    """Cửa sổ rỗng mà Postgres có tiền trong đó ⇒ dựng lại rồi đọc lại.

    Trả về **chính** `state` khi không có gì phải làm, nên chỗ gọi viết được
    một dòng thẳng thay vì một khối `if` của riêng nó.

    Đọc lại sau khi dựng chứ không tự cộng lấy: `read_window` là hàm duy nhất
    biết đọc một cửa sổ (dọn trước, bỏ member hỏng, sắp theo `score` cho
    `retry_after`), và dựng một `WindowState` bằng tay ở đây là bản hiện thực
    thứ hai của đúng thứ đó.
    """
    if state.entries:
        return state
    window = state.window
    repo = UsageEventRepository(session)
    if not await repo.has_events_since(user_id=user_id, since=cutoff_at(window, now)):
        return state

    logger.warning(
        "cua so quota %s cua user %s RONG nhung usage_events co chi tieu trong cua so "
        "— dung lai tu Postgres (RR-7)",
        window.limit_type.value,
        user_id,
    )
    await rebuild_quota(session, redis, user_id=user_id, now=now)
    return await read_window(redis, window, user_id=user_id, now=now)


async def rebuild_all(session: AsyncSession, redis: Redis, *, now: float) -> list[RebuildReport]:
    """Dựng lại cho **mọi** người có chi tiêu trong cửa sổ dài — lệnh CLI `--all`.

    Cửa sổ **dài** quyết định tập người: nó chứa cửa sổ ngắn, nên một người
    không có dòng sổ nào trong 7 ngày thì cũng không có dòng nào trong 5 giờ.

    Một session cho tất cả, chạy tuần tự: với 15–20 người dùng (R1) thì song
    song chỉ thêm một pool kết nối để tiết kiệm vài chục mili giây, mà thứ
    đáng giá ở một lệnh vận hành chạy tay là log đọc được theo thứ tự.
    """
    _, cua_so_dai = windows()
    repo = UsageEventRepository(session)
    user_ids = await repo.user_ids_since(since=cutoff_at(cua_so_dai, now))
    logger.info("rebuild-quota --all: %d nguoi co chi tieu trong cua so dai", len(user_ids))
    return [await rebuild_quota(session, redis, user_id=user_id, now=now) for user_id in user_ids]


# ─────────────────────────── phần trong của file ───────────────────────────


async def _nap_lai(
    redis: Redis,
    window: Window,
    *,
    user_id: uuid.UUID,
    entries: Sequence[LedgerEntry],
) -> Decimal:
    """`ZADD` theo lô rồi `EXPIRE`. Trả về tổng tiền đã nạp.

    `quantize_cost` trước khi `encode_member`, đúng như đường ghi của T-2.12:
    `NUMERIC(12,6)` về tới đây vốn đã sáu chữ số nên phép này không đổi gì —
    nhưng gọi nó vẫn rẻ hơn là để hai đường ghi vào **cùng một** ZSET đi qua
    hai luật làm tròn khác nhau (xem `windows.quantize_cost`).

    Không hàng nào ⇒ **không** tạo khoá và **không** đặt TTL: một khoá rỗng
    khác một khoá không tồn tại ở đúng một chỗ có người đọc — phép đo
    `redis-cli --scan --pattern 'quota:*'` của DoD T-2.12.
    """
    if not entries:
        return Decimal(0)

    key = window.key(user_id)
    tong = Decimal(0)
    for i in range(0, len(entries), ZADD_BATCH):
        lo: dict[str, float] = {}
        for entry in entries[i : i + ZADD_BATCH]:
            cost = quantize_cost(entry.cost_usd)
            tong += cost
            lo[encode_member(entry.id, cost)] = entry.created_at.timestamp()
        await redis.zadd(key, lo)

    # Cùng TTL với `add_to_windows` (nửa (b) của B-156), vì cùng một lý lẽ:
    # mọi member đều có `score <= now`, nên sau đúng một độ dài cửa sổ kể từ
    # lần ghi cuối thì không member nào còn nằm trong cửa sổ.
    await redis.expire(key, window.seconds)
    return tong
