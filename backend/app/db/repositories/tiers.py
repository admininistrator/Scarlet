"""Repository của bảng `tiers` (KH §10.4) — T-2.10.

Một hàm đọc duy nhất, và nó **không** chỉ trả về một `Tier`: nó trả về đúng
cặp thứ mà §10.4 nói là cần để biết hạn mức của một người —

    users.tier_name → tiers.name
    users.limit_override_json → ghi đè từng trường cho một user cụ thể

**Một câu SQL cho cả hai vế, không phải hai.** Ngả hai câu (`SELECT users` rồi
`SELECT tiers`) mở một khe mà giữa hai câu ấy admin đổi tier của người này, và
kết quả là bản ghi đè của tier này dán lên hạn mức của tier kia. Một câu JOIN
đọc cả hai trong cùng một ảnh chụp.

Lọc `user_id` **trong câu SQL** (§20), cùng `deleted_at IS NULL`: một tài
khoản vừa xoá không được cấp hạn mức nào cả — kể cả hạn mức mặc định.
"""

from __future__ import annotations

import uuid
from typing import Any, NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Tier, User


class UserTier(NamedTuple):
    """Tier của một user, kèm bản ghi đè riêng của người đó (có thể `None`)."""

    tier: Tier
    override: dict[str, Any] | None


class TierRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_for_user(self, user_id: uuid.UUID) -> UserTier | None:
        """Tier + bản ghi đè của một user, trong một câu SQL.

        Trả `None` khi user không tồn tại hoặc đã xoá mềm — **không** rơi về
        tier mặc định. "Không biết người này là ai" và "người này thuộc tier
        `free`" là hai câu trả lời khác nhau, và gộp chúng nghĩa là một
        `user_id` bịa ra vẫn được cấp hạn mức để tiêu tiền.

        `INNER JOIN` chứ không `LEFT JOIN`: `users.tier_name` có `NOT NULL
        REFERENCES tiers(name)` (Phụ lục A), nên một hàng `users` không khớp
        tier nào là một trạng thái Postgres không cho tồn tại. Viết `LEFT JOIN`
        là dựng sẵn một nhánh `None` không bao giờ chạy, rồi một ngày nào đó
        có người "sửa" nó thành `or TIER_MAC_DINH`.
        """
        stmt = (
            select(Tier, User.limit_override_json)
            .select_from(User)
            .join(Tier, User.tier_name == Tier.name)
            .where(User.id == user_id, User.deleted_at.is_(None))
        )
        row = (await self._session.execute(stmt)).one_or_none()
        if row is None:
            return None
        return UserTier(tier=row[0], override=row[1])
