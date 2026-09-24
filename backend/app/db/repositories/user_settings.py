"""Repository của bảng `user_settings` (KH §18.4, §20, §24.2b·S14) — T-S.5.

Hai câu, ứng đúng hai người hỏi: `GET /auth/me` đọc, `PUT /settings` ghi. Hình
dạng của `prefs_json` là việc của `app/core/user_prefs.py`; ở đây chỉ có SQL.

**`user_id` lọc trong câu SQL, cả hai câu** (§20, CLAUDE.md), và là tham số
duy nhất nhận danh tính — không có hàm nào nhận một khoá khác để lọc.

**`upsert` chứ không `SELECT` rồi `INSERT`/`UPDATE`**, cùng lý lẽ
`provider_keys.py`: hàng được tạo ở lần ghi đầu tiên (T-S.5 Việc 2), và hai tab
cùng bấm Lưu lần đầu sẽ đua nhau ở ngả hai câu — `ON CONFLICT (user_id)` để
Postgres xử lý cuộc đua ấy.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserSettings


class UserSettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_prefs(self, user_id: uuid.UUID) -> dict[str, Any] | None:
        """`prefs_json` của CHÍNH người gọi, hoặc `None` khi chưa có hàng.

        `None` chứ không `{}`: "chưa từng lưu" và "đã lưu rỗng" là hai sự thật
        khác nhau, và tầng đọc (`user_prefs.read_prefs`) là chỗ quyết định
        chúng trông giống nhau với FE — không phải câu SQL này.
        """
        stmt = select(UserSettings.prefs_json).where(UserSettings.user_id == user_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def put_prefs(self, user_id: uuid.UUID, prefs: dict[str, Any]) -> None:
        """Ghi **đè cả** `prefs_json` của CHÍNH người gọi — `PUT` thay cả tài nguyên.

        Không trộn (`||`) với JSON cũ: một khoá vắng trong body của `PUT` nghĩa
        là "bỏ", và trộn thì nó sống lại (§18.4, T-S.5 DoD dòng 2).
        """
        stmt = (
            insert(UserSettings)
            .values(user_id=user_id, prefs_json=prefs)
            .on_conflict_do_update(
                index_elements=[UserSettings.user_id],
                set_={"prefs_json": prefs, "updated_at": func.now()},
            )
        )
        await self._session.execute(stmt)
