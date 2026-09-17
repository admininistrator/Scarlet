"""Bảng `tiers` (KH Phụ lục A, §10.4) — T-2.10.

§10.4 gọi mục này là **"Tier là dữ liệu, không phải code"**, và đó là toàn bộ
lý do bảng này tồn tại: hạn mức của một người là một **hàng trong Postgres**
mà admin sửa được lúc 3 giờ sáng, không phải một hằng số trong `.py` mà sửa
xong phải build lại image (A3, §19.2 L4).

Vì vậy model này cố ý **không** có một dòng logic nào — nó chỉ mô tả lại DDL
để Python đọc có kiểu. Phần "hạn mức thật của người dùng X là bao nhiêu" (tier
gộp với `users.limit_override_json`, cộng cache 60 s) sống ở
`app/quota/tiers.py`.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Boolean, Integer, Numeric, Text, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class Tier(Base):
    __tablename__ = "tiers"

    #: Khoá chính là **tên** chứ không phải một UUID sinh máy (Phụ lục A).
    #: `users.tier_name` tham chiếu thẳng vào đây, nên một câu `SELECT` trên
    #: `users` đã đọc được tên tier mà không cần JOIN — và một dòng log ghi
    #: `tier_name='trusted'` đọc được ngay, không phải tra ngược một UUID.
    name: Mapped[str] = mapped_column(Text, primary_key=True)

    #: `NUMERIC(10,4)` ⇒ `Decimal`, KHÔNG phải `float`. Đây là tiền: cộng dồn
    #: `float` qua vài nghìn `usage_events` thì sai số nhị phân bò vào đúng
    #: con số mà A7 nói phải chốt được.
    limit_5h_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False, server_default=text("0.50")
    )
    limit_7d_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False, server_default=text("3.00")
    )
    can_execute_skills: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("FALSE")
    )
    can_use_web: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    web_searches_per_day: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("50")
    )
    max_upload_mb: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("10"))
    max_attachments: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("5"))
    allowed_model_tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    #: Tier mà `users.tier_name` rơi vào khi không ai chỉ định. Migration 0001
    #: đặt `TRUE` cho đúng một hàng (`free`); DDL **không** có ràng buộc UNIQUE
    #: nào canh điều đó, xem B-152.
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))

    def __repr__(self) -> str:
        return f"Tier(name={self.name!r}, limit_5h_usd={self.limit_5h_usd!r})"
