"""`GET /skills` · `PUT /skills/{name}/toggle` (KH §18.3, §13.2) — T-7.5.

Danh sách = mọi skill loader đang bật + công tắc của CHÍNH người gọi
(`user_skills`; không hàng ⇒ `skills.default_enabled`, T-7.8b). Lọc `user_id`
trong SQL (§20) — xem `SkillRepository`.

**`PUT …/toggle` nhận `{"enabled": bool}`, không lật trạng thái.** `PUT` phải
idempotent: hai lần bấm (hai tab, mạng chập chờn gửi lại) ra cùng một trạng
thái, còn "lật" thì hai lần bấm về chỗ cũ. Tên route giữ đúng §18.3.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict

from app.core.deps import get_current_user_id
from app.core.errors import ApiError, ApiErrorCode, ErrorEnvelope
from app.db.repositories import SkillRepository
from app.db.session import session_scope

router = APIRouter(prefix="/skills", tags=["skills"])


class SkillOut(BaseModel):
    name: str
    display_name: str
    description: str
    requires_execution: bool
    enabled: bool


class SkillList(BaseModel):
    items: list[SkillOut]


class ToggleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


_NOT_FOUND_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorEnvelope, "description": "SKILL_NOT_FOUND"}
}


async def _list(user_id: uuid.UUID) -> list[SkillOut]:
    async with session_scope() as session:
        rows = await SkillRepository(session).list_for_user(user_id)
    return [SkillOut.model_validate(dict(r._mapping)) for r in rows]


@router.get("", status_code=status.HTTP_200_OK, response_model=SkillList)
async def list_skills(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
) -> SkillList:
    return SkillList(items=await _list(user_id))


@router.put(
    "/{name}/toggle",
    status_code=status.HTTP_200_OK,
    response_model=SkillOut,
    responses=_NOT_FOUND_RESPONSES,
)
async def toggle_skill(
    name: str,
    body: ToggleIn,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
) -> SkillOut:
    async with session_scope() as session:
        found = await SkillRepository(session).set_user_enabled(user_id, name, body.enabled)
        await session.commit()
    if not found:
        raise ApiError(
            status.HTTP_404_NOT_FOUND, ApiErrorCode.SKILL_NOT_FOUND, "khong tim thay skill"
        )
    return next(s for s in await _list(user_id) if s.name == name)
