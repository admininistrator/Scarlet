"""T-2.9 — §10.6 gắn vào đâu trong `api/v1` (hai lớp theo user).

Tên file là `..._routes` chứ không trùng `tests/core/test_ratelimit.py`: `tests/`
không có `__init__.py`, nên hai file cùng basename là một lỗi collect của pytest
("import file mismatch") — đo được ngay khi thử.

`tests/core/test_ratelimit.py` kiểm *cơ chế*; file này kiểm *chỗ gắn*, và đó
là hai kiểu hỏng khác nhau. Một token bucket đúng từng con số mà quên gắn vào
`retry` thì hạn mức 20/phút chỉ là 20/phút cho một trong ba đường tốn tiền —
và không phép kiểm nào ở tầng `core/` thấy được điều đó.

Ba câu file này trả lời:

1. **Ba route SINH CHỮ** (`POST .../messages`, `retry`, `PATCH /messages/{id}`)
   đi qua token bucket; `cancel`/`siblings`/`stream` thì **không** (chúng không
   tốn tiền, và chặn `cancel` nghĩa là một lượt sinh đang chảy không ai dừng
   được nữa — cùng lý lẽ `require_chat_access` của T-2.7).
2. **`GET /messages/{id}/stream` không đếm ghế** — NQ-49, chỗ dễ đọc nhầm nhất
   của B-85.
3. Bị chặn ở **cả hai** lớp đều để lại **0 hàng** trong `messages` và **0** job
   trong hàng đợi: phép kiểm nằm trong transaction, nên ném là rollback.

`ratelimit_redis` (autouse, `tests/api/conftest.py`) mặc định trả lời "cho
qua"; mỗi test ở đây tự đặt kịch bản của mình.
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

from app.config import catalog
from app.config.settings import settings
from app.core import ratelimit
from app.core.access_token import encode_access_token
from app.core.crypto import mask_secret, seal
from app.core.deps import SESSION_COOKIE_NAME
from app.core.errors import ApiErrorCode
from app.db.models import Conversation, Message, MessageRole, MessageStatus, UserRole, UserStatus
from app.db.repositories import ConversationRepository, MessageRepository, ProviderKeyRepository
from app.main import app

#: Kiểu thật là `FakeRateLimitRedis` của `tests/api/conftest.py`, nhưng `tests/`
#: không phải package nên `from tests.api.conftest import …` không chạy (cùng
#: lý do fixture `event_hooks` tồn tại thay cho một hằng import được).
FakeRateLimitRedis = Any

CREATE_PATH = "/api/v1/conversations/{}/messages"
RETRY_PATH = "/api/v1/messages/{}/retry"
EDIT_PATH = "/api/v1/messages/{}"
CANCEL_PATH = "/api/v1/messages/{}/cancel"
SIBLINGS_PATH = "/api/v1/messages/{}/siblings"
STREAM_PATH = "/api/v1/messages/{}/stream"

#: `[allowed, remaining, retry_after_ms, reset_ms]` — xô đã cạn.
EMPTY_BUCKET = [0, 0, 3000, 60000]
#: `[cho_phep, dang_chay]` — đã đủ ghế.
NO_SEATS = [0, settings.MAX_CONCURRENT_STREAMS]


class _RedisWithCancel:
    """Chỉ đúng một lệnh mà `POST /messages/{id}/cancel` dùng (§7.5)."""

    async def set(self, name: str, value: str, *, ex: int | None = None) -> bool:
        return True


class _FakeArq:
    def __init__(self) -> None:
        self.pushed: list[tuple[str, tuple[Any, ...]]] = []
        self.raises = False

    async def enqueue_job(self, name: str, *args: Any, **_: Any) -> object:
        if self.raises:
            raise ConnectionError("redis chet giua chung (gia lap)")
        self.pushed.append((name, args))
        return object()


@pytest.fixture
def _db_for_tests(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


@pytest_asyncio.fixture
async def fake_arq(monkeypatch: pytest.MonkeyPatch) -> _FakeArq:
    fake = _FakeArq()

    async def _pool() -> _FakeArq:
        return fake

    monkeypatch.setattr("app.api.v1.messages.get_arq_pool", _pool)
    return fake


@pytest_asyncio.fixture
async def client(event_hooks: dict[str, Any]) -> AsyncIterator[AsyncClient]:
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


async def _conversation_with_generation(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> tuple[Conversation, Message, Message]:
    """Một hội thoại với một câu hỏi và một câu trả lời đã `completed`."""
    async with session_factory() as session:
        conversations = ConversationRepository(session)
        messages = MessageRepository(session)
        conversation = await conversations.create_conversation(user_id=user_id)
        question = await messages.create_message(
            conversation_id=conversation.id,
            user_id=user_id,
            role=MessageRole.USER,
            content="viet ham sort",
        )
        answer = await messages.create_message(
            conversation_id=conversation.id,
            user_id=user_id,
            role=MessageRole.ASSISTANT,
            parent_id=question.id,
            status=MessageStatus.COMPLETED,
            content="xong",
        )
        await session.commit()
        return conversation, question, answer


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


def _scripts(redis: FakeRateLimitRedis) -> list[str]:
    return [name for name, _ in redis.calls]


# ═════════════ ba route sinh chữ đi qua token bucket, ba route kia thì không ═


@pytest.mark.usefixtures("_db_for_tests", "fake_arq")
async def test_create_message_blocked_by_token_bucket(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    ratelimit_redis: FakeRateLimitRedis,
    fake_arq: _FakeArq,
) -> None:
    """DoD dòng 1, nhìn từ tầng route: hết token ⇒ `429` + `Retry-After`."""
    conversation, _, _ = await _conversation_with_generation(session_factory, user_a)
    before = await _count_messages(session_factory, conversation.id)
    ratelimit_redis.bucket = EMPTY_BUCKET

    resp = await client.post(
        CREATE_PATH.format(conversation.id),
        headers=_session(user_a),
        json={"content": "xin chao"},
    )

    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == ApiErrorCode.RATE_LIMITED
    assert resp.headers["retry-after"] == "3"
    assert await _count_messages(session_factory, conversation.id) == before
    assert fake_arq.pushed == []


@pytest.mark.usefixtures("_db_for_tests", "fake_arq")
async def test_retry_blocked_by_token_bucket(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    ratelimit_redis: FakeRateLimitRedis,
) -> None:
    _, _, answer = await _conversation_with_generation(session_factory, user_a)
    ratelimit_redis.bucket = EMPTY_BUCKET

    resp = await client.post(RETRY_PATH.format(answer.id), headers=_session(user_a))

    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == ApiErrorCode.RATE_LIMITED


@pytest.mark.usefixtures("_db_for_tests", "fake_arq")
async def test_edit_question_blocked_by_token_bucket(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    ratelimit_redis: FakeRateLimitRedis,
) -> None:
    _, question, _ = await _conversation_with_generation(session_factory, user_a)
    ratelimit_redis.bucket = EMPTY_BUCKET

    resp = await client.patch(
        EDIT_PATH.format(question.id),
        headers=_session(user_a),
        json={"content": "hoi lai"},
    )

    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == ApiErrorCode.RATE_LIMITED


@pytest.mark.usefixtures("_db_for_tests")
async def test_cancel_passes_through_no_limit(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    ratelimit_redis: FakeRateLimitRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chặn nút Dừng nghĩa là một lượt sinh đang chảy không ai dừng được nữa —
    và nó cũng không tốn đồng nào (cùng lý lẽ T-2.7 không gắn
    `require_chat_access` cho `cancel`)."""
    _, _, answer = await _conversation_with_generation(session_factory, user_a)
    ratelimit_redis.bucket = EMPTY_BUCKET
    ratelimit_redis.slot = NO_SEATS
    # Cờ huỷ `cancel:{id}` đi qua một Redis KHÁC (`app.api.v1.messages.get_redis`)
    # — giữ hai đường riêng để phép đếm script bên dưới không lẫn.
    monkeypatch.setattr("app.api.v1.messages.get_redis", lambda: _RedisWithCancel())

    resp = await client.post(CANCEL_PATH.format(answer.id), headers=_session(user_a))

    assert resp.status_code == 200
    assert _scripts(ratelimit_redis) == []


@pytest.mark.usefixtures("_db_for_tests")
async def test_siblings_pass_through_no_limit(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    ratelimit_redis: FakeRateLimitRedis,
) -> None:
    _, _, answer = await _conversation_with_generation(session_factory, user_a)
    ratelimit_redis.bucket = EMPTY_BUCKET

    resp = await client.get(SIBLINGS_PATH.format(answer.id), headers=_session(user_a))

    assert resp.status_code == 200
    assert _scripts(ratelimit_redis) == []


@pytest.mark.usefixtures("_db_for_tests")
async def test_stream_counts_no_seat_and_costs_no_token(
    client: AsyncClient,
    user_a: uuid.UUID,
    ratelimit_redis: FakeRateLimitRedis,
) -> None:
    """NQ-49 — chỗ dễ đọc nhầm nhất của B-85.

    Đếm kết nối SSE sẽ chặn tab thứ tư của cùng một hội thoại, tức chặn đúng
    thứ ADR-01 (không consumer group, hai tab cùng đọc được) và UC-03 (F5 giữa
    lúc đang stream) dựng ra. Trần của §10.6 đếm **lượt sinh**, không đếm tab.

    Dùng một `message_id` không tồn tại: `404` xảy ra trước khi có byte nào của
    stream, nên test không phải dựng Redis Stream — mà `404` vẫn chứng minh
    điều cần chứng minh, vì hạn mức là *dependency*, chạy trước handler.
    """
    resp = await client.get(STREAM_PATH.format(uuid.uuid4()), headers=_session(user_a))

    assert resp.status_code == 404
    assert _scripts(ratelimit_redis) == [], "không xô, không ghế"


# ═══════════════════ trần đồng thời (§10.6 hàng 4, B-85, NQ-49) ═════════════


@pytest.mark.usefixtures("_db_for_tests")
async def test_no_seats_429_TOO_MANY_STREAMS_and_writes_no_row(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    ratelimit_redis: FakeRateLimitRedis,
    fake_arq: _FakeArq,
) -> None:
    """DoD dòng 3. Và phần quan trọng hơn con số `429`: phép kiểm nằm **trong**
    transaction, nên một lượt bị từ chối không để lại message mồ côi nào."""
    conversation, _, _ = await _conversation_with_generation(session_factory, user_a)
    before = await _count_messages(session_factory, conversation.id)
    ratelimit_redis.slot = NO_SEATS

    resp = await client.post(
        CREATE_PATH.format(conversation.id),
        headers=_session(user_a),
        json={"content": "cau hoi thu tu"},
    )

    assert resp.status_code == 429
    error = resp.json()["error"]
    assert error["code"] == ApiErrorCode.TOO_MANY_STREAMS
    assert error["details"] == {
        "limit": settings.MAX_CONCURRENT_STREAMS,
        "active": settings.MAX_CONCURRENT_STREAMS,
    }
    assert "retry-after" not in resp.headers, "không ai biết model sinh xong lúc nào"
    assert await _count_messages(session_factory, conversation.id) == before
    assert fake_arq.pushed == []


@pytest.mark.usefixtures("_db_for_tests")
async def test_seat_held_BEFORE_enqueue(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    ratelimit_redis: FakeRateLimitRedis,
    fake_arq: _FakeArq,
) -> None:
    """Thứ tự là hợp đồng: giữ ghế xong mới đẩy job. Đảo lại thì một lượt bị
    từ chối vẫn có job trong hàng đợi, và worker vẫn sinh chữ, vẫn tính tiền."""
    conversation, _, _ = await _conversation_with_generation(session_factory, user_a)
    ratelimit_redis.slot = NO_SEATS

    await client.post(
        CREATE_PATH.format(conversation.id),
        headers=_session(user_a),
        json={"content": "xin chao"},
    )

    assert "slot" in _scripts(ratelimit_redis)
    assert fake_arq.pushed == []


@pytest.mark.usefixtures("_db_for_tests")
async def test_failed_enqueue_RELEASES_seat_immediately(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    ratelimit_redis: FakeRateLimitRedis,
    fake_arq: _FakeArq,
) -> None:
    """Transaction sắp rollback ⇒ hàng `messages` mang id đó sẽ không tồn tại.

    Không nhả ngay thì đó là một ghế trỏ vào hư không, và phép đối chiếu
    Postgres phải đợi hết `PHANTOM_GRACE_S` mới dọn được — 60 giây trong đó
    người dùng mất một phần ba hạn mức của mình vì một sự cố của Redis.
    """
    conversation, _, _ = await _conversation_with_generation(session_factory, user_a)
    fake_arq.raises = True

    resp = await client.post(
        CREATE_PATH.format(conversation.id),
        headers=_session(user_a),
        json={"content": "xin chao"},
    )

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == ApiErrorCode.ENQUEUE_FAILED
    assert len(ratelimit_redis.released) == 1
    key, _ = ratelimit_redis.released[0]
    assert key == ratelimit.stream_slot_key(user_a)


@pytest.mark.usefixtures("_db_for_tests", "fake_arq")
async def test_happy_path_has_all_three_ratelimit_headers(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    ratelimit_redis: FakeRateLimitRedis,
) -> None:
    """§10.6 đòi `X-RateLimit-*` chứ không chỉ `Retry-After`: FE cần biết mình
    sắp hết hạn mức TRƯỚC khi hết."""
    conversation, _, _ = await _conversation_with_generation(session_factory, user_a)
    ratelimit_redis.bucket = [1, 17, 0, 9000]

    resp = await client.post(
        CREATE_PATH.format(conversation.id),
        headers=_session(user_a),
        json={"content": "xin chao"},
    )

    assert resp.status_code == 202
    assert resp.headers[ratelimit.HEADER_LIMIT] == str(settings.RATE_LIMIT_CHAT_PER_MIN)
    assert resp.headers[ratelimit.HEADER_REMAINING] == "17"
    assert resp.headers[ratelimit.HEADER_RESET] == "9"
    assert ratelimit.HEADER_RETRY_AFTER not in resp.headers


@pytest.mark.usefixtures("_db_for_tests", "fake_arq")
async def test_seat_granted_to_the_just_created_assistant_message(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    ratelimit_redis: FakeRateLimitRedis,
) -> None:
    """Member của ZSET phải là `assistant_message_id` — đó là thứ duy nhất
    Postgres trả lời được câu "còn đang sinh không". Cấp ghế cho một token
    ngẫu nhiên thì phép đối chiếu mất luôn điểm tựa."""
    conversation, _, _ = await _conversation_with_generation(session_factory, user_a)

    resp = await client.post(
        CREATE_PATH.format(conversation.id),
        headers=_session(user_a),
        json={"content": "xin chao"},
    )

    assert resp.status_code == 202
    name, argv = next(call for call in ratelimit_redis.calls if call[0] == "slot")
    assert name == "slot"
    assert argv[0] == ratelimit.stream_slot_key(user_a)
    assert argv[4] == resp.json()["assistant_message_id"]


# ═══════ BYOK không mua được quyền miễn rate limit (§10.5, T-2.15) ═══════


@pytest.mark.usefixtures("_db_for_tests", "fake_arq")
async def test_byok_still_blocked_by_token_bucket(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    ratelimit_redis: FakeRateLimitRedis,
    fake_arq: _FakeArq,
) -> None:
    """**DoD dòng 4 của T-2.15.** §10.5 hàng "Rate limit": *"Vẫn áp dụng"*.

    Quota giới hạn **tiền của người vận hành**, rate limit giới hạn **tần
    suất** (§10.6) — hai thứ khác nhau, và BYOK chỉ mua được miễn thứ nhất.
    Người dùng BYOK vẫn dùng worker, vẫn chiếm kết nối Postgres/Redis, vẫn
    gửi được 1000 request/phút nếu không ai chặn.

    Lớp chặn là một **dependency** của route (`_GENERATION_ROUTE`), tức nó chạy
    xong trước khi handler biết BYOK tồn tại — nên tính chất này giữ được
    "miễn phí". Test canh đúng chiều đó: chuyển nó thành một phép kiểm bên
    trong `_open_generation` là mở đường cho một nhánh `if byok: bo_qua`.
    """
    conversation, _, _ = await _conversation_with_generation(session_factory, user_a)
    model = catalog.get_default_model()
    assert model is not None
    key = "sk-" + "0123456789abcdef" * 2
    async with session_factory() as session:
        await ProviderKeyRepository(session).upsert(
            user_id=user_a,
            provider=model.provider,
            sealed=seal(key),
            masked=mask_secret(key),
            verified_at=None,
        )
        await session.commit()
    before = await _count_messages(session_factory, conversation.id)
    ratelimit_redis.bucket = EMPTY_BUCKET

    resp = await client.post(
        CREATE_PATH.format(conversation.id),
        headers=_session(user_a),
        json={"content": "xin chao"},
    )

    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == ApiErrorCode.RATE_LIMITED
    assert resp.headers["retry-after"] == "3"
    assert await _count_messages(session_factory, conversation.id) == before
    assert fake_arq.pushed == []
