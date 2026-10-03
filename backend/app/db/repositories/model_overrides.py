"""Repository của bảng `model_overrides` (T-4.5, NQ-139) — admin ghi đè `vision`.

Mọi chỗ cần biết model **thật sự** có `vision` không đi qua `with_override`
(một model) hoặc `vision_map` (cả danh sách): guard ở ba route sinh chữ
(qua `_pick_model` / `resolve_model`), worker (`resolve_model`), `GET /models`,
`GET /admin/models`. Không cache trong tiến trình: `api` và `worker` là hai
tiến trình, và một cache lệch nhau giữa chúng là guard nói "có" còn ngữ cảnh
nói "không" — ảnh rơi im lặng. Một câu theo khoá chính mỗi lượt sinh là rẻ.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.catalog import ModelEntry, with_vision
from app.db.models.model_override import ModelOverride


class ModelOverrideRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def vision_map(self) -> dict[str, bool]:
        """`model_id → vision` của mọi hàng ghi đè (bảng nhỏ: ≤ số model catalog)."""
        rows = await self._session.execute(select(ModelOverride.model_id, ModelOverride.vision))
        return {model_id: vision for model_id, vision in rows.all()}

    async def get_vision(self, model_id: str) -> bool | None:
        stmt = select(ModelOverride.vision).where(ModelOverride.model_id == model_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def put_vision(self, model_id: str, vision: bool, *, actor_id: uuid.UUID) -> None:
        stmt = (
            insert(ModelOverride)
            .values(model_id=model_id, vision=vision, updated_by=actor_id)
            .on_conflict_do_update(
                index_elements=[ModelOverride.model_id],
                set_={"vision": vision, "updated_by": actor_id, "updated_at": func.now()},
            )
        )
        await self._session.execute(stmt)

    async def clear(self, model_id: str) -> None:
        await self._session.execute(delete(ModelOverride).where(ModelOverride.model_id == model_id))


async def with_override(session: AsyncSession, model: ModelEntry) -> ModelEntry:
    """`model` của catalog với cờ `vision` đã gộp ghi đè của admin."""
    return with_vision(model, await ModelOverrideRepository(session).get_vision(model.id))
