"""Bảng `skills` + `user_skills` (KH Phụ lục A, §13.2, §17.1, §18.3) — T-7.5.

`skills` là sổ đăng ký do loader (`app/skills/loader.py`) ghi từ thư mục
`skills/`; `user_skills` là công tắc per-user. §17.1 không liệt `user_skills`
nhưng DDL `0001` có nó — dùng bảng đã có (B-21, B-399 ②).

**Không có hàng `user_skills` nghĩa là `skills.default_enabled`** (T-7.8b,
NQ-148 ②), dù cột `user_skills.enabled` có `DEFAULT TRUE`: chỉ skill dựng sẵn
khai `default_enabled` mới tự vào tầng 1 của người chưa chọn (C30); mọi skill
khác vẫn TẮT tới khi user bật. Có hàng ⇒ công tắc của user thắng.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Text, func, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class Skill(Base):
    __tablename__ = "skills"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    #: Thư mục của skill **như tiến trình đã nạp nó thấy** (`/skills/<name>`
    #: trong container) — T-7.6 đọc `SKILL.md` từ đây.
    path: Mapped[str] = mapped_column(Text, nullable=False)
    requires_execution: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    #: Loader đặt: `true` khi lần nạp gần nhất thấy skill hợp lệ trên đĩa.
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    #: Loader đặt từ `metadata.default_enabled: "true"` (T-7.8b) — bật cho user
    #: chưa có hàng `user_skills`.
    default_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"Skill(name={self.name!r})"


class UserSkill(Base):
    __tablename__ = "user_skills"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    skill_name: Mapped[str] = mapped_column(
        Text, ForeignKey("skills.name", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
