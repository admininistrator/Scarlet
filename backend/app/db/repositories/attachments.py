"""Repository của bảng `attachments` — T-4.2 (§15.1, §20).

Lọc `user_id` **trong SQL**: tệp của người khác và tệp không tồn tại là cùng
một câu trả lời (`None`) — router đổi thành `404`.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import and_, func, insert, literal, or_, select, update
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Attachment, AttachmentKind, ExtractStatus

#: Cột chép sang hàng mới khi sửa câu hỏi (T-4.4a) — mọi cột trừ `id` và
#: `message_id`. `created_at` có mặt có chủ ý: B-57 / NQ-18.
_COPIED = (
    "user_id",
    "kind",
    "mime_type",
    "original_name",
    "size_bytes",
    "storage_key",
    "width",
    "height",
    "extracted_text",
    "extract_status",
    "page_count",
    "created_at",
)


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

    async def attach(
        self, *, user_id: uuid.UUID, message_id: uuid.UUID, attachment_ids: Sequence[uuid.UUID]
    ) -> int:
        """Gắn tệp CHƯA gắn của chính người gọi vào `message_id`. Trả số hàng đã gắn.

        Ít hơn `len(attachment_ids)` ⇒ caller ném và transaction rollback — tất
        cả hoặc không. Hai request tranh cùng một tệp: khoá hàng của `UPDATE`
        bắt request sau đọc lại `message_id IS NULL` ⇒ 0 hàng.
        """
        stmt = (
            update(Attachment)
            .where(
                Attachment.id.in_(attachment_ids),
                Attachment.user_id == user_id,
                Attachment.message_id.is_(None),
            )
            .values(message_id=message_id)
            .returning(Attachment.id)
        )
        return len((await self._session.execute(stmt)).all())

    async def vision_gate(
        self, *, user_id: uuid.UUID, message_id: uuid.UUID, max_pages: int
    ) -> tuple[bool, bool]:
        """`(cần vision, có PDF quá trần trang)` của một message — MỘT câu (T-4.5, T-4.6b).

        Cần vision = ảnh, hoặc PDF không lớp chữ (`extract_status` là nguồn duy
        nhất — Cạm bẫy ③ T-4.6b, không mở PDF lần hai). Quá trần = đã khép
        `too_many_pages`, hoặc `needs_vision` mà `page_count` vượt `max_pages`
        (trần đọc lúc gọi, không chỉ lúc trích).
        """
        scanned = Attachment.extract_status.in_(
            [ExtractStatus.NEEDS_VISION, ExtractStatus.TOO_MANY_PAGES]
        )
        over = or_(
            Attachment.extract_status == ExtractStatus.TOO_MANY_PAGES,
            and_(
                Attachment.extract_status == ExtractStatus.NEEDS_VISION,
                Attachment.page_count > max_pages,
            ),
        )
        stmt = select(
            func.count().filter(or_(Attachment.kind == AttachmentKind.IMAGE, scanned)) > 0,
            func.count().filter(over) > 0,
        ).where(Attachment.message_id == message_id, Attachment.user_id == user_id)
        needs_vision, too_many = (await self._session.execute(stmt)).one()
        return bool(needs_vision), bool(too_many)

    async def set_extracted(
        self,
        attachment_id: uuid.UUID,
        *,
        status: ExtractStatus,
        text: str | None,
        pages: int | None = None,
    ) -> None:
        """Khép một hàng `pending` (T-4.6a). Hàng đã khép thì không đổi — một lần trích."""
        await self._session.execute(
            update(Attachment)
            .where(
                Attachment.id == attachment_id,
                Attachment.extract_status == ExtractStatus.PENDING,
            )
            .values(extract_status=status, extracted_text=text, page_count=pages)
        )

    async def text_gate(self, *, user_id: uuid.UUID, message_id: uuid.UUID) -> tuple[bool, int]:
        """`(còn tệp pending, tổng ký tự chữ tệp)` của một message — MỘT câu (T-4.6a)."""
        stmt = select(
            func.count().filter(Attachment.extract_status == ExtractStatus.PENDING) > 0,
            func.coalesce(func.sum(func.length(Attachment.extracted_text)), 0),
        ).where(Attachment.message_id == message_id, Attachment.user_id == user_id)
        pending, chars = (await self._session.execute(stmt)).one()
        return bool(pending), int(chars)

    async def list_for_messages(
        self, *, user_id: uuid.UUID, message_ids: Sequence[uuid.UUID]
    ) -> Sequence[Attachment]:
        """Tệp của cả một đường đi — MỘT câu, thứ tự tải lên (Cạm bẫy ④ T-4.4a)."""
        stmt = (
            select(Attachment)
            .where(Attachment.message_id.in_(message_ids), Attachment.user_id == user_id)
            .order_by(Attachment.created_at, Attachment.id)
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def copy_to_message(
        self, *, user_id: uuid.UUID, source_id: uuid.UUID, target_id: uuid.UUID
    ) -> None:
        """Sửa câu hỏi có tệp (NQ-138 ③): hàng mới cùng `storage_key`, giữ `created_at`.

        Chép chứ không chuyển: `message_id` là một FK, chuyển là nhánh cũ mất
        tệp. Hàng gốc không đổi. Hai hàng chung một object ⇒ B-338 đếm tham chiếu.
        """
        columns = [getattr(Attachment, name) for name in _COPIED]
        source = select(*columns, literal(target_id, UUID(as_uuid=True))).where(
            Attachment.message_id == source_id, Attachment.user_id == user_id
        )
        await self._session.execute(
            insert(Attachment).from_select([*_COPIED, "message_id"], source)
        )
