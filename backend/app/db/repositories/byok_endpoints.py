"""Repository của bảng `user_byok_endpoints` — T-S.19b (NQ-134 ②).

Mọi câu lọc `user_id` **trong SQL** (§20): endpoint của người khác và endpoint
không tồn tại là cùng một câu trả lời (`None` / `False`) — router đổi thành `404`.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import Sealed
from app.db.models import UserByokEndpoint


class ByokEndpointRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_user(self, user_id: uuid.UUID) -> Sequence[UserByokEndpoint]:
        stmt = (
            select(UserByokEndpoint)
            .where(UserByokEndpoint.user_id == user_id)
            .order_by(UserByokEndpoint.created_at, UserByokEndpoint.id)
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def count_for_user(self, user_id: uuid.UUID) -> int:
        stmt = select(func.count()).where(UserByokEndpoint.user_id == user_id)
        return int((await self._session.execute(stmt)).scalar_one())

    async def get(self, *, user_id: uuid.UUID, endpoint_id: uuid.UUID) -> UserByokEndpoint | None:
        stmt = select(UserByokEndpoint).where(
            UserByokEndpoint.id == endpoint_id, UserByokEndpoint.user_id == user_id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def label_taken(
        self, *, user_id: uuid.UUID, label: str, except_id: uuid.UUID | None = None
    ) -> bool:
        stmt = select(UserByokEndpoint.id).where(
            UserByokEndpoint.user_id == user_id, UserByokEndpoint.label == label
        )
        if except_id is not None:
            stmt = stmt.where(UserByokEndpoint.id != except_id)
        return (await self._session.execute(stmt.limit(1))).first() is not None

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        label: str,
        base_url: str,
        sealed: Sealed,
        masked: str,
        models: list[str],
        verified_at: datetime | None,
    ) -> UserByokEndpoint:
        row = UserByokEndpoint(
            user_id=user_id,
            label=label,
            base_url=base_url,
            key_cipher=sealed.cipher,
            key_nonce=sealed.nonce,
            key_last4=masked,
            models=models,
            verified_at=verified_at,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def update(
        self,
        *,
        user_id: uuid.UUID,
        endpoint_id: uuid.UUID,
        label: str | None,
        models: list[str] | None,
    ) -> UserByokEndpoint | None:
        """Chỉ `label` / `models` — đổi URL hay khoá là xoá rồi thêm (§10.5)."""
        values: dict[str, object] = {}
        if label is not None:
            values["label"] = label
        if models is not None:
            values["models"] = models
        if not values:
            return await self.get(user_id=user_id, endpoint_id=endpoint_id)
        stmt = (
            update(UserByokEndpoint)
            .where(UserByokEndpoint.id == endpoint_id, UserByokEndpoint.user_id == user_id)
            .values(**values)
            .returning(UserByokEndpoint)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def delete(self, *, user_id: uuid.UUID, endpoint_id: uuid.UUID) -> bool:
        stmt = (
            delete(UserByokEndpoint)
            .where(UserByokEndpoint.id == endpoint_id, UserByokEndpoint.user_id == user_id)
            .returning(UserByokEndpoint.id)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None
