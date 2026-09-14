"""Bảng `messages` — CÂY hội thoại (A2, KH §8.2).

Khớp từng cột với DDL của KH Phụ lục A. Ba chỗ dễ làm sai, đã ghi ngay cạnh cột:

- `parent_id` **nullable** và **không** `ON DELETE CASCADE` (C12).
- `content` ghi MỘT LẦN khi xong; trong lúc stream, nguồn sự thật là Redis
  Stream chứ không phải cột này (§17.2, C5).
- `ix_msg_streaming` là **partial index** — nó chỉ có nghĩa khi
  `status='streaming'`, và reaper (§7.6) quét nhờ nó mới rẻ.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum, StrEnum
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class MessageRole(StrEnum):
    """Khớp kiểu Postgres `message_role`."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class MessageStatus(StrEnum):
    """Khớp kiểu Postgres `message_status` (§17.2, §7.6)."""

    QUEUED = "queued"
    STREAMING = "streaming"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


def pg_enum(python_enum: type[Enum], name: str) -> ENUM:
    """Ánh xạ enum Python sang kiểu ENUM **đã có sẵn** trong Postgres.

    `create_type=False`: kiểu do migration 0001 tạo, ORM không được tạo lại.
    `values_callable`: không có nó, SQLAlchemy gửi **tên** thành viên
    (`ASSISTANT`) xuống DB thay vì **giá trị** (`assistant`), và Postgres từ
    chối vì nhãn không tồn tại trong kiểu.
    """
    return ENUM(
        python_enum,
        name=name,
        create_type=False,
        values_callable=lambda enum_cls: [member.value for member in enum_cls],
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: NULL = gốc của một nhánh; một conversation có thể có NHIỀU gốc (§8.2).
    #: C12: tuyệt đối KHÔNG `ondelete="CASCADE"` ở đây — xoá một message giữa
    #: cây sẽ kéo theo toàn bộ nhánh phía dưới. Xoá là xoá MỀM (`deleted_at`).
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id"), nullable=True
    )
    role: Mapped[MessageRole] = mapped_column(pg_enum(MessageRole, "message_role"), nullable=False)
    status: Mapped[MessageStatus] = mapped_column(
        pg_enum(MessageStatus, "message_status"),
        nullable=False,
        server_default=text("'completed'"),
    )
    #: Ghi MỘT LẦN khi sinh xong (§17.2). Lúc đang stream, đọc Redis.
    content: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    reasoning: Mapped[str | None] = mapped_column(Text)
    model_id: Mapped[str | None] = mapped_column(Text)
    tool_calls: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    tool_call_id: Mapped[str | None] = mapped_column(Text)
    finish_reason: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    #: Chỉ có nghĩa khi `status='streaming'`; reaper so với `now()` (§7.6).
    heartbeat_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    #: `clock_timestamp()` chứ KHÔNG phải `now()` — migration 0002, B-53.
    #: `now()` là `transaction_timestamp()`, nên mọi message ghi trong cùng một
    #: transaction sẽ có `created_at` bằng nhau và §8.3 không sắp được chúng.
    #: Độ phân giải là micro-giây, vẫn trùng được khi ghi hàng loạt bằng MỘT câu
    #: lệnh, nên **mọi truy vấn cây sắp theo `ORDER BY created_at, id`** (T-1.2).
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )
    #: Xoá mềm (C12). Mọi truy vấn của repository mặc định lọc `IS NULL`.
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    __table_args__ = (
        # Ba index dưới đây do migration 0001 tạo; khai lại ở đây để metadata
        # không nói dối (§17.4). Tên phải TRÙNG DDL.
        Index("ix_msg_conv_parent", "conversation_id", "parent_id"),
        Index("ix_msg_parent", "parent_id"),
        Index("ix_msg_streaming", "heartbeat_at", postgresql_where=text("status = 'streaming'")),
    )

    def __repr__(self) -> str:
        # Không in `content`: §20 cấm log nội dung message đầy đủ.
        return (
            f"Message(id={self.id!r}, conversation_id={self.conversation_id!r}, "
            f"parent_id={self.parent_id!r}, role={self.role!r}, status={self.status!r})"
        )
