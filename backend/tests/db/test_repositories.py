"""T-1.1 — repository của cây hội thoại.

Bốn dòng DoD của task nằm ở các test có chữ `DoD` trong docstring:

- `test_get_conversation_cua_user_khac_tra_None`
- `test_xoa_mem_message_thi_con_van_con_trong_db`
- `test_tao_message_voi_parent_thuoc_conversation_khac_thi_raise`

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


async def _tao_hoi_thoai_co_goc(
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


async def test_tao_conversation_dat_dung_default_cua_ddl(
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


async def test_get_conversation_cua_user_khac_tra_None(
    session: AsyncSession, user_a: uuid.UUID, user_b: uuid.UUID
) -> None:
    """DoD: `get_conversation(conv_cua_B, user_id=A)` → `None`, không raise, không trả object."""
    conversations = ConversationRepository(session)
    cua_b = await conversations.create_conversation(user_id=user_b)

    ket_qua = await conversations.get_conversation(cua_b.id, user_id=user_a)

    assert ket_qua is None
    # Và B vẫn đọc được của chính mình — chứng minh dòng trên không xanh chỉ vì
    # hàm hỏng hoàn toàn.
    assert await conversations.get_conversation(cua_b.id, user_id=user_b) is not None


async def test_get_conversation_khong_ton_tai_tra_None(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    conversations = ConversationRepository(session)

    assert await conversations.get_conversation(uuid.uuid4(), user_id=user_a) is None


async def test_xoa_mem_conversation_thi_truy_van_mac_dinh_khong_thay(
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
        con_trong_db = await repo2.get_conversation(
            conversation.id, user_id=user_a, include_deleted=True
        )
        assert con_trong_db is not None
        assert con_trong_db.deleted_at is not None


async def test_xoa_mem_conversation_cua_user_khac_tra_False(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
) -> None:
    conversations = ConversationRepository(session)
    cua_b = await conversations.create_conversation(user_id=user_b)

    assert await conversations.soft_delete_conversation(cua_b.id, user_id=user_a) is False

    async with session_factory() as session2:
        van_con = await ConversationRepository(session2).get_conversation(cua_b.id, user_id=user_b)
        assert van_con is not None
        assert van_con.deleted_at is None


async def test_list_conversations_chi_tra_cua_dung_user(
    session: AsyncSession, user_a: uuid.UUID, user_b: uuid.UUID
) -> None:
    conversations = ConversationRepository(session)
    cua_a = await conversations.create_conversation(user_id=user_a)
    await conversations.create_conversation(user_id=user_b)

    ket_qua = await conversations.list_conversations(user_id=user_a, limit=LIMIT)

    assert [c.id for c in ket_qua] == [cua_a.id]


async def test_list_conversations_khong_tra_ban_da_xoa_mem(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    conversations = ConversationRepository(session)
    giu_lai = await conversations.create_conversation(user_id=user_a)
    xoa_di = await conversations.create_conversation(user_id=user_a)
    await conversations.soft_delete_conversation(xoa_di.id, user_id=user_a)

    ket_qua = await conversations.list_conversations(user_id=user_a, limit=LIMIT)

    assert [c.id for c in ket_qua] == [giu_lai.id]


async def test_list_conversations_ton_trong_limit(session: AsyncSession, user_a: uuid.UUID) -> None:
    conversations = ConversationRepository(session)
    for _ in range(3):
        await conversations.create_conversation(user_id=user_a)

    assert len(await conversations.list_conversations(user_id=user_a, limit=2)) == 2


async def test_set_active_leaf_doi_con_tro_va_bump_updated_at(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
) -> None:
    conversation, root = await _tao_hoi_thoai_co_goc(session, user_a)
    truoc = conversation.updated_at

    da_doi = await ConversationRepository(session).set_active_leaf(
        conversation.id, user_id=user_a, message_id=root.id
    )

    assert da_doi is True
    async with session_factory() as session2:
        sau = await ConversationRepository(session2).get_conversation(
            conversation.id, user_id=user_a
        )
        assert sau is not None
        assert sau.active_leaf_id == root.id
        assert sau.updated_at >= truoc


async def test_set_active_leaf_voi_message_cua_conversation_khac_thi_raise(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """Trỏ con trỏ nhánh sang cây của hội thoại khác = ngữ cảnh lẫn hai hội thoại (C11)."""
    conversation_1, _ = await _tao_hoi_thoai_co_goc(session, user_a)
    _, root_2 = await _tao_hoi_thoai_co_goc(session, user_a)

    with pytest.raises(MessageNotInConversationError):
        await ConversationRepository(session).set_active_leaf(
            conversation_1.id, user_id=user_a, message_id=root_2.id
        )


async def test_set_active_leaf_tren_conversation_cua_user_khac_tra_False(
    session: AsyncSession, user_a: uuid.UUID, user_b: uuid.UUID
) -> None:
    conversation_b, root_b = await _tao_hoi_thoai_co_goc(session, user_b)

    da_doi = await ConversationRepository(session).set_active_leaf(
        conversation_b.id, user_id=user_a, message_id=root_b.id
    )

    assert da_doi is False


# ─────────────────────────────── messages ────────────────────────────────


async def test_tao_message_goc_co_parent_id_null_va_default_cua_ddl(
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


async def test_tao_message_trong_conversation_cua_user_khac_thi_raise(
    session: AsyncSession, user_a: uuid.UUID, user_b: uuid.UUID
) -> None:
    cua_b = await ConversationRepository(session).create_conversation(user_id=user_b)

    with pytest.raises(ConversationNotFoundError):
        await MessageRepository(session).create_message(
            conversation_id=cua_b.id, user_id=user_a, role=MessageRole.USER
        )


async def test_tao_message_voi_parent_thuoc_conversation_khac_thi_raise(
    session: AsyncSession, connection: AsyncConnection, user_a: uuid.UUID
) -> None:
    """DoD: `parent_id` thuộc conversation khác → raise, kiểm ở tầng repo.

    FK `messages.parent_id` của Postgres chỉ bảo đảm message cha TỒN TẠI, nên
    không có phép kiểm này thì hai cây của hai hội thoại nối được vào nhau.
    """
    conversation_1 = await ConversationRepository(session).create_conversation(user_id=user_a)
    _, root_2 = await _tao_hoi_thoai_co_goc(session, user_a)

    with pytest.raises(MessageNotInConversationError):
        await MessageRepository(session).create_message(
            conversation_id=conversation_1.id,
            user_id=user_a,
            role=MessageRole.ASSISTANT,
            parent_id=root_2.id,
        )

    con_lai = await connection.scalar(
        text("SELECT count(*) FROM messages WHERE conversation_id = :cid"),
        {"cid": conversation_1.id},
    )
    assert con_lai == 0  # không message mồ côi nào được ghi


async def test_tao_message_voi_parent_da_xoa_mem_thi_raise(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    conversation, root = await _tao_hoi_thoai_co_goc(session, user_a)
    await MessageRepository(session).soft_delete_message(root.id, user_id=user_a)

    with pytest.raises(MessageNotInConversationError):
        await MessageRepository(session).create_message(
            conversation_id=conversation.id,
            user_id=user_a,
            role=MessageRole.ASSISTANT,
            parent_id=root.id,
        )


async def test_retry_tao_anh_em_cung_parent(session: AsyncSession, user_a: uuid.UUID) -> None:
    """§8.2: retry = thêm ANH EM của message assistant, không đè lên nó."""
    conversation, root = await _tao_hoi_thoai_co_goc(session, user_a)
    messages = MessageRepository(session)

    tra_loi_1 = await messages.create_message(
        conversation_id=conversation.id,
        user_id=user_a,
        role=MessageRole.ASSISTANT,
        parent_id=root.id,
        content="bubble sort",
    )
    tra_loi_2 = await messages.create_message(
        conversation_id=conversation.id,
        user_id=user_a,
        role=MessageRole.ASSISTANT,
        parent_id=root.id,
        content="quicksort",
    )

    assert tra_loi_1.id != tra_loi_2.id
    assert tra_loi_1.parent_id == tra_loi_2.parent_id == root.id
    # Câu trả lời cũ KHÔNG biến mất khi có câu mới.
    assert await messages.get_message(tra_loi_1.id, user_id=user_a) is not None


async def test_tao_message_giu_nguyen_status_va_model_id_duoc_truyen(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
) -> None:
    """Message assistant lúc vừa enqueue là `queued`, chưa có chữ nào (A1, §7.2)."""
    conversation, root = await _tao_hoi_thoai_co_goc(session, user_a)

    message = await MessageRepository(session).create_message(
        conversation_id=conversation.id,
        user_id=user_a,
        role=MessageRole.ASSISTANT,
        parent_id=root.id,
        status=MessageStatus.QUEUED,
        model_id="model-nao-do",
    )

    async with session_factory() as session2:
        doc_lai = await MessageRepository(session2).get_message(message.id, user_id=user_a)
        assert doc_lai is not None
        assert doc_lai.status is MessageStatus.QUEUED
        assert doc_lai.model_id == "model-nao-do"
        assert doc_lai.content == ""


async def test_get_message_cua_user_khac_tra_None(
    session: AsyncSession, user_a: uuid.UUID, user_b: uuid.UUID
) -> None:
    _, root_b = await _tao_hoi_thoai_co_goc(session, user_b)
    messages = MessageRepository(session)

    assert await messages.get_message(root_b.id, user_id=user_a) is None
    assert await messages.get_message(root_b.id, user_id=user_b) is not None


async def test_get_message_trong_conversation_da_xoa_mem_tra_None(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """Xoá hội thoại thì message bên trong cũng biến khỏi truy vấn mặc định."""
    conversation, root = await _tao_hoi_thoai_co_goc(session, user_a)
    await ConversationRepository(session).soft_delete_conversation(conversation.id, user_id=user_a)

    assert await MessageRepository(session).get_message(root.id, user_id=user_a) is None


async def test_xoa_mem_message_thi_con_van_con_trong_db(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
    user_a: uuid.UUID,
) -> None:
    """DoD + C12: xoá mềm một message giữa cây, nhánh phía dưới KHÔNG mất."""
    conversation, root = await _tao_hoi_thoai_co_goc(session, user_a)
    messages = MessageRepository(session)
    giua = await messages.create_message(
        conversation_id=conversation.id,
        user_id=user_a,
        role=MessageRole.ASSISTANT,
        parent_id=root.id,
        content="bubble sort",
    )
    con = await messages.create_message(
        conversation_id=conversation.id,
        user_id=user_a,
        role=MessageRole.USER,
        parent_id=giua.id,
        content="nhanh hơn đi",
    )

    assert await messages.soft_delete_message(giua.id, user_id=user_a) is True

    async with session_factory() as session2:
        repo2 = MessageRepository(session2)
        # Truy vấn mặc định không thấy nó nữa…
        assert await repo2.get_message(giua.id, user_id=user_a) is None
        # …nhưng nó vẫn nằm trong DB, chỉ là đã đánh dấu xoá…
        van_con = await repo2.get_message(giua.id, user_id=user_a, include_deleted=True)
        assert van_con is not None
        assert van_con.deleted_at is not None
        # …và con của nó thì nguyên vẹn, vẫn trỏ vào nó.
        con_doc_lai = await repo2.get_message(con.id, user_id=user_a)
        assert con_doc_lai is not None
        assert con_doc_lai.parent_id == giua.id

    # Đọc bằng SQL thô, không qua ORM: dòng con thật sự còn trong bảng.
    so_con = await connection.scalar(
        text("SELECT count(*) FROM messages WHERE parent_id = :pid"), {"pid": giua.id}
    )
    assert so_con == 1


async def test_xoa_mem_message_cua_user_khac_tra_False(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
) -> None:
    _, root_b = await _tao_hoi_thoai_co_goc(session, user_b)

    assert await MessageRepository(session).soft_delete_message(root_b.id, user_id=user_a) is False

    async with session_factory() as session2:
        van_con = await MessageRepository(session2).get_message(root_b.id, user_id=user_b)
        assert van_con is not None
        assert van_con.deleted_at is None


async def test_xoa_mem_message_hai_lan_thi_lan_hai_tra_False(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    _, root = await _tao_hoi_thoai_co_goc(session, user_a)
    messages = MessageRepository(session)

    assert await messages.soft_delete_message(root.id, user_id=user_a) is True
    assert await messages.soft_delete_message(root.id, user_id=user_a) is False


async def test_enum_role_va_status_di_ve_dung_gia_tri_trong_postgres(
    session: AsyncSession, connection: AsyncConnection, user_a: uuid.UUID
) -> None:
    """Postgres phải nhận `assistant`/`streaming`, không phải tên thành viên enum Python."""
    conversation, root = await _tao_hoi_thoai_co_goc(session, user_a)

    message = await MessageRepository(session).create_message(
        conversation_id=conversation.id,
        user_id=user_a,
        role=MessageRole.ASSISTANT,
        parent_id=root.id,
        status=MessageStatus.STREAMING,
    )

    hang = (
        await connection.execute(
            text("SELECT role::text, status::text FROM messages WHERE id = :id"),
            {"id": message.id},
        )
    ).one()
    assert hang == ("assistant", "streaming")


async def test_created_at_khac_nhau_giua_cac_message_cung_transaction(
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
    conversation, root = await _tao_hoi_thoai_co_goc(session, user_a)
    messages = MessageRepository(session)

    anh_em = [
        await messages.create_message(
            conversation_id=conversation.id,
            user_id=user_a,
            role=MessageRole.ASSISTANT,
            parent_id=root.id,
            content=f"lan thu {i}",
        )
        for i in range(3)
    ]

    moc = [m.created_at for m in anh_em]
    assert len(set(moc)) == 3, f"ba message cùng transaction trùng created_at: {moc}"
    assert moc == sorted(moc), f"created_at không tăng theo thứ tự tạo: {moc}"


async def test_created_at_cua_messages_dung_clock_timestamp(
    connection: AsyncConnection,
) -> None:
    """Chốt DEFAULT ở tầng schema, không chỉ ở hành vi.

    Phép kiểm hành vi phía trên vẫn xanh nếu ai đó chuyển việc sinh mốc thời
    gian lên Python; dòng này bắt đúng thứ mà migration 0002 đã đổi, và sẽ đỏ
    nếu một migration sau vô tình đặt lại `now()`.
    """
    mac_dinh = await connection.scalar(
        text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_name = 'messages' AND column_name = 'created_at'"
        )
    )

    assert mac_dinh == "clock_timestamp()"
