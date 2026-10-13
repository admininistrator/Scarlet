"""Repository của `shared_conversations` (ADR-14, §16.1) — T-8.1.

Hai câu: chủ ghi một snapshot; người lạ đọc nó. Đọc **không** có `user_id` —
token (128 bit, Phụ lục A) là toàn bộ quyền. Tăng `view_count` và đọc trong
MỘT câu `UPDATE … RETURNING`: không đọc rồi ghi (hai người xem cùng lúc mất
một lượt đếm).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SharedConversation


class SharedConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        token: str,
        owner_id: uuid.UUID,
        conversation_id: uuid.UUID,
        snapshot: dict[str, Any],
    ) -> None:
        self._session.add(
            SharedConversation(
                token=token,
                owner_id=owner_id,
                conversation_id=conversation_id,
                snapshot_json=snapshot,
            )
        )
        await self._session.flush()

    async def read_public(self, token: str) -> dict[str, Any] | None:
        """Snapshot + `view_count` +1. Token lạ hoặc đã thu hồi ⇒ `None` (một ca)."""
        stmt = (
            update(SharedConversation)
            .where(SharedConversation.token == token, SharedConversation.revoked_at.is_(None))
            .values(view_count=SharedConversation.view_count + 1)
            .returning(SharedConversation.snapshot_json)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()
