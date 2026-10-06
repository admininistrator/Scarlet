"""Repository của bảng `artifacts` — T-5.1 (ghi), T-5.2a (dòng phiên bản, đọc) — §14.2.

Bảng **không có `user_id`**: sở hữu suy qua `messages → conversations`, mọi câu
ĐỌC đi qua `_owned()` — JOIN hai bảng ấy, lọc `user_id` + `deleted_at` trong SQL
(§20, C12).

**Dòng phiên bản (Q-P5-2):** artifact có tiêu đề nối vào dòng của artifact cùng
tiêu đề (đã chuẩn hoá) trên **đường đi** của message — `parent_artifact_id` trỏ
về **gốc** của dòng, `version` = max của dòng (mọi nhánh) + 1. Tiêu đề rỗng ⇒
luôn v1. Thứ tự phiên bản là cột `version`, không bao giờ `created_at` (B-57).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from sqlalchemy import ColumnElement, Insert, Row, Select, func, insert, literal, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models import Artifact, Conversation, Message
from app.db.repositories.messages import _path_cte

if TYPE_CHECKING:
    from app.llm.artifact_blocks import ArtifactBlock


class ArtifactRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_for_message(
        self, *, message_id: uuid.UUID, user_id: uuid.UUID, blocks: Sequence[ArtifactBlock]
    ) -> list[Artifact]:
        """Mỗi khối một hàng, đúng thứ tự khối trong câu trả lời.

        Mỗi hàng một `INSERT` riêng chứ không một câu nhiều `VALUES`: trong
        cùng một câu, `clock_timestamp()` trùng nhau ở độ phân giải micro-giây
        (đo ở 0002: 500 dòng → 88 giá trị). Đường đi gồm cả chính message ⇒
        hai khối cùng tiêu đề trong một câu trả lời là v1, v2.
        """
        return [await self._insert(message_id, user_id, block) for block in blocks]

    async def _insert(
        self, message_id: uuid.UUID, user_id: uuid.UUID, block: ArtifactBlock
    ) -> Artifact:
        """Hai lượt ghi đua nhau trên một dòng ⇒ một bên vi phạm UNIQUE ⇒ tính
        lại đúng một lần (câu mới, ảnh chụp mới — thấy hàng bên kia đã commit).
        Savepoint để lần hỏng không kéo đổ cả transaction của lô.
        """
        try:
            async with self._session.begin_nested():
                stmt = _insert_statement(message_id, user_id, block)
                return (await self._session.execute(stmt)).scalar_one()
        except IntegrityError:
            async with self._session.begin_nested():
                stmt = _insert_statement(message_id, user_id, block)
                return (await self._session.execute(stmt)).scalar_one()

    async def get(self, *, user_id: uuid.UUID, artifact_id: uuid.UUID) -> Row[Any] | None:
        """`(Artifact, conversation_id)`. Của người khác, message hay hội thoại
        đã xoá mềm ⇒ `None` — cùng một lối với "không có" (§20)."""
        stmt = _owned(select(Artifact, Message.conversation_id), Artifact, user_id).where(
            Artifact.id == artifact_id
        )
        return (await self._session.execute(stmt)).one_or_none()

    async def list_versions(
        self, *, user_id: uuid.UUID, artifact_id: uuid.UUID
    ) -> Sequence[Row[Any]]:
        """Mọi phiên bản của dòng chứa `artifact_id`, mọi nhánh, `ORDER BY version`.

        **Không** `content` (Cạm bẫy ⑤ — đây là danh sách tab). Rỗng ⇒ không có
        hoặc không phải của mình. Phiên bản trên message đã xoá mềm vắng mặt.
        """
        anchor = aliased(Artifact, name="anchor")
        anchor_lineage = _owned(select(_lineage(anchor)), anchor, user_id).where(
            anchor.id == artifact_id
        )
        stmt = (
            _owned(
                select(
                    Artifact.id,
                    Artifact.version,
                    Artifact.kind,
                    Artifact.language,
                    Artifact.title,
                    Artifact.message_id,
                    Artifact.created_at,
                ),
                Artifact,
                user_id,
            )
            .where(_lineage(Artifact) == anchor_lineage.scalar_subquery())
            .order_by(Artifact.version)
        )
        return (await self._session.execute(stmt)).all()

    async def list_for_messages(
        self, *, user_id: uuid.UUID, message_ids: Sequence[uuid.UUID]
    ) -> Sequence[Artifact]:
        """Artifact của cả một đường đi — MỘT câu (Cạm bẫy ④), thứ tự khối."""
        stmt = (
            _owned(select(Artifact), Artifact, user_id)
            .where(Artifact.message_id.in_(message_ids))
            .order_by(Artifact.created_at, Artifact.id)
        )
        return (await self._session.execute(stmt)).scalars().all()


def _lineage(table: Any) -> ColumnElement[uuid.UUID]:
    """Id gốc của dòng — đúng biểu thức của chỉ mục UNIQUE (migration 0012)."""
    return func.coalesce(table.parent_artifact_id, table.id)


def _normalized(title: Any) -> ColumnElement[str]:
    """Chuẩn hoá tiêu đề ở MỘT chỗ, áp cả hai vế: `lower` + gộp khoảng trắng + `btrim`."""
    return func.btrim(func.regexp_replace(func.lower(title), r"\s+", " ", "g"))


def _owned(stmt: Select[Any], table: Any, user_id: uuid.UUID) -> Select[Any]:
    """JOIN sở hữu `messages → conversations` trong SQL (§20); xoá mềm ⇒ vắng (C12)."""
    return (
        stmt.join(Message, Message.id == table.message_id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Message.deleted_at.is_(None),
            Conversation.user_id == user_id,
            Conversation.deleted_at.is_(None),
        )
    )


def _insert_statement(message_id: uuid.UUID, user_id: uuid.UUID, block: ArtifactBlock) -> Insert:
    """MỘT câu: tìm dòng trên đường đi (CTE §8.3) + tính `version` + `INSERT`.

    Dòng = artifact gần lá nhất trên đường đi có cùng tiêu đề chuẩn hoá; tiêu
    đề rỗng không bao giờ khớp. Không khớp ⇒ `parent NULL`, `max(...)` trên tập
    rỗng ⇒ `version 1`. Max đếm **mọi** hàng của dòng, kể cả nhánh khác (Cạm
    bẫy ⑦) và message đã xoá mềm — chúng vẫn giữ chỗ trong chỉ mục UNIQUE.
    """
    path = _path_cte(message_id, user_id=user_id)
    seen = aliased(Artifact, name="seen")
    lineage = (
        select(_lineage(seen))
        .join(path, path.c.id == seen.message_id)
        .where(
            seen.title != "",
            literal(block.title) != "",
            _normalized(seen.title) == _normalized(literal(block.title)),
        )
        .order_by(path.c.depth, seen.version.desc())
        .limit(1)
        .scalar_subquery()
    )
    member = aliased(Artifact, name="member")
    version = (
        select(func.coalesce(func.max(member.version), 0) + 1)
        .where(_lineage(member) == lineage)
        .scalar_subquery()
    )
    return (
        insert(Artifact)
        .values(
            message_id=message_id,
            kind=block.kind,
            language=block.language,
            title=block.title,
            content=block.content,
            parent_artifact_id=lineage,
            version=version,
        )
        .returning(Artifact)
    )
