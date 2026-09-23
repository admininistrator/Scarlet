"""B-93 — bốn endpoint hội thoại của §18.2 (`app/api/v1/conversations.py`).

Cùng lối đi với `test_messages.py`: `httpx.ASGITransport` (không `TestClient`,
vì `connection` của `conftest.py` là kết nối asyncpg gắn với event loop của
chính test), `DEBUG` bật tay, và `session_scope()` trong handler bị trỏ về đúng
kết nối của test.

Không có `arq_gia` ở đây: bốn endpoint này **không đẩy job nào**. Đó cũng là
một phần của phép kiểm — một `POST /conversations` chạm tới hàng đợi là dấu
hiệu ai đó đã trộn §7.2 ① vào nhầm chỗ.

**`conversations.updated_at` mặc định là `now()`, tức hằng số suốt một
transaction** (NQ-18 nói đúng chuyện này cho `messages.created_at`). Cả bộ test
chạy trong MỘT transaction, nên mọi hội thoại tạo ở đây sinh ra với cùng một
mốc thời gian và không phép kiểm sắp xếp nào có nghĩa. Vì thế `_set_timestamp` đặt
`updated_at` tường minh — xem B-101.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import catalog
from app.config.settings import settings
from app.core.access_token import encode_access_token
from app.core.deps import SESSION_COOKIE_NAME
from app.db.models import Conversation, Message, MessageRole, MessageStatus, UserRole, UserStatus
from app.db.repositories import ConversationRepository, MessageRepository
from app.main import app

PATH = "/api/v1/conversations"


@pytest.fixture
def _db_for_tests(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`session_scope()` trong handler trỏ vào ĐÚNG kết nối của test (NQ-17)."""
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as http:
        yield http


def _session(user_id: uuid.UUID) -> dict[str, str]:
    """Header `Cookie` mang phiên thật (§11.2) của `user_id` — T-3.1c.

    Trả một `dict` để truyền vào `headers=` của **từng request**, đúng chỗ mà
    header danh tính tạm của Phase 1 đứng trước đây: danh tính theo request
    chứ không đặt lên `client`, nên hai danh tính trong cùng một ca (phép kiểm
    quyền sở hữu, §20) vẫn viết được cạnh nhau mà không ai phải nhớ dọn.

    **Một header `Cookie`, không phải tham số `cookies=` của httpx.** httpx đã
    deprecate `cookies=` theo request (*"expected behaviour on cookie
    persistence is ambiguous"*) — và ở đây không có gì để persist: mỗi request
    tự mang phiên của nó. Một `dict` header còn ghép được bằng `|` với
    `Idempotency-Key` hay `Last-Event-ID` mà không phải trộn hai cơ chế.

    `status=ACTIVE` chứ không đọc từ bảng `users`: §11.1 kiểm trạng thái từ
    **claim** của access token (xem `core/deps.py`), và bộ test này đo chuyện
    khác — ma trận 5×4 của bảng ấy là việc của `test_account_states.py`.
    """
    token = encode_access_token(
        user_id=user_id,
        role=UserRole.USER,
        tier="free",
        status=UserStatus.ACTIVE,
        ttl_minutes=15,
    )
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


async def _create_conversation(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID, **columns: Any
) -> Conversation:
    async with session_factory() as session:
        conversation = await ConversationRepository(session).create_conversation(
            user_id=user_id, **columns
        )
        await session.commit()
        return conversation


async def _set_timestamp(
    session_factory: async_sessionmaker[AsyncSession],
    conversation_id: uuid.UUID,
    mark: datetime,
) -> None:
    """Đặt `updated_at` tường minh — xem docstring module."""
    async with session_factory() as session:
        await session.execute(
            update(Conversation).where(Conversation.id == conversation_id).values(updated_at=mark)
        )
        await session.commit()


async def _create_message(
    session_factory: async_sessionmaker[AsyncSession],
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    role: MessageRole,
    parent_id: uuid.UUID | None,
    content: str,
    **columns: Any,
) -> Message:
    async with session_factory() as session:
        message = await MessageRepository(session).create_message(
            conversation_id=conversation_id,
            user_id=user_id,
            role=role,
            parent_id=parent_id,
            content=content,
            **columns,
        )
        await session.commit()
        return message


async def _point_to_foreign(
    session_factory: async_sessionmaker[AsyncSession],
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    message_id: uuid.UUID,
) -> None:
    async with session_factory() as session:
        await ConversationRepository(session).set_active_leaf(
            conversation_id, user_id=user_id, message_id=message_id
        )
        await session.commit()


async def _count_conversations(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> int:
    async with session_factory() as session:
        stmt = select(func.count()).select_from(Conversation).where(Conversation.user_id == user_id)
        return int((await session.execute(stmt)).scalar_one())


# ═══════════════════════════ POST /conversations ═══════════════════════════


@pytest.mark.usefixtures("_db_for_tests")
async def test_create_empty_conversation_201_and_null_active_leaf(
    client: AsyncClient, user_a: uuid.UUID, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """§18.2 "Tạo rỗng": có hàng trong DB, chưa message nào, chưa con trỏ nhánh."""
    res = await client.post(PATH, json={"title": "buoi sang"}, headers=_session(user_a))

    assert res.status_code == 201
    body = res.json()
    assert body["title"] == "buoi sang"
    assert body["active_leaf_id"] is None
    assert body["pinned"] is False

    async with session_factory() as session:
        row = await session.get(Conversation, uuid.UUID(body["id"]))
        assert row is not None and row.user_id == user_a


@pytest.mark.usefixtures("_db_for_tests")
async def test_create_conversation_needs_no_body(client: AsyncClient, user_a: uuid.UUID) -> None:
    res = await client.post(PATH, json={}, headers=_session(user_a))

    assert res.status_code == 201
    assert res.json()["title"] is None


@pytest.mark.usefixtures("_db_for_tests")
async def test_default_model_in_catalog_is_saved(
    client: AsyncClient, user_a: uuid.UUID, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    default = catalog.get_default_model()
    assert default is not None

    res = await client.post(PATH, json={"default_model": default.id}, headers=_session(user_a))

    assert res.status_code == 201
    async with session_factory() as session:
        row = await session.get(Conversation, uuid.UUID(res.json()["id"]))
        assert row is not None and row.default_model == default.id


@pytest.mark.usefixtures("_db_for_tests")
async def test_unknown_default_model_400_and_creates_NO_row(
    client: AsyncClient, user_a: uuid.UUID, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Kiểm ngay lúc tạo: một hội thoại mang model không tồn tại là mìn hẹn giờ."""
    res = await client.post(
        PATH, json={"default_model": "khong-co-model-nay"}, headers=_session(user_a)
    )

    assert res.status_code == 400
    assert res.json()["error"]["code"] == "MODEL_UNKNOWN"
    assert await _count_conversations(session_factory, user_a) == 0


@pytest.mark.usefixtures("_db_for_tests")
async def test_debug_on_creates_nothing_without_session(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`DEBUG=true` không còn mua được gì — T-3.1c.

    Tới T-3.1b, bật `DEBUG` là mở nhánh danh tính tạm của Phase 1: một header
    người gọi tự gõ đủ để đi hết đường này. Ca này canh đúng chiều ngược lại —
    nhánh ấy chết rồi, nên `DEBUG` không đổi được kết cục của một request
    không mang cookie phiên. Nó là bản đảo của ca cũ (`DEBUG=false` ⇒ `503`),
    và nó chính là thứ sẽ đỏ nếu ai đó dựng lại một cửa sau thứ hai.
    """
    monkeypatch.setattr(settings, "DEBUG", True)

    res = await client.post(PATH, json={})

    assert res.status_code == 401
    assert res.json()["error"]["code"] == "UNAUTHENTICATED"
    assert await _count_conversations(session_factory, user_a) == 0


@pytest.mark.usefixtures("_db_for_tests")
async def test_missing_session_cookie_gives_401(client: AsyncClient) -> None:
    res = await client.post(PATH, json={})

    assert res.status_code == 401
    assert res.json()["error"]["code"] == "UNAUTHENTICATED"


# ═══════════════════════════ GET /conversations ════════════════════════════


@pytest.mark.usefixtures("_db_for_tests")
async def test_list_newest_first(
    client: AsyncClient, user_a: uuid.UUID, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    base_time = datetime(2026, 9, 15, 10, 0, tzinfo=UTC)
    ids = []
    for i in range(3):
        conversation = await _create_conversation(session_factory, user_a, title=f"ht{i}")
        await _set_timestamp(session_factory, conversation.id, base_time + timedelta(minutes=i))
        ids.append(str(conversation.id))

    res = await client.get(PATH, headers=_session(user_a))

    assert res.status_code == 200
    assert [x["id"] for x in res.json()["items"]] == list(reversed(ids))


@pytest.mark.usefixtures("_db_for_tests")
async def test_list_shows_only_own_conversations(
    client: AsyncClient,
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """§20 — lọc `user_id` trong SQL. Một dòng của người khác lọt ra là IDOR."""
    await _create_conversation(session_factory, user_b, title="cua nguoi khac")
    mine = await _create_conversation(session_factory, user_a, title="cua toi")

    res = await client.get(PATH, headers=_session(user_a))

    assert [x["id"] for x in res.json()["items"]] == [str(mine.id)]


@pytest.mark.usefixtures("_db_for_tests")
async def test_deleted_conversation_leaves_list(
    client: AsyncClient, user_a: uuid.UUID, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    conversation = await _create_conversation(session_factory, user_a)
    await client.delete(f"{PATH}/{conversation.id}", headers=_session(user_a))

    res = await client.get(PATH, headers=_session(user_a))

    assert res.json()["items"] == []


@pytest.mark.usefixtures("_db_for_tests")
async def test_pagination_by_updated_at_cursor(
    client: AsyncClient, user_a: uuid.UUID, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Con trỏ, không phải OFFSET: trang 2 nối đúng sau trang 1, không lặp dòng."""
    base_time = datetime(2026, 9, 15, 10, 0, tzinfo=UTC)
    ids = []
    for i in range(5):
        conversation = await _create_conversation(session_factory, user_a, title=f"ht{i}")
        await _set_timestamp(session_factory, conversation.id, base_time + timedelta(minutes=i))
        ids.append(str(conversation.id))
    newest_first = list(reversed(ids))

    page1 = (await client.get(PATH, params={"limit": 2}, headers=_session(user_a))).json()
    assert [x["id"] for x in page1["items"]] == newest_first[:2]
    assert page1["next_cursor"] is not None

    page2 = (
        await client.get(
            PATH,
            params={"limit": 2, "updated_before": page1["next_cursor"]},
            headers=_session(user_a),
        )
    ).json()
    assert [x["id"] for x in page2["items"]] == newest_first[2:4]

    page3 = (
        await client.get(
            PATH,
            params={"limit": 2, "updated_before": page2["next_cursor"]},
            headers=_session(user_a),
        )
    ).json()
    assert [x["id"] for x in page3["items"]] == newest_first[4:]
    assert page3["next_cursor"] is None, "trang chua day thi khong moi client hoi them"


@pytest.mark.usefixtures("_db_for_tests")
async def test_empty_list_has_null_next_cursor(client: AsyncClient, user_a: uuid.UUID) -> None:
    res = await client.get(PATH, headers=_session(user_a))

    assert res.json() == {"items": [], "next_cursor": None}


@pytest.mark.usefixtures("_db_for_tests")
async def test_limit_over_configured_cap_is_422(client: AsyncClient, user_a: uuid.UUID) -> None:
    """A3: trần là `settings.CONVERSATION_PAGE_SIZE`, không phải một số trong `.py`."""
    res = await client.get(
        PATH,
        params={"limit": settings.CONVERSATION_PAGE_SIZE + 1},
        headers=_session(user_a),
    )

    assert res.status_code == 422
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


# ═════════════════════════ GET /conversations/{id} ═════════════════════════


@pytest.mark.usefixtures("_db_for_tests")
async def test_detail_of_empty_conversation_has_empty_path(
    client: AsyncClient, user_a: uuid.UUID, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    conversation = await _create_conversation(session_factory, user_a)

    res = await client.get(f"{PATH}/{conversation.id}", headers=_session(user_a))

    assert res.status_code == 200
    assert res.json()["path"] == []
    assert res.json()["active_leaf_id"] is None


@pytest.mark.usefixtures("_db_for_tests")
async def test_detail_returns_PATH_not_all_messages(
    client: AsyncClient, user_a: uuid.UUID, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """A2/C11 — cây có hai nhánh, chỉ nhánh đang xem được trả về.

    `WHERE conversation_id = ... ORDER BY created_at` sẽ trả cả 4 message và
    gửi cả nhánh người dùng đã bỏ lên model ở mọi lượt sau.
    """
    conversation = await _create_conversation(session_factory, user_a)
    question_msg = await _create_message(
        session_factory,
        conversation.id,
        user_a,
        role=MessageRole.USER,
        parent_id=None,
        content="cau hoi",
    )
    answer_1 = await _create_message(
        session_factory,
        conversation.id,
        user_a,
        role=MessageRole.ASSISTANT,
        parent_id=question_msg.id,
        content="nhanh mot",
    )
    answer_2 = await _create_message(
        session_factory,
        conversation.id,
        user_a,
        role=MessageRole.ASSISTANT,
        parent_id=question_msg.id,
        content="nhanh hai",
    )
    await _point_to_foreign(session_factory, conversation.id, user_a, answer_2.id)

    path = (await client.get(f"{PATH}/{conversation.id}", headers=_session(user_a))).json()["path"]

    assert [x["id"] for x in path] == [str(question_msg.id), str(answer_2.id)]
    assert str(answer_1.id) not in [x["id"] for x in path]
    assert [x["content"] for x in path] == ["cau hoi", "nhanh hai"]


@pytest.mark.usefixtures("_db_for_tests")
async def test_detail_carries_sibling_index_and_count(
    client: AsyncClient, user_a: uuid.UUID, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """C13 — hai số do SQL tính; `sibling_index` đếm từ 0 (B-60)."""
    conversation = await _create_conversation(session_factory, user_a)
    question_msg = await _create_message(
        session_factory,
        conversation.id,
        user_a,
        role=MessageRole.USER,
        parent_id=None,
        content="q",
    )
    await _create_message(
        session_factory,
        conversation.id,
        user_a,
        role=MessageRole.ASSISTANT,
        parent_id=question_msg.id,
        content="a1",
    )
    a2 = await _create_message(
        session_factory,
        conversation.id,
        user_a,
        role=MessageRole.ASSISTANT,
        parent_id=question_msg.id,
        content="a2",
    )
    await _point_to_foreign(session_factory, conversation.id, user_a, a2.id)

    path = (await client.get(f"{PATH}/{conversation.id}", headers=_session(user_a))).json()["path"]

    assert path[0]["sibling_index"] == 0 and path[0]["sibling_count"] == 1
    assert path[1]["sibling_index"] == 1 and path[1]["sibling_count"] == 2


@pytest.mark.usefixtures("_db_for_tests")
async def test_detail_does_not_leak_operational_columns(
    client: AsyncClient, user_a: uuid.UUID, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`raw_response`/`tool_calls`/`heartbeat_at` không được ra khỏi server."""
    conversation = await _create_conversation(session_factory, user_a)
    question_msg = await _create_message(
        session_factory,
        conversation.id,
        user_a,
        role=MessageRole.USER,
        parent_id=None,
        content="q",
    )
    await _point_to_foreign(session_factory, conversation.id, user_a, question_msg.id)

    path = (await client.get(f"{PATH}/{conversation.id}", headers=_session(user_a))).json()["path"]

    forbidden = {"raw_response", "tool_calls", "heartbeat_at", "prompt_tokens", "completion_tokens"}
    assert forbidden.isdisjoint(path[0].keys())


@pytest.mark.usefixtures("_db_for_tests")
async def test_detail_streaming_message_still_in_path(
    client: AsyncClient, user_a: uuid.UUID, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """T-1.14 mở lại tab giữa lúc stream: phần đã ghi phải có mặt ngay."""
    conversation = await _create_conversation(session_factory, user_a)
    question_msg = await _create_message(
        session_factory,
        conversation.id,
        user_a,
        role=MessageRole.USER,
        parent_id=None,
        content="q",
    )
    running = await _create_message(
        session_factory,
        conversation.id,
        user_a,
        role=MessageRole.ASSISTANT,
        parent_id=question_msg.id,
        content="phan da ghi",
        status=MessageStatus.STREAMING,
    )
    await _point_to_foreign(session_factory, conversation.id, user_a, running.id)

    path = (await client.get(f"{PATH}/{conversation.id}", headers=_session(user_a))).json()["path"]

    assert path[-1]["status"] == "streaming"
    assert path[-1]["content"] == "phan da ghi"


@pytest.mark.usefixtures("_db_for_tests")
async def test_detail_of_other_user_is_404(
    client: AsyncClient,
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """§20 — 404 chứ không 403: 403 xác nhận hội thoại đó có thật."""
    of_b = await _create_conversation(session_factory, user_b)

    res = await client.get(f"{PATH}/{of_b.id}", headers=_session(user_a))

    assert res.status_code == 404
    assert res.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"


@pytest.mark.usefixtures("_db_for_tests")
async def test_detail_of_missing_conversation_is_404(
    client: AsyncClient, user_a: uuid.UUID
) -> None:
    res = await client.get(f"{PATH}/{uuid.uuid4()}", headers=_session(user_a))

    assert res.status_code == 404


# ═══════════════════════ DELETE /conversations/{id} ════════════════════════


@pytest.mark.usefixtures("_db_for_tests")
async def test_soft_delete_204_and_messages_remain_in_db(
    client: AsyncClient, user_a: uuid.UUID, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """C12 — xoá hội thoại KHÔNG được đụng tới cây message bên dưới."""
    conversation = await _create_conversation(session_factory, user_a)
    question_msg = await _create_message(
        session_factory,
        conversation.id,
        user_a,
        role=MessageRole.USER,
        parent_id=None,
        content="q",
    )

    res = await client.delete(f"{PATH}/{conversation.id}", headers=_session(user_a))

    assert res.status_code == 204
    assert res.content == b""
    async with session_factory() as session:
        row = await session.get(Conversation, conversation.id)
        assert row is not None and row.deleted_at is not None, "xoa MEM, hang van con"
        message = await session.get(Message, question_msg.id)
        assert message is not None and message.deleted_at is None


@pytest.mark.usefixtures("_db_for_tests")
async def test_second_deletion_is_404(
    client: AsyncClient, user_a: uuid.UUID, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    conversation = await _create_conversation(session_factory, user_a)
    await client.delete(f"{PATH}/{conversation.id}", headers=_session(user_a))

    second_time = await client.delete(f"{PATH}/{conversation.id}", headers=_session(user_a))

    assert second_time.status_code == 404
    assert second_time.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"


@pytest.mark.usefixtures("_db_for_tests")
async def test_after_delete_GET_is_also_404(
    client: AsyncClient, user_a: uuid.UUID, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    conversation = await _create_conversation(session_factory, user_a)
    await client.delete(f"{PATH}/{conversation.id}", headers=_session(user_a))

    res = await client.get(f"{PATH}/{conversation.id}", headers=_session(user_a))

    assert res.status_code == 404


@pytest.mark.usefixtures("_db_for_tests")
async def test_cannot_delete_other_users_conversation(
    client: AsyncClient,
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    of_b = await _create_conversation(session_factory, user_b)

    res = await client.delete(f"{PATH}/{of_b.id}", headers=_session(user_a))

    assert res.status_code == 404
    async with session_factory() as session:
        row = await session.get(Conversation, of_b.id)
        assert row is not None and row.deleted_at is None, "hang cua nguoi khac KHONG duoc dung"
