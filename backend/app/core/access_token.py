"""Access JWT — mã hoá/giải mã + xác minh (§11.2, ADR-07) — T-2.3, T-2.4.

KH tham chiếu: §11.2, §11.3, ADR-07 · CLAUDE.md A3, A4 · tasks.md T-2.3, T-2.4, NQ-36.

Claim đúng §11.2: `sub` (user id), `jti` (cho blacklist T-2.4), `role`,
`tier`, `status`, `iat`, `exp`. `get_current_user_id` (app/core/deps.py) hôm
nay chỉ đọc `sub`; `role`/`tier`/`status` có mặt sẵn để T-2.7
(`require_status`) đọc lại từ payload thay vì phải xin thêm một chuyến
`SELECT` — nhưng việc ĐỌC chúng là việc của task đó, không phải task này.

**T-2.4 thêm `issued_at`/`expires_at` vào `AccessTokenClaims`** (đúng hai claim
`iat`/`exp` mà `encode_access_token` vẫn luôn ghi ra, chỉ là chưa ai đọc lại).
Cả hai là dữ liệu vào của §11.3, không phải tiện nghi: `expires_at` cho ra TTL
của `bl:jti:{jti}` ("bằng đúng thời gian sống còn lại của token" — Cạm bẫy
T-2.4), và `issued_at` là vế trái của phép so `iat < bl:user:{uid}`. Không đọc
chúng ở đây thì `app/core/blacklist.py` phải tự `jwt.decode` lần thứ hai, tức
có hai chỗ biết PyJWT ném ra kiểu gì — đúng thứ docstring dưới đây loại bỏ.

Bí mật ký là `settings.JWT_SECRET` — biến bắt buộc, đã có từ T-0.3 (A4). TTL là
`settings.ACCESS_TOKEN_TTL_MIN` — một *giới hạn*, không phải hằng trong file
này (A3, §19.2 L4).

Hai ngoại lệ riêng (`TokenExpiredError`, `TokenInvalidError`) thay vì để
`jwt.exceptions.*` rò ra ngoài module: `app/core/deps.py` cần phân biệt đúng
HAI trường hợp cho DoD T-2.3 ("access token hết hạn → 401 `TOKEN_EXPIRED`,
phân biệt với token sai"), và bọc lại ở đây là chỗ DUY NHẤT phải biết PyJWT
ném ra những kiểu gì.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from app.config.settings import settings
from app.db.models import UserRole, UserStatus

_ALGORITHM = "HS256"


class TokenExpiredError(Exception):
    """Chữ ký hợp lệ nhưng đã qua `exp`."""


class TokenInvalidError(Exception):
    """Sai chữ ký, sai định dạng, hoặc claim bắt buộc thiếu/không đọc được."""


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    user_id: uuid.UUID
    jti: str
    role: UserRole
    tier: str
    status: UserStatus
    #: Claim `iat`/`exp` của §11.2, đã đổi sang `datetime` có múi giờ (T-2.4).
    #: Tên dài thay vì `iat`/`exp` cùng lối với `user_id` thay vì `sub`: kiểu ở
    #: đây là kiểu của miền vấn đề, không phải hình dạng nguyên văn của payload.
    issued_at: datetime
    expires_at: datetime


def encode_access_token(
    *, user_id: uuid.UUID, role: UserRole, tier: str, status: UserStatus, ttl_minutes: int
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "jti": uuid.uuid4().hex,
        "role": role.value,
        "tier": tier,
        "status": status.value,
        "iat": now,
        "exp": now + timedelta(minutes=ttl_minutes),
    }
    return jwt.encode(payload, settings.JWT_SECRET.get_secret_value(), algorithm=_ALGORITHM)


def decode_access_token(raw_token: str) -> AccessTokenClaims:
    """Xác minh chữ ký + `exp`, trả về claim đã ép kiểu.

    Raise:
        TokenExpiredError: chữ ký đúng, `exp` đã qua.
        TokenInvalidError: mọi trường hợp khác (sai chữ ký, sai định dạng,
            thiếu claim, claim sai kiểu/giá trị không nằm trong enum).
    """
    try:
        payload = jwt.decode(
            raw_token, settings.JWT_SECRET.get_secret_value(), algorithms=[_ALGORITHM]
        )
    except jwt.ExpiredSignatureError as loi:
        raise TokenExpiredError from loi
    except jwt.InvalidTokenError as loi:
        raise TokenInvalidError from loi

    try:
        return AccessTokenClaims(
            user_id=uuid.UUID(payload["sub"]),
            jti=payload["jti"],
            role=UserRole(payload["role"]),
            tier=payload["tier"],
            status=UserStatus(payload["status"]),
            issued_at=datetime.fromtimestamp(payload["iat"], UTC),
            expires_at=datetime.fromtimestamp(payload["exp"], UTC),
        )
    except (KeyError, ValueError, TypeError, OverflowError, OSError) as loi:
        # `OverflowError`/`OSError`: `fromtimestamp` với một `iat`/`exp` nằm
        # ngoài tầm của hệ điều hành. PyJWT đã bảo đảm chúng là số, nhưng "là
        # số" và "là một mốc thời gian có thật" là hai chuyện khác nhau, và một
        # token bịa đặt không có quyền làm nổ handler thành 500.
        raise TokenInvalidError from loi
