"""Bảng `refresh_tokens` — xoay vòng + phát hiện tái sử dụng (§11.2, ADR-07) — T-2.3.

DDL đã tồn tại từ migration 0001 (KH Phụ lục A) — không migration nào ở task
này. `family_id` gom mọi token sinh ra từ cùng một lần đăng nhập: xoay vòng
sinh token mới CÙNG `family_id`, và phát hiện tái sử dụng (một token đã
`used_at` bị dùng lại) thu hồi TOÀN BỘ family bằng một câu `UPDATE ...
revoked_at = now() WHERE family_id = ...` — xem `RefreshTokenRepository`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    #: SHA-256 hex của token bản rõ — KHÔNG BAO GIỜ lưu bản rõ (§11.2, cùng luật
    #: với `email_tokens.token_hash`).
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    #: Token này đã được dùng để xoay vòng chưa. Dùng lại một token đã
    #: `used_at` là dấu hiệu bị đánh cắp (Cạm bẫy T-2.3) → thu hồi cả family.
    used_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        # Không in token_hash (§20).
        return (
            f"RefreshToken(id={self.id!r}, family_id={self.family_id!r}, "
            f"used_at={self.used_at!r}, revoked_at={self.revoked_at!r})"
        )
