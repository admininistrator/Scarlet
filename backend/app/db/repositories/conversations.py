"""Repository của bảng `conversations`.

KH tham chiếu: §8.2, §17.1, §17.2, §20.

Ba luật áp cho MỌI hàm trong file này:

1. **Nhận `user_id` và lọc trong câu SQL.** §20: "lọc `user_id` trong câu SQL,
   không lọc ở tầng Python sau khi đã lấy về". Một lần quên là một lỗ IDOR, và
   `SELECT ... WHERE id = :id` rồi so `row.user_id != user_id` trong Python vẫn
   đã kéo dữ liệu của người khác ra khỏi DB rồi.
2. **Mặc định `deleted_at IS NULL`.** Muốn thấy bản đã xoá phải nói rõ
   `include_deleted=True` (C12).
3. **Không `commit()`.** Đơn vị công việc thuộc về caller — một request HTTP
   hay một job worker thường đụng nhiều bảng, và repository tự commit sẽ cắt
   đôi giao dịch đó. Repository chỉ `flush()` để lấy giá trị DB sinh ra.

Hệ quả của luật 3, phải biết trước: các hàm ghi ở đây chạy câu UPDATE thẳng
xuống DB (`synchronize_session=False`), nên **object đã nạp trước đó trong
cùng session không tự cập nhật**. Caller đọc lại bằng `get_conversation` hoặc
dùng session mới.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, Message
from app.db.repositories.errors import MessageNotInConversationError

#: Cột mà `PATCH /conversations/{id}` (§18.2) được phép đổi — allowlist, không
#: phải blocklist. Thêm một cột vào bảng `conversations` ở migration sau sẽ
#: **không** tự động mở nó ra cho HTTP; phải có người cố ý viết tên nó vào đây.
#:
#: `active_leaf_id` **cố ý không** nằm trong danh sách này dù §18.2 liệt nó
#: cùng chỗ: đổi con trỏ nhánh phải đi qua `set_active_leaf`, nơi có phép kiểm
#: "message này có thuộc đúng hội thoại không". Cho nó vào đây là mở đường trỏ
#: `active_leaf_id` sang cây của hội thoại khác — `get_path` khi đó dựng ra một
#: đường đi lẫn hai hội thoại và mọi lượt chat sau gửi nhầm ngữ cảnh lên model.
CO_THE_SUA = frozenset({"title", "default_model", "pinned"})


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_conversation(
        self,
        *,
        user_id: uuid.UUID,
        title: str | None = None,
        default_model: str | None = None,
        system_prompt_override: str | None = None,
    ) -> Conversation:
        """Tạo hội thoại rỗng (`active_leaf_id` NULL — chưa có message nào)."""
        conversation = Conversation(
            user_id=user_id,
            title=title,
            default_model=default_model,
            system_prompt_override=system_prompt_override,
        )
        self._session.add(conversation)
        await self._session.flush()
        return conversation

    async def get_conversation(
        self,
        conversation_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        include_deleted: bool = False,
    ) -> Conversation | None:
        """Trả `None` khi không tồn tại, đã xoá mềm, **hoặc của user khác**.

        Trả `None` chứ không raise: đây là đường đi thẳng tới 404 của §20 —
        403 sẽ xác nhận cho kẻ dò rằng tài nguyên đó có thật.
        """
        stmt = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
        if not include_deleted:
            stmt = stmt.where(Conversation.deleted_at.is_(None))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_conversations(
        self,
        *,
        user_id: uuid.UUID,
        limit: int,
        updated_before: datetime | None = None,
    ) -> Sequence[Conversation]:
        """Sidebar: mới nhất trước, phân trang bằng con trỏ `updated_before`.

        `limit` **không có giá trị mặc định** — hạn mức là cấu hình, không phải
        hằng số nằm trong `.py` (A3). Caller đọc nó từ nơi cấu hình sống.
        """
        stmt = (
            select(Conversation)
            .where(
                Conversation.user_id == user_id,
                Conversation.deleted_at.is_(None),
            )
            .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
            .limit(limit)
        )
        if updated_before is not None:
            stmt = stmt.where(Conversation.updated_at < updated_before)
        return (await self._session.execute(stmt)).scalars().all()

    async def update_conversation(
        self,
        conversation_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        thay_doi: Mapping[str, Any],
    ) -> bool:
        """Đổi metadata của một hội thoại (§18.2). Trả `False` nếu không thấy được.

        Nhận một `Mapping` chứ không phải bốn tham số tuỳ chọn vì `PATCH` phải
        phân biệt **vắng mặt** với **`null`**: `title=None` là "xoá tiêu đề",
        không phải "đừng đụng tới tiêu đề". Router đã đọc `model_fields_set`
        để biết người gọi gửi những gì, nên nó truyền xuống đúng những khoá đó.

        Khoá ngoài `CO_THE_SUA` → `ValueError`, không phải bỏ qua im lặng: gọi
        nhầm tên cột là lỗi lập trình ở tầng trên, và một `PATCH` lặng lẽ không
        đổi gì là thứ chỉ phát hiện được khi có người ngồi soi DB.

        Hệ quả của luật 3 áp ở đây rõ nhất: câu UPDATE đi thẳng xuống DB, nên
        object `Conversation` caller đang giữ **vẫn mang giá trị cũ**. Caller
        muốn đọc lại phải `refresh()` hoặc dùng session khác.
        """
        la = set(thay_doi) - CO_THE_SUA
        if la:
            raise ValueError(f"cot khong duoc sua qua update_conversation: {sorted(la)}")
        if not thay_doi:
            raise ValueError("update_conversation goi voi thay_doi rong")

        stmt = (
            update(Conversation)
            .where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
                Conversation.deleted_at.is_(None),
            )
            .values(**thay_doi)
            .returning(Conversation.id)
            .execution_options(synchronize_session=False)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    async def soft_delete_conversation(
        self, conversation_id: uuid.UUID, *, user_id: uuid.UUID
    ) -> bool:
        """Xoá MỀM. Trả `False` khi không có gì để xoá (kể cả vì của user khác).

        Message con **không** bị đụng tới: hội thoại biến khỏi mọi truy vấn mặc
        định, còn cây bên dưới vẫn nguyên trong DB (C12).
        """
        stmt = (
            update(Conversation)
            .where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
                Conversation.deleted_at.is_(None),
            )
            .values(deleted_at=func.now())
            .returning(Conversation.id)
            .execution_options(synchronize_session=False)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    async def set_active_leaf(
        self,
        conversation_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        message_id: uuid.UUID | None,
    ) -> bool:
        """Đổi con trỏ nhánh đang xem (§8.2). Trả `False` nếu hội thoại không thấy được.

        Raise `MessageNotInConversationError` nếu `message_id` không thuộc đúng
        hội thoại này: trỏ `active_leaf_id` sang cây của hội thoại khác sẽ làm
        `get_path` (T-1.2) dựng ra một đường đi lẫn hai hội thoại, và mọi lượt
        chat sau đó gửi nhầm ngữ cảnh lên model.

        Thứ tự kiểm là cố ý: quyền sở hữu hội thoại TRƯỚC, quan hệ cha-con SAU.
        Kiểm ngược lại sẽ rò rỉ "message này có thật không" cho người không sở
        hữu hội thoại.
        """
        if await self.get_conversation(conversation_id, user_id=user_id) is None:
            return False

        if message_id is not None:
            belongs = select(Message.id).where(
                Message.id == message_id,
                Message.conversation_id == conversation_id,
                Message.deleted_at.is_(None),
            )
            if (await self._session.execute(belongs)).scalar_one_or_none() is None:
                raise MessageNotInConversationError(message_id, conversation_id)

        stmt = (
            update(Conversation)
            .where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
                Conversation.deleted_at.is_(None),
            )
            .values(active_leaf_id=message_id)
            .returning(Conversation.id)
            .execution_options(synchronize_session=False)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None
