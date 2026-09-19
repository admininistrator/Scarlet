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

**Ghi sổ là bước ⑥.5, giữa Postgres và `XADD done` (T-2.12).** `app/quota/
meter.py` tính `cost_usd`, `INSERT usage_events` với `price_snapshot` (A7,
ADR-08) rồi `ZADD` hai cửa sổ của §10.3. Nó chạy trên **cả ba** ngả khép sổ —
xong, huỷ, lỗi giữa chừng — vì cả ba đều đã tiêu tiền thật. Thứ tự bắt buộc:
ghi sổ **trước** `XADD done`, vì event `done` mang theo `cost_usd` (§7.4,
B-78); ngược lại thì con số tiền lên dây trước khi nó có chỗ nào để đối chiếu.

**Trên đường huỷ, `usage` của provider là `None` — và điều đó KHÔNG đổi từ
T-2.12.** Cả bốn provider đang bật chỉ gửi `usage` ở **chunk cuối cùng** (đo
lại trên fixture của T-1.3: 135/135 · 533/533 · 11/11 · 602/602), mà huỷ nghĩa
là bỏ stream trước chunk đó. Hai cột `messages.prompt_tokens`/
`completion_tokens` vì vậy vẫn để **NULL** (NQ-26): chúng chỉ chứa số thật của
provider, và nhét một ước tính `tiktoken` vào đó là biến "không đo được" thành
"đo được" (NQ-23). Số tự đếm đi vào `usage_events` — nơi **duy nhất** có cột
`cost_confidence` để đánh dấu nó là `low` (B-67, B-94). Dòng log
`NGUOI DUNG HUY …` của Phase 1 nay in thêm con số đã ghi sổ.

**Đường BYOK là bước ①.5, ngay sau khi đọc được chủ sở hữu (T-2.15, §10.5).**
`llm/credentials.py` trả lời "lượt này tiêu tiền của ai", và câu trả lời quyết
định **hai** thứ, không phải một: adapter nào gọi model (§9.1 — `ByokAdapter`
trỏ thẳng `provider.base_url`, `SystemAdapter` qua LiteLLM) và `key_source`
nào đi vào `usage_events` ở bước ⑥.5 (§10.5 — `byok` thì **không** `ZADD` vào
hai cửa sổ quota). Cùng hàm mà `api/v1/messages.py` đã hỏi lúc nhận request,
nên hai tiến trình không thể quyết hai kiểu — xem docstring `credentials.py`
cho khe đua giữa hai lần hỏi và vì sao nó được chấp nhận.

**Chưa có, cố ý:** `tools=None` (tool registry là §12/§13, Phase 6–7, và §7.2
ghi vòng lặp tool ở đó); `raw_response` (§17.2) chưa có người ghi — hoãn sang
Phase 6, khi tool-call bắt đầu vỡ thật và hình dạng "response cuối" mới kiểm
chứng được (B-79).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.config.catalog import ModelEntry, get_model
from app.config.settings import settings
from app.db.models import KeySource, MessageStatus
from app.db.repositories import MessageRepository
from app.db.session import session_scope
from app.llm import context
from app.llm.adapters.byok import ByokAdapter
from app.llm.client import Chunk, LLMClient, ToolCall, Usage
from app.llm.credentials import Credential, resolve_credential
from app.quota import meter
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

    #: Model đã tra được trong catalog. Thay cho `model_id` trần của T-1.6:
    #: bước ghi sổ (T-2.12) cần cả `provider`, `pricing_mode` và bảng giá, và
    #: tra lại catalog lần thứ hai ở `_dong_so` là mời một kết quả khác — một
    #: `POST /admin/catalog/reload` chen vào giữa lượt sinh là đủ.
    model: ModelEntry | None = None
    #: Chủ hội thoại. `messages` không có cột `user_id` (Phụ lục A) nên con số
    #: này chỉ lấy được một lần, ở `_chuan_bi`, và `usage_events.user_id` là
    #: cột NOT NULL cần nó.
    user_id: uuid.UUID | None = None
    #: Đúng danh sách message đã gửi lên. Giữ **tham chiếu**, không phải bản
    #: sao: `_chay` vẫn đang giữ chính list đó suốt lượt sinh, nên nó không tốn
    #: thêm gì. Chỉ được đọc trên đường lùi C40 — khi provider không báo
    #: `usage` thì đây là thứ duy nhất đếm lại được phần prompt (B-67, B-94).
    sent: list[dict[str, Any]] = field(default_factory=list)
    #: Thời điểm **gọi model**, dùng để tra bảng giá theo khung giờ (A7, B-35).
    #: KHÁC thời điểm ghi sổ: một lượt sinh mười phút có thể bắt đầu lúc 16:58
    #: giờ cao điểm và kết thúc lúc 17:08 giờ thường — giá phải là giá 16:58.
    started_at: datetime | None = None
    #: Credential nào trả tiền cho lượt này (§10.5, T-2.15). Mặc định là
    #: `system` chứ không `None`: một lượt sinh chết **trước** `_chuan_bi`
    #: không ghi sổ gì cả (xem `billable`), nên giá trị này chỉ có nghĩa khi
    #: nó đã được điền — và mặc định chặt hơn (trừ quota) là mặc định đúng
    #: chiều nếu có ngày nào đó một nhánh quên điền.
    key_source: KeySource = KeySource.SYSTEM
    #: Do `_record_usage` điền ở bước ⑥.5; đi tiếp lên event `done` (§7.4,
    #: B-78). `None` = chưa ghi sổ được, và khi đó khoá `cost_usd` **vắng mặt**
    #: trên dây chứ không bằng 0.
    cost_usd: Decimal | None = None
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

    @property
    def billable(self) -> bool:
        """Có gì để ghi sổ không — cửa duy nhất vào bước ⑥.5.

        Hai điều kiện, và cả hai đều là "đã thật sự chạm tới provider chưa".

        `model`/`user_id`/`started_at` cùng được điền một lần ngay sau
        `_chuan_bi`, nên thiếu một cái nghĩa là lượt sinh chết **trước** khi
        gọi model: message không còn trong DB, model đã tắt trong catalog,
        ngữ cảnh dựng không nổi, hoặc một worker khác đã nhận job. Không token
        nào được tiêu, nên một dòng sổ 0 đồng ở đó chỉ là rác — và rác trong
        sổ cái làm hỏng đúng phép đếm mà DoD dòng 1 đo ("**đúng 1** dòng cho
        một lượt chat").

        Vế sau là ca `401` nổ ngay tại `await client.stream(...)`: model đã tra
        được nhưng request bị từ chối trước khi sinh một chữ nào. Có `usage`,
        có chữ, có reasoning hoặc có tool call thì mới có cái để tính tiền.
        `reasoning` đứng riêng vì nó là ca **đã quan sát được**: huỷ
        `deepseek-flash` trong 112 chunk đầu cho `content` rỗng mà `reasoning`
        thì không (B-97) — và provider vẫn tính tiền phần đó (B-33).
        """
        if self.model is None or self.user_id is None or self.started_at is None:
            return False
        return bool(self.usage or self.chu or self.reasoning or self.tool_calls)


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
        await _dong_so(ctx, mid, producer, ket_qua)


# ───────────────────────────── các bước ─────────────────────────────


async def _chay(
    ctx: dict[str, Any],
    mid: uuid.UUID,
    producer: StreamProducer,
    ket_qua: _KetQua,
) -> None:
    """Bước ① → ⑤ của §7.2 ③. Ném `LoiSinh` cho mọi ngả không đi tiếp được."""
    model_meta, wire_messages, user_id, credential = await _chuan_bi(mid)
    ket_qua.model = model_meta
    ket_qua.user_id = user_id
    ket_qua.sent = wire_messages
    ket_qua.key_source = credential.key_source

    # Nhịp tim mở NGAY sau `_chuan_bi` (nơi `mark_streaming` chạy) chứ không
    # đợi chunk đầu: quãng `client.stream(...)` bên dưới chính là TTFT, và đó
    # đúng là quãng mà bản cũ để trống — xem `_nhip_tim` (B-122).
    async with _nhip_tim(mid), _turn_client(ctx, credential) as client:
        await producer.emit(StartEvent(message_id=str(mid), model_id=model_meta.id))

        # Mốc giá của A7: bảng giá dùng để ghi sổ là bảng giá của **lúc gọi**,
        # không phải lúc lượt sinh kết thúc. Đặt ngay trước `await` chứ không
        # ở đầu `_chay`: quãng `_chuan_bi` có thể mất vài chục mili-giây vì
        # recursive CTE của §8.3, và mốc giá phải là mốc gửi request.
        ket_qua.started_at = datetime.now(UTC)
        try:
            stream = await client.stream(
                # Alias LiteLLM hay tên gốc của provider — tuỳ credential, và
                # `Credential` là chỗ biết cả hai (T-2.15).
                model=credential.model_name(model_meta),
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


@asynccontextmanager
async def _turn_client(ctx: dict[str, Any], credential: Credential) -> AsyncIterator[LLMClient]:
    """`LLMClient` của lượt này — dùng chung (system) hay dựng riêng (BYOK). §9.1.

    Hai vòng đời khác nhau, và khác biệt ấy là lý do có context manager này
    thay vì một dòng `ctx[CTX_LLM_CLIENT]`:

    * **system** — một instance cho cả tiến trình, dựng ở `main.on_startup`,
      đóng ở `on_shutdown`. **Không** đóng ở đây: đóng nó là vứt connection
      pool của mọi lượt sinh sau.
    * **BYOK** — credential thuộc về một người dùng cụ thể, nên instance chỉ
      được sống đúng một lượt (xem docstring `adapters/byok.py`). `finally`
      đóng nó trên **mọi** đường thoát, kể cả huỷ giữa chừng và
      `CancelledError` của arq: một `AsyncOpenAI` không đóng để lại kết nối
      treo tới lúc timeout, và với BYOK thì đó là kết nối *mang khoá của
      người dùng* nằm mở.
    """
    if credential.provider is None or credential.api_key is None:
        yield ctx[CTX_LLM_CLIENT]
        return

    adapter = ByokAdapter.for_provider(credential.provider, api_key=credential.api_key)
    try:
        yield adapter
    finally:
        await adapter.close()


async def _chuan_bi(
    mid: uuid.UUID,
) -> tuple[ModelEntry, list[dict[str, Any]], uuid.UUID, Credential]:
    """Bước ① → ③ (+ ①.5): đọc message, chọn credential, dựng ngữ cảnh, `streaming`.

    Cả bốn trong **một** session rồi đóng ngay: một lượt sinh có thể kéo mười
    phút, và giữ một kết nối Postgres suốt thời gian đó chỉ để chờ model là
    cách nhanh nhất làm cạn pool khi có vài người cùng chat. `resolve_credential`
    đi nhờ đúng session ấy (T-2.15) thay vì mở một kết nối thứ hai cho một câu
    `SELECT` một hàng.

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

        # ①.5 §10.5 — ai trả tiền cho lượt này. **Trước** `mark_streaming`
        # chứ không sau: cả hai ngả lùi của nó (khoá bị xoá, khoá không giải
        # mã được) chỉ là "đi bằng system key", nhưng một ngoại lệ Postgres ở
        # đây mà đứng sau `mark_streaming` sẽ để lại một message `streaming`
        # không ai sinh — đúng món ăn của reaper §7.6.
        credential = await resolve_credential(session, user_id=owned.user_id, model=model_meta)

        if not await repo.mark_streaming(mid, model_id=model_meta.id):
            # Không còn `queued`: một worker khác đã nhận, hoặc message đã
            # `failed`/`cancelled` trong lúc chờ hàng đợi. Bỏ lượt là đúng —
            # sinh tiếp là trả tiền lần hai cho cùng một câu hỏi (B-72).
            raise LoiSinh(
                ErrorCode.MESSAGE_NOT_FOUND,
                "message khong con o trang thai queued (worker khac da nhan?)",
            )
        await session.commit()

    # `user_id` đi ra cùng ba thứ kia vì đây là chỗ DUY NHẤT đọc được nó:
    # `messages` không có cột `user_id` (Phụ lục A), nó nằm ở hội thoại chứa
    # message. Bước ghi sổ ⑥.5 cần nó cho `usage_events.user_id`.
    return model_meta, wire_messages, owned.user_id, credential


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

    Dòng log này ra đời ở Phase 1 để thay cho `usage_events` khi chưa ai ghi
    bảng đó (DoD T-1.9: *"ở phase này kiểm bằng log"*). Từ T-2.12 nó **không**
    còn là nguồn duy nhất — `_record_usage` ở bước ⑥.5 mới là — nhưng vẫn giữ,
    và vẫn in `usage` của provider (gần như luôn `None` trên ngả này, B-94) vì
    đó là chỗ đọc log so được hai con số: cái provider **không** báo, và cái
    meter đã đếm thay ở dòng `ghi so` ngay sau.
    """
    ket_qua.bi_huy = True
    ket_qua.finish_reason = FINISH_REASON_CANCELLED
    logger.info(
        "generate: %s NGUOI DUNG HUY sau %d chunk · %d ky tu da sinh · "
        "usage tu provider: %s · phan da sinh se duoc ghi so o buoc ⑥.5",
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


async def _dong_so(
    ctx: dict[str, Any], mid: uuid.UUID, producer: StreamProducer, ket_qua: _KetQua
) -> None:
    """Bước ⑥ → ⑧: ghi Postgres, ghi sổ, `XADD done|error`, `EXPIRE`. C19 + C8.

    Bốn việc, bốn `try` riêng. Cố ý: Postgres hỏng **không** được phép nuốt
    luôn event kết thúc, vì hậu quả của việc không ghi event là client treo vô
    hạn — nặng hơn hẳn một dòng lịch sử bị mất. Cùng lẽ đó, `EXPIRE` hỏng không
    được phép làm gì tới event đã phát.

    **Ghi sổ (⑥.5) hỏng thì event kết thúc vẫn là `done`, KHÔNG phải `error`.**
    Khác hẳn ca `_ghi_ket_qua` hỏng ngay trên. Hai hỏng, hai người chịu hậu
    quả: mất `messages.content` là mất **câu trả lời của người dùng** — họ F5
    ra một message rỗng, nên phải nói thẳng bằng `PERSIST_FAILED`. Mất một dòng
    `usage_events` là mất **một khoản trong sổ của mình**: người dùng đã đọc
    xong câu trả lời và không có gì để họ làm khác đi. Đổi nó thành một lỗi đỏ
    trên màn hình là bắt họ trả giá cho một sự cố kế toán. Dòng `logger.
    exception` ở `_record_usage` là chỗ khai, và `rebuild_quota` của T-2.13 là
    đường vá.
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

    # ⑥.5 — §10.2 vế SAU. Chạy TRƯỚC `XADD` vì `cost_usd` đi trên event `done`.
    await _record_usage(ctx, mid, ket_qua)

    ket_thuc: Event = (
        DoneEvent(
            finish_reason=ket_qua.finish_reason,
            usage=ket_qua.usage,
            cost_usd=ket_qua.cost_usd,
        )
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
        "generate: xong %s · %s · %d ky tu · finish_reason=%s · usage=%s · cost_usd=%s",
        mid,
        "loi " + loi.code.value if loi is not None else "ok",
        len(ket_qua.content),
        ket_qua.finish_reason,
        ket_qua.usage,
        ket_qua.cost_usd,
    )


async def _record_usage(ctx: dict[str, Any], mid: uuid.UUID, ket_qua: _KetQua) -> None:
    """Bước ⑥.5 — §10.2 vế SAU. Điền `ket_qua.cost_usd`; hỏng thì **không** ném.

    Gọi trên **cả ba** ngả khép sổ, vì cả ba đều đã tiêu tiền thật:

    * xong bình thường — `usage` của provider, `cost_confidence='exact'` nếu
      model `metered`;
    * huỷ giữa chừng (§7.5) — `usage` là `None` **luôn luôn** (B-94), meter tự
      đếm phần đã sinh bằng `tiktoken` rồi ghi `low`;
    * lỗi giữa chừng (C19) — upstream đứt sau khi đã chảy được một đoạn; phần
      chữ ấy provider đã tính tiền, nên nó phải có mặt trong sổ.

    Ngả thứ tư — chết **trước** khi gọi model — không ghi gì, và `billable` là
    chỗ chặn (xem docstring của nó).

    **BYOK vẫn ghi sổ, chỉ không trừ quota (§10.5, T-2.15).** Dòng
    `usage_events` có mặt để người dùng tự xem chi tiêu của mình; thứ vắng
    mặt là hai lệnh `ZADD` của §10.3, và chỗ quyết là `quota/meter.py`.

    **Nuốt mọi ngoại lệ**, cùng lý lẽ với `_ghi_heartbeat` và `_bi_huy` nhưng
    đắt hơn: ở đây cái mất là một khoản trong sổ cái, không phải một nhịp tim.
    Vẫn nuốt, vì thay thế duy nhất là để một lỗi Redis/Postgres biến một câu
    trả lời đã sinh xong thành một lỗi đỏ trên màn hình người dùng — xem
    docstring `_dong_so`. `logger.exception` là chỗ khai, và nó ghi đủ
    `user_id`/`model` để người đọc log vá lại bằng tay được.
    """
    if not ket_qua.billable:
        return
    # `billable` đã khẳng định ba trường này khác `None`; khẳng định lại ở đây
    # cho mypy thay vì `assert`, vì `assert` bị `python -O` xoá mất.
    model = ket_qua.model
    user_id = ket_qua.user_id
    started_at = ket_qua.started_at
    if model is None or user_id is None or started_at is None:  # pragma: no cover
        return

    try:
        async with session_scope() as session:
            record = await meter.record_usage(
                session,
                ctx["redis"],
                user_id=user_id,
                message_id=mid,
                model=model,
                at=started_at,
                now=time.time(),
                usage=ket_qua.usage,
                sent=ket_qua.sent,
                content=ket_qua.content,
                reasoning="".join(ket_qua.reasoning),
                tool_calls=[tc.to_wire() for tc in ket_qua.tool_calls] or None,
                # §10.5 — `byok` thì `record_usage` ghi dòng sổ nhưng KHÔNG
                # `ZADD` hai cửa sổ quota. Luật nằm ở `quota/meter.py`, chỗ
                # duy nhất biết cả hai vế; ở đây chỉ chở giá trị (B-157).
                key_source=ket_qua.key_source,
            )
            await session.commit()
    except Exception:  # noqa: BLE001 — xem docstring
        logger.exception(
            "generate: %s KHONG ghi duoc usage_events (user=%s model=%s) — "
            "quota KHONG bi tru cho luot nay, va cost_usd se vang mat tren event done",
            mid,
            user_id,
            model.id,
        )
        return

    ket_qua.cost_usd = record.cost_usd
    logger.info(
        "generate: %s ghi so %s · %s · key_source=%s · in=%d out=%d cached=%d · %s USD · %s",
        mid,
        record.id,
        model.id,
        ket_qua.key_source.value,
        record.spent.prompt_tokens,
        record.spent.completion_tokens,
        record.spent.cached_tokens,
        record.cost_usd,
        record.confidence.value
        + ("" if record.spent.measured else " (tiktoken tu dem, provider khong bao usage)"),
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
