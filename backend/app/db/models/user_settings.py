"""Bảng `user_settings` (KH Phụ lục A, §18.4, §24.2b·S14) — T-S.5.

Bảng có trong DB từ migration 0001 nhưng tới T-S.5 mới có người dùng: cột
`prefs_json` giữ những tuỳ chọn cá nhân **không** phải một cột của `users` —
hôm nay là `avatar_color` và mức suy luận đã nhớ theo từng model (S14 hàng
"Dữ liệu"). Hình dạng của JSON ấy sống ở `app/core/user_prefs.py`, không ở đây.

┌──────────────────────────────────────────────────────────────────────────┐
│  HAI CHỖ LƯU "CÀI ĐẶT" — CÁI GÌ Ở ĐÂU (T-S.5 Cạm bẫy ①)                  │
└──────────────────────────────────────────────────────────────────────────┘

- `users.default_model` — model mặc định (NQ-79, T-3.0). **Không** dời sang
  đây: đó là một migration dữ liệu không ai yêu cầu.
- `users.display_name` — tên hiển thị (NQ-116), cột có từ Phụ lục A.
- `user_settings.prefs_json` — `avatar_color`, `reasoning` (model → mức).

Hai cột `theme` và `default_model` của bảng này **không được map**, cố ý: theme
sống ở `localStorage` từ T-0.10, còn `default_model` đã có chủ ở `users`. Map
chúng là mời một người sau ghi vào nhầm chỗ; chúng giữ `DEFAULT` của DDL khi
hàng được tạo.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, func, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class UserSettings(Base):
    __tablename__ = "user_settings"

    #: Khoá chính **là** `user_id` (Phụ lục A): một người một hàng, nên
    #: `ON CONFLICT (user_id)` của `UserSettingsRepository.put_prefs` suy ra
    #: được từ model. `ON DELETE CASCADE` — xoá tài khoản là xoá tuỳ chọn.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    prefs_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"UserSettings(user_id={self.user_id!r})"
