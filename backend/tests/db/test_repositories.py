"""T-1.1 — repository của cây hội thoại.

Bốn dòng DoD của task nằm ở các test có chữ `DoD` trong docstring:

- `test_get_conversation_of_other_user_returns_None`
- `test_soft_deleted_message_children_remain_in_db`
- `test_create_message_with_foreign_conversation_parent_raises`

Mọi phép kiểm "dữ liệu có thật trong DB" đều đọc lại bằng session THỨ HAI hoặc
bằng SQL thô, không tin vào object còn nằm trong identity map của session đã ghi.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from app.db.models import Conversation, Message, MessageRole, MessageStatus
from app.db.repositories import (
    ConversationNotFoundError,
    ConversationRepository,
    MessageNotInConversationError,
    MessageRepository,
)

#: `list_conversations` cố tình không có default cho `limit` (A3); test tự chọn.
LIMIT = 50


async def _create_conversation_with_root(
    session: AsyncSession, user_id: uuid.UUID
) -> tuple[Conversation, Message]:
    conversations = ConversationRepository(session)
    messages = MessageRepository(session)
    conversation = await conversations.create_conversation(user_id=user_id)
    root = await messages.create_message(
        conversation_id=conversation.id,
        user_id=user_id,
        role=MessageRole.USER,
        content="viết hàm sort",
    )
    return conversation, root


# ───────────────────────────── conversations ─────────────────────────────


async def test_create_conversation_sets_ddl_defaults(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    conversation = await ConversationRepository(session).create_conversation(user_id=user_a)

    assert isinstance(conversation.id, uuid.UUID)
    assert conversation.user_id == user_a
    # Ba giá trị dưới đây do Postgres điền, không phải Python (models/base.py).
    assert conversation.pinned is False
    assert conversation.created_at is not None
    # Hội thoại rỗng chưa có message nào để trỏ tới (§17.2).
    assert conversation.active_leaf_id is None


async def test_get_conversation_of_other_user_returns_None(
    session: AsyncSession, user_a: uuid.UUID, user_b: uuid.UUID
) -> None:
    """DoD: `get_conversation(conv_cua_B, user_id=A)` → `None`, không raise, không trả object."""
    conversations = ConversationRepository(session)
    of_b = await conversations.create_conversation(user_id=user_b)

    result = await conversations.get_conversation(of_b.id, user_id=user_a)

    assert result is None
    # Và B vẫn đọc được của chính mình — chứng minh dòng trên không xanh chỉ vì
    # hàm hỏng hoàn toàn.
    assert await conversations.get_conversation(of_b.id, user_id=user_b) is not None


async def test_get_missing_conversation_returns_None(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    conversations = ConversationRepository(session)

    assert await conversations.get_conversation(uuid.uuid4(), user_id=user_a) is None


async def test_soft_deleted_conversation_hidden_from_default_queries(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
) -> None:
    conversations = ConversationRepository(session)
    conversation = await conversations.create_conversation(user_id=user_a)

    assert await conversations.soft_delete_conversation(conversation.id, user_id=user_a) is True

    async with session_factory() as session2:
        repo2 = ConversationRepository(session2)
        assert await repo2.get_conversation(conversation.id, user_id=user_a) is None
        still_in_db = await repo2.get_conversation(
            conversation.id, user_id=user_a, include_deleted=True
        )
        assert still_in_db is not None
        assert still_in_db.deleted_at is not None


async def test_soft_delete_other_users_conversation_returns_False(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
) -> None:
    conversations = ConversationRepository(session)
    of_b = await conversations.create_conversation(user_id=user_b)

    assert await conversations.soft_delete_conversation(of_b.id, user_id=user_a) is False

    async with session_factory() as session2:
        still_there = await ConversationRepository(session2).get_conversation(
            of_b.id, user_id=user_b
        )
        assert still_there is not None
        assert still_there.deleted_at is None


async def test_list_conversations_returns_only_own(
    session: AsyncSession, user_a: uuid.UUID, user_b: uuid.UUID
) -> None:
    conversations = ConversationRepository(session)
    of_a = await conversations.create_conversation(user_id=user_a)
    await conversations.create_conversation(user_id=user_b)

    result = await conversations.list_conversations(user_id=user_a, limit=LIMIT)

    assert [c.id for c in result] == [of_a.id]


async def test_list_conversations_omits_soft_deleted(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    conversations = ConversationRepository(session)
    kept = await conversations.create_conversation(user_id=user_a)
    to_delete = await conversations.create_conversation(user_id=user_a)
    await conversations.soft_delete_conversation(to_delete.id, user_id=user_a)

    result = await conversations.list_conversations(user_id=user_a, limit=LIMIT)

    assert [c.id for c in result] == [kept.id]


async def test_list_conversations_honors_limit(session: AsyncSession, user_a: uuid.UUID) -> None:
    conversations = ConversationRepository(session)
    for _ in range(3):
        await conversations.create_conversation(user_id=user_a)

    assert len(await conversations.list_conversations(user_id=user_a, limit=2)) == 2


async def test_set_active_leaf_moves_pointer_and_bumps_updated_at(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
) -> None:
    conversation, root = await _create_conversation_with_root(session, user_a)
    before = conversation.updated_at

    changed = await ConversationRepository(session).set_active_leaf(
        conversation.id, user_id=user_a, message_id=root.id
    )

    assert changed is True
    async with session_factory() as session2:
        after = await ConversationRepository(session2).get_conversation(
            conversation.id, user_id=user_a
        )
        assert after is not None
        assert after.active_leaf_id == root.id
        assert after.updated_at >= before


async def test_set_active_leaf_with_foreign_conversation_message_raises(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """Trỏ con trỏ nhánh sang cây của hội thoại khác = ngữ cảnh lẫn hai hội thoại (C11)."""
    conversation_1, _ = await _create_conversation_with_root(session, user_a)
    _, root_2 = await _create_conversation_with_root(session, user_a)

    with pytest.raises(MessageNotInConversationError):
        await ConversationRepository(session).set_active_leaf(
            conversation_1.id, user_id=user_a, message_id=root_2.id
        )


async def test_set_active_leaf_on_other_users_conversation_returns_False(
    session: AsyncSession, user_a: uuid.UUID, user_b: uuid.UUID
) -> None:
    conversation_b, root_b = await _create_conversation_with_root(session, user_b)

    changed = await ConversationRepository(session).set_active_leaf(
        conversation_b.id, user_id=user_a, message_id=root_b.id
    )

    assert changed is False


# ─────────────────────────────── messages ────────────────────────────────


async def test_create_root_message_null_parent_id_and_ddl_defaults(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    conversation = await ConversationRepository(session).create_conversation(user_id=user_a)

    message = await MessageRepository(session).create_message(
        conversation_id=conversation.id, user_id=user_a, role=MessageRole.USER
    )

    assert message.parent_id is None  # gốc nhánh — hợp lệ (§8.2)
    assert message.role is MessageRole.USER
    # Hai default của Phụ lục A, do Postgres điền chứ không phải Python:
    assert message.status is MessageStatus.COMPLETED
    assert message.content == ""


async def test_create_message_in_other_users_conversation_raises(
    session: AsyncSession, user_a: uuid.UUID, user_b: uuid.UUID
) -> None:
    of_b = await ConversationRepository(session).create_conversation(user_id=user_b)

    with pytest.raises(ConversationNotFoundError):
        await MessageRepository(session).create_message(
            conversation_id=of_b.id, user_id=user_a, role=MessageRole.USER
        )


async def test_create_message_with_foreign_conversation_parent_raises(
    session: AsyncSession, connection: AsyncConnection, user_a: uuid.UUID
) -> None:
    """DoD: `parent_id` thuộc conversation khác → raise, kiểm ở tầng repo.

    FK `messages.parent_id` của Postgres chỉ bảo đảm message cha TỒN TẠI, nên
    không có phép kiểm này thì hai cây của hai hội thoại nối được vào nhau.
    """
    conversation_1 = await ConversationRepository(session).create_conversation(user_id=user_a)
    _, root_2 = await _create_conversation_with_root(session, user_a)

    with pytest.raises(MessageNotInConversationError):
        await MessageRepository(session).create_message(
            conversation_id=conversation_1.id,
            user_id=user_a,
            role=MessageRole.ASSISTANT,
            parent_id=root_2.id,
        )

    remaining = await connection.scalar(
        text("SELECT count(*) FROM messages WHERE conversation_id = :cid"),
        {"cid": conversation_1.id},
    )
    assert remaining == 0  # không message mồ côi nào được ghi


async def test_create_message_with_soft_deleted_parent_raises(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    conversation, root = await _create_conversation_with_root(session, user_a)
    await MessageRepository(session).soft_delete_message(root.id, user_id=user_a)

    with pytest.raises(MessageNotInConversationError):
        await MessageRepository(session).create_message(
            conversation_id=conversation.id,
            user_id=user_a,
            role=MessageRole.ASSISTANT,
            parent_id=root.id,
        )


async def test_retry_creates_sibling_with_same_parent(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """§8.2: retry = thêm ANH EM của message assistant, không đè lên nó."""
    conversation, root = await _create_conversation_with_root(session, user_a)
    messages = MessageRepository(session)

    answer_1 = await messages.create_message(
        conversation_id=conversation.id,
        user_id=user_a,
        role=MessageRole.ASSISTANT,
        parent_id=root.id,
        content="bubble sort",
    )
    answer_2 = await messages.create_message(
        conversation_id=conversation.id,
        user_id=user_a,
        role=MessageRole.ASSISTANT,
        parent_id=root.id,
        content="quicksort",
    )

    assert answer_1.id != answer_2.id
    assert answer_1.parent_id == answer_2.parent_id == root.id
    # Câu trả lời cũ KHÔNG biến mất khi có câu mới.
    assert await messages.get_message(answer_1.id, user_id=user_a) is not None


async def test_create_message_keeps_given_status_and_model_id(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
) -> None:
    """Message assistant lúc vừa enqueue là `queued`, chưa có chữ nào (A1, §7.2)."""
    conversation, root = await _create_conversation_with_root(session, user_a)

    message = await MessageRepository(session).create_message(
        conversation_id=conversation.id,
        user_id=user_a,
        role=MessageRole.ASSISTANT,
        parent_id=root.id,
        status=MessageStatus.QUEUED,
        model_id="model-nao-do",
    )

    async with session_factory() as session2:
        reloaded = await MessageRepository(session2).get_message(message.id, user_id=user_a)
        assert reloaded is not None
        assert reloaded.status is MessageStatus.QUEUED
        assert reloaded.model_id == "model-nao-do"
        assert reloaded.content == ""


async def test_get_message_of_other_user_returns_None(
    session: AsyncSession, user_a: uuid.UUID, user_b: uuid.UUID
) -> None:
    _, root_b = await _create_conversation_with_root(session, user_b)
    messages = MessageRepository(session)

    assert await messages.get_message(root_b.id, user_id=user_a) is None
    assert await messages.get_message(root_b.id, user_id=user_b) is not None


async def test_get_message_in_soft_deleted_conversation_returns_None(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """Xoá hội thoại thì message bên trong cũng biến khỏi truy vấn mặc định."""
    conversation, root = await _create_conversation_with_root(session, user_a)
    await ConversationRepository(session).soft_delete_conversation(conversation.id, user_id=user_a)

    assert await MessageRepository(session).get_message(root.id, user_id=user_a) is None


async def test_soft_deleted_message_children_remain_in_db(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
    user_a: uuid.UUID,
) -> None:
    """DoD + C12: xoá mềm một message giữa cây, nhánh phía dưới KHÔNG mất."""
    conversation, root = await _create_conversation_with_root(session, user_a)
    messages = MessageRepository(session)
    middle = await messages.create_message(
        conversation_id=conversation.id,
        user_id=user_a,
        role=MessageRole.ASSISTANT,
        parent_id=root.id,
        content="bubble sort",
    )
    child = await messages.create_message(
        conversation_id=conversation.id,
        user_id=user_a,
        role=MessageRole.USER,
        parent_id=middle.id,
        content="nhanh hơn đi",
    )

    assert await messages.soft_delete_message(middle.id, user_id=user_a) is True

    async with session_factory() as session2:
        repo2 = MessageRepository(session2)
        # Truy vấn mặc định không thấy nó nữa…
        assert await repo2.get_message(middle.id, user_id=user_a) is None
        # …nhưng nó vẫn nằm trong DB, chỉ là đã đánh dấu xoá…
        still_there = await repo2.get_message(middle.id, user_id=user_a, include_deleted=True)
        assert still_there is not None
        assert still_there.deleted_at is not None
        # …và con của nó thì nguyên vẹn, vẫn trỏ vào nó.
        child_reloaded = await repo2.get_message(child.id, user_id=user_a)
        assert child_reloaded is not None
        assert child_reloaded.parent_id == middle.id

    # Đọc bằng SQL thô, không qua ORM: dòng con thật sự còn trong bảng.
    child_count = await connection.scalar(
        text("SELECT count(*) FROM messages WHERE parent_id = :pid"), {"pid": middle.id}
    )
    assert child_count == 1


async def test_soft_delete_other_users_message_returns_False(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
) -> None:
    _, root_b = await _create_conversation_with_root(session, user_b)

    assert await MessageRepository(session).soft_delete_message(root_b.id, user_id=user_a) is False

    async with session_factory() as session2:
        still_there = await MessageRepository(session2).get_message(root_b.id, user_id=user_b)
        assert still_there is not None
        assert still_there.deleted_at is None


async def test_soft_delete_message_twice_second_returns_False(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    _, root = await _create_conversation_with_root(session, user_a)
    messages = MessageRepository(session)

    assert await messages.soft_delete_message(root.id, user_id=user_a) is True
    assert await messages.soft_delete_message(root.id, user_id=user_a) is False


async def test_role_and_status_enums_round_trip_through_postgres(
    session: AsyncSession, connection: AsyncConnection, user_a: uuid.UUID
) -> None:
    """Postgres phải nhận `assistant`/`streaming`, không phải tên thành viên enum Python."""
    conversation, root = await _create_conversation_with_root(session, user_a)

    message = await MessageRepository(session).create_message(
        conversation_id=conversation.id,
        user_id=user_a,
        role=MessageRole.ASSISTANT,
        parent_id=root.id,
        status=MessageStatus.STREAMING,
    )

    row = (
        await connection.execute(
            text("SELECT role::text, status::text FROM messages WHERE id = :id"),
            {"id": message.id},
        )
    ).one()
    assert row == ("assistant", "streaming")


async def test_created_at_differs_between_messages_in_one_transaction(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """B-53: `created_at` phải sắp được các message ghi trong CÙNG một transaction.

    Với `DEFAULT now()` (= `transaction_timestamp()`) cả ba message dưới đây có
    cùng một mốc thời gian, và `ORDER BY created_at` của §8.3 trả về thứ tự tuỳ
    ý — hỏng đúng chỗ `sibling_index`/`sibling_count` (C13). Migration 0002 đổi
    default sang `clock_timestamp()`.

    Cả ba message ở đây là ANH EM (cùng `parent_id`), tức đúng hình dạng dữ liệu
    mà `get_siblings` của T-1.2 sẽ phải sắp.
    """
    conversation, root = await _create_conversation_with_root(session, user_a)
    messages = MessageRepository(session)

    siblings = [
        await messages.create_message(
            conversation_id=conversation.id,
            user_id=user_a,
            role=MessageRole.ASSISTANT,
            parent_id=root.id,
            content=f"lan thu {i}",
        )
        for i in range(3)
    ]

    mark = [m.created_at for m in siblings]
    assert len(set(mark)) == 3, f"ba message cùng transaction trùng created_at: {mark}"
    assert mark == sorted(mark), f"created_at không tăng theo thứ tự tạo: {mark}"


async def test_messages_created_at_uses_clock_timestamp(
    connection: AsyncConnection,
) -> None:
    """Chốt DEFAULT ở tầng schema, không chỉ ở hành vi.

    Phép kiểm hành vi phía trên vẫn xanh nếu ai đó chuyển việc sinh mốc thời
    gian lên Python; dòng này bắt đúng thứ mà migration 0002 đã đổi, và sẽ đỏ
    nếu một migration sau vô tình đặt lại `now()`.
    """
    default = await connection.scalar(
        text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_name = 'messages' AND column_name = 'created_at'"
        )
    )

    assert default == "clock_timestamp()"


# ────────────── vòng đời lượt sinh (T-1.6, §7.2 ③) ──────────────


async def test_get_message_for_worker_returns_conversation_owner_id(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """Worker không có `user_id` để lọc, nên nó phải NHẬN được đúng một.

    Con số này đi thẳng vào `get_path` của `context.build`, tức mọi truy vấn
    sau đó vẫn lọc quyền sở hữu trong câu SQL (§20).
    """
    _, root = await _create_conversation_with_root(session, user_a)

    owned = await MessageRepository(session).get_message_for_worker(root.id)

    assert owned is not None
    assert owned.message.id == root.id
    assert owned.user_id == user_a


async def test_get_message_for_worker_skips_soft_deleted_message(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    repo = MessageRepository(session)
    _, root = await _create_conversation_with_root(session, user_a)
    await repo.soft_delete_message(root.id, user_id=user_a)

    assert await repo.get_message_for_worker(root.id) is None


async def test_get_message_for_worker_skips_soft_deleted_conversation(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    conversation, root = await _create_conversation_with_root(session, user_a)
    await ConversationRepository(session).soft_delete_conversation(conversation.id, user_id=user_a)

    assert await MessageRepository(session).get_message_for_worker(root.id) is None


async def test_mark_streaming_applies_only_once(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    """B-72: hai worker cùng nhận một job thì chỉ một cái đổi được trạng thái.

    Không có `WHERE status = 'queued'` thì cả hai cùng sinh, cùng ghi đè
    `content`, và người dùng trả tiền hai lần cho một câu hỏi.
    """
    conversation, _ = await _create_conversation_with_root(session, user_a)
    repo = MessageRepository(session)
    message = await repo.create_message(
        conversation_id=conversation.id,
        user_id=user_a,
        role=MessageRole.ASSISTANT,
        status=MessageStatus.QUEUED,
    )

    assert (
        await repo.mark_streaming(message.id, model_id="mo-hinh-x", reasoning_effort=None) is True
    )
    assert (
        await repo.mark_streaming(message.id, model_id="mo-hinh-x", reasoning_effort=None) is False
    )

    async with session_factory() as reader:
        reloaded = await reader.get(Message, message.id)
        assert reloaded is not None
        assert reloaded.status is MessageStatus.STREAMING
        assert reloaded.model_id == "mo-hinh-x"
        assert reloaded.heartbeat_at is not None, "§7.6: NULL thì reaper không bao giờ dọn"


async def test_touch_heartbeat_only_touches_streaming_message(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """Message đã xong mà còn nhích `heartbeat_at` là nói dối với reaper."""
    conversation, _ = await _create_conversation_with_root(session, user_a)
    repo = MessageRepository(session)
    finished = await repo.create_message(
        conversation_id=conversation.id,
        user_id=user_a,
        role=MessageRole.ASSISTANT,
        status=MessageStatus.COMPLETED,
    )

    assert await repo.touch_heartbeat(finished.id) is False


async def test_finish_generation_writes_error_path_too(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    """Phần chữ đã sinh được giữ lại kể cả khi lượt sinh thất bại (§7.5, C19)."""
    conversation, _ = await _create_conversation_with_root(session, user_a)
    repo = MessageRepository(session)
    message = await repo.create_message(
        conversation_id=conversation.id,
        user_id=user_a,
        role=MessageRole.ASSISTANT,
        status=MessageStatus.QUEUED,
    )

    assert (
        await repo.finish_generation(
            message.id,
            status=MessageStatus.FAILED,
            content="mot nua cau tra loi",
            error_code="UPSTREAM_ERROR",
        )
        is True
    )

    async with session_factory() as reader:
        reloaded = await reader.get(Message, message.id)
        assert reloaded is not None
        assert reloaded.status is MessageStatus.FAILED
        assert reloaded.content == "mot nua cau tra loi"
        assert reloaded.error_code == "UPSTREAM_ERROR"


# ───────── generation_states — trần đồng thời §10.6 (T-2.9, B-85) ─────────
#
# Đây là **đường nhả ghế** của trần `MAX_CONCURRENT_STREAMS`: Redis giữ danh
# sách ghế bận, còn câu "ghế này còn bận thật không" thì chỉ Postgres trả lời
# được (§10.3). Sai ở đây hỏng theo hai chiều, và cả hai đều im lặng — nhả một
# ghế còn bận cho lượt thứ tư đi qua; không nhả một ghế đã khép thì khoá người
# dùng ra khỏi chính tài khoản của họ.


async def test_generation_states_split_generating_from_settled(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    conversation, _ = await _create_conversation_with_root(session, user_a)
    messages = MessageRepository(session)
    by_status: dict[MessageStatus, uuid.UUID] = {}
    for status in MessageStatus:
        message = await messages.create_message(
            conversation_id=conversation.id,
            user_id=user_a,
            role=MessageRole.ASSISTANT,
            status=status,
        )
        by_status[status] = message.id

    result = await messages.generation_states(list(by_status.values()), user_id=user_a)

    assert result.known == frozenset(by_status.values()), "cả năm đều có thật"
    assert result.in_flight == {
        by_status[MessageStatus.QUEUED],
        by_status[MessageStatus.STREAMING],
    }, "chỉ `queued` và `streaming` là lượt sinh chưa khép"


async def test_generation_states_do_not_see_other_users_messages(
    session: AsyncSession, user_a: uuid.UUID, user_b: uuid.UUID
) -> None:
    """IDOR: ghế của người khác không được tính là ghế của mình — và cũng
    không được coi là "đã khép" theo kiểu biết chắc. Nó chỉ đơn giản là một id
    lạ, tức rơi ra khỏi cả hai tập hợp."""
    conversation_b, _ = await _create_conversation_with_root(session, user_b)
    messages = MessageRepository(session)
    of_b = await messages.create_message(
        conversation_id=conversation_b.id,
        user_id=user_b,
        role=MessageRole.ASSISTANT,
        status=MessageStatus.STREAMING,
    )

    result = await messages.generation_states([of_b.id], user_id=user_a)

    assert result.known == frozenset()
    assert result.in_flight == frozenset()

    b_seen_by_b = await messages.generation_states([of_b.id], user_id=user_b)
    assert b_seen_by_b.in_flight == {of_b.id}, "cùng hàng, đúng chủ thì vẫn đang sinh"


async def test_generation_states_treat_soft_deleted_message_as_settled(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """Xoá mềm giữa lúc đang sinh ⇒ `status` còn `streaming` mãi mãi.

    `get_message_for_worker` trả `None` cho hàng đã xoá nên worker bỏ lượt mà
    **không** ghi trạng thái mới. Không có dòng này thì đó là một ghế không bao
    giờ được nhả.
    """
    conversation, _ = await _create_conversation_with_root(session, user_a)
    messages = MessageRepository(session)
    message = await messages.create_message(
        conversation_id=conversation.id,
        user_id=user_a,
        role=MessageRole.ASSISTANT,
        status=MessageStatus.STREAMING,
    )
    assert await messages.soft_delete_message(message.id, user_id=user_a) is True

    result = await messages.generation_states([message.id], user_id=user_a)

    assert result.known == {message.id}, "hàng vẫn còn trong DB (C12)"
    assert result.in_flight == frozenset()


async def test_generation_states_treat_soft_deleted_conversation_as_settled(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    conversation, _ = await _create_conversation_with_root(session, user_a)
    messages = MessageRepository(session)
    message = await messages.create_message(
        conversation_id=conversation.id,
        user_id=user_a,
        role=MessageRole.ASSISTANT,
        status=MessageStatus.QUEUED,
    )
    assert (
        await ConversationRepository(session).soft_delete_conversation(
            conversation.id, user_id=user_a
        )
        is True
    )

    result = await messages.generation_states([message.id], user_id=user_a)

    assert result.known == {message.id}
    assert result.in_flight == frozenset()


async def test_generation_states_missing_id_falls_out_of_both_sets(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """Khác biệt giữa "không có trong `known`" và "đã khép" là thứ giữ cho
    `PHANTOM_GRACE_S` có nghĩa — xem `app/core/ratelimit.py`."""
    unknown = uuid.uuid4()

    result = await MessageRepository(session).generation_states([unknown], user_id=user_a)

    assert result.known == frozenset()
    assert result.in_flight == frozenset()


async def test_generation_states_empty_list_skips_db(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    result = await MessageRepository(session).generation_states([], user_id=user_a)

    assert result.known == frozenset()
    assert result.in_flight == frozenset()
