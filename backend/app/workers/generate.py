"""Job `generate` — vòng đời một câu trả lời, phía worker (§7.2 bước ③).

KH tham chiếu: §7.2, §7.4, §7.6, §9.1, §9.6, ADR-01, ADR-02, C5, C8, C9, C10,
C19 · CLAUDE.md A1, A2, A3, A9 · NQ-22, NQ-23.

Đây là chỗ A1 chỉ tới. HTTP handler của §7.2 ① chỉ `INSERT` hai message rồi
`enqueue('generate', assistant_message_id)` và trả `202`; toàn bộ phần đợi
model nằm ở đây. Thứ tự các bước bám đúng §7.2 ③ và **không** được đảo:

    ① đọc message + chủ sở hữu   → ② dựng ngữ cảnh từ ĐƯỜNG ĐI (A2, C11)
    ③ UPDATE status='streaming'  → ④ XADD start
    ⑤ vòng lặp stream: XADD delta/reasoning/tool_call/usage
                       + kiểm cờ huỷ mỗi KIEM_HUY_MOI_N_CHUNK chunk (§7.5)
    ⑥ UPDATE messages (content/status/usage)  → ⑦ XADD done|error  → ⑧ EXPIRE

    ╰─ song song từ ③ tới ⑤: task `_nhip_tim` ghi `heartbeat_at` mỗi
       `WORKER_HEARTBEAT_S` (§7.6), ĐỘC LẬP với việc có chunk hay không (B-122)

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

**Huỷ giữa chừng là đường thoát thứ tư, và nó KHÔNG phải một lỗi (§7.5).**
Ba ngả kia kết thúc bằng `done` (xong), `error` (hỏng) hoặc `error` (bị arq
cắt). Ngả huỷ kết thúc bằng `done` mang `finish_reason='cancelled'`, và
`messages.status` là `cancelled` chứ không phải `failed`: người dùng chủ động
bấm Dừng thì phần chữ họ đã đọc là một câu trả lời ngắn, không phải một sự cố.
Đó cũng là lý do `llm/context.py::USABLE_STATUSES` nhận `cancelled` — phần đã
sinh vẫn đi vào ngữ cảnh lượt sau, vì người dùng đã nhìn thấy nó.

**Chưa có ở Phase 1, cố ý:** `tools=None` (tool registry là §12/§13, Phase 6–7,
và §7.2 ghi vòng lặp tool ở đó); `INSERT usage_events` + `cost_usd` là
**T-2.12** (giá snapshot vào từng dòng usage — A7, ADR-08); `raw_response`
(§17.2) chưa có người ghi. **Trên đường huỷ, `usage` là `None`** và hai cột
`messages.prompt_tokens`/`completion_tokens` để NULL: cả bốn provider đang bật
chỉ gửi `usage` ở **chunk cuối cùng** (đo lại trên fixture của T-1.3:
135/135 · 533/533 · 11/11 · 602/602), mà huỷ nghĩa là bỏ stream trước chunk
đó. Điền một con số tự đếm vào hai cột ấy sẽ biến "không đo được" thành "đo
được" — đúng thứ NQ-23 cấm — trong khi chưa có cột `cost_confidence` nào để
đánh dấu. Việc đếm ước tính cho phần đã huỷ thuộc **T-2.12** cùng với
`cost_confidence='low'` (B-67, B-94); ở Phase 1 nó là **một dòng log**, đúng
chữ của DoD T-1.9.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from typing import Any

from app.config.catalog import ModelEntry, get_model
from app.config.settings import settings
from app.db.models import MessageStatus
from app.db.repositories import MessageRepository
from app.db.session import session_scope
from app.llm import context
from app.llm.client import Chunk, LLMClient, ToolCall, Usage
from app.streaming.cancel import FINISH_REASON_CANCELLED, da_yeu_cau_huy
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

#: §7.5 viết thẳng "mỗi 8 chunk kiểm EXISTS cancel:{amid}". Đếm theo **chunk**
#: chứ không theo giây như `_nhip_tim` của heartbeat, và khác biệt đó là cố ý: nhịp
#: tim trả lời một câu hỏi đo bằng giây (reaper §7.6 so `heartbeat_at` với
#: `now()`), còn nút Dừng trả lời câu "bao nhiêu chữ nữa thì người dùng thôi
#: thấy chữ chảy" — đo bằng chunk là đo đúng thứ họ nhìn.
#:
#: **Không** phải biến `Settings`: đây là nhịp hỏi nội bộ của một vòng lặp, cùng
#: loại với `SO_BAN_GHI_MOI_LAN` của `streaming/consumer.py`, chứ không phải
#: một *giới hạn* vận hành như `CANCEL_TTL_S` (A3 liệt "tên model, giá, giới
#: hạn, URL provider, màu sắc"). Giá của nó: một `EXISTS` cho mỗi 8 chunk, tức
#: ~66 lệnh cho một câu trả lời dài của `deepseek-flash` (533 chunk đo ở T-1.3).
KIEM_HUY_MOI_N_CHUNK = 8


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
    #: §7.5 — người dùng đã bấm Dừng và vòng lặp đã thoát vì thế. Cờ RIÊNG chứ
    #: không phải `finish_reason == "cancelled"`: ba giá trị `finish_reason`
    #: kia đến từ provider, và một ngày nào đó provider trả đúng chuỗi ấy thì
    #: `messages.status` sẽ thành `cancelled` cho một lượt không ai huỷ.
    bi_huy: bool = False

    @property
    def content(self) -> str:
        """Nối mọi `delta` — phải **bằng byte-by-byte** với chuỗi client dựng.

        Nối bằng `str.join` chứ không cộng dồn theo byte: C9 là lỗi cắt một ký
        tự tiếng Việt làm đôi, và nó chỉ xuất hiện khi có chỗ nào đó làm việc
        với `bytes`. Ở đây không có chỗ nào như vậy.
        """
        return "".join(self.chu)


async def _vong_nhip_tim(mid: uuid.UUID) -> None:
    """Ghi `messages.heartbeat_at` mỗi `WORKER_HEARTBEAT_S` cho tới khi bị huỷ.

    Ngủ **trước** rồi mới ghi: `mark_streaming` vừa đặt `heartbeat_at = now()`
    ngay trước khi vòng này chạy, nên một lần ghi tức thì chỉ tốn một
    round-trip để viết lại đúng con số vừa có.

    Không có `try/except` quanh vòng lặp: `_ghi_heartbeat` đã tự nuốt mọi lỗi
    của nó rồi (một blip Postgres không được phép giết nhịp tim), nên ngoại lệ
    thoát tới đây chỉ có thể là `CancelledError` — và cái đó phải bay tiếp.
    """
    while True:
        await asyncio.sleep(settings.WORKER_HEARTBEAT_S)
        await _ghi_heartbeat(mid)


@asynccontextmanager
async def _nhip_tim(mid: uuid.UUID) -> AsyncIterator[None]:
    """Nhịp tim §7.6 chạy như một task ĐỘC LẬP, không bám vào vòng chunk (B-122).

    **Vì sao không còn là một bộ đếm trong vòng lặp.** Bản cũ (`_Nhip`) đo bằng
    `time.monotonic()` — đúng — nhưng chỗ *hỏi* nó lại nằm bên trong
    `async for chunk in stream`, nên giữa `mark_streaming` và chunk đầu tiên
    **không một nhịp nào được ghi**. Hệ quả là `REAPER_STALE_S` kiêm luôn một
    vai thứ hai mà không ai khai: *TTFT tối đa trước khi reaper giết một lượt
    sinh còn sống*. Với `nr-gemini-flash` đo được TTFT p95 **43.7 s** ngày xấu
    (B-103) và `LLM_REQUEST_TIMEOUT_S = 600 s` cho phép model im lặng tới mười
    phút, đó là một quả mìn hẹn giờ — và nó cũng là thứ chặn việc hạ
    `REAPER_STALE_S` để đóng B-100/B-116.

    Tách ra rồi thì `REAPER_STALE_S` thuần một nghĩa: "worker còn sống không".

    Task bị huỷ trong `finally`, nên nó **không bao giờ** sống lâu hơn lượt
    sinh. Kể cả nếu lọt, `touch_heartbeat` chỉ khớp `status='streaming'` nên
    một nhịp muộn rơi vào message đã khép là no-op — hai lớp, vì một nhịp tim
    mồ côi sẽ làm reaper mù đúng ca nó sinh ra để bắt.
    """
    task = asyncio.create_task(_vong_nhip_tim(mid), name=f"nhip-tim:{mid}")
    try:
        yield
    finally:
        task.cancel()
        # `await` để chắc chắn task đã dừng hẳn trước khi hàm thoát: bỏ qua
        # bước này thì nó có thể còn ghi thêm một nhịp *sau* `_dong_so`.
        with suppress(asyncio.CancelledError):
            await task


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

    # Nhịp tim mở NGAY sau `_chuan_bi` (nơi `mark_streaming` chạy) chứ không
    # đợi chunk đầu: quãng `client.stream(...)` bên dưới chính là TTFT, và đó
    # đúng là quãng mà bản cũ để trống — xem `_nhip_tim` (B-122).
    async with _nhip_tim(mid):
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

        so_chunk = 0
        try:
            async for chunk in stream:
                # `_phat` chạy TRƯỚC phép kiểm: chunk thứ 8 vẫn ra dây và vẫn vào
                # `ket_qua.chu`. §7.5 đòi "vẫn lưu phần đã sinh", mà phần đã sinh
                # tính tới mẩu cuối cùng provider đã gửi — bỏ nó đi là để màn hình
                # và `messages.content` nói hai chuyện khác nhau.
                await _phat(producer, ket_qua, chunk)
                so_chunk += 1
                if so_chunk % KIEM_HUY_MOI_N_CHUNK == 0 and await _bi_huy(ctx, mid):
                    _dung_vi_huy(mid, ket_qua, so_chunk)
                    break
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


async def _bi_huy(ctx: dict[str, Any], mid: uuid.UUID) -> bool:
    """`EXISTS cancel:{mid}` (§7.5). Hỏng thì **không** làm hỏng lượt sinh.

    Cùng lý lẽ với `_ghi_heartbeat`, nhưng ở đây cái giá của việc không nuốt
    còn rõ hơn: để ngoại lệ thoát ra thì `_chay` bọc nó thành
    `UPSTREAM_ERROR`, tức người dùng đọc được "provider lỗi" cho một sự cố
    hoàn toàn nằm ở phía mình. Mất một lần hỏi nghĩa là nút Dừng ăn muộn
    `KIEM_HUY_MOI_N_CHUNK` chunk nữa, và cờ vẫn còn đó (`CANCEL_TTL_S`).
    """
    try:
        return await da_yeu_cau_huy(ctx["redis"], mid)
    except Exception:  # noqa: BLE001 — xem docstring
        logger.warning("generate: %s khong kiem duoc co huy", mid, exc_info=True)
        return False


def _dung_vi_huy(mid: uuid.UUID, ket_qua: _KetQua, so_chunk: int) -> None:
    """Ghi nhận ngả huỷ vào `ket_qua` — và **dòng log** mà DoD T-1.9 đòi.

    Không `raise`: huỷ không phải lỗi (xem docstring module). Đặt hai trường
    rồi để `break` ở `_chay` đưa luồng về `_dong_so`, nơi nó ra dây thành
    `done` mang `finish_reason='cancelled'` đúng như §7.5 viết.

    Dòng log này là thứ thay cho `usage_events` ở Phase 1 — DoD T-1.9 ghi
    *"ở phase này kiểm bằng log"*. Nó in cả `usage` (gần như luôn là `None`,
    xem docstring module) để chỗ trống ấy **nhìn thấy được** trong log thay vì
    im lặng: T-2.12 là người lấp nó bằng `count_text()` + `cost_confidence`.
    """
    ket_qua.bi_huy = True
    ket_qua.finish_reason = FINISH_REASON_CANCELLED
    logger.info(
        "generate: %s NGUOI DUNG HUY sau %d chunk · %d ky tu da sinh · "
        "usage tu provider: %s · usage_events: chua ghi (T-2.12, B-94)",
        mid,
        so_chunk,
        len(ket_qua.content),
        ket_qua.usage,
    )


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


def _trang_thai_cuoi(ket_qua: _KetQua) -> MessageStatus:
    """Ba ngả của §7.2 ③ + §7.5 → một giá trị của `message_status`.

    **Lỗi thắng cờ huỷ.** Trúng cả hai (bấm Dừng rồi Postgres hỏng ngay sau
    đó) thì `failed` là câu đúng hơn: có một sự cố cần người đọc log biết, còn
    `cancelled` sẽ nói rằng mọi thứ đã diễn ra như người dùng muốn.
    """
    if ket_qua.loi is not None:
        return MessageStatus.FAILED
    if ket_qua.bi_huy:
        return MessageStatus.CANCELLED
    return MessageStatus.COMPLETED


async def _ghi_ket_qua(mid: uuid.UUID, ket_qua: _KetQua) -> None:
    """`UPDATE messages` — lần ghi DUY NHẤT vào `content` (§17.2, C5).

    Đường huỷ (§7.5) đi qua đúng hàm này chứ không có nhánh riêng: nó ghi
    `status='cancelled'`, `finish_reason='cancelled'`, và `content` là **phần
    đã sinh được** — cùng một câu lệnh, cùng một chỗ. `error_code` để NULL vì
    không có lỗi nào xảy ra.

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
            status=_trang_thai_cuoi(ket_qua),
            content=ket_qua.content,
            reasoning="".join(ket_qua.reasoning) or None,
            tool_calls=[tc.to_wire() for tc in ket_qua.tool_calls] or None,
            finish_reason=ket_qua.finish_reason,
            error_code=loi.code.value if loi is not None else None,
            prompt_tokens=usage.prompt_tokens if usage is not None else None,
            completion_tokens=usage.completion_tokens if usage is not None else None,
        )
        await session.commit()
