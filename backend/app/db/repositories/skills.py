"""Repository của `skills` + `user_skills` (KH §13.2, §18.3, §20) — T-7.5.

Hai người gọi: loader (`app/skills/loader.py`) ghi sổ đăng ký lúc `api` khởi
động; `api/v1/skills.py` đọc danh sách và ghi công tắc của CHÍNH người gọi.

**`user_id` lọc trong câu SQL** (§20, CLAUDE.md) — kể cả ở `LEFT JOIN`: điều
kiện `user_id` nằm trong `ON` chứ không trong `WHERE`, để skill user chưa bật
vẫn ra một hàng thay vì biến mất.

**Công tắc hiệu lực = `COALESCE(user_skills.enabled, skills.default_enabled)`**
(T-7.8b, NQ-148 ②): hàng của user luôn thắng, không hàng thì theo mặc định của
skill. Một biểu thức (`_EFFECTIVE`) cho cả danh sách lẫn tầng 1.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import ColumnElement, Row, and_, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Skill, UserSkill

_EFFECTIVE = func.coalesce(UserSkill.enabled, Skill.default_enabled)


def _with_switch(user_id: uuid.UUID) -> ColumnElement[bool]:
    """`LEFT JOIN user_skills` của đúng `user_id` — điều kiện trong `ON`."""
    return and_(UserSkill.skill_name == Skill.name, UserSkill.user_id == user_id)


class SkillRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        *,
        name: str,
        display_name: str,
        description: str,
        path: str,
        requires_execution: bool,
        default_enabled: bool = False,
    ) -> None:
        """Ghi một skill loader vừa đọc được; `enabled` về `true` (thấy trên đĩa)."""
        values = {
            "display_name": display_name,
            "description": description,
            "path": path,
            "requires_execution": requires_execution,
            "default_enabled": default_enabled,
            "enabled": True,
        }
        stmt = (
            insert(Skill)
            .values(name=name, **values)
            .on_conflict_do_update(index_elements=[Skill.name], set_=values)
        )
        await self._session.execute(stmt)

    async def disable_missing(self, present: Sequence[str]) -> None:
        """Skill có trong sổ mà lần nạp này không thấy (xoá thư mục / hỏng) ⇒ `enabled=false`.

        Không `DELETE`: `user_skills` có `ON DELETE CASCADE`, xoá là mất lựa
        chọn của mọi user chỉ vì một lần deploy lỡ tay. Tắt thì sửa thư mục
        xong, lần nạp sau bật lại nguyên trạng.
        """
        stmt = update(Skill).where(Skill.name.not_in(present)).values(enabled=False)
        await self._session.execute(stmt)

    async def list_for_user(self, user_id: uuid.UUID) -> Sequence[Row[str, str, str, bool, bool]]:
        """Mọi skill đang dùng được + công tắc hiệu lực của `user_id` (không hàng ⇒ mặc định)."""
        stmt = (
            select(
                Skill.name,
                Skill.display_name,
                Skill.description,
                Skill.requires_execution,
                _EFFECTIVE.label("enabled"),
            )
            .outerjoin(UserSkill, _with_switch(user_id))
            .where(Skill.enabled.is_(True))
            .order_by(Skill.name)
        )
        return (await self._session.execute(stmt)).all()

    async def enabled_for_user(self, user_id: uuid.UUID) -> Sequence[Row[str, str]]:
        """`(name, description)` của skill đang bật với `user_id` (T-7.6 tầng 1, T-7.8b)."""
        stmt = (
            select(Skill.name, Skill.description)
            .outerjoin(UserSkill, _with_switch(user_id))
            .where(_EFFECTIVE.is_(True), Skill.enabled.is_(True))
            .order_by(Skill.name)
        )
        return (await self._session.execute(stmt)).all()

    async def set_user_enabled(self, user_id: uuid.UUID, name: str, enabled: bool) -> bool:
        """Ghi công tắc của `user_id` cho skill `name`. `False` ⇒ skill không tồn tại/đã tắt."""
        exists = select(Skill.name).where(Skill.name == name, Skill.enabled.is_(True))
        if (await self._session.execute(exists)).scalar_one_or_none() is None:
            return False
        stmt = (
            insert(UserSkill)
            .values(user_id=user_id, skill_name=name, enabled=enabled)
            .on_conflict_do_update(
                index_elements=[UserSkill.user_id, UserSkill.skill_name],
                set_={"enabled": enabled},
            )
        )
        await self._session.execute(stmt)
        return True
