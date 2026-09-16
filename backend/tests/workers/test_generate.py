"""T-1.6 — `app/workers/generate.py`: vòng đời một lượt sinh (§7.2 ③).

KH tham chiếu: §7.2, §7.4, §7.6, ADR-01, C5, C8, C9, C10, C19 · NQ-22, NQ-23.

Bốn trong sáu dòng DoD của task được kiểm ở đây dưới dạng tự động; hai dòng
còn lại (`redis-cli XLEN`/`TTL` trên đường chạy thật) nằm trong báo cáo task:

- **DoD 2** — bản ghi cuối cùng là `type=done`: `test_duong_chay_binh_thuong…`
- **DoD 3** — upstream đứt giữa chừng → bản ghi cuối là `error` **có mã**:
  `test_upstream_dut_giua_chung…` (C19)
- **DoD 5** — nối mọi `delta` **bằng byte-by-byte** với `messages.content`:
  `test_noi_delta_bang_dung_content_trong_postgres`
- **DoD 6** — emoji + xuống dòng, `json.loads` đọc lại được (C10): cùng test trên

Cây message là cây **thật trong Postgres** (fixture của `tests/conftest.py`),
đi qua đúng `get_path` của T-1.2 và `context.build` của T-1.4. Chỉ hai thứ là
giả: Redis (một list ghi lại lời gọi) và provider (`ClientGia`). Giả Postgres ở
đây sẽ bỏ lọt đúng thứ đáng kiểm nhất — rằng `content` xuống đĩa **bằng** chuỗi
client dựng từ stream.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.db.session as db_session
from app.config.catalog import get_model
from app.config.settings import settings
from app.db.models import Conversation, Message, MessageRole, MessageStatus
from app.db.repositories import ConversationRepository, MessageRepository
from app.llm import context as llm_context
from app.llm.client import Chunk, ToolCall, Usage
from app.streaming.cancel import FINISH_REASON_CANCELLED, cancel_key
from app.streaming.producer import FIELD_DATA, FIELD_TYPE
from app.workers.generate import CTX_LLM_CLIENT, KIEM_HUY_MOI_N_CHUNK, generate

#: Model THẬT trong `config/model_catalog.json` — `generate` tra catalog bằng
#: `messages.model_id`, nên một id bịa sẽ đi thẳng vào nhánh `MODEL_UNKNOWN`.
MODEL_ID = "deepseek-flash"

#: Nhịp tim dùng trong test §7.6. **Không** đặt 0: từ B-122 nhịp tim là một
#: task riêng chạy `while True: await sleep(nhip)`, nên 0 biến nó thành vòng
#: nóng quay Postgres không nghỉ và test sẽ đỏ vì cạn pool chứ không vì cái nó
#: muốn đo. Đủ nhỏ để test vẫn nhanh, đủ lớn để một nhịp thật sự kịp ghi.
NHIP_TEST_S = 0.02


# ─────────────────────────── hai thứ giả ───────────────────────────


class RedisGia:
    """Đủ `xadd`/`expire` (§7.2 ③) và `exists` (cờ huỷ §7.5).

    Trả `bytes` như pool arq dựng (không decode). `co_huy` là tập khoá đang
    "tồn tại" — test đặt tay thay cho `POST /messages/{id}/cancel`.
    """

    def __init__(self) -> None:
        self.ban_ghi: list[dict[str, str]] = []
        self.expire_calls: list[tuple[str, int]] = []
        self.co_huy: set[str] = set()
        self.exists_calls: list[str] = []
        self.exists_no_ra = False
        self._seq = 0

    async def exists(self, name: str) -> int:
        self.exists_calls.append(name)
        if self.exists_no_ra:
            raise ConnectionError("redis chet giua chung (gia lap)")
        return 1 if name in self.co_huy else 0

    async def xadd(self, name: str, fields: dict[str, Any]) -> bytes:
        self._seq += 1
        self.ban_ghi.append({"__key__": name, **fields})
        return f"1725984000{self._seq:03d}-0".encode()

    async def expire(self, name: str, ttl: int) -> int:
        self.expire_calls.append((name, ttl))
        return 1

    # ── đọc lại cho tiện khẳng định ──

    @property
    def loai(self) -> list[str]:
        return [b[FIELD_TYPE] for b in self.ban_ghi]

    def data(self, i: int) -> Any:
        return json.loads(self.ban_ghi[i][FIELD_DATA])

    @property
    def cuoi(self) -> dict[str, Any]:
        """Bản ghi cuối cùng, đã parse — DoD dòng 2 và 3 nhìn vào đúng chỗ này."""
        return {"type": self.ban_ghi[-1][FIELD_TYPE], "data": self.data(-1)}

    def chu(self) -> str:
        return "".join(self.data(i)["t"] for i, t in enumerate(self.loai) if t == "delta")


class ClientGia:
    """`LLMClient` giả: phát sẵn một dãy `Chunk`, rồi (tuỳ chọn) nổ."""

    def __init__(self, chunks: list[Chunk], *, loi: BaseException | None = None) -> None:
        self._chunks = chunks
        self._loi = loi
        self.goi: dict[str, Any] | None = None

    async def stream(self, **kwargs: Any) -> AsyncIterator[Chunk]:
        self.goi = kwargs
        return self._phat()

    async def _phat(self) -> AsyncIterator[Chunk]:
        for chunk in self._chunks:
            yield chunk
        if self._loi is not None:
            raise self._loi


class ClientNoNgay(ClientGia):
    """Nổ ngay tại `await stream(...)` — ca 401/400/429 của §9.1."""

    async def stream(self, **kwargs: Any) -> AsyncIterator[Chunk]:
        self.goi = kwargs
        raise RuntimeError("401 Unauthorized")


# ─────────────────────────── hạ tầng test ───────────────────────────


@pytest.fixture
def redis_gia() -> RedisGia:
    return RedisGia()


@pytest.fixture(autouse=True)
def _noi_session_vao_db_test(
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


def _ctx(redis_gia: RedisGia, client: ClientGia) -> dict[str, Any]:
    return {"redis": redis_gia, "job_id": "test-job", CTX_LLM_CLIENT: client}


async def _cay_toi_thieu(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    model_id: str | None = MODEL_ID,
    status: MessageStatus = MessageStatus.QUEUED,
) -> Message:
    """Một câu hỏi đã xong + một message assistant `queued` — đúng §7.2 ①."""
    repo = MessageRepository(session)
    conversation: Conversation = await ConversationRepository(session).create_conversation(
        user_id=user_id
    )
    hoi = await repo.create_message(
        conversation_id=conversation.id,
        user_id=user_id,
        role=MessageRole.USER,
        content="Mùa thu Hà Nội thế nào?",
        status=MessageStatus.COMPLETED,
    )
    tra_loi = await repo.create_message(
        conversation_id=conversation.id,
        user_id=user_id,
        role=MessageRole.ASSISTANT,
        parent_id=hoi.id,
        status=status,
        model_id=model_id,
    )
    await session.commit()
    return tra_loi


async def _doc_lai(session_factory: async_sessionmaker[AsyncSession], mid: uuid.UUID) -> Message:
    """Đọc bằng session MỚI: repository ghi bằng `UPDATE` thẳng, nên session cũ
    có thể còn giữ bản trong identity map (xem `conftest.py`)."""
    async with session_factory() as s:
        return (await s.execute(select(Message).where(Message.id == mid))).scalar_one()


def _chunks_binh_thuong(chu: list[str]) -> list[Chunk]:
    usage = Usage(prompt_tokens=214, completion_tokens=len(chu), total_tokens=214 + len(chu))
    return [
        *(Chunk(kind="delta", text=phan) for phan in chu),
        Chunk(kind="usage", usage=usage),
        Chunk(kind="done", finish_reason="stop", usage=usage),
    ]


# ───────────────────────────── đường chạy ─────────────────────────────


async def test_duong_chay_binh_thuong_ket_thuc_bang_done(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    redis_gia: RedisGia,
) -> None:
    """DoD dòng 2: bản ghi cuối cùng có `type=done`. Và đúng thứ tự §7.2 ③."""
    message = await _cay_toi_thieu(session, user_a)
    client = ClientGia(_chunks_binh_thuong(["Hà Nội ", "mùa thu ", "đẹp."]))

    await generate(_ctx(redis_gia, client), str(message.id))

    assert redis_gia.loai == ["start", "delta", "delta", "delta", "usage", "done"]
    assert redis_gia.cuoi["type"] == "done"
    assert redis_gia.cuoi["data"] == {
        "finish_reason": "stop",
        "usage": {"in": 214, "out": 3},
    }
    # C8 — TTL đặt sau event kết thúc, đúng một lần.
    assert redis_gia.expire_calls == [(f"stream:{message.id}", settings.STREAM_TTL_S)]

    lai = await _doc_lai(session_factory, message.id)
    assert lai.status is MessageStatus.COMPLETED
    assert lai.finish_reason == "stop"
    assert lai.prompt_tokens == 214
    assert lai.completion_tokens == 3
    assert lai.error_code is None


async def test_noi_delta_bang_dung_content_trong_postgres(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    redis_gia: RedisGia,
) -> None:
    """DoD dòng 5 + 6: so **byte-by-byte**, với emoji và xuống dòng (C9, C10)."""
    manh = ["Chào 🎉\n", 'bạn — dấu " và \\', "\ncuối 😀", "…"]
    message = await _cay_toi_thieu(session, user_a)

    await generate(_ctx(redis_gia, ClientGia(_chunks_binh_thuong(manh))), str(message.id))

    mong_doi = "".join(manh)
    lai = await _doc_lai(session_factory, message.id)
    assert lai.content == mong_doi
    assert lai.content.encode("utf-8") == mong_doi.encode("utf-8")
    # Nối lại từ CHÍNH các bản ghi trong stream, sau khi đi qua json.dumps.
    assert redis_gia.chu() == mong_doi
    assert all("\n" not in b[FIELD_DATA] for b in redis_gia.ban_ghi)


async def test_reasoning_khong_lan_vao_content(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    redis_gia: RedisGia,
) -> None:
    """B-33: reasoning là `event` riêng, cột riêng, và KHÔNG vào `content`."""
    message = await _cay_toi_thieu(session, user_a)
    chunks = [
        Chunk(kind="reasoning", text="để tôi nghĩ…"),
        Chunk(kind="delta", text="Xin chào"),
        Chunk(kind="done", finish_reason="stop"),
    ]

    await generate(_ctx(redis_gia, ClientGia(chunks)), str(message.id))

    assert redis_gia.loai == ["start", "reasoning", "delta", "done"]
    lai = await _doc_lai(session_factory, message.id)
    assert lai.content == "Xin chào"
    assert lai.reasoning == "để tôi nghĩ…"


async def test_tool_calls_ghi_dung_hinh_dang_cua_day_openai(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    redis_gia: RedisGia,
) -> None:
    """NQ-22/B-68: cột `tool_calls` phải là thứ `context._to_wire` đọc lại được.

    Không so với một dict chép tay: phép kiểm thật là **bên đọc nhận ra bên
    ghi**, vì đó chính là chỗ hai task lệch nhau được.
    """
    message = await _cay_toi_thieu(session, user_a)
    goi = ToolCall(call_id="call_abc", name="web_search", arguments='{"query": "mùa thu"}')
    chunks = [
        Chunk(kind="delta", text="Để tôi tìm."),
        Chunk(kind="tool_call", tool_call=goi),
        Chunk(kind="done", finish_reason="tool_calls"),
    ]

    await generate(_ctx(redis_gia, ClientGia(chunks)), str(message.id))

    lai = await _doc_lai(session_factory, message.id)
    assert lai.tool_calls == [
        {
            "id": "call_abc",
            "type": "function",
            "function": {"name": "web_search", "arguments": '{"query": "mùa thu"}'},
        }
    ]
    # Bên đọc của lượt SAU nhận ra đúng `id` này (C15 `_dong_khoi` dựa vào nó).
    assert llm_context._declared_call_ids({"tool_calls": lai.tool_calls}) == {"call_abc"}

    # Trên dây thì `args` là object (§7.4), còn chuỗi thô ở lại trong DB.
    su_kien = redis_gia.data(redis_gia.loai.index("tool_call"))
    assert su_kien == {"call_id": "call_abc", "name": "web_search", "args": {"query": "mùa thu"}}


# ─────────────────────── các đường thoát bất thường (C19) ───────────────────────


async def test_upstream_dut_giua_chung_ket_thuc_bang_error_co_ma(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    redis_gia: RedisGia,
) -> None:
    """DoD dòng 3 + C19: đứt giữa chừng **không** được im lặng, và giữ phần chữ."""
    message = await _cay_toi_thieu(session, user_a)
    client = ClientGia(
        [Chunk(kind="delta", text="Hà Nội "), Chunk(kind="delta", text="mùa thu")],
        loi=ConnectionResetError("peer closed"),
    )

    await generate(_ctx(redis_gia, client), str(message.id))

    assert redis_gia.cuoi["type"] == "error"
    assert redis_gia.cuoi["data"]["code"] == "UPSTREAM_ERROR"
    assert "ConnectionResetError" in redis_gia.cuoi["data"]["message"]
    # C8 vẫn phải chạy trên đường lỗi — stream lỗi cũng chiếm RAM.
    assert redis_gia.expire_calls == [(f"stream:{message.id}", settings.STREAM_TTL_S)]

    lai = await _doc_lai(session_factory, message.id)
    assert lai.status is MessageStatus.FAILED
    assert lai.error_code == "UPSTREAM_ERROR"
    assert lai.content == "Hà Nội mùa thu", "phần đã sinh phải được giữ lại"


async def test_loi_ngay_tai_await_stream_van_co_event_ket_thuc(
    session: AsyncSession,
    user_a: uuid.UUID,
    redis_gia: RedisGia,
) -> None:
    """401/400/429 nổ tại `await` (điểm 1 `client.py`) — vẫn phải có `error`."""
    message = await _cay_toi_thieu(session, user_a)

    await generate(_ctx(redis_gia, ClientNoNgay([])), str(message.id))

    assert redis_gia.loai == ["start", "error"]
    assert redis_gia.cuoi["data"]["code"] == "UPSTREAM_ERROR"


async def test_bi_huy_van_ghi_error_roi_nem_tiep(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    redis_gia: RedisGia,
) -> None:
    """arq cắt job quá `GENERATE_TIMEOUT_S`: client không được treo, mà
    `CancelledError` cũng không được nuốt."""
    message = await _cay_toi_thieu(session, user_a)
    client = ClientGia([Chunk(kind="delta", text="một nửa")], loi=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await generate(_ctx(redis_gia, client), str(message.id))

    assert redis_gia.cuoi["type"] == "error"
    assert redis_gia.cuoi["data"]["code"] == "WORKER_TIMEOUT"
    lai = await _doc_lai(session_factory, message.id)
    assert lai.status is MessageStatus.FAILED
    assert lai.content == "một nửa"


async def test_message_khong_con_thi_bao_ma_rieng(user_a: uuid.UUID, redis_gia: RedisGia) -> None:
    """Job mồ côi: không có `start`, nhưng vẫn có đúng một event kết thúc."""
    await generate(_ctx(redis_gia, ClientGia([])), str(uuid.uuid4()))

    assert redis_gia.loai == ["error"]
    assert redis_gia.cuoi["data"]["code"] == "MESSAGE_NOT_FOUND"


async def test_model_id_khong_co_trong_catalog(
    session: AsyncSession, user_a: uuid.UUID, redis_gia: RedisGia
) -> None:
    message = await _cay_toi_thieu(session, user_a, model_id="model-da-bi-xoa")

    await generate(_ctx(redis_gia, ClientGia([])), str(message.id))

    assert redis_gia.loai == ["error"]
    assert redis_gia.cuoi["data"]["code"] == "MODEL_UNKNOWN"


async def test_message_khong_con_queued_thi_bo_luot(
    session: AsyncSession, user_a: uuid.UUID, redis_gia: RedisGia
) -> None:
    """B-72: arq giao lại một job đã chạy (SIGKILL) — worker thứ hai phải bỏ.

    Sinh tiếp là gọi model lần hai cho cùng một câu hỏi, tức hoá đơn lần hai.
    """
    message = await _cay_toi_thieu(session, user_a, status=MessageStatus.STREAMING)

    await generate(_ctx(redis_gia, ClientGia(_chunks_binh_thuong(["x"]))), str(message.id))

    assert redis_gia.loai == ["error"]
    assert redis_gia.cuoi["data"]["code"] == "MESSAGE_NOT_FOUND"


async def test_khong_ghi_duoc_postgres_thi_bao_persist_failed(
    session: AsyncSession,
    user_a: uuid.UUID,
    redis_gia: RedisGia,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chữ đã tới người dùng nhưng lịch sử thì không — nói thẳng, không gửi `done`."""
    message = await _cay_toi_thieu(session, user_a)

    async def no(*_a: Any, **_k: Any) -> bool:
        raise RuntimeError("deadlock detected")

    monkeypatch.setattr(MessageRepository, "finish_generation", no)

    await generate(_ctx(redis_gia, ClientGia(_chunks_binh_thuong(["a"]))), str(message.id))

    assert redis_gia.cuoi["type"] == "error"
    assert redis_gia.cuoi["data"]["code"] == "PERSIST_FAILED"


# ───────────────────────────── §7.6 heartbeat ─────────────────────────────


async def test_ghi_heartbeat_trong_luc_sinh(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    redis_gia: RedisGia,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§7.6: reaper so `heartbeat_at` với `now()`, nên nó phải NHÍCH trong lúc sinh."""
    message = await _cay_toi_thieu(session, user_a)
    monkeypatch.setattr(settings, "WORKER_HEARTBEAT_S", NHIP_TEST_S)

    async def doc_heartbeat() -> Any:
        return (await _doc_lai(session_factory, message.id)).heartbeat_at

    moc: list[Any] = []

    class ClientCoMoc(ClientGia):
        async def _phat(self) -> AsyncIterator[Chunk]:
            for chunk in _chunks_binh_thuong(["a", "b"]):
                yield chunk
                await asyncio.sleep(NHIP_TEST_S * 3)
                moc.append(await doc_heartbeat())

    await generate(_ctx(redis_gia, ClientCoMoc([])), str(message.id))

    assert all(m is not None for m in moc), "heartbeat_at phải có giá trị ngay từ mark_streaming"
    assert moc[-1] > moc[0], f"heartbeat_at không nhích: {moc}"


async def test_nhip_tim_dap_ca_khi_model_CHUA_tra_mot_chunk_nao(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    redis_gia: RedisGia,
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
    message = await _cay_toi_thieu(session, user_a)
    monkeypatch.setattr(settings, "WORKER_HEARTBEAT_S", NHIP_TEST_S)

    async def doc_heartbeat() -> Any:
        return (await _doc_lai(session_factory, message.id)).heartbeat_at

    moc: list[Any] = []

    class ClientNghiLau(ClientGia):
        async def _phat(self) -> AsyncIterator[Chunk]:
            moc.append(await doc_heartbeat())  # ngay sau `mark_streaming`
            await asyncio.sleep(NHIP_TEST_S * 4)  # model đang "nghĩ"
            moc.append(await doc_heartbeat())  # VẪN chưa có chunk nào ra
            for chunk in _chunks_binh_thuong(["a"]):
                yield chunk

    await generate(_ctx(redis_gia, ClientNghiLau([])), str(message.id))

    assert all(m is not None for m in moc)
    assert moc[1] > moc[0], (
        f"nhịp tim không đập trong lúc chờ chunk đầu — REAPER_STALE_S vẫn đang "
        f"kiêm vai 'TTFT tối đa' (B-122): {moc}"
    )


async def test_nhip_tim_khong_song_lau_hon_luot_sinh(
    session: AsyncSession,
    user_a: uuid.UUID,
    redis_gia: RedisGia,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task nhịp tim phải bị huỷ ở `finally`, không rò ra ngoài `generate`.

    Một task rò sẽ ghi `heartbeat_at` cho một message đã khép. Hôm nay vô hại
    vì `touch_heartbeat` chỉ khớp `status='streaming'`, nhưng nó là lớp phòng
    thủ thứ hai — lớp thứ nhất là không rò. Đếm task theo TÊN chứ không theo
    tác dụng phụ, vì tác dụng phụ đang bị lớp thứ hai che mất.
    """
    message = await _cay_toi_thieu(session, user_a)
    monkeypatch.setattr(settings, "WORKER_HEARTBEAT_S", NHIP_TEST_S)

    await generate(_ctx(redis_gia, ClientGia(_chunks_binh_thuong(["a"]))), str(message.id))

    con_song = [t for t in asyncio.all_tasks() if t.get_name().startswith("nhip-tim:")]
    assert con_song == [], f"task nhịp tim còn sống sau khi generate xong: {con_song}"


async def test_tham_so_gui_cho_model_lay_tu_catalog_va_settings(
    session: AsyncSession, user_a: uuid.UUID, redis_gia: RedisGia
) -> None:
    """A3: `max_tokens` từ catalog, `temperature` từ `.env` — không hằng trong `.py`."""
    message = await _cay_toi_thieu(session, user_a)
    client = ClientGia(_chunks_binh_thuong(["x"]))

    await generate(_ctx(redis_gia, client), str(message.id))

    assert client.goi is not None
    assert client.goi["model"] == MODEL_ID
    assert client.goi["max_tokens"] == 8192  # `max_output` của deepseek-flash
    assert client.goi["temperature"] == settings.LLM_TEMPERATURE
    assert client.goi["tools"] is None, "Phase 1 chưa có tool registry (C18)"
    # A2/C11: ngữ cảnh là ĐƯỜNG ĐI, và message `queued` đang sinh không có mặt.
    vai_tro = [m["role"] for m in client.goi["messages"]]
    assert vai_tro == ["system", "user"]


# ═════════════════════ §7.5 — huỷ giữa chừng (T-1.9) ═════════════════════


def _chunks_dai(so_luong: int) -> list[Chunk]:
    """`so_luong` mẩu `delta`, rồi `usage` + `done` như một lượt sinh bình thường.

    Dãy này **cố ý** kết thúc đầy đủ: nếu vòng lặp không dừng vì cờ huỷ, test sẽ
    thấy `finish_reason='stop'` và `status='completed'` — tức phép kiểm hỏng
    theo hướng nhìn thấy được, chứ không phải treo.
    """
    chu = [f"m{i} " for i in range(so_luong)]
    return _chunks_binh_thuong(chu)


async def test_dung_vong_lap_khi_thay_co_huy(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    redis_gia: RedisGia,
) -> None:
    """§7.5: thấy cờ ⇒ dừng, `finish_reason='cancelled'`, `status='cancelled'`.

    Huỷ **không** phải lỗi: `error_code` để NULL và event cuối là `done`, chứ
    không phải `error`. FE bật nút Retry theo `error`, mà một câu trả lời người
    dùng chủ động dừng thì không có gì để thử lại.
    """
    message = await _cay_toi_thieu(session, user_a)
    redis_gia.co_huy.add(cancel_key(message.id))
    client = ClientGia(_chunks_dai(40))

    await generate(_ctx(redis_gia, client), str(message.id))

    assert redis_gia.cuoi["type"] == "done"
    assert redis_gia.cuoi["data"]["finish_reason"] == FINISH_REASON_CANCELLED

    lai = await _doc_lai(session_factory, message.id)
    assert lai.status is MessageStatus.CANCELLED
    assert lai.finish_reason == FINISH_REASON_CANCELLED
    assert lai.error_code is None


async def test_dung_dung_sau_N_chunk_khong_som_khong_muon(
    session: AsyncSession,
    user_a: uuid.UUID,
    redis_gia: RedisGia,
) -> None:
    """Đếm **chính xác** `KIEM_HUY_MOI_N_CHUNK`: đó là ngân sách của "≤ 500 ms".

    Kiểm mỗi chunk thì tốn một `EXISTS` cho mỗi mẩu chữ; kiểm thưa hơn thì nút
    Dừng ăn muộn. Test khoá con số lại để một lần "tối ưu" sau này phải đi qua
    đây.
    """
    message = await _cay_toi_thieu(session, user_a)
    redis_gia.co_huy.add(cancel_key(message.id))

    await generate(_ctx(redis_gia, ClientGia(_chunks_dai(100))), str(message.id))

    assert redis_gia.chu() == "".join(f"m{i} " for i in range(KIEM_HUY_MOI_N_CHUNK))
    assert len(redis_gia.exists_calls) == 1, "thấy cờ ở lần hỏi đầu tiên thì thôi hỏi nữa"


async def test_van_luu_phan_da_sinh_va_bang_dung_chu_tren_day(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    redis_gia: RedisGia,
) -> None:
    """DoD dòng 2: `messages.content` chứa **đúng** phần đã sinh — không rỗng,
    không đầy đủ, và bằng byte-by-byte với chuỗi client dựng từ stream."""
    message = await _cay_toi_thieu(session, user_a)
    redis_gia.co_huy.add(cancel_key(message.id))

    await generate(_ctx(redis_gia, ClientGia(_chunks_dai(100))), str(message.id))

    lai = await _doc_lai(session_factory, message.id)
    day_du = "".join(f"m{i} " for i in range(100))
    assert lai.content == redis_gia.chu()
    assert lai.content, "không rỗng"
    assert lai.content != day_du, "không đầy đủ"
    assert day_du.startswith(lai.content), "là TIỀN TỐ của câu trả lời đầy đủ"


async def test_khong_co_co_thi_khong_dung_va_van_hoi_dung_khoa(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    redis_gia: RedisGia,
) -> None:
    """Không ai bấm Dừng ⇒ lượt sinh chạy hết, và khoá được hỏi đúng tên.

    Phép so `exists_calls` là chỗ bắt lỗi gõ lệch tiền tố: nếu worker hỏi
    `cancel-{id}` còn API ghi `cancel:{id}` thì mọi test huỷ ở trên vẫn xanh
    (chúng tự đặt khoá bằng `cancel_key`), chỉ đường chạy thật là hỏng.
    """
    message = await _cay_toi_thieu(session, user_a)
    so_chunk_delta = 40

    await generate(_ctx(redis_gia, ClientGia(_chunks_dai(so_chunk_delta))), str(message.id))

    lai = await _doc_lai(session_factory, message.id)
    assert lai.status is MessageStatus.COMPLETED
    assert lai.finish_reason == "stop"
    # `usage` + `done` là hai chunk nữa sau `delta`, nên tổng là 42.
    assert len(redis_gia.exists_calls) == (so_chunk_delta + 2) // KIEM_HUY_MOI_N_CHUNK
    assert set(redis_gia.exists_calls) == {cancel_key(message.id)}


async def test_khong_kiem_duoc_co_thi_van_sinh_tiep(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    redis_gia: RedisGia,
) -> None:
    """`EXISTS` nổ ⇒ ghi cảnh báo rồi đi tiếp, KHÔNG đội lốt `UPSTREAM_ERROR`.

    Mất một lần hỏi là nút Dừng ăn muộn vài chunk. Để ngoại lệ thoát ra thì
    người dùng đọc được "provider lỗi" cho một sự cố nằm hoàn toàn ở phía mình.
    """
    message = await _cay_toi_thieu(session, user_a)
    redis_gia.exists_no_ra = True

    await generate(_ctx(redis_gia, ClientGia(_chunks_dai(40))), str(message.id))

    assert redis_gia.cuoi["type"] == "done"
    lai = await _doc_lai(session_factory, message.id)
    assert lai.status is MessageStatus.COMPLETED


async def test_huy_thi_usage_de_NULL_chu_khong_bia_so(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    redis_gia: RedisGia,
) -> None:
    """Provider chỉ gửi `usage` ở chunk CUỐI, nên huỷ = không có usage thật.

    Hai cột để NULL chứ không điền một con số tự đếm: NQ-23 dựa vào chỗ khác
    nhau giữa "provider không báo" và "báo và bằng 0", và chưa có cột
    `cost_confidence` nào để đánh dấu một con số ước tính. Việc đếm cho phần đã
    huỷ thuộc T-2.12 (B-94); ở Phase 1 nó là một dòng log.
    """
    message = await _cay_toi_thieu(session, user_a)
    redis_gia.co_huy.add(cancel_key(message.id))

    await generate(_ctx(redis_gia, ClientGia(_chunks_dai(100))), str(message.id))

    assert redis_gia.cuoi["data"]["usage"] is None
    lai = await _doc_lai(session_factory, message.id)
    assert lai.prompt_tokens is None
    assert lai.completion_tokens is None


async def test_huy_ghi_mot_dong_log_cho_usage(
    session: AsyncSession,
    user_a: uuid.UUID,
    redis_gia: RedisGia,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """DoD dòng 3: "ở phase này kiểm bằng log" — dòng log ấy phải TỒN TẠI.

    Không có nó thì phần đã huỷ biến mất khỏi sổ sách một cách im lặng, và
    T-2.12 không có chỗ nào để nối vào (Cạm bẫy của task: quota bị rò).
    """
    message = await _cay_toi_thieu(session, user_a)
    redis_gia.co_huy.add(cancel_key(message.id))

    with caplog.at_level("INFO", logger="app.workers.generate"):
        await generate(_ctx(redis_gia, ClientGia(_chunks_dai(100))), str(message.id))

    dong = [r.getMessage() for r in caplog.records if "HUY" in r.getMessage()]
    assert len(dong) == 1, "đúng một dòng, không phải không dòng nào và không phải hai"
    assert str(message.id) in dong[0]
    assert "usage" in dong[0]


async def test_huy_van_EXPIRE_stream(
    session: AsyncSession,
    user_a: uuid.UUID,
    redis_gia: RedisGia,
) -> None:
    """C8 áp cho cả ba ngả: stream của một lượt bị huỷ cũng chiếm RAM."""
    message = await _cay_toi_thieu(session, user_a)
    redis_gia.co_huy.add(cancel_key(message.id))

    await generate(_ctx(redis_gia, ClientGia(_chunks_dai(100))), str(message.id))

    assert redis_gia.expire_calls == [(f"stream:{message.id}", settings.STREAM_TTL_S)]


async def test_phan_da_huy_van_vao_ngu_canh_luot_sau(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    redis_gia: RedisGia,
) -> None:
    """`USABLE_STATUSES` nhận `cancelled` — người dùng đã nhìn thấy phần chữ đó.

    Kiểm qua chính `context.build` chứ không đọc hằng số: nếu một ngày ai đó
    bỏ `cancelled` khỏi `USABLE_STATUSES` thì lượt sau sẽ thấy một hội thoại
    thiếu mất câu trả lời mà người dùng đang nhìn trên màn hình.
    """
    message = await _cay_toi_thieu(session, user_a)
    redis_gia.co_huy.add(cancel_key(message.id))
    await generate(_ctx(redis_gia, ClientGia(_chunks_dai(100))), str(message.id))

    lai = await _doc_lai(session_factory, message.id)
    model_meta = get_model(MODEL_ID)
    assert model_meta is not None
    async with session_factory() as s:
        wire = await llm_context.build(s, lai.id, model_meta, user_id=user_a)

    assert any(m["role"] == "assistant" and m.get("content") == lai.content for m in wire)
