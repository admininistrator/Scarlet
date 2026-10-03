"""Bảng `model_overrides` — admin ghi đè cờ `vision` của model catalog (T-4.5, NQ-139).

File catalog là giá trị mặc định (§9.2); một hàng ở đây thắng file. Gộp hai
nguồn là việc của `app/db/repositories/model_overrides.py::with_override`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class ModelOverride(Base):
    __tablename__ = "model_overrides"

    #: `models[].id` của catalog. Không khoá ngoại — catalog là file.
    model_id: Mapped[str] = mapped_column(Text, primary_key=True)
    vision: Mapped[bool] = mapped_column(nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"ModelOverride(model_id={self.model_id!r}, vision={self.vision!r})"
