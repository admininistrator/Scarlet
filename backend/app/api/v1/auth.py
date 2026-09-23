"""`POST /auth/register`, `/verify-email`, `/resend-verification` (§11.1,
§11.5, §11.6, UC-01) — T-2.1, T-2.2. `POST /auth/login`, `/refresh`,
`GET /auth/me` (§11.2, ADR-07) — T-2.3. `POST /auth/logout` (§11.3, C21) — T-2.4.
`POST /auth/forgot-password`, `/reset-password` (§11.5, §11.6) — T-2.5.
`GET /auth/me` nở ra đủ bốn nhóm của §18.1 (quota, `message_max_chars`,
`default_model`) — T-3.0.

KH tham chiếu: §11.5, §11.2, §11.3, §11.6, §10.6, §18.1, UC-01, UC-07,
ADR-07, C21 · CLAUDE.md A3, A7 · tasks.md T-2.2, T-2.3, T-2.4, T-2.5, T-3.0,
NQ-36, NQ-43, NQ-44, NQ-78, NQ-79, NQ-81.

┌──────────────────────────────────────────────────────────────────────────┐
│  CẠM BẪY CỦA T-2.1: chống dò email (§11.5)                                │
└──────────────────────────────────────────────────────────────────────────┘

"Trả lỗi 'email đã tồn tại' là cho phép người lạ dò xem ai đã đăng ký."
`register` vì vậy cố ý KHÔNG có hai nhánh response khác nhau:

1. Cả hai đường (email mới / email đã tồn tại) đều trả về đúng MỘT hằng số
   `_REGISTER_RESPONSE` — cùng status code, cùng body, byte-for-byte (DoD).
2. Mật khẩu vẫn được băm bằng Argon2 (~50–200 ms) DÙ email đã tồn tại, để
   thời gian phản hồi không trở thành một kênh ngầm (đường "đã tồn tại" mà
   nhanh hơn hẳn đường "mới" là một cách dò khác, tinh vi hơn status code).
3. `UserRepository.create_pending_user` trả `None` thay vì raise khi UNIQUE
   của `email` va chạm — không có exception riêng để lộ ra thành hai nhánh xử
   lý ở đây. Nhánh đó cũng không phát hành token/gửi mail: không đọc/ghi gì
   thêm về user đã có (§11.5).

`resend-verification` áp đúng nguyên tắc trên: một hằng số response, không
rẽ nhánh theo email có tồn tại/đã verify hay chưa.

┌──────────────────────────────────────────────────────────────────────────┐
│  CẠM BẪY CỦA T-2.2: không lưu token bản rõ                                 │
└──────────────────────────────────────────────────────────────────────────┘

"Lưu token bản rõ trong DB nghĩa là ai đọc được DB thì chiếm được mọi tài
khoản." Token bản rõ chỉ tồn tại trong biến cục bộ của request đang xử lý
(`EmailTokenRepository.issue` trả về nó, không ghi nó) và trong nội dung
email đã gửi — `email_tokens.token_hash` luôn là SHA-256 (`hash_email_token`).

`verify-email` phải phân biệt BA kết cục khác nhau mà none trong số đó là
lỗi 500 (DoD): token hợp lệ lần đầu và token đã dùng trước đó đều trả
`{"status": "verified"}` (idempotent, UC-01); token hết hạn trả
`{"status": "expired"}` **vẫn HTTP 200** — client dựa vào trường `status`,
không dựa vào mã lỗi, để quyết định hiện trang nào. Chỉ token chưa từng tồn
tại (giả mạo/sai `purpose`) mới ra `400 TOKEN_INVALID`.

┌──────────────────────────────────────────────────────────────────────────┐
│  TURNSTILE (T-2.6, §11.6, RR-1) — hai route, một hàm                     │
└──────────────────────────────────────────────────────────────────────────┘

`register` và `forgot-password` là hai route §11.6 chỉ định, và cả hai gọi
đúng một hàm `core/turnstile.py::kiem_turnstile`. Ba điểm quyết định hình
dạng của chúng (lý do đầy đủ ở docstring của module đó):

1. **`turnstile_token` là `str | None = None`, không phải field bắt buộc.**
   Field bắt buộc mà thiếu thì pydantic trả `422 VALIDATION_ERROR`, còn DoD
   T-2.6 đòi `400` — và `400 TURNSTILE_FAILED` là câu nói đúng việc ("giải lại
   captcha"), khác hẳn "body sai kiểu".
2. **Kiểm TRƯỚC mọi thứ khác trong thân handler**, kể cả trước `hash_password`
   (~100 ms, 192 MiB) và trước `SELECT` đầu tiên. Đây là cổng chống *máy*; để
   nó sau bất cứ việc gì là trả tiền cho request mà mình sắp từ chối.
3. **Không đổi một chữ nào trong hợp đồng chống dò của §11.5.** Phép kiểm
   captcha không đọc `email`, nên nó không thêm được nhánh nào rẽ theo "email
   này có tồn tại không" — `_REGISTER_RESPONSE` và `_FORGOT_PASSWORD_RESPONSE`
   vẫn là một hằng số cho mọi đường.

Hệ quả UX đã biết: mật khẩu quá yếu → `422`, và token Turnstile vừa gửi kèm
**đã tiêu** (Cloudflare chỉ nhận một lần). FE phải gọi `turnstile.reset()` sau
mọi response lỗi, không riêng `400` — ghi rõ ở `components/auth/Turnstile.tsx`.

┌──────────────────────────────────────────────────────────────────────────┐
│  CẠM BẪY CỦA T-2.3: xoay vòng refresh + phát hiện tái sử dụng             │
└──────────────────────────────────────────────────────────────────────────┘

`login` phát hành family refresh token MỚI; `refresh` xoay vòng — đọc token
cũ, đánh dấu `used_at`, phát hành token mới CÙNG `family_id`. Một token đã
`used_at` bị trình ra LẦN NỮA là dấu hiệu nó bị đánh cắp (kẻ tấn công dùng bản
sao trong khi nạn nhân đã tự xoay vòng, hoặc ngược lại) → `RefreshTokenRepository.rotate`
thu hồi TOÀN BỘ family, kể cả hàng vừa xoay ra và còn hợp lệ — DoD T-2.3 kiểm
đúng chỗ này (`SELECT revoked_at FROM refresh_tokens WHERE family_id=...` →
tất cả khác NULL sau lần dùng lại thứ hai).

`login` áp lại đúng kỹ thuật chống dò-qua-thời-gian của `register` (điểm 2 ở
trên): sai mật khẩu và email không tồn tại phải tốn THỜI GIAN như nhau, nên
nhánh "không có user" vẫn băm `_DUMMY_PASSWORD` thay vì trả lỗi ngay — nếu không,
đo độ trễ response là một cách dò danh sách email đã đăng ký (khác hẳn nhánh
"sai mật khẩu" vốn luôn băm thật).

Một cookie phiên (`scarlet_session`, §11.2, NQ-36) — KHÔNG Bearer — mang access
JWT; `app/core/deps.py::get_current_user_id` là nơi verify nó. Cookie refresh
giữ `Path=/api/v1/auth` (chỉ gửi tới nhóm route này), cookie phiên rộng hơn
(`Path=/api/v1`, mọi route cần đọc danh tính) — hai path khác nhau nên trình
duyệt không bao giờ gửi nhầm cookie refresh cho một route thường.

┌──────────────────────────────────────────────────────────────────────────┐
│  CẠM BẪY CỦA T-2.4 (C21): logout phải ĐÓNG ĐƯỢC, kể cả khi đã muộn        │
└──────────────────────────────────────────────────────────────────────────┘

`logout` **không** đứng sau `Depends(get_current_user_id)`, và đó là quyết định
chính của task chứ không phải một chỗ lười. Access token sống 15 phút, refresh
token sống 30 ngày: bắt buộc phải có access token còn hạn mới đăng xuất được
nghĩa là người rời máy quá 15 phút rồi bấm "Đăng xuất" sẽ nhận `401` — và cái
còn sống, refresh token, **vẫn nguyên**. Người dùng tin mình đã ra, thực tế thì
phiên 30 ngày vẫn mở. Đó đúng là C21, chỉ đổi nguyên nhân từ "không blacklist"
sang "blacklist không với tới". Vì vậy `logout` đọc thẳng hai cookie, tha mọi
token không giải mã được, và **luôn** trả 200 — không có trạng thái nào của
client làm nó từ chối đóng cửa.

Cho đăng xuất mà không cần xác thực **không** mở thêm CSRF: thứ duy nhất kẻ
tấn công đạt được là đá nạn nhân ra khỏi phiên của chính nạn nhân (phiền, không
mất mát), và `OriginCheckMiddleware` (NQ-36) vẫn chặn POST cross-site có
`Origin` — mọi trình duyệt thật đều gửi header đó cho request kiểu này.

**Thứ tự hai nửa của §11.3 là Postgres TRƯỚC, Redis SAU.** Một trong hai nửa
trượt thì nửa nào đã chạy quyết định thiệt hại: chạy DB trước thì lần trượt để
lại "refresh (30 ngày) đã chết, access (≤15 phút) còn sống" — tự lành; chạy
Redis trước thì lần trượt để lại "access đã chết, **refresh 30 ngày còn sống**"
— không tự lành, và đó là credential đắt hơn hẳn.

┌──────────────────────────────────────────────────────────────────────────┐
│  RATE LIMIT THEO IP (§10.6) — B-127, B-131                               │
└──────────────────────────────────────────────────────────────────────────┘

Hai hạn mức, hai lý do khác nhau (chi tiết ở `app/core/ratelimit.py`):

- **3/giờ** cho route *gửi thư* (`resend-verification`): §18.1 ghi hạn mức này
  ngay từ đầu cho đúng route đó. Không có nó, endpoint là một cách gửi thư hàng
  loạt tới một hộp thư bất kỳ — vô hại khi SMTP còn là Mailpit, thành đường
  lạm dụng/spam-report khi T-H8 đổi sang SMTP thật (B-127).
- **5/phút** cho route `/auth/*` *không* gửi thư (`logout`, `reset-password`):
  §10.6 xếp nhóm `auth` ở 5/phút **theo user**, nhưng hai route này cố ý không
  có user (NQ-42, và `reset-password` chạy khi chưa đăng nhập) nên trục đếm
  phải là IP (B-131).

┌──────────────────────────────────────────────────────────────────────────┐
│  CẠM BẪY CỦA T-2.5: đặt lại mật khẩu phải ĐUỔI ĐƯỢC kẻ đang ở trong       │
└──────────────────────────────────────────────────────────────────────────┘

"Không revoke session sau khi đổi mật khẩu = kẻ đã chiếm tài khoản vẫn ở trong
đó sau khi nạn nhân đổi mật khẩu." `reset-password` vì vậy gọi
`core/blacklist.py::thu_hoi_moi_phien()` — **một** hàm làm cả hai nửa của
§11.3 (revoke mọi refresh family + đặt mốc `bl:user:`), đúng như T-2.4 dựng ra
để T-2.5 không phải nhớ một nửa.

`forgot-password` mang nguyên tắc chống dò của §11.5 sang một hình dạng mới:
**không** rẽ nhánh response theo email có tồn tại hay không, và cũng không rẽ
theo trạng thái tài khoản. Một hằng số response duy nhất, y như `register` và
`resend-verification`.

**Ba kết cục của một token reset hỏng đều trả CÙNG một câu.** Không tồn tại,
đã dùng rồi, hết hạn → `400 TOKEN_INVALID` với cùng `message`. Khác hẳn
`verify-email` (nơi "đã dùng" là thành công idempotent và "hết hạn" có mã
riêng), và khác có lý do: bấm lại link verify là vô hại, còn dùng lại link
reset là **đổi mật khẩu lần thứ hai**. Phân biệt ba ca đó cho người cầm một
token đã tiêu (nhặt trong log proxy, trong lịch sử trình duyệt) biết token ấy
từng là thật — tức biết email đó có tài khoản, đúng thứ §11.5 không cho rò. Và
việc FE phải làm thì giống hệt nhau ở cả ba: xin một link mới.

**Mật khẩu được kiểm TRƯỚC `hash_password` và trước khi mở transaction** — vì
Argon2id ở đây tốn ~100 ms và 192 MiB RAM mỗi lượt (T-2.1), nên trả `422` cho
một chuỗi 4 ký tự *sau* khi đã băm nó là tự trả tiền cho mỗi lượt gọi rác.

Cái mà thứ tự này **không** phải là: một lớp bảo vệ cho token. Đo bằng phép
kiểm ngược (dời hai phép kiểm xuống *sau* `consume`) — **không** test nào đỏ,
vì `session_scope()` không commit khi có ngoại lệ, nên `used_at` vừa ghi bị
rollback và link vẫn dùng được. Token sống sót qua một lần gõ sai là nhờ
transaction, không nhờ thứ tự; ghi rõ ra đây để không ai "tối ưu" cái đúng
bằng một lý do sai.

Một lần gõ sai vẫn tính vào hạn mức (dependency chạy trước handler), nên
`reset-password` dùng hạn mức 5/phút chứ không 3/giờ: ba lần gõ mật khẩu quá
yếu không được khoá **nạn nhân** ra khỏi tài khoản một tiếng (xem
`core/ratelimit.py`).

**`reset-password` KHÔNG tự đăng nhập** — chốt ở NQ-44, đóng B-130. Mốc
`bl:user:` giữ phần thập phân (NQ-42 ②) nên nó chặn cả access token phát hành
trong *cùng giây* với lần thu hồi; một endpoint vừa đặt mốc vừa tự ký cookie
phiên sẽ trả về một cookie mà chính nó vừa làm cho vô hiệu. Nó xoá hai cookie
cũ thay vào đó: phiên cũ đằng nào cũng vừa bị thu hồi, để nguyên chỉ khiến mọi
request kế tiếp của tab đó nhận `401` mà không ai hiểu vì sao.
"""

from __future__ import annotations

import logging
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, EmailStr

from app.config.settings import settings
from app.core.access_token import (
    TokenExpiredError,
    TokenInvalidError,
    decode_access_token,
    encode_access_token,
)
from app.core.blacklist import block_jti, revoke_all_sessions
from app.core.deps import (
    SESSION_COOKIE_NAME,
    STATUSES_CAN_LOGIN,
    ensure_status_allowed,
    get_current_user_id,
    require_app_access,
)
from app.core.errors import ApiError, ApiErrorCode, ErrorEnvelope
from app.core.mailer import mailer
from app.core.ratelimit import (
    ROUTE_FORGOT_PASSWORD,
    ROUTE_LOGOUT,
    ROUTE_REGISTER,
    ROUTE_RESEND_VERIFICATION,
    ROUTE_RESET_PASSWORD,
    auth_limit,
    client_ip,
    email_send_limit,
)
from app.core.redis import get_redis
from app.core.security import hash_password, is_common_password, verify_password
from app.core.turnstile import verify_turnstile
from app.db.models import EmailTokenPurpose, UserRole, UserStatus
from app.db.repositories.email_tokens import ConsumeResult, EmailTokenRepository
from app.db.repositories.refresh_tokens import RefreshTokenRepository, RotateResult
from app.db.repositories.users import UserRepository
from app.db.session import session_scope
from app.quota.snapshot import WindowSnapshot, read_snapshot

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

#: `Path` hẹp hơn cookie phiên (`SESSION_COOKIE_NAME`, `app/core/deps.py`) —
#: chỉ nhóm route `/auth/*` cần đọc token này (§11.2).
REFRESH_COOKIE_NAME = "scarlet_refresh"

#: `Path` của hai cookie. Thành hằng ở T-2.4 vì `delete_cookie` **phải** dùng
#: đúng `Path` đã `set_cookie`: lệch một ký tự thì trình duyệt giữ nguyên
#: cookie cũ và không ai biết — `Set-Cookie` vẫn đi ra, response vẫn 200, chỉ
#: có điều người dùng vẫn đăng nhập. Chép tay ở bốn chỗ là bốn cơ hội để lệch.
#: Giá trị bám theo `prefix` của `app/api/v1/__init__.py`; không import được từ
#: đó (vòng import: `api.v1.__init__` nạp chính module này).
SESSION_COOKIE_PATH = "/api/v1"
REFRESH_COOKIE_PATH = "/api/v1/auth"

#: Mật khẩu giả — KHÔNG dùng để so khớp, chỉ để `hash_password` tốn đúng
#: ngần ấy mili-giây khi email không tồn tại (chống dò qua thời gian, xem
#: docstring module).
_DUMMY_PASSWORD = "mat-khau-gia-chi-de-giu-thoi-gian-phan-hoi-dong-deu-000"


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    #: `cf-turnstile-response` của widget (T-2.6). Tuỳ chọn ở tầng schema chứ
    #: KHÔNG phải tuỳ chọn ở tầng luật — xem điểm 1 của docstring module.
    turnstile_token: str | None = None


class RegisterResponse(BaseModel):
    message: str


#: Response CỐ ĐỊNH cho cả hai nhánh (email mới / email đã tồn tại) — DoD đòi
#: byte-for-byte giống nhau, nên đây là MỘT hằng số duy nhất, không phải hai
#: chỗ gõ tay cùng một câu (dễ lệch một khoảng trắng).
_REGISTER_RESPONSE = RegisterResponse(
    message=(
        "neu email hop le va chua duoc dang ky truoc do, "
        "tai khoan da duoc tao va dang cho xac thuc email"
    )
)


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class ResendVerificationResponse(BaseModel):
    message: str


#: Cùng lối với `_REGISTER_RESPONSE`: một hằng số, không rẽ nhánh theo email có
#: tồn tại / đã verify hay chưa (§11.5).
_RESEND_RESPONSE = ResendVerificationResponse(
    message=("neu email nay ton tai va chua duoc xac thuc, mot email xac thuc moi da duoc gui")
)


class VerifyEmailRequest(BaseModel):
    token: str


class VerifyEmailResponse(BaseModel):
    #: `verified`: token hợp lệ, **lần đầu** — tài khoản vừa chuyển sang
    #: `pending_approval`, FE đưa người dùng tới màn "chờ duyệt".
    #: `already_verified`: token đúng nhưng đã dùng rồi (idempotent, UC-01
    #: dòng 5) — FE đưa thẳng tới màn đăng nhập.
    #: `expired`: hết hạn, FE hiện trang "gửi lại" — vẫn HTTP 200 (DoD T-2.2).
    #:
    #: **Vì sao tách `already_verified` khỏi `verified` (T-3.1b).** Tới T-2.2
    #: hai ca ấy trả cùng một chuỗi vì không ai cần phân biệt; T-3.1b thì cần,
    #: và cần **cả hai chiều cùng lúc**: DoD dòng 1 đòi lần bấm đầu tự sang
    #: `/cho-duyet`, DoD dòng 4 đòi lần bấm thứ hai về `/dang-nhap`. Một
    #: response giống hệt nhau cho hai kết cục khác nhau thì FE chỉ đoán được.
    #: Phân biệt này **không** rò gì: phải cầm đúng token mới tới được đây, nên
    #: nó không phải một đường dò kiểu §11.5. Cả hai vẫn `200`, vẫn không có
    #: tác dụng phụ ở lần thứ hai — tính idempotent của UC-01 giữ nguyên.
    status: Literal["verified", "already_verified", "expired"]


async def _send_verification_email(email: str, raw_token: str) -> None:
    """Best-effort: lỗi gửi mail KHÔNG được làm hỏng response của caller.

    Xem docstring `core/mailer.py` phần "vì sao send lỗi không làm register
    trả 500" — tài khoản/token đã commit vào DB trước khi hàm này chạy, nên
    một lần SMTP hỏng chỉ mất một email, không mất dữ liệu; người dùng còn
    đường `resend-verification` để lấy token mới.
    """
    verify_url = f"{settings.PUBLIC_BASE_URL}/verify-email?token={raw_token}"
    try:
        await mailer.send(
            template="verify_email",
            to=email,
            ctx={"verify_url": verify_url, "ttl_minutes": settings.EMAIL_TOKEN_TTL_MIN},
        )
    except Exception:
        logger.exception("gui email xac thuc that bai cho %s", email)


@router.post(
    "/register",
    status_code=status.HTTP_200_OK,
    response_model=RegisterResponse,
    # §10.6 hàng "theo IP cho route chưa đăng nhập": **đăng ký 3/giờ** (B-133,
    # T-2.9). Cùng chính sách với `forgot-password`/`resend-verification` và
    # cùng lý do: mỗi lượt gọi gửi một lá thư tới một hộp thư người gọi tự
    # nhập. Ở đây nó chặn thêm một thứ hai — mỗi lượt còn băm Argon2id 192 MiB
    # (T-2.1), nên endpoint này là đường làm cạn RAM của `api` rẻ nhất.
    #
    # Bộ đếm RIÊNG với hai route kia (khoá mang tên route): người vừa đăng ký
    # xong vẫn phải xin lại được thư xác thực.
    #
    # KHÔNG thay được Turnstile và không bị Turnstile thay: `TURNSTILE_SECRET`
    # rỗng ở dev thì captcha bị bỏ qua hoàn toàn (§11.6), còn captcha bật thì
    # nó chặn trình duyệt chứ không chặn một script gọi thẳng API.
    dependencies=[Depends(email_send_limit(ROUTE_REGISTER))],
    responses={
        400: {
            "model": ErrorEnvelope,
            "description": "thieu token Turnstile hoac token khong hop le (TURNSTILE_FAILED)",
        },
        429: {"model": ErrorEnvelope, "description": "qua 3 lan/gio tu mot IP (RATE_LIMITED)"},
        422: {
            "model": ErrorEnvelope,
            "description": "mat khau qua ngan (PASSWORD_TOO_SHORT) "
            "hoac qua pho bien (PASSWORD_TOO_WEAK)",
        },
        503: {
            "model": ErrorEnvelope,
            "description": "khong hoi duoc Cloudflare de xac minh captcha (SERVICE_UNAVAILABLE)",
        },
    },
)
async def register(body: RegisterRequest, request: Request) -> RegisterResponse:
    """Đăng ký (UC-01): tạo user `status='pending_email'`, tier mặc định,
    phát hành token verify và gửi email xác thực (T-2.2).

    Turnstile (§11.6, RR-1) chạy TRƯỚC mọi việc khác — xem điểm 2 của
    docstring module. `TURNSTILE_SECRET` rỗng ⇒ bỏ qua (chỉ dev).
    """
    await verify_turnstile(body.turnstile_token, remote_ip=client_ip(request))

    if len(body.password) < settings.PASSWORD_MIN_LENGTH:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ApiErrorCode.PASSWORD_TOO_SHORT,
            f"mat khau phai co it nhat {settings.PASSWORD_MIN_LENGTH} ky tu",
        )
    if is_common_password(body.password):
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ApiErrorCode.PASSWORD_TOO_WEAK,
            "mat khau qua pho bien, hay chon mat khau khac",
        )

    # Băm TRƯỚC khi biết email có tồn tại hay không (điểm 2 của docstring
    # module): cả hai nhánh dưới đây đều đã trả giá ~50–200 ms như nhau.
    password_hash = await hash_password(body.password)

    raw_token: str | None = None
    async with session_scope() as session:
        user = await UserRepository(session).create_pending_user(
            email=body.email, password_hash=password_hash
        )
        if user is not None:
            raw_token = await EmailTokenRepository(session).issue(
                user_id=user.id,
                purpose=EmailTokenPurpose.VERIFY,
                ttl_minutes=settings.EMAIL_TOKEN_TTL_MIN,
            )
            await session.commit()
        # else: email đã tồn tại — repository đã tự rollback, không có gì để
        # commit. Không đọc/ghi gì thêm: mọi thông tin về user đã có KHÔNG
        # được phép rò tới response (§11.5).

    # Gửi mail NGOÀI transaction, sau khi user+token đã commit — xem docstring
    # `_send_verification_email`.
    if raw_token is not None:
        await _send_verification_email(body.email, raw_token)

    return _REGISTER_RESPONSE


@router.post(
    "/resend-verification",
    status_code=status.HTTP_200_OK,
    response_model=ResendVerificationResponse,
    # §18.1 ghi "Rate limit 3/giờ" cho đúng route này ngay từ đầu; T-2.2 làm
    # theo "Việc cần làm" của task nên chưa có, B-127 ghi lại thiếu sót đó.
    dependencies=[Depends(email_send_limit(ROUTE_RESEND_VERIFICATION))],
    responses={
        429: {"model": ErrorEnvelope, "description": "qua 3 lan/gio tu mot IP (RATE_LIMITED)"}
    },
)
async def resend_verification(body: ResendVerificationRequest) -> ResendVerificationResponse:
    """Gửi lại email verify (UC-01). Chống dò (§11.5): response cố định."""
    raw_token: str | None = None
    email_to_send: str | None = None
    async with session_scope() as session:
        user = await UserRepository(session).get_by_email(body.email)
        if user is not None and user.status == UserStatus.PENDING_EMAIL:
            raw_token = await EmailTokenRepository(session).issue(
                user_id=user.id,
                purpose=EmailTokenPurpose.VERIFY,
                ttl_minutes=settings.EMAIL_TOKEN_TTL_MIN,
            )
            email_to_send = user.email
            await session.commit()
        # else: email không tồn tại, hoặc đã qua khỏi pending_email — không
        # phát hành token, không gửi mail, không đọc/ghi gì thêm (§11.5).

    if raw_token is not None and email_to_send is not None:
        await _send_verification_email(email_to_send, raw_token)

    return _RESEND_RESPONSE


@router.post(
    "/verify-email",
    status_code=status.HTTP_200_OK,
    response_model=VerifyEmailResponse,
    responses={400: {"model": ErrorEnvelope, "description": "token khong ton tai (TOKEN_INVALID)"}},
)
async def verify_email(body: VerifyEmailRequest) -> VerifyEmailResponse:
    """Bấm link verify (UC-01). Idempotent: bấm lần hai vẫn `verified`, không lỗi."""
    async with session_scope() as session:
        outcome = await EmailTokenRepository(session).consume(
            raw_token=body.token, purpose=EmailTokenPurpose.VERIFY
        )

        if outcome.result is ConsumeResult.NOT_FOUND:
            raise ApiError(
                status.HTTP_400_BAD_REQUEST,
                ApiErrorCode.TOKEN_INVALID,
                "token khong hop le",
            )
        if outcome.result is ConsumeResult.EXPIRED:
            return VerifyEmailResponse(status="expired")

        if outcome.result is ConsumeResult.ALREADY_USED:
            # Không có gì để đổi thêm — idempotent. Nói ra rằng đây là lần
            # thứ hai chứ không im lặng trộn vào `verified`: xem docstring
            # `VerifyEmailResponse.status`.
            return VerifyEmailResponse(status="already_verified")

        uid: UUID | None = outcome.user_id
        if uid is None:  # bất biến của EmailTokenRepository.consume — không nên xảy ra
            raise ApiError(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                ApiErrorCode.INTERNAL_ERROR,
                "loi noi bo, xem log cua server",
            )
        await UserRepository(session).mark_email_verified(uid)

        await session.commit()

    return VerifyEmailResponse(status="verified")


# ═══════════════════ POST /auth/login, /refresh, GET /auth/me (T-2.3) ═══════


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    """Thông tin công khai của user hiện tại — dùng chung cho `/login`,
    `/refresh`, `/me` (một hình dạng, một chỗ để đúng)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    display_name: str | None
    status: UserStatus
    role: UserRole
    tier_name: str
    #: Model mặc định của người này (§18.4, B-206) — `null` = chưa chọn, FE rơi
    #: về `default: true` của catalog. Nằm ở **lớp chung** chứ không riêng
    #: `/me` vì nó là một cột của chính hàng `users`, tức miễn phí ở cả ba
    #: endpoint; và biết nó ngay sau `login` là bớt một vòng gọi trước khi vẽ
    #: Model Picker. Xem `ProfileOut` cho hai trường chỉ `/me` mới trả.
    default_model: str | None = None


class ProfileOut(UserOut):
    """`GET /auth/me` — *"User + tier + quota còn lại + trạng thái"* (§18.1).

    Rộng hơn `UserOut` đúng ba trường (hai của T-3.0, `quota_warn_remaining_pct`
    của T-3.11), và đứng riêng vì chúng thuộc về thanh quota và ô nhập — còn
    `quota` thì **không** miễn phí: `quota` là hai lượt đọc Redis (và có thể một lượt dựng
    lại từ Postgres, RR-7). `login`/`refresh` không có việc gì phải trả giá đó
    — chúng trả lời "anh là ai", còn câu "anh còn bao nhiêu tiền" là câu FE hỏi
    lại nhiều lần sau đó.

    **Đừng đặt `Cache-Control` lên endpoint này.** `message_max_chars` tĩnh
    nhưng `quota` đổi sau **mỗi** lượt sinh, và FE gọi lại chính `/auth/me` để
    làm tươi thanh quota (UC-07). Một header cache ở đây đóng băng thanh ấy
    đúng lúc nó phải động — Cạm bẫy ① của T-3.0.
    """

    #: `null` = chưa đo được lúc này (Redis không trả lời), **không** phải
    #: "không có hạn mức" — xem `app/quota/snapshot.py`. FE ẩn thanh đi.
    quota: list[WindowSnapshot] | None
    #: Trần độ dài một message, tính bằng ký tự (B-205, NQ-78). Ô nhập của
    #: T-3.4 đếm ngược về đúng con số này; không literal nào ở FE (A3/L4).
    message_max_chars: int
    #: Ngưỡng "còn ≤ N%" của UC-07 dòng 1 (T-3.11). Cùng một biến `.env` với
    #: `quota_warning` của `202` (`estimator._warning`), nên thanh quota của FE
    #: và khối cảnh báo của backend không thể dùng hai ngưỡng khác nhau (A3).
    quota_warn_remaining_pct: int


def _set_session_cookie(response: Response, user: UserOut) -> None:
    """Set cookie phiên mang access JWT (§11.2, NQ-36) — KHÔNG trả JWT trong body."""
    access_token = encode_access_token(
        user_id=user.id,
        role=user.role,
        tier=user.tier_name,
        status=user.status,
        ttl_minutes=settings.ACCESS_TOKEN_TTL_MIN,
    )
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=access_token,
        max_age=settings.ACCESS_TOKEN_TTL_MIN * 60,
        path=SESSION_COOKIE_PATH,
        httponly=True,
        secure=True,
        samesite="lax",
    )


def _set_refresh_cookie(response: Response, raw_refresh_token: str) -> None:
    """Set cookie refresh — `Path=/api/v1/auth`, hẹp hơn cookie phiên (§11.2)."""
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=raw_refresh_token,
        max_age=settings.REFRESH_TOKEN_TTL_DAYS * 86400,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=True,
        samesite="lax",
    )


@router.post(
    "/login",
    status_code=status.HTTP_200_OK,
    response_model=UserOut,
    responses={
        401: {
            "model": ErrorEnvelope,
            "description": "email hoac mat khau sai (INVALID_CREDENTIALS)",
        },
        403: {
            "model": ErrorEnvelope,
            "description": "tai khoan rejected/suspended (ACCOUNT_DISABLED)",
        },
    },
)
async def login(body: LoginRequest, request: Request, response: Response) -> UserOut:
    """Đăng nhập (§11.2, ADR-07): kiểm mật khẩu, kiểm trạng thái, phát hành
    family refresh MỚI + set cookie phiên.

    Cột "Đăng nhập" của §11.1 (T-2.7): `pending_email`/`pending_approval` vẫn
    vào được (họ cần thấy giao diện để verify / để chờ duyệt), `rejected` và
    `suspended` nhận `403 ACCOUNT_DISABLED`.
    """
    async with session_scope() as session:
        user = await UserRepository(session).get_by_email(body.email)
        if user is not None:
            valid = await verify_password(user.password_hash, body.password)
        else:
            # Chống dò qua thời gian (xem docstring module) — vẫn trả giá
            # Argon2 dù không có user để so.
            await hash_password(_DUMMY_PASSWORD)
            valid = False

        if user is None or not valid:
            raise ApiError(
                status.HTTP_401_UNAUTHORIZED,
                ApiErrorCode.INVALID_CREDENTIALS,
                "email hoac mat khau khong dung",
            )

        # §11.1 (T-2.7) — cột "Đăng nhập". **Sau** khi mật khẩu đã đúng, không
        # bao giờ trước: kiểm trước nghĩa là ai gõ một email bất kỳ cũng biết
        # được tài khoản đó có tồn tại và đang ở trạng thái nào, đúng thứ §11.5
        # cấm rò. Cũng **trước** khi phát hành family refresh ngay dưới: một
        # tài khoản bị khoá không có việc gì phải cầm một credential 30 ngày.
        ensure_status_allowed(user.status, STATUSES_CAN_LOGIN)

        out = UserOut.model_validate(user)
        raw_refresh_token, _family_id = await RefreshTokenRepository(session).issue_new_family(
            user_id=user.id,
            ttl_days=settings.REFRESH_TOKEN_TTL_DAYS,
            user_agent=request.headers.get("user-agent"),
        )
        await session.commit()

    _set_session_cookie(response, out)
    _set_refresh_cookie(response, raw_refresh_token)
    return out


@router.post(
    "/refresh",
    status_code=status.HTTP_200_OK,
    response_model=UserOut,
    responses={
        401: {
            "model": ErrorEnvelope,
            "description": "refresh token thieu, sai, het han, hoac da bi thu hoi "
            "(UNAUTHENTICATED)",
        }
    },
)
async def refresh(
    request: Request,
    response: Response,
    raw_refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)] = None,
) -> UserOut:
    """Xoay vòng refresh token + phát hành access JWT mới (§11.2, ADR-07).

    Phát hiện tái sử dụng (Cạm bẫy T-2.3): token đã `used_at` bị trình ra lần
    nữa → thu hồi cả family, `401`. Xem `RefreshTokenRepository.rotate`.
    """
    if raw_refresh_token is None:
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED, ApiErrorCode.UNAUTHENTICATED, "thieu refresh token"
        )

    async with session_scope() as session:
        outcome = await RefreshTokenRepository(session).rotate(
            raw_token=raw_refresh_token,
            ttl_days=settings.REFRESH_TOKEN_TTL_DAYS,
            user_agent=request.headers.get("user-agent"),
        )

        if outcome.result is RotateResult.REUSED:
            # `rotate` đã thu hồi cả family — commit để giữ lại đúng đó.
            await session.commit()
            logger.warning("refresh token bi tai su dung - da thu hoi ca family")
            raise ApiError(
                status.HTTP_401_UNAUTHORIZED,
                ApiErrorCode.UNAUTHENTICATED,
                "refresh token da bi thu hoi (tai su dung)",
            )
        if outcome.result is RotateResult.INVALID:
            raise ApiError(
                status.HTTP_401_UNAUTHORIZED,
                ApiErrorCode.UNAUTHENTICATED,
                "refresh token khong hop le",
            )

        if outcome.user_id is None or outcome.raw_token is None:
            # bất biến của RefreshTokenRepository.rotate — không nên xảy ra.
            raise ApiError(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                ApiErrorCode.INTERNAL_ERROR,
                "loi noi bo, xem log cua server",
            )
        user = await UserRepository(session).get_by_id(outcome.user_id)
        if user is None:  # tài khoản đã bị xoá giữa hai lần refresh
            raise ApiError(
                status.HTTP_401_UNAUTHORIZED, ApiErrorCode.UNAUTHENTICATED, "user khong con ton tai"
            )

        out = UserOut.model_validate(user)
        await session.commit()

    _set_session_cookie(response, out)
    _set_refresh_cookie(response, outcome.raw_token)
    return out


# ═══════════════════════ POST /auth/logout (T-2.4, §11.3, C21) ══════════════


class LogoutResponse(BaseModel):
    #: Một giá trị duy nhất, luôn luôn. Logout không có kết cục thứ hai để
    #: báo: "không có gì để đóng" và "đã đóng xong" là cùng một trạng thái
    #: cuối đối với người dùng (xem docstring module), và phân biệt chúng chỉ
    #: nói cho người gọi biết cookie họ vừa gửi có thật hay không — đúng loại
    #: thông tin §11.5 không cho rò ra.
    status: Literal["logged_out"]


_LOGOUT_RESPONSE = LogoutResponse(status="logged_out")


#: Path rộng hơn `SESSION_COOKIE_PATH` mà logout cũng quét (2026-09-22).
#:
#: Scarlet chỉ **đặt** cookie phiên ở `Path=/api/v1`, nhưng một cookie cùng tên
#: ở path rộng hơn vẫn được trình duyệt gửi kèm, và `_all_session_cookies`
#: (`app/core/deps.py`) chỉ làm nó vô hại chứ không xoá được nó — `Set-Cookie`
#: là đường duy nhất xoá một cookie `HttpOnly`, và nó phải trúng ĐÚNG `Path`.
#: Không quét hai path này thì một cookie rác sống tới khi người dùng tự đi
#: dọn trong cài đặt trình duyệt, và logout không thật sự dọn sạch phiên.
_EXTRA_SESSION_PATHS = ("/", "/api")


def _clear_both_cookies(response: Response) -> None:
    """Xoá cookie phiên + cookie refresh, đúng `Path` đã đặt chúng."""
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path=SESSION_COOKIE_PATH,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    for path in _EXTRA_SESSION_PATHS:
        response.delete_cookie(
            key=SESSION_COOKIE_NAME,
            path=path,
            httponly=True,
            secure=True,
            samesite="lax",
        )
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=True,
        samesite="lax",
    )


@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
    response_model=LogoutResponse,
    # B-131: endpoint cố ý không đòi xác thực (NQ-42) nên bất kỳ ai gọi được nó
    # cũng tạo được một lượt ghi Redis + một `UPDATE` trên `refresh_tokens`.
    # Không có `user_id` để đếm theo ⇒ đếm theo IP, hạn mức của nhóm `auth`
    # (§10.6). Hạn mức này KHÔNG phá NQ-42: nó không đòi thêm gì ở client, chỉ
    # chặn gọi dồn dập — một người đăng xuất thật vẫn chỉ gọi một lần.
    dependencies=[Depends(auth_limit(ROUTE_LOGOUT))],
    responses={
        429: {"model": ErrorEnvelope, "description": "qua 5 lan/phut tu mot IP (RATE_LIMITED)"},
        503: {
            "model": ErrorEnvelope,
            "description": "khong ghi duoc blacklist vao Redis (SERVICE_UNAVAILABLE)",
        },
    },
)
async def logout(
    response: Response,
    session_cookie: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    raw_refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)] = None,
) -> LogoutResponse:
    """Đăng xuất (§11.3, C21): blacklist `jti` + thu hồi family + xoá cookie.

    KHÔNG đứng sau `Depends(get_current_user_id)` và KHÔNG từ chối token hết
    hạn — xem docstring module cho lý do đầy đủ.

    Raise:
        ApiError 503 `SERVICE_UNAVAILABLE`: không ghi được `bl:jti:` vào Redis.
            Nuốt lỗi ở đây là đúng nghĩa C21 — người dùng đọc "đã đăng xuất"
            trong khi access token của họ còn chạy thêm 15 phút.
    """
    # ── nửa Postgres: thu hồi family của phiên này (thứ tự, xem docstring) ──
    revoked_families = 0
    if raw_refresh_token is not None:
        async with session_scope() as session:
            revoked_families = await RefreshTokenRepository(session).revoke_family_by_token(
                raw_refresh_token
            )
            await session.commit()

    # ── nửa Redis: chặn đúng access token đang cầm ──
    ttl_set: int | None = None
    if session_cookie is not None:
        try:
            claims = decode_access_token(session_cookie)
        except (TokenExpiredError, TokenInvalidError):
            # Hết hạn thì không còn gì để chặn; sai chữ ký thì nó chưa bao giờ
            # là token của ai. Cả hai đều không phải lý do để từ chối đóng cửa.
            claims = None
        if claims is not None:
            try:
                ttl_set = await block_jti(get_redis(), claims)
            except Exception as exc:
                logger.exception("khong ghi duoc bl:jti cho user %s", claims.user_id)
                raise ApiError(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    ApiErrorCode.SERVICE_UNAVAILABLE,
                    "khong dang xuat duoc, hay thu lai",
                ) from exc

    _clear_both_cookies(response)
    logger.info(
        "logout: da thu hoi %d refresh token, bl:jti TTL=%s",
        revoked_families,
        ttl_set,
    )
    return _LOGOUT_RESPONSE


# ═════════ POST /auth/forgot-password + /reset-password (T-2.5, §11.5) ══════


class ForgotPasswordRequest(BaseModel):
    email: EmailStr
    #: Cùng lối `RegisterRequest.turnstile_token` — §11.6 chỉ định captcha cho cả
    #: hai form: đăng ký **và** quên mật khẩu.
    turnstile_token: str | None = None


class ForgotPasswordResponse(BaseModel):
    message: str


#: Một hằng số, cùng lối `_REGISTER_RESPONSE`/`_RESEND_RESPONSE`: DoD đòi
#: response của email không tồn tại giống HỆT response của email có thật.
_FORGOT_PASSWORD_RESPONSE = ForgotPasswordResponse(
    message="neu email nay ton tai, mot lien ket dat lai mat khau da duoc gui"
)


class ResetPasswordRequest(BaseModel):
    token: str
    password: str


class ResetPasswordResponse(BaseModel):
    #: Một giá trị duy nhất. Không trả thông tin user: endpoint này KHÔNG đăng
    #: nhập ai cả (NQ-44), nên nó không có danh tính nào để nói.
    status: Literal["reset"]


_RESET_RESPONSE = ResetPasswordResponse(status="reset")

#: Câu trả lời CHUNG cho cả ba kiểu token hỏng — xem docstring module.
_RESET_TOKEN_MSG = "lien ket dat lai mat khau khong hop le hoac da het han"


async def _send_reset_email(email: str, raw_token: str) -> None:
    """Best-effort, cùng lối `_send_verification_email`: SMTP hỏng không được làm
    `forgot-password` trả 500 — làm vậy là nói cho người gọi biết email đó có
    thật (§11.5), và token thì đã commit rồi."""
    # Đường dẫn của FE, không của API — nó đi vào một lá thư cho người thật
    # bấm. `/dat-lai-mat-khau` là `PATHS.resetPassword` của
    # `frontend/src/app/paths.ts`; tới T-3.1a nó còn là một trang tạm, nên
    # chuỗi ở đây trỏ vào `/reset-password` — một đường KHÔNG có trong bảng
    # route, tức mọi link đặt lại mật khẩu đều rơi vào trang 404. Sửa ở
    # T-3.1b, cùng lúc màn hình thật ra đời. Cặp với `verify_url` bên trên,
    # vốn đã trùng `PATHS.verifyEmail` từ đầu.
    reset_url = f"{settings.PUBLIC_BASE_URL}/dat-lai-mat-khau?token={raw_token}"
    try:
        await mailer.send(
            template="reset_password",
            to=email,
            ctx={"reset_url": reset_url, "ttl_minutes": settings.EMAIL_TOKEN_TTL_MIN},
        )
    except Exception:
        logger.exception("gui email dat lai mat khau that bai cho %s", email)


@router.post(
    "/forgot-password",
    status_code=status.HTTP_200_OK,
    response_model=ForgotPasswordResponse,
    dependencies=[Depends(email_send_limit(ROUTE_FORGOT_PASSWORD))],
    responses={
        400: {
            "model": ErrorEnvelope,
            "description": "thieu token Turnstile hoac token khong hop le (TURNSTILE_FAILED)",
        },
        429: {"model": ErrorEnvelope, "description": "qua 3 lan/gio tu mot IP (RATE_LIMITED)"},
        503: {
            "model": ErrorEnvelope,
            "description": "khong hoi duoc Cloudflare de xac minh captcha (SERVICE_UNAVAILABLE)",
        },
    },
)
async def forgot_password(body: ForgotPasswordRequest, request: Request) -> ForgotPasswordResponse:
    """Xin link đặt lại mật khẩu (§11.5). **Luôn** 200, luôn cùng một body.

    Không kiểm `status` tài khoản: bảng §11.1 là việc của T-2.7, và rẽ nhánh
    theo trạng thái ở đây sẽ làm response nói ra điều §11.5 cấm.

    Turnstile (T-2.6) chạy trước phép `SELECT` đầu tiên và **không** đọc
    `email`, nên nó không mở thêm nhánh nào cho §11.5 — xem điểm 3 của
    docstring module. Hạn mức 3/giờ (NQ-43) vẫn chạy trước nó: dependency đếm
    lượt *thử*, và một lượt thử bị captcha chặn cũng là một lượt thử.
    """
    await verify_turnstile(body.turnstile_token, remote_ip=client_ip(request))

    raw_token: str | None = None
    email_to_send: str | None = None
    async with session_scope() as session:
        user = await UserRepository(session).get_by_email(body.email)
        if user is not None:
            raw_token = await EmailTokenRepository(session).issue(
                user_id=user.id,
                purpose=EmailTokenPurpose.RESET,
                ttl_minutes=settings.EMAIL_TOKEN_TTL_MIN,
            )
            email_to_send = user.email
            await session.commit()
        # else: không có user — không phát hành token, không gửi thư, không
        # đọc/ghi gì thêm (§11.5).

    if raw_token is not None and email_to_send is not None:
        await _send_reset_email(email_to_send, raw_token)

    return _FORGOT_PASSWORD_RESPONSE


@router.post(
    "/reset-password",
    status_code=status.HTTP_200_OK,
    response_model=ResetPasswordResponse,
    dependencies=[Depends(auth_limit(ROUTE_RESET_PASSWORD))],
    responses={
        400: {
            "model": ErrorEnvelope,
            "description": "token khong ton tai, da dung, hoac het han (TOKEN_INVALID)",
        },
        422: {
            "model": ErrorEnvelope,
            "description": "mat khau qua ngan (PASSWORD_TOO_SHORT) "
            "hoac qua pho bien (PASSWORD_TOO_WEAK)",
        },
        429: {"model": ErrorEnvelope, "description": "qua 5 lan/phut tu mot IP (RATE_LIMITED)"},
        503: {
            "model": ErrorEnvelope,
            "description": "khong dat duoc moc thu hoi phien vao Redis (SERVICE_UNAVAILABLE)",
        },
    },
)
async def reset_password(body: ResetPasswordRequest, response: Response) -> ResetPasswordResponse:
    """Đặt mật khẩu mới bằng token trong email (§11.5, §11.6) + thu hồi **mọi**
    phiên (§11.3, Cạm bẫy T-2.5).

    KHÔNG tự đăng nhập (NQ-44, B-130) — xem docstring module.
    """
    # Kiểm mật khẩu TRƯỚC `hash_password` (~100 ms, 192 MiB) — xem docstring
    # module, kể cả phần nói rõ thứ tự này KHÔNG phải thứ bảo vệ token.
    if len(body.password) < settings.PASSWORD_MIN_LENGTH:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ApiErrorCode.PASSWORD_TOO_SHORT,
            f"mat khau phai co it nhat {settings.PASSWORD_MIN_LENGTH} ky tu",
        )
    if is_common_password(body.password):
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ApiErrorCode.PASSWORD_TOO_WEAK,
            "mat khau qua pho bien, hay chon mat khau khac",
        )

    password_hash = await hash_password(body.password)

    async with session_scope() as session:
        outcome = await EmailTokenRepository(session).consume(
            raw_token=body.token, purpose=EmailTokenPurpose.RESET
        )
        if outcome.result is not ConsumeResult.OK or outcome.user_id is None:
            # NOT_FOUND / ALREADY_USED / EXPIRED — một câu trả lời cho cả ba.
            raise ApiError(
                status.HTTP_400_BAD_REQUEST, ApiErrorCode.TOKEN_INVALID, _RESET_TOKEN_MSG
            )

        user_id = outcome.user_id
        if not await UserRepository(session).set_new_password(user_id, password_hash):
            # Token còn hạn của một tài khoản đã xoá mềm. Cùng câu trả lời với
            # token hỏng: sự tồn tại của tài khoản không phải thứ để rò ra.
            raise ApiError(
                status.HTTP_400_BAD_REQUEST, ApiErrorCode.TOKEN_INVALID, _RESET_TOKEN_MSG
            )

        try:
            # Hai nửa của §11.3 trong MỘT hàm (T-2.4) — chạy trong transaction
            # này, trước `commit`. Nửa Redis trượt ⇒ ngoại lệ ⇒ `session_scope`
            # rollback ⇒ mật khẩu KHÔNG đổi: thà người dùng bấm lại link còn hơn
            # đổi xong mật khẩu mà phiên của kẻ tấn công vẫn sống thêm 15 phút.
            await revoke_all_sessions(session, get_redis(), user_id)
        except Exception as exc:
            logger.exception("khong thu hoi duoc phien khi dat lai mat khau cho %s", user_id)
            raise ApiError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                ApiErrorCode.SERVICE_UNAVAILABLE,
                "khong dat lai duoc mat khau, hay thu lai",
            ) from exc

        await session.commit()

    # Phiên cũ vừa bị thu hồi; giữ lại cookie chỉ khiến tab này nhận `401` ở
    # request kế tiếp mà không ai hiểu vì sao (NQ-44).
    _clear_both_cookies(response)
    logger.info("dat lai mat khau xong cho user %s, da thu hoi moi phien", user_id)
    return _RESET_RESPONSE


@router.get(
    "/me",
    status_code=status.HTTP_200_OK,
    response_model=ProfileOut,
    # §11.1 (T-2.7) — cột "Xem UI". Route duy nhất của router `auth` đòi tài
    # khoản dùng được; `logout` cố ý KHÔNG (NQ-42), phần còn lại là công khai.
    # Xem `api/v1/__init__.py` cho danh sách router được gắn cả cụm.
    dependencies=[Depends(require_app_access)],
    responses={
        403: {
            "model": ErrorEnvelope,
            "description": "tai khoan rejected/suspended (ACCOUNT_DISABLED)",
        }
    },
)
async def me(user_id: Annotated[UUID, Depends(get_current_user_id)]) -> ProfileOut:
    """Thông tin user hiện tại — đi qua `get_current_user_id` như mọi route
    khác (§20), không tự đọc cookie.

    `403 ACCOUNT_DISABLED` cho `rejected`/`suspended` chứ không phải `200` kèm
    `status`: §11.1 để trống cả ô "Xem UI" của hai hàng ấy, và FE đọc được
    đúng câu chuyện từ mã lỗi — nó không cần đọc `status` rồi tự nghĩ ra luật
    lần thứ hai (đúng cạm bẫy "mỗi endpoint một luật" của task này).

    **Bốn nhóm trong một response** (§18.1: *"User + tier + quota còn lại +
    trạng thái"*, B-158/NQ-81): hồ sơ + trạng thái, `quota` hai cửa sổ,
    `message_max_chars`, `default_model`. Ba task FE của P3 (T-3.4, T-3.6,
    T-3.11) đọc ba nhóm khác nhau của **cùng** một response chứ không sửa
    `UserOut` ở ba commit — đó là toàn bộ lý do gộp chúng vào đây.

    `read_snapshot` đứng **trong** `session_scope` vì `refill_if_empty` (RR-7)
    cần một session Postgres để phân biệt "chưa tiêu gì" với "Redis vừa mất
    dữ liệu". Nó **không** ném khi Redis chết — xem `app/quota/snapshot.py`.
    """
    async with session_scope() as session:
        user = await UserRepository(session).get_by_id(user_id)
        if user is None:
            raise ApiError(
                status.HTTP_401_UNAUTHORIZED, ApiErrorCode.UNAUTHENTICATED, "user khong con ton tai"
            )
        # Đọc ra schema TRƯỚC khi làm bất cứ việc gì khác với session: sau đó
        # `user` vẫn còn sống, nhưng thói quen ở cả `conversations.py` là chốt
        # hình dạng ngay khi còn cầm hàng trong tay.
        profile = UserOut.model_validate(user)
        quota = await read_snapshot(session, user_id=user_id)

    return ProfileOut(
        **profile.model_dump(),
        quota=quota,
        message_max_chars=settings.MESSAGE_MAX_CHARS,
        quota_warn_remaining_pct=settings.QUOTA_WARN_REMAINING_PCT,
    )
