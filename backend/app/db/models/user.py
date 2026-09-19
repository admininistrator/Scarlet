"""Bảng `users` (KH Phụ lục A, §11.1, §11.6) — T-2.1.

`status` là máy trạng thái 5 bước của §11.1, KHÔNG phải cờ boolean
`is_active`: đăng ký mở + admin duyệt (R5) cần phân biệt "chưa verify email"
với "chờ duyệt", còn một boolean chỉ trả lời được một câu hỏi.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import ForeignKey, Index, Text, func, text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, pg_enum


class UserStatus(StrEnum):
    """Khớp kiểu Postgres `user_status` (§11.1)."""

    PENDING_EMAIL = "pending_email"
    PENDING_APPROVAL = "pending_approval"
    ACTIVE = "active"
    REJECTED = "rejected"
    SUSPENDED = "suspended"


class UserRole(StrEnum):
    """Khớp kiểu Postgres `user_role`. R7: một admin, không RBAC."""

    USER = "user"
    ADMIN = "admin"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    #: CITEXT: Postgres so sánh/UNIQUE không phân biệt hoa-thường, nên không
    #: có `.lower()` nào lặp lại ở tầng Python — một nguồn sự thật duy nhất
    #: cho câu hỏi "hai email này có trùng không" (§11.5 chống dò).
    email: Mapped[str] = mapped_column(CITEXT, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text)
    status: Mapped[UserStatus] = mapped_column(
        pg_enum(UserStatus, "user_status"),
        nullable=False,
        server_default=text("'pending_email'"),
    )
    role: Mapped[UserRole] = mapped_column(
        pg_enum(UserRole, "user_role"),
        nullable=False,
        server_default=text("'user'"),
    )
    #: DDL: `REFERENCES tiers(name) DEFAULT 'free'`. T-2.1 cố ý **không** khai
    #: `ForeignKey` ở đây vì `tiers` chưa có model, và một FK trỏ vào bảng
    #: không nằm trong `Base.metadata` sẽ nổ ngay khi có ai đó compile DDL từ
    #: metadata. T-2.10 dựng `db/models/tier.py` nên lý do đó hết, và khai FK
    #: thật là cách duy nhất để `TierRepository.get_for_user` JOIN được bằng
    #: quan hệ mà Phụ lục A đã ghi chứ bằng một điều kiện chép tay.
    #: `server_default` vẫn là cách "tier mặc định" vào đời mà không cần chuỗi
    #: `"free"` nằm trong `.py` (A3) — `create_pending_user` không truyền
    #: `tier_name`, Postgres tự điền.
    tier_name: Mapped[str] = mapped_column(
        Text, ForeignKey("tiers.name"), nullable=False, server_default=text("'free'")
    )
    limit_override_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    #: Model mặc định của **người này** (§18.4, B-206, NQ-79) — T-3.0.
    #:
    #: `NULL` = chưa chọn ⇒ rơi về `conversations.default_model`, rồi về model
    #: `default: true` của catalog (§9.2). Đó là cùng bậc thang mà
    #: `api/v1/messages.py::_chon_model` đã đi, chỉ thêm một bậc ở trên.
    #:
    #: **Không** `ForeignKey` — catalog là một file JSON sửa nóng
    #: (`POST /admin/catalog/reload`, §19.1), không phải một bảng. Phép kiểm
    #: "model này có thật không" vì vậy nằm ở `PUT /settings`, tức lúc **GHI**;
    #: lúc đọc thì một model vừa biến khỏi catalog trả về nguyên văn và FE rơi
    #: về mặc định của catalog (T-3.6 Cạm bẫy ①). Ném lỗi lúc đọc nghĩa là một
    #: dòng cấu hình admin vừa sửa làm hỏng màn hình của người khác.
    default_model: Mapped[str | None] = mapped_column(Text)
    email_verified_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    last_login_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    password_changed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    __table_args__ = (
        Index("ix_users_status", "status", postgresql_where=text("deleted_at IS NULL")),
    )

    def __repr__(self) -> str:
        # Không in `email`/`password_hash`: đây là danh tính + bí mật (§20).
        return f"User(id={self.id!r}, status={self.status!r}, role={self.role!r})"
