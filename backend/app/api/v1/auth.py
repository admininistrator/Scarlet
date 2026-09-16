"""`POST /auth/register` (§11.1, §11.5, §11.6, UC-01) — T-2.1.

KH tham chiếu: §11.1, §11.6, UC-01 · CLAUDE.md A3 · tasks.md T-2.1.

┌──────────────────────────────────────────────────────────────────────────┐
│  CẠM BẪY CỦA TASK NÀY: chống dò email (§11.5)                            │
└──────────────────────────────────────────────────────────────────────────┘

"Trả lỗi 'email đã tồn tại' là cho phép người lạ dò xem ai đã đăng ký."
Handler dưới đây vì vậy cố ý KHÔNG có hai nhánh response khác nhau:

1. Cả hai đường (email mới / email đã tồn tại) đều trả về đúng MỘT hằng số
   `_PHAN_HOI_DANG_KY` — cùng status code, cùng body, byte-for-byte (DoD).
2. Mật khẩu vẫn được băm bằng Argon2 (~50–200 ms) DÙ email đã tồn tại, để
   thời gian phản hồi không trở thành một kênh ngầm (đường "đã tồn tại" mà
   nhanh hơn hẳn đường "mới" là một cách dò khác, tinh vi hơn status code).
3. `UserRepository.create_pending_user` trả `None` thay vì raise khi UNIQUE
   của `email` va chạm — không có exception riêng để lộ ra thành hai nhánh xử
   lý ở đây.

Kiểm độ dài/độ phổ biến của mật khẩu chạy TRƯỚC bước trên và không phụ thuộc
email, nên `422` ở đó không lộ gì (đúng cho cả email mới lẫn email đã có).

Turnstile (T-2.6) và gửi email xác thực (T-2.2) CHƯA có ở đây — hai task đó
nối tiếp đúng endpoint này, không viết lại nó.
"""

from __future__ import annotations

from fastapi import APIRouter, status
from pydantic import BaseModel, EmailStr

from app.config.settings import settings
from app.core.errors import ApiError, ApiErrorCode, ErrorEnvelope
from app.core.security import hash_password, mat_khau_qua_pho_bien
from app.db.repositories.users import UserRepository
from app.db.session import session_scope

router = APIRouter(prefix="/auth", tags=["auth"])


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
    """Đăng ký (UC-01): tạo user `status='pending_email'`, tier mặc định.

    Không verify Turnstile (T-2.6), không gửi email (T-2.2) — cả hai nối tiếp
    sau, cùng một đường dẫn này.
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

    async with session_scope() as session:
        user = await UserRepository(session).create_pending_user(
            email=body.email, password_hash=password_hash
        )
        if user is not None:
            await session.commit()
        # else: email đã tồn tại — repository đã tự rollback, không có gì để
        # commit. Không đọc/ghi gì thêm: mọi thông tin về user đã có KHÔNG
        # được phép rò tới response (§11.5).

    return _PHAN_HOI_DANG_KY
