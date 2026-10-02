"""Bảng `user_byok_endpoints` — endpoint BYOK người dùng tự nhập (T-S.19b, NQ-134 ②).

Anh em của `user_provider_key.py`: cùng cách cất khoá (AES-256-GCM, nonce riêng
mỗi hàng, `key_last4` là chuỗi che), cùng xoá cứng. `base_url` là URL **người
dùng** gửi — mọi lượt gọi tới nó đi qua `app/tools/ssrf.py` (A5).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, LargeBinary, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class UserByokEndpoint(Base):
    __tablename__ = "user_byok_endpoints"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(Text, nullable=False)
    #: Đã chuẩn hoá: `https`, không `/` cuối, kết thúc bằng segment phiên bản (C43).
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    key_cipher: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_last4: Mapped[str] = mapped_column(Text, nullable=False)
    models: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    #: `NULL` = endpoint không có `GET /models` để kiểm khoá (C42).
    verified_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (UniqueConstraint("user_id", "label"),)

    def __repr__(self) -> str:
        # Không bản mã, không nonce (C20) — như `UserProviderKey.__repr__`.
        return (
            f"UserByokEndpoint(id={self.id!r}, user_id={self.user_id!r}, "
            f"label={self.label!r}, key_last4={self.key_last4!r})"
        )
