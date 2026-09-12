"""Bảng `conversations` (KH Phụ lục A, §17.2).

`active_leaf_id` là con trỏ nhánh đang xem (§8.2): chuyển nhánh `‹ 2/3 ›` chỉ
đổi con trỏ này, KHÔNG xoá gì. Nó nullable vì một hội thoại rỗng chưa có
message nào để trỏ tới.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, Text, desc, func, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    #: DDL có `REFERENCES users(id) ON DELETE CASCADE`. Không khai ForeignKey ở
    #: đây vì bảng `users` chưa có model (Phase 2, T-2.1) — một FK trỏ vào bảng
    #: không nằm trong `Base.metadata` sẽ nổ ngay khi có ai đó compile DDL từ
    #: metadata. Ràng buộc thật vẫn do Postgres giữ.
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    default_model: Mapped[str | None] = mapped_column(Text)
    system_prompt_override: Mapped[str | None] = mapped_column(Text)
    #: §8.2. `use_alter`: `messages` tham chiếu ngược `conversations`, nên FK
    #: này phải sinh bằng `ALTER TABLE` sau — đúng thứ tự của migration 0001.
    active_leaf_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL", use_alter=True, name="fk_active_leaf"),
    )
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    #: DDL không có trigger cập nhật cột này; `onupdate` bắt mọi câu UPDATE đi
    #: qua bảng này tự bơm `now()`. Sidebar sắp theo cột này (§17.4).
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    __table_args__ = (
        Index(
            "ix_conv_user",
            "user_id",
            desc("updated_at"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    def __repr__(self) -> str:
        # Không in `title`: tiêu đề sinh từ nội dung message đầu tiên (§20).
        return (
            f"Conversation(id={self.id!r}, user_id={self.user_id!r}, "
            f"active_leaf_id={self.active_leaf_id!r})"
        )
