"""T-6.7a — vòng lặp tool ở worker (§7.2 ③ "lặp lại", §13.5), lượt tool trong MỘT message.

KH tham chiếu: §7.2, §7.4, §9.6, C15, C18, C19, C33, §10.2 · NQ-144 (Q-P6-1, Q-P6-6).

LLM giả phát `Chunk` dựng từ fixture THẬT của bước đo đầu task
(`tests/llm/fixtures/*.fetch_url*.jsonl`, qua `StreamParser` như production).
Giả ở MỘT chỗ nối mỗi đường: provider (`SeqClient`) và client `fetch_url` của
worker (`app.tools.registry.fetch_url`). Postgres, `context.build`, meter là thật.
"""

from __future__ import annotations

import json
import math
import time
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_generate import FakeRedis, _ctx, _read_ledger, _reload, _WireRecorder

from app.config.catalog import get_model
from app.config.settings import settings
from app.db.models import Conversation, Message, MessageRole, MessageStatus, User
from app.db.repositories import ConversationRepository, MessageRepository
from app.llm import context as llm_context
from app.llm.adapters import openai_compat
from app.llm.adapters.system import SystemAdapter
from app.llm.client import Chunk, ToolCall, Usage
from app.llm.parser import StreamParser
from app.llm.tokens import count_messages
from app.quota import web_searches
from app.quota.estimator import estimate
from app.tools import registry as registry_mod
from app.tools import web_search as web_search_mod
from app.tools.fetch_url import FetchResult
from app.tools.web_search import SearchHit, SearchResult
from app.workers.generate import generate

FIXTURES = Path(__file__).parents[1] / "llm" / "fixtures"
#: Model có `tools` trong catalog thật; fixture ghi từ chính nó.
TOOLS_MODEL = "nr-gemini-flash"
#: Model KHÔNG có `tools` (catalog thật).
NO_TOOLS_MODEL = "ol-qwen-small"
PAGE_URL = "https://httpbin.org/html"
PAGE_TEXT = "Herman Melville - Moby-Dick. Avast, me hearties..."


def _fixture(name: str) -> list[Chunk]:
    parser = StreamParser()
    out: list[Chunk] = []
    for line in (FIXTURES / name).read_text(encoding="utf-8").splitlines():
        out += parser.feed(json.loads(line))
    return out + parser.finish()


ROUND1 = _fixture(f"{TOOLS_MODEL}.fetch_url.jsonl")
ROUND2 = _fixture(f"{TOOLS_MODEL}.fetch_url_round2.jsonl")


def _calls_turn(*calls: ToolCall, prompt: int = 100) -> list[Chunk]:
    usage = Usage(prompt_tokens=prompt, completion_tokens=10, total_tokens=prompt + 10)
    return [
        *(Chunk(kind="tool_call", tool_call=c) for c in calls),
        Chunk(kind="usage", usage=usage),
        Chunk(kind="done", finish_reason="tool_calls", usage=usage),
    ]


def _fetch(call_id: str, url: str = PAGE_URL) -> ToolCall:
    return ToolCall(call_id=call_id, name="fetch_url", arguments=json.dumps({"url": url}))


class SeqClient:
    """`LLMClient` giả: mỗi lần `stream` phát dãy chunk kế tiếp; hết dãy ⇒ một câu chữ."""

    def __init__(self, *turns: list[Chunk]) -> None:
        self._turns = list(turns)
        self.calls: list[dict[str, Any]] = []

    async def stream(self, **kwargs: Any) -> AsyncIterator[Chunk]:
        # Bản chụp `messages` — dây còn lớn thêm sau lần gọi.
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        chunks = self._turns.pop(0) if self._turns else ROUND2
        return self._emit(chunks)

    async def _emit(self, chunks: list[Chunk]) -> AsyncIterator[Chunk]:
        for chunk in chunks:
            yield chunk


class FetchRecorder:
    def __init__(self) -> None:
        self.urls: list[str] = []
        self.text = PAGE_TEXT
        self.raises: BaseException | None = None
        self.on_call: Any = None

    async def __call__(self, url: str) -> FetchResult:
        self.urls.append(url)
        if self.on_call is not None:
            self.on_call()
        if self.raises is not None:
            raise self.raises
        return FetchResult(
            ok=True, final_url=url, title="Moby-Dick", text=self.text, fetch_method="httpx"
        )


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture(autouse=True)
def quota_redis(monkeypatch: pytest.MonkeyPatch, quota_redis_fake: Any) -> Any:
    """`web_search` đọc hạn mức + bộ đếm `web:{uid}` qua `get_redis` (T-6.8)."""
    monkeypatch.setattr("app.quota.tiers.get_redis", lambda: quota_redis_fake)
    monkeypatch.setattr("app.quota.web_searches.get_redis", lambda: quota_redis_fake)
    return quota_redis_fake


@pytest.fixture(autouse=True)
def _bind_session(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> _WireRecorder:
    """Body THẬT của adapter qua `MockTransport` — cùng cách fixture `wire` của `test_generate`."""
    recorder = _WireRecorder()
    real = openai_compat.AsyncOpenAI

    def _build(**kwargs: Any) -> Any:
        transport = httpx.MockTransport(recorder)
        return real(**{**kwargs, "http_client": httpx.AsyncClient(transport=transport)})

    monkeypatch.setattr(openai_compat, "AsyncOpenAI", _build)
    return recorder


@pytest.fixture
def fetch(monkeypatch: pytest.MonkeyPatch) -> FetchRecorder:
    recorder = FetchRecorder()
    monkeypatch.setattr(registry_mod, "fetch_url", recorder)
    return recorder


async def _tree(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    model_id: str = TOOLS_MODEL,
    web_tools: bool = True,
    question: str = "Đọc https://httpbin.org/html và cho biết tác giả",
    parent_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
) -> Message:
    repo = MessageRepository(session)
    if conversation_id is None:
        conv: Conversation = await ConversationRepository(session).create_conversation(
            user_id=user_id
        )
        conversation_id = conv.id
    q = await repo.create_message(
        conversation_id=conversation_id,
        user_id=user_id,
        role=MessageRole.USER,
        parent_id=parent_id,
        content=question,
        status=MessageStatus.COMPLETED,
    )
    answer = await repo.create_message(
        conversation_id=conversation_id,
        user_id=user_id,
        role=MessageRole.ASSISTANT,
        parent_id=q.id,
        status=MessageStatus.QUEUED,
        model_id=model_id,
        web_tools=web_tools,
    )
    await session.commit()
    return answer


async def _rounds(factory: async_sessionmaker[AsyncSession], mid: uuid.UUID) -> Any:
    async with factory() as s:
        return (await s.execute(select(Message.tool_rounds).where(Message.id == mid))).scalar_one()


# ───────────────────────── một vòng: thứ tự + sổ ─────────────────────────


async def test_one_round_event_order_rounds_and_exactly_one_ledger_row(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    fetch: FetchRecorder,
) -> None:
    """DoD: `start · tool_call · tool_result · delta… · usage · done`, 1 vòng, ĐÚNG 1 dòng sổ."""
    message = await _tree(session, user_a)
    client = SeqClient(ROUND1, ROUND2)

    await generate(_ctx(fake_redis, client), str(message.id))  # type: ignore[arg-type]

    kinds = fake_redis.kind
    assert kinds[:3] == ["start", "tool_call", "tool_result"]
    assert set(kinds[3:-2]) == {"delta"} and kinds[-2:] == ["usage", "done"]
    result = fake_redis.data(2)
    assert result["ok"] is True and result["name"] == "fetch_url"
    assert result["result"] == {
        "sources": [{"url": PAGE_URL, "title": "Moby-Dick"}],
        "reason": None,
    }
    assert PAGE_TEXT not in json.dumps(result)  # chip không mang chữ trang
    assert fetch.urls == [PAGE_URL]

    # Lần gọi 1 mời tool, lần 2 mời tiếp (còn vòng) — dây lần 2 có cặp tool.
    assert client.calls[0]["tools"][0]["function"]["name"] == "fetch_url"
    second = client.calls[1]["messages"]
    assert ROUND1[0].tool_call is not None
    assert second[-2]["tool_calls"] == [ROUND1[0].tool_call.to_wire()]  # NQ-22 nguyên văn
    assert second[-1]["role"] == "tool" and PAGE_TEXT in second[-1]["content"]
    assert second[-1]["content"].startswith('<untrusted_content name="https://httpbin.org/html">')

    reloaded = await _reload(session_factory, message.id)
    assert reloaded.status is MessageStatus.COMPLETED
    assert "Herman Melville" in reloaded.content
    assert reloaded.tool_calls is None  # lời gọi đã chạy sống trong `tool_rounds`
    rounds = await _rounds(session_factory, message.id)
    assert len(rounds) == 1
    assert rounds[0]["finish_reason"] == "tool_calls"
    assert rounds[0]["results"][0]["content"] == PAGE_TEXT

    ledger = await _read_ledger(session_factory, user_a)
    assert len(ledger) == 1
    u1, u2 = ROUND1[-1].usage, ROUND2[-1].usage
    assert u1 is not None and u2 is not None
    assert ledger[0].prompt_tokens == u1.prompt_tokens + u2.prompt_tokens
    assert ledger[0].completion_tokens == u1.completion_tokens + u2.completion_tokens
    assert reloaded.prompt_tokens == u1.prompt_tokens + u2.prompt_tokens
    assert fake_redis.last["data"]["usage"]["in"] == u1.prompt_tokens + u2.prompt_tokens


async def test_two_calls_in_one_round_two_results_matching_ids(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    fetch: FetchRecorder,
) -> None:
    message = await _tree(session, user_a)
    client = SeqClient(_calls_turn(_fetch("c_1", "https://a.example/"), _fetch("c_2")), ROUND2)

    await generate(_ctx(fake_redis, client), str(message.id))  # type: ignore[arg-type]

    results = [fake_redis.data(i) for i, k in enumerate(fake_redis.kind) if k == "tool_result"]
    assert [r["call_id"] for r in results] == ["c_1", "c_2"]
    sent = client.calls[1]["messages"]
    assert [m["tool_call_id"] for m in sent[-2:]] == ["c_1", "c_2"]
    assert [c["id"] for c in sent[-3]["tool_calls"]] == ["c_1", "c_2"]
    rounds = await _rounds(session_factory, message.id)
    assert [r["tool_call_id"] for r in rounds[0]["results"]] == ["c_1", "c_2"]


async def test_past_max_tool_rounds_last_call_has_no_tools(
    session: AsyncSession,
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    fetch: FetchRecorder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MAX_TOOL_ROUNDS", 2)
    message = await _tree(session, user_a)
    # Model đòi tool mãi — vòng lặp phải tự dừng.
    client = SeqClient(*(_calls_turn(_fetch(f"c_{n}")) for n in range(5)))

    await generate(_ctx(fake_redis, client), str(message.id))  # type: ignore[arg-type]

    assert [c["tools"] is not None for c in client.calls] == [True, True, False]
    assert len(fetch.urls) == 2
    assert fake_redis.last["type"] == "done"


async def test_past_max_tool_calls_per_turn_extra_are_ok_false(
    session: AsyncSession,
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    fetch: FetchRecorder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MAX_TOOL_CALLS_PER_TURN", 1)
    message = await _tree(session, user_a)
    client = SeqClient(_calls_turn(_fetch("c_1"), _fetch("c_2")), ROUND2)

    await generate(_ctx(fake_redis, client), str(message.id))  # type: ignore[arg-type]

    results = [fake_redis.data(i) for i, k in enumerate(fake_redis.kind) if k == "tool_result"]
    assert [(r["ok"], r["result"]["reason"]) for r in results] == [
        (True, None),
        (False, "too_many_calls"),
    ]
    assert len(fetch.urls) == 1


async def test_unknown_tool_is_ok_false_and_turn_finishes(
    session: AsyncSession, user_a: uuid.UUID, fake_redis: FakeRedis, fetch: FetchRecorder
) -> None:
    message = await _tree(session, user_a)
    bogus = ToolCall(call_id="c_x", name="rm_rf", arguments="{}")
    client = SeqClient(_calls_turn(bogus), ROUND2)

    await generate(_ctx(fake_redis, client), str(message.id))  # type: ignore[arg-type]

    result = fake_redis.data(fake_redis.kind.index("tool_result"))
    assert (result["ok"], result["result"]["reason"]) == (False, "unknown_tool")
    assert client.calls[1]["messages"][-1]["content"] == "[rm_rf lỗi: unknown_tool]"
    assert fake_redis.last["type"] == "done" and fetch.urls == []


async def test_bad_arguments_is_ok_false(
    session: AsyncSession, user_a: uuid.UUID, fake_redis: FakeRedis, fetch: FetchRecorder
) -> None:
    message = await _tree(session, user_a)
    broken = ToolCall(call_id="c_b", name="fetch_url", arguments='{"url": ')
    client = SeqClient(_calls_turn(broken), ROUND2)

    await generate(_ctx(fake_redis, client), str(message.id))  # type: ignore[arg-type]

    result = fake_redis.data(fake_redis.kind.index("tool_result"))
    assert (result["ok"], result["result"]["reason"]) == (False, "invalid_arguments")
    assert fake_redis.last["type"] == "done"


async def test_tool_raising_is_ok_false_and_turn_finishes(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    fetch: FetchRecorder,
) -> None:
    fetch.raises = RuntimeError("fetcher no")
    message = await _tree(session, user_a)
    client = SeqClient(ROUND1, ROUND2)

    await generate(_ctx(fake_redis, client), str(message.id))  # type: ignore[arg-type]

    result = fake_redis.data(fake_redis.kind.index("tool_result"))
    assert (result["ok"], result["result"]["reason"]) == (False, "tool_error")
    assert fake_redis.last["type"] == "done"
    assert (await _reload(session_factory, message.id)).status is MessageStatus.COMPLETED


# ───────────────────────────── huỷ (§7.5, B-96) ─────────────────────────────


async def test_cancel_while_tool_runs_no_more_tools_no_more_model_calls(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    fetch: FetchRecorder,
) -> None:
    message = await _tree(session, user_a)
    fetch.on_call = lambda: fake_redis.cancel_flags.add(f"cancel:{message.id}")
    client = SeqClient(_calls_turn(_fetch("c_1"), _fetch("c_2")), ROUND2)

    await generate(_ctx(fake_redis, client), str(message.id))  # type: ignore[arg-type]

    assert len(client.calls) == 1
    assert fetch.urls == [PAGE_URL]  # lời gọi thứ hai không chạy
    assert fake_redis.last == {
        "type": "done",
        "data": fake_redis.last["data"] | {"finish_reason": "cancelled"},
    }
    assert (await _reload(session_factory, message.id)).status is MessageStatus.CANCELLED
    assert len(await _read_ledger(session_factory, user_a)) == 1


async def test_cancel_between_rounds_zero_next_model_calls(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    fetch: FetchRecorder,
) -> None:
    """Cờ đặt trong lúc tool CUỐI của vòng chạy ⇒ phép kiểm đầu vòng kế bắt được."""
    message = await _tree(session, user_a)
    fetch.on_call = lambda: fake_redis.cancel_flags.add(f"cancel:{message.id}")
    client = SeqClient(ROUND1, ROUND2)

    await generate(_ctx(fake_redis, client), str(message.id))  # type: ignore[arg-type]

    assert len(client.calls) == 1
    # Vòng 1 đã khép nên `usage` của nó là số thật của provider (B-160).
    assert fake_redis.kind[-3:] == ["tool_result", "usage", "done"]
    assert fake_redis.last["data"]["finish_reason"] == "cancelled"
    assert (await _reload(session_factory, message.id)).status is MessageStatus.CANCELLED


# ───────────────────────────── ngân sách (B-208) ─────────────────────────────


async def test_budget_too_small_for_next_round_answers_without_tools(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    fetch: FetchRecorder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = await _tree(session, user_a)
    model = get_model(TOOLS_MODEL)
    assert model is not None
    initial = await llm_context.build(session, message.id, model, user_id=user_a)
    budget = count_messages(initial, model_id=model.id) + 400  # đủ schema + một mẩu trang
    monkeypatch.setattr(llm_context, "token_budget", lambda _m: budget)
    fetch.text = "chữ trang dài " * 5000
    client = SeqClient(ROUND1, ROUND2)

    await generate(_ctx(fake_redis, client), str(message.id))  # type: ignore[arg-type]

    assert [c["tools"] is not None for c in client.calls] == [True, False]
    assert count_messages(client.calls[1]["messages"], model_id=model.id) <= budget
    assert fake_redis.last["type"] == "done"
    reloaded = await _reload(session_factory, message.id)
    assert reloaded.status is MessageStatus.COMPLETED and reloaded.error_code is None
    cut = (await _rounds(session_factory, message.id))[0]["results"][0]["content"]
    assert 0 < len(cut) < len(fetch.text)


# ───────────────────────────── C18 + ngữ cảnh lượt sau ─────────────────────────────


async def test_web_tools_false_real_body_has_no_tools_key(
    session: AsyncSession, user_a: uuid.UUID, fake_redis: FakeRedis, wire: _WireRecorder
) -> None:
    """C18 trên body THẬT của adapter: `web_tools=false` ⇒ khoá `tools` vắng hẳn."""
    message = await _tree(session, user_a, web_tools=False)
    system = SystemAdapter.from_settings()
    try:
        await generate(_ctx(fake_redis, system), str(message.id))  # type: ignore[arg-type]
    finally:
        await system.close()
    assert "tools" not in wire.body


async def test_web_tools_on_model_without_tools_capability_sends_no_tools(
    session: AsyncSession, user_a: uuid.UUID, fake_redis: FakeRedis, fetch: FetchRecorder
) -> None:
    """Lưới thứ hai sau `422` của API: cờ lọt tới worker vẫn không mời tool (C18)."""
    message = await _tree(session, user_a, model_id=NO_TOOLS_MODEL)
    client = SeqClient(ROUND2)

    await generate(_ctx(fake_redis, client), str(message.id))  # type: ignore[arg-type]

    assert [c["tools"] for c in client.calls] == [None]


async def test_next_turn_build_has_no_tool_result_only_web_line(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    fetch: FetchRecorder,
) -> None:
    """C33: chữ trang chỉ đủ trong vòng lặp của lượt chứa nó; lượt sau còn một dòng."""
    first = await _tree(session, user_a)
    await generate(_ctx(fake_redis, SeqClient(ROUND1, ROUND2)), str(first.id))  # type: ignore[arg-type]
    nxt = await _tree(
        session,
        user_a,
        question="cảm ơn",
        parent_id=first.id,
        conversation_id=first.conversation_id,
    )
    model = get_model(TOOLS_MODEL)
    assert model is not None

    # Session MỚI: worker ghi bằng UPDATE thẳng, identity map của `session` còn
    # giữ bản `queued` của câu trả lời (xem `_reload`).
    async with session_factory() as fresh:
        built = await llm_context.build(fresh, nxt.id, model, user_id=user_a)

    dumped = json.dumps(built, ensure_ascii=False)
    assert PAGE_TEXT not in dumped and '<untrusted_content name="' not in dumped
    assert all(m["role"] != "tool" and "tool_calls" not in m for m in built)
    answer = next(m for m in built if m["role"] == "assistant")
    assert answer["content"].endswith("[đã dùng web: 1 nguồn]")


# ───────────────────────────── estimator (Q-P6-6) ─────────────────────────────


def test_estimate_for_web_turn_is_est_max_times_rounds_plus_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MAX_TOOL_ROUNDS", 3)
    model = get_model("claude-haiku")
    assert model is not None
    question = [{"role": "user", "content": "xin chào"}]

    plain = estimate(model, question).est_max_usd
    web = estimate(model, question, web_tools=True).est_max_usd

    assert plain > Decimal(0)
    assert web == plain * 4


# ───────────────────────────── `messages` không phình ─────────────────────────────


async def test_one_turn_one_message_row(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    fetch: FetchRecorder,
) -> None:
    """Q-P6-1: hai vòng tool vẫn đúng hai hàng (câu hỏi + câu trả lời), không role `tool`."""
    message = await _tree(session, user_a)
    client = SeqClient(_calls_turn(_fetch("c_1")), _calls_turn(_fetch("c_2")), ROUND2)

    await generate(_ctx(fake_redis, client), str(message.id))  # type: ignore[arg-type]

    async with session_factory() as s:
        count = (
            await s.execute(
                select(func.count())
                .select_from(Message)
                .where(Message.conversation_id == message.conversation_id)
            )
        ).scalar_one()
    assert count == 2
    assert len(await _rounds(session_factory, message.id)) == 2


# ───────────────────────────── `web_search` (T-6.7b) ─────────────────────────────

HITS = (
    SearchHit(title="Tin B", url="https://b.example/2", content="Đoạn trích B"),
    SearchHit(title="Tin A", url="https://a.example/1", content="Đoạn trích A"),
)


class SearchRecorder:
    def __init__(self, result: SearchResult) -> None:
        self.result = result
        self.queries: list[str] = []

    async def search(self, query: str, *, max_results: int | None = None) -> SearchResult:
        self.queries.append(query)
        return self.result


def _search(call_id: str = "c_s") -> ToolCall:
    return ToolCall(call_id=call_id, name="web_search", arguments='{"query": "tin mới"}')


async def test_web_search_ok_sources_in_order_in_tool_result_and_rounds(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    search = SearchRecorder(SearchResult(results=HITS))
    monkeypatch.setattr(registry_mod, "search_provider", search)
    message = await _tree(session, user_a)
    client = SeqClient(_calls_turn(_search()), ROUND2)

    await generate(_ctx(fake_redis, client), str(message.id))  # type: ignore[arg-type]

    sources = [{"url": h.url, "title": h.title} for h in HITS]
    assert [t["function"]["name"] for t in client.calls[0]["tools"]] == [
        "fetch_url",
        "web_search",
    ]
    result = fake_redis.data(fake_redis.kind.index("tool_result"))
    assert result["ok"] is True and result["name"] == "web_search"
    assert result["result"] == {"sources": sources, "reason": None}
    assert "Đoạn trích" not in json.dumps(result, ensure_ascii=False)
    assert search.queries == ["tin mới"]
    sent = client.calls[1]["messages"][-1]["content"]
    assert sent.startswith('<untrusted_content name="web_search">')
    assert "1. Tin B · https://b.example/2\nĐoạn trích B" in sent
    assert sent.index("Tin B") < sent.index("Tin A")
    rounds = await _rounds(session_factory, message.id)
    assert rounds[0]["results"][0]["sources"] == sources
    assert fake_redis.last["type"] == "done"


def _real_tavily(monkeypatch: pytest.MonkeyPatch, key: str, handler: Any) -> list[httpx.Request]:
    """`TavilySearch` THẬT sau registry; chỉ tầng mạng giả (`MockTransport`)."""
    sent: list[httpx.Request] = []

    def _record(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return handler(request)

    monkeypatch.setattr(settings, "TAVILY_API_KEY", SecretStr(key))
    monkeypatch.setattr(
        web_search_mod,
        "_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(_record)),
    )
    return sent


async def test_web_search_error_is_ok_false_turn_done_with_content(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UC-08 dòng 5: Tavily hết giờ ⇒ `ok: false`, model được báo, lượt `done` có chữ."""

    def _stalled(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("tavily im lang", request=request)

    sent = _real_tavily(monkeypatch, "tvly-khoa-gia", _stalled)
    message = await _tree(session, user_a)
    client = SeqClient(_calls_turn(_search()), ROUND2)

    await generate(_ctx(fake_redis, client), str(message.id))  # type: ignore[arg-type]

    assert len(sent) == 1
    result = fake_redis.data(fake_redis.kind.index("tool_result"))
    assert (result["ok"], result["result"]) == (False, {"sources": [], "reason": "timeout"})
    told = client.calls[1]["messages"][-1]["content"]
    assert told == f"[web_search lỗi: timeout] {registry_mod.SEARCH_UNAVAILABLE}"
    assert fake_redis.kind[-2:] == ["usage", "done"]
    reloaded = await _reload(session_factory, message.id)
    assert reloaded.status is MessageStatus.COMPLETED and reloaded.content.strip()


async def test_web_search_empty_key_zero_requests_not_configured(
    session: AsyncSession,
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = _real_tavily(monkeypatch, "", lambda _r: httpx.Response(200, json={"results": []}))
    message = await _tree(session, user_a)
    client = SeqClient(_calls_turn(_search()), ROUND2)

    await generate(_ctx(fake_redis, client), str(message.id))  # type: ignore[arg-type]

    result = fake_redis.data(fake_redis.kind.index("tool_result"))
    assert (result["ok"], result["result"]["reason"]) == (False, "not_configured")
    assert sent == []
    assert fake_redis.last["type"] == "done"


async def test_web_search_blank_query_is_invalid_arguments_no_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    search = SearchRecorder(SearchResult(results=HITS))
    monkeypatch.setattr(registry_mod, "search_provider", search)
    ctx = registry_mod.UserContext(user_id=uuid.uuid4(), web_tools=True)

    out = await registry_mod.registry.call("web_search", '{"query": "  "}', ctx)

    assert (out.ok, out.reason) == (False, "invalid_arguments")
    assert search.queries == []


# ═══════════════ T-6.8: `web_searches_per_day` — cửa sổ trượt 24 h ═══════════════


async def test_override_one_search_per_day_second_search_is_web_quota_turn_done(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    quota_redis: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ghi đè từng người (B-153) `1` ⇒ lời gọi thứ hai không tới Tavily, `ok: false`, `done`."""
    await session.execute(
        update(User)
        .where(User.id == user_a)
        .values(limit_override_json={"web_searches_per_day": 1})
    )
    await session.commit()
    search = SearchRecorder(SearchResult(results=HITS))
    monkeypatch.setattr(registry_mod, "search_provider", search)
    message = await _tree(session, user_a)
    client = SeqClient(_calls_turn(_search("c_s1"), _search("c_s2")), ROUND2)

    await generate(_ctx(fake_redis, client), str(message.id))  # type: ignore[arg-type]

    assert search.queries == ["tin mới"]
    first, second = (
        fake_redis.data(i) for i, k in enumerate(fake_redis.kind) if k == "tool_result"
    )
    assert first["ok"] is True
    assert (second["ok"], second["result"]["reason"]) == (False, "web_quota")
    told = client.calls[1]["messages"][-1]["content"]
    assert told.startswith("[web_search lỗi: web_quota] Đã dùng hết 1 lượt")
    assert "có lại một lượt lúc" in told
    assert len(quota_redis.zset[f"web:{user_a}"]) == 1
    assert fake_redis.last["type"] == "done"
    reloaded = await _reload(session_factory, message.id)
    assert reloaded.status is MessageStatus.COMPLETED


async def test_fetch_url_does_not_count_as_web_search(
    session: AsyncSession,
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    quota_redis: Any,
    fetch: FetchRecorder,
) -> None:
    """§12.4 nói "lượt search" — `fetch_url` không chạm bộ đếm."""
    message = await _tree(session, user_a)
    client = SeqClient(_calls_turn(_fetch("c_f")), ROUND2)

    await generate(_ctx(fake_redis, client), str(message.id))  # type: ignore[arg-type]

    assert fetch.urls == [PAGE_URL]
    assert not any(k.startswith(web_searches.WEB_PREFIX) for k in quota_redis.zset)


async def test_entry_older_than_24h_is_not_counted_and_is_cleaned(quota_redis: Any) -> None:
    """Score đặt tường minh (B-290): 24 h + 1 s trước rơi ra; 24 h − 1 s trước còn tính."""
    uid = uuid.uuid4()
    now = time.time()
    key = f"{web_searches.WEB_PREFIX}{uid}"
    quota_redis.zset[key] = {"cu": now - web_searches.DAY_S - 1}

    assert await web_searches.take_search(uid, limit=1, now=now) is None
    assert "cu" not in quota_redis.zset[key] and len(quota_redis.zset[key]) == 1

    quota_redis.zset[key] = {"sat": now - web_searches.DAY_S + 1}
    refill_at = await web_searches.take_search(uid, limit=1, now=now)
    assert refill_at == pytest.approx(now + 1)
    assert list(quota_redis.zset[key]) == ["sat"]


async def test_limit_zero_never_refills(quota_redis: Any) -> None:
    assert await web_searches.take_search(uuid.uuid4(), limit=0, now=time.time()) == math.inf
