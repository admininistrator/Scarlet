"""Bảng `email_tokens` — verify + reset, lưu HASH (§11.5, §17.2) — T-2.2.

`purpose` là `TEXT NOT NULL CHECK (purpose IN ('verify','reset'))` trong DDL
(Phụ lục A), KHÔNG phải một kiểu ENUM Postgres như `user_status`/`user_role` —
không có `CREATE TYPE` nào cho nó (xem migration 0001). Vì vậy cột này ánh xạ
sang `Mapped[str]` + `Text` (cùng lối với `User.tier_name`), không dùng
`pg_enum`: `pg_enum` giả định kiểu đã tồn tại sẵn trong Postgres
(`create_type=False`), dùng nó cho một cột TEXT thường sẽ khai một kiểu
Postgres không hề tồn tại. `EmailTokenPurpose` vẫn tồn tại để tầng gọi
(repository, router) không gõ tay chuỗi `"verify"`/`"reset"` rải rác (A3).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class EmailTokenPurpose(StrEnum):
    VERIFY = "verify"
    RESET = "reset"


class EmailToken(Base):
    __tablename__ = "email_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    #: SHA-256 hex của token bản rõ — KHÔNG BAO GIỜ lưu bản rõ (Cạm bẫy T-2.2,
    #: §11.5). `UNIQUE` ở DDL cho lookup verify một câu SELECT bằng index.
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        # Không in token_hash: dù là hash, in log không có lý do gì (§20).
        return f"EmailToken(id={self.id!r}, purpose={self.purpose!r}, used_at={self.used_at!r})"
