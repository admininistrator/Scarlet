"""Repository của bảng `user_provider_keys` — BYOK (KH §10.5, §20) — T-2.14.

Ba câu đầu ứng đúng ba endpoint của §18.4 (`GET /settings/keys`, `PUT` và
`DELETE /settings/keys/{provider}`). Câu thứ tư — `get`, đường **đọc để
dùng** — ra đời ở T-2.15 cùng với người gọi của nó
(`app/llm/credentials.py`), đúng như T-2.14 đã hẹn.

**`user_id` lọc trong câu SQL, cả ba câu** (§20, CLAUDE.md). Bảng này chứa
credential của người khác, nên "lọc ở tầng Python sau khi đã SELECT" ở đây
không phải một lỗi phong cách mà là một đường rò.

**`upsert` chứ không `SELECT` rồi `INSERT`/`UPDATE`.** §10.5 nói muốn đổi khoá
thì nhập lại, tức `PUT` phải ghi đè được. Ngả hai câu mở một khe mà hai tab
cùng bấm Lưu sẽ đua nhau: cả hai thấy "chưa có", cả hai `INSERT`, một cái nổ
`UNIQUE`. `ON CONFLICT (user_id, provider) DO UPDATE` là một câu lệnh, một lần
đi-về, và Postgres tự xử lý cuộc đua ấy.

Ghi đè **cả bốn** cột (`key_cipher`, `key_nonce`, `key_last4`, `verified_at`),
không chỉ bản mã: nonce của bản ghi cũ mà đi cùng bản mã mới thì không giải mã
được nữa, và `verified_at` của lần kiểm trước nói dối về khoá vừa dán vào.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import Sealed
from app.db.models import UserProviderKey


class ProviderKeyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_user(self, user_id: uuid.UUID) -> Sequence[UserProviderKey]:
        """Mọi khoá BYOK của một người, sắp theo `provider` cho ổn định thứ tự.

        Sắp xếp trong SQL chứ không ở Python: một danh sách cài đặt nhảy thứ
        tự giữa hai lần tải là thứ người dùng thấy ngay, và `ORDER BY` trên
        một bảng vài hàng không tốn gì.
        """
        stmt = (
            select(UserProviderKey)
            .where(UserProviderKey.user_id == user_id)
            .order_by(UserProviderKey.provider)
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def get(self, *, user_id: uuid.UUID, provider: str) -> UserProviderKey | None:
        """Khoá BYOK của một người cho ĐÚNG một provider — đường gọi model (T-2.15).

        Khác `list_for_user` ở chỗ nó trả về hàng để **giải mã rồi dùng**, nên
        nó lọc thêm `provider` **trong câu SQL**: đọc cả danh sách rồi chọn ở
        Python là kéo bản mã của mọi provider khác vào tiến trình mà không
        việc gì tới chúng (§20, C20).

        `None` = chưa cấu hình khoá cho provider này ⇒ lượt sinh đi bằng
        system key (§10.5). Đó cũng là đường mà DoD dòng 3 của T-2.15 đi: xoá
        khoá xong thì câu này trả `None` ở lượt kế tiếp.
        """
        stmt = select(UserProviderKey).where(
            UserProviderKey.user_id == user_id, UserProviderKey.provider == provider
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def upsert(
        self,
        *,
        user_id: uuid.UUID,
        provider: str,
        sealed: Sealed,
        masked: str,
        verified_at: datetime | None,
    ) -> UserProviderKey:
        """Thêm mới hoặc thay khoá của `(user_id, provider)`. Xem docstring module.

        `RETURNING` (qua `returning(...)`) chứ không `SELECT` lại sau đó: hàng
        vừa ghi phải là hàng được trả về, kể cả khi hai request chạy đua — đọc
        lại bằng một câu thứ hai là mời chính cuộc đua ấy quay lại ở chỗ khác.
        """
        stmt = (
            insert(UserProviderKey)
            .values(
                user_id=user_id,
                provider=provider,
                key_cipher=sealed.cipher,
                key_nonce=sealed.nonce,
                key_last4=masked,
                verified_at=verified_at,
            )
            .on_conflict_do_update(
                index_elements=[UserProviderKey.user_id, UserProviderKey.provider],
                set_={
                    "key_cipher": sealed.cipher,
                    "key_nonce": sealed.nonce,
                    "key_last4": masked,
                    "verified_at": verified_at,
                },
            )
            .returning(UserProviderKey)
        )
        return (await self._session.execute(stmt)).scalar_one()

    async def delete(self, *, user_id: uuid.UUID, provider: str) -> bool:
        """Xoá **cứng** một khoá (§10.5 — không soft-delete).

        Trả `False` khi không có hàng nào khớp, không raise: router quyết định
        câu trả lời (`404`), cùng lối `mark_email_verified` của
        `repositories/users.py`.
        """
        stmt = (
            delete(UserProviderKey)
            .where(UserProviderKey.user_id == user_id, UserProviderKey.provider == provider)
            .returning(UserProviderKey.id)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None
