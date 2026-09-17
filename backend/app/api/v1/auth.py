"""`POST /auth/register`, `/verify-email`, `/resend-verification` (§11.1,
§11.5, §11.6, UC-01) — T-2.1, T-2.2. `POST /auth/login`, `/refresh`,
`GET /auth/me` (§11.2, ADR-07) — T-2.3. `POST /auth/logout` (§11.3, C21) — T-2.4.

KH tham chiếu: §11.5, §11.2, §11.3, UC-01, ADR-07, C21 · CLAUDE.md A3 ·
tasks.md T-2.2, T-2.3, T-2.4, NQ-36.

┌──────────────────────────────────────────────────────────────────────────┐
│  CẠM BẪY CỦA T-2.1: chống dò email (§11.5)                                │
└──────────────────────────────────────────────────────────────────────────┘

"Trả lỗi 'email đã tồn tại' là cho phép người lạ dò xem ai đã đăng ký."
`register` vì vậy cố ý KHÔNG có hai nhánh response khác nhau:

1. Cả hai đường (email mới / email đã tồn tại) đều trả về đúng MỘT hằng số
   `_PHAN_HOI_DANG_KY` — cùng status code, cùng body, byte-for-byte (DoD).
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

Turnstile (T-2.6) CHƯA có ở `register` — nối tiếp đúng endpoint này, không
viết lại nó.

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
nhánh "không có user" vẫn băm `_MAT_KHAU_GIA` thay vì trả lỗi ngay — nếu không,
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
from app.core.blacklist import chan_jti
from app.core.deps import SESSION_COOKIE_NAME, get_current_user_id
from app.core.errors import ApiError, ApiErrorCode, ErrorEnvelope
from app.core.mailer import mailer
from app.core.redis import get_redis
from app.core.security import hash_password, mat_khau_qua_pho_bien, verify_password
from app.db.models import EmailTokenPurpose, UserRole, UserStatus
from app.db.repositories.email_tokens import ConsumeResult, EmailTokenRepository
from app.db.repositories.refresh_tokens import RefreshTokenRepository, RotateResult
from app.db.repositories.users import UserRepository
from app.db.session import session_scope

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
_MAT_KHAU_GIA = "mat-khau-gia-chi-de-giu-thoi-gian-phan-hoi-dong-deu-000"


class DangKyRequest(BaseModel):
    email: EmailStr
    password: str


class DangKyResponse(BaseModel):
    message: str


#: Response CỐ ĐỊNH cho cả hai nhánh (email mới / email đã tồn tại) — DoD đòi
#: byte-for-byte giống nhau, nên đây là MỘT hằng số duy nhất, không phải hai
#: chỗ gõ tay cùng một câu (dễ lệch một khoảng trắng).
_PHAN_HOI_DANG_KY = DangKyResponse(
    message=(
        "neu email hop le va chua duoc dang ky truoc do, "
        "tai khoan da duoc tao va dang cho xac thuc email"
    )
)


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class ResendVerificationResponse(BaseModel):
    message: str


#: Cùng lối với `_PHAN_HOI_DANG_KY`: một hằng số, không rẽ nhánh theo email có
#: tồn tại / đã verify hay chưa (§11.5).
_PHAN_HOI_RESEND = ResendVerificationResponse(
    message=("neu email nay ton tai va chua duoc xac thuc, mot email xac thuc moi da duoc gui")
)


class VerifyEmailRequest(BaseModel):
    token: str


class VerifyEmailResponse(BaseModel):
    #: `verified`: token hợp lệ (lần đầu hoặc đã dùng trước đó — idempotent).
    #: `expired`: hết hạn, FE hiện trang "gửi lại" — vẫn HTTP 200 (DoD T-2.2).
    status: Literal["verified", "expired"]


async def _gui_email_xac_thuc(email: str, raw_token: str) -> None:
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
    response_model=DangKyResponse,
    responses={
        422: {
            "model": ErrorEnvelope,
            "description": "mat khau qua ngan (PASSWORD_TOO_SHORT) "
            "hoac qua pho bien (PASSWORD_TOO_WEAK)",
        }
    },
)
async def register(body: DangKyRequest) -> DangKyResponse:
    """Đăng ký (UC-01): tạo user `status='pending_email'`, tier mặc định,
    phát hành token verify và gửi email xác thực (T-2.2).

    Không verify Turnstile (T-2.6) — nối tiếp sau, cùng một đường dẫn này.
    """
    if len(body.password) < settings.PASSWORD_MIN_LENGTH:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ApiErrorCode.PASSWORD_TOO_SHORT,
            f"mat khau phai co it nhat {settings.PASSWORD_MIN_LENGTH} ky tu",
        )
    if mat_khau_qua_pho_bien(body.password):
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
    # `_gui_email_xac_thuc`.
    if raw_token is not None:
        await _gui_email_xac_thuc(body.email, raw_token)

    return _PHAN_HOI_DANG_KY


@router.post(
    "/resend-verification",
    status_code=status.HTTP_200_OK,
    response_model=ResendVerificationResponse,
)
async def resend_verification(body: ResendVerificationRequest) -> ResendVerificationResponse:
    """Gửi lại email verify (UC-01). Chống dò (§11.5): response cố định."""
    raw_token: str | None = None
    email_de_gui: str | None = None
    async with session_scope() as session:
        user = await UserRepository(session).get_by_email(body.email)
        if user is not None and user.status == UserStatus.PENDING_EMAIL:
            raw_token = await EmailTokenRepository(session).issue(
                user_id=user.id,
                purpose=EmailTokenPurpose.VERIFY,
                ttl_minutes=settings.EMAIL_TOKEN_TTL_MIN,
            )
            email_de_gui = user.email
            await session.commit()
        # else: email không tồn tại, hoặc đã qua khỏi pending_email — không
        # phát hành token, không gửi mail, không đọc/ghi gì thêm (§11.5).

    if raw_token is not None and email_de_gui is not None:
        await _gui_email_xac_thuc(email_de_gui, raw_token)

    return _PHAN_HOI_RESEND


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

        if outcome.result is ConsumeResult.OK:
            uid: UUID | None = outcome.user_id
            if uid is None:  # bất biến của EmailTokenRepository.consume — không nên xảy ra
                raise ApiError(
                    status.HTTP_500_INTERNAL_SERVER_ERROR,
                    ApiErrorCode.INTERNAL_ERROR,
                    "loi noi bo, xem log cua server",
                )
            await UserRepository(session).mark_email_verified(uid)
        # ConsumeResult.ALREADY_USED: không có gì để đổi thêm — idempotent.

        await session.commit()

    return VerifyEmailResponse(status="verified")


# ═══════════════════ POST /auth/login, /refresh, GET /auth/me (T-2.3) ═══════


class DangNhapRequest(BaseModel):
    email: EmailStr
    password: str


class NguoiDungRa(BaseModel):
    """Thông tin công khai của user hiện tại — dùng chung cho `/login`,
    `/refresh`, `/me` (một hình dạng, một chỗ để đúng)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    display_name: str | None
    status: UserStatus
    role: UserRole
    tier_name: str


def _dat_cookie_phien(response: Response, nguoi_dung: NguoiDungRa) -> None:
    """Set cookie phiên mang access JWT (§11.2, NQ-36) — KHÔNG trả JWT trong body."""
    access_token = encode_access_token(
        user_id=nguoi_dung.id,
        role=nguoi_dung.role,
        tier=nguoi_dung.tier_name,
        status=nguoi_dung.status,
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


def _dat_cookie_refresh(response: Response, raw_refresh_token: str) -> None:
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
    response_model=NguoiDungRa,
    responses={
        401: {
            "model": ErrorEnvelope,
            "description": "email hoac mat khau sai (INVALID_CREDENTIALS)",
        }
    },
)
async def login(body: DangNhapRequest, request: Request, response: Response) -> NguoiDungRa:
    """Đăng nhập (§11.2, ADR-07): kiểm mật khẩu, phát hành family refresh MỚI
    + set cookie phiên. KHÔNG kiểm `status` (pending_email/pending_approval
    đều đăng nhập được — bảng §11.1; chặn theo trạng thái là việc của T-2.7)."""
    async with session_scope() as session:
        user = await UserRepository(session).get_by_email(body.email)
        if user is not None:
            hop_le = await verify_password(user.password_hash, body.password)
        else:
            # Chống dò qua thời gian (xem docstring module) — vẫn trả giá
            # Argon2 dù không có user để so.
            await hash_password(_MAT_KHAU_GIA)
            hop_le = False

        if user is None or not hop_le:
            raise ApiError(
                status.HTTP_401_UNAUTHORIZED,
                ApiErrorCode.INVALID_CREDENTIALS,
                "email hoac mat khau khong dung",
            )

        ra = NguoiDungRa.model_validate(user)
        raw_refresh_token, _family_id = await RefreshTokenRepository(session).issue_new_family(
            user_id=user.id,
            ttl_days=settings.REFRESH_TOKEN_TTL_DAYS,
            user_agent=request.headers.get("user-agent"),
        )
        await session.commit()

    _dat_cookie_phien(response, ra)
    _dat_cookie_refresh(response, raw_refresh_token)
    return ra


@router.post(
    "/refresh",
    status_code=status.HTTP_200_OK,
    response_model=NguoiDungRa,
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
) -> NguoiDungRa:
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

        ra = NguoiDungRa.model_validate(user)
        await session.commit()

    _dat_cookie_phien(response, ra)
    _dat_cookie_refresh(response, outcome.raw_token)
    return ra


# ═══════════════════════ POST /auth/logout (T-2.4, §11.3, C21) ══════════════


class DangXuatResponse(BaseModel):
    #: Một giá trị duy nhất, luôn luôn. Logout không có kết cục thứ hai để
    #: báo: "không có gì để đóng" và "đã đóng xong" là cùng một trạng thái
    #: cuối đối với người dùng (xem docstring module), và phân biệt chúng chỉ
    #: nói cho người gọi biết cookie họ vừa gửi có thật hay không — đúng loại
    #: thông tin §11.5 không cho rò ra.
    status: Literal["logged_out"]


_PHAN_HOI_DANG_XUAT = DangXuatResponse(status="logged_out")


def _xoa_hai_cookie(response: Response) -> None:
    """Xoá cookie phiên + cookie refresh, đúng `Path` đã đặt chúng."""
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path=SESSION_COOKIE_PATH,
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
    response_model=DangXuatResponse,
    responses={
        503: {
            "model": ErrorEnvelope,
            "description": "khong ghi duoc blacklist vao Redis (SERVICE_UNAVAILABLE)",
        }
    },
)
async def logout(
    response: Response,
    session_cookie: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    raw_refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)] = None,
) -> DangXuatResponse:
    """Đăng xuất (§11.3, C21): blacklist `jti` + thu hồi family + xoá cookie.

    KHÔNG đứng sau `Depends(get_current_user_id)` và KHÔNG từ chối token hết
    hạn — xem docstring module cho lý do đầy đủ.

    Raise:
        ApiError 503 `SERVICE_UNAVAILABLE`: không ghi được `bl:jti:` vào Redis.
            Nuốt lỗi ở đây là đúng nghĩa C21 — người dùng đọc "đã đăng xuất"
            trong khi access token của họ còn chạy thêm 15 phút.
    """
    # ── nửa Postgres: thu hồi family của phiên này (thứ tự, xem docstring) ──
    so_family_da_thu_hoi = 0
    if raw_refresh_token is not None:
        async with session_scope() as session:
            so_family_da_thu_hoi = await RefreshTokenRepository(session).thu_hoi_family_theo_token(
                raw_refresh_token
            )
            await session.commit()

    # ── nửa Redis: chặn đúng access token đang cầm ──
    ttl_da_dat: int | None = None
    if session_cookie is not None:
        try:
            claims = decode_access_token(session_cookie)
        except (TokenExpiredError, TokenInvalidError):
            # Hết hạn thì không còn gì để chặn; sai chữ ký thì nó chưa bao giờ
            # là token của ai. Cả hai đều không phải lý do để từ chối đóng cửa.
            claims = None
        if claims is not None:
            try:
                ttl_da_dat = await chan_jti(get_redis(), claims)
            except Exception as loi:
                logger.exception("khong ghi duoc bl:jti cho user %s", claims.user_id)
                raise ApiError(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    ApiErrorCode.SERVICE_UNAVAILABLE,
                    "khong dang xuat duoc, hay thu lai",
                ) from loi

    _xoa_hai_cookie(response)
    logger.info(
        "logout: da thu hoi %d refresh token, bl:jti TTL=%s",
        so_family_da_thu_hoi,
        ttl_da_dat,
    )
    return _PHAN_HOI_DANG_XUAT


@router.get("/me", status_code=status.HTTP_200_OK, response_model=NguoiDungRa)
async def me(user_id: Annotated[UUID, Depends(get_current_user_id)]) -> NguoiDungRa:
    """Thông tin user hiện tại — đi qua `get_current_user_id` như mọi route
    khác (§20), không tự đọc cookie."""
    async with session_scope() as session:
        user = await UserRepository(session).get_by_id(user_id)
        if user is None:
            raise ApiError(
                status.HTTP_401_UNAUTHORIZED, ApiErrorCode.UNAUTHENTICATED, "user khong con ton tai"
            )
        ra = NguoiDungRa.model_validate(user)

    return ra
