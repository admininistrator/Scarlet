"""T-6.7a — cờ `web_tools` ở ba route sinh chữ (Q-P6-3) + tóm tắt tool trên đường đi.

KH tham chiếu: §18.2, §9.4, C18, S9 (lối T-4.5) · NQ-144 (Q-P6-1, Q-P6-3).

`true` + model thiếu `tools` ⇒ `422 MODEL_NO_TOOLS` ở **cả ba** đường, không ghi
hàng nào. Đường đi mang `tools: [{name, ok, reason, sources}]` đọc bằng MỘT câu,
và câu của `get_path` không kéo `tool_rounds` (chữ trang) về.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from app.config import catalog
from app.core.access_token import encode_access_token
from app.core.deps import SESSION_COOKIE_NAME
from app.db.models import Message, MessageRole, MessageStatus, User, UserRole, UserStatus
from app.db.repositories import ConversationRepository, MessageRepository
from app.main import app
from app.quota.tiers import tier_cache_key

API = "/api/v1"
NO_TOOLS = "MODEL_NO_TOOLS"
PAGE_TEXT = "chữ trang web rất dài KHÔNG được ra khỏi Postgres"


def _model(*, tools: bool) -> str:
    """Một model đang bật của catalog thật, có / không có `tools`."""
    return next(
        m.id
        for m in catalog.get_catalog().models
        if m.enabled and (catalog.TOOLS_CAPABILITY in m.capabilities) == tools
    )


class _FakeArq:
    def __init__(self) -> None:
        self.pushed: list[str] = []

    async def enqueue_job(self, name: str, *_: Any, **__: Any) -> object:
        self.pushed.append(name)
        return object()


@pytest.fixture(autouse=True)
def _db_for_tests(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


@pytest_asyncio.fixture(autouse=True)
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


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    token = encode_access_token(
        user_id=user_id, role=UserRole.USER, tier="free", status=UserStatus.ACTIVE, ttl_minutes=15
    )
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


def _round(*, ok: bool = True) -> list[dict[str, Any]]:
    """Một vòng `tool_rounds` như worker ghi (Q-P6-1)."""
    return [
        {
            "tool_calls": [
                {
                    "id": "c_1",
                    "type": "function",
                    "function": {"name": "fetch_url", "arguments": '{"url": "https://a.vn/"}'},
                }
            ],
            "reasoning": None,
            "finish_reason": "tool_calls",
            "results": [
                {
                    "tool_call_id": "c_1",
                    "name": "fetch_url",
                    "ok": ok,
                    "content": PAGE_TEXT if ok else "",
                    "sources": [{"url": "https://a.vn/", "title": "A"}] if ok else [],
                    "reason": None if ok else "blocked",
                }
            ],
        }
    ]


async def _turn(
    factory: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
    *,
    model_id: str,
    web_tools: bool = False,
    default_model: str | None = None,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Hội thoại một lượt đã xong. Trả `(conversation, câu hỏi, câu trả lời)`."""
    async with factory() as session:
        conv = await ConversationRepository(session).create_conversation(
            user_id=user_id, default_model=default_model
        )
        messages = MessageRepository(session)
        question = await messages.create_message(
            conversation_id=conv.id,
            user_id=user_id,
            role=MessageRole.USER,
            content="doc link nay",
            status=MessageStatus.COMPLETED,
        )
        answer = await messages.create_message(
            conversation_id=conv.id,
            user_id=user_id,
            role=MessageRole.ASSISTANT,
            parent_id=question.id,
            content="xong",
            status=MessageStatus.COMPLETED,
            model_id=model_id,
            web_tools=web_tools,
        )
        await ConversationRepository(session).set_active_leaf(
            conv.id, user_id=user_id, message_id=answer.id
        )
        await session.commit()
        return conv.id, question.id, answer.id


async def _count(factory: async_sessionmaker[AsyncSession]) -> int:
    async with factory() as session:
        return int((await session.execute(select(func.count()).select_from(Message))).scalar_one())


async def _web_tools_of(factory: async_sessionmaker[AsyncSession], mid: str) -> bool:
    async with factory() as session:
        stmt = select(Message.web_tools).where(Message.id == uuid.UUID(mid))
        return bool((await session.execute(stmt)).scalar_one())


def _assert_no_tools(resp: Any, model_id: str) -> None:
    assert resp.status_code == 422, resp.text
    error = resp.json()["error"]
    assert error["code"] == NO_TOOLS
    assert error["details"] == {"model_id": model_id}


# ═══════════════════════════ ba đường × model không `tools` ═══════════════════


async def test_post_web_tools_to_model_without_tools_is_422_writes_nothing(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_arq: _FakeArq,
) -> None:
    conv, _, _ = await _turn(session_factory, user_a, model_id=_model(tools=True))
    before = await _count(session_factory)
    no_tools = _model(tools=False)

    resp = await client.post(
        f"{API}/conversations/{conv}/messages",
        headers=_auth(user_a),
        json={"content": "doc https://a.vn", "model_id": no_tools, "web_tools": True},
    )

    _assert_no_tools(resp, no_tools)
    assert await _count(session_factory) == before
    assert fake_arq.pushed == []


async def test_retry_web_tools_to_model_without_tools_is_422_writes_nothing(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_arq: _FakeArq,
) -> None:
    no_tools = _model(tools=False)
    _, _, answer = await _turn(session_factory, user_a, model_id=no_tools)
    before = await _count(session_factory)

    resp = await client.post(
        f"{API}/messages/{answer}/retry", headers=_auth(user_a), json={"web_tools": True}
    )

    _assert_no_tools(resp, no_tools)
    assert await _count(session_factory) == before
    assert fake_arq.pushed == []


async def test_patch_web_tools_to_model_without_tools_is_422_writes_nothing(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_arq: _FakeArq,
) -> None:
    no_tools = _model(tools=False)
    _, question, _ = await _turn(session_factory, user_a, model_id=no_tools, default_model=no_tools)
    before = await _count(session_factory)

    resp = await client.patch(
        f"{API}/messages/{question}",
        headers=_auth(user_a),
        json={"content": "doc https://b.vn", "web_tools": True},
    )

    _assert_no_tools(resp, no_tools)
    assert await _count(session_factory) == before
    assert fake_arq.pushed == []


# ═══════════════════════════ cờ đi tới hàng `queued` ═══════════════════════════


async def test_post_flag_lands_on_queued_row_absent_means_false(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    conv, _, _ = await _turn(session_factory, user_a, model_id=_model(tools=True))
    url = f"{API}/conversations/{conv}/messages"
    model = _model(tools=True)

    on = await client.post(
        url, headers=_auth(user_a), json={"content": "a", "model_id": model, "web_tools": True}
    )
    off = await client.post(url, headers=_auth(user_a), json={"content": "b", "model_id": model})

    assert on.status_code == off.status_code == 202, (on.text, off.text)
    assert await _web_tools_of(session_factory, on.json()["assistant_message_id"]) is True
    assert await _web_tools_of(session_factory, off.json()["assistant_message_id"]) is False


async def test_retry_without_flag_inherits_column_and_drops_it_for_model_without_tools(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    """Lối `_pick_reasoning`: vắng ⇒ dùng lại cột; model mới không `tools` ⇒ bỏ, không `422`."""
    _, _, answer = await _turn(session_factory, user_a, model_id=_model(tools=True), web_tools=True)

    same = await client.post(f"{API}/messages/{answer}/retry", headers=_auth(user_a))
    other = await client.post(
        f"{API}/messages/{answer}/retry",
        headers=_auth(user_a),
        json={"model_id": _model(tools=False)},
    )

    assert same.status_code == other.status_code == 202, (same.text, other.text)
    assert await _web_tools_of(session_factory, same.json()["assistant_message_id"]) is True
    assert await _web_tools_of(session_factory, other.json()["assistant_message_id"]) is False


# ═══════════════════════════ đường đi: tóm tắt tool, không chữ trang ═══════════


async def _tool_path(
    factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID, turns: int, *, tools: bool
) -> uuid.UUID:
    """Đường đi `turns` lượt; `tools` ⇒ mỗi câu trả lời có một vòng tool."""
    async with factory() as session:
        conv = await ConversationRepository(session).create_conversation(user_id=user_id)
        messages = MessageRepository(session)
        parent: uuid.UUID | None = None
        for n in range(turns * 2):
            msg = await messages.create_message(
                conversation_id=conv.id,
                user_id=user_id,
                role=MessageRole.USER if n % 2 == 0 else MessageRole.ASSISTANT,
                parent_id=parent,
                content=f"m{n}",
                status=MessageStatus.COMPLETED,
            )
            parent = msg.id
            if tools and n % 2 == 1:
                await session.execute(
                    update(Message).where(Message.id == msg.id).values(tool_rounds=_round())
                )
        await ConversationRepository(session).set_active_leaf(
            conv.id, user_id=user_id, message_id=parent
        )
        await session.commit()
        return conv.id


async def _count_sql(
    client: AsyncClient, connection: AsyncConnection, path: str, auth: Any
) -> tuple[int, list[str], Any]:
    seen: list[str] = []

    def _on(_conn: Any, _cur: Any, statement: str, *_: Any) -> None:
        seen.append(statement)

    event.listen(connection.sync_engine, "before_cursor_execute", _on)
    try:
        resp = await client.get(path, headers=auth)
    finally:
        event.remove(connection.sync_engine, "before_cursor_execute", _on)
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["path"]) == 20
    return len(seen), seen, resp.json()


async def test_path_of_20_with_tools_same_query_count_and_no_tool_rounds_column(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
    user_a: uuid.UUID,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """T-3.7a ① / B-244: `tool_rounds` deferred — `get_path` không kéo; tóm tắt một câu."""
    with_tools = await _tool_path(session_factory, user_a, 10, tools=True)
    plain = await _tool_path(session_factory, user_a, 10, tools=False)
    auth = _auth(user_a)

    n_tools, sql, body = await _count_sql(
        client, connection, f"{API}/conversations/{with_tools}", auth
    )
    n_plain, _, _ = await _count_sql(client, connection, f"{API}/conversations/{plain}", auth)
    with capsys.disabled():
        print(f"\n[T-6.7a] SQL duong 20 msg: co tool = {n_tools}; khong tool = {n_plain}")

    assert n_tools == n_plain
    path_sql = next(s for s in sql if "WITH RECURSIVE path" in s)
    assert "tool_rounds" not in path_sql
    assert PAGE_TEXT not in str(body)
    answers = [m for m in body["path"] if m["role"] == "assistant"]
    assert all(
        m["tools"]
        == [
            {
                "name": "fetch_url",
                "ok": True,
                "reason": None,
                "sources": [{"url": "https://a.vn/", "title": "A"}],
            }
        ]
        for m in answers
    )
    assert all(m["tools"] == [] for m in body["path"] if m["role"] == "user")


async def test_siblings_carry_tool_summary_too(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    _, _, answer = await _turn(session_factory, user_a, model_id=_model(tools=True))
    async with session_factory() as session:
        await session.execute(
            update(Message).where(Message.id == answer).values(tool_rounds=_round(ok=False))
        )
        await session.commit()

    resp = await client.get(f"{API}/messages/{answer}/siblings", headers=_auth(user_a))

    assert resp.status_code == 200, resp.text
    (item,) = resp.json()["items"]
    assert item["tools"] == [{"name": "fetch_url", "ok": False, "reason": "blocked", "sources": []}]


# ═══════════════ T-6.8: `can_use_web` đọc lúc gọi (B-153) + `/auth/me` ═══════════════


async def _web_off(factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID) -> None:
    """Ghi đè TỪNG NGƯỜI (`limit_override_json`) — đọc thẳng `tiers` sẽ không thấy (B-153)."""
    async with factory() as session:
        await session.execute(
            update(User)
            .where(User.id == user_id)
            .values(limit_override_json={"can_use_web": False})
        )
        await session.commit()


@pytest.mark.parametrize("route", ["post", "retry", "patch"])
async def test_can_use_web_false_is_422_web_disabled_writes_nothing(
    route: str,
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_arq: _FakeArq,
) -> None:
    model = _model(tools=True)
    conv, question, answer = await _turn(
        session_factory, user_a, model_id=model, default_model=model
    )
    await _web_off(session_factory, user_a)
    before = await _count(session_factory)

    if route == "post":
        resp = await client.post(
            f"{API}/conversations/{conv}/messages",
            headers=_auth(user_a),
            json={"content": "tim web", "model_id": model, "web_tools": True},
        )
    elif route == "retry":
        resp = await client.post(
            f"{API}/messages/{answer}/retry", headers=_auth(user_a), json={"web_tools": True}
        )
    else:
        resp = await client.patch(
            f"{API}/messages/{question}",
            headers=_auth(user_a),
            json={"content": "tim web", "web_tools": True},
        )

    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "WEB_DISABLED"
    assert await _count(session_factory) == before
    assert fake_arq.pushed == []


async def test_retry_inherited_flag_is_dropped_when_web_disabled(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    """Cờ thừa kế (không ai ghi rõ) + web tắt ⇒ bỏ cờ, `202` — lối model không `tools`."""
    _, _, answer = await _turn(session_factory, user_a, model_id=_model(tools=True), web_tools=True)
    await _web_off(session_factory, user_a)

    resp = await client.post(f"{API}/messages/{answer}/retry", headers=_auth(user_a))

    assert resp.status_code == 202, resp.text
    assert await _web_tools_of(session_factory, resp.json()["assistant_message_id"]) is False


async def test_tier_change_applies_once_tier_cache_expires(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    quota_redis: Any,
) -> None:
    """NQ-51: đổi `tiers` ⇒ hiệu lực khi khoá `tier:limits:{uid}` (TTL `TIER_CACHE_TTL_S`) hết."""
    model = _model(tools=True)
    conv, _, _ = await _turn(session_factory, user_a, model_id=model)
    url = f"{API}/conversations/{conv}/messages"
    body = {"content": "tim web", "model_id": model, "web_tools": True}

    warm = await client.post(url, headers=_auth(user_a), json=body)
    async with session_factory() as session:
        await session.execute(text("UPDATE tiers SET can_use_web = false WHERE name = 'free'"))
        await session.commit()
    cached = await client.post(url, headers=_auth(user_a), json=body)
    del quota_redis.store[tier_cache_key(user_a)]  # TTL trôi qua
    expired = await client.post(url, headers=_auth(user_a), json=body)

    assert (warm.status_code, cached.status_code) == (202, 202), (warm.text, cached.text)
    assert expired.status_code == 422, expired.text
    assert expired.json()["error"]["code"] == "WEB_DISABLED"


async def test_me_returns_three_web_fields(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    quota_redis: Any,
) -> None:
    async with session_factory() as session:
        await session.execute(
            update(User)
            .where(User.id == user_a)
            .values(limit_override_json={"web_searches_per_day": 3})
        )
        await session.commit()
    now = time.time()
    # Một lượt trong 24 h, một lượt quá hạn (score tường minh — B-290).
    quota_redis.zset[f"web:{user_a}"] = {"trong": now - 60, "cu": now - 24 * 3600 - 1}

    resp = await client.get(f"{API}/auth/me", headers=_auth(user_a))

    assert resp.status_code == 200, resp.text
    me = resp.json()
    assert (me["can_use_web"], me["web_searches_per_day"], me["web_searches_used"]) == (
        True,
        3,
        1,
    )


async def test_me_can_execute_skills_follows_limit_override(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    quota_redis: Any,
) -> None:
    """T-7.8 (B-404 ②): quyền chạy code đã gộp ghi đè — `free` tắt, override bật."""
    before = (await client.get(f"{API}/auth/me", headers=_auth(user_a))).json()
    async with session_factory() as session:
        await session.execute(
            update(User)
            .where(User.id == user_a)
            .values(limit_override_json={"can_execute_skills": True})
        )
        await session.commit()
    del quota_redis.store[tier_cache_key(user_a)]
    after = (await client.get(f"{API}/auth/me", headers=_auth(user_a))).json()

    assert (before["can_execute_skills"], after["can_execute_skills"]) == (False, True)
