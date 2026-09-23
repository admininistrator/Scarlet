"""Đồng hồ và access token — B-194.

KH tham chiếu: §11.2, §11.3 · CLAUDE.md A3 · tasks.md B-194, rà P2 2026-09-20.

Bộ test này canh đúng **một** quyết định: PyJWT không được kiểm `iat`, còn
`exp` thì phải kiểm nghiêm như cũ. Hai vế đi cùng nhau, vì cách sửa bị loại
(`leeway=N`) đóng được vế đầu nhưng đồng thời nới vế sau — và một bộ test chỉ
kiểm vế đầu sẽ **xanh** với cả hai cách sửa, tức không phân biệt được cách
đúng với cách đắt.

Vì sao `iat` ở tương lai là chuyện có thật chứ không phải ca giả tưởng: từ
PyJWT 2.10, `_validate_iat` ném `ImmatureSignatureError` khi `iat > now`, với
dung sai mặc định **0 giây**. Đồng hồ WSL2 trên máy dev lùi lại nhiều lần
(`dmesg`: `systemd-journald: Time jumped backwards, rotating.`), nên một token
vừa ký xong có thể tự từ chối chính nó. Đo được: `test_account_states.py` đỏ
1 trong 3 lần chạy cả bộ, `rejected` nhận `401` thay vì `403`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.config.settings import settings
from app.core.access_token import (
    TokenExpiredError,
    TokenInvalidError,
    decode_access_token,
    encode_access_token,
)
from app.db.models import UserRole, UserStatus

_ALGORITHM = "HS256"


def _token_with_times(*, iat: datetime, exp: datetime, user_id: uuid.UUID) -> str:
    """Ký thẳng bằng PyJWT để đặt `iat`/`exp` vào đúng chỗ muốn đo.

    `encode_access_token` cố tình không nhận `iat` — nó luôn dùng `now()`, và
    đó là hành vi đúng. Muốn dựng một token \"đến từ tương lai\" thì phải đi
    vòng qua nó, chứ không phải nới cửa của nó ra cho test.
    """
    payload = {
        "sub": str(user_id),
        "jti": uuid.uuid4().hex,
        "role": UserRole.USER.value,
        "tier": "free",
        "status": UserStatus.ACTIVE.value,
        "iat": iat,
        "exp": exp,
    }
    return jwt.encode(payload, settings.JWT_SECRET.get_secret_value(), algorithm=_ALGORITHM)


@pytest.mark.parametrize("back_seconds", [1, 5, 60, 3600])
def test_future_iat_is_still_readable(back_seconds: int) -> None:
    """Đồng hồ lùi `lui_giay` giây giữa lúc ký và lúc đọc → token VẪN hợp lệ.

    Đây là ca đã làm bộ test đỏ ngẫu nhiên trước B-194. Bốn mốc chứ không một:
    một `leeway` nhỏ (ví dụ 5 s) sẽ qua được hai mốc đầu và trượt hai mốc sau,
    nên bảng này phân biệt được \"tắt hẳn\" với \"nới một ít\".
    """
    now = datetime.now(UTC)
    user_id = uuid.uuid4()
    token = _token_with_times(
        iat=now + timedelta(seconds=back_seconds),
        exp=now + timedelta(minutes=15),
        user_id=user_id,
    )

    claims = decode_access_token(token)

    assert claims.user_id == user_id
    # `iat` vẫn đọc được nguyên vẹn — `app/core/blacklist.py` (§11.3) so nó với
    # mốc `bl:user:{uid}`, và phép so đó là của chúng ta, không phải của PyJWT.
    assert claims.issued_at > now


def test_past_exp_is_still_rejected() -> None:
    """Vế thứ hai, và là vế dễ mất nhất: tắt `verify_iat` KHÔNG được đụng `exp`.

    Nếu ai đó đổi cách sửa sang `leeway=N` thì test này vẫn xanh với `N` nhỏ —
    nên nó đi cùng `test_exp_one_second_past_is_rejected` ngay dưới, nơi
    biên được siết tới một giây.
    """
    now = datetime.now(UTC)
    token = _token_with_times(
        iat=now - timedelta(minutes=30),
        exp=now - timedelta(minutes=15),
        user_id=uuid.uuid4(),
    )

    with pytest.raises(TokenExpiredError):
        decode_access_token(token)


def test_exp_one_second_past_is_rejected() -> None:
    """`exp` giữ nghĩa TUYỆT ĐỐI: quá một giây là hết, không có vùng đệm nào.

    Đây là phép kiểm ngược của chính B-194: bản sửa bằng `leeway=5` sẽ làm test
    này **đỏ**, và đó đúng là lý do nó không được chọn.
    """
    now = datetime.now(UTC)
    token = _token_with_times(
        iat=now - timedelta(minutes=1),
        exp=now - timedelta(seconds=1),
        user_id=uuid.uuid4(),
    )

    with pytest.raises(TokenExpiredError):
        decode_access_token(token)


def test_bad_signature_is_still_rejected() -> None:
    """Tắt một phép kiểm không được làm hở phép kiểm nào khác."""
    now = datetime.now(UTC)
    payload = {
        "sub": str(uuid.uuid4()),
        "jti": uuid.uuid4().hex,
        "role": UserRole.USER.value,
        "tier": "free",
        "status": UserStatus.ACTIVE.value,
        "iat": now,
        "exp": now + timedelta(minutes=15),
    }
    # Đủ 32 byte: dưới ngưỡng ấy PyJWT kêu `InsecureKeyLengthWarning`, và một
    # cảnh báo mới trong `make test` là một dòng nhiễu người sau phải đọc.
    token = jwt.encode(payload, "k" * 32, algorithm=_ALGORITHM)

    with pytest.raises(TokenInvalidError):
        decode_access_token(token)


def test_freshly_signed_token_is_readable_immediately() -> None:
    """Đường đi bình thường không đổi — `encode` rồi `decode` ngay."""
    user_id = uuid.uuid4()

    token = encode_access_token(
        user_id=user_id,
        role=UserRole.ADMIN,
        tier="trusted",
        status=UserStatus.ACTIVE,
        ttl_minutes=15,
    )
    claims = decode_access_token(token)

    assert claims.user_id == user_id
    assert claims.role is UserRole.ADMIN
    assert claims.tier == "trusted"
    assert claims.status is UserStatus.ACTIVE
