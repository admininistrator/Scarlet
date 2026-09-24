"""T-S.6 — mức suy luận ở biên vào: `POST …/messages`, `retry`, `PATCH`, đường đi.

KH tham chiếu: §24.2b·S4, S14, §18.2, UC-04 · tasks.md T-S.6 · NQ-118.

Bốn câu, mỗi câu một nhóm test:

1. **Thứ tự thắng** — body › (retry) mức của câu trả lời đang thử lại › mức đã
   nhớ `reasoning_prefs[model]` › `reasoning.default` › `NULL`.
2. **Chỉ mức người gọi ghi rõ mới được hỏng**, và hỏng **trước** mọi `INSERT`:
   `400 REASONING_UNSUPPORTED`, `count(*)` không đổi (DoD dòng 3).
3. **Retry bằng model khác + mức khác** ⇒ hai anh em cùng `parent_id`, khác
   `model_id` và `reasoning_effort` (DoD dòng 5, UC-04 dòng 4).
4. **Cột đi ra đường đi** — `GET /conversations/{id}` và `/siblings`.

Catalog là bản thật **cộng** ba model dựng cho test (`_TEST_MODELS`): mức của
`deepseek-flash` đổi theo phép đo (T-S.2, T-S.6), còn luật thì không — test
bám model của chính nó để không đỏ mỗi lần catalog đổi dữ liệu. Cùng lối
`test_models.py::test_s7_new_model_with_reasoning_appears_after_reload`.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import catalog
from app.core.access_token import encode_access_token
from app.core.deps import SESSION_COOKIE_NAME
from app.db.models import Conversation, Message, MessageStatus, UserRole, UserStatus
from app.db.repositories import (
    ConversationRepository,
    MessageRepository,
    UserSettingsRepository,
)
from app.main import app

CREATE_MESSAGE = "/api/v1/conversations/{}/messages"
RETRY = "/api/v1/messages/{}/retry"
EDIT_MESSAGE = "/api/v1/messages/{}"
SIBLINGS = "/api/v1/messages/{}/siblings"
CONVERSATION = "/api/v1/conversations/{}"

#: Model có ba mức, mặc định `low`.
THINKER = "ts6-thinker"
#: Model có hai mức (`off`, `high`) — KHÔNG có `low`, để đo ca "mức thừa kế
#: không còn hợp lệ ở model mới".
OTHER_THINKER = "ts6-other-thinker"
#: Model không khai khối `reasoning`.
PLAIN = "ts6-plain"

_TEST_MODELS: list[dict[str, Any]] = [
    {
        "id": THINKER,
        "display_name": "T-S.6 Thinker",
        "provider": "deepseek",
        "upstream_model": "deepseek/ts6-thinker",
        "context_window": 32768,
        "max_output": 4096,
        "pricing_mode": "unmetered",
        "order": 91,
        "reasoning": {
            "default": "low",
            "options": [
                {"id": "off", "params": {"thinking": {"type": "disabled"}}},
                {"id": "low", "params": {"reasoning_effort": "low"}},
                {"id": "high", "params": {"reasoning_effort": "high"}},
            ],
        },
    },
    {
        "id": OTHER_THINKER,
        "display_name": "T-S.6 Other Thinker",
        "provider": "anthropic",
        "upstream_model": "anthropic/ts6-other-thinker",
        "context_window": 32768,
        "max_output": 4096,
        "pricing_mode": "unmetered",
        "order": 92,
        "reasoning": {
            "default": "off",
            "options": [
                {"id": "off", "params": {"thinking": {"type": "disabled"}}},
                {
                    "id": "high",
                    "params": {"thinking": {"type": "enabled", "budget_tokens": 1024}},
                    "omit_temperature": True,
                },
            ],
        },
    },
    {
        "id": PLAIN,
        "display_name": "T-S.6 Plain",
        "provider": "ollama",
        "upstream_model": "openai/ts6-plain",
        "context_window": 32768,
        "max_output": 4096,
        "pricing_mode": "unmetered",
        "order": 93,
    },
]


# ─────────────────────────────── hạ tầng ───────────────────────────────


@pytest.fixture(autouse=True)
def _ts6_catalog(tmp_path: Path) -> Iterator[None]:
    """Catalog thật + ba model của test; trả catalog thật khi xong."""
    raw = json.loads(catalog.CATALOG_PATH.read_text(encoding="utf-8"))
    raw["models"].extend(_TEST_MODELS)
    fixture = tmp_path / "model_catalog.json"
    fixture.write_text(json.dumps(raw), encoding="utf-8")
    catalog.reload(path=fixture)
    yield
    catalog.reload(path=catalog.CATALOG_PATH)


class FakeArq:
    """Pool arq giả — ghi lại mọi lần enqueue (cùng khuôn `test_branching.py`)."""

    def __init__(self) -> None:
        self.pushed: list[tuple[str, tuple[Any, ...]]] = []

    async def enqueue_job(self, name: str, *args: Any, **_: Any) -> object | None:
        self.pushed.append((name, args))
        return object()


@pytest.fixture(autouse=True)
def _db_for_tests(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`session_scope()` trong handler trỏ vào ĐÚNG kết nối của test (NQ-17)."""
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


@pytest_asyncio.fixture(autouse=True)
async def fake_arq(monkeypatch: pytest.MonkeyPatch) -> FakeArq:
    fake = FakeArq()

    async def _pool() -> FakeArq:
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
    """Header `Cookie` mang phiên thật (§11.2) — cùng khuôn `test_branching.py`."""
    token = encode_access_token(
        user_id=user_id,
        role=UserRole.USER,
        tier="free",
        status=UserStatus.ACTIVE,
        ttl_minutes=15,
    )
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


async def _create_conversation(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> Conversation:
    async with session_factory() as session:
        conversation = await ConversationRepository(session).create_conversation(user_id=user_id)
        await session.commit()
        return conversation


async def _read_message(
    session_factory: async_sessionmaker[AsyncSession], message_id: uuid.UUID
) -> Message:
    async with session_factory() as session:
        message = await session.get(Message, message_id)
        assert message is not None
        return message


async def _count_all_messages(session_factory: async_sessionmaker[AsyncSession]) -> int:
    """`SELECT count(*) FROM messages` — đúng câu của DoD dòng 3, không lọc gì."""
    async with session_factory() as session:
        return int((await session.execute(select(func.count()).select_from(Message))).scalar_one())


async def _remember(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID, prefs: dict[str, str]
) -> None:
    """Ghi mức đã nhớ thẳng vào `user_settings` — hình dạng `prefs_json` của T-S.5."""
    async with session_factory() as session:
        await UserSettingsRepository(session).put_prefs(user_id, {"reasoning": prefs})
        await session.commit()


async def _complete(
    session_factory: async_sessionmaker[AsyncSession], message_id: uuid.UUID
) -> None:
    """Khép lượt sinh như worker làm — không thì `retry` trả `409` đúng đắn."""
    async with session_factory() as session:
        await MessageRepository(session).finish_generation(
            message_id, status=MessageStatus.COMPLETED, content="xong", finish_reason="stop"
        )
        await session.commit()


async def _send(
    client: AsyncClient, conversation_id: uuid.UUID, user_id: uuid.UUID, **body: Any
) -> Any:
    return await client.post(
        CREATE_MESSAGE.format(conversation_id),
        headers=_session(user_id),
        json={"content": "hỏi", **body},
    )


async def _sent_level(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
    **body: Any,
) -> str | None:
    """Gửi một câu, trả `reasoning_effort` đã ghi lên hàng assistant `queued`."""
    conversation = await _create_conversation(session_factory, user_id)
    resp = await _send(client, conversation.id, user_id, **body)
    assert resp.status_code == 202, resp.text
    row = await _read_message(session_factory, uuid.UUID(resp.json()["assistant_message_id"]))
    return row.reasoning_effort


# ─────────────────────── 1. thứ tự thắng ───────────────────────


async def test_body_level_is_written_on_the_queued_assistant_row(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    """Mức chốt ở API, cùng chỗ `model_id` — job chỉ mang một khoá chính (C5)."""
    conversation = await _create_conversation(session_factory, user_a)

    resp = await _send(client, conversation.id, user_a, model_id=THINKER, reasoning_effort="high")

    assert resp.status_code == 202, resp.text
    user_row = await _read_message(session_factory, uuid.UUID(resp.json()["user_message_id"]))
    answer = await _read_message(session_factory, uuid.UUID(resp.json()["assistant_message_id"]))
    assert answer.status is MessageStatus.QUEUED
    assert answer.model_id == THINKER
    assert answer.reasoning_effort == "high"
    assert user_row.reasoning_effort is None, "câu hỏi không có lượt sinh nào"


async def test_body_beats_remembered_level(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    await _remember(session_factory, user_a, {THINKER: "off"})

    level = await _sent_level(
        client, session_factory, user_a, model_id=THINKER, reasoning_effort="high"
    )

    assert level == "high"


async def test_remembered_level_beats_catalog_default(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    await _remember(session_factory, user_a, {THINKER: "off"})

    assert await _sent_level(client, session_factory, user_a, model_id=THINKER) == "off"


async def test_remembered_level_is_per_model(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    """S4: nhớ **theo user × model** — mức của model khác không lan sang."""
    await _remember(session_factory, user_a, {OTHER_THINKER: "high"})

    assert await _sent_level(client, session_factory, user_a, model_id=THINKER) == "low"


async def test_no_body_no_memory_uses_catalog_default(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    assert await _sent_level(client, session_factory, user_a, model_id=THINKER) == "low"


async def test_explicit_null_behaves_like_absent(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    """`null` không phải một mức — nó là "không chọn", rơi xuống nguồn kế."""
    level = await _sent_level(
        client, session_factory, user_a, model_id=THINKER, reasoning_effort=None
    )

    assert level == "low"


async def test_stale_remembered_level_is_skipped_not_400(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    tmp_path: Path,
) -> None:
    """Mức đã nhớ mà admin vừa gỡ khỏi catalog: bỏ qua, không đổ lỗi người gửi.

    Cùng lý lẽ `read_prefs` của T-S.5 (Cạm bẫy ③ của T-3.0) — chỉ mức ghi rõ
    trong body mới được phép thành `400`.
    """
    await _remember(session_factory, user_a, {THINKER: "high"})
    raw = json.loads(catalog.CATALOG_PATH.read_text(encoding="utf-8"))
    trimmed = json.loads(json.dumps(_TEST_MODELS[0]))
    trimmed["reasoning"]["options"] = [
        o for o in trimmed["reasoning"]["options"] if o["id"] != "high"
    ]
    raw["models"].append(trimmed)
    fixture = tmp_path / "trimmed_catalog.json"
    fixture.write_text(json.dumps(raw), encoding="utf-8")
    catalog.reload(path=fixture)

    assert await _sent_level(client, session_factory, user_a, model_id=THINKER) == "low"


async def test_model_without_reasoning_block_writes_NULL(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    """Không khối `reasoning` ⇒ không gửi gì ⇒ cột `NULL` — và KHÔNG đọc mức đã nhớ."""
    await _remember(session_factory, user_a, {THINKER: "high"})

    assert await _sent_level(client, session_factory, user_a, model_id=PLAIN) is None


# ─────────────────── 2. mức sai: 400 trước mọi INSERT ───────────────────


@pytest.mark.parametrize(
    ("model_id", "level"),
    [
        (PLAIN, "high"),  # model không có khối `reasoning` — DoD dòng 3
        (OTHER_THINKER, "low"),  # có khối, nhưng không khai mức ấy
        (THINKER, "ultra-bogus"),  # ngoài bộ từ vựng
    ],
)
async def test_unsupported_level_is_400_and_writes_nothing(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_arq: FakeArq,
    model_id: str,
    level: str,
) -> None:
    """**DoD dòng 3** — `400 REASONING_UNSUPPORTED`, `count(*)` KHÔNG đổi, không job."""
    conversation = await _create_conversation(session_factory, user_a)
    before = await _count_all_messages(session_factory)

    resp = await _send(client, conversation.id, user_a, model_id=model_id, reasoning_effort=level)

    assert resp.status_code == 400, resp.text
    body = resp.json()["error"]
    assert body["code"] == "REASONING_UNSUPPORTED"
    assert body["details"] == {"model_id": model_id, "level": level}
    assert await _count_all_messages(session_factory) == before
    assert fake_arq.pushed == []


async def test_level_is_checked_against_the_EFFECTIVE_model(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    """Vắng `model_id` ⇒ model mặc định của hội thoại/catalog; mức kiểm theo nó.

    Model mặc định thật là model có khối `reasoning` — mức mặc định của nó hợp
    lệ, còn một mức bịa thì không.
    """
    default = catalog.get_default_model()
    assert default is not None and default.reasoning is not None
    conversation = await _create_conversation(session_factory, user_a)

    ok = await _send(client, conversation.id, user_a, reasoning_effort=default.reasoning.default)
    bad = await _send(client, conversation.id, user_a, reasoning_effort="ultra-bogus")

    assert ok.status_code == 202, ok.text
    assert bad.status_code == 400
    assert bad.json()["error"]["details"]["model_id"] == default.id


# ───────────────────────────── 3. retry ─────────────────────────────


async def _answered_turn(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
    **body: Any,
) -> uuid.UUID:
    """Một lượt đã khép; trả `id` câu trả lời."""
    conversation = await _create_conversation(session_factory, user_id)
    resp = await _send(client, conversation.id, user_id, **body)
    assert resp.status_code == 202, resp.text
    amid = uuid.UUID(resp.json()["assistant_message_id"])
    await _complete(session_factory, amid)
    return amid


async def test_retry_other_model_and_level_two_siblings_differ(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    """**DoD dòng 5** (UC-04 dòng 4): cùng `parent_id`, khác model VÀ mức; bản cũ nguyên."""
    amid = await _answered_turn(
        client, session_factory, user_a, model_id=THINKER, reasoning_effort="high"
    )

    resp = await client.post(
        RETRY.format(amid),
        headers=_session(user_a),
        json={"model_id": OTHER_THINKER, "reasoning_effort": "off"},
    )

    assert resp.status_code == 202, resp.text
    old = await _read_message(session_factory, amid)
    new = await _read_message(session_factory, uuid.UUID(resp.json()["assistant_message_id"]))
    assert new.parent_id == old.parent_id
    assert (old.model_id, old.reasoning_effort) == (THINKER, "high")
    assert (new.model_id, new.reasoning_effort) == (OTHER_THINKER, "off")


async def test_retry_without_level_reuses_the_retried_answers_level(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    """Việc 3: Thử lại trơn ⇒ đúng mức cũ — kể cả khi mức đã nhớ nói khác.

    Mức đã nhớ đặt `off` SAU lượt đầu: nếu retry bỏ qua mức thừa kế, bản mới
    sẽ lặng lẽ ra `off` thay vì `high`.
    """
    amid = await _answered_turn(
        client, session_factory, user_a, model_id=THINKER, reasoning_effort="high"
    )
    await _remember(session_factory, user_a, {THINKER: "off"})

    resp = await client.post(RETRY.format(amid), headers=_session(user_a))

    assert resp.status_code == 202, resp.text
    new = await _read_message(session_factory, uuid.UUID(resp.json()["assistant_message_id"]))
    assert (new.model_id, new.reasoning_effort) == (THINKER, "high")


async def test_retry_inherited_level_missing_on_new_model_falls_through(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    """Mức thừa kế model mới không khai ⇒ bỏ qua (không `400`) ⇒ đã nhớ ⇒ mặc định."""
    amid = await _answered_turn(
        client, session_factory, user_a, model_id=THINKER, reasoning_effort="low"
    )

    resp = await client.post(
        RETRY.format(amid), headers=_session(user_a), json={"model_id": OTHER_THINKER}
    )

    assert resp.status_code == 202, resp.text
    new = await _read_message(session_factory, uuid.UUID(resp.json()["assistant_message_id"]))
    assert (new.model_id, new.reasoning_effort) == (OTHER_THINKER, "off")


async def test_retry_body_level_beats_inherited(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    amid = await _answered_turn(
        client, session_factory, user_a, model_id=THINKER, reasoning_effort="high"
    )

    resp = await client.post(
        RETRY.format(amid), headers=_session(user_a), json={"reasoning_effort": "off"}
    )

    new = await _read_message(session_factory, uuid.UUID(resp.json()["assistant_message_id"]))
    assert new.reasoning_effort == "off"


async def test_retry_unsupported_level_is_400_and_writes_nothing(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_arq: FakeArq,
) -> None:
    amid = await _answered_turn(client, session_factory, user_a, model_id=THINKER)
    before = await _count_all_messages(session_factory)
    jobs = len(fake_arq.pushed)

    resp = await client.post(
        RETRY.format(amid),
        headers=_session(user_a),
        json={"model_id": PLAIN, "reasoning_effort": "high"},
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "REASONING_UNSUPPORTED"
    assert await _count_all_messages(session_factory) == before
    assert len(fake_arq.pushed) == jobs


async def test_edit_question_uses_remembered_level(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    """`PATCH` không nhận mức trong body (S14) nhưng đi qua cùng `_pick_reasoning`."""
    conversation = await _create_conversation(session_factory, user_a)
    async with session_factory() as session:
        await ConversationRepository(session).update_conversation(
            conversation.id, user_id=user_a, changes={"default_model": THINKER}
        )
        await session.commit()
    first = await _send(client, conversation.id, user_a)
    await _complete(session_factory, uuid.UUID(first.json()["assistant_message_id"]))
    await _remember(session_factory, user_a, {THINKER: "high"})

    resp = await client.patch(
        EDIT_MESSAGE.format(first.json()["user_message_id"]),
        headers=_session(user_a),
        json={"content": "hỏi lại"},
    )

    assert resp.status_code == 202, resp.text
    new = await _read_message(session_factory, uuid.UUID(resp.json()["assistant_message_id"]))
    assert (new.model_id, new.reasoning_effort) == (THINKER, "high")


# ───────────────────────── 4. cột đi ra đường đi ─────────────────────────


async def test_path_and_siblings_carry_reasoning_effort(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    """Việc 1: `GET /conversations/{id}` và `/siblings` trả cột — chip sau F5 (T-S.15)."""
    conversation = await _create_conversation(session_factory, user_a)
    first = await _send(client, conversation.id, user_a, model_id=THINKER, reasoning_effort="high")
    amid = uuid.UUID(first.json()["assistant_message_id"])
    await _complete(session_factory, amid)
    retried = await client.post(
        RETRY.format(amid),
        headers=_session(user_a),
        json={"model_id": PLAIN},
    )
    await _complete(session_factory, uuid.UUID(retried.json()["assistant_message_id"]))

    path = (await client.get(CONVERSATION.format(conversation.id), headers=_session(user_a))).json()
    siblings = (await client.get(SIBLINGS.format(amid), headers=_session(user_a))).json()

    assert [(m["role"], m["reasoning_effort"]) for m in path["path"]] == [
        ("user", None),
        ("assistant", None),  # lá đang xem là bản retry bằng model không có mức
    ]
    assert [(m["model_id"], m["reasoning_effort"]) for m in siblings["items"]] == [
        (THINKER, "high"),
        (PLAIN, None),
    ]
