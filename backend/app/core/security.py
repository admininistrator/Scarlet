"""Argon2id hash/verify + kiểm mật khẩu yếu (§11.6) — T-2.1.

KH tham chiếu: §11.6 · CLAUDE.md A3.

Tham số Argon2 đọc từ `settings` (`ARGON2_TIME_COST`, `ARGON2_MEMORY_KIB`):
đổi tham số là đổi một dòng `.env`, không phải sửa file này (A3, A4).

Bấm/kiểm chạy qua `asyncio.to_thread`: Argon2id cố ý CHẬM (mục tiêu 50–200 ms,
xem DoD T-2.1) để chống brute-force offline, và tiến trình `api` chạy chung
một event loop cho mọi request — kể cả SSE đang chảy (§3/A1). Chạy đồng bộ
ngay trong handler sẽ khoá cả tiến trình trong đúng từng ấy mili-giây mỗi lần
có ai đăng ký/đăng nhập.
"""

from __future__ import annotations

import asyncio

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerificationError, VerifyMismatchError
from zxcvbn import zxcvbn

from app.config.settings import settings

#: Một instance dùng chung — tạo `PasswordHasher` không tốn gì (không hash gì
#: lúc khởi tạo), nhưng tạo lại mỗi lần gọi là một chỗ phân bổ thừa vô nghĩa.
_hasher = PasswordHasher(
    time_cost=settings.ARGON2_TIME_COST,
    memory_cost=settings.ARGON2_MEMORY_KIB,
)


async def hash_password(password: str) -> str:
    """Trả về chuỗi hash dạng `$argon2id$...` (DoD T-2.1)."""
    return await asyncio.to_thread(_hasher.hash, password)


async def verify_password(password_hash: str, password: str) -> bool:
    """`True` nếu mật khẩu khớp hash.

    Tham số Argon2 dùng để kiểm được ĐỌC TỪ chính chuỗi `password_hash` (tự
    mô tả, đúng định dạng PHC) — không cần `_hasher` hiện tại trùng tham số
    với lúc hash, nên đổi `ARGON2_TIME_COST`/`ARGON2_MEMORY_KIB` trong `.env`
    không làm hỏng hash cũ đã lưu.
    """
    try:
        return await asyncio.to_thread(_hasher.verify, password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHash):
        return False


def mat_khau_qua_pho_bien(password: str) -> bool:
    """`True` nếu mật khẩu quá yếu/phổ biến (điểm zxcvbn dưới ngưỡng cấu hình).

    §11.6 cho phép `zxcvbn` HOẶC một danh sách 10k mật khẩu phổ biến. Chọn
    zxcvbn: nó mang sẵn tập tần suất mật khẩu rò rỉ thật (không phải một file
    `.txt` phải tự tải và không có cách xác minh nguồn gốc trong repo này),
    chạy hoàn toàn offline sau khi cài, và bắt được cả biến thể ("Password1234"
    hay "passw0rd1234") mà một danh sách tĩnh chỉ khớp đúng chuỗi mới bắt được.
    """
    ket_qua = zxcvbn(password)
    return bool(ket_qua["score"] < settings.PASSWORD_MIN_ZXCVBN_SCORE)
