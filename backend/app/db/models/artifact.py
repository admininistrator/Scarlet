"""Bảng `artifacts` — khối nội dung có phiên bản, hiện ở panel phải (§14.2, Phụ lục A) — T-5.1.

**Không có `user_id`**: sở hữu chỉ suy được qua `messages → conversations`
(T-5.2a lọc trong SQL). `parent_artifact_id` trỏ về **gốc** của dòng phiên bản.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    parent_artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("artifacts.id"), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    #: html | react | svg | mermaid | code | markdown | file (Phụ lục A).
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: `""` = khối không tiêu đề (T-5.1) — không bao giờ vào dòng phiên bản (T-5.2a).
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: `clock_timestamp()` từ migration 0011 (B-57).
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )

    __table_args__ = (
        # Migration 0012 (T-5.2a) — khai lại để metadata không nói dối (§17.4).
        # Tên phải TRÙNG DDL. Dòng = `COALESCE(parent_artifact_id, id)`.
        Index(
            "uq_art_lineage_version",
            func.coalesce(parent_artifact_id, id),
            version,
            unique=True,
        ),
    )
