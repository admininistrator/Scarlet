"""Rate limit **theo IP** cho nhóm route chưa đăng nhập (§10.6) — B-127, B-131, T-2.5.

KH tham chiếu: §10.6, §18.1, §11.5 · CLAUDE.md A3, A4 · tasks.md B-127, B-131, T-2.5.

§10.6 tách rõ hai thứ hay bị gộp: **quota** giới hạn *tiền*, **rate limit** giới
hạn *tần suất*. Bảng của nó có bốn lớp; file này là lớp thứ ba:

    | API | theo IP cho route chưa đăng nhập | đăng ký: 3/giờ · quên mật khẩu: 3/giờ |

**Vì sao theo IP chứ không theo user.** Ba route dùng file này —
`resend-verification`, `forgot-password`, `reset-password` — đều chạy khi
*chưa* có ai đăng nhập, và `logout` thì cố ý không đòi xác thực (NQ-42). Không
có `user_id` để đếm theo. Lớp "theo user + nhóm route" của §10.6 (chat 20/phút,
auth 5/phút) là việc của T-2.9 và dùng token bucket; hai lớp chồng lên nhau chứ
không thay nhau.

┌──────────────────────────────────────────────────────────────────────────┐
│  CỬA SỔ CỐ ĐỊNH (INCR + EXPIRE NX), KHÔNG PHẢI TOKEN BUCKET              │
└──────────────────────────────────────────────────────────────────────────┘

§10.6 chỉ định token bucket + Lua cho lớp **theo user**, nơi câu hỏi là "cho
phép bùng phát bao nhiêu rồi hồi lại với tốc độ nào". Lớp theo IP trả lời một
câu đơn giản hơn nhiều — "trong một giờ, IP này được gọi mấy lần" — và một bộ
đếm có TTL trả lời đúng nó bằng hai lệnh Redis, không cần script.

**`EXPIRE ... NX` chứ không `EXPIRE` trần**, và thứ tự là INCR trước:

1. `INCR` tạo khoá với giá trị 1 nếu chưa có — nhưng **không** TTL.
2. `EXPIRE key <cửa sổ> NX` chỉ đặt TTL khi khoá **chưa** có TTL. Gọi ở mọi
   lượt (không chỉ lượt đầu) nên nếu tiến trình chết đúng giữa hai lệnh và để
   lại một khoá không TTL — trường hợp duy nhất mà cặp lệnh không-nguyên-tử
   này hỏng — thì **lượt gọi kế tiếp tự vá**, thay vì khoá vĩnh viễn một IP.
   `EXPIRE` trần thì ngược lại: mỗi lượt gọi đẩy hạn ra xa, nên kẻ tấn công gọi
   liên tục sẽ giữ cửa sổ mở mãi và bộ đếm không bao giờ về 0 — một hạn mức
   "3 mỗi giờ" biến thành "3 mãi mãi".

Cái giá của cửa sổ cố định (so với cửa sổ trượt) là biên: 3 lượt cuối giờ thứ
nhất cộng 3 lượt đầu giờ thứ hai cho 6 lượt trong vài giây. Với mục tiêu ở
đây — chống dò email và chống gửi thư hàng loạt — 6 lá thư trong một khe biên
không đổi bản chất điều gì, và nó không đáng một script Lua để đóng.

┌──────────────────────────────────────────────────────────────────────────┐
│  IP LẤY TỪ `X-Real-IP`, VÀ VÌ SAO TIN ĐƯỢC HEADER ĐÓ                     │
└──────────────────────────────────────────────────────────────────────────┘

`request.client.host` nhìn từ trong container `api` là **IP của Nginx**, không
phải của người gọi — tin nó nghĩa là cả 15–20 người dùng dùng chung một bộ
đếm, và người thứ tư trong giờ bị chặn vì ba người khác.

`config/nginx/nginx.conf` đặt `proxy_set_header X-Real-IP $remote_addr` cho
`location /api/`. `proxy_set_header` **ghi đè** giá trị client gửi lên, nên
header này không giả được — miễn là mọi đường vào đều đi qua Nginx.
`docker-compose.yml` **không** publish cổng nào của service `api` (chỉ `nginx`
giữ `0.0.0.0:443`), nên điều kiện đó đang đúng. Đổi điều đó — publish `api` ra
host, thêm một reverse proxy thứ hai — là mở đường cho một `X-Real-IP` bịa ra
đi thẳng vào đây, và khi ấy hạn mức này vô hiệu **trong im lặng**.

`request.client` vẫn là đường lùi (test qua `ASGITransport`, gọi thẳng `api`
trong mạng nội bộ lúc debug), và cuối cùng là một xô chung `unknown` — thà tất
cả dùng chung một bộ đếm còn hơn không đếm gì.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import Request, status

from app.config.settings import settings
from app.core.errors import ApiError, ApiErrorCode
from app.core.redis import get_redis

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

#: Tiền tố khoá. Cùng luật với `BL_JTI_PREFIX` của `core/blacklist.py` và
#: `cancel_key()` của `streaming/cancel.py`: không ai tự nối chuỗi, vì một
#: tiền tố gõ lệch là một hạn mức không bao giờ chặn ai — và nó không báo lỗi.
RL_IP_PREFIX = "rl:ip:"

#: Header do Nginx đặt (`$remote_addr`) — xem docstring module.
HEADER_IP_THAT = "X-Real-IP"

#: Xô chung cho request không có IP nào đọc được. Một chuỗi cố định chứ không
#: bỏ qua phép đếm: "không biết anh là ai" không phải lý do để được gọi vô hạn.
IP_KHONG_RO = "unknown"

#: Quy đổi đơn vị của chính tên biến `..._PER_HOUR` / `..._PER_MIN` trong
#: `Settings`, **không** phải một nút vặn thứ hai: đổi cửa sổ mà giữ nguyên tên
#: biến là để lại một cái tên nói dối. Vì vậy hai con số này nằm ở đây, còn
#: *hạn mức* (3, 5) — thứ A3 gọi là "giới hạn" — nằm trong `.env`.
CUA_SO_GIO_S = 3600
CUA_SO_PHUT_S = 60


def ip_key(nhom: str, ip: str) -> str:
    """Khoá đếm của một (nhóm route, IP).

    `nhom` là **tên route**, không phải tên chính sách: §10.6 cho đăng ký và
    quên-mật-khẩu mỗi thứ một hạn mức riêng 3/giờ, tức hai bộ đếm riêng. Dùng
    chung một xô cho mọi route cùng chính sách sẽ làm một người vừa xin gửi lại
    thư xác thực không xin được link đặt lại mật khẩu.
    """
    return f"{RL_IP_PREFIX}{nhom}:{ip}"


def dia_chi_ip(request: Request) -> str:
    """IP của người gọi — `X-Real-IP` (Nginx) → `request.client` → `unknown`."""
    header = request.headers.get(HEADER_IP_THAT)
    if header and header.strip():
        return header.strip()
    if request.client is not None and request.client.host:
        return request.client.host
    return IP_KHONG_RO


@dataclass(frozen=True, slots=True)
class KetQuaDem:
    """Kết quả một lượt đếm. `retry_after_s` chỉ có nghĩa khi `vuot` là `True`."""

    so_lan: int
    vuot: bool
    retry_after_s: int


async def dem_va_kiem(redis: Redis, key: str, *, gioi_han: int, cua_so_s: int) -> KetQuaDem:
    """Đếm lượt gọi này rồi trả lời "đã vượt hạn mức chưa".

    Đếm **trước**, không phải sau khi handler chạy xong: thứ cần chặn là *lượt
    thử*, và một lần dò email thất bại cũng là một lần dò.

    Ngoại lệ của Redis **không** bị nuốt ở đây — chỗ gọi mới biết phải trả lời
    người dùng thế nào (cùng lối `bi_chan` của `core/blacklist.py`).
    """
    so_lan = int(await redis.incr(key))
    # Đặt TTL ở MỌI lượt, không chỉ lượt đầu (`nx=True` lo phần "chỉ khi chưa
    # có") — xem docstring module, mục EXPIRE NX.
    await redis.expire(key, cua_so_s, nx=True)
    if so_lan <= gioi_han:
        return KetQuaDem(so_lan=so_lan, vuot=False, retry_after_s=0)

    con_lai = int(await redis.ttl(key))
    # `ttl` trả `-1` (khoá không TTL) hoặc `-2` (khoá vừa hết hạn giữa hai
    # lệnh). Cả hai đều không phải một khoảng chờ hợp lệ để đưa cho client.
    return KetQuaDem(so_lan=so_lan, vuot=True, retry_after_s=max(1, con_lai))


def _dung_dependency(
    nhom: str, *, cua_so_s: int, doc_gioi_han: Callable[[], int]
) -> Callable[[Request], Awaitable[None]]:
    """Dựng một dependency FastAPI cho một (route, chính sách).

    `doc_gioi_han` là một hàm chứ không phải một số vì `Settings` được đọc lúc
    **gọi**, không phải lúc import: hạn mức là cấu hình (A3), và một test hạ
    hạn mức xuống 1 phải thấy hiệu lực mà không cần nạp lại module.
    """

    async def kiem_han_muc(request: Request) -> None:
        gioi_han = doc_gioi_han()
        key = ip_key(nhom, dia_chi_ip(request))
        try:
            ket_qua = await dem_va_kiem(get_redis(), key, gioi_han=gioi_han, cua_so_s=cua_so_s)
        except Exception as loi:
            logger.exception("khong dem duoc rate limit cho %s", key)
            # Cùng lý lẽ với blacklist (`core/deps.py`): không hỏi được Redis
            # nghĩa là KHÔNG BIẾT IP này đã gọi mấy lần, và cho qua là gỡ đúng
            # lớp phòng thủ chống dò email vào lúc hệ thống đang hỏng — tức lúc
            # khó phát hiện nhất. Redis vốn là phụ thuộc cứng của app (A1).
            raise ApiError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                ApiErrorCode.SERVICE_UNAVAILABLE,
                "khong kiem duoc han muc goi, hay thu lai",
            ) from loi

        if ket_qua.vuot:
            logger.warning(
                "rate limit: %s da goi %d lan, tran %d moi %d giay",
                key,
                ket_qua.so_lan,
                gioi_han,
                cua_so_s,
            )
            raise ApiError(
                status.HTTP_429_TOO_MANY_REQUESTS,
                ApiErrorCode.RATE_LIMITED,
                "goi qua nhieu lan, hay thu lai sau",
                details={"retry_after": ket_qua.retry_after_s},
                # Header chuẩn của 429 — `core/errors.py` giữ nguyên `headers`
                # của `ApiError` đúng vì hai ca này (401 `WWW-Authenticate`,
                # 429 `Retry-After`).
                headers={"Retry-After": str(ket_qua.retry_after_s)},
            )

    return kiem_han_muc


def gioi_han_gui_email(nhom: str) -> Callable[[Request], Awaitable[None]]:
    """3/giờ theo IP — route **gửi thư** cho một email người gọi tự nhập.

    §10.6 ("quên mật khẩu: 3/giờ") và §18.1 ("`/auth/resend-verification` —
    Rate limit 3/giờ"). Hai thứ bị chặn ở đây: dò xem email nào đã đăng ký, và
    biến endpoint thành máy gửi thư tới một hộp thư bất kỳ (B-127).
    """
    return _dung_dependency(
        nhom,
        cua_so_s=CUA_SO_GIO_S,
        doc_gioi_han=lambda: settings.RATE_LIMIT_EMAIL_IP_PER_HOUR,
    )


def gioi_han_auth(nhom: str) -> Callable[[Request], Awaitable[None]]:
    """5/phút theo IP — route `/auth/*` **không** gửi thư.

    Con số lấy từ nhóm `auth` của §10.6 ("auth: 5/phút"), đổi trục đếm từ user
    sang IP vì những route này chạy khi chưa có user (B-131).

    Không dùng 3/giờ ở đây, và đó là một khác biệt có chủ ý: `reset-password`
    có thể bị chính người dùng gọi lại vài lần (gõ mật khẩu quá yếu → `422`,
    sửa rồi gửi lại), nên một hạn mức tính bằng giờ sẽ khoá **nạn nhân** ra
    khỏi tài khoản của họ trong một tiếng vì họ gõ sai mật khẩu ba lần.
    """
    return _dung_dependency(
        nhom,
        cua_so_s=CUA_SO_PHUT_S,
        doc_gioi_han=lambda: settings.RATE_LIMIT_AUTH_IP_PER_MIN,
    )
