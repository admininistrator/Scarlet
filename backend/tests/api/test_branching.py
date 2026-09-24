"""T-1.13 — retry, sửa câu hỏi, chuyển nhánh, đọc anh em (§8.2, §8.3, §18.2, UC-04).

Năm dòng DoD của task nằm ở các test có chữ **DoD** trong docstring.

Cùng lối đi với `test_messages.py` và `test_conversations.py`:
`httpx.ASGITransport` (không `TestClient`, vì `connection` của `conftest.py` là
kết nối asyncpg gắn với event loop của chính test), `DEBUG` bật tay, và
`session_scope()` trong handler bị trỏ về đúng kết nối của test.

`arq_gia` thay chỗ `get_arq_pool` vì pool thật nối tới `redis:6379` — một host
chỉ phân giải được **bên trong** network `internal` của compose, mà `make test`
chạy từ WSL host. Nó cũng là chỗ đo "có đúng một job mới cho mỗi nhánh mới".

**Câu mà gần như mọi test ở đây kiểm lại từ một góc khác:** không thao tác nào
của T-1.13 được **sửa hoặc xoá** một hàng đã có. Đó là cạm bẫy task gọi tên
("cám dỗ xoá nhánh cũ cho gọn") và là lý do duy nhất cây message tồn tại (§8.1).
Vì thế các test không chỉ khẳng định "nhánh mới đúng" mà còn đọc lại hàng cũ và
khẳng định nó **không đổi một cột nào**.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import catalog
from app.config.settings import settings
from app.core.access_token import encode_access_token
from app.core.deps import SESSION_COOKIE_NAME
from app.db.models import Conversation, Message, MessageRole, MessageStatus, UserRole, UserStatus
from app.db.repositories import ConversationRepository, MessageRepository
from app.main import app

CREATE_MESSAGE = "/api/v1/conversations/{}/messages"
RETRY = "/api/v1/messages/{}/retry"
EDIT_MESSAGE = "/api/v1/messages/{}"
SIBLINGS = "/api/v1/messages/{}/siblings"
CONVERSATION = "/api/v1/conversations/{}"


class FakeArq:
    """Pool arq giả — ghi lại mọi lần enqueue, có công tắc để ép nó ném.

    Bản rút gọn của `FakeArq` trong `test_messages.py`: ở đây không cần ngả
    "arq trả `None`" (T-1.8 đã đo nó cho `_day_job`, và ba endpoint mới dùng
    **chung** hàm đó), nhưng vẫn cần ngả "Redis chết" để đo rollback.
    """

    def __init__(self) -> None:
        self.pushed: list[tuple[str, tuple[Any, ...]]] = []
        self.raises = False

    async def enqueue_job(self, name: str, *args: Any, **_: Any) -> object | None:
        if self.raises:
            raise ConnectionError("redis chet giua chung (gia lap)")
        self.pushed.append((name, args))
        return object()


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
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID, **columns: Any
) -> Conversation:
    async with session_factory() as session:
        conversation = await ConversationRepository(session).create_conversation(
            user_id=user_id, **columns
        )
        await session.commit()
        return conversation


async def _read_message(
    session_factory: async_sessionmaker[AsyncSession], message_id: uuid.UUID
) -> Message:
    """Đọc bằng session MỚI: repository ghi bằng UPDATE thẳng, identity map của
    session cũ sẽ trả lại object cũ. Xem docstring `session_factory`."""
    async with session_factory() as session:
        message = await session.get(Message, message_id)
        assert message is not None
        return message


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


#: Hai `id` dựng tay cho các ca thứ tự ở dưới. UUID sinh ngẫu nhiên thì quan hệ
#: lớn-bé giữa hai anh em là ngẫu nhiên, nên một ca "khoá `id` không được quyết"
#: sẽ đúng 50% số lần chạy — tức không đo gì. Hai hằng này cắt đứt chuyện đó.
_SMALL_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
_BIG_ID = uuid.UUID("ffffffff-0000-4000-8000-00000000000f")


async def _insert_message(
    session_factory: async_sessionmaker[AsyncSession],
    conversation_id: uuid.UUID,
    parent_id: uuid.UUID | None,
    role: MessageRole,
    seconds: int,
    *,
    id: uuid.UUID | None = None,
) -> uuid.UUID:
    """`INSERT` thẳng một message với `id` và `created_at` DO TEST CHỌN.

    Ngoại lệ có chủ ý với luật "đi qua endpoint thật" ở `_one_turn`: ba khoá
    sắp xếp của `get_deepest_leaf` chỉ phân biệt được nhau khi test điều khiển
    được cả thời điểm lẫn `id`, mà không endpoint nào cho làm việc đó — đúng
    như vậy, vì cả hai là do DB sinh.
    """
    new_id = uuid.uuid4() if id is None else id
    async with session_factory() as session:
        await session.execute(
            Message.__table__.insert().values(
                id=new_id,
                conversation_id=conversation_id,
                parent_id=parent_id,
                role=role,
                status=MessageStatus.COMPLETED,
                content=f"node {seconds}",
                created_at=datetime(2026, 9, 22, 0, 0, seconds, tzinfo=UTC),
            )
        )
        await session.commit()
    return new_id


async def _active_leaf(
    session_factory: async_sessionmaker[AsyncSession], conversation_id: uuid.UUID
) -> uuid.UUID | None:
    async with session_factory() as session:
        stmt = select(Conversation.active_leaf_id).where(Conversation.id == conversation_id)
        return (await session.execute(stmt)).scalar_one()


async def _complete(
    session_factory: async_sessionmaker[AsyncSession], message_id: uuid.UUID, content: str
) -> None:
    """Khép một lượt sinh như worker làm (§7.2 ③).

    Không có bước này thì mọi message assistant do `POST .../messages` tạo ra
    còn nằm ở `queued`, và `retry` sẽ đúng đắn trả `409` — tức mọi test nhánh
    sẽ đo nhầm một phép kiểm khác.
    """
    async with session_factory() as session:
        await MessageRepository(session).finish_generation(
            message_id,
            status=MessageStatus.COMPLETED,
            content=content,
            finish_reason="stop",
        )
        await session.commit()


async def _one_turn(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    question: str,
    *,
    answer: str = "tra loi",
    **body: Any,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Một lượt chat trọn vẹn qua HTTP, đã khép. Trả `(user_id, assistant_id)`.

    Đi qua đúng endpoint thật chứ không `INSERT` tay: cây mà các test này thao
    tác phải là cây mà `POST .../messages` thật sự dựng ra, nếu không thì
    `parent_id` và `active_leaf_id` chỉ đúng trong tưởng tượng của test.
    """
    resp = await client.post(
        CREATE_MESSAGE.format(conversation_id),
        headers=_session(user_id),
        json={
            "content": question,
            **body,
        },
    )
    assert resp.status_code == 202, resp.text
    uid = uuid.UUID(resp.json()["user_message_id"])
    amid = uuid.UUID(resp.json()["assistant_message_id"])
    await _complete(session_factory, amid, answer)
    return uid, amid


def _non_default_model() -> str:
    """Một `model_id` đang bật, KHÁC model `default`. A3: không gõ tên vào đây."""
    default = catalog.get_default_model()
    assert default is not None
    others = [m.id for m in catalog.get_catalog().models if m.enabled and m.id != default.id]
    assert others, "catalog phải có ít nhất hai model bật thì test này mới có nghĩa"
    return others[0]


# ═══════════════ POST /messages/{id}/retry — tạo anh em (§8.2) ═════════════


async def test_retry_creates_sibling_assistant_same_parent(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """202, assistant mới cùng `parent_id`, `queued`, một job, lá dời sang nó."""
    conversation = await _create_conversation(session_factory, user_a)
    uid, amid = await _one_turn(client, session_factory, conversation.id, user_a, "a")
    fake_arq.pushed.clear()

    resp = await client.post(RETRY.format(amid), headers=_session(user_a))

    assert resp.status_code == 202, resp.text
    new_id = uuid.UUID(resp.json()["assistant_message_id"])
    assert new_id != amid

    new_version = await _read_message(session_factory, new_id)
    assert new_version.role is MessageRole.ASSISTANT
    assert new_version.parent_id == uid, "ANH EM của bản cũ, không phải con của nó"
    assert new_version.status is MessageStatus.QUEUED
    assert new_version.content == ""

    assert await _active_leaf(session_factory, conversation.id) == new_id
    assert fake_arq.pushed == [("generate", (str(new_id),))]
    assert resp.json()["stream_url"] == f"/api/v1/messages/{new_id}/stream"


async def test_retry_does_not_touch_old_version(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """Cạm bẫy của task: bản cũ giữ NGUYÊN `content`, `status`, `model_id`.

    Ngả sai — "ghi đè cho gọn" — không làm hỏng response nào, nên chỉ có phép
    kiểm này bắt được: câu trả lời cũ biến mất khỏi DB mà không ai báo gì.
    """
    conversation = await _create_conversation(session_factory, user_a)
    _, amid = await _one_turn(
        client, session_factory, conversation.id, user_a, "a", answer="cau tra loi cu"
    )
    before = await _read_message(session_factory, amid)
    old_model, old_deleted_at = before.model_id, before.deleted_at

    await client.post(
        RETRY.format(amid),
        headers=_session(user_a),
        json={"model_id": _non_default_model()},
    )

    after = await _read_message(session_factory, amid)
    assert after.content == "cau tra loi cu"
    assert after.status is MessageStatus.COMPLETED
    assert after.finish_reason == "stop"
    assert after.model_id == old_model
    assert after.deleted_at is old_deleted_at is None


async def test_retry_twice_sibling_count_three_all_three_in_db(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """**DoD 2** — retry 2 lần → `sibling_count == 3`, cả ba đều còn trong DB."""
    conversation = await _create_conversation(session_factory, user_a)
    uid, amid = await _one_turn(client, session_factory, conversation.id, user_a, "a")

    first = await client.post(RETRY.format(amid), headers=_session(user_a))
    second = await client.post(RETRY.format(amid), headers=_session(user_a))
    three_ids = [
        amid,
        uuid.UUID(first.json()["assistant_message_id"]),
        uuid.UUID(second.json()["assistant_message_id"]),
    ]

    resp = await client.get(SIBLINGS.format(amid), headers=_session(user_a))
    assert resp.status_code == 200, resp.text
    assert resp.json()["sibling_count"] == 3
    assert [uuid.UUID(m["id"]) for m in resp.json()["items"]] == three_ids

    # "Còn trong DB" đọc thẳng từ bảng, không qua API: một endpoint lọc
    # `deleted_at IS NULL` sẽ nói dối đúng ở ca người ta sợ nhất (xoá mềm).
    for mid in three_ids:
        row = await _read_message(session_factory, mid)
        assert row.deleted_at is None
        assert row.parent_id == uid
    assert await _count_messages(session_factory, conversation.id) == 4


async def test_retry_other_model_old_branch_unchanged(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """**DoD 3** — nhánh mới mang `model_id` mới, nhánh cũ giữ model cũ."""
    default = catalog.get_default_model()
    assert default is not None
    others = _non_default_model()
    conversation = await _create_conversation(session_factory, user_a)
    _, amid = await _one_turn(client, session_factory, conversation.id, user_a, "a")
    assert (await _read_message(session_factory, amid)).model_id == default.id

    resp = await client.post(
        RETRY.format(amid), headers=_session(user_a), json={"model_id": others}
    )

    assert resp.json()["model_id"] == others
    new_id = await _read_message(session_factory, uuid.UUID(resp.json()["assistant_message_id"]))
    assert new_id.model_id == others
    assert (await _read_message(session_factory, amid)).model_id == default.id


async def test_retry_without_model_reuses_old_versions_model(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """Bấm Retry trơn ⇒ sinh lại bằng ĐÚNG model cũ, không phải model mặc định.

    Hội thoại để `default_model` là model `default` của catalog, còn lượt kia
    gọi đích danh một model khác — nếu `_pick_model` bỏ qua mức giữa
    (`messages.model_id`) thì bản retry sẽ lặng lẽ rơi về model mặc định.
    """
    default = catalog.get_default_model()
    assert default is not None
    others = _non_default_model()
    conversation = await _create_conversation(session_factory, user_a, default_model=default.id)
    _, amid = await _one_turn(
        client, session_factory, conversation.id, user_a, "a", model_id=others
    )

    resp = await client.post(RETRY.format(amid), headers=_session(user_a))

    assert resp.json()["model_id"] == others


async def test_retry_user_message_is_400(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """Sinh lại một câu HỎI không có nghĩa — đường sửa câu hỏi là `PATCH`."""
    conversation = await _create_conversation(session_factory, user_a)
    uid, _ = await _one_turn(client, session_factory, conversation.id, user_a, "a")
    before = await _count_messages(session_factory, conversation.id)
    fake_arq.pushed.clear()

    resp = await client.post(RETRY.format(uid), headers=_session(user_a))

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "MESSAGE_ROLE_MISMATCH"
    assert resp.json()["error"]["details"] == {"role": "user", "expected": "assistant"}
    assert await _count_messages(session_factory, conversation.id) == before
    assert fake_arq.pushed == []


@pytest.mark.parametrize("status", [MessageStatus.QUEUED, MessageStatus.STREAMING])
async def test_retry_while_previous_turn_open_is_409(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    status: MessageStatus,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """Hai lượt sinh cho cùng một `parent_id` = trả tiền hai lần. Chặn ở 409.

    Không dùng `_one_turn` (nó khép lượt lại): ở đây message assistant phải
    còn đúng trạng thái đang chạy.
    """
    conversation = await _create_conversation(session_factory, user_a)
    resp = await client.post(
        CREATE_MESSAGE.format(conversation.id), headers=_session(user_a), json={"content": "a"}
    )
    amid = uuid.UUID(resp.json()["assistant_message_id"])
    if status is MessageStatus.STREAMING:
        async with session_factory() as session:
            await MessageRepository(session).mark_streaming(
                amid, model_id="bat-ky", reasoning_effort=None
            )
            await session.commit()
    before = await _count_messages(session_factory, conversation.id)
    fake_arq.pushed.clear()

    second_time = await client.post(RETRY.format(amid), headers=_session(user_a))

    assert second_time.status_code == 409
    assert second_time.json()["error"]["code"] == "GENERATION_IN_PROGRESS"
    assert second_time.json()["error"]["details"] == {"status": status.value}
    assert await _count_messages(session_factory, conversation.id) == before
    assert fake_arq.pushed == []


async def test_retry_other_users_message_404_and_writes_nothing(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """IDOR (§20): 404 chứ không 403, và tuyệt đối không hàng nào được ghi."""
    conversation = await _create_conversation(session_factory, user_a)
    _, amid = await _one_turn(client, session_factory, conversation.id, user_a, "a")
    before = await _count_messages(session_factory, conversation.id)
    fake_arq.pushed.clear()

    resp = await client.post(RETRY.format(amid), headers=_session(user_b))

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "MESSAGE_NOT_FOUND"
    assert await _count_messages(session_factory, conversation.id) == before
    assert fake_arq.pushed == []


async def test_retry_model_not_in_catalog_400_and_writes_nothing(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    conversation = await _create_conversation(session_factory, user_a)
    _, amid = await _one_turn(client, session_factory, conversation.id, user_a, "a")
    before = await _count_messages(session_factory, conversation.id)

    resp = await client.post(
        RETRY.format(amid), headers=_session(user_a), json={"model_id": "khong-ton-tai"}
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "MODEL_UNKNOWN"
    assert await _count_messages(session_factory, conversation.id) == before


async def test_retry_enqueue_failure_leaves_no_orphan_message(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """`enqueue` nằm TRONG transaction ở cả ba đường, không riêng T-1.8.

    Ngả ngược lại để lại một message `queued` **vĩnh viễn** (reaper §7.6 chỉ
    dọn `streaming`) và một `active_leaf_id` trỏ vào nó — tức hội thoại kẹt ở
    một bong bóng rỗng không bao giờ có chữ.
    """
    conversation = await _create_conversation(session_factory, user_a)
    _, amid = await _one_turn(client, session_factory, conversation.id, user_a, "a")
    before = await _count_messages(session_factory, conversation.id)
    fake_arq.raises = True

    resp = await client.post(RETRY.format(amid), headers=_session(user_a))

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "ENQUEUE_FAILED"
    assert await _count_messages(session_factory, conversation.id) == before
    assert await _active_leaf(session_factory, conversation.id) == amid


# ════════ PATCH /messages/{id} — sửa câu hỏi thành một nhánh (§8.2) ════════


async def test_edit_user_message_creates_sibling_and_new_generation(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """202, user mới cùng `parent_id`, assistant `queued` làm con của nó."""
    conversation = await _create_conversation(session_factory, user_a)
    u1, a1 = await _one_turn(client, session_factory, conversation.id, user_a, "cau hoi 1")
    u2, _ = await _one_turn(client, session_factory, conversation.id, user_a, "cau hoi 2")
    fake_arq.pushed.clear()

    resp = await client.patch(
        EDIT_MESSAGE.format(u2), headers=_session(user_a), json={"content": "cau hoi 2 da sua"}
    )

    assert resp.status_code == 202, resp.text
    u2b = uuid.UUID(resp.json()["user_message_id"])
    a2b = uuid.UUID(resp.json()["assistant_message_id"])
    assert u2b != u2

    edited = await _read_message(session_factory, u2b)
    assert edited.role is MessageRole.USER
    assert edited.content == "cau hoi 2 da sua"
    assert edited.parent_id == a1, "ANH EM của bản cũ ⇒ cùng cha là a1"

    answer = await _read_message(session_factory, a2b)
    assert answer.role is MessageRole.ASSISTANT
    assert answer.parent_id == u2b
    assert answer.status is MessageStatus.QUEUED

    assert await _active_leaf(session_factory, conversation.id) == a2b
    assert fake_arq.pushed == [("generate", (str(a2b),))]
    assert resp.json()["stream_url"] == f"/api/v1/messages/{a2b}/stream"
    assert u1 is not None  # u1 chỉ để dựng cây, giữ tên cho dễ đọc


async def test_edit_message_does_not_touch_old_version(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """`PATCH` không sửa hàng nào — `messages.content` cũ không đổi một ký tự."""
    conversation = await _create_conversation(session_factory, user_a)
    u1, _ = await _one_turn(client, session_factory, conversation.id, user_a, "ban goc")

    await client.patch(
        EDIT_MESSAGE.format(u1), headers=_session(user_a), json={"content": "ban sua"}
    )

    old = await _read_message(session_factory, u1)
    assert old.content == "ban goc"
    assert old.deleted_at is None


async def test_edit_mid_conversation_old_child_branch_still_reachable(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """**DoD 4** — sửa message user ở giữa, nhánh con cũ vẫn mở lại được bằng
    `active_leaf_id` cũ.

    Cây trước khi sửa: `u1 → a1 → u2 → a2` (lá = `a2`). Sau khi sửa `u2`, lá
    dời sang nhánh mới; trả lá về `a2` phải cho lại **đúng** đường đi cũ, kể cả
    nội dung câu hỏi cũ.
    """
    conversation = await _create_conversation(session_factory, user_a)
    u1, a1 = await _one_turn(client, session_factory, conversation.id, user_a, "cau hoi 1")
    u2, a2 = await _one_turn(client, session_factory, conversation.id, user_a, "cau hoi 2")
    old_leaf = a2

    edit = await client.patch(
        EDIT_MESSAGE.format(u2), headers=_session(user_a), json={"content": "cau hoi 2 khac han"}
    )
    u2b = uuid.UUID(edit.json()["user_message_id"])
    a2b = uuid.UUID(edit.json()["assistant_message_id"])

    # Màn hình ngay sau khi sửa: nhánh MỚI.
    right_after = await client.get(CONVERSATION.format(conversation.id), headers=_session(user_a))
    assert [uuid.UUID(m["id"]) for m in right_after.json()["path"]] == [u1, a1, u2b, a2b]

    # Quay về lá cũ — đúng một `PATCH`, không khôi phục gì cả.
    back_to_old = await client.patch(
        CONVERSATION.format(conversation.id),
        headers=_session(user_a),
        json={"active_leaf_id": str(old_leaf)},
    )
    assert back_to_old.status_code == 200, back_to_old.text
    assert [uuid.UUID(m["id"]) for m in back_to_old.json()["path"]] == [u1, a1, u2, a2]
    assert back_to_old.json()["path"][2]["content"] == "cau hoi 2"
    # Và `‹ n/m ›` của câu hỏi cũ nay là 1/2 — C13 do API trả, FE không tự đếm.
    assert back_to_old.json()["path"][2]["sibling_index"] == 0
    assert back_to_old.json()["path"][2]["sibling_count"] == 2


async def test_edit_root_message_creates_second_root(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """Sửa câu hỏi ĐẦU TIÊN ⇒ hai gốc (`parent_id` NULL) trong một hội thoại.

    §8.2 cho phép, và `IS NOT DISTINCT FROM` của §8.3 tồn tại chính vì ca này:
    viết `parent_id = NULL` thì mọi gốc báo "0 anh em" và `‹ n/m ›` biến mất
    đúng lúc người dùng cần nó nhất.
    """
    conversation = await _create_conversation(session_factory, user_a)
    u1, _ = await _one_turn(client, session_factory, conversation.id, user_a, "goc 1")

    edit = await client.patch(
        EDIT_MESSAGE.format(u1), headers=_session(user_a), json={"content": "goc 2"}
    )
    u1b = uuid.UUID(edit.json()["user_message_id"])

    assert (await _read_message(session_factory, u1b)).parent_id is None
    siblings = await client.get(SIBLINGS.format(u1), headers=_session(user_a))
    assert siblings.json()["parent_id"] is None
    assert siblings.json()["sibling_count"] == 2
    assert [uuid.UUID(m["id"]) for m in siblings.json()["items"]] == [u1, u1b]


async def test_edit_assistant_message_is_400(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """Sửa lời của model rồi để nó vào ngữ cảnh lượt sau là bịa lịch sử."""
    conversation = await _create_conversation(session_factory, user_a)
    _, amid = await _one_turn(client, session_factory, conversation.id, user_a, "a")
    before = await _count_messages(session_factory, conversation.id)

    resp = await client.patch(
        EDIT_MESSAGE.format(amid), headers=_session(user_a), json={"content": "toi noi ho model"}
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "MESSAGE_ROLE_MISMATCH"
    assert resp.json()["error"]["details"] == {"role": "assistant", "expected": "user"}
    assert await _count_messages(session_factory, conversation.id) == before


async def test_edit_message_over_cap_422_and_writes_nothing(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """`MESSAGE_MAX_CHARS` áp cho CẢ HAI schema (T-3.0, B-205).

    B-205 đếm được hai chỗ thiếu trần, và một nhánh sửa câu hỏi không có trần
    là đúng đường vòng mà bản vá đang đóng: `PATCH` cũng tạo một message mới
    và cũng đẩy một job.
    """
    conversation = await _create_conversation(session_factory, user_a)
    u1, _ = await _one_turn(client, session_factory, conversation.id, user_a, "a")
    before = await _count_messages(session_factory, conversation.id)
    fake_arq.pushed.clear()

    resp = await client.patch(
        EDIT_MESSAGE.format(u1),
        headers=_session(user_a),
        json={"content": "a" * (settings.MESSAGE_MAX_CHARS + 1)},
    )

    assert resp.status_code == 422
    assert await _count_messages(session_factory, conversation.id) == before
    assert fake_arq.pushed == []


async def test_edit_other_users_message_404_and_writes_nothing(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    conversation = await _create_conversation(session_factory, user_a)
    u1, _ = await _one_turn(client, session_factory, conversation.id, user_a, "a")
    before = await _count_messages(session_factory, conversation.id)
    fake_arq.pushed.clear()

    resp = await client.patch(
        EDIT_MESSAGE.format(u1), headers=_session(user_b), json={"content": "cua toi day"}
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "MESSAGE_NOT_FOUND"
    assert await _count_messages(session_factory, conversation.id) == before
    assert fake_arq.pushed == []
    assert (await _read_message(session_factory, u1)).content == "a"


async def test_edit_message_empty_content_is_422(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """Sửa thành rỗng = trả tiền cho một lượt sinh không có câu hỏi."""
    conversation = await _create_conversation(session_factory, user_a)
    u1, _ = await _one_turn(client, session_factory, conversation.id, user_a, "a")
    before = await _count_messages(session_factory, conversation.id)

    resp = await client.patch(
        EDIT_MESSAGE.format(u1), headers=_session(user_a), json={"content": ""}
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
    assert await _count_messages(session_factory, conversation.id) == before


# ═════ PATCH /conversations/{id} — chuyển nhánh và metadata (§18.2) ════════


async def test_changing_active_leaf_id_changes_path(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """Chuyển nhánh chỉ đổi con trỏ — số message trong DB không nhúc nhích."""
    conversation = await _create_conversation(session_factory, user_a)
    u1, a1 = await _one_turn(client, session_factory, conversation.id, user_a, "a")
    retry = await client.post(RETRY.format(a1), headers=_session(user_a))
    a1b = uuid.UUID(retry.json()["assistant_message_id"])
    before = await _count_messages(session_factory, conversation.id)

    resp = await client.patch(
        CONVERSATION.format(conversation.id),
        headers=_session(user_a),
        json={"active_leaf_id": str(a1)},
    )

    assert resp.status_code == 200, resp.text
    assert uuid.UUID(resp.json()["active_leaf_id"]) == a1
    assert [uuid.UUID(m["id"]) for m in resp.json()["path"]] == [u1, a1]
    assert resp.json()["path"][1]["sibling_count"] == 2
    assert await _active_leaf(session_factory, conversation.id) == a1
    assert await _count_messages(session_factory, conversation.id) == before
    assert (await _read_message(session_factory, a1b)).deleted_at is None


async def test_switch_branch_then_new_message_attaches_to_viewed_branch(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """**DoD 5** — chuyển nhánh rồi gửi tin nhắn mới → gắn đúng nhánh đang xem.

    Cây: `u1 → a1` với `a1` có hai anh em (`a1`, `a1b`). Đang xem `a1b` mà trả
    lá về `a1` rồi gửi tiếp thì lượt mới phải mọc dưới `a1`, không phải `a1b`.
    """
    conversation = await _create_conversation(session_factory, user_a)
    _, a1 = await _one_turn(client, session_factory, conversation.id, user_a, "a")
    retry = await client.post(RETRY.format(a1), headers=_session(user_a))
    a1b = uuid.UUID(retry.json()["assistant_message_id"])
    assert await _active_leaf(session_factory, conversation.id) == a1b

    await client.patch(
        CONVERSATION.format(conversation.id),
        headers=_session(user_a),
        json={"active_leaf_id": str(a1)},
    )
    next_resp = await client.post(
        CREATE_MESSAGE.format(conversation.id), headers=_session(user_a), json={"content": "tiep"}
    )

    assert next_resp.json()["branched"] is False, "nối vào đúng lá đang xem, không phải nhánh mới"
    u2 = await _read_message(session_factory, uuid.UUID(next_resp.json()["user_message_id"]))
    assert u2.parent_id == a1


async def test_active_leaf_id_from_other_conversation_is_404(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """Trỏ con trỏ nhánh sang cây khác ⇒ `get_path` lẫn hai hội thoại (C11)."""
    first = await _create_conversation(session_factory, user_a)
    second = await _create_conversation(session_factory, user_a)
    _, a1 = await _one_turn(client, session_factory, first.id, user_a, "a")

    resp = await client.patch(
        CONVERSATION.format(second.id), headers=_session(user_a), json={"active_leaf_id": str(a1)}
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "LEAF_NOT_FOUND"
    assert await _active_leaf(session_factory, second.id) is None


# ───────── B-109 / NQ-35 ngả (a) — con trỏ đi tiếp xuống lá sâu nhất ────────


async def test_back_to_old_question_does_not_truncate_screen(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """**B-109** — trỏ vào một node CÓ CON ⇒ con trỏ đi tiếp xuống hết nhánh.

    Đây là ca mà T-3.8 sinh ra hằng ngày: sửa `u2` ở giữa hội thoại rồi bấm
    `‹` để xem lại câu hỏi cũ. FE gửi đúng id của anh em được chọn (`u2`, C13
    cấm nó tự đoán id khác), và `u2` còn cả `a2` phía dưới. Trước ngả (a),
    đường đi dừng ở `u2` và câu trả lời cũ biến khỏi màn hình dù vẫn nằm
    nguyên trong DB — mất hẳn một nửa của UC-04 dòng 1 (*"không xoá nhánh
    cũ"*) ngay trên màn hình.
    """
    conversation = await _create_conversation(session_factory, user_a)
    u1, a1 = await _one_turn(client, session_factory, conversation.id, user_a, "cau hoi 1")
    u2, a2 = await _one_turn(client, session_factory, conversation.id, user_a, "cau hoi 2")
    await client.patch(
        EDIT_MESSAGE.format(u2), headers=_session(user_a), json={"content": "khac han"}
    )

    back_to_old = await client.patch(
        CONVERSATION.format(conversation.id),
        headers=_session(user_a),
        json={"active_leaf_id": str(u2)},
    )

    assert back_to_old.status_code == 200, back_to_old.text
    # Con trỏ KHÔNG dừng ở `u2`: nó đi tiếp xuống `a2`.
    assert uuid.UUID(back_to_old.json()["active_leaf_id"]) == a2
    assert await _active_leaf(session_factory, conversation.id) == a2
    assert [uuid.UUID(m["id"]) for m in back_to_old.json()["path"]] == [u1, a1, u2, a2]
    # Và `‹ n/m ›` của câu hỏi cũ vẫn do SQL tính (C13).
    assert back_to_old.json()["path"][2]["sibling_index"] == 0
    assert back_to_old.json()["path"][2]["sibling_count"] == 2


async def test_pointing_at_a_leaf_changes_nothing(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """Ngả (a) là KHÔNG-OP cho mọi lần chuyển nhánh giữa các anh em lá (Retry).

    Phép kiểm ngược của test trên: nếu `get_deepest_leaf` đi lạc sang nhánh
    khác thì ca này đỏ, và nó là ca thường gặp nhất của `‹ n/m ›`.
    """
    conversation = await _create_conversation(session_factory, user_a)
    u1, a1 = await _one_turn(client, session_factory, conversation.id, user_a, "a")
    await client.post(RETRY.format(a1), headers=_session(user_a))

    resp = await client.patch(
        CONVERSATION.format(conversation.id),
        headers=_session(user_a),
        json={"active_leaf_id": str(a1)},
    )

    assert uuid.UUID(resp.json()["active_leaf_id"]) == a1
    assert [uuid.UUID(m["id"]) for m in resp.json()["path"]] == [u1, a1]


async def test_tie_on_DEPTH_created_at_decides_not_id(
    session_factory: async_sessionmaker[AsyncSession],
    client: AsyncClient,
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """Hoà `depth` ⇒ `created_at DESC` phân xử — đúng chữ "mới nhất" của B-109.

    Hai anh em cùng sâu 1, và anh em **mới hơn** được cố ý cho `id` NHỎ hơn.
    Nhờ thế ca này đỏ nếu ai đó rút `created_at` khỏi khoá sắp và để `id DESC`
    gánh một mình — mà với UUID ngẫu nhiên thì một bộ test không dựng tay sẽ
    đúng 50% số lần chạy, tức không bắt được gì.
    """
    conversation = await _create_conversation(session_factory, user_a)
    u1 = await _insert_message(session_factory, conversation.id, None, MessageRole.USER, 0)
    old = await _insert_message(
        session_factory, conversation.id, u1, MessageRole.ASSISTANT, 1, id=_BIG_ID
    )
    new_id = await _insert_message(
        session_factory, conversation.id, u1, MessageRole.ASSISTANT, 2, id=_SMALL_ID
    )

    async with session_factory() as session:
        leaf = await MessageRepository(session).get_deepest_leaf(u1, user_id=user_a)

    assert leaf == new_id, "phải là anh em sinh SAU, dù `id` của nó nhỏ hơn"
    assert leaf != old


async def test_tie_on_created_at_TOO_id_keeps_result_deterministic(
    session_factory: async_sessionmaker[AsyncSession],
    client: AsyncClient,
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """Khoá thứ ba — hai anh em TRÙNG `created_at` vẫn phải ra một kết quả.

    NQ-18 đã ghi ca này cho `get_siblings`: `clock_timestamp()` chỉ phân giải
    tới micro-giây nên script seed ghi hàng loạt vẫn tạo ra giá trị trùng. Ở
    đây chốt chiều `id DESC`, và khẳng định ngược chiều với ca trên: rút
    `created_at` đi thì ca trên đỏ, đổi `id DESC` thành `id ASC` thì ca này đỏ.
    """
    conversation = await _create_conversation(session_factory, user_a)
    u1 = await _insert_message(session_factory, conversation.id, None, MessageRole.USER, 0)
    small = await _insert_message(
        session_factory, conversation.id, u1, MessageRole.ASSISTANT, 1, id=_SMALL_ID
    )
    big = await _insert_message(
        session_factory, conversation.id, u1, MessageRole.ASSISTANT, 1, id=_BIG_ID
    )

    async with session_factory() as session:
        repo = MessageRepository(session)
        first_call = await repo.get_deepest_leaf(u1, user_id=user_a)
        second_call = await repo.get_deepest_leaf(u1, user_id=user_a)

    assert first_call == big and second_call == big, "trùng `created_at` ⇒ `id` lớn hơn, và ổn định"
    assert first_call != small


async def test_LONGER_branch_beats_newer_branch(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """`depth` là khoá ĐẦU, `created_at` chỉ phân xử khi hoà.

    Cây: `u1 → a1 → u2 → a2` (nhánh cũ, sâu 3) và `a1b` — một lần retry `a1`
    chạy SAU cùng, nên nó là node mới nhất của cả hội thoại mà chỉ sâu 1. Trỏ
    con trỏ vào `u1` phải ra `a2`, không phải `a1b`. Thứ tự dựng cây là cố ý:
    dựng ngược lại thì node sâu nhất cũng là node mới nhất và ca này không còn
    phân biệt được hai khoá.
    """
    conversation = await _create_conversation(session_factory, user_a)
    u1, a1 = await _one_turn(client, session_factory, conversation.id, user_a, "a")
    u2, a2 = await _one_turn(client, session_factory, conversation.id, user_a, "b")
    retry = await client.post(RETRY.format(a1), headers=_session(user_a))
    a1b = uuid.UUID(retry.json()["assistant_message_id"])

    resp = await client.patch(
        CONVERSATION.format(conversation.id),
        headers=_session(user_a),
        json={"active_leaf_id": str(u1)},
    )

    assert uuid.UUID(resp.json()["active_leaf_id"]) == a2
    assert uuid.UUID(resp.json()["active_leaf_id"]) != a1b
    assert [uuid.UUID(m["id"]) for m in resp.json()["path"]] == [u1, a1, u2, a2]


async def test_walking_down_does_NOT_skip_soft_deleted_message(
    session_factory: async_sessionmaker[AsyncSession],
    client: AsyncClient,
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """C12 — `deleted_at IS NULL` ở CẢ HAI nhánh của CTE xuôi.

    Xoá mềm `u2` ⇒ nhánh bị cắt tại đó, nên lá sâu nhất dưới `a1` là chính
    `a1`. Thiếu điều kiện ở nhánh đệ quy thì con trỏ đậu xuống `a2` — một
    message nằm **dưới** một message đã xoá, tức `get_path` sẽ trả về một
    đường đi rỗng và màn hình trắng.
    """
    conversation = await _create_conversation(session_factory, user_a)
    _, a1 = await _one_turn(client, session_factory, conversation.id, user_a, "a")
    u2, _ = await _one_turn(client, session_factory, conversation.id, user_a, "b")
    async with session_factory() as session:
        await session.execute(
            Message.__table__.update().where(Message.id == u2).values(deleted_at=func.now())
        )
        await session.commit()

    async with session_factory() as session:
        leaf = await MessageRepository(session).get_deepest_leaf(a1, user_id=user_a)

    assert leaf == a1


async def test_get_deepest_leaf_of_other_user_returns_None(
    session_factory: async_sessionmaker[AsyncSession],
    client: AsyncClient,
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """§20 — quyền sở hữu kiểm TRONG SQL; `None` để handler giữ nguyên 404.

    Ca này là lý do `_is_deepest` trả lại id gốc thay vì ném: đường báo lỗi
    vẫn là `LEAF_NOT_FOUND` của `set_active_leaf`, đúng một chỗ.
    """
    conversation = await _create_conversation(session_factory, user_a)
    _, a1 = await _one_turn(client, session_factory, conversation.id, user_a, "a")

    async with session_factory() as session:
        leaf = await MessageRepository(session).get_deepest_leaf(a1, user_id=user_b)

    assert leaf is None


async def test_change_title_model_and_pin(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """Ba trường còn lại của §18.2, và `null` tường minh xoá được tiêu đề."""
    others = _non_default_model()
    conversation = await _create_conversation(session_factory, user_a, title="ten cu")

    set_resp = await client.patch(
        CONVERSATION.format(conversation.id),
        headers=_session(user_a),
        json={"title": "ten moi", "default_model": others, "pinned": True},
    )
    assert set_resp.status_code == 200, set_resp.text
    assert set_resp.json()["title"] == "ten moi"
    assert set_resp.json()["default_model"] == others
    assert set_resp.json()["pinned"] is True

    deleted_resp = await client.patch(
        CONVERSATION.format(conversation.id), headers=_session(user_a), json={"title": None}
    )
    assert deleted_resp.json()["title"] is None
    assert deleted_resp.json()["default_model"] == others, "trường không gửi thì không bị đụng"
    assert deleted_resp.json()["pinned"] is True


async def test_pinned_null_is_400(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """Cột `NOT NULL` ⇒ `null` không có nghĩa, và bỏ qua im lặng là tệ hơn."""
    conversation = await _create_conversation(session_factory, user_a)

    resp = await client.patch(
        CONVERSATION.format(conversation.id), headers=_session(user_a), json={"pinned": None}
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "BAD_REQUEST"


async def test_default_model_not_in_catalog_is_400(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    conversation = await _create_conversation(session_factory, user_a, title="giu nguyen")

    resp = await client.patch(
        CONVERSATION.format(conversation.id),
        headers=_session(user_a),
        json={"title": "doi luon", "default_model": "khong-ton-tai"},
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "MODEL_UNKNOWN"
    # Kiểm TRƯỚC khi ghi: `title` trong cùng request cũng không được áp.
    read_resp = await client.get(CONVERSATION.format(conversation.id), headers=_session(user_a))
    assert read_resp.json()["title"] == "giu nguyen"


async def test_patch_other_users_conversation_is_404(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    conversation = await _create_conversation(session_factory, user_a, title="cua a")

    resp = await client.patch(
        CONVERSATION.format(conversation.id), headers=_session(user_b), json={"title": "cua b"}
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"
    async with session_factory() as session:
        child = await ConversationRepository(session).get_conversation(
            conversation.id, user_id=user_a
        )
    assert child is not None
    assert child.title == "cua a"


async def test_patch_empty_body_changes_nothing(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """`{}` hợp lệ: trả về trạng thái hiện tại, đúng như `GET`."""
    conversation = await _create_conversation(session_factory, user_a, title="ten")
    _, a1 = await _one_turn(client, session_factory, conversation.id, user_a, "a")

    resp = await client.patch(
        CONVERSATION.format(conversation.id), headers=_session(user_a), json={}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["title"] == "ten"
    assert uuid.UUID(resp.json()["active_leaf_id"]) == a1
    assert len(resp.json()["path"]) == 2


# ═════════════ GET /messages/{id}/siblings — dữ liệu cho ‹ n/m › ══════════


async def test_siblings_include_itself_and_sort_deterministically(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """`sibling_index` 0-based (B-60) và khớp vị trí trong danh sách đã sắp.

    Hỏi từ **mỗi** anh em một lần: `sibling_index` phải đổi theo người hỏi,
    còn `items` và `sibling_count` thì không.
    """
    conversation = await _create_conversation(session_factory, user_a)
    _, a1 = await _one_turn(client, session_factory, conversation.id, user_a, "a")
    first = await client.post(RETRY.format(a1), headers=_session(user_a))
    a1b = uuid.UUID(first.json()["assistant_message_id"])
    second = await client.post(RETRY.format(a1), headers=_session(user_a))
    a1c = uuid.UUID(second.json()["assistant_message_id"])

    for index, mid in enumerate([a1, a1b, a1c]):
        resp = await client.get(SIBLINGS.format(mid), headers=_session(user_a))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert uuid.UUID(body["message_id"]) == mid
        assert body["sibling_index"] == index
        assert body["sibling_count"] == 3
        assert [uuid.UUID(m["id"]) for m in body["items"]] == [a1, a1b, a1c]
        assert [m["sibling_index"] for m in body["items"]] == [0, 1, 2]
        assert {m["sibling_count"] for m in body["items"]} == {3}


async def test_siblings_without_siblings_still_returns_one(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """`sibling_count == 1`, không phải 0 — cùng quy ước với `_sibling_stats`.

    Lệch quy ước ở đây là C13 ở dạng khó tìm nhất: `‹ 1/0 ›` trên màn hình.
    """
    conversation = await _create_conversation(session_factory, user_a)
    _, a1 = await _one_turn(client, session_factory, conversation.id, user_a, "a")

    resp = await client.get(SIBLINGS.format(a1), headers=_session(user_a))

    assert resp.json()["sibling_count"] == 1
    assert resp.json()["sibling_index"] == 0
    assert len(resp.json()["items"]) == 1


async def test_siblings_do_not_leak_operational_columns(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """`raw_response`, `tool_calls`, `heartbeat_at`, `prompt_tokens` không ra dây."""
    conversation = await _create_conversation(session_factory, user_a)
    _, a1 = await _one_turn(client, session_factory, conversation.id, user_a, "a")

    resp = await client.get(SIBLINGS.format(a1), headers=_session(user_a))

    forbidden = {"raw_response", "tool_calls", "heartbeat_at", "prompt_tokens", "completion_tokens"}
    assert set(resp.json()["items"][0]) & forbidden == set()


async def test_siblings_of_other_user_is_404(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    conversation = await _create_conversation(session_factory, user_a)
    _, a1 = await _one_turn(client, session_factory, conversation.id, user_a, "a")

    resp = await client.get(SIBLINGS.format(a1), headers=_session(user_b))

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "MESSAGE_NOT_FOUND"


async def test_siblings_missing_message_is_404(
    client: AsyncClient,
    user_a: uuid.UUID,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    resp = await client.get(SIBLINGS.format(uuid.uuid4()), headers=_session(user_a))

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "MESSAGE_NOT_FOUND"


async def test_no_session_all_four_endpoints_401(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """`DEBUG=true` không còn mua được gì — T-3.1c.

    Ca cũ bật `DEBUG=false` rồi đòi `503`: đó là phép đo của nhánh danh tính
    tạm Phase 1, thứ T-3.1c đã xoá. Bản đảo của nó bật `DEBUG` LÊN rồi đòi
    `401` — bốn endpoint này đi qua đúng một cửa (`get_current_user_id`), và
    cửa ấy không còn đường vòng nào.
    """
    monkeypatch.setattr(settings, "DEBUG", True)
    mid = uuid.uuid4()

    for call in (
        client.post(RETRY.format(mid)),
        client.patch(EDIT_MESSAGE.format(mid), json={"content": "x"}),
        client.get(SIBLINGS.format(mid)),
        client.patch(CONVERSATION.format(mid), json={"pinned": True}),
    ):
        resp = await call
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "UNAUTHENTICATED"
