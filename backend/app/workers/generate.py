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
    ⑥ UPDATE messages (content/status/usage)  → ⑥.2 artifacts (T-5.1)
                                              → ⑦ XADD done|error  → ⑧ EXPIRE

    ╰─ song song từ ③ tới ⑤: task `_heartbeat` ghi `heartbeat_at` mỗi
       `WORKER_HEARTBEAT_S` (§7.6), ĐỘC LẬP với việc có chunk hay không (B-122)

**Ba luật của file này:**

1. **Không có đường thoát nào không ghi event kết thúc (C19).** `finally` gọi
   `_close_ledger` đúng một lần cho cả ba ngả: chạy xong, lỗi, và bị huỷ. Thiếu nó
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

**Mức suy luận đi từ hàng `messages`, không từ payload của job (T-S.6, §24.2b·S4).**
API đã giải mức (body › đã nhớ › mặc định) và ghi nó lên hàng `queued`; bước ①
đọc lại, `catalog.reasoning_to_send` chốt mức sẽ GỬI, và `mark_streaming` ghi
đè cột bằng đúng mức ấy. Ba thứ của mức đổi request ở bước ④ và **chỉ** ở đó:
`params` (hoặc `byok_params` trên đường BYOK) trộn vào `extra`, `alias` thay
tên model gửi LiteLLM, `omit_temperature` bỏ hẳn khoá `temperature`. Code không
biết tên tham số nào của provider nào (A3) — nó chỉ chép khối của catalog.

**Vòng lặp tool (T-6.7a, §7.2 ③ "lặp lại", §13.5).** Hàng có `web_tools` và
model có capability `tools` ⇒ gửi schema của `tools/registry.py`; model gọi
tool ⇒ `tool_call` → chạy → `tool_result` → gọi lại, tới `MAX_TOOL_ROUNDS`.
Cả lượt vẫn là MỘT message (Q-P6-1): chữ mọi vòng nối vào `content`, các vòng
vào cột `tool_rounds`, MỘT dòng `usage_events` (B-160). Xem `_run`.

**Không ghi, cố ý:** `raw_response` (§17.2) — Q-P6-5 / B-79 đóng: `tool_rounds`
đã giữ nguyên văn `tool_calls` + `finish_reason` từng vòng, thứ §17.2 muốn để
debug tool-call vỡ; cột ở lại DDL, luôn NULL.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.config.catalog import TOOLS_CAPABILITY, ModelEntry, ReasoningOption, reasoning_to_send
from app.config.settings import settings
from app.core import storage
from app.db.models import KeySource, MessageRole, MessageStatus
from app.db.repositories import ArtifactRepository, MessageRepository
from app.db.session import session_scope
from app.llm import byok_endpoints, context
from app.llm.adapters.byok import ByokAdapter
from app.llm.artifact_blocks import artifact_blocks
from app.llm.client import Chunk, LLMClient, ToolCall, Usage
from app.llm.credentials import Credential, CredentialUnavailable, resolve_credential
from app.llm.tokens import IMAGE_PART_TYPE, count_message, count_messages, count_text
from app.llm.vision import prepare_image
from app.quota import meter
from app.streaming.cancel import FINISH_REASON_CANCELLED, is_cancel_requested
from app.streaming.events import (
    ArtifactEvent,
    DeltaEvent,
    DoneEvent,
    ErrorCode,
    ErrorEvent,
    Event,
    ReasoningEvent,
    StartEvent,
    ToolCallEvent,
    ToolResultEvent,
    UsageEvent,
)
from app.streaming.producer import StreamProducer
from app.tools.registry import REASON_TOO_MANY_CALLS, ToolResult, UserContext, registry
from app.tools.ssrf import UnsafeUrlError, pinned_client
from app.workers.extract import PAGE_MIME, render_pdf_page

logger = logging.getLogger(__name__)

#: Khoá trong `ctx` của arq giữ `LLMClient` dùng chung cả vòng đời tiến trình.
#: `main.py` dựng nó ở `on_startup` và đóng ở `on_shutdown` — `AsyncOpenAI`
#: mang theo một connection pool gắn với event loop, tạo mới mỗi lượt chat là
#: vứt pool đi mỗi lượt (docstring `adapters/system.py`). Tên khoá ở đây chứ
#: không ở `main.py` để tránh import vòng: `main` đã import module này.
CTX_LLM_CLIENT = "llm_client"

#: §7.5 viết thẳng "mỗi 8 chunk kiểm EXISTS cancel:{amid}". Đếm theo **chunk**
#: chứ không theo giây như `_heartbeat` của heartbeat, và khác biệt đó là cố ý: nhịp
#: tim trả lời một câu hỏi đo bằng giây (reaper §7.6 so `heartbeat_at` với
#: `now()`), còn nút Dừng trả lời câu "bao nhiêu chữ nữa thì người dùng thôi
#: thấy chữ chảy" — đo bằng chunk là đo đúng thứ họ nhìn.
#:
#: **Không** phải biến `Settings`: đây là nhịp hỏi nội bộ của một vòng lặp, cùng
#: loại với `ENTRIES_PER_READ` của `streaming/consumer.py`, chứ không phải
#: một *giới hạn* vận hành như `CANCEL_TTL_S` (A3 liệt "tên model, giá, giới
#: hạn, URL provider, màu sắc"). Giá của nó: một `EXISTS` cho mỗi 8 chunk, tức
#: ~66 lệnh cho một câu trả lời dài của `deepseek-flash` (533 chunk đo ở T-1.3).
CANCEL_CHECK_EVERY_N_CHUNKS = 8


#: Message `role=tool` khi tool hỏng (T-6.7a) — chữ của mình, không phải
#: `untrusted_block`; `reason` là mã cố định, không host / IP (§20).
TOOL_ERROR_TEXT = "[{name} lỗi: {reason}]"


class GenerationError(Exception):
    """Lỗi đã phân loại được thành một `ErrorCode` của §7.4.

    Có kiểu riêng vì `_close_ledger` phải phân biệt hai thứ: lỗi mình *biết tên*
    (ghi thẳng mã vào event và vào `messages.error_code`) và lỗi lạ (ghi
    `INTERNAL_ERROR` kèm traceback vào log — còn thấy mã đó nghĩa là còn một
    nhánh chưa ai đặt tên).
    """

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(f"{code.value}: {message}")
        self.code = code
        self.details = message


@dataclass(slots=True)
class _Call:
    """MỘT lần gọi model trong lượt — vòng tool có nhiều lần (T-6.7a, Q-P6-1).

    Giữ riêng từng lần vì hai thứ không cộng được ở mức lượt: `sent` (mỗi lần
    gửi lại cả ngữ cảnh — đường lùi C40 của meter đếm từng lần) và chữ của
    vòng (dây vòng tool cần đúng `content` + `tool_calls` của lần ấy).
    """

    #: Đúng danh sách message đã gửi lên ở lần này (bản chụp — dây còn lớn thêm).
    sent: list[dict[str, Any]]
    text: list[str] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage | None = None

    def spent(self, model: ModelEntry) -> meter.Spent:
        """Token của lần gọi này — số provider, hoặc tự đếm (C40, B-94)."""
        return meter.measure(
            model,
            usage=self.usage,
            sent=self.sent,
            content="".join(self.text),
            reasoning="".join(self.reasoning),
            tool_calls=[tc.to_wire() for tc in self.tool_calls] or None,
        )


def _sum_usage(usages: list[Usage]) -> Usage:
    """Cộng `usage` các lần gọi (B-160: một dòng sổ, token cộng mọi vòng)."""

    def total(values: list[int | None]) -> int | None:
        known = [v for v in values if v is not None]
        return sum(known) if known else None

    return Usage(
        prompt_tokens=sum(u.prompt_tokens for u in usages),
        completion_tokens=sum(u.completion_tokens for u in usages),
        total_tokens=sum(u.total_tokens for u in usages),
        reasoning_tokens=total([u.reasoning_tokens for u in usages]),
        cached_prompt_tokens=total([u.cached_prompt_tokens for u in usages]),
    )


@dataclass(slots=True)
class _Result:
    """Những gì gom được trong lúc stream. Sống đúng một lượt sinh.

    Là biến cục bộ truyền vào các hàm con chứ **không** phải thuộc tính của
    worker: §5.2 cấm worker "giữ state trong RAM giữa các job".
    """

    #: Model đã tra được trong catalog. Thay cho `model_id` trần của T-1.6:
    #: bước ghi sổ (T-2.12) cần cả `provider`, `pricing_mode` và bảng giá, và
    #: tra lại catalog lần thứ hai ở `_close_ledger` là mời một kết quả khác — một
    #: `POST /admin/catalog/reload` chen vào giữa lượt sinh là đủ.
    model: ModelEntry | None = None
    #: Chủ hội thoại. `messages` không có cột `user_id` (Phụ lục A) nên con số
    #: này chỉ lấy được một lần, ở `_prepare`, và `usage_events.user_id` là
    #: cột NOT NULL cần nó.
    user_id: uuid.UUID | None = None
    #: Mọi lần gọi model của lượt, theo thứ tự (T-6.7a). Lượt không tool có
    #: đúng một. Đường lùi C40 của meter đếm `sent` của TỪNG lần (B-67, B-94).
    calls: list[_Call] = field(default_factory=list)
    #: Cột `messages.tool_rounds` (Q-P6-1) — mỗi vòng tool một phần tử.
    rounds: list[dict[str, Any]] = field(default_factory=list)
    #: Số lời gọi tool đã CHẠY trong lượt — so với `MAX_TOOL_CALLS_PER_TURN`.
    tools_run: int = 0
    #: Thời điểm **gọi model**, dùng để tra bảng giá theo khung giờ (A7, B-35).
    #: KHÁC thời điểm ghi sổ: một lượt sinh mười phút có thể bắt đầu lúc 16:58
    #: giờ cao điểm và kết thúc lúc 17:08 giờ thường — giá phải là giá 16:58.
    started_at: datetime | None = None
    #: Credential nào trả tiền cho lượt này (§10.5, T-2.15). Mặc định là
    #: `system` chứ không `None`: một lượt sinh chết **trước** `_prepare`
    #: không ghi sổ gì cả (xem `billable`), nên giá trị này chỉ có nghĩa khi
    #: nó đã được điền — và mặc định chặt hơn (trừ quota) là mặc định đúng
    #: chiều nếu có ngày nào đó một nhánh quên điền.
    key_source: KeySource = KeySource.SYSTEM
    #: Do `_record_usage` điền ở bước ⑥.5; đi tiếp lên event `done` (§7.4,
    #: B-78). `None` = chưa ghi sổ được, và khi đó khoá `cost_usd` **vắng mặt**
    #: trên dây chứ không bằng 0.
    cost_usd: Decimal | None = None
    #: Của lần gọi CUỐI (provider), hoặc `cancelled` (§7.5).
    finish_reason: str | None = None
    error: GenerationError | None = None
    #: §7.5 — người dùng đã bấm Dừng và vòng lặp đã thoát vì thế. Cờ RIÊNG chứ
    #: không phải `finish_reason == "cancelled"`: ba giá trị `finish_reason`
    #: kia đến từ provider, và một ngày nào đó provider trả đúng chuỗi ấy thì
    #: `messages.status` sẽ thành `cancelled` cho một lượt không ai huỷ.
    cancelled: bool = False

    @property
    def content(self) -> str:
        """Nối mọi `delta` — phải **bằng byte-by-byte** với chuỗi client dựng.

        Nối bằng `str.join` chứ không cộng dồn theo byte: C9 là lỗi cắt một ký
        tự tiếng Việt làm đôi, và nó chỉ xuất hiện khi có chỗ nào đó làm việc
        với `bytes`. Ở đây không có chỗ nào như vậy.

        Mọi lần gọi của lượt nối vào cùng `content` (T-6.7a) — đúng thứ tự mà
        `delta` đã ra dây.
        """
        return "".join(t for call in self.calls for t in call.text)

    @property
    def reasoning(self) -> str:
        return "".join(r for call in self.calls for r in call.reasoning)

    @property
    def tool_calls(self) -> list[ToolCall]:
        return [tc for call in self.calls for tc in call.tool_calls]

    @property
    def usage(self) -> Usage | None:
        """Tổng `usage` provider báo — `None` nếu MỘT lần gọi nào không báo.

        Không trộn số provider với số tự đếm trên cột `messages.*_tokens`
        (NQ-23, NQ-26); meter đếm từng lần qua `_Call.spent`.
        """
        usages = [call.usage for call in self.calls]
        if not usages or any(u is None for u in usages):
            return None
        return _sum_usage([u for u in usages if u is not None])

    @property
    def billable(self) -> bool:
        """Có gì để ghi sổ không — cửa duy nhất vào bước ⑥.5.

        Hai điều kiện, và cả hai đều là "đã thật sự chạm tới provider chưa".

        `model`/`user_id`/`started_at` cùng được điền một lần ngay sau
        `_prepare`, nên thiếu một cái nghĩa là lượt sinh chết **trước** khi
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
        return any(c.usage or c.text or c.reasoning or c.tool_calls for c in self.calls)


async def _heartbeat_loop(mid: uuid.UUID) -> None:
    """Ghi `messages.heartbeat_at` mỗi `WORKER_HEARTBEAT_S` cho tới khi bị huỷ.

    Ngủ **trước** rồi mới ghi: `mark_streaming` vừa đặt `heartbeat_at = now()`
    ngay trước khi vòng này chạy, nên một lần ghi tức thì chỉ tốn một
    round-trip để viết lại đúng con số vừa có.

    Không có `try/except` quanh vòng lặp: `_write_heartbeat` đã tự nuốt mọi lỗi
    của nó rồi (một blip Postgres không được phép giết nhịp tim), nên ngoại lệ
    thoát tới đây chỉ có thể là `CancelledError` — và cái đó phải bay tiếp.
    """
    while True:
        await asyncio.sleep(settings.WORKER_HEARTBEAT_S)
        await _write_heartbeat(mid)


@asynccontextmanager
async def _heartbeat(mid: uuid.UUID) -> AsyncIterator[None]:
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
    task = asyncio.create_task(_heartbeat_loop(mid), name=f"nhip-tim:{mid}")
    try:
        yield
    finally:
        task.cancel()
        # `await` để chắc chắn task đã dừng hẳn trước khi hàm thoát: bỏ qua
        # bước này thì nó có thể còn ghi thêm một nhịp *sau* `_close_ledger`.
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
    result = _Result()

    logger.info("generate: bat dau %s (job=%s)", mid, ctx.get("job_id"))
    try:
        await _run(ctx, mid, producer, result)
    except GenerationError as error:
        result.error = error
        logger.warning("generate: %s dung vi %s", mid, error)
    except asyncio.CancelledError:
        # arq cắt job quá `GENERATE_TIMEOUT_S`, hoặc container nhận SIGTERM.
        # `finally` vẫn chạy để client không treo, rồi ném tiếp — nuốt
        # `CancelledError` là nói dối với vòng lặp sự kiện.
        result.error = GenerationError(ErrorCode.WORKER_TIMEOUT, "job bi huy giua chung")
        logger.warning("generate: %s bi huy giua chung", mid)
        raise
    except Exception as exc:  # noqa: BLE001 — C19: không có ngoại lệ nào được thoát ra ngoài mà không ghi event
        result.error = GenerationError(ErrorCode.INTERNAL_ERROR, type(exc).__name__)
        logger.exception("generate: %s loi khong phan loai duoc", mid)
    finally:
        # C19. Đường duy nhất ra khỏi hàm này đi qua đây.
        await _close_ledger(ctx, mid, producer, result)


# ───────────────────────────── các bước ─────────────────────────────


async def _run(
    ctx: dict[str, Any],
    mid: uuid.UUID,
    producer: StreamProducer,
    result: _Result,
) -> None:
    """Bước ① → ⑤ của §7.2 ③. Ném `GenerationError` cho mọi ngả không đi tiếp được.

    **Vòng lặp tool (§7.2 ③ "lặp lại", T-6.7a).** Lần gọi có `tools` mà model
    trả `tool_calls` ⇒ chạy tool, nối vòng vào dây, gọi lại. Dừng khi: model
    không gọi tool · lần gọi không mang `tools` (hết `MAX_TOOL_ROUNDS`, hoặc
    ngữ cảnh + schema vượt `token_budget()` — B-208, không `CONTEXT_TOO_LARGE`
    giữa lượt) · huỷ (kiểm trước mỗi vòng sau vòng đầu và trước mỗi lời gọi tool
    — B-96). Mọi ngả vẫn ra `_close_ledger` (C19): vòng lặp không mở đường thoát
    nào mới.
    """
    model_meta, wire, user_id, credential, level, web_tools = await _prepare(mid)
    result.model = model_meta
    result.user_id = user_id
    result.key_source = credential.key_source
    tool_ctx = UserContext(user_id=user_id)
    # C18 / Q-P6-3: công tắc VÀ capability — thiếu một ⇒ `tools=None` như cũ.
    schema = (
        [spec.to_wire() for spec in registry.specs(tool_ctx)]
        if web_tools and TOOLS_CAPABILITY in model_meta.capabilities
        else []
    )

    # Nhịp tim mở NGAY sau `_prepare` (nơi `mark_streaming` chạy) chứ không
    # đợi chunk đầu, và sống suốt mọi vòng + mọi tool (B-122).
    async with _heartbeat(mid), _turn_client(ctx, credential) as client:
        await producer.emit(
            StartEvent(
                message_id=str(mid),
                model_id=model_meta.id,
                reasoning_effort=level.id if level is not None else None,
            )
        )

        await _inline_images(wire)

        # Mốc giá của A7: bảng giá của **lúc gọi lần đầu**. ponytail: vòng sau
        # vắt qua mốc khung giờ cao điểm DeepSeek vẫn tính giá vòng đầu — đổi
        # sang giá từng lần khi meter ghi được nhiều mốc cho một dòng sổ.
        result.started_at = datetime.now(UTC)
        while True:
            if result.calls and await _is_cancelled(ctx, mid):
                _stop_for_cancel(mid, result, 0)
                break
            offer = (
                bool(schema)
                and len(result.rounds) < settings.MAX_TOOL_ROUNDS
                and _fits(wire, schema, model_meta)
            )
            call = await _call_model(
                ctx,
                mid,
                client,
                producer,
                result,
                model=credential.model_name(model_meta, level),
                wire=wire,
                tools=schema if offer else None,
                max_tokens=model_meta.max_output,
                temperature=(
                    None
                    if level is not None and level.omit_temperature
                    else settings.LLM_TEMPERATURE
                ),
                extra=credential.reasoning_params(level),
            )
            if result.cancelled or not offer or not call.tool_calls:
                break
            await _run_tools(ctx, mid, producer, result, call, wire, tool_ctx, model_meta)
            if result.cancelled:
                break

        # MỘT event `usage` cho cả lượt, tổng mọi lần gọi (B-160) — trước
        # artifact và `done` như cũ. Ngả huỷ không có `usage` của provider (B-94).
        if result.usage is not None:
            await producer.emit(UsageEvent(usage=result.usage))


async def _call_model(
    ctx: dict[str, Any],
    mid: uuid.UUID,
    client: LLMClient,
    producer: StreamProducer,
    result: _Result,
    *,
    model: str,
    wire: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    max_tokens: int,
    temperature: float | None,
    extra: dict[str, Any],
) -> _Call:
    """Một lần gọi model + vòng chunk của nó (§7.2 ③ ⑤). Trả `_Call` đã gom."""
    call = _Call(sent=list(wire))
    result.calls.append(call)
    try:
        stream = await client.stream(
            # Alias LiteLLM hay tên gốc của provider — tuỳ credential (T-2.15);
            # mức có `alias` thay tên trên đường system (T-S.2).
            model=model,
            messages=call.sent,
            # `None` chứ không `[]`: adapter đổi nó thành `omit`, model không có
            # capability `tools` (§9.4) thì không được thấy khoá đó (C18). Lần
            # gọi cuối của vòng lặp cũng `None` — đo T-6.7a: cả ba model `200`
            # khi dây có `tool_calls` mà request không có `tools`.
            tools=tools,
            # §10.2 `est_max` KHÔNG đổi (Cạm bẫy ④ của T-S.6): token suy luận
            # nằm trong `max_tokens` ở mọi provider đã đo.
            max_tokens=max_tokens,
            # `None` = không gửi khoá (Cạm bẫy ① của T-S.6).
            temperature=temperature,
            # `params` (hoặc `byok_params`) của mức, trộn NGUYÊN VĂN (§24.2b·S3b).
            extra=extra,
        )
    except Exception as exc:
        # `await` này là chỗ gửi request và nhận header, nên 401/400/429 nổ
        # tại đây chứ không đội lốt stream rỗng (điểm 1 docstring `client.py`).
        raise GenerationError(ErrorCode.UPSTREAM_ERROR, f"{type(exc).__name__}: {exc}") from exc

    so_chunk = 0
    try:
        async for chunk in stream:
            # `_emit` chạy TRƯỚC phép kiểm: chunk thứ 8 vẫn ra dây và vẫn vào
            # `call.text` — §7.5 "vẫn lưu phần đã sinh" tính tới mẩu cuối.
            await _emit(producer, result, call, chunk)
            so_chunk += 1
            if so_chunk % CANCEL_CHECK_EVERY_N_CHUNKS == 0 and await _is_cancelled(ctx, mid):
                _stop_for_cancel(mid, result, so_chunk)
                break
    except GenerationError:
        raise
    except Exception as exc:
        # Đứt giữa chừng: ca chính của C19. Phần chữ đã gom vẫn được ghi.
        raise GenerationError(ErrorCode.UPSTREAM_ERROR, f"{type(exc).__name__}: {exc}") from exc
    return call


def _schema_tokens(schema: list[dict[str, Any]], model_id: str) -> int:
    return count_text(json.dumps(schema, ensure_ascii=False), model_id=model_id) if schema else 0


def _fits(wire: list[dict[str, Any]], schema: list[dict[str, Any]], model: ModelEntry) -> bool:
    """Ngữ cảnh + schema tool ≤ `token_budget()` (§9.6) — trước MỖI lần mời tool."""
    used = count_messages(wire, model_id=model.id) + _schema_tokens(schema, model.id)
    return used <= context.token_budget(model)


async def _run_tools(
    ctx: dict[str, Any],
    mid: uuid.UUID,
    producer: StreamProducer,
    result: _Result,
    call: _Call,
    wire: list[dict[str, Any]],
    tool_ctx: UserContext,
    model: ModelEntry,
) -> None:
    """Chạy các `tool_calls` của một lần gọi, ghi vòng, nối dây cho lần gọi kế.

    `tool_result` ra dây TRƯỚC mọi `delta` của vòng sau và trước `done`
    (Cạm bẫy ① T-6.7a). Kết quả lên dây trong `untrusted_block` (§20), cắt
    theo `TOOL_RESULT_MAX_CHARS` rồi cắt mềm cho dây vẫn vừa `token_budget()`
    (B-208 ⑤) — vòng kế không bao giờ là `CONTEXT_TOO_LARGE`; hết chỗ cho
    schema thì vòng kế là lần gọi cuối, không tool.
    """
    calls = [tc.to_wire() for tc in call.tool_calls]
    round_: dict[str, Any] = {
        # NQ-22: `ToolCall.to_wire()` là nguồn duy nhất của hình dạng này.
        "tool_calls": calls,
        "reasoning": "".join(call.reasoning) or None,
        "finish_reason": result.finish_reason,
        "results": [],
    }
    result.rounds.append(round_)
    # Suy luận KHÔNG gửi lại (B-266 / B-283, đo T-6.7a: DeepSeek `200` cả qua
    # LiteLLM lẫn gọi thẳng, `prompt_tokens` bằng nhau có hay không có nó).
    wire.append(
        {
            "role": MessageRole.ASSISTANT.value,
            "content": "".join(call.text) or None,
            "tool_calls": calls,
        }
    )
    # Dây (không schema) luôn vừa ngân sách ⇒ lần gọi kế ít nhất đi được KHÔNG
    # tool; còn chỗ cho schema hay không là việc của `_fits` ở đầu vòng.
    room = context.token_budget(model) - count_messages(wire, model_id=model.id)
    for tc in call.tool_calls:
        if await _is_cancelled(ctx, mid):
            _stop_for_cancel(mid, result, 0)
            return
        if result.tools_run >= settings.MAX_TOOL_CALLS_PER_TURN:
            out = ToolResult(ok=False, reason=REASON_TOO_MANY_CALLS)
        else:
            result.tools_run += 1
            out = await registry.call(tc.name, tc.arguments, tool_ctx)
        text, message = _tool_message(tc, out, room=room, model_id=model.id)
        room -= count_message(message, model_id=model.id)
        wire.append(message)
        round_["results"].append(
            {
                "tool_call_id": tc.call_id,
                "name": tc.name,
                "ok": out.ok,
                "content": text,
                "sources": out.sources,
                "reason": out.reason,
            }
        )
        await producer.emit(
            ToolResultEvent(
                call_id=tc.call_id,
                name=tc.name,
                ok=out.ok,
                # Không mang chữ trang — chip chỉ cần nguồn và lý do.
                result={"sources": out.sources, "reason": out.reason},
            )
        )


def _tool_message(
    tc: ToolCall, out: ToolResult, *, room: int, model_id: str
) -> tuple[str, dict[str, Any]]:
    """Message `role=tool` cho một kết quả: (chữ đã cắt, message trên dây)."""
    if not out.ok:
        return "", {
            "role": MessageRole.TOOL.value,
            "tool_call_id": tc.call_id,
            "content": TOOL_ERROR_TEXT.format(name=tc.name, reason=out.reason),
        }
    name = out.sources[0]["url"] if out.sources else tc.name
    text = out.content[: settings.TOOL_RESULT_MAX_CHARS]
    while True:
        message = {
            "role": MessageRole.TOOL.value,
            "tool_call_id": tc.call_id,
            "content": context.untrusted_block(name, text),
        }
        cost = count_message(message, model_id=model_id)
        if cost <= room or not text:
            return text, message
        # Cắt mềm theo tỉ lệ rồi đo lại — tokenizer không tuyến tính tuyệt đối.
        text = text[: max(0, len(text) * max(room, 0) // cost - 1)]


async def _inline_images(messages: list[dict[str, Any]]) -> None:
    """Thay mỗi `context.image_ref` bằng `data:<mime>;base64,…` — tại chỗ (T-4.4b).

    Ở worker chứ không trong `build()` (Cạm bẫy ① T-4.4b). Pillow trong
    `to_thread`: chạy thẳng trên event loop là đứng delta + nhịp tim của mọi
    lượt sinh khác cùng worker (Cạm bẫy ⑤). Object mất ⇒ `error` có mã (C19).

    Tham chiếu có `page` = trang PDF quét (T-4.6b): render trang ấy thành PNG
    rồi đi cùng T-4.3 — một trang một lần (Cạm bẫy ②). Byte PDF đọc một lần
    cho mọi trang của nó.
    """
    objects: dict[str, bytes] = {}
    for message in messages:
        parts = message["content"]
        if not isinstance(parts, list):
            continue
        for index, part in enumerate(parts):
            if part.get("type") != IMAGE_PART_TYPE or "storage_key" not in part:
                continue
            key = part["storage_key"]
            try:
                if key not in objects:
                    objects[key] = await storage.get(key)
            except Exception as exc:
                raise GenerationError(
                    ErrorCode.ATTACHMENT_UNAVAILABLE,
                    f"anh {part['attachment_id']}: {type(exc).__name__}",
                ) from exc
            mime, b64 = await asyncio.to_thread(_prepare_part, objects[key], part)
            parts[index] = {
                "type": IMAGE_PART_TYPE,
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            }


def _prepare_part(data: bytes, part: dict[str, Any]) -> tuple[str, str]:
    """T-4.3 cho một tham chiếu — trang PDF quét render thành PNG trước (T-4.6b)."""
    if "page" in part:
        return prepare_image(render_pdf_page(data, part["page"]), PAGE_MIME)
    return prepare_image(data, part["mime_type"])


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
    if credential.base_url is not None and credential.api_key is not None:
        # Endpoint người dùng tự nhập (T-S.19b): A5 kiểm lại mỗi lượt — DNS có
        # thể đã đổi từ lúc lưu — rồi nối qua đúng các IP đã kiểm (T-6.3).
        try:
            checked = await byok_endpoints.check_base_url(credential.base_url)
        except UnsafeUrlError as exc:
            raise GenerationError(ErrorCode.UPSTREAM_ERROR, str(exc)) from None
        adapter = ByokAdapter.for_endpoint(
            credential.base_url,
            api_key=credential.api_key,
            http_client=pinned_client(checked, timeout=settings.LLM_REQUEST_TIMEOUT_S),
        )
    elif credential.provider is None or credential.api_key is None:
        yield ctx[CTX_LLM_CLIENT]
        return
    else:
        adapter = ByokAdapter.for_provider(credential.provider, api_key=credential.api_key)
    try:
        yield adapter
    finally:
        await adapter.close()


async def _prepare(
    mid: uuid.UUID,
) -> tuple[ModelEntry, list[dict[str, Any]], uuid.UUID, Credential, ReasoningOption | None, bool]:
    """Bước ① → ③ (+ ①.5): đọc message, chọn credential, dựng ngữ cảnh, `streaming`.

    Cả bốn trong **một** session rồi đóng ngay: một lượt sinh có thể kéo mười
    phút, và giữ một kết nối Postgres suốt thời gian đó chỉ để chờ model là
    cách nhanh nhất làm cạn pool khi có vài người cùng chat. `resolve_credential`
    đi nhờ đúng session ấy (T-2.15) thay vì mở một kết nối thứ hai cho một câu
    `SELECT` một hàng.

    Dựng ngữ cảnh **trước** khi đổi trạng thái, đúng thứ tự §7.2: ngữ cảnh
    hỏng (lá không tồn tại, ngân sách không đủ) thì message còn nguyên
    `queued`, và `_close_ledger` sẽ đánh nó `failed` kèm mã — chứ không để lại một
    message `streaming` mà không có ai sinh, tức món ăn của reaper §7.6.
    """
    async with session_scope() as session:
        repo = MessageRepository(session)

        owned = await repo.get_message_for_worker(mid)
        if owned is None:
            raise GenerationError(ErrorCode.MESSAGE_NOT_FOUND, "message khong con trong DB")

        model_meta = await byok_endpoints.resolve_model(
            session, user_id=owned.user_id, model_id=owned.message.model_id or ""
        )
        if model_meta is None:
            raise GenerationError(
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
            raise GenerationError(ErrorCode.CONTEXT_EMPTY, str(exc)) from exc
        except context.BudgetTooSmallError as exc:
            raise GenerationError(ErrorCode.CONTEXT_TOO_LARGE, str(exc)) from exc

        # ①.5 §10.5 — ai trả tiền cho lượt này. **Trước** `mark_streaming`
        # chứ không sau: cả hai ngả lùi của nó (khoá bị xoá, khoá không giải
        # mã được) chỉ là "đi bằng system key", nhưng một ngoại lệ Postgres ở
        # đây mà đứng sau `mark_streaming` sẽ để lại một message `streaming`
        # không ai sinh — đúng món ăn của reaper §7.6.
        try:
            credential = await resolve_credential(session, user_id=owned.user_id, model=model_meta)
        except CredentialUnavailable as exc:
            raise GenerationError(ErrorCode.UPSTREAM_ERROR, str(exc)) from None

        # Mức sẽ gửi (T-S.6). Khác mức API đã ghi chỉ khi catalog vừa bỏ mức
        # ấy lúc job còn trong hàng đợi — khi đó rơi về `reasoning.default` và
        # nói ra trong log; cột bị ghi đè ngay dưới bằng mức thật sự gửi.
        stored_level = owned.message.reasoning_effort
        level = reasoning_to_send(model_meta, stored_level)
        sent_level = level.id if level is not None else None
        if stored_level is not None and sent_level != stored_level:
            logger.warning(
                "generate: %s muc %r khong con trong catalog cua %s — gui %r",
                mid,
                stored_level,
                model_meta.id,
                sent_level,
            )

        if not await repo.mark_streaming(mid, model_id=model_meta.id, reasoning_effort=sent_level):
            # Không còn `queued`: một worker khác đã nhận, hoặc message đã
            # `failed`/`cancelled` trong lúc chờ hàng đợi. Bỏ lượt là đúng —
            # sinh tiếp là trả tiền lần hai cho cùng một câu hỏi (B-72).
            raise GenerationError(
                ErrorCode.MESSAGE_NOT_FOUND,
                "message khong con o trang thai queued (worker khac da nhan?)",
            )
        await session.commit()

    # `user_id` đi ra cùng các thứ kia vì đây là chỗ DUY NHẤT đọc được nó:
    # `messages` không có cột `user_id` (Phụ lục A), nó nằm ở hội thoại chứa
    # message. Bước ghi sổ ⑥.5 cần nó cho `usage_events.user_id`.
    # `web_tools` đi từ hàng `queued` như mức suy luận (Q-P6-3, lối T-S.6).
    return model_meta, wire_messages, owned.user_id, credential, level, owned.message.web_tools


async def _emit(producer: StreamProducer, result: _Result, call: _Call, chunk: Chunk) -> None:
    """Một `Chunk` của §9.1 → một event của §7.4. Map một-một, không bảng dịch.

    `Chunk.kind` cố ý trùng tên `event` của SSE (điểm 2 docstring `client.py`),
    nên hàm này không dịch tên — nó chỉ quyết định cái gì được **gom lại** để
    ghi Postgres, và chunk `done` thì không ra dây ở đây (xem docstring module).
    """
    match chunk.kind:
        case "delta":
            text = chunk.text or ""
            call.text.append(text)
            await producer.emit(DeltaEvent(text=text))
        case "reasoning":
            text = chunk.text or ""
            # KHÔNG vào `result.chu`: reasoning đi vào cột `messages.reasoning`
            # và không bao giờ quay lại ngữ cảnh lượt sau (B-33, `context.py`).
            call.reasoning.append(text)
            await producer.emit(ReasoningEvent(text=text))
        case "tool_call" if chunk.tool_call is not None:
            call.tool_calls.append(chunk.tool_call)
            await producer.emit(
                ToolCallEvent(
                    call_id=chunk.tool_call.call_id,
                    name=chunk.tool_call.name,
                    arguments=chunk.tool_call.arguments,
                )
            )
        case "usage" if chunk.usage is not None:
            # Chỉ GOM — event `usage` ra MỘT lần cho cả lượt ở cuối `_run`
            # (tổng mọi lần gọi, B-160), không một lần mỗi vòng tool.
            call.usage = chunk.usage
        case "done":
            # Chỉ NHẶT, không phát. Event `done` ra dây ở `_close_ledger`, sau khi
            # Postgres đã ghi xong (luật 2 ở docstring module).
            result.finish_reason = chunk.finish_reason
            # Provider gửi `usage` ở chunk riêng **trước** `done` (C40); giữ số
            # cũ nếu `done` không mang gì, thay bằng số mới nếu có.
            call.usage = chunk.usage or call.usage
        case _:
            logger.warning("generate: bo qua chunk kind=%r khong co du lieu", chunk.kind)


async def _is_cancelled(ctx: dict[str, Any], mid: uuid.UUID) -> bool:
    """`EXISTS cancel:{mid}` (§7.5). Hỏng thì **không** làm hỏng lượt sinh.

    Cùng lý lẽ với `_write_heartbeat`, nhưng ở đây cái giá của việc không nuốt
    còn rõ hơn: để ngoại lệ thoát ra thì `_chay` bọc nó thành
    `UPSTREAM_ERROR`, tức người dùng đọc được "provider lỗi" cho một sự cố
    hoàn toàn nằm ở phía mình. Mất một lần hỏi nghĩa là nút Dừng ăn muộn
    `CANCEL_CHECK_EVERY_N_CHUNKS` chunk nữa, và cờ vẫn còn đó (`CANCEL_TTL_S`).
    """
    try:
        return await is_cancel_requested(ctx["redis"], mid)
    except Exception:  # noqa: BLE001 — xem docstring
        logger.warning("generate: %s khong kiem duoc co huy", mid, exc_info=True)
        return False


def _stop_for_cancel(mid: uuid.UUID, result: _Result, so_chunk: int) -> None:
    """Ghi nhận ngả huỷ vào `result` — và **dòng log** mà DoD T-1.9 đòi.

    Không `raise`: huỷ không phải lỗi (xem docstring module). Đặt hai trường
    rồi để `break` ở `_chay` đưa luồng về `_close_ledger`, nơi nó ra dây thành
    `done` mang `finish_reason='cancelled'` đúng như §7.5 viết.

    Dòng log này ra đời ở Phase 1 để thay cho `usage_events` khi chưa ai ghi
    bảng đó (DoD T-1.9: *"ở phase này kiểm bằng log"*). Từ T-2.12 nó **không**
    còn là nguồn duy nhất — `_record_usage` ở bước ⑥.5 mới là — nhưng vẫn giữ,
    và vẫn in `usage` của provider (gần như luôn `None` trên ngả này, B-94) vì
    đó là chỗ đọc log so được hai con số: cái provider **không** báo, và cái
    meter đã đếm thay ở dòng `ghi so` ngay sau.
    """
    result.cancelled = True
    result.finish_reason = FINISH_REASON_CANCELLED
    logger.info(
        "generate: %s NGUOI DUNG HUY sau %d chunk · %d ky tu da sinh · "
        "usage tu provider: %s · phan da sinh se duoc ghi so o buoc ⑥.5",
        mid,
        so_chunk,
        len(result.content),
        result.usage,
    )


async def _write_heartbeat(mid: uuid.UUID) -> None:
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


async def _close_ledger(
    ctx: dict[str, Any], mid: uuid.UUID, producer: StreamProducer, result: _Result
) -> None:
    """Bước ⑥ → ⑧: ghi Postgres, ghi sổ, `XADD done|error`, `EXPIRE`. C19 + C8.

    Bốn việc, bốn `try` riêng (cộng `try` của ⑥.2 artifact — T-5.1). Cố ý:
    Postgres hỏng **không** được phép nuốt luôn event kết thúc, vì hậu quả của
    việc không ghi event là client treo vô hạn — nặng hơn hẳn một dòng lịch sử
    bị mất. Cùng lẽ đó, `EXPIRE` hỏng không
    được phép làm gì tới event đã phát.

    **Ghi sổ (⑥.5) hỏng thì event kết thúc vẫn là `done`, KHÔNG phải `error`.**
    Khác hẳn ca `_write_result` hỏng ngay trên. Hai hỏng, hai người chịu hậu
    quả: mất `messages.content` là mất **câu trả lời của người dùng** — họ F5
    ra một message rỗng, nên phải nói thẳng bằng `PERSIST_FAILED`. Mất một dòng
    `usage_events` là mất **một khoản trong sổ của mình**: người dùng đã đọc
    xong câu trả lời và không có gì để họ làm khác đi. Đổi nó thành một lỗi đỏ
    trên màn hình là bắt họ trả giá cho một sự cố kế toán. Dòng `logger.
    exception` ở `_record_usage` là chỗ khai, và `rebuild_quota` của T-2.13 là
    đường vá.
    """
    error = result.error
    try:
        await _write_result(mid, result)
    except Exception:  # noqa: BLE001 — xem docstring
        logger.exception("generate: %s khong ghi duoc ket qua xuong Postgres", mid)
        if error is None:
            # Chữ đã tới người dùng nhưng lịch sử thì không: nói thẳng bằng mã
            # riêng thay vì gửi `done` rồi để họ F5 ra một message rỗng.
            error = GenerationError(ErrorCode.PERSIST_FAILED, "UPDATE messages that bai")
    else:
        # ⑥.2 — T-5.1. Chỉ khi `content` đã nằm trong Postgres, và TRƯỚC event
        # kết thúc: FE đóng stream khi thấy `done`, event tới sau là mất.
        await _publish_artifacts(mid, producer, result)

    # ⑥.5 — §10.2 vế SAU. Chạy TRƯỚC `XADD` vì `cost_usd` đi trên event `done`.
    await _record_usage(ctx, mid, result)

    final_event: Event = (
        DoneEvent(
            finish_reason=result.finish_reason,
            usage=result.usage,
            cost_usd=result.cost_usd,
        )
        if error is None
        else ErrorEvent(code=error.code, message=error.details)
    )
    try:
        await producer.emit(final_event)
    except Exception:  # noqa: BLE001 — xem docstring
        logger.exception("generate: %s khong XADD duoc event ket thuc (C19)", mid)

    try:
        await producer.expire()
    except Exception:  # noqa: BLE001 — xem docstring
        logger.exception("generate: %s khong EXPIRE duoc %s (C8)", mid, producer.key)

    logger.info(
        "generate: xong %s · %s · %d ky tu · finish_reason=%s · usage=%s · cost_usd=%s",
        mid,
        "loi " + error.code.value if error is not None else "ok",
        len(result.content),
        result.finish_reason,
        result.usage,
        result.cost_usd,
    )


async def _publish_artifacts(mid: uuid.UUID, producer: StreamProducer, result: _Result) -> None:
    """Bước ⑥.2 — khối code đủ điều kiện ⇒ hàng `artifacts` + `XADD artifact` (T-5.1, T-5.2a).

    Mọi ngả khép (xong, huỷ, `length`, lỗi giữa chừng) đi qua cùng luật: chỉ khối
    rào **đã đóng** — khối dở ở cuối không bao giờ thành artifact (Cạm bẫy ③).

    **Hỏng thì nuốt, như `_record_usage`:** câu trả lời đã nằm trong Postgres;
    mất artifact là sự cố có log, không phải lỗi đỏ cho người dùng. INSERT cả
    lô trong một transaction rồi mới XADD — không phát event cho hàng chưa commit.
    """
    try:
        blocks = artifact_blocks(result.content)
        if not blocks or result.user_id is None:
            return
        async with session_scope() as session:
            # T-5.2a: có tiêu đề ⇒ có thể là phiên bản kế của một dòng trên đường đi.
            rows = await ArtifactRepository(session).create_for_message(
                message_id=mid, user_id=result.user_id, blocks=blocks
            )
            await session.commit()
        for row in rows:
            await producer.emit(
                ArtifactEvent(
                    artifact_id=str(row.id), version=row.version, kind=row.kind, title=row.title
                )
            )
    except Exception:  # noqa: BLE001 — xem docstring
        logger.exception("generate: %s KHONG tao duoc artifact — cau tra loi van nguyen", mid)


async def _record_usage(ctx: dict[str, Any], mid: uuid.UUID, result: _Result) -> None:
    """Bước ⑥.5 — §10.2 vế SAU. Điền `result.cost_usd`; hỏng thì **không** ném.

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

    **Nuốt mọi ngoại lệ**, cùng lý lẽ với `_write_heartbeat` và `_is_cancelled` nhưng
    đắt hơn: ở đây cái mất là một khoản trong sổ cái, không phải một nhịp tim.
    Vẫn nuốt, vì thay thế duy nhất là để một lỗi Redis/Postgres biến một câu
    trả lời đã sinh xong thành một lỗi đỏ trên màn hình người dùng — xem
    docstring `_close_ledger`. `logger.exception` là chỗ khai, và nó ghi đủ
    `user_id`/`model` để người đọc log vá lại bằng tay được.
    """
    if not result.billable:
        return
    # `billable` đã khẳng định ba trường này khác `None`; khẳng định lại ở đây
    # cho mypy thay vì `assert`, vì `assert` bị `python -O` xoá mất.
    model = result.model
    user_id = result.user_id
    started_at = result.started_at
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
                usage=result.usage,
                sent=result.calls[0].sent,
                content=result.content,
                reasoning=result.reasoning,
                tool_calls=[tc.to_wire() for tc in result.tool_calls] or None,
                # T-6.7a / B-160: MỘT dòng sổ, token cộng từng lần gọi — mỗi
                # lần đo riêng (số provider, hoặc tự đếm `sent` của lần ấy).
                spent=sum(
                    (call.spent(model) for call in result.calls[1:]),
                    result.calls[0].spent(model),
                ),
                # §10.5 — `byok` thì `record_usage` ghi dòng sổ nhưng KHÔNG
                # `ZADD` hai cửa sổ quota. Luật nằm ở `quota/meter.py`, chỗ
                # duy nhất biết cả hai vế; ở đây chỉ chở giá trị (B-157).
                key_source=result.key_source,
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

    result.cost_usd = record.cost_usd
    logger.info(
        "generate: %s ghi so %s · %s · key_source=%s · in=%d out=%d cached=%d · %s USD · %s",
        mid,
        record.id,
        model.id,
        result.key_source.value,
        record.spent.prompt_tokens,
        record.spent.completion_tokens,
        record.spent.cached_tokens,
        record.cost_usd,
        record.confidence.value
        + ("" if record.spent.measured else " (tiktoken tu dem, provider khong bao usage)"),
    )


def _final_status(result: _Result) -> MessageStatus:
    """Ba ngả của §7.2 ③ + §7.5 → một giá trị của `message_status`.

    **Lỗi thắng cờ huỷ.** Trúng cả hai (bấm Dừng rồi Postgres hỏng ngay sau
    đó) thì `failed` là câu đúng hơn: có một sự cố cần người đọc log biết, còn
    `cancelled` sẽ nói rằng mọi thứ đã diễn ra như người dùng muốn.
    """
    if result.error is not None:
        return MessageStatus.FAILED
    if result.cancelled:
        return MessageStatus.CANCELLED
    return MessageStatus.COMPLETED


async def _write_result(mid: uuid.UUID, result: _Result) -> None:
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
    error = result.error
    usage = result.usage
    executed = {tc["id"] for round_ in result.rounds for tc in round_["tool_calls"]}
    async with session_scope() as session:
        await MessageRepository(session).finish_generation(
            mid,
            status=_final_status(result),
            content=result.content,
            reasoning=result.reasoning or None,
            # Lời gọi đã chạy sống trong `tool_rounds` (Q-P6-1); cột cũ chỉ còn
            # giữ lời gọi KHÔNG chạy (lần gọi không mời tool mà model vẫn gọi).
            tool_calls=[tc.to_wire() for tc in result.tool_calls if tc.call_id not in executed]
            or None,
            tool_rounds=result.rounds or None,
            finish_reason=result.finish_reason,
            error_code=error.code.value if error is not None else None,
            prompt_tokens=usage.prompt_tokens if usage is not None else None,
            completion_tokens=usage.completion_tokens if usage is not None else None,
        )
        await session.commit()
