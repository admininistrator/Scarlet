"""Repository của bảng `email_tokens` (§11.5, §17.2) — T-2.2.

Hai thao tác, đúng hai câu hỏi mà `auth.py` cần trả lời:

- `issue`: sinh một token MỚI, trả về bản RÕ (chỉ sống trong bộ nhớ của request
  này — không bao giờ ghi DB, không bao giờ log). Gọi từ `register` và
  `resend-verification`.
- `consume`: tra một token bản rõ do client gửi lên, đối chiếu bằng HASH, và
  phân biệt bốn trạng thái mà `verify-email` phải trả lời khác nhau (Cạm bẫy
  T-2.2 + DoD): chưa từng tồn tại, đã dùng rồi (idempotent — không phải lỗi),
  hết hạn (trang "gửi lại", không phải lỗi), hoặc hợp lệ (đánh dấu dùng).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_email_token, hash_email_token
from app.db.models import EmailToken, EmailTokenPurpose


class ConsumeResult(StrEnum):
    """Bốn kết cục của `consume` — xem docstring module."""

    OK = "ok"
    ALREADY_USED = "already_used"
    EXPIRED = "expired"
    NOT_FOUND = "not_found"


@dataclass(frozen=True, slots=True)
class ConsumeOutcome:
    result: ConsumeResult
    #: Chỉ có giá trị khi `result` là `OK` hoặc `ALREADY_USED` — hai trường
    #: hợp duy nhất mà caller cần biết token thuộc về user nào.
    user_id: uuid.UUID | None = None


class EmailTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def issue(
        self, *, user_id: uuid.UUID, purpose: EmailTokenPurpose, ttl_minutes: int
    ) -> str:
        """Sinh + lưu một token mới, trả về bản RÕ để router đưa vào email.

        Không vô hiệu hoá token cũ (nếu có) của cùng user/purpose: nhiều token
        còn hiệu lực cùng lúc là vô hại (mỗi token tự đứng, `token_hash` là
        UNIQUE riêng), và làm vậy tránh một ca hẹp — user bấm link cũ đúng lúc
        `resend-verification` vừa phát hành link mới — biến một cú bấm hợp lệ
        thành lỗi.
        """
        raw_token = generate_email_token()
        row = EmailToken(
            user_id=user_id,
            purpose=purpose.value,
            token_hash=hash_email_token(raw_token),
            expires_at=datetime.now(UTC) + timedelta(minutes=ttl_minutes),
        )
        self._session.add(row)
        await self._session.flush()
        return raw_token

    async def consume(self, *, raw_token: str, purpose: EmailTokenPurpose) -> ConsumeOutcome:
        """Tra token bằng hash, đánh dấu `used_at` nếu hợp lệ và chưa dùng.

        Lọc `purpose` NGAY TRONG câu SQL (§20): một token `reset` đưa vào
        `verify-email` phải ra `NOT_FOUND`, không phải "tìm thấy nhưng sai
        chỗ" — hai đường đó không được phép phân biệt được với nhau từ response.
        """
        token_hash = hash_email_token(raw_token)
        stmt = select(EmailToken).where(
            EmailToken.token_hash == token_hash, EmailToken.purpose == purpose.value
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return ConsumeOutcome(ConsumeResult.NOT_FOUND)
        if row.used_at is not None:
            return ConsumeOutcome(ConsumeResult.ALREADY_USED, user_id=row.user_id)
        if row.expires_at < datetime.now(UTC):
            return ConsumeOutcome(ConsumeResult.EXPIRED)

        row.used_at = datetime.now(UTC)
        await self._session.flush()
        return ConsumeOutcome(ConsumeResult.OK, user_id=row.user_id)
