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
from enum import StrEnum
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.config.settings import FEEDBACK_REASON_MAX_CHARS
from app.db.models.base import Base, pg_enum


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


class MessageFeedback(StrEnum):
    """Khớp kiểu Postgres `message_feedback` (§18.2, migration 0005).

    Chỉ hai giá trị, và **không** có thành viên thứ ba tên `none`/`unset`: "chưa
    ai bấm gì" là `NULL` trên cột, không phải một nhãn của enum. Một nhãn như
    thế sẽ cho hai cách viết cùng một sự thật, và mọi truy vấn sau đó phải nhớ
    kiểm cả hai.
    """

    LIKE = "like"
    DISLIKE = "dislike"


#: Bộ từ vựng của `messages.reasoning_effort` — bản của metadata, cùng giá trị
#: với `catalog.REASONING_LEVELS` và `_LEVELS` của migration 0006. Xem CHECK
#: `ck_msg_reasoning_effort_level` bên dưới cho lý do chép tay.
REASONING_EFFORT_LEVELS = ("off", "low", "medium", "high", "xhigh", "max")


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
    #: Like/Dislike của §18.2 — `NULL` = chưa ai bấm, hoặc vừa bấm gỡ. Hai cột
    #: này **không** mang `user_id`: NQ-80 chốt "cột thay vì bảng riêng" và
    #: nhận luôn cái giá đi kèm — ngày P8 mở share/fork, câu "ai đánh giá"
    #: không trả lời được từ đây. Xem migration 0005.
    feedback: Mapped[MessageFeedback | None] = mapped_column(
        pg_enum(MessageFeedback, "message_feedback")
    )
    #: Lý do tuỳ chọn đi kèm. Có trần độ dài ở DDL
    #: (`settings.FEEDBACK_REASON_MAX_CHARS`): đây là trường **tự do** duy nhất
    #: trên một bảng mà mọi truy vấn đường đi (§8.3) đều kéo cả hàng về.
    feedback_reason: Mapped[str | None] = mapped_column(Text)
    #: Mức suy luận của lượt sinh (§24.2b·S4, migration 0006) — một `id` của
    #: `reasoning.options` trong catalog. API ghi mức đã giải lúc tạo hàng
    #: `queued`; worker ghi lại đúng mức đã GỬI ở `mark_streaming` (rơi về
    #: `reasoning.default` nếu catalog vừa bỏ mức ấy). `NULL` = không gửi tham số
    #: suy luận nào: model không khai khối `reasoning`, hoặc hàng có từ trước 0006.
    reasoning_effort: Mapped[str | None] = mapped_column(Text)
    #: Công tắc "Tìm web" của lượt (T-6.7a, Q-P6-3, migration 0014) — API ghi
    #: lên hàng `queued`, worker đọc. `true` ⇒ gửi `tools` nếu model có capability.
    web_tools: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    #: Các vòng tool của lượt (Q-P6-1): `[{tool_calls, reasoning, finish_reason,
    #: results: [{tool_call_id, name, ok, content, sources, reason}]}]`. NULL =
    #: không gọi tool — SQL NULL (`none_as_null`), không phải JSON `null`, để
    #: `tool_summaries` lọc được bằng `IS NOT NULL`. **deferred**: chữ trang web
    #: nằm ở đây, và `get_path` / mọi `select(Message)` không được kéo nó về
    #: (T-3.7a ①, B-244) — đường đi đọc bản tóm tắt qua `tool_summaries`.
    tool_rounds: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB(none_as_null=True), deferred=True
    )
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
        # Ba index đầu do migration 0001 tạo, `ix_msg_queued` do 0003; khai lại
        # ở đây để metadata không nói dối (§17.4). Tên phải TRÙNG DDL.
        Index("ix_msg_conv_parent", "conversation_id", "parent_id"),
        Index("ix_msg_parent", "parent_id"),
        Index("ix_msg_streaming", "heartbeat_at", postgresql_where=text("status = 'streaming'")),
        # Nhánh thứ hai của reaper §7.6 (B-123). Đánh trên `created_at` chứ
        # không `heartbeat_at`: message `queued` chưa bao giờ có nhịp tim, vì
        # `mark_streaming` — chỗ đặt `heartbeat_at` — đúng là bước chưa chạy.
        Index("ix_msg_queued", "created_at", postgresql_where=text("status = 'queued'")),
        # Hai CHECK của migration 0005, khai lại vì cùng lý do với bốn index
        # trên: metadata không được nói dối (§17.4). Tên phải TRÙNG DDL — một
        # `alembic revision --autogenerate` sau này so theo tên, và hai tên
        # lệch nhau sẽ sinh ra một migration đòi tạo lại thứ đã có.
        CheckConstraint(
            "feedback_reason IS NULL OR "
            f"char_length(feedback_reason) <= {FEEDBACK_REASON_MAX_CHARS}",
            name="ck_msg_feedback_reason_len",
        ),
        CheckConstraint(
            "feedback IS NOT NULL OR feedback_reason IS NULL",
            name="ck_msg_feedback_reason_needs_value",
        ),
        # CHECK của migration 0006. Bộ từ vựng chép tay chứ không import
        # `catalog.REASONING_LEVELS`: import module ấy là NẠP catalog (fail-fast
        # lúc import), và metadata của bảng không được phụ thuộc một file JSON.
        # `tests/db/test_reasoning_effort_column.py` canh ba chỗ không lệch nhau.
        CheckConstraint(
            "reasoning_effort IS NULL OR reasoning_effort IN "
            f"({', '.join(repr(level) for level in REASONING_EFFORT_LEVELS)})",
            name="ck_msg_reasoning_effort_level",
        ),
    )

    def __repr__(self) -> str:
        # Không in `content`: §20 cấm log nội dung message đầy đủ.
        return (
            f"Message(id={self.id!r}, conversation_id={self.conversation_id!r}, "
            f"parent_id={self.parent_id!r}, role={self.role!r}, status={self.status!r})"
        )
