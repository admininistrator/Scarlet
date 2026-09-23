"""Dependency dùng chung của tầng HTTP (§23 `core/deps.py`).

KH tham chiếu: §18.1, §20, §11.1, §11.2, §11.3, §10.5, §16.3, UC-01, Phụ lục F ·
CLAUDE.md A10 · tasks.md T-2.3, T-2.4, T-2.7, T-2.16, T-3.1c · B-34, B-83,
B-114, B-128, NQ-36.

**T-2.16 thêm `require_admin` ở CUỐI file** — cùng hình dạng và cùng chỗ gắn
với `require_app_access` (lời gọi `include_router`), khác nó ở đúng một điểm:
câu hỏi của nó là `role`, không phải `status`. Lý do đầy đủ nằm trong docstring
của chính hàm đó.

╔══════════════════════════════════════════════════════════════════════════╗
║  T-2.7: MÁY TRẠNG THÁI TÀI KHOẢN — bảng §11.1 sống ở ĐÚNG MỘT CHỖ        ║
╚══════════════════════════════════════════════════════════════════════════╝

Cạm bẫy của chính task: *"viết `if user.is_active` ở rải rác trong code. Tập
trung vào một dependency, nếu không mỗi endpoint sẽ có một luật khác nhau."*
Vì vậy bốn cột của bảng §11.1 là bốn **hằng số** ngay dưới đây, và mọi chỗ
trong app hỏi "trạng thái này làm được việc kia không" đều đi qua chúng — hai
đường, không có đường thứ ba:

* `require_status(...)` — dependency của FastAPI, gắn ở `api/v1/__init__.py`
  (cả router) và ở từng route sinh chữ trong `api/v1/messages.py`.
* `ensure_status_allowed(...)` — cùng phép kiểm, dạng gọi thẳng, cho chỗ duy
  nhất không có danh tính để `Depends`: `POST /auth/login` (lúc đó chưa có
  token nào — chính nó mới là cái phát hành token).

**Trạng thái đọc từ CLAIM của access token, không phải từ một `SELECT`.**
`app/core/access_token.py` đã ghi sẵn `status` vào JWT từ T-2.3 và nói rõ nó
có mặt "để T-2.7 đọc lại từ payload thay vì phải xin thêm một chuyến SELECT".
Cái giá là một cửa sổ cũ ≤ `ACCESS_TOKEN_TTL_MIN` (15 phút): admin duyệt xong
thì người đó còn chờ hết hạn token mới chat được bằng system key. Chiều nguy
hiểm — admin **khoá** một người mà người đó vẫn chat tiếp — đã có §11.3 đóng:
suspend "như đổi mật khẩu", tức đặt mốc `bl:user:{uid}` và mọi token cũ chết
ngay ở `get_access_claims` phía trên, trước khi phép kiểm trạng thái chạy.

**BYOK là câu hỏi duy nhất phải hỏi Postgres** (§10.5, §11.1): `pending_approval`
chat được **nếu** đã cấu hình khoá riêng — "người đó không tiêu tiền của bạn,
nên không có lý do gì chặn họ". Không claim nào trả lời được (khoá thêm/xoá
giữa hai lần phát hành token), nên có đúng một `SELECT EXISTS` — và nó chỉ
chạy cho đúng trạng thái đó, không phải cho mọi request.

**Không có claim = chưa đăng nhập ⇒ `401`, ở CẢ BA cửa.** Từ T-3.1c,
`get_access_claims` trả `None` chỉ còn đúng một nghĩa: không có cookie phiên
nào. Trước đó nó còn nghĩa thứ hai — "có thể là nhánh danh tính tạm của Phase
1" — và vì nghĩa thứ hai ấy mà `require_status` cùng `get_current_user_status`
cho `None` **đi thẳng qua**. Nhánh tạm chết thì lối đi thẳng ấy không còn gì
để chở, và giữ nó lại là để sẵn một cửa mở cho ngày ai đó thêm một route quên
`get_current_user_id`. Vì vậy cả ba đều dừng ở `401 UNAUTHENTICATED` — `401`
chứ không `403`: chưa chứng minh được mình là ai thì chưa tới lượt hỏi quyền
(cùng câu mà `require_admin` ở cuối file đã viết từ T-2.16).

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
║  T-3.1c: CHỖ TẠM CỦA PHASE 1 ĐÃ BỊ XOÁ                                   ║
╚══════════════════════════════════════════════════════════════════════════╝

NQ-36 chốt đường thật: một cookie phiên `HttpOnly; Secure; SameSite=Lax;
Path=/api/v1` mang access JWT (§11.2, BỎ Bearer), và `get_current_user_id` là
nơi verify nó. Từ T-2.3 tới T-3.1b, đường ấy xếp LỚP lên trên một chỗ tạm của
Phase 1: một header danh tính người gọi tự gõ, rồi một cookie dev riêng, cả
hai chỉ sống khi `DEBUG=true` (NQ-24/NQ-33 — tên chính xác của chúng nằm ở
đó và ở B-128). Cookie phiên thử trước, vắng mặt thì rơi xuống chỗ tạm. NQ-41
giữ chỗ tạm lại **có điều kiện**, và điều kiện ấy viết ra được thành đúng hai
câu: FE chưa có trang đăng nhập thật, và 16 file test/script dựng danh tính
bằng nó.

T-3.1b dựng sáu màn auth ⇒ điều kiện thứ nhất hết. T-3.1c chuyển 10 file test
và 6 script sang cookie phiên thật ⇒ điều kiện thứ hai hết. Nên nhánh ấy —
cùng hằng tên cookie dev, cùng mã lỗi "auth chưa hiện thực" của
`core/errors.py`, cùng fixture `_debug_bat` của bộ test — biến mất ở đây
(B-128, B-186). Một dòng DoD của T-3.1c là `grep` cả bốn cái tên ấy trên
`backend/app`, `frontend/src`, `backend/tests` và đòi **0** dòng, nên
chúng không được phép sống sót kể cả trong một docstring.

**Cái còn lại là hình dạng đơn giản nhất mà file này từng có:** đúng MỘT đường
mang danh tính vào app, và nó không phụ thuộc `DEBUG`. Từ nay `DEBUG` chỉ còn
quyết định đúng một thứ, ở `api/v1/__init__.py`: router `/_debug/*` có được
đăng ký hay không (§18.6).

**Vì sao `get_access_claims` vẫn trả `None` thay vì tự `401`:** `POST
/auth/logout` cố ý chạy được cả khi không có access token còn hạn (NQ-42,
C21), nên "không có cookie phiên" phải là một giá trị người gọi đọc được, chứ
không phải một ngoại lệ. Chỗ biến `None` thành `401` là ba cửa gọi nó, không
phải chính nó.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request, status

from app.core.access_token import (
    AccessTokenClaims,
    TokenExpiredError,
    TokenInvalidError,
    decode_access_token,
)
from app.core.blacklist import is_blocked
from app.core.errors import ApiError, ApiErrorCode
from app.core.redis import get_redis
from app.db.models import UserRole, UserStatus
from app.db.repositories.users import UserRepository
from app.db.session import session_scope

logger = logging.getLogger(__name__)

#: Cookie phiên thật (§11.2, T-2.3, NQ-36). `Path=/api/v1` — rộng hơn cookie
#: refresh (`Path=/api/v1/auth`, xem `app/api/v1/auth.py`) vì mọi endpoint
#: dưới `/api/v1` cần đọc được nó, còn refresh chỉ có nghĩa ở `/auth/refresh`.
SESSION_COOKIE_NAME = "scarlet_session"


def _all_session_cookies(request: Request) -> list[str]:
    """MỌI giá trị `scarlet_session` trong header `Cookie`, đúng thứ tự gửi.

    **Vì sao không dùng `Cookie(alias=...)` của FastAPI** — đây là một lỗi đã
    cắn thật, đo được 2026-09-22:

        POST /api/v1/auth/login    → 200   (đăng nhập thành công)
        GET  /api/v1/auth/me       → 401 TOKEN_EXPIRED
        GET  /api/v1/auth/me       → 401   ss=1 dup=1   ← HAI cookie cùng tên

    `Cookie(alias=...)` đọc `request.cookies`, mà `cookie_parser` của Starlette
    gán vào một `dict` trong một vòng lặp, tức **giá trị cuối cùng thắng**::

        cookie_parser('scarlet_session=CU; scarlet_session=MOI')  → 'MOI'
        cookie_parser('scarlet_session=MOI; scarlet_session=CU')  → 'CU'

    RFC 6265 §5.4 bắt trình duyệt xếp cookie có `Path` DÀI hơn lên trước, nên
    cookie mới (`Path=/api/v1`, xem `_set_session_cookie`) đi **trước** và một
    cookie cũ cùng tên ở path rộng hơn đi **sau** — đúng cái Starlette giữ lại.
    Hệ quả: người dùng đăng nhập lại bao nhiêu lần cũng vô ích, vì cookie vừa
    cấp luôn bị cái cũ che, và màn hình báo "access token đã hết hạn" ngay sau
    một lần `login` trả `200`.

    Và nó KHÔNG chỉ là chuyện phiền: đây là **cookie tossing**. Ai đặt được một
    cookie cùng tên ở path rộng hơn — hoặc, khi lên domain thật, từ một
    subdomain anh em — sẽ khoá vĩnh viễn phiên của người khác mà không cần
    biết một bí mật nào. Cookie `HttpOnly` không đỡ được: nó chặn JS **đọc**,
    không chặn việc ghi đè bằng một cookie khác.

    Vì vậy tầng này đọc header thô và trả **tất cả**; `get_access_claims` nhận
    cái đầu tiên giải mã được. Một cookie rác đi kèm không còn đủ sức chặn một
    cookie thật.
    """
    raw = request.headers.get("cookie")
    if not raw:
        return []
    value: list[str] = []
    for part in raw.split(";"):
        name, eq_sign, val = part.partition("=")
        if eq_sign and name.strip() == SESSION_COOKIE_NAME:
            value.append(val.strip().strip('"'))
    return value


async def get_access_claims(request: Request) -> AccessTokenClaims | None:
    """Claim của cookie phiên, đã verify chữ ký + `exp` + blacklist (§11.3).

    Trả `None` khi **không có** cookie phiên; ba cửa gọi hàm này biến `None`
    ấy thành `401` (xem docstring module). Mọi ca khác — cookie có mặt nhưng
    không dùng được — đều raise ngay tại đây.

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
    cookies = _all_session_cookies(request)
    if not cookies:
        return None

    # Nhận cái ĐẦU TIÊN giải mã được. Khi chỉ có một cookie — đường đi thường —
    # vòng lặp này chạy đúng một lần và hành vi y hệt bản cũ.
    claims = None
    has_expired = False
    for raw_token in cookies:
        try:
            claims = decode_access_token(raw_token)
            break
        except TokenExpiredError:
            has_expired = True
        except TokenInvalidError:
            pass

    if claims is None:
        # `TOKEN_EXPIRED` được ưu tiên hơn `UNAUTHENTICATED` khi có ít nhất một
        # cookie hết hạn: nó là mã FE đọc để đi `/auth/refresh` thay vì đẩy
        # thẳng người dùng ra màn đăng nhập. Một cookie rác đi kèm không được
        # phép hạ cấp chẩn đoán ấy.
        if has_expired:
            raise ApiError(
                status.HTTP_401_UNAUTHORIZED,
                ApiErrorCode.TOKEN_EXPIRED,
                "access token da het han",
            )
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            ApiErrorCode.UNAUTHENTICATED,
            "access token khong hop le",
        )

    try:
        revoked = await is_blocked(get_redis(), claims)
    except Exception as exc:
        logger.exception("khong kiem duoc blacklist cho user %s", claims.user_id)
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ApiErrorCode.SERVICE_UNAVAILABLE,
            "khong kiem duoc trang thai phien dang nhap",
        ) from exc

    if revoked:
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            ApiErrorCode.TOKEN_REVOKED,
            "phien dang nhap da bi thu hoi, hay dang nhap lai",
        )
    return claims


async def get_current_user_id(
    claims: Annotated[AccessTokenClaims | None, Depends(get_access_claims)] = None,
) -> uuid.UUID:
    """`user_id` của người gọi — đúng MỘT đường: cookie phiên `scarlet_session`.

    §11.2, T-2.3, NQ-36. Chỗ tạm của Phase 1 từng nằm ngay dưới đây đã bị
    T-3.1c xoá; xem docstring module.

    Raise:
        Mọi lỗi của `get_access_claims` (401 `TOKEN_EXPIRED` /
            `UNAUTHENTICATED` / `TOKEN_REVOKED`, 503 `SERVICE_UNAVAILABLE`).
        ApiError 401 `UNAUTHENTICATED`: không có cookie phiên.

    `UNAUTHENTICATED` là mã FE đọc để đẩy người dùng ra màn hình đăng nhập
    (§18, B-86, `StatusGate` của T-3.1c).
    """
    if claims is None:
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            ApiErrorCode.UNAUTHENTICATED,
            "can dang nhap de dung chuc nang nay",
        )
    return claims.user_id


# ════════════════ §11.1 — bảng phân quyền theo trạng thái (T-2.7) ═══════════
#
# | Trạng thái        | Đăng nhập | Xem UI | Chat system key | Chat BYOK |
# |-------------------|-----------|--------|-----------------|-----------|
# | pending_email     |     ✓     |   ✓    |        ✗        |     ✗     |
# | pending_approval  |     ✓     |   ✓    |        ✗        |     ✓     |
# | active            |     ✓     |   ✓    |        ✓        |     ✓     |
# | rejected          |     ✗     |   —    |        —        |     —     |
# | suspended         |     ✗     |   —    |        —        |     —     |
#
# Bốn hằng dưới đây là bốn CỘT của bảng, chép đúng một lần. Thêm một trạng
# thái thứ sáu vào `UserStatus` mà quên chúng thì trạng thái đó không làm được
# gì cả — hỏng về phía an toàn, và hỏng ồn ào ở test ma trận 5×4.

#: Cột "Đăng nhập". `rejected`/`suspended` là hai trạng thái CUỐI: không có
#: đường nào tự đi ra khỏi chúng, chỉ admin mới đổi được (§16.3).
STATUSES_CAN_LOGIN = frozenset(
    {UserStatus.PENDING_EMAIL, UserStatus.PENDING_APPROVAL, UserStatus.ACTIVE}
)

#: Cột "Xem UI" — mọi endpoint KHÔNG sinh chữ: đọc/sửa hội thoại, đọc cây, đọc
#: stream, huỷ một lượt đang chạy, `GET /auth/me`. Ba trạng thái đầu đều thấy
#: giao diện (§11.1 ghi kèm banner nhắc verify / chờ duyệt — banner là việc của
#: FE, và FE biết phải hiện cái nào nhờ `status` trong `GET /auth/me`).
STATUSES_CAN_VIEW_APP = frozenset(
    {UserStatus.PENDING_EMAIL, UserStatus.PENDING_APPROVAL, UserStatus.ACTIVE}
)

#: Cột "Chat bằng system key" — tiền của người vận hành, nên chỉ `active`.
STATUSES_CAN_CHAT_SYSTEM_KEY = frozenset({UserStatus.ACTIVE})

#: Cột "Chat bằng BYOK" (§10.5): `pending_approval` **được**, có chủ ý —
#: "người đó không tiêu tiền của bạn, nên không có lý do gì chặn họ".
#: `pending_email` KHÔNG có mặt ở đây: chưa chứng minh được hộp thư là của
#: mình thì chưa có tài khoản để nói tới, dù tiền là của ai.
STATUSES_CAN_CHAT_BYOK = frozenset({UserStatus.PENDING_APPROVAL, UserStatus.ACTIVE})


#: Trạng thái bị từ chối → (mã lỗi §18, câu nói cho người dùng). `active`
#: không có mặt: nó không bao giờ bị từ chối ở bất kỳ cột nào.
_DENIAL_BY_STATUS: dict[UserStatus, tuple[ApiErrorCode, str]] = {
    UserStatus.PENDING_EMAIL: (
        ApiErrorCode.EMAIL_NOT_VERIFIED,
        "hay xac thuc email truoc khi dung chuc nang nay",
    ),
    UserStatus.PENDING_APPROVAL: (
        ApiErrorCode.PENDING_APPROVAL,
        "tai khoan dang cho quan tri duyet; them khoa API rieng (BYOK) de dung ngay",
    ),
    UserStatus.REJECTED: (
        ApiErrorCode.ACCOUNT_DISABLED,
        "tai khoan khong dung duoc, hay lien he quan tri",
    ),
    UserStatus.SUSPENDED: (
        ApiErrorCode.ACCOUNT_DISABLED,
        "tai khoan khong dung duoc, hay lien he quan tri",
    ),
}


def _denied(user_status: UserStatus) -> ApiError:
    """`403` mang đúng mã của §18 cho trạng thái này.

    `403` chứ không `401` ở **mọi** ca: danh tính đã được chứng minh (mật khẩu
    đúng, hoặc access token còn hạn và chưa bị thu hồi), thứ thiếu là quyền.
    Trả `401` sẽ đá người dùng ra màn đăng nhập rồi họ đăng nhập lại thành
    công và gặp lại đúng bức tường ấy — một vòng lặp không có lối ra.
    """
    code, message = _DENIAL_BY_STATUS[user_status]
    return ApiError(status.HTTP_403_FORBIDDEN, code, message, details={"status": user_status.value})


def ensure_status_allowed(user_status: UserStatus, allowed: frozenset[UserStatus]) -> None:
    """Raise `403` nếu `user_status` không nằm trong cột `allowed` của §11.1.

    Dạng gọi thẳng của `require_status`, cho `POST /auth/login` — chỗ duy nhất
    kiểm trạng thái mà **chưa** có access token để `Depends` đọc claim.

    Raise:
        ApiError 403 `EMAIL_NOT_VERIFIED` / `PENDING_APPROVAL` /
            `ACCOUNT_DISABLED` — xem `_DENIAL_BY_STATUS`.
    """
    if user_status not in allowed:
        raise _denied(user_status)


async def _has_byok(user_id: uuid.UUID) -> bool:
    """§10.5 — người này đã cấu hình khoá API riêng chưa."""
    async with session_scope() as session:
        return await UserRepository(session).has_provider_key(user_id)


async def get_current_user_status(
    claims: Annotated[AccessTokenClaims | None, Depends(get_access_claims)] = None,
) -> UserStatus:
    """Trạng thái tài khoản của người gọi (T-2.15).

    Dùng cho phép kiểm §11.1 **chính xác** mà `require_chat_access` không làm
    nổi: nó chạy trước khi handler đọc body nên nó không biết `model_id`, tức
    không biết provider, tức chỉ hỏi được "có khoá **nào đó** không" thay vì
    "có khoá cho provider này không" (**B-140**). Ba route sinh chữ vì vậy xin
    thêm trạng thái để hỏi lại câu đúng ở `_open_generation`, nơi model đã chốt.

    Hằng `STATUSES_CAN_*` vẫn là nguồn sự thật duy nhất của bảng §11.1 — hàm
    này chỉ chở một giá trị, nó không phán xét gì; phép so sánh vẫn là
    `ensure_status_allowed(...)` như ở `POST /auth/login`.

    Raise:
        ApiError 401 `UNAUTHENTICATED`: không có cookie phiên. Trước T-3.1c ca
            này trả `None` để nhánh tạm Phase 1 đi qua — xem docstring module.
    """
    if claims is None:
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            ApiErrorCode.UNAUTHENTICATED,
            "can dang nhap de dung chuc nang nay",
        )
    return claims.status


def require_status(
    allowed: frozenset[UserStatus],
    *,
    allowed_with_byok: frozenset[UserStatus] = frozenset(),
) -> Callable[[AccessTokenClaims | None], Awaitable[None]]:
    """Dependency chặn theo cột của bảng §11.1.

    Args:
        allowed: cột chính — những trạng thái qua được mà không cần hỏi gì thêm.
        allowed_with_byok: những trạng thái qua được **chỉ khi** đã cấu hình
            BYOK (§10.5). Phần giao với `allowed` bị loại ngay lúc dựng, nên
            `SELECT EXISTS` chỉ chạy cho đúng những trạng thái thật sự cần hỏi
            — một `active` không bao giờ phải trả giá cho luật của người khác.

    Dùng qua `dependencies=[Depends(...)]` chứ không phải tham số của handler:
    nó không trả về gì (`None`), và một tham số luôn `None` trong chữ ký
    handler là thứ người đọc sau sẽ tưởng là thừa rồi xoá đi.

    Raise:
        ApiError 401 `UNAUTHENTICATED`: không có cookie phiên. Trước T-3.1c ca
            này đi thẳng qua để nhánh tạm Phase 1 sống được.
        ApiError 403 `EMAIL_NOT_VERIFIED` / `PENDING_APPROVAL` /
            `ACCOUNT_DISABLED` — xem `_DENIAL_BY_STATUS`.
    """
    byok_only = frozenset(allowed_with_byok) - frozenset(allowed)

    async def _check(
        claims: Annotated[AccessTokenClaims | None, Depends(get_access_claims)] = None,
    ) -> None:
        if claims is None:
            raise ApiError(
                status.HTTP_401_UNAUTHORIZED,
                ApiErrorCode.UNAUTHENTICATED,
                "can dang nhap de dung chuc nang nay",
            )
        if claims.status in allowed:
            return
        if claims.status in byok_only and await _has_byok(claims.user_id):
            return
        raise _denied(claims.status)

    return _check


#: "Xem UI" của §11.1 — gắn cho CẢ router `conversations`, `messages`, `stream`
#: ở `app/api/v1/__init__.py`, và cho `GET /auth/me`. Gắn theo router chứ không
#: theo từng route là cách trả lời cạm bẫy của T-2.7 (và của T-2.16): endpoint
#: thứ mười một sinh ra sau này được bảo vệ vì nó nằm trong router, không phải
#: vì ai đó nhớ chép thêm một dòng.
require_app_access = require_status(STATUSES_CAN_VIEW_APP)

#: "Chat" của §11.1 — gắn cho ba route SINH CHỮ (`POST .../messages`,
#: `POST /messages/{id}/retry`, `PATCH /messages/{id}`). Ba route đó tốn tiền;
#: những route còn lại của cùng router (`cancel`, `siblings`) thì không, và
#: `cancel` còn phải chạy được đúng lúc trạng thái vừa đổi — chặn nó nghĩa là
#: một lượt sinh đang chảy không ai dừng được nữa.
require_chat_access = require_status(
    STATUSES_CAN_CHAT_SYSTEM_KEY, allowed_with_byok=STATUSES_CAN_CHAT_BYOK
)


# ═══════════════ §16.3 — cánh cửa của `/admin/*` (T-2.16) ═══════════════════


async def require_admin(
    claims: Annotated[AccessTokenClaims | None, Depends(get_access_claims)] = None,
) -> None:
    """Chặn mọi request không phải của một admin — §16.3, §20.

    Gắn ở **lời gọi `include_router`** của `api/v1/__init__.py`, không rải vào
    từng `@router.get/post`. Cạm bẫy của T-2.16 viết nguyên văn *"quên
    `require_admin` ở MỘT endpoint là đủ"*, và nó là cùng một cạm bẫy mà
    `require_app_access` ngay trên đã đóng bằng cùng một cách: endpoint
    `/admin/*` thứ tám sinh ra sau này được bảo vệ vì **vị trí** của nó, không
    vì ai đó nhớ chép thêm một dòng.

    **Đọc `role` từ CLAIM, không từ một `SELECT`** — cùng lý lẽ `require_status`
    (§11.2 ghi sẵn `role` vào JWT từ T-2.3). Cửa sổ cũ ≤ `ACCESS_TOKEN_TTL_MIN`
    của nó ở đây **hẹp hơn** hai chiều so với `status`: không có endpoint nào
    phong/gỡ chức admin (R7: một admin, đặt bằng SQL), nên không có sự kiện nào
    trong app sinh ra một claim `role` cũ.

    ╔══════════════════════════════════════════════════════════════════════╗
    ║  `claims is None` ⇒ `401`, KHÔNG phải `403`                          ║
    ╚══════════════════════════════════════════════════════════════════════╝

    Chưa có danh tính nào được chứng minh thì chưa tới lượt hỏi quyền. Đó cũng
    là đúng chữ DoD dòng 1 của T-2.16 (*"`curl` không token → `401`"*).

    Hàm này là cửa **đầu tiên** viết ra luật ấy: từ T-2.16 tới T-3.1b nó đứng
    một mình, vì `require_status` phải cho `claims is None` đi qua để nhánh
    danh tính tạm của Phase 1 sống được — mà cho nhánh ấy vào `/admin/*` thì
    bất kỳ ai gọi được `api` lúc `DEBUG=true` đều duyệt được tài khoản, đổi
    được tier và đọc được bảng chi phí của cả hệ thống (chính lỗ hổng B-34 ghi
    từ T-0.7 và giao cho T-2.16 đóng). T-3.1c xoá nhánh tạm, nên nay cả ba cửa
    của file này nói cùng một câu — xem docstring module.

    Raise:
        ApiError 401 `UNAUTHENTICATED`: không có cookie phiên.
        ApiError 403 `ADMIN_REQUIRED`: có danh tính, nhưng `role != admin`.
    """
    if claims is None:
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            ApiErrorCode.UNAUTHENTICATED,
            "can dang nhap bang tai khoan quan tri",
        )
    if claims.role is not UserRole.ADMIN:
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            ApiErrorCode.ADMIN_REQUIRED,
            "chuc nang nay danh cho quan tri vien",
            details={"role": claims.role.value},
        )
