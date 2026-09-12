"""Repository của bảng `messages` — các thao tác trên CÂY (A2, §8.2).

KH tham chiếu: §8.2, §17.2, §20, C12.

Ba luật của `conversations.py` áp nguyên ở đây (nhận `user_id` và lọc trong
SQL · mặc định `deleted_at IS NULL` · không `commit()`), cộng thêm một luật
riêng của bảng này:

**Quyền sở hữu message là quyền sở hữu hội thoại chứa nó.** `messages` không
có cột `user_id` (Phụ lục A), nên mọi truy vấn phải JOIN hoặc lồng truy vấn
sang `conversations` — vẫn là lọc TRONG câu SQL, không phải lấy về rồi so.

Task này CHƯA làm truy vấn đường đi và đếm anh em — đó là T-1.2 (§8.3, recursive
CTE + `IS NOT DISTINCT FROM`). Ở đây chỉ có ghi/đọc một message.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, Message, MessageRole, MessageStatus
from app.db.repositories.errors import (
    ConversationNotFoundError,
    MessageNotInConversationError,
)


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_message(
        self,
        *,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
        role: MessageRole,
        parent_id: uuid.UUID | None = None,
        content: str | None = None,
        status: MessageStatus | None = None,
        model_id: str | None = None,
        tool_call_id: str | None = None,
    ) -> Message:
        """Thêm một node vào cây.

        `parent_id=None` là gốc của một nhánh — hợp lệ và có thể có NHIỀU gốc
        trong cùng hội thoại (sửa message đầu tiên, §8.2). Truyền `parent_id`
        của một message đã có = tạo con; truyền đúng `parent_id` của một message
        đang tồn tại = tạo ANH EM của nó, tức là retry.

        Raise:
            ConversationNotFoundError: hội thoại không tồn tại/đã xoá/của người khác.
            MessageNotInConversationError: `parent_id` thuộc hội thoại khác hoặc
                đã bị xoá mềm. FK của Postgres không bắt được trường hợp này —
                nó chỉ kiểm message cha có tồn tại hay không.
        """
        await self._assert_conversation_visible(conversation_id, user_id=user_id)

        if parent_id is not None:
            parent_ok = select(Message.id).where(
                Message.id == parent_id,
                Message.conversation_id == conversation_id,
                Message.deleted_at.is_(None),
            )
            if (await self._session.execute(parent_ok)).scalar_one_or_none() is None:
                raise MessageNotInConversationError(parent_id, conversation_id)

        message = Message(
            conversation_id=conversation_id,
            parent_id=parent_id,
            role=role,
            model_id=model_id,
            tool_call_id=tool_call_id,
        )
        # `content` và `status` có DEFAULT trong DDL (Phụ lục A). `None` nghĩa là
        # KHÔNG đặt thuộc tính, để Postgres áp default của nó — không chép hai
        # giá trị đó sang Python cho hai nguồn khỏi lệch nhau (xem models/base.py).
        if content is not None:
            message.content = content
        if status is not None:
            message.status = status

        self._session.add(message)
        await self._session.flush()
        return message

    async def get_message(
        self,
        message_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        include_deleted: bool = False,
    ) -> Message | None:
        """Trả `None` khi không tồn tại, đã xoá mềm, hoặc thuộc user khác (→ 404)."""
        stmt = (
            select(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.id == message_id,
                Conversation.user_id == user_id,
                Conversation.deleted_at.is_(None),
            )
        )
        if not include_deleted:
            stmt = stmt.where(Message.deleted_at.is_(None))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def soft_delete_message(self, message_id: uuid.UUID, *, user_id: uuid.UUID) -> bool:
        """Xoá MỀM một message. Trả `False` khi không có gì để xoá.

        C12 sống ở đây: **không** đụng tới con cháu. Message biến khỏi truy vấn
        mặc định, nhưng các node phía dưới vẫn nguyên trong DB và vẫn trỏ
        `parent_id` vào nó. Xoá cứng (hoặc `ON DELETE CASCADE`) sẽ mất cả nhánh.
        """
        owned_conversations = select(Conversation.id).where(
            Conversation.user_id == user_id,
            Conversation.deleted_at.is_(None),
        )
        stmt = (
            update(Message)
            .where(
                Message.id == message_id,
                Message.deleted_at.is_(None),
                Message.conversation_id.in_(owned_conversations),
            )
            .values(deleted_at=func.now())
            .returning(Message.id)
            .execution_options(synchronize_session=False)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    async def _assert_conversation_visible(
        self, conversation_id: uuid.UUID, *, user_id: uuid.UUID
    ) -> None:
        stmt = select(Conversation.id).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
            Conversation.deleted_at.is_(None),
        )
        if (await self._session.execute(stmt)).scalar_one_or_none() is None:
            raise ConversationNotFoundError(conversation_id, user_id)
