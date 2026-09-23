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
from collections.abc import Mapping, Sequence
from typing import Any, NamedTuple

from sqlalchemy import select, update
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

    async def get(self, name: str) -> Tier | None:
        """Một hàng `tiers` theo tên — `PATCH /admin/users/{id}` (T-2.16).

        Tồn tại để câu trả lời cho *"tier này có thật không"* là một `404`/`400`
        nói đúng chuyện, thay vì một `IntegrityError` của khoá ngoại
        `users.tier_name → tiers.name` nổi lên thành `500`. Cùng lý lẽ với
        `_find_provider` của `api/v1/settings.py`: phép kiểm nằm ở chỗ có thể
        nói câu tử tế, không ở chỗ chỉ biết gào lên.
        """
        return await self._session.get(Tier, name)

    async def list_all(self) -> Sequence[Tier]:
        """Cả bảng `tiers`, sắp theo tên — `GET /admin/tiers` (§18.5).

        Không phân trang, và khác `GET /admin/users` ở chỗ đó là một tính chất
        chứ không phải một món nợ (B-175): số hàng ở đây là số **hạn mức** người
        vận hành tự định nghĩa, hôm nay là hai (`free`, `trusted`). Một bảng mà
        chính admin phải gõ tay từng hàng mới dài ra thì không có cách nào dài
        tới mức cần con trỏ.

        `ORDER BY name` chứ không theo thứ tự Postgres trả về: màn hình §16.3
        đọc bảng này cạnh một ô chọn tier, và một danh sách đổi thứ tự sau mỗi
        lần `UPDATE` là một danh sách không bấm trúng được.
        """
        stmt = select(Tier).order_by(Tier.name)
        return (await self._session.execute(stmt)).scalars().all()

    async def update(self, name: str, *, changes: Mapping[str, Any]) -> Tier | None:
        """Đổi hạn mức của **cả một tier** — `PATCH /admin/tiers/{name}` (§10.4).

        Đây là nửa còn thiếu của §10.4. T-2.16 chỉ mở được đường sửa
        `users.limit_override_json`, tức hạn mức của **một** người; câu "đổi
        hạn mức trong admin panel" của §10.4 nói về hàng `tiers`, thứ áp cho
        mọi người thuộc tier đó cùng lúc.

        **Không có bước gỡ cache**, cùng một câu đã viết ở
        `UserRepository.update_by_admin` và vì cùng lý do — chỉ ở đây nó đáng
        nói to hơn: cache của T-2.10 nhớ `tier:limits:{user_id}`, tức **kết quả
        đã gộp của từng người**, không nhớ hàng `tiers`. Xoá một khoá đặt theo
        tên tier là xoá một khoá không tồn tại, và làm xong sẽ yên tâm rằng
        mình đã gỡ cache. TTL 60 s là luật duy nhất (NQ-51, §10.4 "có hiệu lực
        ≤ 60 s").

        `changes` rỗng thì **không** chạy câu UPDATE nào nhưng vẫn trả hàng
        hiện tại, để `PATCH` body rỗng cư xử như `GET` — cùng lối
        `update_by_admin`/`update_conversation`.

        Trả `None` khi không có tier tên ấy.
        """
        if not changes:
            return await self.get(name)
        stmt = (
            update(Tier)
            .where(Tier.name == name)
            .values(**changes)
            .returning(Tier)
            .execution_options(synchronize_session="fetch")
        )
        return (await self._session.execute(stmt)).scalars().one_or_none()
