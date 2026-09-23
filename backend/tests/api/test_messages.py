"""T-1.8 — `POST /api/v1/conversations/{id}/messages` (§7.2 ①, §18.2, C14).

Ba dòng DoD của task nằm ở các test có chữ `DoD` trong docstring. Dòng thứ tư
(`curl -w "%{time_total}"` < 200 ms) đo cả chặng Nginx nên nó chỉ chứng minh
được trên hạ tầng thật — output nằm trong báo cáo, không ở đây.

Cùng lối đi với `test_stream.py`: `httpx.ASGITransport` (không `TestClient`,
vì `connection` của `conftest.py` là kết nối asyncpg gắn với event loop của
chính test), `DEBUG` bật tay, và `session_scope()` trong handler bị trỏ về
đúng kết nối của test.

`arq_gia` thay chỗ `get_arq_pool` là bắt buộc chứ không phải tiện: pool thật
nối tới `redis:6379`, một host chỉ phân giải được **bên trong** network
`internal` của compose — `make test` chạy từ WSL host. Và nó cho phép dựng
đúng ca DoD cuối: ép enqueue thất bại rồi đếm hàng trong DB.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.v1 import IDEMPOTENCY_REQUIRED_ROUTES
from app.api.v1.messages import CREATE_MESSAGE_ROUTE_NAME, RETRY_ROUTE_NAME
from app.config import catalog
from app.config.settings import settings
from app.core.access_token import encode_access_token
from app.core.deps import SESSION_COOKIE_NAME
from app.db.models import Conversation, Message, MessageRole, MessageStatus, UserRole, UserStatus
from app.db.repositories import ConversationRepository, MessageRepository
from app.main import app

PATH = "/api/v1/conversations/{}/messages"


class FakeArq:
    """Pool arq giả: ghi lại mọi lần enqueue, có công tắc để ép nó ném.

    `raises` mô phỏng Redis chết giữa bước ④ của §7.2 ①; `returns_none` mô phỏng
    arq từ chối job (trùng `_job_id`) — hai ngả khác nhau nhưng cùng phải dẫn
    tới "không có message mồ côi".
    """

    def __init__(self) -> None:
        self.pushed: list[tuple[str, tuple[Any, ...]]] = []
        #: `_job_id` của từng lần enqueue, theo đúng thứ tự `pushed` (B-92).
        #: Tách khỏi `pushed` chứ không nhét thêm vào tuple: bốn file test khác
        #: so `pushed` bằng `==` với một tuple hai phần tử, và đổi hình dạng của
        #: nó là sửa những test không liên quan gì tới B-92.
        self.used_job_ids: list[str | None] = []
        self.raises = False
        self.returns_none = False

    async def enqueue_job(self, name: str, *args: Any, **kwargs: Any) -> object | None:
        if self.raises:
            raise ConnectionError("redis chet giua chung (gia lap)")
        self.pushed.append((name, args))
        self.used_job_ids.append(kwargs.get("_job_id"))
        return None if self.returns_none else object()


@pytest.fixture
def _db_for_tests(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`session_scope()` trong handler trỏ vào ĐÚNG kết nối của test (NQ-17)."""
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


@pytest_asyncio.fixture
async def fake_arq(monkeypatch: pytest.MonkeyPatch) -> FakeArq:
    fake = FakeArq()

    async def _pool() -> FakeArq:
        return fake

    monkeypatch.setattr("app.api.v1.messages.get_arq_pool", _pool)
    return fake


@pytest_asyncio.fixture
async def client(event_hooks: dict[str, Any]) -> AsyncIterator[AsyncClient]:
    # `event_hooks`: mỗi POST một `Idempotency-Key` mới, đúng hành vi FE của C22
    # — xem `tests/api/conftest.py`. Không có nó thì mọi POST tới
    # `.../messages` nhận `400 IDEMPOTENCY_KEY_REQUIRED` (§11.4, A8, T-2.8).
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://localhost", event_hooks=event_hooks
    ) as http:
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
    session_factory: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
    **columns: Any,
) -> Conversation:
    async with session_factory() as session:
        conversation = await ConversationRepository(session).create_conversation(
            user_id=user_id, **columns
        )
        await session.commit()
        return conversation


async def _count_messages(
    session_factory: async_sessionmaker[AsyncSession], conversation_id: uuid.UUID
) -> int:
    async with session_factory() as session:
        stmt = (
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == conversation_id)
        )
        return int((await session.execute(stmt)).scalar_one())


async def _read_message(
    session_factory: async_sessionmaker[AsyncSession], message_id: uuid.UUID
) -> Message:
    async with session_factory() as session:
        message = await session.get(Message, message_id)
        assert message is not None
        return message


async def _active_leaf(
    session_factory: async_sessionmaker[AsyncSession], conversation_id: uuid.UUID
) -> uuid.UUID | None:
    async with session_factory() as session:
        stmt = select(Conversation.active_leaf_id).where(Conversation.id == conversation_id)
        return (await session.execute(stmt)).scalar_one()


def _non_default_model() -> str:
    """Một `model_id` đang bật, KHÁC model `default`. A3: không gõ tên vào đây."""
    default = catalog.get_default_model()
    assert default is not None
    others = [m.id for m in catalog.get_catalog().models if m.enabled and m.id != default.id]
    assert others, "catalog phải có ít nhất hai model bật thì test này mới có nghĩa"
    return others[0]


# ════════════════════════ đường chạy đúng (§7.2 ①) ════════════════════════


async def test_creates_two_messages_and_enqueues_job(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """Một POST ⇒ 202, hai message, một job, `active_leaf_id` dời sang assistant."""
    conversation = await _create_conversation(session_factory, user_a)

    resp = await client.post(
        PATH.format(conversation.id),
        headers=_session(user_a),
        json={"content": "xin chao"},
    )

    assert resp.status_code == 202
    body = resp.json()
    uid = uuid.UUID(body["user_message_id"])
    amid = uuid.UUID(body["assistant_message_id"])

    user_message = await _read_message(session_factory, uid)
    assert user_message.role is MessageRole.USER
    assert user_message.content == "xin chao"
    assert user_message.parent_id is None, "hội thoại rỗng ⇒ message đầu là gốc (§8.2)"

    assistant = await _read_message(session_factory, amid)
    assert assistant.role is MessageRole.ASSISTANT
    assert assistant.parent_id == uid
    assert assistant.content == ""

    assert await _active_leaf(session_factory, conversation.id) == amid
    assert fake_arq.pushed == [("generate", (str(amid),))]


async def test_assistant_is_queued(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """`queued` chứ không phải DEFAULT `completed` của cột.

    `mark_streaming` có `WHERE status='queued'`; để mặc định thì worker nhận
    job xong bỏ lượt, và message rỗng ấy lại **vào ngữ cảnh** của lượt sau vì
    `USABLE_STATUSES` nhận `completed`.
    """
    conversation = await _create_conversation(session_factory, user_a)

    resp = await client.post(
        PATH.format(conversation.id),
        headers=_session(user_a),
        json={"content": "hoi mot cau"},
    )

    assistant = await _read_message(session_factory, uuid.UUID(resp.json()["assistant_message_id"]))
    assert assistant.status is MessageStatus.QUEUED


async def test_stream_url_points_to_t17_route(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """`stream_url` phải gọi được thật, không chỉ "trông giống đường dẫn"."""
    conversation = await _create_conversation(session_factory, user_a)

    resp = await client.post(
        PATH.format(conversation.id),
        headers=_session(user_a),
        json={"content": "xin chao"},
    )
    amid = resp.json()["assistant_message_id"]
    stream_url = resp.json()["stream_url"]

    assert stream_url == f"/api/v1/messages/{amid}/stream"
    # Gọi thẳng vào nó: 404 (message của user khác) sẽ lộ ra nếu đường dẫn sai
    # tiền tố, 200/500 nếu đúng. Chỉ cần nó KHÔNG phải 404-không-có-route.
    second_time = await client.get(stream_url, headers=_session(uuid.uuid4()))
    assert second_time.json()["error"]["code"] == "MESSAGE_NOT_FOUND"


# ═══════════════════════ A1 — không gọi model ở đây ═══════════════════════


async def test_does_not_wait_for_model_output(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """DoD/A1: response về khi `content` của assistant vẫn còn rỗng.

    Đây là phát biểu kiểm được của "endpoint trả về < 200 ms": nếu handler
    chờ model thì lúc nó trả lời, `messages.content` đã có chữ.
    """
    conversation = await _create_conversation(session_factory, user_a)

    resp = await client.post(
        PATH.format(conversation.id),
        headers=_session(user_a),
        json={"content": "viet cho toi 800 tu"},
    )

    assistant = await _read_message(session_factory, uuid.UUID(resp.json()["assistant_message_id"]))
    assert assistant.content == ""
    assert assistant.status is MessageStatus.QUEUED
    assert assistant.finish_reason is None
    assert assistant.prompt_tokens is None


# ═════════════════════════ nhánh (C14, §8.2) ══════════════════════════════


async def test_old_parent_id_returns_branched_and_tree_gains_branch(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """DoD: gửi với `parent_id` cũ → `branched: true`, và cây có thêm nhánh."""
    conversation = await _create_conversation(session_factory, user_a)
    auth_headers = _session(user_a)

    first = await client.post(
        PATH.format(conversation.id), headers=auth_headers, json={"content": "a"}
    )
    assert first.json()["branched"] is False
    root_user = uuid.UUID(first.json()["user_message_id"])

    second = await client.post(
        PATH.format(conversation.id),
        headers=auth_headers,
        json={"content": "b", "parent_id": str(root_user)},
    )

    assert second.status_code == 202
    assert second.json()["branched"] is True

    # Message user của lượt 1 nay có HAI con: assistant của lượt 1, và message
    # user của lượt 2. Đó đúng là "cây có thêm nhánh".
    async with session_factory() as session:
        child = await MessageRepository(session).get_siblings(
            conversation.id, root_user, user_id=user_a
        )
    assert len(child) == 2
    assert {m.id for m in child} == {
        uuid.UUID(first.json()["assistant_message_id"]),
        uuid.UUID(second.json()["user_message_id"]),
    }


async def test_parent_id_equal_to_current_leaf_is_not_a_branch(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """Gửi kèm `parent_id` ĐÚNG lá đang xem ⇒ `branched: false` (C14).

    C14 nói FE **luôn** gửi lá nó đang thấy; nếu mọi lần gửi đều bị gắn cờ
    `branched` thì cờ đó vô nghĩa và FE sẽ tắt nó đi.
    """
    conversation = await _create_conversation(session_factory, user_a)
    auth_headers = _session(user_a)

    first = await client.post(
        PATH.format(conversation.id), headers=auth_headers, json={"content": "a"}
    )
    leaf = first.json()["assistant_message_id"]

    second = await client.post(
        PATH.format(conversation.id),
        headers=auth_headers,
        json={"content": "b", "parent_id": leaf},
    )

    assert second.json()["branched"] is False


async def test_missing_parent_id_appends_to_viewed_leaf(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """Không gửi `parent_id` ⇒ dùng `active_leaf_id`, không phải `NULL`.

    Đây là chỗ `model_fields_set` khác `is None`: nếu handler đọc `parent_id`
    bằng `or active_leaf_id` thì `parent_id: null` (gốc nhánh mới) và "vắng
    hẳn" biến thành cùng một chuyện, và mọi lượt chat thứ hai sẽ thành một GỐC
    mới — hội thoại rơi thành N cây rời, model không thấy câu hỏi trước đó.
    """
    conversation = await _create_conversation(session_factory, user_a)
    auth_headers = _session(user_a)

    first = await client.post(
        PATH.format(conversation.id), headers=auth_headers, json={"content": "a"}
    )
    leaf = uuid.UUID(first.json()["assistant_message_id"])

    second = await client.post(
        PATH.format(conversation.id), headers=auth_headers, json={"content": "b"}
    )

    second_user_msg = await _read_message(
        session_factory, uuid.UUID(second.json()["user_message_id"])
    )
    assert second_user_msg.parent_id == leaf
    assert second.json()["branched"] is False


async def test_explicit_null_parent_id_creates_new_root(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """`parent_id: null` gửi tường minh ⇒ gốc thứ hai của hội thoại (§8.2)."""
    conversation = await _create_conversation(session_factory, user_a)
    auth_headers = _session(user_a)

    await client.post(PATH.format(conversation.id), headers=auth_headers, json={"content": "a"})
    second = await client.post(
        PATH.format(conversation.id),
        headers=auth_headers,
        json={"content": "b", "parent_id": None},
    )

    assert second.json()["branched"] is True
    second_user_msg = await _read_message(
        session_factory, uuid.UUID(second.json()["user_message_id"])
    )
    assert second_user_msg.parent_id is None

    async with session_factory() as session:
        roots = await MessageRepository(session).get_siblings(conversation.id, None, user_id=user_a)
    assert len(roots) == 2, "hai gốc trong một hội thoại — §8.2 cho phép"


async def test_parent_id_from_other_conversation_is_404(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """Nối hai cây của hai hội thoại làm một là đúng thứ `create_message` chặn."""
    first = await _create_conversation(session_factory, user_a)
    second = await _create_conversation(session_factory, user_a)
    auth_headers = _session(user_a)

    within_one = await client.post(
        PATH.format(first.id), headers=auth_headers, json={"content": "a"}
    )
    leaf_of_one = within_one.json()["assistant_message_id"]

    resp = await client.post(
        PATH.format(second.id),
        headers=auth_headers,
        json={"content": "b", "parent_id": leaf_of_one},
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PARENT_NOT_FOUND"
    assert await _count_messages(session_factory, second.id) == 0


# ═══════════════════ quyền sở hữu và danh tính (§20) ══════════════════════


async def test_other_users_conversation_404_and_writes_nothing(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """404 chứ không 403, và tuyệt đối không có hàng nào được ghi."""
    of_a = await _create_conversation(session_factory, user_a)

    resp = await client.post(
        PATH.format(of_a.id),
        headers=_session(user_b),
        json={"content": "toi khong so huu hoi thoai nay"},
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"
    assert await _count_messages(session_factory, of_a.id) == 0
    assert fake_arq.pushed == []


async def test_missing_conversation_is_404(
    client: AsyncClient,
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    resp = await client.post(
        PATH.format(uuid.uuid4()),
        headers=_session(user_a),
        json={"content": "a"},
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"


async def test_missing_session_cookie_is_401(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    conversation = await _create_conversation(session_factory, user_a)

    resp = await client.post(PATH.format(conversation.id), json={"content": "a"})

    assert resp.status_code == 401
    assert await _count_messages(session_factory, conversation.id) == 0


async def test_debug_on_opens_no_door(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """`DEBUG=true` không còn mua được gì — T-3.1c.

    Tới T-3.1b, bật `DEBUG` là mở nhánh danh tính tạm của Phase 1: một header
    người gọi tự gõ đủ để đi hết đường này. Ca này canh đúng chiều ngược lại —
    nhánh ấy chết rồi, nên `DEBUG` không đổi được kết cục của một request
    không mang cookie phiên. Nó là bản đảo của ca cũ (`DEBUG=false` ⇒ `503`),
    và nó chính là thứ sẽ đỏ nếu ai đó dựng lại một cửa sau thứ hai.
    """
    monkeypatch.setattr(settings, "DEBUG", True)
    conversation = await _create_conversation(session_factory, user_a)

    resp = await client.post(PATH.format(conversation.id), json={"content": "a"})

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"
    assert await _count_messages(session_factory, conversation.id) == 0


# ════════════════════════ chọn model (§9.2, A3) ═══════════════════════════


async def test_no_model_given_uses_catalog_default(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    conversation = await _create_conversation(session_factory, user_a)
    default = catalog.get_default_model()
    assert default is not None

    resp = await client.post(
        PATH.format(conversation.id),
        headers=_session(user_a),
        json={"content": "a"},
    )

    assistant = await _read_message(session_factory, uuid.UUID(resp.json()["assistant_message_id"]))
    assert assistant.model_id == default.id


async def test_conversation_default_model_beats_catalog_default(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    others = _non_default_model()
    conversation = await _create_conversation(session_factory, user_a, default_model=others)

    resp = await client.post(
        PATH.format(conversation.id),
        headers=_session(user_a),
        json={"content": "a"},
    )

    assistant = await _read_message(session_factory, uuid.UUID(resp.json()["assistant_message_id"]))
    assert assistant.model_id == others


async def test_request_model_id_beats_everything(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    default = catalog.get_default_model()
    assert default is not None
    conversation = await _create_conversation(session_factory, user_a, default_model=default.id)
    others = _non_default_model()

    resp = await client.post(
        PATH.format(conversation.id),
        headers=_session(user_a),
        json={"content": "a", "model_id": others},
    )

    assistant = await _read_message(session_factory, uuid.UUID(resp.json()["assistant_message_id"]))
    assert assistant.model_id == others


async def test_model_not_in_catalog_400_and_writes_nothing(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    conversation = await _create_conversation(session_factory, user_a)

    resp = await client.post(
        PATH.format(conversation.id),
        headers=_session(user_a),
        json={"content": "a", "model_id": "khong-ton-tai"},
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "MODEL_UNKNOWN"
    assert resp.json()["error"]["details"] == {"model_id": "khong-ton-tai"}
    assert await _count_messages(session_factory, conversation.id) == 0


async def test_disabled_model_is_also_400(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """`enabled: false` phải chặn cả đường gọi, không chỉ ẩn khỏi Model Picker."""
    others = _non_default_model()
    conversation = await _create_conversation(session_factory, user_a)
    monkeypatch.setattr(catalog, "get_model", lambda _: None)

    resp = await client.post(
        PATH.format(conversation.id),
        headers=_session(user_a),
        json={"content": "a", "model_id": others},
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "MODEL_UNKNOWN"


async def test_no_enabled_model_left_is_503(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """Sự cố cấu hình phía server ⇒ 5xx, không phải 4xx của người gọi."""
    conversation = await _create_conversation(session_factory, user_a)
    monkeypatch.setattr(catalog, "get_default_model", lambda: None)

    resp = await client.post(
        PATH.format(conversation.id),
        headers=_session(user_a),
        json={"content": "a"},
    )

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "NO_MODEL_AVAILABLE"
    assert await _count_messages(session_factory, conversation.id) == 0


# ════════════ DoD: lỗi giữa transaction ⇒ KHÔNG có message mồ côi ═════════


async def test_enqueue_failure_leaves_no_orphan_message(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """DoD: ép enqueue thất bại → 0 message, `active_leaf_id` không nhúc nhích.

    Đây là lý do `enqueue` nằm TRONG transaction. Đảo lại (commit trước,
    enqueue sau) thì ca này để lại hai message `queued` **vĩnh viễn**: reaper
    §7.6 chỉ dọn `status='streaming'`.
    """
    conversation = await _create_conversation(session_factory, user_a)
    fake_arq.raises = True

    resp = await client.post(
        PATH.format(conversation.id),
        headers=_session(user_a),
        json={"content": "a"},
    )

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "ENQUEUE_FAILED"
    assert await _count_messages(session_factory, conversation.id) == 0
    assert await _active_leaf(session_factory, conversation.id) is None


async def test_arq_rejecting_job_also_leaves_no_orphan_message(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """Ngả thứ hai: `enqueue_job` trả `None` thay vì ném — cũng phải rollback."""
    conversation = await _create_conversation(session_factory, user_a)
    fake_arq.returns_none = True

    resp = await client.post(
        PATH.format(conversation.id),
        headers=_session(user_a),
        json={"content": "a"},
    )

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "ENQUEUE_FAILED"
    assert await _count_messages(session_factory, conversation.id) == 0
    assert await _active_leaf(session_factory, conversation.id) is None


async def test_job_id_equals_assistant_message_id(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """B-92: `_job_id` phải là chính `assistant_message_id`, không phải gì khác.

    Lớp chống trùng của **hàng đợi**, độc lập với `Idempotency-Key` của §11.4
    (§11.4 chặn ở mức request, cái này ở mức job). Bỏ `_job_id` đi thì arq sinh
    một id ngẫu nhiên mỗi lần và lớp này biến mất **trong im lặng** — không
    lỗi, không log, chỉ là một phép chống trùng không bao giờ chặn ai.
    """
    conversation = await _create_conversation(session_factory, user_a)

    resp = await client.post(
        PATH.format(conversation.id),
        headers=_session(user_a),
        json={"content": "a"},
    )

    assert resp.status_code == 202
    amid = resp.json()["assistant_message_id"]
    assert fake_arq.used_job_ids == [amid]


# ═════════════════════ body và Idempotency-Key (§11.4) ════════════════════


# ══════════════ MESSAGE_MAX_CHARS — cửa chặn đầu tiên (T-3.0, B-205) ═══════


async def test_content_one_char_over_cap_422_and_writes_nothing(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """Đúng ca âm của DoD T-3.0: `MESSAGE_MAX_CHARS + 1` ký tự.

    Trước NQ-78, cùng request này trả `202`, ghi **hai** hàng `messages` và chỉ
    nổ `CONTEXT_TOO_LARGE` ở `llm/context.py` khi worker dựng ngữ cảnh — tức
    sau khi đã tiêu một lượt `Idempotency-Key`. `_dem_message == 0` là phép đo
    nói rằng trần nay đứng **trước** Postgres, không sau.
    """
    conversation = await _create_conversation(session_factory, user_a)

    resp = await client.post(
        PATH.format(conversation.id),
        headers=_session(user_a),
        json={"content": "a" * (settings.MESSAGE_MAX_CHARS + 1)},
    )

    assert resp.status_code == 422
    assert await _count_messages(session_factory, conversation.id) == 0
    assert fake_arq.pushed == []


async def test_content_exactly_at_cap_passes(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """Biên là `<=`, không phải `<` — một trần lệch một ký tự là một trần sai.

    Cặp với test trên: không có nó thì `max_length=0` cũng làm test kia xanh.
    """
    conversation = await _create_conversation(session_factory, user_a)

    resp = await client.post(
        PATH.format(conversation.id),
        headers=_session(user_a),
        json={"content": "a" * settings.MESSAGE_MAX_CHARS},
    )

    assert resp.status_code == 202
    assert await _count_messages(session_factory, conversation.id) == 2


@pytest.mark.parametrize("body", [{}, {"content": ""}, {"content": "a", "parent_id": "khong-uuid"}])
async def test_bad_body_is_422(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    body: dict[str, Any],
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    conversation = await _create_conversation(session_factory, user_a)

    resp = await client.post(PATH.format(conversation.id), headers=_session(user_a), json=body)

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
    assert await _count_messages(session_factory, conversation.id) == 0


async def test_two_sends_same_key_create_one_turn(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """§11.4 nhìn từ phía endpoint: hai POST cùng key ⇒ **một** lượt sinh.

    T-1.8 để lại ca này khẳng định hành vi **chưa đúng** (hai key giống nhau
    cho bốn message) để T-2.8 buộc phải sửa nó. Đây là bản sau khi sửa: cùng
    một `Idempotency-Key` cho đúng hai message, đúng một job, và lần thứ hai
    trả **cùng** `assistant_message_id` — tức tiêu chí S5.

    Luật ở đây được kiểm đầy đủ trong `tests/api/test_idempotency.py`; ca này
    ở lại `test_messages.py` vì nó nói về hợp đồng của chính endpoint này.
    """
    conversation = await _create_conversation(session_factory, user_a)
    auth_headers = _session(user_a)
    headers = {"Idempotency-Key": "khoa-cua-mot-lan-soan-thao"}

    first = await client.post(
        PATH.format(conversation.id), headers=auth_headers | headers, json={"content": "a"}
    )
    second = await client.post(
        PATH.format(conversation.id), headers=auth_headers | headers, json={"content": "a"}
    )

    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    assert second.headers["Idempotent-Replay"] == "true"
    assert await _count_messages(session_factory, conversation.id) == 2
    assert len(fake_arq.pushed) == 1


async def test_missing_idempotency_key_is_400(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """DoD T-2.8 dòng 3 + A8: header là **bắt buộc** với đúng endpoint này.

    Dựng client riêng, KHÔNG có `event_hooks` của `tests/api/conftest.py`: chỗ
    này cần một request thật sự vắng header, còn fixture `client` cố ý gắn một
    key mới cho mọi POST (xem docstring conftest).
    """
    conversation = await _create_conversation(session_factory, user_a)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://localhost"
    ) as no_hook:
        resp = await no_hook.post(
            PATH.format(conversation.id),
            headers=_session(user_a),
            json={"content": "a"},
        )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert await _count_messages(session_factory, conversation.id) == 0


def test_route_name_matches_function() -> None:
    """Hai hằng tên route phải là tên FastAPI thực sự đặt cho hai route ấy.

    FastAPI lấy tên route từ **tên hàm**, nên đổi tên `create_message` (hoặc
    `retry_message`) mà quên hằng tương ứng sẽ gỡ luật "bắt buộc
    `Idempotency-Key`" trong im lặng: danh sách ở `api/v1/__init__.py` trỏ vào
    một tên không route nào mang, và endpoint đắt tiền nhất của app lại thành
    "tuỳ chọn" mà không một dòng log nào kêu.

    Đẳng thức kiểm **cả hai chiều** (NQ-93/B-231): thêm một tên vào
    `IDEMPOTENCY_REQUIRED_ROUTES` mà không có route nào mang nó cũng đỏ ở đây,
    không đợi tới lúc người dùng bấm nút.
    """
    assert frozenset({CREATE_MESSAGE_ROUTE_NAME, RETRY_ROUTE_NAME}) == IDEMPOTENCY_REQUIRED_ROUTES
    # `url_path_for` ném `NoMatchFound` nếu không route nào mang tên ấy — đó
    # chính là phép kiểm. Đi đường này chứ không duyệt `app.routes` vì từ
    # FastAPI 0.141 `include_router` giữ router lồng nhau (`_IncludedRouter`)
    # thay vì trải phẳng, nên `app.routes` không còn là danh sách route nữa.
    path = app.url_path_for(CREATE_MESSAGE_ROUTE_NAME, conversation_id=str(uuid.uuid4()))
    retry_path = app.url_path_for(RETRY_ROUTE_NAME, message_id=str(uuid.uuid4()))

    assert str(path).endswith("/messages")
    assert str(retry_path).endswith("/retry")


# ═══════════════ A1 dạng kiểm được bằng grep (§5.3, DoD) ══════════════════


def test_api_layer_imports_nothing_from_providers() -> None:
    """DoD: `grep -rnE "litellm|openai|AsyncOpenAI" backend/app/api/` phải rỗng.

    Chạy lại phép grep đó trong bộ test chứ không chỉ trong
    `scripts/check_hardcode.sh`: `make test` chạy ở mọi vòng sửa code, còn
    `make check-hardcode` thì người ta nhớ chạy lúc sắp commit.

    **Phân biệt hoa/thường, đúng như `grep -E` mặc định.** Bật `IGNORECASE`
    làm test này đỏ ở `health.py`, nơi một docstring liệt kê "LiteLLM" trong
    danh sách thứ `/health/deep` kiểm — tức là báo động giả trên một dòng chú
    thích. Một phép kiểm báo động giả là một phép kiểm sắp bị tắt.
    """
    import re
    from pathlib import Path

    pattern = re.compile(r"litellm|openai|AsyncOpenAI")
    directory = Path(__file__).resolve().parents[2] / "app" / "api"
    violations = [
        f"{f}:{so}"
        for f in sorted(directory.rglob("*.py"))
        for so, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]
    assert violations == []
