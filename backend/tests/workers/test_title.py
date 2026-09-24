"""T-S.7 — `app/workers/title.py`: đặt tên hội thoại tự động (§24.2b·S6).

KH tham chiếu: §24.2b·S3d, S6, §7.2–§7.4, §10.2, §10.3 · A1, A7 · NQ-110.

Dòng DoD của task có mặt ở đây dưới dạng tự động (phần chạy trên stack thật nằm
trong báo cáo):

- **DoD 2** — một dòng `usage_events` `purpose='title'`, `key_source='system'`,
  `cost_usd > 0`, và **không** `ZADD`: `test_one_ledger_row_purpose_title…`
- **DoD 4** — đổi tên trong lúc job còn chạy (**model giả chậm**) ⇒ tên của
  người dùng còn nguyên: `test_user_rename_while_model_is_slow_wins`
- **DoD 7** — model giả ném ⇒ event `error`, `title` vẫn `NULL`, hàm trả về
  bình thường (worker sống): `test_model_raises_error_event_title_stays_null`

Cùng lối `test_generate.py`: Postgres **thật** (fixture của `conftest.py`), chỉ
Redis và provider là giả.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.db.session as db_session
from app.config import catalog
from app.config.settings import CONVERSATION_TITLE_MAX_CHARS, settings
from app.db.models import (
    Conversation,
    KeySource,
    MessageRole,
    MessageStatus,
    UsageEvent,
    UsagePurpose,
)
from app.db.repositories import ConversationRepository, MessageRepository
from app.llm.client import Chunk, Usage
from app.streaming.producer import FIELD_DATA, FIELD_TYPE, title_stream_key
from app.workers.generate import CTX_LLM_CLIENT
from app.workers.title import clean_title, generate_title

QUESTION = "Làm sao nấu phở bò cho 4 người, nước dùng trong?"

# ─────────────────────────── hai thứ giả ───────────────────────────


class FakeRedis:
    """Đủ `xadd`/`expire` (stream tiêu đề) và `zadd` (để bắt một `ZADD` lạc)."""

    def __init__(self) -> None:
        self.records: list[dict[str, str]] = []
        self.expire_calls: list[tuple[str, int]] = []
        self.zset: dict[str, dict[str, float]] = {}
        self._seq = 0

    async def xadd(self, name: str, fields: dict[str, Any]) -> bytes:
        self._seq += 1
        self.records.append({"__key__": name, **fields})
        return f"1725984000{self._seq:03d}-0".encode()

    async def expire(self, name: str, ttl: int) -> int:
        self.expire_calls.append((name, ttl))
        return 1

    async def zadd(self, name: str, mapping: dict[str, float]) -> int:
        self.zset.setdefault(name, {}).update(mapping)
        return len(mapping)

    @property
    def kind(self) -> list[str]:
        return [r[FIELD_TYPE] for r in self.records]

    def data(self, i: int) -> Any:
        return json.loads(self.records[i][FIELD_DATA])


class FakeClient:
    """`LLMClient` giả: phát sẵn một dãy `Chunk`, rồi (tuỳ chọn) nổ.

    `gate` là "model chậm" của DoD 4: chunk đầu ra ngay, phần còn lại chờ tới
    khi test mở cổng — đủ để chen một `PATCH` vào giữa lượt sinh.
    """

    def __init__(
        self,
        chunks: list[Chunk],
        *,
        error: BaseException | None = None,
        gate: asyncio.Event | None = None,
    ) -> None:
        self._chunks = chunks
        self._error = error
        self._gate = gate
        self.call: dict[str, Any] | None = None
        self.first_chunk_sent = asyncio.Event()

    async def stream(self, **kwargs: Any) -> AsyncIterator[Chunk]:
        self.call = kwargs
        return self._emit()

    async def _emit(self) -> AsyncIterator[Chunk]:
        for i, chunk in enumerate(self._chunks):
            yield chunk
            if i == 0:
                self.first_chunk_sent.set()
                if self._gate is not None:
                    await self._gate.wait()
        if self._error is not None:
            raise self._error


class FailsImmediately(FakeClient):
    async def stream(self, **kwargs: Any) -> AsyncIterator[Chunk]:
        self.call = kwargs
        raise RuntimeError("401 Unauthorized")


def _chunks(parts: list[str]) -> list[Chunk]:
    usage = Usage(prompt_tokens=180, completion_tokens=len(parts), total_tokens=180 + len(parts))
    return [
        *(Chunk(kind="delta", text=p) for p in parts),
        Chunk(kind="usage", usage=usage),
        Chunk(kind="done", finish_reason="stop", usage=usage),
    ]


# ─────────────────────────── hạ tầng test ───────────────────────────


@pytest.fixture(autouse=True)
def _bind_session_to_test_db(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`session_scope()` của worker trỏ vào transaction của test — như `test_generate.py`."""
    monkeypatch.setattr(db_session, "get_sessionmaker", lambda: session_factory)


def _ctx(redis: FakeRedis, client: FakeClient) -> dict[str, Any]:
    return {"redis": redis, "job_id": "title:test", CTX_LLM_CLIENT: client}


async def _first_question(
    session_factory: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
    *,
    title: str | None = None,
    content: str = QUESTION,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Hội thoại + câu hỏi đầu — đúng thứ `POST …/messages` đã commit trước khi đẩy job."""
    async with session_factory() as session:
        conversation = await ConversationRepository(session).create_conversation(
            user_id=user_id, title=title
        )
        question = await MessageRepository(session).create_message(
            conversation_id=conversation.id,
            user_id=user_id,
            role=MessageRole.USER,
            content=content,
            status=MessageStatus.COMPLETED,
        )
        await session.commit()
        return conversation.id, question.id


async def _title_in_db(
    session_factory: async_sessionmaker[AsyncSession], cid: uuid.UUID
) -> str | None:
    async with session_factory() as session:
        return (
            await session.execute(select(Conversation.title).where(Conversation.id == cid))
        ).scalar_one()


async def _title_rows(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> list[UsageEvent]:
    async with session_factory() as session:
        return list(
            (
                await session.execute(
                    select(UsageEvent).where(
                        UsageEvent.user_id == user_id, UsageEvent.purpose == UsagePurpose.TITLE
                    )
                )
            )
            .scalars()
            .all()
        )


# ───────────────────────────── đường chạy ─────────────────────────────


async def test_happy_path_start_deltas_done_and_title_written(
    session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    """Bốn event của S6 trên đúng khoá `stream:title:{id}`, `done` mang tiêu đề đã ghi."""
    cid, qid = await _first_question(session_factory, user_a)
    redis = FakeRedis()
    client = FakeClient(_chunks(["Nấu ", "phở bò ", "nước trong"]))

    await generate_title(_ctx(redis, client), str(cid), str(qid))

    assert {r["__key__"] for r in redis.records} == {title_stream_key(cid)}
    assert redis.kind == ["start", "delta", "delta", "delta", "done"]
    assert redis.data(0)["message_id"] == str(qid)
    assert redis.data(0)["model_id"] == catalog.get_catalog().title_model.model
    assert redis.data(-1) == {"title": "Nấu phở bò nước trong"}
    assert await _title_in_db(session_factory, cid) == "Nấu phở bò nước trong"
    # C8 — EXPIRE sớm sau `start` VÀ sau event cuối (không có reaper cho khoá này).
    assert redis.expire_calls == [(title_stream_key(cid), settings.STREAM_TTL_S)] * 2


async def test_one_ledger_row_purpose_title_system_and_NO_zadd(
    session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    """DoD 2 — một dòng sổ `title`/`system`, `cost_usd > 0`, A7; quota KHÔNG bị trừ."""
    cid, qid = await _first_question(session_factory, user_a)
    redis = FakeRedis()

    await generate_title(_ctx(redis, FakeClient(_chunks(["Phở bò"]))), str(cid), str(qid))

    (row,) = await _title_rows(session_factory, user_a)
    assert row.key_source == KeySource.SYSTEM
    assert row.message_id == qid, "dong so truy nguoc duoc ve cau hoi da dat ten"
    assert row.model_id == catalog.get_catalog().title_model.model
    assert row.cost_usd > Decimal(0)
    assert row.price_snapshot["input_per_1m"] is not None
    assert redis.zset == {}, "luot dat ten KHONG duoc ZADD vao hai cua so quota"


async def test_call_uses_title_model_system_key_and_reasoning_of_catalog(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`title_model` của catalog (A3): model, `max_output`, mức suy luận; câu hỏi bị cắt trần."""
    monkeypatch.setattr(settings, "TITLE_INPUT_MAX_CHARS", 12)
    cid, qid = await _first_question(session_factory, user_a)
    client = FakeClient(_chunks(["Phở"]))

    await generate_title(_ctx(FakeRedis(), client), str(cid), str(qid))

    spec = catalog.get_catalog().title_model
    model = catalog.get_model(spec.model)
    assert model is not None and model.reasoning is not None and spec.reasoning is not None
    level = model.reasoning.option(spec.reasoning)
    assert level is not None
    assert client.call is not None
    assert client.call["model"] == (level.alias or model.id), "duong system: alias LiteLLM"
    assert client.call["max_tokens"] == spec.max_output
    assert client.call["tools"] is None
    assert client.call["extra"] == level.params
    assert client.call["extra"] is not level.params, "ban sao sau, khong phai dict cua catalog"
    (message,) = client.call["messages"]
    assert message["role"] == "user"
    assert QUESTION[:12] in message["content"]
    assert QUESTION[:13] not in message["content"], "TITLE_INPUT_MAX_CHARS phai cat cau hoi"


async def test_user_rename_while_model_is_slow_wins(
    session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    """DoD 4 — model giả chậm, người dùng đổi tên giữa chừng ⇒ tên của họ còn nguyên.

    `done` mang tên **của người dùng** (tiêu đề đang nằm trong DB), không phải
    chữ model vừa sinh — FE thay chữ đã chảy bằng đúng chuỗi ấy. Tiền vẫn ghi
    sổ: provider đã sinh xong và đã tính.
    """
    cid, qid = await _first_question(session_factory, user_a)
    redis = FakeRedis()
    gate = asyncio.Event()
    client = FakeClient(_chunks(["Tiêu ", "đề ", "của model"]), gate=gate)

    job = asyncio.create_task(generate_title(_ctx(redis, client), str(cid), str(qid)))
    await asyncio.wait_for(client.first_chunk_sent.wait(), timeout=5)
    async with session_factory() as session:
        assert await ConversationRepository(session).update_conversation(
            cid, user_id=user_a, changes={"title": "Tên tôi tự đặt"}
        )
        await session.commit()
    gate.set()
    await asyncio.wait_for(job, timeout=5)

    assert await _title_in_db(session_factory, cid) == "Tên tôi tự đặt"
    assert redis.kind[-1] == "done"
    assert redis.data(-1) == {"title": "Tên tôi tự đặt"}
    assert len(await _title_rows(session_factory, user_a)) == 1


async def test_title_set_before_job_runs_skips_model_entirely(
    session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    """Người dùng đặt tên trước khi job kịp chạy ⇒ không gọi model, không tốn xu nào."""
    cid, qid = await _first_question(session_factory, user_a, title="Đặt sẵn")
    redis = FakeRedis()
    client = FakeClient(_chunks(["không được dùng"]))

    await generate_title(_ctx(redis, client), str(cid), str(qid))

    assert client.call is None
    assert redis.kind == ["done"]
    assert redis.data(0) == {"title": "Đặt sẵn"}
    assert await _title_rows(session_factory, user_a) == []


async def test_model_raises_error_event_title_stays_null(
    session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    """DoD 7 — model giả ném ⇒ `error` có mã, `title` NULL, hàm KHÔNG ném (worker sống)."""
    cid, qid = await _first_question(session_factory, user_a)
    redis = FakeRedis()

    await generate_title(_ctx(redis, FailsImmediately([])), str(cid), str(qid))

    assert redis.kind == ["start", "error"]
    assert redis.data(-1)["code"] == "UPSTREAM_ERROR"
    assert await _title_in_db(session_factory, cid) is None
    assert await _title_rows(session_factory, user_a) == [], "chua sinh gi ⇒ khong ghi so"
    assert redis.expire_calls[-1] == (title_stream_key(cid), settings.STREAM_TTL_S)


async def test_upstream_cut_midway_still_bills_but_no_title(
    session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    """Đứt giữa chừng: chữ đã chảy nhưng tiêu đề KHÔNG ghi; phần đã sinh vẫn vào sổ (A7)."""
    cid, qid = await _first_question(session_factory, user_a)
    redis = FakeRedis()
    client = FakeClient([Chunk(kind="delta", text="Phở")], error=ConnectionError("dut"))

    await generate_title(_ctx(redis, client), str(cid), str(qid))

    assert redis.kind == ["start", "delta", "error"]
    assert redis.data(-1)["code"] == "UPSTREAM_ERROR"
    assert await _title_in_db(session_factory, cid) is None
    (row,) = await _title_rows(session_factory, user_a)
    assert row.key_source == KeySource.SYSTEM


async def test_empty_output_is_error_and_title_stays_null(
    session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    cid, qid = await _first_question(session_factory, user_a)
    redis = FakeRedis()

    await generate_title(_ctx(redis, FakeClient(_chunks(["  ", "\n"]))), str(cid), str(qid))

    assert redis.kind[-1] == "error"
    assert await _title_in_db(session_factory, cid) is None


async def test_missing_question_reports_own_code(
    session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    """Job mồ côi (câu hỏi không còn) — không gọi model, event cuối có mã."""
    cid, _ = await _first_question(session_factory, user_a)
    redis = FakeRedis()
    client = FakeClient(_chunks(["x"]))

    await generate_title(_ctx(redis, client), str(cid), str(uuid.uuid4()))

    assert client.call is None
    assert redis.kind == ["error"]
    assert redis.data(0)["code"] == "MESSAGE_NOT_FOUND"


async def test_cancelled_still_writes_terminal_event_then_reraises(
    session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    """arq cắt job (timeout/SIGTERM): event cuối vẫn ra (C19), rồi ném tiếp."""
    cid, qid = await _first_question(session_factory, user_a)
    redis = FakeRedis()
    client = FakeClient([Chunk(kind="delta", text="Ph")], error=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await generate_title(_ctx(redis, client), str(cid), str(qid))

    assert redis.kind[-1] == "error"
    assert redis.data(-1)["code"] == "WORKER_TIMEOUT"


# ───────────────────────────── làm sạch tiêu đề ─────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Nấu phở bò", "Nấu phở bò"),
        ('"Nấu phở bò"', "Nấu phở bò"),
        ("“Nấu phở bò”.", "Nấu phở bò"),
        ("**Nấu phở bò**", "Nấu phở bò"),
        ("\n\n  Nấu   phở\tbò  \nDòng thứ hai bị bỏ", "Nấu phở bò"),
        ("Hàm `map` trong Python", "Hàm `map` trong Python"),
        ("   \n  ", None),
        ('""', None),
    ],
)
def test_clean_title(raw: str, expected: str | None) -> None:
    assert clean_title(raw) == expected


def test_clean_title_cuts_at_the_same_limit_as_PATCH() -> None:
    """Tiêu đề tự đặt không bao giờ dài hơn thứ người dùng được phép tự gõ lại."""
    cleaned = clean_title("ơ" * (CONVERSATION_TITLE_MAX_CHARS + 50))
    assert cleaned is not None
    assert len(cleaned) == CONVERSATION_TITLE_MAX_CHARS
