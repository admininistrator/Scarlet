"""Bảng `attachments` — tệp người dùng tải lên (§15.1, Phụ lục A) — T-4.2.

Byte nằm trên MinIO dưới `storage_key` (`app/core/storage.py`); hàng này chỉ
là con trỏ. `original_name` chỉ để hiển thị, không bao giờ vào khoá (§15.2).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, ForeignKey, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class AttachmentKind(StrEnum):
    IMAGE = "image"
    FILE = "file"


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    #: `NULL` tới khi tệp được gửi kèm một message (T-4.4a).
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    #: MIME **đã nhận dạng** từ byte — không phải `Content-Type` client khai.
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    original_name: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: `none` tới T-4.6a (trích chữ).
    extract_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'none'"))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
