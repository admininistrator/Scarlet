"""Rate limit của §10.6 — ba trong bốn lớp của bảng đó sống trong file này.

KH tham chiếu: §10.6, §18.1, §11.5, §10.3 · CLAUDE.md A3, A4 · tasks.md
B-127, B-131, B-133, B-85, T-2.5, T-2.9.

§10.6 tách rõ hai thứ hay bị gộp: **quota** giới hạn *tiền*, **rate limit** giới
hạn *tần suất*. Bảng của nó có bốn lớp; lớp đầu là `limit_req_zone` của Nginx,
ba lớp còn lại ở đây:

    | API | theo user + nhóm route      | chat: 20/phút · auth: 5/phút …   |
    | API | theo IP cho route chưa login | đăng ký: 3/giờ · quên mật khẩu: 3/giờ |
    | Đồng thời | theo user             | tối đa MAX_CONCURRENT_STREAMS=3  |

Ba lớp, ba cơ chế khác nhau, và khác biệt giữa chúng là chủ ý:

* **Cửa sổ cố định** (`INCR` + `EXPIRE NX`) cho lớp theo IP — T-2.5, phần đầu.
* **Token bucket bằng Lua** cho lớp theo user — T-2.9, phần giữa.
* **ZSET ghế bận + đối chiếu Postgres** cho trần đồng thời — T-2.9, phần cuối.

Chúng **chồng lên nhau**, không thay nhau: một request `POST .../messages` đi
qua cả token bucket (bấm quá nhanh) lẫn trần đồng thời (ba câu trả lời cùng
chảy), và hai câu trả lời `429` của chúng nói hai chuyện khác nhau.

┌──────────────────────────────────────────────────────────────────────────┐
│  LỚP THEO IP — route chưa đăng nhập (T-2.5, B-127, B-131, B-133)         │
└──────────────────────────────────────────────────────────────────────────┘

**Vì sao theo IP chứ không theo user.** Bốn route dùng lớp này —
`register`, `resend-verification`, `forgot-password`, `reset-password` — đều
chạy khi *chưa* có ai đăng nhập, và `logout` thì cố ý không đòi xác thực
(NQ-42). Không có `user_id` để đếm theo. Vì vậy nhóm `auth` của hàng "theo
user" trong §10.6 được **thực thi trên trục IP** ở đây (5/phút, NQ-43) chứ
không lặp lại một lần nữa ở lớp token bucket bên dưới: đếm hai lần cùng một
thứ là hai chỗ để lệch, mà cái thứ hai thì không có gì để đếm.

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
import math
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Final

from fastapi import Depends, Request, Response, status

from app.config.settings import settings
from app.core.deps import get_current_user_id
from app.core.errors import ApiError, ApiErrorCode
from app.core.redis import get_redis

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from app.db.repositories import MessageRepository

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

#: Tên nhóm của lớp theo IP — **là tên route**, xem `ip_key`. Thành hằng ở
#: B-188 chứ không còn là năm chuỗi gõ tay trong `api/v1/auth.py`, vì từ nay có
#: **hai** người đọc chúng: `Depends(...)` lúc chạy, và `python -m app.cli
#: reset-rate-limit` lúc vận hành. Một chuỗi gõ lệch giữa hai bên cho ra một
#: lệnh xoá đúng cú pháp, chạy xong, in "0 khoá" — và người vận hành đọc nó
#: thành "hạn mức đã hết hạn rồi" chứ không thành "tôi gõ sai tên route". Đó
#: đúng là triệu chứng B-188 ghi lại, chỉ lùi thêm một bước.
ROUTE_REGISTER = "register"
ROUTE_RESEND_VERIFICATION = "resend-verification"
ROUTE_FORGOT_PASSWORD = "forgot-password"
ROUTE_RESET_PASSWORD = "reset-password"
ROUTE_LOGOUT = "logout"

#: Mọi nhóm hợp lệ của trục IP. `app/cli.py` dùng nó để từ chối một tên gõ sai
#: **trước** khi chạm tới Redis; `tests/core/test_ratelimit.py` dùng nó để canh
#: rằng `api/v1/auth.py` không thêm một route thứ sáu bằng chuỗi gõ tay.
NHOM_THEO_IP: Final[tuple[str, ...]] = (
    ROUTE_REGISTER,
    ROUTE_RESEND_VERIFICATION,
    ROUTE_FORGOT_PASSWORD,
    ROUTE_RESET_PASSWORD,
    ROUTE_LOGOUT,
)


def ip_key(nhom: str, ip: str) -> str:
    """Khoá đếm của một (nhóm route, IP).

    `nhom` là **tên route**, không phải tên chính sách: §10.6 cho đăng ký và
    quên-mật-khẩu mỗi thứ một hạn mức riêng 3/giờ, tức hai bộ đếm riêng. Dùng
    chung một xô cho mọi route cùng chính sách sẽ làm một người vừa xin gửi lại
    thư xác thực không xin được link đặt lại mật khẩu.
    """
    return f"{RL_IP_PREFIX}{nhom}:{ip}"


def mau_khoa_ip(nhom: str) -> str:
    """Mẫu `SCAN` phủ **mọi** IP của một nhóm — `rl:ip:register:*` (B-188).

    Tồn tại vì đường vận hành thật thiếu đúng một mẩu dữ liệu: người chạy DoD
    biết mình vừa bị `429` ở route nào, nhưng **không** biết IP mà Nginx gắn
    cho mình (`X-Real-IP` là địa chỉ của host trong network `internal`, không
    phải thứ đọc được từ trình duyệt). Bắt họ tra IP ra trước khi xoá được một
    bộ đếm là để nguyên phân nửa của B-188.

    Là một hàm chứ không một chuỗi nối tại chỗ, cùng luật với `ip_key`: chỗ
    duy nhất biết hình dạng khoá vẫn là file này.
    """
    return f"{RL_IP_PREFIX}{nhom}:*"


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


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  LỚP THEO USER — token bucket bằng Lua (§10.6 hàng 2, T-2.9)             ║
# ╚══════════════════════════════════════════════════════════════════════════╝
#
# Cạm bẫy của chính task: *"làm `GET` rồi `SET` trong Python thay vì Lua = race
# condition. Dưới tải, hạn mức sẽ bị vượt và bug này rất khó tái hiện."*
#
# Vì sao **token bucket** ở đây mà **cửa sổ cố định** ở lớp trên: lớp theo IP
# trả lời "trong một giờ, IP này gọi mấy lần" — một con số. Lớp theo user trả
# lời một câu khác: "được bùng phát bao nhiêu, rồi hồi lại với tốc độ nào".
# Người dùng thật gõ theo cụm: năm câu hỏi liên tiếp rồi im mười phút. Xô cho
# cả cụm đi qua miễn là *trung bình* vẫn trong hạn mức, và nó hồi lại từng
# token một chứ không mở toang ở ranh giới phút — tức không có khe biên "20
# cuối phút này + 20 đầu phút sau" mà lớp theo IP chấp nhận.

#: Tiền tố khoá lớp theo user. Cùng luật với `RL_IP_PREFIX`: không ai tự nối
#: chuỗi. Khoá mang **tên nhóm** chứ không tên route — §10.6 xếp hạn mức theo
#: *nhóm*, nên ba route sinh chữ dùng chung một xô. Tách thành ba xô riêng sẽ
#: cho một người 60 lượt mỗi phút chỉ bằng cách xen kẽ ba endpoint.
RL_USER_PREFIX = "rl:user:"

#: Nhóm route của §10.6. `auth` không có mặt ở đây — nó chạy trên trục IP
#: (`gioi_han_auth`, NQ-43); `upload` chưa có endpoint nào tới Phase 4 (B-148).
#: Khai một nhóm rỗng chỉ để cho đủ bảng là dựng một nút vặn không ai xoay
#: được, và là đúng thứ A10 gọi tên.
GROUP_CHAT = "chat"

#: Ba header của §10.6 ("header `X-RateLimit-*` + `Retry-After`").
#: `X-RateLimit-Reset` tính bằng **số giây còn lại tới khi xô đầy lại**, không
#: phải một mốc epoch: FE không phải tin đồng hồ của server mới dùng được nó,
#: và đó cũng là dạng của `Retry-After` ngay bên cạnh.
HEADER_LIMIT = "X-RateLimit-Limit"
HEADER_REMAINING = "X-RateLimit-Remaining"
HEADER_RESET = "X-RateLimit-Reset"
HEADER_RETRY_AFTER = "Retry-After"

#: Giá một request. Một hằng có tên chứ không một số 1 rải trong lời gọi: §10.2
#: đã có một đường "request đắt hơn request khác" (quota theo USD), và nếu có
#: ngày rate limit cũng cần thế thì chỗ sửa phải là một chỗ.
COST_MOI_REQUEST = 1

#: Token bucket, chạy **nguyên tử** trong Redis — không có khe nào giữa đọc và
#: ghi cho một request thứ hai chen vào (DoD T-2.9 dòng 2).
#:
#: Trạng thái là một hash hai trường: `tokens` (số token còn lại lúc `ts`) và
#: `ts` (lần chạm cuối, epoch giây). Nạp lại tính **lười** — không có tiến
#: trình nền nào rót token vào xô, mỗi lượt gọi tự tính "từ `ts` tới giờ trôi
#: bao lâu, nhân tốc độ nạp". Xô chưa từng tồn tại = xô đầy.
#:
#: `now` truyền từ Python chứ không gọi `redis.call('TIME')`: một script không
#: đọc đồng hồ là một script **kiểm được** — test đẩy `now` tới trước để đo
#: phần nạp lại mà không phải `sleep` thật. Cái giá là lệch đồng hồ giữa nhiều
#: tiến trình `api`; hôm nay chỉ có một, và nếu có nhiều thì chúng cùng máy.
#:
#: TTL đặt đúng bằng `window`: xô rỗng nạp đầy lại mất đúng chừng ấy giây, mà
#: một xô đầy thì không khác gì một xô chưa tồn tại — xoá đi không mất thông
#: tin nào. Đặt lại ở **mọi** lượt nên khoá không bao giờ sống mãi.
#:
#: Trả về bốn số nguyên. Redis cắt phần thập phân của số Lua, nên hai đại lượng
#: thời gian đi ra bằng **mili-giây** và `math.ceil` ở phía Lua: `retry_after`
#: 3.2 s mà làm tròn xuống 3 s là bảo client thử lại vào đúng lúc còn bị chặn.
LUA_TOKEN_BUCKET = """
local key      = KEYS[1]
local capacity = tonumber(ARGV[1])
local window   = tonumber(ARGV[2])
local now      = tonumber(ARGV[3])
local cost     = tonumber(ARGV[4])

local rate = capacity / window

local state  = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(state[1])
local ts     = tonumber(state[2])
if tokens == nil or ts == nil then
  tokens = capacity
  ts     = now
end

local delta = now - ts
if delta < 0 then delta = 0 end
tokens = math.min(capacity, tokens + delta * rate)

local allowed        = 0
local retry_after_ms = 0
if tokens >= cost then
  tokens  = tokens - cost
  allowed = 1
else
  retry_after_ms = math.ceil(((cost - tokens) / rate) * 1000)
end

redis.call('HSET', key, 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', key, math.ceil(window))

local reset_ms = math.ceil(((capacity - tokens) / rate) * 1000)
return {allowed, math.floor(tokens), retry_after_ms, reset_ms}
"""


def user_key(group: str, user_id: uuid.UUID) -> str:
    """Khoá xô của một (nhóm route, user) — `rl:user:chat:{uuid}`."""
    return f"{RL_USER_PREFIX}{group}:{user_id}"


def mau_khoa_user(group: str) -> str:
    """Mẫu `SCAN` phủ mọi user của một nhóm — `rl:user:chat:*` (B-188).

    Cặp với `mau_khoa_ip`; xem docstring bên ấy cho lý do tồn tại.
    """
    return f"{RL_USER_PREFIX}{group}:*"


@dataclass(frozen=True, slots=True)
class KetQuaXo:
    """Một lượt lấy token. `retry_after_s` chỉ có nghĩa khi `allowed` là `False`."""

    allowed: bool
    limit: int
    remaining: int
    retry_after_s: int
    reset_s: int

    def headers(self) -> dict[str, str]:
        """Ba header `X-RateLimit-*`, cộng `Retry-After` khi đã bị chặn."""
        them = {HEADER_RETRY_AFTER: str(self.retry_after_s)} if not self.allowed else {}
        return {
            HEADER_LIMIT: str(self.limit),
            HEADER_REMAINING: str(self.remaining),
            HEADER_RESET: str(self.reset_s),
            **them,
        }


def _giay_len(milli: int) -> int:
    """ms -> giây, làm tròn **lên**, tối thiểu 1.

    `Retry-After` của HTTP là số giây nguyên. Làm tròn xuống là mời client thử
    lại vào đúng lúc vẫn còn bị chặn; `0` thì tệ hơn — nó nghĩa là "thử ngay
    đi", tức một vòng lặp bận.
    """
    return max(1, math.ceil(milli / 1000))


async def take_token(
    redis: Redis, key: str, *, capacity: int, window_s: int, now: float
) -> KetQuaXo:
    """Lấy một token khỏi xô `key`. Ngoại lệ của Redis **không** bị nuốt ở đây.

    Cùng lối `dem_va_kiem` của lớp theo IP: chỗ gọi mới biết phải trả lời người
    dùng thế nào.
    """
    # Mọi ARGV đi bằng **chuỗi**: đó là thứ duy nhất giao thức Redis mang
    # được, `tonumber()` phía Lua bóc lại, và nó giữ nguyên phần thập phân của
    # `now` — thứ một `int` sẽ cắt mất, biến mọi phép nạp lại dưới một giây
    # thành 0.
    allowed, remaining, retry_after_ms, reset_ms = await redis.eval(  # type: ignore[misc]
        LUA_TOKEN_BUCKET,
        1,
        key,
        str(capacity),
        str(window_s),
        repr(now),
        str(COST_MOI_REQUEST),
    )
    return KetQuaXo(
        allowed=bool(allowed),
        limit=capacity,
        remaining=int(remaining),
        retry_after_s=_giay_len(int(retry_after_ms)) if not allowed else 0,
        reset_s=_giay_len(int(reset_ms)),
    )


def gioi_han_theo_user(
    group: str, *, doc_gioi_han: Callable[[], int]
) -> Callable[..., Awaitable[None]]:
    """Dựng dependency token bucket cho một nhóm route của §10.6.

    `doc_gioi_han` là một hàm chứ không phải một số — cùng lý do đã ghi ở
    `_dung_dependency` của lớp theo IP: hạn mức là cấu hình (A3), đọc lúc
    **gọi**, nên một test hạ nó xuống 1 thấy hiệu lực ngay.

    Gắn ở **từng route sinh chữ** (`api/v1/messages.py`), không ở
    `include_router`: nhóm `chat` của §10.6 là ba route TỐN TIỀN, còn router
    `conversations` có cả `GET /conversations` mà FE gọi mỗi lần mở trang —
    20/phút cho *mọi* thao tác chat sẽ chặn đúng những request không tốn gì.
    Đây cũng là chỗ `require_chat_access` (T-2.7) đứng, và hai luật đi cùng
    nhau không phải tình cờ: chúng bảo vệ đúng một tập ba route.
    """

    async def kiem_han_muc(
        response: Response,
        user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    ) -> None:
        gioi_han = doc_gioi_han()
        key = user_key(group, user_id)
        try:
            ket_qua = await take_token(
                get_redis(),
                key,
                capacity=gioi_han,
                window_s=CUA_SO_PHUT_S,
                now=time.time(),
            )
        except Exception as loi:
            logger.exception("khong chay duoc token bucket cho %s", key)
            # Cùng lý lẽ đã chốt bốn lần (`core/deps.py`, `core/blacklist.py`,
            # `core/idempotency.py`, và lớp theo IP ngay trên): không hỏi được
            # Redis nghĩa là KHÔNG BIẾT người này đã gọi mấy lần, và cho qua là
            # gỡ đúng lớp phòng thủ vào lúc hệ thống đang hỏng.
            raise ApiError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                ApiErrorCode.SERVICE_UNAVAILABLE,
                "khong kiem duoc han muc goi, hay thu lai",
            ) from loi

        if not ket_qua.allowed:
            logger.warning(
                "rate limit theo user: %s het token, tran %d moi %d giay",
                key,
                gioi_han,
                CUA_SO_PHUT_S,
            )
            raise ApiError(
                status.HTTP_429_TOO_MANY_REQUESTS,
                ApiErrorCode.RATE_LIMITED,
                "goi qua nhieu lan, hay thu lai sau",
                details={"retry_after": ket_qua.retry_after_s, "limit": gioi_han},
                headers=ket_qua.headers(),
            )

        # Header trên response THÀNH CÔNG: `Response` do FastAPI tiêm vào
        # dependency là cùng object mà nó gom header sang response cuối cùng,
        # miễn là handler trả về một *model* chứ không tự dựng `Response` —
        # đúng hình dạng của cả ba route sinh chữ (§18.2 trả `202` + JSON).
        # Không có phần này thì FE chỉ biết mình sắp hết hạn mức vào đúng lúc
        # đã hết.
        response.headers.update(ket_qua.headers())

    return kiem_han_muc


def gioi_han_chat() -> Callable[..., Awaitable[None]]:
    """20/phút theo user cho ba route SINH CHỮ (§10.6, nhóm `chat`)."""
    return gioi_han_theo_user(GROUP_CHAT, doc_gioi_han=lambda: settings.RATE_LIMIT_CHAT_PER_MIN)


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  TRẦN ĐỒNG THỜI — MAX_CONCURRENT_STREAMS (§10.6 hàng 4, T-2.9, B-85)     ║
# ╚══════════════════════════════════════════════════════════════════════════╝
#
# §10.6: "tối đa `MAX_CONCURRENT_STREAMS=3` **message đang `streaming`**".
#
# ┌──────────────────────────────────────────────────────────────────────────┐
# │  ĐẾM LƯỢT SINH, KHÔNG ĐẾM KẾT NỐI SSE                                    │
# └──────────────────────────────────────────────────────────────────────────┘
#
# B-85 để ngỏ hai cách đọc và người dùng đã chốt cách thứ nhất (NQ-49): thứ bị
# giới hạn là số **lượt sinh chưa khép** (`queued`/`streaming`) của một người,
# chặn ở ba route sinh chữ. `GET /messages/{id}/stream` **không** đếm gì cả.
#
# Ngả kia — đếm kết nối SSE — chặn đúng thứ §7 cố ý cho phép: ADR-01 từ chối
# consumer group để hai tab cùng đọc được một stream, và UC-03 là "F5 giữa lúc
# đang stream". Trần 3 kết nối nghĩa là tab thứ tư của cùng một hội thoại nhận
# `429`, và một chuỗi F5 nhanh tự khoá chính mình vì kết nối cũ chỉ được phát
# hiện đứt ở nhịp `: ping` kế tiếp (<= `STREAM_HEARTBEAT_S`). Thứ khan hiếm
# thật là worker và tiền, không phải tab.
#
# ┌──────────────────────────────────────────────────────────────────────────┐
# │  REDIS GIỮ GHẾ, POSTGRES NÓI GHẾ CÒN BẬN KHÔNG                           │
# └──────────────────────────────────────────────────────────────────────────┘
#
# B-85 hỏi thẳng "đếm ở đâu", và loại sẵn một đáp án: "biến trong tiến trình
# `api` sẽ sai ngay khi có replica thứ hai". Nên: một ZSET cho mỗi user,
# member = `message_id`, score = lúc nhận ghế.
#
# Câu khó hơn là **ai nhả ghế**. Lượt sinh khép lại trong `worker`, không phải
# trong `api` — nên ngả hiển nhiên là bắt `workers/generate.py` gọi `ZREM`. Đó
# là ngả **không** chọn, vì ba lý do:
#
#   ① Worker chết giữa chừng thì không ai nhả, ghế treo tới TTL. Reaper §7.6
#      sẽ phải nhả hộ, tức luật sống ở hai nơi — và chỗ thứ hai là chỗ quên.
#   ② `messages` không có cột `user_id` (Phụ lục A), nên worker phải JOIN sang
#      `conversations` chỉ để biết ghế nằm ở khoá nào.
#   ③ Ghế bị bỏ quên **không tự khai**: nó chỉ hiện ra khi một người dùng thật
#      bị chặn nhầm, và lúc đó không còn dấu vết nào để truy.
#
# Ngả đã chọn là **đối chiếu ngược**: `api` hỏi Postgres "trong các ghế đang
# bận, cái nào thật sự còn `queued`/`streaming`" ngay trước khi cấp ghế mới.
# Đúng luật §10.3 ("Redis là cache, Postgres là sự thật"), và nó tự lành trước
# mọi cách hỏng — worker chết, job bị arq cắt, `docker compose down` giữa
# chừng, hay một hàng `messages` bị sửa tay.
#
# Phép đối chiếu **chỉ chạy khi ghế đã đầy**, nên đường đi thường (0–2 ghế) là
# đúng một lệnh Redis, không có truy vấn Postgres nào.
#
# ┌──────────────────────────────────────────────────────────────────────────┐
# │  VÌ SAO CÓ `PHANTOM_GRACE_S`                                             │
# └──────────────────────────────────────────────────────────────────────────┘
#
# Ghế được nhận **bên trong** transaction đã ghi hàng `messages`, trước
# `commit()` — bắt buộc, vì `message_id` chỉ tồn tại sau `INSERT`, còn từ chối
# *sau* `commit()` thì đã muộn (hàng đã ghi, job đã đẩy).
#
# Hệ quả: có một khe vài mili-giây trong đó ghế đã nằm trong Redis mà Postgres
# thì chưa thấy hàng nào. Một request song song đối chiếu đúng lúc ấy sẽ kết
# luận "ghế này trỏ vào hư không" và nhả nó — tức cho lượt thứ tư đi qua, đúng
# cái đua mà DoD dòng 2 bắt phải không có.
#
# Vì vậy luật nhả có **hai vế**, không phải một:
#
#   * ghế mà Postgres BIẾT và đã khép  -> nhả **ngay**, bất kể mới hay cũ (đây
#     là vế làm DoD dòng 4 chạy: một lượt xong là ghế trống ngay lập tức)
#   * ghế mà Postgres CHƯA TỪNG NGHE TỚI -> chỉ nhả khi quá `PHANTOM_GRACE_S`
#     (đủ lâu để mọi `commit()` lành mạnh đã xong; ngắn đủ để một transaction
#     rollback không khoá người dùng cả buổi)

#: Tiền tố ZSET ghế bận. Cùng luật với `RL_IP_PREFIX`/`RL_USER_PREFIX`.
RL_STREAMS_PREFIX = "rl:streams:"

#: Bao lâu thì một ghế trỏ vào `message_id` Postgres chưa từng thấy bị coi là
#: rác. Đây **không** phải một nút vặn vận hành mà là biên an toàn của một
#: transaction — cùng loại `CLAIM_ATTEMPTS` (`core/idempotency.py`) và
#: `KIEM_HUY_MOI_N_CHUNK` (`workers/generate.py`), nên nó ở đây chứ không
#: trong `.env`. 60 giây: một `INSERT` + `enqueue` + `commit` lành mạnh mất
#: mili-giây, nên biên này rộng gấp hàng nghìn lần thứ nó phải phủ.
PHANTOM_GRACE_S = 60


def _tuoi_toi_da_ghe() -> int:
    """Trần tuổi tuyệt đối của một ghế, và cũng là TTL của khoá.

    **Suy ra** từ hai giới hạn đã có chứ không phải một biến `.env` thứ ba:
    một lượt sinh sống lâu nhất có thể là `REAPER_QUEUED_STALE_S` giây nằm
    trong hàng đợi rồi `GENERATE_TIMEOUT_S` giây sinh chữ — quá mốc đó thì
    reaper §7.6 đã đánh dấu nó chết từ lâu. Đây là lưới cuối, không phải đường
    nhả chính.
    """
    return settings.REAPER_QUEUED_STALE_S + settings.GENERATE_TIMEOUT_S


#: Nhận một ghế, **nguyên tử**. Phần "ghế nào đã khép" do Python tính (nó phải
#: hỏi Postgres) và truyền vào từ `ARGV[5]` trở đi; phần đếm-và-cấp chạy trọn
#: trong Redis, nên hai request song song của cùng một người không thể cùng
#: thấy "còn chỗ".
#:
#: `ZSCORE` trước khi cấp: cùng một `message_id` xin ghế hai lần (một lần thử
#: lại sau khi transaction cũ rollback) phải là **cùng một ghế**, không phải
#: hai — nếu không, ba lần thử lại là hết ghế của chính mình.
LUA_GIU_GHE = """
local key     = KEYS[1]
local limit   = tonumber(ARGV[1])
local now     = tonumber(ARGV[2])
local max_age = tonumber(ARGV[3])
local member  = ARGV[4]

for i = 5, #ARGV do
  redis.call('ZREM', key, ARGV[i])
end
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - max_age)

if redis.call('ZSCORE', key, member) then
  redis.call('EXPIRE', key, max_age)
  return {1, redis.call('ZCARD', key)}
end

local active = redis.call('ZCARD', key)
if active >= limit then
  return {0, active}
end

redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, max_age)
return {1, active + 1}
"""


def stream_slot_key(user_id: uuid.UUID) -> str:
    """ZSET ghế bận của một user — `rl:streams:{uuid}`."""
    return f"{RL_STREAMS_PREFIX}{user_id}"


def _uuid_hoac_none(raw: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


async def _ghe_can_nha(
    messages: MessageRepository,
    *,
    user_id: uuid.UUID,
    members: Sequence[tuple[str, float]],
    now: float,
) -> list[str]:
    """Trong các ghế đang bận, cái nào nhả được — xem mục `PHANTOM_GRACE_S`.

    `members` là `(member, score)` lấy từ ZSET; score là lúc nhận ghế.
    """
    theo_uuid = {raw: _uuid_hoac_none(raw) for raw, _ in members}
    hop_le = [mid for mid in theo_uuid.values() if mid is not None]
    trang_thai = await messages.generation_states(hop_le, user_id=user_id)

    can_nha: list[str] = []
    for raw, score in members:
        mid = theo_uuid[raw]
        if mid is None:
            # Không phải UUID ⇒ không thể là một `message_id`. Chưa đường nào
            # ghi được thứ như vậy, nên nếu có thì đó là rác — nhả ngay.
            can_nha.append(raw)
        elif mid in trang_thai.in_flight:
            continue
        elif mid in trang_thai.known or (now - score) >= PHANTOM_GRACE_S:
            can_nha.append(raw)
    return can_nha


def _redis_khong_hoi_duoc(key: str) -> ApiError:
    logger.exception("khong hoi duoc redis cho tran dong thoi %s", key)
    return ApiError(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        ApiErrorCode.SERVICE_UNAVAILABLE,
        "khong kiem duoc so luot sinh dang chay, hay thu lai",
    )


async def nhan_ghe_sinh(
    messages: MessageRepository, *, user_id: uuid.UUID, message_id: uuid.UUID
) -> None:
    """Giữ một ghế cho lượt sinh `message_id`, hoặc `429 TOO_MANY_STREAMS`.

    Gọi **trong** transaction đã ghi hàng `messages`, ngay trước khi đẩy job:
    ném từ đây làm cả transaction rollback, nên một lượt bị từ chối không để
    lại hàng nào trong Postgres và không có job nào trong hàng đợi.

    Raise:
        ApiError 429 `TOO_MANY_STREAMS`: đã đủ `MAX_CONCURRENT_STREAMS` lượt.
        ApiError 503 `SERVICE_UNAVAILABLE`: không hỏi được Redis.
    """
    redis = get_redis()
    key = stream_slot_key(user_id)
    gioi_han = settings.MAX_CONCURRENT_STREAMS
    max_age = _tuoi_toi_da_ghe()
    now = time.time()

    try:
        dang_ban: Sequence[tuple[str, float]] = await redis.zrange(key, 0, -1, withscores=True)
    except Exception as loi:
        raise _redis_khong_hoi_duoc(key) from loi

    # Chỉ hỏi Postgres khi ghế đã đầy. Đường đi thường không tốn truy vấn nào,
    # và một ghế đã khép nằm lại thêm một lượt là vô hại: lượt nào chạm trần
    # cũng dọn nó trước khi trả lời.
    can_nha = (
        await _ghe_can_nha(messages, user_id=user_id, members=dang_ban, now=now)
        if len(dang_ban) >= gioi_han
        else []
    )

    try:
        cho_phep, dang_chay = await redis.eval(  # type: ignore[misc]
            LUA_GIU_GHE,
            1,
            key,
            str(gioi_han),
            repr(now),
            str(max_age),
            str(message_id),
            *can_nha,
        )
    except Exception as loi:
        raise _redis_khong_hoi_duoc(key) from loi

    if not cho_phep:
        logger.warning(
            "tran dong thoi: user %s dang co %d luot sinh chua khep (tran %d)",
            user_id,
            int(dang_chay),
            gioi_han,
        )
        raise ApiError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            ApiErrorCode.TOO_MANY_STREAMS,
            "dang co qua nhieu cau tra loi cung luc, hay doi mot cai xong",
            details={"limit": gioi_han, "active": int(dang_chay)},
        )


async def nha_ghe_sinh(*, user_id: uuid.UUID, message_id: uuid.UUID) -> None:
    """Trả ghế ngay — dùng khi transaction vừa giữ ghế sẽ rollback.

    Nuốt mọi lỗi và chỉ ghi log: đây là đường **dọn dẹp**, và ném ở đây sẽ
    thay một `503 ENQUEUE_FAILED` (câu đúng: job không vào được hàng đợi) bằng
    một câu nói về Redis mà người dùng không làm gì được. Ghế không nhả được
    cũng không kẹt vĩnh viễn — phép đối chiếu Postgres dọn nó ở lượt sau.
    """
    try:
        await get_redis().zrem(stream_slot_key(user_id), str(message_id))
    except Exception:
        logger.exception("khong nha duoc ghe sinh %s cua user %s", message_id, user_id)
