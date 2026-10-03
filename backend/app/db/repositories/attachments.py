"""Repository của bảng `attachments` — T-4.2 (§15.1, §20).

Lọc `user_id` **trong SQL**: tệp của người khác và tệp không tồn tại là cùng
một câu trả lời (`None`) — router đổi thành `404`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Attachment


class AttachmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, **values: object) -> Attachment:
        row = Attachment(**values)
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def get(self, *, user_id: uuid.UUID, attachment_id: uuid.UUID) -> Attachment | None:
        stmt = select(Attachment).where(
            Attachment.id == attachment_id, Attachment.user_id == user_id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()
