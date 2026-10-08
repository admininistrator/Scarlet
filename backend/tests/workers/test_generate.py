"""T-1.6 — `app/workers/generate.py`: vòng đời một lượt sinh (§7.2 ③).

KH tham chiếu: §7.2, §7.4, §7.6, ADR-01, C5, C8, C9, C10, C19 · NQ-22, NQ-23.

Bốn trong sáu dòng DoD của task được kiểm ở đây dưới dạng tự động; hai dòng
còn lại (`redis-cli XLEN`/`TTL` trên đường chạy thật) nằm trong báo cáo task:

- **DoD 2** — bản ghi cuối cùng là `type=done`: `test_duong_chay_binh_thuong…`
- **DoD 3** — upstream đứt giữa chừng → bản ghi cuối là `error` **có mã**:
  `test_upstream_dut_giua_chung…` (C19)
- **DoD 5** — nối mọi `delta` **bằng byte-by-byte** với `messages.content`:
  `test_joined_deltas_equal_postgres_content`
- **DoD 6** — emoji + xuống dòng, `json.loads` đọc lại được (C10): cùng test trên

Cây message là cây **thật trong Postgres** (fixture của `tests/conftest.py`),
đi qua đúng `get_path` của T-1.2 và `context.build` của T-1.4. Chỉ hai thứ là
giả: Redis (một list ghi lại lời gọi) và provider (`FakeClient`). Giả Postgres ở
đây sẽ bỏ lọt đúng thứ đáng kiểm nhất — rằng `content` xuống đĩa **bằng** chuỗi
client dựng từ stream.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.db.session as db_session
import app.workers.generate as generate_mod
from app.config import catalog
from app.config.catalog import get_model
from app.config.settings import settings
from app.core import storage
from app.db.models import (
    Artifact,
    Conversation,
    CostConfidence,
    KeySource,
    Message,
    MessageRole,
    MessageStatus,
    UsageEvent,
)
from app.db.repositories import ArtifactRepository, ConversationRepository, MessageRepository
from app.db.repositories.attachments import AttachmentRepository
from app.llm import context as llm_context
from app.llm.adapters import openai_compat
from app.llm.adapters.system import SystemAdapter
from app.llm.client import Chunk, ToolCall, Usage
from app.quota.windows import parse_member, windows
from app.streaming.cancel import FINISH_REASON_CANCELLED, cancel_key
from app.streaming.producer import FIELD_DATA, FIELD_TYPE
from app.workers.generate import CANCEL_CHECK_EVERY_N_CHUNKS, CTX_LLM_CLIENT, generate

#: Model THẬT trong `config/model_catalog.json` — `generate` tra catalog bằng
#: `messages.model_id`, nên một id bịa sẽ đi thẳng vào nhánh `MODEL_UNKNOWN`.
MODEL_ID = "deepseek-flash"

#: Nhịp tim dùng trong test §7.6. **Không** đặt 0: từ B-122 nhịp tim là một
#: task riêng chạy `while True: await sleep(nhip)`, nên 0 biến nó thành vòng
#: nóng quay Postgres không nghỉ và test sẽ đỏ vì cạn pool chứ không vì cái nó
#: muốn đo. Đủ nhỏ để test vẫn nhanh, đủ lớn để một nhịp thật sự kịp ghi.
TEST_BEAT_S = 0.02


# ─────────────────────────── hai thứ giả ───────────────────────────


class FakeRedis:
    """Đủ `xadd`/`expire` (§7.2 ③), `exists` (cờ huỷ §7.5) và `zadd` (quota §10.3).

    Trả `bytes` như pool arq dựng (không decode). `cancel_flags` là tập khoá đang
    "tồn tại" — test đặt tay thay cho `POST /messages/{id}/cancel`.

    **`zadd` được thêm ở T-2.12, và việc thiếu nó từng làm cả bước ghi sổ hỏng
    IM LẶNG.** `_record_usage` nuốt mọi ngoại lệ có chủ ý (một lỗi kế toán
    không được biến câu trả lời đã sinh xong thành lỗi đỏ), nên một Redis giả
    không biết `zadd` sẽ cho `AttributeError` → bị nuốt → không dòng
    `usage_events` nào, mà **không test nào đỏ**. Đo thật: bỏ hai phương thức
    dưới đây ra thì 812 test vẫn xanh trong khi sổ cái rỗng hoàn toàn. Đó là lý
    do các phép kiểm của T-2.12 khẳng định thẳng vào hàng trong Postgres chứ
    không chỉ vào dòng log.
    """

    def __init__(self) -> None:
        self.records: list[dict[str, str]] = []
        self.expire_calls: list[tuple[str, int]] = []
        self.zset: dict[str, dict[str, float]] = {}
        self.cancel_flags: set[str] = set()
        self.exists_calls: list[str] = []
        self.exists_raises = False
        self.zadd_raises = False
        self._seq = 0

    async def zadd(self, name: str, mapping: dict[str, float]) -> int:
        if self.zadd_raises:
            raise ConnectionError("redis chet giua chung (gia lap)")
        self.zset.setdefault(name, {}).update(mapping)
        return len(mapping)

    async def exists(self, name: str) -> int:
        self.exists_calls.append(name)
        if self.exists_raises:
            raise ConnectionError("redis chet giua chung (gia lap)")
        return 1 if name in self.cancel_flags else 0

    async def xadd(self, name: str, fields: dict[str, Any]) -> bytes:
        self._seq += 1
        self.records.append({"__key__": name, **fields})
        return f"1725984000{self._seq:03d}-0".encode()

    async def expire(self, name: str, ttl: int) -> int:
        self.expire_calls.append((name, ttl))
        return 1

    # ── đọc lại cho tiện khẳng định ──

    @property
    def expire_stream(self) -> list[tuple[str, int]]:
        """Chỉ những `EXPIRE` đặt lên chính stream — phép kiểm C8 của DoD T-1.6.

        Từ T-2.12, cùng một client còn nhận hai `EXPIRE` nữa cho hai khoá
        `quota:*` (B-156), nên `expire_calls` trần không còn trả lời được câu
        "TTL của stream có được đặt đúng MỘT lần không".
        """
        return [item for item in self.expire_calls if item[0].startswith("stream:")]

    @property
    def kind(self) -> list[str]:
        return [b[FIELD_TYPE] for b in self.records]

    def data(self, i: int) -> Any:
        return json.loads(self.records[i][FIELD_DATA])

    @property
    def last(self) -> dict[str, Any]:
        """Bản ghi cuối cùng, đã parse — DoD dòng 2 và 3 nhìn vào đúng chỗ này."""
        return {"type": self.records[-1][FIELD_TYPE], "data": self.data(-1)}

    def text(self) -> str:
        return "".join(self.data(i)["t"] for i, t in enumerate(self.kind) if t == "delta")


class FakeClient:
    """`LLMClient` giả: phát sẵn một dãy `Chunk`, rồi (tuỳ chọn) nổ."""

    def __init__(self, chunks: list[Chunk], *, error: BaseException | None = None) -> None:
        self._chunks = chunks
        self._error = error
        self.call: dict[str, Any] | None = None

    async def stream(self, **kwargs: Any) -> AsyncIterator[Chunk]:
        self.call = kwargs
        return self._emit()

    async def _emit(self) -> AsyncIterator[Chunk]:
        for chunk in self._chunks:
            yield chunk
        if self._error is not None:
            raise self._error


class ClientFailsImmediately(FakeClient):
    """Nổ ngay tại `await stream(...)` — ca 401/400/429 của §9.1."""

    async def stream(self, **kwargs: Any) -> AsyncIterator[Chunk]:
        self.call = kwargs
        raise RuntimeError("401 Unauthorized")


# ─────────────────────────── hạ tầng test ───────────────────────────


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture(autouse=True)
def _bind_session_to_test_db(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """`session_scope()` của worker trỏ vào transaction của test.

    `app/db/session.py` tra `get_sessionmaker()` **ở thời điểm gọi**, nên vá
    một tên là đủ cho cả `session_scope` lẫn `get_session`. Nhà máy của
    `conftest.py` dùng `join_transaction_mode="create_savepoint"`, nên
    `commit()` thật trong worker chỉ giải phóng savepoint — rollback cuối test
    vẫn dọn sạch, mà đường ghi vẫn là đường ghi thật.
    """
    monkeypatch.setattr(db_session, "get_sessionmaker", lambda: session_factory)


def _ctx(fake_redis: FakeRedis, client: FakeClient) -> dict[str, Any]:
    return {"redis": fake_redis, "job_id": "test-job", CTX_LLM_CLIENT: client}


async def _minimal_tree(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    model_id: str | None = MODEL_ID,
    status: MessageStatus = MessageStatus.QUEUED,
    reasoning_effort: str | None = None,
) -> Message:
    """Một câu hỏi đã xong + một message assistant `queued` — đúng §7.2 ①."""
    repo = MessageRepository(session)
    conversation: Conversation = await ConversationRepository(session).create_conversation(
        user_id=user_id
    )
    question_msg = await repo.create_message(
        conversation_id=conversation.id,
        user_id=user_id,
        role=MessageRole.USER,
        content="Mùa thu Hà Nội thế nào?",
        status=MessageStatus.COMPLETED,
    )
    answer = await repo.create_message(
        conversation_id=conversation.id,
        user_id=user_id,
        role=MessageRole.ASSISTANT,
        parent_id=question_msg.id,
        status=status,
        model_id=model_id,
        reasoning_effort=reasoning_effort,
    )
    await session.commit()
    return answer


async def _reload(session_factory: async_sessionmaker[AsyncSession], mid: uuid.UUID) -> Message:
    """Đọc bằng session MỚI: repository ghi bằng `UPDATE` thẳng, nên session cũ
    có thể còn giữ bản trong identity map (xem `conftest.py`)."""
    async with session_factory() as s:
        return (await s.execute(select(Message).where(Message.id == mid))).scalar_one()


def _normal_chunks(text: list[str]) -> list[Chunk]:
    usage = Usage(prompt_tokens=214, completion_tokens=len(text), total_tokens=214 + len(text))
    return [
        *(Chunk(kind="delta", text=part) for part in text),
        Chunk(kind="usage", usage=usage),
        Chunk(kind="done", finish_reason="stop", usage=usage),
    ]


# ───────────────────────────── đường chạy ─────────────────────────────


async def test_normal_path_ends_with_done(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """DoD dòng 2: bản ghi cuối cùng có `type=done`. Và đúng thứ tự §7.2 ③."""
    message = await _minimal_tree(session, user_a)
    client = FakeClient(_normal_chunks(["Hà Nội ", "mùa thu ", "đẹp."]))

    await generate(_ctx(fake_redis, client), str(message.id))

    assert fake_redis.kind == ["start", "delta", "delta", "delta", "usage", "done"]
    assert fake_redis.last["type"] == "done"
    # `cost_usd` nằm TRONG khối `usage` (§7.4, B-78) và do meter của T-2.12
    # tính; con số cụ thể được kiểm ở `test_cost_usd_on_done_event_matches_ledger_row`.
    data = fake_redis.last["data"]
    assert data["finish_reason"] == "stop"
    assert data["usage"]["in"] == 214
    assert data["usage"]["out"] == 3
    assert data["usage"]["cost_usd"] > 0
    # C8 — TTL đặt sau event kết thúc, đúng một lần.
    assert fake_redis.expire_stream == [(f"stream:{message.id}", settings.STREAM_TTL_S)]

    reloaded = await _reload(session_factory, message.id)
    assert reloaded.status is MessageStatus.COMPLETED
    assert reloaded.finish_reason == "stop"
    assert reloaded.prompt_tokens == 214
    assert reloaded.completion_tokens == 3
    assert reloaded.error_code is None


async def test_joined_deltas_equal_postgres_content(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """DoD dòng 5 + 6: so **byte-by-byte**, với emoji và xuống dòng (C9, C10)."""
    pieces = ["Chào 🎉\n", 'bạn — dấu " và \\', "\ncuối 😀", "…"]
    message = await _minimal_tree(session, user_a)

    await generate(_ctx(fake_redis, FakeClient(_normal_chunks(pieces))), str(message.id))

    expected = "".join(pieces)
    reloaded = await _reload(session_factory, message.id)
    assert reloaded.content == expected
    assert reloaded.content.encode("utf-8") == expected.encode("utf-8")
    # Nối lại từ CHÍNH các bản ghi trong stream, sau khi đi qua json.dumps.
    assert fake_redis.text() == expected
    assert all("\n" not in b[FIELD_DATA] for b in fake_redis.records)


async def test_reasoning_does_not_leak_into_content(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """B-33: reasoning là `event` riêng, cột riêng, và KHÔNG vào `content`."""
    message = await _minimal_tree(session, user_a)
    chunks = [
        Chunk(kind="reasoning", text="để tôi nghĩ…"),
        Chunk(kind="delta", text="Xin chào"),
        Chunk(kind="done", finish_reason="stop"),
    ]

    await generate(_ctx(fake_redis, FakeClient(chunks)), str(message.id))

    assert fake_redis.kind == ["start", "reasoning", "delta", "done"]
    reloaded = await _reload(session_factory, message.id)
    assert reloaded.content == "Xin chào"
    assert reloaded.reasoning == "để tôi nghĩ…"


async def test_tool_calls_written_in_openai_wire_shape(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """NQ-22/B-68: cột `tool_calls` phải là thứ `context._to_wire` đọc lại được.

    Không so với một dict chép tay: phép kiểm thật là **bên đọc nhận ra bên
    ghi**, vì đó chính là chỗ hai task lệch nhau được.
    """
    message = await _minimal_tree(session, user_a)
    call = ToolCall(call_id="call_abc", name="web_search", arguments='{"query": "mùa thu"}')
    chunks = [
        Chunk(kind="delta", text="Để tôi tìm."),
        Chunk(kind="tool_call", tool_call=call),
        Chunk(kind="done", finish_reason="tool_calls"),
    ]

    await generate(_ctx(fake_redis, FakeClient(chunks)), str(message.id))

    reloaded = await _reload(session_factory, message.id)
    assert reloaded.tool_calls == [
        {
            "id": "call_abc",
            "type": "function",
            "function": {"name": "web_search", "arguments": '{"query": "mùa thu"}'},
        }
    ]
    # Bên đọc của lượt SAU nhận ra đúng `id` này (C15 `_close_block` dựa vào nó).
    assert llm_context._declared_call_ids({"tool_calls": reloaded.tool_calls}) == {"call_abc"}

    # Trên dây thì `args` là object (§7.4), còn chuỗi thô ở lại trong DB.
    events = fake_redis.data(fake_redis.kind.index("tool_call"))
    assert events == {"call_id": "call_abc", "name": "web_search", "args": {"query": "mùa thu"}}


# ─────────────────────── các đường thoát bất thường (C19) ───────────────────────


async def test_upstream_cut_midway_ends_with_coded_error(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """DoD dòng 3 + C19: đứt giữa chừng **không** được im lặng, và giữ phần chữ."""
    message = await _minimal_tree(session, user_a)
    client = FakeClient(
        [Chunk(kind="delta", text="Hà Nội "), Chunk(kind="delta", text="mùa thu")],
        error=ConnectionResetError("peer closed"),
    )

    await generate(_ctx(fake_redis, client), str(message.id))

    assert fake_redis.last["type"] == "error"
    assert fake_redis.last["data"]["code"] == "UPSTREAM_ERROR"
    assert "ConnectionResetError" in fake_redis.last["data"]["message"]
    # C8 vẫn phải chạy trên đường lỗi — stream lỗi cũng chiếm RAM.
    assert fake_redis.expire_stream == [(f"stream:{message.id}", settings.STREAM_TTL_S)]

    reloaded = await _reload(session_factory, message.id)
    assert reloaded.status is MessageStatus.FAILED
    assert reloaded.error_code == "UPSTREAM_ERROR"
    assert reloaded.content == "Hà Nội mùa thu", "phần đã sinh phải được giữ lại"


async def test_error_right_at_await_stream_still_has_terminal_event(
    session: AsyncSession,
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """401/400/429 nổ tại `await` (điểm 1 `client.py`) — vẫn phải có `error`."""
    message = await _minimal_tree(session, user_a)

    await generate(_ctx(fake_redis, ClientFailsImmediately([])), str(message.id))

    assert fake_redis.kind == ["start", "error"]
    assert fake_redis.last["data"]["code"] == "UPSTREAM_ERROR"


async def test_cancelled_still_writes_error_then_reraises(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """arq cắt job quá `GENERATE_TIMEOUT_S`: client không được treo, mà
    `CancelledError` cũng không được nuốt."""
    message = await _minimal_tree(session, user_a)
    client = FakeClient([Chunk(kind="delta", text="một nửa")], error=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await generate(_ctx(fake_redis, client), str(message.id))

    assert fake_redis.last["type"] == "error"
    assert fake_redis.last["data"]["code"] == "WORKER_TIMEOUT"
    reloaded = await _reload(session_factory, message.id)
    assert reloaded.status is MessageStatus.FAILED
    assert reloaded.content == "một nửa"


async def test_missing_message_reports_own_code(user_a: uuid.UUID, fake_redis: FakeRedis) -> None:
    """Job mồ côi: không có `start`, nhưng vẫn có đúng một event kết thúc."""
    await generate(_ctx(fake_redis, FakeClient([])), str(uuid.uuid4()))

    assert fake_redis.kind == ["error"]
    assert fake_redis.last["data"]["code"] == "MESSAGE_NOT_FOUND"


async def test_model_id_not_in_catalog(
    session: AsyncSession, user_a: uuid.UUID, fake_redis: FakeRedis
) -> None:
    message = await _minimal_tree(session, user_a, model_id="model-da-bi-xoa")

    await generate(_ctx(fake_redis, FakeClient([])), str(message.id))

    assert fake_redis.kind == ["error"]
    assert fake_redis.last["data"]["code"] == "MODEL_UNKNOWN"


async def test_message_no_longer_queued_skips_turn(
    session: AsyncSession, user_a: uuid.UUID, fake_redis: FakeRedis
) -> None:
    """B-72: arq giao lại một job đã chạy (SIGKILL) — worker thứ hai phải bỏ.

    Sinh tiếp là gọi model lần hai cho cùng một câu hỏi, tức hoá đơn lần hai.
    """
    message = await _minimal_tree(session, user_a, status=MessageStatus.STREAMING)

    await generate(_ctx(fake_redis, FakeClient(_normal_chunks(["x"]))), str(message.id))

    assert fake_redis.kind == ["error"]
    assert fake_redis.last["data"]["code"] == "MESSAGE_NOT_FOUND"


async def test_postgres_write_failure_reports_persist_failed(
    session: AsyncSession,
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chữ đã tới người dùng nhưng lịch sử thì không — nói thẳng, không gửi `done`."""
    message = await _minimal_tree(session, user_a)

    async def no(*_a: Any, **_k: Any) -> bool:
        raise RuntimeError("deadlock detected")

    monkeypatch.setattr(MessageRepository, "finish_generation", no)

    await generate(_ctx(fake_redis, FakeClient(_normal_chunks(["a"]))), str(message.id))

    assert fake_redis.last["type"] == "error"
    assert fake_redis.last["data"]["code"] == "PERSIST_FAILED"


# ───────────────────────────── §7.6 heartbeat ─────────────────────────────


def _serialized_heartbeat(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
    mid: uuid.UUID,
) -> Any:
    """Đọc `heartbeat_at` mà không đua với task nhịp tim trên MỘT kết nối test.

    Hai session (lần đọc của test + `_write_heartbeat`) dùng chung kết nối với
    `create_savepoint`; xen nhau giữa chừng là `savepoint … does not exist`
    (đo T-6.7a: đỏ 3/3 khi gom `tests/workers` với một tệp `tests/api`). Khoá
    chỉ tuần tự hoá hai bên — hàm ghi nhịp THẬT vẫn chạy theo nhịp của nó.
    """
    lock = asyncio.Lock()
    real_write = generate_mod._write_heartbeat

    async def locked_write(message_id: uuid.UUID) -> None:
        async with lock:
            await real_write(message_id)

    monkeypatch.setattr(generate_mod, "_write_heartbeat", locked_write)

    async def read_heartbeat() -> Any:
        async with lock:
            return (await _reload(session_factory, mid)).heartbeat_at

    return read_heartbeat


async def test_writes_heartbeat_while_generating(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§7.6: reaper so `heartbeat_at` với `now()`, nên nó phải NHÍCH trong lúc sinh."""
    message = await _minimal_tree(session, user_a)
    monkeypatch.setattr(settings, "WORKER_HEARTBEAT_S", TEST_BEAT_S)

    read_heartbeat = _serialized_heartbeat(monkeypatch, session_factory, message.id)

    mark: list[Any] = []

    class ClientWithTimestamps(FakeClient):
        async def _emit(self) -> AsyncIterator[Chunk]:
            for chunk in _normal_chunks(["a", "b"]):
                yield chunk
                await asyncio.sleep(TEST_BEAT_S * 3)
                mark.append(await read_heartbeat())

    await generate(_ctx(fake_redis, ClientWithTimestamps([])), str(message.id))

    assert all(m is not None for m in mark), "heartbeat_at phải có giá trị ngay từ mark_streaming"
    assert mark[-1] > mark[0], f"heartbeat_at không nhích: {mark}"


async def test_heartbeat_beats_even_before_model_returns_ANY_chunk(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B-122 — quãng TTFT là quãng bản cũ để trống, và thường là quãng DÀI NHẤT.

    Bản trước `_Nhip` chỉ được hỏi **bên trong** `async for chunk in stream`,
    nên từ `mark_streaming` tới chunk đầu tiên không một nhịp nào được ghi.
    Hệ quả: `REAPER_STALE_S` kiêm luôn vai "TTFT tối đa trước khi reaper giết
    một lượt sinh còn sống" — với `nr-gemini-flash` đo được TTFT p95 43.7 s
    (B-103) và `LLM_REQUEST_TIMEOUT_S = 600 s`, đó là một quả mìn hẹn giờ.

    Test dựng đúng hình dạng đó: model "nghĩ" một quãng **trước** chunk đầu.
    Chạy test này trên bản cũ thì hai mốc bằng nhau và nó đỏ.
    """
    message = await _minimal_tree(session, user_a)
    monkeypatch.setattr(settings, "WORKER_HEARTBEAT_S", TEST_BEAT_S)

    read_heartbeat = _serialized_heartbeat(monkeypatch, session_factory, message.id)

    mark: list[Any] = []

    class SlowClient(FakeClient):
        async def _emit(self) -> AsyncIterator[Chunk]:
            mark.append(await read_heartbeat())  # ngay sau `mark_streaming`
            await asyncio.sleep(TEST_BEAT_S * 4)  # model đang "nghĩ"
            mark.append(await read_heartbeat())  # VẪN chưa có chunk nào ra
            for chunk in _normal_chunks(["a"]):
                yield chunk

    await generate(_ctx(fake_redis, SlowClient([])), str(message.id))

    assert all(m is not None for m in mark)
    assert mark[1] > mark[0], (
        f"nhịp tim không đập trong lúc chờ chunk đầu — REAPER_STALE_S vẫn đang "
        f"kiêm vai 'TTFT tối đa' (B-122): {mark}"
    )


async def test_heartbeat_does_not_outlive_generation(
    session: AsyncSession,
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task nhịp tim phải bị huỷ ở `finally`, không rò ra ngoài `generate`.

    Một task rò sẽ ghi `heartbeat_at` cho một message đã khép. Hôm nay vô hại
    vì `touch_heartbeat` chỉ khớp `status='streaming'`, nhưng nó là lớp phòng
    thủ thứ hai — lớp thứ nhất là không rò. Đếm task theo TÊN chứ không theo
    tác dụng phụ, vì tác dụng phụ đang bị lớp thứ hai che mất.
    """
    message = await _minimal_tree(session, user_a)
    monkeypatch.setattr(settings, "WORKER_HEARTBEAT_S", TEST_BEAT_S)

    await generate(_ctx(fake_redis, FakeClient(_normal_chunks(["a"]))), str(message.id))

    alive = [t for t in asyncio.all_tasks() if t.get_name().startswith("nhip-tim:")]
    assert alive == [], f"task nhịp tim còn sống sau khi generate xong: {alive}"


async def test_model_params_come_from_catalog_and_settings(
    session: AsyncSession, user_a: uuid.UUID, fake_redis: FakeRedis
) -> None:
    """A3: `max_tokens` từ catalog, `temperature` từ `.env` — không hằng trong `.py`."""
    message = await _minimal_tree(session, user_a)
    client = FakeClient(_normal_chunks(["x"]))

    await generate(_ctx(fake_redis, client), str(message.id))

    assert client.call is not None
    assert client.call["model"] == MODEL_ID
    assert client.call["max_tokens"] == 8192  # `max_output` của deepseek-flash
    assert client.call["temperature"] == settings.LLM_TEMPERATURE
    assert client.call["tools"] is None, "Phase 1 chưa có tool registry (C18)"
    # A2/C11: ngữ cảnh là ĐƯỜNG ĐI, và message `queued` đang sinh không có mặt.
    roles = [m["role"] for m in client.call["messages"]]
    assert roles == ["system", "user"]


# ═════════════════════ §7.5 — huỷ giữa chừng (T-1.9) ═════════════════════


def _long_chunks(count: int) -> list[Chunk]:
    """`count` mẩu `delta`, rồi `usage` + `done` như một lượt sinh bình thường.

    Dãy này **cố ý** kết thúc đầy đủ: nếu vòng lặp không dừng vì cờ huỷ, test sẽ
    thấy `finish_reason='stop'` và `status='completed'` — tức phép kiểm hỏng
    theo hướng nhìn thấy được, chứ không phải treo.
    """
    text = [f"m{i} " for i in range(count)]
    return _normal_chunks(text)


async def test_stops_loop_on_cancel_flag(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """§7.5: thấy cờ ⇒ dừng, `finish_reason='cancelled'`, `status='cancelled'`.

    Huỷ **không** phải lỗi: `error_code` để NULL và event cuối là `done`, chứ
    không phải `error`. FE bật nút Retry theo `error`, mà một câu trả lời người
    dùng chủ động dừng thì không có gì để thử lại.
    """
    message = await _minimal_tree(session, user_a)
    fake_redis.cancel_flags.add(cancel_key(message.id))
    client = FakeClient(_long_chunks(40))

    await generate(_ctx(fake_redis, client), str(message.id))

    assert fake_redis.last["type"] == "done"
    assert fake_redis.last["data"]["finish_reason"] == FINISH_REASON_CANCELLED

    reloaded = await _reload(session_factory, message.id)
    assert reloaded.status is MessageStatus.CANCELLED
    assert reloaded.finish_reason == FINISH_REASON_CANCELLED
    assert reloaded.error_code is None


async def test_stops_exactly_after_N_chunks_not_early_not_late(
    session: AsyncSession,
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """Đếm **chính xác** `CANCEL_CHECK_EVERY_N_CHUNKS`: đó là ngân sách của "≤ 500 ms".

    Kiểm mỗi chunk thì tốn một `EXISTS` cho mỗi mẩu chữ; kiểm thưa hơn thì nút
    Dừng ăn muộn. Test khoá con số lại để một lần "tối ưu" sau này phải đi qua
    đây.
    """
    message = await _minimal_tree(session, user_a)
    fake_redis.cancel_flags.add(cancel_key(message.id))

    await generate(_ctx(fake_redis, FakeClient(_long_chunks(100))), str(message.id))

    assert fake_redis.text() == "".join(f"m{i} " for i in range(CANCEL_CHECK_EVERY_N_CHUNKS))
    assert len(fake_redis.exists_calls) == 1, "thấy cờ ở lần hỏi đầu tiên thì thôi hỏi nữa"


async def test_still_saves_generated_part_equal_to_wire_text(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """DoD dòng 2: `messages.content` chứa **đúng** phần đã sinh — không rỗng,
    không đầy đủ, và bằng byte-by-byte với chuỗi client dựng từ stream."""
    message = await _minimal_tree(session, user_a)
    fake_redis.cancel_flags.add(cancel_key(message.id))

    await generate(_ctx(fake_redis, FakeClient(_long_chunks(100))), str(message.id))

    reloaded = await _reload(session_factory, message.id)
    full = "".join(f"m{i} " for i in range(100))
    assert reloaded.content == fake_redis.text()
    assert reloaded.content, "không rỗng"
    assert reloaded.content != full, "không đầy đủ"
    assert full.startswith(reloaded.content), "là TIỀN TỐ của câu trả lời đầy đủ"


async def test_no_flag_does_not_stop_and_still_checks_right_key(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """Không ai bấm Dừng ⇒ lượt sinh chạy hết, và khoá được hỏi đúng tên.

    Phép so `exists_calls` là chỗ bắt lỗi gõ lệch tiền tố: nếu worker hỏi
    `cancel-{id}` còn API ghi `cancel:{id}` thì mọi test huỷ ở trên vẫn xanh
    (chúng tự đặt khoá bằng `cancel_key`), chỉ đường chạy thật là hỏng.
    """
    message = await _minimal_tree(session, user_a)
    so_chunk_delta = 40

    await generate(_ctx(fake_redis, FakeClient(_long_chunks(so_chunk_delta))), str(message.id))

    reloaded = await _reload(session_factory, message.id)
    assert reloaded.status is MessageStatus.COMPLETED
    assert reloaded.finish_reason == "stop"
    # `usage` + `done` là hai chunk nữa sau `delta`, nên tổng là 42.
    assert len(fake_redis.exists_calls) == (so_chunk_delta + 2) // CANCEL_CHECK_EVERY_N_CHUNKS
    assert set(fake_redis.exists_calls) == {cancel_key(message.id)}


async def test_unreadable_flag_keeps_generating(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """`EXISTS` nổ ⇒ ghi cảnh báo rồi đi tiếp, KHÔNG đội lốt `UPSTREAM_ERROR`.

    Mất một lần hỏi là nút Dừng ăn muộn vài chunk. Để ngoại lệ thoát ra thì
    người dùng đọc được "provider lỗi" cho một sự cố nằm hoàn toàn ở phía mình.
    """
    message = await _minimal_tree(session, user_a)
    fake_redis.exists_raises = True

    await generate(_ctx(fake_redis, FakeClient(_long_chunks(40))), str(message.id))

    assert fake_redis.last["type"] == "done"
    reloaded = await _reload(session_factory, message.id)
    assert reloaded.status is MessageStatus.COMPLETED


async def test_cancel_leaves_usage_NULL_not_made_up(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """Provider chỉ gửi `usage` ở chunk CUỐI, nên huỷ = không có usage thật.

    Hai cột để NULL chứ không điền một con số tự đếm, và **T-2.12 KHÔNG đổi
    điều đó** (NQ-26): NQ-23 dựa vào chỗ khác nhau giữa "provider không báo" và
    "báo và bằng 0", còn `messages` không có cột nào đánh dấu một con số ước
    tính. Số tự đếm cho phần đã huỷ đi vào `usage_events` — nơi duy nhất có
    `cost_confidence` (B-94) — xem `test_huy_van_ghi_mot_dong_usage_events`.
    """
    message = await _minimal_tree(session, user_a)
    fake_redis.cancel_flags.add(cancel_key(message.id))

    await generate(_ctx(fake_redis, FakeClient(_long_chunks(100))), str(message.id))

    # Khối `usage` trên dây mang ĐÚNG MỘT khoá: `cost_usd` của meter. Hai khoá
    # token **vắng mặt**, và "khoá vắng mặt nghĩa là provider KHÔNG báo" (NQ-23)
    # — điền 0 vào đó mới là bịa. Xem docstring `DoneEvent`.
    usage_on_wire = fake_redis.last["data"]["usage"]
    assert set(usage_on_wire) == {"cost_usd"}
    reloaded = await _reload(session_factory, message.id)
    assert reloaded.prompt_tokens is None
    assert reloaded.completion_tokens is None


async def test_cancel_logs_one_usage_line(
    session: AsyncSession,
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """DoD dòng 3 của T-1.9: "ở phase này kiểm bằng log" — dòng log ấy phải TỒN TẠI.

    Từ T-2.12 nó không còn là nguồn duy nhất (sổ cái mới là), nhưng vẫn giữ: nó
    in `usage` mà provider **không** báo, ngay cạnh dòng `ghi so` in con số
    meter đã đếm thay — hai con số đứng cạnh nhau là cách đọc log thấy được
    đường lùi C40 có chạy hay không.
    """
    message = await _minimal_tree(session, user_a)
    fake_redis.cancel_flags.add(cancel_key(message.id))

    with caplog.at_level("INFO", logger="app.workers.generate"):
        await generate(_ctx(fake_redis, FakeClient(_long_chunks(100))), str(message.id))

    lines = [r.getMessage() for r in caplog.records if "HUY" in r.getMessage()]
    assert len(lines) == 1, "đúng một dòng, không phải không dòng nào và không phải hai"
    assert str(message.id) in lines[0]
    assert "usage" in lines[0]


async def test_cancel_still_EXPIREs_stream(
    session: AsyncSession,
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """C8 áp cho cả ba ngả: stream của một lượt bị huỷ cũng chiếm RAM."""
    message = await _minimal_tree(session, user_a)
    fake_redis.cancel_flags.add(cancel_key(message.id))

    await generate(_ctx(fake_redis, FakeClient(_long_chunks(100))), str(message.id))

    assert fake_redis.expire_stream == [(f"stream:{message.id}", settings.STREAM_TTL_S)]


async def test_cancelled_part_still_enters_next_turn_context(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """`USABLE_STATUSES` nhận `cancelled` — người dùng đã nhìn thấy phần chữ đó.

    Kiểm qua chính `context.build` chứ không đọc hằng số: nếu một ngày ai đó
    bỏ `cancelled` khỏi `USABLE_STATUSES` thì lượt sau sẽ thấy một hội thoại
    thiếu mất câu trả lời mà người dùng đang nhìn trên màn hình.
    """
    message = await _minimal_tree(session, user_a)
    fake_redis.cancel_flags.add(cancel_key(message.id))
    await generate(_ctx(fake_redis, FakeClient(_long_chunks(100))), str(message.id))

    reloaded = await _reload(session_factory, message.id)
    model_meta = get_model(MODEL_ID)
    assert model_meta is not None
    async with session_factory() as s:
        wire = await llm_context.build(s, reloaded.id, model_meta, user_id=user_a)

    assert any(m["role"] == "assistant" and m.get("content") == reloaded.content for m in wire)


# ──────────────────── ghi sổ ⑥.5 — §10.2 vế SAU (T-2.12) ────────────────────
#
# `tests/quota/test_meter.py` kiểm phép nhân tiền và hình dạng dòng sổ. Ở đây
# chỉ kiểm một câu: **ngả khép sổ nào có ghi, ngả nào không** — thứ chỉ nhìn
# thấy được từ trong `generate()`, và thứ mà Cạm bẫy của task gọi là quota rò.


async def _read_ledger(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> list[UsageEvent]:
    async with session_factory() as s:
        rows = await s.execute(select(UsageEvent).where(UsageEvent.user_id == user_id))
        return list(rows.scalars().all())


def _zset_total(fake_redis: FakeRedis, user_id: uuid.UUID) -> Decimal:
    seats = fake_redis.zset[windows()[0].key(user_id)]
    return sum((parse_member(m) or Decimal(0) for m in seats), Decimal(0))


async def test_one_finished_chat_turn_yields_one_usage_events_row(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """DoD dòng 1, đo từ đầu vào thật của worker chứ không từ `record_usage`."""
    message = await _minimal_tree(session, user_a)

    await generate(_ctx(fake_redis, FakeClient(_normal_chunks(["a", "b"]))), str(message.id))

    so = await _read_ledger(session_factory, user_a)
    assert len(so) == 1
    assert so[0].message_id == message.id
    assert so[0].model_id == MODEL_ID
    assert so[0].cost_usd > 0
    assert so[0].cost_confidence == CostConfidence.EXACT
    assert so[0].prompt_tokens == 214
    assert so[0].completion_tokens == 2
    assert so[0].price_snapshot["input_per_1m"] is not None


async def test_cost_usd_on_done_event_matches_ledger_row(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """B-78 + §7.4: `done` mang `cost_usd` NẰM TRONG khối `usage`."""
    message = await _minimal_tree(session, user_a)

    await generate(_ctx(fake_redis, FakeClient(_normal_chunks(["a", "b"]))), str(message.id))

    so = await _read_ledger(session_factory, user_a)
    usage_on_wire = fake_redis.last["data"]["usage"]
    assert usage_on_wire["cost_usd"] == float(so[0].cost_usd)
    assert usage_on_wire["in"] == 214
    assert usage_on_wire["out"] == 2


async def test_after_ledger_write_both_quota_windows_grow(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """DoD dòng 5 nhìn từ worker: SUM Postgres = tổng ZSET, ở **cả hai** cửa sổ."""
    message = await _minimal_tree(session, user_a)

    await generate(_ctx(fake_redis, FakeClient(_normal_chunks(["a", "b"]))), str(message.id))

    so = await _read_ledger(session_factory, user_a)
    postgres_total = sum((e.cost_usd for e in so), Decimal(0))
    for window in windows():
        seats = fake_redis.zset[window.key(user_a)]
        redis_total = sum((parse_member(m) or Decimal(0) for m in seats), Decimal(0))
        assert abs(postgres_total - redis_total) <= Decimal("0.000001")


async def test_cancel_still_writes_one_usage_events_row_for_generated_part(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """DoD dòng 4 — và đây là chỗ B-94 được đóng.

    `messages.completion_tokens` vẫn NULL (NQ-23/NQ-26), nhưng sổ cái thì
    **không** rỗng: `usage_events.completion_tokens` mang phần đã sinh do
    `tiktoken` đếm, kèm `cost_confidence='low'` để không ai nhầm nó với một
    con số provider gửi về.
    """
    message = await _minimal_tree(session, user_a)
    fake_redis.cancel_flags.add(cancel_key(message.id))

    await generate(_ctx(fake_redis, FakeClient(_long_chunks(100))), str(message.id))

    reloaded = await _reload(session_factory, message.id)
    assert reloaded.status is MessageStatus.CANCELLED
    assert reloaded.completion_tokens is None  # NQ-26 — không đổi

    so = await _read_ledger(session_factory, user_a)
    assert len(so) == 1
    assert so[0].cost_confidence == CostConfidence.LOW
    assert so[0].completion_tokens > 0
    # Nửa prompt cũng phải được đếm, không chỉ nửa output: nó là nửa ĐẮT của
    # một hội thoại dài, và nó chỉ đếm được nếu worker thật sự trao ngữ cảnh
    # đã gửi cho meter (`_Result.sent`). Phép kiểm ngược: đặt `sent = []` thì
    # con số này về 0 trong khi mọi khẳng định khác vẫn xanh.
    assert so[0].prompt_tokens > 0
    assert so[0].cost_usd > 0
    assert _zset_total(fake_redis, user_a) == so[0].cost_usd


async def test_upstream_cut_midway_still_bills_part_run(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """Ngả `failed` của "Việc cần làm": chữ đã chảy thì provider đã tính tiền."""
    message = await _minimal_tree(session, user_a)
    client = FakeClient(
        [Chunk(kind="delta", text="Ha Noi mua thu ")], error=RuntimeError("upstream dut")
    )

    await generate(_ctx(fake_redis, client), str(message.id))

    assert fake_redis.last["type"] == "error"
    so = await _read_ledger(session_factory, user_a)
    assert len(so) == 1
    assert so[0].cost_confidence == CostConfidence.LOW
    assert so[0].completion_tokens > 0
    assert so[0].prompt_tokens > 0


async def test_dying_BEFORE_model_call_writes_NO_row(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """Ngả thứ tư — `401` nổ ngay tại `await stream(...)`, chưa sinh một chữ nào.

    Một dòng sổ 0 đồng ở đây là rác, và rác làm hỏng đúng phép đếm mà DoD dòng
    1 đo. Phép kiểm ngược: bỏ `billable` đi thì test này đỏ.
    """
    message = await _minimal_tree(session, user_a)

    await generate(_ctx(fake_redis, ClientFailsImmediately([])), str(message.id))

    assert fake_redis.last["type"] == "error"
    assert await _read_ledger(session_factory, user_a) == []
    assert fake_redis.zset == {}


async def test_model_not_in_catalog_writes_no_row(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """Cùng họ test trên: chết ở `_prepare` thì chưa có model để tính giá."""
    message = await _minimal_tree(session, user_a, model_id="khong-ton-tai")

    await generate(_ctx(fake_redis, FakeClient([])), str(message.id))

    assert fake_redis.last["data"]["code"] == "MODEL_UNKNOWN"
    assert await _read_ledger(session_factory, user_a) == []


async def test_ledger_write_failure_still_done_not_user_error(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Khác hẳn `PERSIST_FAILED`: mất một khoản trong sổ khác mất câu trả lời.

    Người dùng đã đọc xong câu trả lời và không có gì để họ làm khác đi. Sự cố
    kế toán khai trong log, không khai trên màn hình họ. `cost_usd` khi đó
    **vắng mặt** trên dây chứ không bằng 0.
    """
    message = await _minimal_tree(session, user_a)
    fake_redis.zadd_raises = True

    with caplog.at_level("ERROR", logger="app.workers.generate"):
        await generate(_ctx(fake_redis, FakeClient(_normal_chunks(["a"]))), str(message.id))

    assert fake_redis.last["type"] == "done"
    assert "cost_usd" not in fake_redis.last["data"]["usage"]
    assert await _read_ledger(session_factory, user_a) == []
    assert any("usage_events" in r.getMessage() for r in caplog.records)
    # Câu trả lời vẫn xuống đĩa nguyên vẹn — đó là điều phải giữ bằng mọi giá.
    assert (await _reload(session_factory, message.id)).status is MessageStatus.COMPLETED


async def test_price_taken_at_CALL_time_not_ledger_time(
    session: AsyncSession,
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A7 + B-35: một lượt sinh dài có thể vượt qua ranh giới khung giờ.

    `deepseek-flash` đổi giá lúc 17:00 giờ Việt Nam. Bắt đầu 16:58 và kết thúc
    17:08 thì giá phải là giá 16:58 — nếu không thì hai lượt sinh giống hệt
    nhau sẽ có hai hoá đơn khác nhau tuỳ vào việc model trả lời nhanh hay chậm.
    """
    message = await _minimal_tree(session, user_a)
    queried: list[datetime | None] = []
    original = catalog.Catalog.effective_pricing

    def record(self: catalog.Catalog, model_id: str, at: datetime | None = None) -> Any:
        queried.append(at)
        return original(self, model_id, at)

    monkeypatch.setattr(catalog.Catalog, "effective_pricing", record)
    before = datetime.now(UTC)
    await generate(_ctx(fake_redis, FakeClient(_normal_chunks(["a"]))), str(message.id))
    after = datetime.now(UTC)

    assert queried, "meter phai hoi bang gia dung mot lan"
    mark = queried[-1]
    assert mark is not None, "None = 'bay gio', tuc bo mat moc gia cua A7"
    assert before <= mark <= after


# ══════════ T-2.15 — đường BYOK: adapter nào, tên model nào, quota nào ══════════
#
# Ba câu chỉ nhìn thấy được từ **trong** `generate()`:
#
# 1. có khoá ⇒ worker dựng `ByokAdapter` và **không** dùng client dùng chung
#    trong `ctx` (dùng nhầm nó là gọi model bằng tiền của người vận hành, trong
#    khi sổ sách ghi `byok` — tức mất tiền mà không ai thấy);
# 2. dòng `usage_events` mang `key_source='byok'` và **hai cửa sổ quota không
#    tăng** (§10.5, B-157);
# 3. adapter riêng ấy được `close()` trên **mọi** đường thoát, kể cả lỗi.


async def _save_byok_key(
    session_factory: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
    provider: str | None = None,
) -> None:
    from app.core.crypto import mask_secret, seal
    from app.db.repositories import ProviderKeyRepository

    model = get_model(MODEL_ID)
    assert model is not None
    key = "sk-" + "0123456789abcdef" * 2
    async with session_factory() as s:
        await ProviderKeyRepository(s).upsert(
            user_id=user_id,
            provider=provider or model.provider,
            sealed=seal(key),
            masked=mask_secret(key),
            verified_at=None,
        )
        await s.commit()


class _FakeByok(FakeClient):
    """Đứng thay `ByokAdapter`: nhớ cách nó được dựng và có được đóng không."""

    def __init__(self, chunks: list[Chunk], *, error: BaseException | None = None) -> None:
        super().__init__(chunks, error=error)
        self.built_with: dict[str, Any] = {}
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_byok(monkeypatch: pytest.MonkeyPatch) -> _FakeByok:
    """Vá `ByokAdapter.for_provider` ngay tại chỗ `generate` nhìn thấy nó."""
    fake = _FakeByok(_normal_chunks(["a", "b"]))

    def _build(provider: Any, *, api_key: str, **_: Any) -> _FakeByok:
        fake.built_with = {"provider": provider, "api_key": api_key}
        return fake

    monkeypatch.setattr("app.workers.generate.ByokAdapter.for_provider", _build)
    return fake


async def test_byok_uses_own_adapter_not_shared_client(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    fake_byok: _FakeByok,
) -> None:
    """§9.1 hàng 2: `base_url` từ catalog, credential là khoá của user."""
    message = await _minimal_tree(session, user_a)
    await _save_byok_key(session_factory, user_a)
    system_client = FakeClient(_normal_chunks(["khong-duoc-dung"]))

    await generate(_ctx(fake_redis, system_client), str(message.id))

    assert system_client.call is None, "client dùng chung KHÔNG được chạm tới"
    assert fake_byok.call is not None
    model = get_model(MODEL_ID)
    assert model is not None
    assert fake_byok.built_with["provider"] is catalog.get_catalog().providers[model.provider]
    assert fake_byok.built_with["api_key"].startswith("sk-")


async def test_byok_sends_provider_NATIVE_NAME_not_litellm_alias(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    fake_byok: _FakeByok,
) -> None:
    """LiteLLM không có mặt trên đường này để dịch alias — xem `provider_model`."""
    message = await _minimal_tree(session, user_a)
    await _save_byok_key(session_factory, user_a)
    model = get_model(MODEL_ID)
    assert model is not None

    await generate(_ctx(fake_redis, FakeClient([])), str(message.id))

    assert fake_byok.call is not None
    assert fake_byok.call["model"] == model.provider_model


async def test_byok_writes_ledger_row_key_source_byok_and_ZSET_does_NOT_grow(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    fake_byok: _FakeByok,
) -> None:
    """**DoD dòng 2 của T-2.15** (§10.5, B-157).

    Hai vế phải cùng đúng: dòng sổ **có** (người dùng tự xem chi tiêu của
    mình) và hai cửa sổ quota **không** tăng (tiền không phải của người vận
    hành). Bỏ `key_source=` ở `_record_usage` ra thì vế thứ hai đỏ.
    """
    message = await _minimal_tree(session, user_a)
    await _save_byok_key(session_factory, user_a)

    await generate(_ctx(fake_redis, FakeClient([])), str(message.id))

    so = await _read_ledger(session_factory, user_a)
    assert len(so) == 1
    assert so[0].key_source == KeySource.BYOK
    # NQ-134 ③ (T-S.19b): BYOK chỉ đếm token — không tiền, không snapshot giá.
    assert so[0].cost_usd == 0
    assert so[0].price_snapshot == {}
    assert so[0].prompt_tokens > 0 and so[0].completion_tokens > 0
    assert fake_redis.zset == {}, "§10.5: BYOK không trừ quota"


async def test_no_key_stays_system_and_ZSET_grows(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """Đối chứng của test ngay trên: không khoá ⇒ đường cũ không đổi một ly."""
    message = await _minimal_tree(session, user_a)

    await generate(_ctx(fake_redis, FakeClient(_normal_chunks(["a"]))), str(message.id))

    so = await _read_ledger(session_factory, user_a)
    assert so[0].key_source == KeySource.SYSTEM
    assert _zset_total(fake_redis, user_a) == so[0].cost_usd


async def test_key_for_OTHER_provider_still_goes_system(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    fake_byok: _FakeByok,
) -> None:
    """B-140 ở tầng worker: một khoá của provider khác không trả tiền hộ được."""
    message = await _minimal_tree(session, user_a)
    model = get_model(MODEL_ID)
    assert model is not None
    other = next(t for t in sorted(catalog.get_catalog().providers) if t != model.provider)
    await _save_byok_key(session_factory, user_a, provider=other)
    system_client = FakeClient(_normal_chunks(["a"]))

    await generate(_ctx(fake_redis, system_client), str(message.id))

    assert system_client.call is not None, "phải dùng client dùng chung"
    assert fake_byok.call is None
    so = await _read_ledger(session_factory, user_a)
    assert so[0].key_source == KeySource.SYSTEM


async def test_byok_adapter_closed_even_when_upstream_raises(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Không đóng là để một kết nối MANG KHOÁ nằm treo tới lúc timeout."""
    fake = _FakeByok([], error=RuntimeError("upstream dut giua chung"))

    def _build(provider: Any, *, api_key: str, **_: Any) -> _FakeByok:
        return fake

    monkeypatch.setattr("app.workers.generate.ByokAdapter.for_provider", _build)
    message = await _minimal_tree(session, user_a)
    await _save_byok_key(session_factory, user_a)

    await generate(_ctx(fake_redis, FakeClient([])), str(message.id))

    assert fake.closed, "adapter riêng phải được close() trên mọi đường thoát"
    assert fake_redis.last["type"] == "error"


# ══════════ T-S.6 — mức suy luận: BODY THẬT gửi đi, không phải kwargs ══════════
#
# DoD dòng 1: "mỗi loại tuỳ chọn (`params` / `byok_params` / `alias` /
# `omit_temperature`) một ca, khẳng định trên **body thật** gửi đi". Vì vậy các
# ca dưới đây KHÔNG dùng `FakeClient` (nó chỉ thấy kwargs của `stream()`): chúng
# chạy `SystemAdapter`/`ByokAdapter` THẬT, SDK `openai` thật, và chỉ thay tầng
# vận chuyển của httpx bằng `_WireRecorder` — thứ ghi lại đúng chuỗi JSON sẽ ra
# dây. Một `temperature=None` mà SDK gửi thành `"temperature": null`, hay một
# `extra_body` bị lồng sai tầng, chỉ lộ ra ở đây.
#
# Model của các ca này là `ts6-probe`, dựng trong catalog tạm (`ts6_catalog`):
# mỗi mức của nó mang đúng MỘT loại tuỳ chọn, để một ca đỏ chỉ về đúng một chỗ.

#: Model thử — provider `deepseek` vì cần `byok_supported: true` cho đường BYOK.
PROBE_MODEL = "ts6-probe"
#: Model thử không khai khối `reasoning`.
PLAIN_MODEL = "ts6-plain"

_TS6_MODELS: list[dict[str, Any]] = [
    {
        "id": PROBE_MODEL,
        "display_name": "T-S.6 Probe",
        "provider": "deepseek",
        "upstream_model": "deepseek/ts6-native",
        "context_window": 32768,
        "max_output": 4096,
        "pricing_mode": "unmetered",
        "order": 91,
        "reasoning": {
            "default": "off",
            "options": [
                # `params` trơn.
                {"id": "off", "params": {"thinking": {"type": "disabled"}}},
                # `byok_params` — khác `params` ở MỌI khoá, để lẫn là thấy ngay.
                {
                    "id": "low",
                    "params": {"reasoning_effort": "low"},
                    "byok_params": {"native_effort": {"level": "low"}},
                },
                # `alias`.
                {"id": "high", "params": {"reasoning_effort": "high"}, "alias": "ts6-probe-high"},
                # `omit_temperature`.
                {
                    "id": "max",
                    "params": {"thinking": {"type": "enabled", "budget_tokens": 2048}},
                    "omit_temperature": True,
                },
            ],
        },
    },
    {
        "id": PLAIN_MODEL,
        "display_name": "T-S.6 Plain",
        "provider": "ollama",
        "upstream_model": "openai/ts6-plain",
        "context_window": 32768,
        "max_output": 4096,
        "pricing_mode": "unmetered",
        "order": 92,
    },
]

#: Một lượt stream tối thiểu đúng khuôn Chat Completions: một mẩu chữ, `stop`,
#: chunk `usage` riêng (C40), rồi `[DONE]`.
_SSE_REPLY = (
    b"".join(
        b"data: " + json.dumps(chunk).encode() + b"\n\n"
        for chunk in (
            {
                "id": "c1",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "m",
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": "ok"}}],
            },
            {
                "id": "c1",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "m",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            },
            {
                "id": "c1",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "m",
                "choices": [],
                "usage": {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11},
            },
        )
    )
    + b"data: [DONE]\n\n"
)


class _WireRecorder:
    """Tầng vận chuyển giả của httpx: ghi URL + body JSON, trả `_SSE_REPLY`."""

    def __init__(self) -> None:
        self.urls: list[str] = []
        self.bodies: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.urls.append(str(request.url))
        self.bodies.append(json.loads(request.content))
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=_SSE_REPLY
        )

    @property
    def body(self) -> dict[str, Any]:
        (only,) = self.bodies
        return only


@pytest.fixture
def ts6_catalog(tmp_path: Path) -> Iterator[None]:
    """Catalog thật + hai model thử; trả catalog thật khi xong."""
    raw = json.loads(catalog.CATALOG_PATH.read_text(encoding="utf-8"))
    raw["models"].extend(_TS6_MODELS)
    fixture = tmp_path / "model_catalog.json"
    fixture.write_text(json.dumps(raw), encoding="utf-8")
    catalog.reload(path=fixture)
    yield
    catalog.reload(path=catalog.CATALOG_PATH)


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> _WireRecorder:
    """Mọi `AsyncOpenAI` mà adapter dựng ra đi qua `_WireRecorder` — cả hai đường.

    Vá đúng tên `AsyncOpenAI` mà `openai_compat.py` nhìn thấy, không vá
    adapter: `SystemAdapter.from_settings()` và `ByokAdapter.for_provider()` chạy
    y nguyên, chỉ còn socket là giả.
    """
    recorder = _WireRecorder()
    real = openai_compat.AsyncOpenAI

    def _build(**kwargs: Any) -> Any:
        transport = httpx.MockTransport(recorder)
        return real(**{**kwargs, "http_client": httpx.AsyncClient(transport=transport)})

    monkeypatch.setattr(openai_compat, "AsyncOpenAI", _build)
    return recorder


async def _run_real_adapter(fake_redis: FakeRedis, message: Message, *, byok: bool = False) -> None:
    """Chạy `generate` với `SystemAdapter` thật trong `ctx` (đường BYOK tự dựng adapter)."""
    system = SystemAdapter.from_settings()
    try:
        await generate(_ctx(fake_redis, system), str(message.id))  # type: ignore[arg-type]
    finally:
        await system.close()
    assert fake_redis.last["type"] == "done", fake_redis.last


@pytest.mark.usefixtures("ts6_catalog")
async def test_params_merged_verbatim_into_real_body(
    session: AsyncSession, user_a: uuid.UUID, fake_redis: FakeRedis, wire: _WireRecorder
) -> None:
    """**DoD dòng 1 — `params`**: khối của mức nằm ở TẦNG TRÊN CÙNG của body."""
    message = await _minimal_tree(session, user_a, model_id=PROBE_MODEL, reasoning_effort="off")

    await _run_real_adapter(fake_redis, message)

    body = wire.body
    assert body["model"] == PROBE_MODEL
    assert body["thinking"] == {"type": "disabled"}
    assert body["temperature"] == settings.LLM_TEMPERATURE
    assert "reasoning_effort" not in body
    assert wire.urls[0].startswith(settings.LITELLM_BASE_URL)


@pytest.mark.usefixtures("ts6_catalog")
async def test_byok_params_replace_params_on_byok_path(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    wire: _WireRecorder,
) -> None:
    """**DoD dòng 1 — `byok_params`**: đường BYOK gửi `byok_params`, KHÔNG trộn `params`."""
    message = await _minimal_tree(session, user_a, model_id=PROBE_MODEL, reasoning_effort="low")
    await _save_byok_key(session_factory, user_a)

    await _run_real_adapter(fake_redis, message)

    body = wire.body
    provider = catalog.get_catalog().providers["deepseek"]
    assert wire.urls[0].startswith(provider.base_url), "BYOK gọi thẳng provider"
    assert body["model"] == "ts6-native", "tên gốc của provider, không phải id LiteLLM"
    assert body["native_effort"] == {"level": "low"}
    assert "reasoning_effort" not in body, "params KHÔNG được trộn cùng byok_params"


@pytest.mark.usefixtures("ts6_catalog")
async def test_same_level_on_system_path_sends_params_not_byok_params(
    session: AsyncSession, user_a: uuid.UUID, fake_redis: FakeRedis, wire: _WireRecorder
) -> None:
    """Đối chứng của ca trên: không khoá riêng ⇒ `params`, `byok_params` vắng mặt."""
    message = await _minimal_tree(session, user_a, model_id=PROBE_MODEL, reasoning_effort="low")

    await _run_real_adapter(fake_redis, message)

    assert wire.body["reasoning_effort"] == "low"
    assert "native_effort" not in wire.body


@pytest.mark.usefixtures("ts6_catalog")
async def test_alias_replaces_model_name_sent_to_litellm(
    session: AsyncSession, user_a: uuid.UUID, fake_redis: FakeRedis, wire: _WireRecorder
) -> None:
    """**DoD dòng 1 — `alias`**: 9Router chọn mức bằng TÊN model (T-S.2)."""
    message = await _minimal_tree(session, user_a, model_id=PROBE_MODEL, reasoning_effort="high")

    await _run_real_adapter(fake_redis, message)

    assert wire.body["model"] == "ts6-probe-high"
    assert wire.body["reasoning_effort"] == "high"


@pytest.mark.usefixtures("ts6_catalog")
async def test_alias_is_ignored_on_byok_path(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    wire: _WireRecorder,
) -> None:
    """Alias là tên trong `litellm.config.yaml` — provider gọi thẳng không biết nó."""
    message = await _minimal_tree(session, user_a, model_id=PROBE_MODEL, reasoning_effort="high")
    await _save_byok_key(session_factory, user_a)

    await _run_real_adapter(fake_redis, message)

    assert wire.body["model"] == "ts6-native"


@pytest.mark.usefixtures("ts6_catalog")
async def test_omit_temperature_drops_the_key_from_real_body(
    session: AsyncSession, user_a: uuid.UUID, fake_redis: FakeRedis, wire: _WireRecorder
) -> None:
    """**DoD dòng 1 — `omit_temperature`** (Cạm bẫy ①): khoá VẮNG, không phải `null`.

    Anthropic bật thinking trả `400` cho mọi `temperature` khác 1 (T-S.2, cả
    hai đường). `"temperature": null` cũng là "có khoá" — chỉ vắng hẳn mới an toàn.
    """
    message = await _minimal_tree(session, user_a, model_id=PROBE_MODEL, reasoning_effort="max")

    await _run_real_adapter(fake_redis, message)

    assert "temperature" not in wire.body
    assert wire.body["thinking"] == {"type": "enabled", "budget_tokens": 2048}
    assert wire.body["max_tokens"] == 4096, "§10.2: max_tokens không đổi theo mức"


@pytest.mark.usefixtures("ts6_catalog")
async def test_model_without_reasoning_sends_no_extra_and_keeps_temperature(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    wire: _WireRecorder,
) -> None:
    """Không khối `reasoning` ⇒ body đúng như trước T-S.6; cột và `start` đều `null`."""
    message = await _minimal_tree(session, user_a, model_id=PLAIN_MODEL)

    await _run_real_adapter(fake_redis, message)

    assert set(wire.body) == {
        "model",
        "messages",
        "max_tokens",
        "temperature",
        "stream",
        "stream_options",
    }
    assert fake_redis.data(0)["reasoning_effort"] is None
    assert (await _reload(session_factory, message.id)).reasoning_effort is None


@pytest.mark.usefixtures("ts6_catalog")
async def test_start_event_and_column_carry_the_level_sent(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    wire: _WireRecorder,
) -> None:
    """Việc 4: event `start` mang `reasoning_effort` (S14), cột giữ đúng mức đã gửi."""
    message = await _minimal_tree(session, user_a, model_id=PROBE_MODEL, reasoning_effort="high")

    await _run_real_adapter(fake_redis, message)

    assert fake_redis.kind[0] == "start"
    assert fake_redis.data(0) == {
        "message_id": str(message.id),
        "model_id": PROBE_MODEL,
        "reasoning_effort": "high",
    }
    assert (await _reload(session_factory, message.id)).reasoning_effort == "high"


@pytest.mark.usefixtures("ts6_catalog")
async def test_level_dropped_from_catalog_falls_back_to_default_and_column_says_so(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    wire: _WireRecorder,
) -> None:
    """Catalog bỏ mức giữa lúc job nằm hàng đợi ⇒ gửi `reasoning.default`, cột ghi ĐÚNG thế.

    `medium` không có ở `ts6-probe` — đứng thay cho một mức admin vừa gỡ.
    Không đổ câu hỏi của người dùng (API đã kiểm lúc nhận), nhưng cũng không để
    cột nói một mức đã không được gửi.
    """
    message = await _minimal_tree(session, user_a, model_id=PROBE_MODEL, reasoning_effort="medium")

    await _run_real_adapter(fake_redis, message)

    assert wire.body["thinking"] == {"type": "disabled"}, "params của mức mặc định `off`"
    assert fake_redis.data(0)["reasoning_effort"] == "off"
    assert (await _reload(session_factory, message.id)).reasoning_effort == "off"


@pytest.mark.usefixtures("ts6_catalog")
async def test_catalog_params_are_not_mutated_by_a_turn(
    session: AsyncSession, user_a: uuid.UUID, fake_redis: FakeRedis, wire: _WireRecorder
) -> None:
    """`params` là dữ liệu dùng chung của tiến trình — lượt sinh chỉ nhận bản sao."""
    model = get_model(PROBE_MODEL)
    assert model is not None and model.reasoning is not None
    option = model.reasoning.option("max")
    assert option is not None
    before = json.dumps(option.params, sort_keys=True)
    message = await _minimal_tree(session, user_a, model_id=PROBE_MODEL, reasoning_effort="max")

    await _run_real_adapter(fake_redis, message)

    assert json.dumps(option.params, sort_keys=True) == before


async def test_no_reasoning_chunks_leave_column_NULL_not_empty_string(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """Cạm bẫy ② (B-267): BYOK của Anthropic không trả chữ suy luận dù đã bật thinking.

    `messages.reasoning` phải là `NULL` chứ không `''` — FE vẽ khối "Suy luận"
    gập được theo `reasoning != null`, và một khối rỗng bên trong là lỗi hiển thị.
    """
    message = await _minimal_tree(session, user_a)
    chunks = [
        Chunk(kind="delta", text="chỉ có câu trả lời"),
        Chunk(kind="done", finish_reason="stop"),
    ]

    await generate(_ctx(fake_redis, FakeClient(chunks)), str(message.id))

    reloaded = await _reload(session_factory, message.id)
    assert reloaded.content == "chỉ có câu trả lời"
    assert reloaded.reasoning is None


# ══════════ T-S.19b — endpoint BYOK người dùng tự nhập ══════════
#
# Đo ở `PinnedTransport.handle_async_request` (tầng dưới SDK `openai`): lượt
# sinh đi qua client ghim IP của T-6.3 (Cạm bẫy ②) — `ByokAdapter.for_endpoint`
# mà quên `http_client=` thì SDK tự dựng client riêng, request đi ra mạng thật
# tới một tên không resolve được, và ca dưới đỏ.

_ENDPOINT_KEY = "sk-" + "khongphaikhoathat" * 2
_ENDPOINT_MODEL = "deepseek/deepseek-chat"

#: Stream KHÔNG có chunk `usage` — C40: token phải tự đếm, `cost_confidence=low`.
_SSE_NO_USAGE = (
    b'data: {"id":"c1","object":"chat.completion.chunk","created":1,"model":"m",'
    b'"choices":[{"index":0,"delta":{"role":"assistant","content":"xin chao"}}]}\n\n'
    b'data: {"id":"c1","object":"chat.completion.chunk","created":1,"model":"m",'
    b'"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
    b"data: [DONE]\n\n"
)


async def _save_endpoint(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID, base_url: str
) -> uuid.UUID:
    from app.core.crypto import mask_secret, seal
    from app.db.repositories import ByokEndpointRepository

    async with session_factory() as s:
        row = await ByokEndpointRepository(s).create(
            user_id=user_id,
            label="ep",
            base_url=base_url,
            sealed=seal(_ENDPOINT_KEY),
            masked=mask_secret(_ENDPOINT_KEY),
            models=[_ENDPOINT_MODEL],
            verified_at=None,
        )
        await s.commit()
        return row.id


@pytest.fixture
def pinned_net(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    from app.llm import byok_endpoints
    from app.tools import ssrf

    sent: list[httpx.Request] = []

    async def _handle(self: ssrf.PinnedTransport, request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=_SSE_NO_USAGE
        )

    async def _resolve(host: str, port: int) -> list[str]:
        return ["93.184.215.14"] if host == "llm.invalid" else ["127.0.0.1"]

    monkeypatch.setattr(ssrf.PinnedTransport, "handle_async_request", _handle)
    monkeypatch.setattr(
        byok_endpoints, "validate_url", lambda url: ssrf.validate_url(url, resolver=_resolve)
    )
    return sent


async def test_endpoint_turn_goes_through_pinned_client_and_counts_tokens_only(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    pinned_net: list[httpx.Request],
) -> None:
    """DoD 1 (vế endpoint): 1 dòng sổ, token > 0, `cost_usd = 0`, ZSET không đổi."""
    eid = await _save_endpoint(session_factory, user_a, "https://llm.invalid/v1")
    model_id = f"byok:{eid}/{_ENDPOINT_MODEL}"
    message = await _minimal_tree(session, user_a, model_id=model_id)
    system_client = FakeClient(_normal_chunks(["khong-duoc-dung"]))

    await generate(_ctx(fake_redis, system_client), str(message.id))

    assert fake_redis.last["type"] == "done", fake_redis.last
    assert system_client.call is None
    (sent,) = pinned_net
    assert str(sent.url) == "https://llm.invalid/v1/chat/completions"
    assert sent.headers["authorization"] == f"Bearer {_ENDPOINT_KEY}"
    assert json.loads(sent.content)["model"] == _ENDPOINT_MODEL, "tên nguyên văn, giữ `/`"

    so = await _read_ledger(session_factory, user_a)
    assert len(so) == 1
    assert (so[0].key_source, so[0].provider, so[0].model_id) == (
        KeySource.BYOK,
        f"byok:{eid}",
        model_id,
    )
    assert so[0].prompt_tokens > 0 and so[0].completion_tokens > 0
    assert so[0].cost_usd == 0
    assert so[0].price_snapshot == {}
    assert so[0].cost_confidence == CostConfidence.LOW, "C40: không có usage ⇒ tự đếm"
    assert fake_redis.zset == {}
    assert (await _reload(session_factory, message.id)).content == "xin chao"


async def test_endpoint_now_resolving_to_private_ip_fails_before_any_request(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    pinned_net: list[httpx.Request],
) -> None:
    """A5 kiểm lại mỗi lượt: DNS đổi sang IP riêng sau khi lưu ⇒ lỗi, không gói nào đi."""
    eid = await _save_endpoint(session_factory, user_a, "https://rebind.invalid/v1")
    message = await _minimal_tree(session, user_a, model_id=f"byok:{eid}/{_ENDPOINT_MODEL}")

    await generate(_ctx(fake_redis, FakeClient([])), str(message.id))

    assert fake_redis.last["type"] == "error"
    assert fake_redis.last["data"]["code"] == "UPSTREAM_ERROR"
    assert "127.0.0.1" not in json.dumps(fake_redis.last)
    assert pinned_net == []
    assert await _read_ledger(session_factory, user_a) == []
    assert (await _reload(session_factory, message.id)).status == MessageStatus.FAILED


async def test_endpoint_of_other_user_is_model_unknown(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    fake_redis: FakeRedis,
    pinned_net: list[httpx.Request],
) -> None:
    eid = await _save_endpoint(session_factory, user_b, "https://llm.invalid/v1")
    message = await _minimal_tree(session, user_a, model_id=f"byok:{eid}/{_ENDPOINT_MODEL}")

    await generate(_ctx(fake_redis, FakeClient([])), str(message.id))

    assert fake_redis.last["data"]["code"] == "MODEL_UNKNOWN"
    assert pinned_net == []


# ───────────────────────── ảnh tới model (T-4.4b) ─────────────────────────


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), "red").save(buf, format="PNG")
    return buf.getvalue()


async def _tree_with_image(session: AsyncSession, user_id: uuid.UUID) -> tuple[Message, str]:
    """`_minimal_tree` + một ảnh gắn vào câu hỏi. Trả lá và `storage_key`."""
    answer = await _minimal_tree(session, user_id)
    key = f"{user_id}/2026/10/{uuid.uuid4()}.png"
    await AttachmentRepository(session).create(
        user_id=user_id,
        message_id=answer.parent_id,
        kind="image",
        mime_type="image/png",
        original_name="do.png",
        size_bytes=1,
        storage_key=key,
    )
    await session.commit()
    return answer, key


async def test_image_reference_becomes_data_url_before_stream(
    session: AsyncSession,
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Worker thay tham chiếu của `build()` bằng `data:image/png;base64,…` — byte từ MinIO."""
    message, key = await _tree_with_image(session, user_a)
    png = _png()
    asked: list[str] = []

    async def _get(storage_key: str) -> bytes:
        asked.append(storage_key)
        return png

    monkeypatch.setattr(storage, "get", _get)
    client = FakeClient(_normal_chunks(["Màu đỏ."]))

    await generate(_ctx(fake_redis, client), str(message.id))

    assert fake_redis.last["type"] == "done"
    assert asked == [key]
    assert client.call is not None
    parts = client.call["messages"][-1]["content"]
    assert parts[1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()},
    }


async def test_scanned_pdf_pages_become_png_data_urls_one_read(
    session: AsyncSession,
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-4.6b: tham chiếu trang PDF quét ⇒ trang render thành PNG cạnh dài
    `VISION_MAX_EDGE_PX`, đúng thứ tự trang; object PDF đọc MỘT lần cho mọi trang."""
    answer = await _minimal_tree(session, user_a)
    key = f"{user_a}/2026/10/{uuid.uuid4()}.pdf"
    await AttachmentRepository(session).create(
        user_id=user_a,
        message_id=answer.parent_id,
        kind="file",
        mime_type="application/pdf",
        original_name="ban-chup.pdf",
        size_bytes=1,
        storage_key=key,
        extract_status="needs_vision",
        page_count=2,
    )
    await session.commit()
    pages = [Image.new("RGB", (200, 100), color) for color in ("red", "blue")]
    buf = io.BytesIO()
    pages[0].save(buf, "PDF", save_all=True, append_images=pages[1:])
    asked: list[str] = []

    async def _get(storage_key: str) -> bytes:
        asked.append(storage_key)
        return buf.getvalue()

    monkeypatch.setattr(storage, "get", _get)
    client = FakeClient(_normal_chunks(["Hai trang."]))

    await generate(_ctx(fake_redis, client), str(answer.id))

    assert fake_redis.last["type"] == "done"
    assert asked == [key]
    assert client.call is not None
    images = [p for p in client.call["messages"][-1]["content"] if p["type"] == "image_url"]
    prefix = "data:image/png;base64,"
    colors = []
    for part in images:
        url = part["image_url"]["url"]
        assert url.startswith(prefix)
        with Image.open(io.BytesIO(base64.b64decode(url[len(prefix) :]))) as page:
            assert max(page.size) == settings.VISION_MAX_EDGE_PX
            colors.append(page.convert("RGB").getpixel((page.width // 2, page.height // 2)))
    # Pillow nén trang PDF bằng JPEG (255 thành 254) — so kênh trội, đúng thứ tự trang.
    assert [rgb.index(max(rgb)) for rgb in colors] == [0, 2]


async def test_missing_image_object_ends_with_coded_error(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Object mất ⇒ `error ATTACHMENT_UNAVAILABLE` (C19), không gọi model, không treo."""
    message, _key = await _tree_with_image(session, user_a)

    async def _missing(_storage_key: str) -> bytes:
        raise FileNotFoundError("NoSuchKey")

    monkeypatch.setattr(storage, "get", _missing)
    client = FakeClient(_normal_chunks(["không được tới đây"]))

    await generate(_ctx(fake_redis, client), str(message.id))

    assert fake_redis.kind == ["start", "error"]
    assert fake_redis.last["data"]["code"] == "ATTACHMENT_UNAVAILABLE"
    assert client.call is None
    reloaded = await _reload(session_factory, message.id)
    assert reloaded.status is MessageStatus.FAILED
    assert reloaded.error_code == "ATTACHMENT_UNAVAILABLE"


# ─────────────────────── ⑥.2 artifact từ khối code (T-5.1) ───────────────────────

#: Hai khối có tiêu đề, cắt thành mẩu để khối nằm vắt qua nhiều `delta` như thật.
TWO_BLOCKS = [
    'Đây là trang:\n\n```html title="Trang một"\n',
    "<p>một</p>\n```\n\n",
    'Và hình:\n\n```svg title="Hình hai"\n',
    "<svg/>\n```\n",
]


async def _read_artifacts(
    session_factory: async_sessionmaker[AsyncSession], mid: uuid.UUID
) -> list[Artifact]:
    async with session_factory() as s:
        stmt = select(Artifact).where(Artifact.message_id == mid).order_by(Artifact.created_at)
        return list((await s.execute(stmt)).scalars())


async def test_two_blocks_two_v1_rows_and_artifact_events_before_done(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """T-5.1 DoD dòng 3: 2 hàng v1 của message assistant, 2 `artifact` TRƯỚC `done`.

    `created_at` tăng dần là phép đo của migration 0011: cả lô ghi trong MỘT
    transaction (ở đây còn chung transaction ngoài của test) — `now()` cho mọi
    hàng một giá trị.
    """
    message = await _minimal_tree(session, user_a)

    await generate(_ctx(fake_redis, FakeClient(_normal_chunks(TWO_BLOCKS))), str(message.id))

    rows = await _read_artifacts(session_factory, message.id)
    assert [(r.kind, r.title, r.content, r.version) for r in rows] == [
        ("html", "Trang một", "<p>một</p>", 1),
        ("svg", "Hình hai", "<svg/>", 1),
    ]
    assert all(r.parent_artifact_id is None for r in rows)
    assert rows[0].created_at < rows[1].created_at

    assert fake_redis.kind[-3:] == ["artifact", "artifact", "done"]
    events = [fake_redis.data(i) for i, k in enumerate(fake_redis.kind) if k == "artifact"]
    assert events == [
        {"artifact_id": str(r.id), "version": 1, "kind": r.kind, "title": r.title} for r in rows
    ]


async def test_artifact_insert_failure_still_done_content_intact_one_log_line(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Câu trả lời đã ghi — mất artifact là sự cố có log, không phải lỗi đỏ."""
    message = await _minimal_tree(session, user_a)

    async def _boom(*_a: Any, **_k: Any) -> list[Artifact]:
        raise RuntimeError("deadlock detected")

    monkeypatch.setattr(ArtifactRepository, "create_for_message", _boom)

    with caplog.at_level("ERROR", logger="app.workers.generate"):
        await generate(_ctx(fake_redis, FakeClient(_normal_chunks(TWO_BLOCKS))), str(message.id))

    assert fake_redis.last["type"] == "done"
    assert "artifact" not in fake_redis.kind
    reloaded = await _reload(session_factory, message.id)
    assert reloaded.status is MessageStatus.COMPLETED
    assert reloaded.content == "".join(TWO_BLOCKS)
    assert [r.getMessage() for r in caplog.records] == [
        f"generate: {message.id} KHONG tao duoc artifact — cau tra loi van nguyen"
    ]


async def test_cancel_while_second_block_open_keeps_only_closed_one(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """Huỷ ở chunk thứ `CANCEL_CHECK_EVERY_N_CHUNKS` khi khối hai còn dở ⇒ 1 hàng."""
    pieces = [
        '```html title="Xong"\n',
        "<p>a</p>\n",
        "```\n",
        '```svg title="Dở"\n',
        *(["<g/>\n"] * (CANCEL_CHECK_EVERY_N_CHUNKS - 4)),
        "```\n",
    ]
    message = await _minimal_tree(session, user_a)
    fake_redis.cancel_flags.add(cancel_key(message.id))

    await generate(_ctx(fake_redis, FakeClient(_normal_chunks(pieces))), str(message.id))

    assert fake_redis.last["data"]["finish_reason"] == FINISH_REASON_CANCELLED
    rows = await _read_artifacts(session_factory, message.id)
    assert [r.title for r in rows] == ["Xong"]
    assert fake_redis.kind[-2:] == ["artifact", "done"]
