"""Dependency dùng chung của tầng HTTP (§23 `core/deps.py`).

KH tham chiếu: §18.1, §20, §11.2, §11.3, Phụ lục F · CLAUDE.md A10 ·
tasks.md T-2.3, T-2.4 · B-83, B-114, NQ-36.

╔══════════════════════════════════════════════════════════════════════════╗
║  T-2.4: BLACKLIST — "middleware" của §11.3 nằm ở ĐÂY                     ║
╚══════════════════════════════════════════════════════════════════════════╝

§11.3 gọi nó là "middleware", nhưng chỗ đúng là dependency này chứ không phải
một lớp ASGI như `core/origin.py`: phép kiểm cần `jti` và `iat`, tức cần token
đã **giải mã xong**, và chỗ duy nhất giải mã token là `get_access_claims` ngay
dưới. Một middleware ASGI sẽ phải decode lần thứ hai — hai chỗ cùng biết luật,
và chỗ nào cũng có thể sai một mình.

`get_access_claims` tách ra khỏi `get_current_user_id` vì `POST /auth/logout`
cần **cả claim** (`jti` để chặn, `exp` để tính TTL) chứ không chỉ `user_id`;
`get_current_user_id` nay chỉ còn lấy `user_id` ra khỏi kết quả của nó. Nhánh
tạm Phase 1 không đi qua blacklist và không cần: nó không có token nào để thu
hồi, và nó chỉ sống khi `DEBUG=true`.

**Redis chết ⇒ 503, KHÔNG cho qua.** Cho qua là mở lại đúng C21 ("logout xong
vẫn gọi API được vài phút") với một nguyên nhân mới, và mở nó ra đúng lúc hệ
thống đang hỏng — tức lúc khó phát hiện nhất. Redis vốn đã là phụ thuộc cứng
của app (A1: mọi lượt sinh đi qua stream), nên "Redis chết mà API vẫn phục vụ
được" không phải một trạng thái có thật để bảo vệ. 503 chứ không 401 cũng là
một khác biệt có nghĩa: FE hiểu 503 là "thử lại", còn 401 sẽ đá người dùng ra
màn hình đăng nhập vì một sự cố hạ tầng hoàn toàn không liên quan tới họ.

╔══════════════════════════════════════════════════════════════════════════╗
║  T-2.3: THÊM ĐƯỜNG AUTH THẬT — KHÔNG XOÁ CHỖ TẠM CỦA PHASE 1              ║
╚══════════════════════════════════════════════════════════════════════════╝

NQ-36 chốt: một cookie phiên `HttpOnly; Secure; SameSite=Lax; Path=/api/v1`
mang access JWT (§11.2, BỎ Bearer), và `get_current_user_id` là nơi verify nó.
Đường mới này chạy TRƯỚC mọi thứ, KHÔNG phụ thuộc `DEBUG`: một request có
cookie `scarlet_session` hợp lệ được nhận danh tính bất kể môi trường, vì đây
mới là đường thật của production.

**Vì sao chỗ tạm của Phase 1 (header `X-User-Id` → cookie `scarlet_dev_user`)
vẫn ở nguyên dưới đây, không bị xoá dù docstring cũ của T-1.7 nói "T-2.3 thay
thân hàm này".** Hai lý do, cả hai đều đo được, không phải phỏng đoán:

1. `frontend/src/lib/api.ts` (T-1.14) vẫn tự đặt cookie `scarlet_dev_user` cho
   màn chat thô — NQ-36 tự ghi rõ T-2.3 "không sửa một dòng FE nào", và FE
   chưa có trang đăng nhập thật (đó là việc của Phase 3, xem báo cáo T-2.2).
   Xoá đường cũ mà không thay FE là khoá luôn màn chat thô đang chạy.
2. Sáu file test (`test_conversations.py`, `test_messages.py`,
   `test_messages_cancel.py`, `test_branching.py`, `test_stream.py`, và chính
   `test_auth.py` gián tiếp) dựng danh tính qua fixture `_debug_bat` +
   `X-User-Id`/cookie dev — không thuộc "Việc cần làm" của T-2.3, và xoá đường
   cũ bắt sửa lại toàn bộ, đúng loại việc CLAUDE.md §0.4 dặn "không làm thêm".

Vì vậy thân hàm dưới đây có hai nhánh xếp lớp: cookie phiên thật (mới, luôn
bật) thử trước; vắng mặt thì rơi xuống đúng logic cũ (nguyên văn, vẫn giữ ba
lớp chặn bên dưới) — không đổi một dòng hành vi nào của nhánh cũ. Khi FE có
trang đăng nhập thật (Phase 3), nhánh cũ này mới hết lý do tồn tại; ghi lại
thành Backlog cho lúc đó.

── Phần dưới đây (nhánh Phase 1) giữ nguyên docstring gốc của NQ-24/NQ-33 ──

T-1.7 đã phải kiểm quyền sở hữu ngay từ bây giờ ("message của user khác →
404"), và cả Phase 1 — `scripts/test_resume.py`, `bench_ttft.py`, màn chat thô
của T-1.14 — cần một danh tính để gọi API. Người dùng chốt phương án này trong
phiên T-1.7 (xem Nhật ký quyết định NQ-24).

**Ba thứ giữ cho chỗ tạm này không sống sót sang production:**

1. `DEBUG=false` thì dependency **từ chối mọi request** bằng `503` — không có
   đường nào để một triển khai thật lỡ chạy với nó. `.env.example` để
   `DEBUG=false`, nên mặc định của một máy mới là "đóng".
2. Router **không** biết nó đang đọc header nào. Chúng chỉ viết
   `Depends(get_current_user_id)` và nhận một `UUID`. T-2.3 sửa đúng thân hàm
   dưới đây, không sửa một dòng nào trong `api/v1/*.py`.
3. Hàm **không** kiểm tra user có tồn tại trong bảng `users` hay không, và đó
   là chủ ý: nó không phải xác thực, nó là một chỗ giữ chân. Mọi truy vấn sau
   đó vẫn lọc `user_id` **trong câu SQL** (§20), nên một `X-User-Id` bịa ra chỉ
   thấy được đúng số hội thoại nó sở hữu — tức là không cái nào.

┌──────────────────────────────────────────────────────────────────────────┐
│  VÌ SAO CÓ ĐƯỜNG THỨ HAI: COOKIE  (T-1.14, NQ-33)                        │
└──────────────────────────────────────────────────────────────────────────┘

`EventSource` của trình duyệt **không đặt được header tuỳ chọn** — đó là chỗ
API dừng lại, không phải một thiếu sót của thư viện nào. Cả T-1.7 tới T-1.13
không chạm phải giới hạn đó vì mọi client của chúng là `curl` hoặc `httpx`;
T-1.14 là client đầu tiên **là một trình duyệt**, và §7.4 + Phụ lục F đòi đúng
`EventSource` native để `Last-Event-ID` do trình duyệt tự gửi khi reconnect.

Phụ lục F vốn đã viết sẵn `new EventSource(url, { withCredentials: true })` —
`withCredentials` nói về **cookie**, tức bản thân kế hoạch đã giả định đường
stream xác thực bằng cookie chứ không bằng header. Cookie ở đây là chỗ tạm đi
đúng hình dạng mà auth thật rồi cũng phải đi.

**Header vẫn thắng cookie, và thứ tự đó không phải tuỳ tiện.** Ba script của
Phase 1 (`test_resume.py`, `bench_ttft.py`, mọi `curl` trong DoD) gửi header;
nếu cookie thắng thì một cookie cũ còn sót trong `curl -b` hoặc trong jar của
ai đó sẽ **lặng lẽ** đổi danh tính của phép đo. Ngược lại thì không: header chỉ
có khi người gọi cố ý đặt nó.

**Cookie chỉ được đọc khi header VẮNG MẶT**, và đó là lý do nó khai kiểu `str`
chứ không `uuid.UUID`. Khai `uuid.UUID` thì FastAPI validate **cả hai** tham số
trước khi thân hàm chạy, nên một cookie hỏng (người dùng sửa tay, bản cũ của
một phiên trước) sẽ trả `422` cho cả những request mang header hoàn toàn hợp
lệ — tức làm hỏng `curl` vì một thứ `curl` không gửi.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import Cookie, Depends, Header, status

from app.config.settings import settings
from app.core.access_token import (
    AccessTokenClaims,
    TokenExpiredError,
    TokenInvalidError,
    decode_access_token,
)
from app.core.blacklist import bi_chan
from app.core.errors import ApiError, ApiErrorCode
from app.core.redis import get_redis

logger = logging.getLogger(__name__)

#: Cookie phiên thật (§11.2, T-2.3, NQ-36). `Path=/api/v1` — rộng hơn cookie
#: refresh (`Path=/api/v1/auth`, xem `app/api/v1/auth.py`) vì mọi endpoint
#: dưới `/api/v1` cần đọc được nó, còn refresh chỉ có nghĩa ở `/auth/refresh`.
SESSION_COOKIE_NAME = "scarlet_session"

#: Tên cookie mang danh tính tạm của Phase 1. **Bản sao duy nhất của hằng này
#: nằm ở `frontend/src/lib/api.ts`** (`TEN_COOKIE_DEV`) — hai đầu của một sợi
#: dây, cùng loại với `stream:{id}` giữa producer và consumer. Đổi ở đây mà
#: quên bên kia thì FE im lặng trượt về `401`, nên cả hai chỗ đều trỏ về nhau
#: bằng chú thích.
DEV_USER_COOKIE = "scarlet_dev_user"


async def get_access_claims(
    session_cookie: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> AccessTokenClaims | None:
    """Claim của cookie phiên, đã verify chữ ký + `exp` + blacklist (§11.3).

    Trả `None` khi **không có** cookie phiên — đó không phải lỗi ở đây, vì
    `get_current_user_id` còn nhánh tạm Phase 1 phía sau. Mọi ca khác (cookie
    có mặt nhưng không dùng được) đều raise.

    Raise:
        ApiError 401 `TOKEN_EXPIRED`: đúng chữ ký nhưng đã qua `exp` — khác
            "token sai" để FE (tương lai) thử `/auth/refresh` thay vì đẩy
            thẳng ra màn đăng nhập.
        ApiError 401 `UNAUTHENTICATED`: sai chữ ký/định dạng/thiếu claim.
        ApiError 401 `TOKEN_REVOKED`: còn hạn nhưng đã bị thu hồi (§11.3) —
            logout, đổi mật khẩu, hoặc admin suspend.
        ApiError 503 `SERVICE_UNAVAILABLE`: không hỏi được Redis nên KHÔNG
            biết token có bị thu hồi hay không (xem docstring module).
    """
    if session_cookie is None:
        return None

    try:
        claims = decode_access_token(session_cookie)
    except TokenExpiredError as loi:
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            ApiErrorCode.TOKEN_EXPIRED,
            "access token da het han",
        ) from loi
    except TokenInvalidError as loi:
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            ApiErrorCode.UNAUTHENTICATED,
            "access token khong hop le",
        ) from loi

    try:
        da_bi_thu_hoi = await bi_chan(get_redis(), claims)
    except Exception as loi:
        logger.exception("khong kiem duoc blacklist cho user %s", claims.user_id)
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ApiErrorCode.SERVICE_UNAVAILABLE,
            "khong kiem duoc trang thai phien dang nhap",
        ) from loi

    if da_bi_thu_hoi:
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            ApiErrorCode.TOKEN_REVOKED,
            "phien dang nhap da bi thu hoi, hay dang nhap lai",
        )
    return claims


async def get_current_user_id(
    claims: Annotated[AccessTokenClaims | None, Depends(get_access_claims)] = None,
    x_user_id: Annotated[uuid.UUID | None, Header(alias="X-User-Id")] = None,
    dev_user_cookie: Annotated[str | None, Cookie(alias=DEV_USER_COOKIE)] = None,
) -> uuid.UUID:
    """`user_id` của người gọi.

    Thứ tự: cookie phiên thật `scarlet_session` (§11.2, T-2.3, luôn bật, nay đi
    qua `get_access_claims` ở trên) → chỗ tạm của Phase 1 (header `X-User-Id` →
    cookie `scarlet_dev_user`, DEBUG-only — xem docstring module cho lý do nó
    còn ở đây).

    Raise:
        Mọi lỗi của `get_access_claims` (401 `TOKEN_EXPIRED` /
            `UNAUTHENTICATED` / `TOKEN_REVOKED`, 503 `SERVICE_UNAVAILABLE`).
        ApiError 401 `UNAUTHENTICATED`: (nhánh Phase 1) không có đường nào
            mang danh tính tới.
        ApiError 503 `AUTH_NOT_IMPLEMENTED`: không có cookie phiên VÀ
            `DEBUG=false` — nhánh Phase 1 đóng (xem docstring module).
        ApiError 422 `VALIDATION_ERROR`: (nhánh Phase 1) có cookie dev nhưng
            nó không phải UUID.

    `UNAUTHENTICATED` là mã FE đọc để đẩy người dùng ra màn hình đăng nhập
    (§18, B-86) — cả hai nhánh dưới đây đều giữ đúng mã này cho ca đó.
    """
    if claims is not None:
        return claims.user_id

    # ── nhánh Phase 1 (NQ-24, NQ-33) — NGUYÊN VĂN, xem docstring module ──
    if not settings.DEBUG:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ApiErrorCode.AUTH_NOT_IMPLEMENTED,
            "auth chua duoc hien thuc (tasks.md T-2.3); Phase 1 chi chay voi DEBUG=true",
        )
    if x_user_id is not None:
        return x_user_id
    if dev_user_cookie is None:
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            ApiErrorCode.UNAUTHENTICATED,
            f"thieu header X-User-Id va cookie {DEV_USER_COOKIE} "
            f"(cho tam cua Phase 1, xem app/core/deps.py)",
        )
    try:
        return uuid.UUID(dev_user_cookie)
    except ValueError as loi:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ApiErrorCode.VALIDATION_ERROR,
            f"cookie {DEV_USER_COOKIE} khong phai UUID",
        ) from loi
