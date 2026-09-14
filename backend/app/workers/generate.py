"""Job `generate` — vòng đời một câu trả lời, phía worker (§7.2 bước ③).

KH tham chiếu: §7.2, §7.4, §7.6, §9.1, §9.6, ADR-01, ADR-02, C5, C8, C9, C10,
C19 · CLAUDE.md A1, A2, A3, A9 · NQ-22, NQ-23.

Đây là chỗ A1 chỉ tới. HTTP handler của §7.2 ① chỉ `INSERT` hai message rồi
`enqueue('generate', assistant_message_id)` và trả `202`; toàn bộ phần đợi
model nằm ở đây. Thứ tự các bước bám đúng §7.2 ③ và **không** được đảo:

    ① đọc message + chủ sở hữu   → ② dựng ngữ cảnh từ ĐƯỜNG ĐI (A2, C11)
    ③ UPDATE status='streaming'  → ④ XADD start
    ⑤ vòng lặp stream: XADD delta/reasoning/tool_call/usage
                       + ghi heartbeat_at mỗi WORKER_HEARTBEAT_S (§7.6)
    ⑥ UPDATE messages (content/status/usage)  → ⑦ XADD done|error  → ⑧ EXPIRE

**Ba luật của file này:**

1. **Không có đường thoát nào không ghi event kết thúc (C19).** `finally` gọi
   `_dong_so` đúng một lần cho cả ba ngả: chạy xong, lỗi, và bị huỷ. Thiếu nó
   thì upstream đứt bất thường = client treo vô hạn, vì §7.4 cấm FE suy ra
   "đã xong" từ việc stream im lặng — im lặng nghĩa là *đang chờ*.

2. **Ghi Postgres TRƯỚC, `XADD done` SAU.** Client nhận `done` rồi tải lại
   trang sẽ đọc `messages.content`; đảo thứ tự là tạo một khe vài mili-giây
   trong đó câu trả lời đã "xong" nhưng lịch sử còn rỗng. Ghi hỏng thì event
   cuối là `error` mã `PERSIST_FAILED`, **không** phải `done`.

3. **`EXPIRE` ở cả hai ngả (C8).** Stream lỗi cũng là stream, cũng chiếm RAM,
   và cũng cần đọc lại được một lúc để FE hiện nút Retry.

**Chunk `done` của parser KHÔNG phải event `done` của SSE.** Parser phát
`kind="done"` khi upstream kết thúc bình thường (§9.1); worker chỉ *nhặt*
`finish_reason`/`usage` từ đó rồi đi tiếp. Event `done` ra dây ở bước ⑦, sau
khi Postgres đã ghi xong. Nhầm hai cái này là hai `done` trên cùng một stream.

**Chưa có ở Phase 1, cố ý:** `tools=None` (tool registry là §12/§13, Phase 6–7,
và §7.2 ghi vòng lặp tool ở đó); cờ huỷ `cancel:{amid}` của §7.5 là **T-1.9**;
`INSERT usage_events` + `cost_usd` là **T-2.12** (giá snapshot vào từng dòng
usage — A7, ADR-08); `raw_response` (§17.2) chưa có người ghi.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.config.catalog import ModelEntry, get_model
from app.config.settings import settings
from app.db.models import MessageStatus
from app.db.repositories import MessageRepository
from app.db.session import session_scope
from app.llm import context
from app.llm.client import Chunk, LLMClient, ToolCall, Usage
from app.streaming.events import (
    DeltaEvent,
    DoneEvent,
    ErrorCode,
    ErrorEvent,
    Event,
    ReasoningEvent,
    StartEvent,
    ToolCallEvent,
    UsageEvent,
)
from app.streaming.producer import StreamProducer

logger = logging.getLogger(__name__)

#: Khoá trong `ctx` của arq giữ `LLMClient` dùng chung cả vòng đời tiến trình.
#: `main.py` dựng nó ở `on_startup` và đóng ở `on_shutdown` — `AsyncOpenAI`
#: mang theo một connection pool gắn với event loop, tạo mới mỗi lượt chat là
#: vứt pool đi mỗi lượt (docstring `adapters/system.py`). Tên khoá ở đây chứ
#: không ở `main.py` để tránh import vòng: `main` đã import module này.
CTX_LLM_CLIENT = "llm_client"


class LoiSinh(Exception):
    """Lỗi đã phân loại được thành một `ErrorCode` của §7.4.

    Có kiểu riêng vì `_dong_so` phải phân biệt hai thứ: lỗi mình *biết tên*
    (ghi thẳng mã vào event và vào `messages.error_code`) và lỗi lạ (ghi
    `INTERNAL_ERROR` kèm traceback vào log — còn thấy mã đó nghĩa là còn một
    nhánh chưa ai đặt tên).
    """

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(f"{code.value}: {message}")
        self.code = code
        self.chi_tiet = message


@dataclass(slots=True)
class _KetQua:
    """Những gì gom được trong lúc stream. Sống đúng một lượt sinh.

    Là biến cục bộ truyền vào các hàm con chứ **không** phải thuộc tính của
    worker: §5.2 cấm worker "giữ state trong RAM giữa các job".
    """

    model_id: str | None = None
    chu: list[str] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage | None = None
    finish_reason: str | None = None
    loi: LoiSinh | None = None

    @property
    def content(self) -> str:
        """Nối mọi `delta` — phải **bằng byte-by-byte** với chuỗi client dựng.

        Nối bằng `str.join` chứ không cộng dồn theo byte: C9 là lỗi cắt một ký
        tự tiếng Việt làm đôi, và nó chỉ xuất hiện khi có chỗ nào đó làm việc
        với `bytes`. Ở đây không có chỗ nào như vậy.
        """
        return "".join(self.chu)


class _Nhip:
    """Bộ đếm "đã tới lúc ghi heartbeat chưa" (§7.6).

    Dựa trên `time.monotonic()` chứ không đếm số chunk: số chunk mỗi giây khác
    nhau cả trăm lần giữa `deepseek-flash` (333 chunk reasoning một lượt) và
    một model trả lời ngắn, nên "mỗi N chunk" cho ra nhịp tim lúc 2 giây lúc 2
    phút — và reaper §7.6 đo bằng giây.
    """

    __slots__ = ("_moi_giay", "_lan_cuoi")

    def __init__(self, moi_giay: float) -> None:
        self._moi_giay = moi_giay
        self._lan_cuoi = time.monotonic()

    def den_han(self) -> bool:
        now = time.monotonic()
        if now - self._lan_cuoi < self._moi_giay:
            return False
        self._lan_cuoi = now
        return True


async def generate(ctx: dict[str, Any], message_id: str) -> None:
    """Sinh câu trả lời cho `message_id` (message assistant đang `queued`).

    Nhận `message_id` chứ không nhận nội dung câu hỏi: §7.2 ① đã ghi cả hai
    message xuống Postgres trước khi enqueue, nên payload của job chỉ cần một
    khoá chính. Nhét nội dung vào payload sẽ tạo nguồn sự thật thứ hai nằm
    trong Redis — đúng thứ C5 cấm — và làm hàng đợi phình theo độ dài hội thoại.
    """
    mid = uuid.UUID(message_id)
    producer = StreamProducer(ctx["redis"], mid, ttl_s=settings.STREAM_TTL_S)
    ket_qua = _KetQua()

    logger.info("generate: bat dau %s (job=%s)", mid, ctx.get("job_id"))
    try:
        await _chay(ctx, mid, producer, ket_qua)
    except LoiSinh as loi:
        ket_qua.loi = loi
        logger.warning("generate: %s dung vi %s", mid, loi)
    except asyncio.CancelledError:
        # arq cắt job quá `GENERATE_TIMEOUT_S`, hoặc container nhận SIGTERM.
        # `finally` vẫn chạy để client không treo, rồi ném tiếp — nuốt
        # `CancelledError` là nói dối với vòng lặp sự kiện.
        ket_qua.loi = LoiSinh(ErrorCode.WORKER_TIMEOUT, "job bi huy giua chung")
        logger.warning("generate: %s bi huy giua chung", mid)
        raise
    except Exception as exc:  # noqa: BLE001 — C19: không có ngoại lệ nào được thoát ra ngoài mà không ghi event
        ket_qua.loi = LoiSinh(ErrorCode.INTERNAL_ERROR, type(exc).__name__)
        logger.exception("generate: %s loi khong phan loai duoc", mid)
    finally:
        # C19. Đường duy nhất ra khỏi hàm này đi qua đây.
        await _dong_so(mid, producer, ket_qua)


# ───────────────────────────── các bước ─────────────────────────────


async def _chay(
    ctx: dict[str, Any],
    mid: uuid.UUID,
    producer: StreamProducer,
    ket_qua: _KetQua,
) -> None:
    """Bước ① → ⑤ của §7.2 ③. Ném `LoiSinh` cho mọi ngả không đi tiếp được."""
    model_meta, wire_messages = await _chuan_bi(mid)
    ket_qua.model_id = model_meta.id

    await producer.emit(StartEvent(message_id=str(mid), model_id=model_meta.id))

    client: LLMClient = ctx[CTX_LLM_CLIENT]
    try:
        stream = await client.stream(
            model=model_meta.id,
            messages=wire_messages,
            # Tool registry là §12/§13 (Phase 6–7). `None` chứ không `[]`:
            # adapter đổi nó thành `omit`, model không có capability `tools`
            # (§9.4) thì không được thấy khoá đó (C18).
            tools=None,
            max_tokens=model_meta.max_output,
            temperature=settings.LLM_TEMPERATURE,
            extra={},
        )
    except Exception as exc:
        # `await` này là chỗ gửi request và nhận header, nên 401/400/429 nổ
        # tại đây chứ không đội lốt stream rỗng (điểm 1 docstring `client.py`).
        raise LoiSinh(ErrorCode.UPSTREAM_ERROR, f"{type(exc).__name__}: {exc}") from exc

    nhip = _Nhip(settings.WORKER_HEARTBEAT_S)
    try:
        async for chunk in stream:
            await _phat(producer, ket_qua, chunk)
            if nhip.den_han():
                await _ghi_heartbeat(mid)
    except LoiSinh:
        raise
    except Exception as exc:
        # Đứt giữa chừng: đây là ca chính của C19. Phần chữ đã gom trong
        # `ket_qua` vẫn được ghi xuống Postgres ở `_dong_so`.
        raise LoiSinh(ErrorCode.UPSTREAM_ERROR, f"{type(exc).__name__}: {exc}") from exc


async def _chuan_bi(mid: uuid.UUID) -> tuple[ModelEntry, list[dict[str, Any]]]:
    """Bước ① → ③: đọc message, dựng ngữ cảnh, đổi trạng thái sang `streaming`.

    Cả ba trong **một** session rồi đóng ngay: một lượt sinh có thể kéo mười
    phút, và giữ một kết nối Postgres suốt thời gian đó chỉ để chờ model là
    cách nhanh nhất làm cạn pool khi có vài người cùng chat.

    Dựng ngữ cảnh **trước** khi đổi trạng thái, đúng thứ tự §7.2: ngữ cảnh
    hỏng (lá không tồn tại, ngân sách không đủ) thì message còn nguyên
    `queued`, và `_dong_so` sẽ đánh nó `failed` kèm mã — chứ không để lại một
    message `streaming` mà không có ai sinh, tức món ăn của reaper §7.6.
    """
    async with session_scope() as session:
        repo = MessageRepository(session)

        owned = await repo.get_message_for_worker(mid)
        if owned is None:
            raise LoiSinh(ErrorCode.MESSAGE_NOT_FOUND, "message khong con trong DB")

        model_meta = get_model(owned.message.model_id or "")
        if model_meta is None:
            raise LoiSinh(
                ErrorCode.MODEL_UNKNOWN,
                f"model_id={owned.message.model_id!r} khong co trong catalog hoac da tat",
            )

        try:
            # A2/C11: ngữ cảnh đi từ lá ngược lên gốc, KHÔNG gom theo
            # `conversation_id`. `user_id` lấy từ chính hội thoại nên `get_path`
            # vẫn lọc quyền sở hữu trong câu SQL (§20).
            wire_messages = await context.build(
                session, owned.message.id, model_meta, user_id=owned.user_id
            )
        except context.EmptyPathError as exc:
            raise LoiSinh(ErrorCode.CONTEXT_EMPTY, str(exc)) from exc
        except context.BudgetTooSmallError as exc:
            raise LoiSinh(ErrorCode.CONTEXT_TOO_LARGE, str(exc)) from exc

        if not await repo.mark_streaming(mid, model_id=model_meta.id):
            # Không còn `queued`: một worker khác đã nhận, hoặc message đã
            # `failed`/`cancelled` trong lúc chờ hàng đợi. Bỏ lượt là đúng —
            # sinh tiếp là trả tiền lần hai cho cùng một câu hỏi (B-72).
            raise LoiSinh(
                ErrorCode.MESSAGE_NOT_FOUND,
                "message khong con o trang thai queued (worker khac da nhan?)",
            )
        await session.commit()

    return model_meta, wire_messages


async def _phat(producer: StreamProducer, ket_qua: _KetQua, chunk: Chunk) -> None:
    """Một `Chunk` của §9.1 → một event của §7.4. Map một-một, không bảng dịch.

    `Chunk.kind` cố ý trùng tên `event` của SSE (điểm 2 docstring `client.py`),
    nên hàm này không dịch tên — nó chỉ quyết định cái gì được **gom lại** để
    ghi Postgres, và chunk `done` thì không ra dây ở đây (xem docstring module).
    """
    match chunk.kind:
        case "delta":
            text = chunk.text or ""
            ket_qua.chu.append(text)
            await producer.emit(DeltaEvent(text=text))
        case "reasoning":
            text = chunk.text or ""
            # KHÔNG vào `ket_qua.chu`: reasoning đi vào cột `messages.reasoning`
            # và không bao giờ quay lại ngữ cảnh lượt sau (B-33, `context.py`).
            ket_qua.reasoning.append(text)
            await producer.emit(ReasoningEvent(text=text))
        case "tool_call" if chunk.tool_call is not None:
            ket_qua.tool_calls.append(chunk.tool_call)
            await producer.emit(
                ToolCallEvent(
                    call_id=chunk.tool_call.call_id,
                    name=chunk.tool_call.name,
                    arguments=chunk.tool_call.arguments,
                )
            )
        case "usage" if chunk.usage is not None:
            ket_qua.usage = chunk.usage
            await producer.emit(UsageEvent(usage=chunk.usage))
        case "done":
            # Chỉ NHẶT, không phát. Event `done` ra dây ở `_dong_so`, sau khi
            # Postgres đã ghi xong (luật 2 ở docstring module).
            ket_qua.finish_reason = chunk.finish_reason
            # Provider gửi `usage` ở chunk riêng **trước** `done` (C40); giữ số
            # cũ nếu `done` không mang gì, thay bằng số mới nếu có.
            ket_qua.usage = chunk.usage or ket_qua.usage
        case _:
            logger.warning("generate: bo qua chunk kind=%r khong co du lieu", chunk.kind)


async def _ghi_heartbeat(mid: uuid.UUID) -> None:
    """Nhịp §7.6. Hỏng thì **không** làm hỏng lượt sinh.

    Mất một nhịp tim không phải lý do để vứt một câu trả lời đang chảy: hậu quả
    xấu nhất là reaper §7.6 đánh nhầm `WORKER_LOST` sau `REAPER_STALE_S`, mà
    đó cũng chỉ xảy ra khi mất liên tiếp nhiều nhịp.
    """
    try:
        async with session_scope() as session:
            await MessageRepository(session).touch_heartbeat(mid)
            await session.commit()
    except Exception:  # noqa: BLE001 — xem docstring
        logger.warning("generate: %s khong ghi duoc heartbeat_at", mid, exc_info=True)


async def _dong_so(mid: uuid.UUID, producer: StreamProducer, ket_qua: _KetQua) -> None:
    """Bước ⑥ → ⑧: ghi Postgres, `XADD done|error`, `EXPIRE`. C19 + C8.

    Ba việc, ba `try` riêng. Cố ý: Postgres hỏng **không** được phép nuốt luôn
    event kết thúc, vì hậu quả của việc không ghi event là client treo vô hạn —
    nặng hơn hẳn một dòng lịch sử bị mất. Cùng lẽ đó, `EXPIRE` hỏng không được
    phép làm gì tới event đã phát.
    """
    loi = ket_qua.loi
    try:
        await _ghi_ket_qua(mid, ket_qua)
    except Exception:  # noqa: BLE001 — xem docstring
        logger.exception("generate: %s khong ghi duoc ket qua xuong Postgres", mid)
        if loi is None:
            # Chữ đã tới người dùng nhưng lịch sử thì không: nói thẳng bằng mã
            # riêng thay vì gửi `done` rồi để họ F5 ra một message rỗng.
            loi = LoiSinh(ErrorCode.PERSIST_FAILED, "UPDATE messages that bai")

    ket_thuc: Event = (
        DoneEvent(finish_reason=ket_qua.finish_reason, usage=ket_qua.usage)
        if loi is None
        else ErrorEvent(code=loi.code, message=loi.chi_tiet)
    )
    try:
        await producer.emit(ket_thuc)
    except Exception:  # noqa: BLE001 — xem docstring
        logger.exception("generate: %s khong XADD duoc event ket thuc (C19)", mid)

    try:
        await producer.expire()
    except Exception:  # noqa: BLE001 — xem docstring
        logger.exception("generate: %s khong EXPIRE duoc %s (C8)", mid, producer.key)

    logger.info(
        "generate: xong %s · %s · %d ky tu · finish_reason=%s · usage=%s",
        mid,
        "loi " + loi.code.value if loi is not None else "ok",
        len(ket_qua.content),
        ket_qua.finish_reason,
        ket_qua.usage,
    )


async def _ghi_ket_qua(mid: uuid.UUID, ket_qua: _KetQua) -> None:
    """`UPDATE messages` — lần ghi DUY NHẤT vào `content` (§17.2, C5).

    `tool_calls` ghi bằng `ToolCall.to_wire()`, tức đúng khối `tool_calls` của
    dây OpenAI (NQ-22/B-68). Đó là hình dạng mà `llm/context.py::_to_wire` đọc
    lại **nguyên văn** ở lượt sau; ghi lệch thì lượt sau mới vỡ, và vỡ bằng
    `400 invalid request` không nói lý do.
    """
    loi = ket_qua.loi
    usage = ket_qua.usage
    async with session_scope() as session:
        await MessageRepository(session).finish_generation(
            mid,
            status=MessageStatus.COMPLETED if loi is None else MessageStatus.FAILED,
            content=ket_qua.content,
            reasoning="".join(ket_qua.reasoning) or None,
            tool_calls=[tc.to_wire() for tc in ket_qua.tool_calls] or None,
            finish_reason=ket_qua.finish_reason,
            error_code=loi.code.value if loi is not None else None,
            prompt_tokens=usage.prompt_tokens if usage is not None else None,
            completion_tokens=usage.completion_tokens if usage is not None else None,
        )
        await session.commit()
