"""Chín loại event của §7.4 — mỗi loại một dataclass, mỗi loại một `data()`.

KH tham chiếu: §7.4, §7.6, C10, C19, C40 · CLAUDE.md A3 · NQ-22, NQ-23.

File này là **hợp đồng giữa worker và trình duyệt**, và nó là chỗ DUY NHẤT
viết ra hình dạng đó. Producer (T-1.6) gọi `data()` rồi `json.dumps`; consumer
(T-1.7) chỉ chép lại `type` sang `event:` và chuỗi JSON sang `data:` — nó
**không** dựng lại payload. Nhờ vậy thêm một trường vào event là sửa một dòng
ở đây, không phải hai chỗ ở hai task khác nhau.

**Vì sao `data()` trả `dict` chứ không trả chuỗi.** C10: SSE dùng `\\n` làm dấu
phân cách trường, nên mọi payload phải đi qua `json.dumps` — và nếu mỗi event
tự nội suy chuỗi thì sẽ có đúng một event nào đó quên. Ở đây không event nào
nhìn thấy chuỗi; việc serialize nằm trọn trong `producer.py`.

**Khoá của payload bám đúng §7.4**, kể cả khi trông tiết kiệm quá mức:
`delta` là `{"t": …}` chứ không phải `{"text": …}`, `usage` là `{"in":…,"out":…}`.
Đó là chữ đã viết trong kế hoạch và là thứ `sse.ts` (T-1.14) sẽ đọc.

**Ba event chưa có người sinh ở Phase 1** — `tool_result` (§12, Phase 6),
`artifact` (§14, Phase 5) và một nửa của `tool_call` — vẫn khai ở đây vì
tasks.md T-1.6 đòi đủ chín loại, và vì FE cần biết trước danh sách `event:`
nào có thể tới. Chúng không phải code chết: `EventType` là kiểu đóng, nên
thêm một nhánh `match` ở consumer mà quên một loại thì mypy báo ngay.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any, ClassVar, Literal

from app.llm.client import Usage

#: Giá trị của trường `type` trong bản ghi Redis Stream, cũng là `event:` của
#: SSE. Trùng tên với `Chunk.kind` (§9.1) ở năm loại chung — xem điểm 2 trong
#: docstring của `app/llm/client.py`: cố ý, để worker map một-một, không bảng dịch.
EventType = Literal[
    "start",
    "delta",
    "reasoning",
    "tool_call",
    "tool_result",
    "artifact",
    "usage",
    "done",
    "error",
]


class ErrorCode(StrEnum):
    """Mã lỗi của event `error` — cũng là giá trị ghi vào `messages.error_code`.

    §7.4 đòi event `error` mang **mã**, không phải một câu tiếng Việt: FE bật
    nút Retry theo mã, và một thông điệp tự do thì không so sánh được. Đây là
    hằng của protocol chứ không phải cấu hình sản phẩm, nên nó ở đây chứ không
    ở `config/` (A3 nói về tên model, giá, giới hạn, URL provider, màu sắc).

    Không có mã nào nghĩa là "lỗi không rõ" mà im lặng: mọi đường thoát của
    `generate` đều rơi vào đúng một mã ở đây (C19).
    """

    #: `message_id` của job không còn trong DB (đã xoá cứng, hoặc job mồ côi).
    MESSAGE_NOT_FOUND = "MESSAGE_NOT_FOUND"
    #: `messages.model_id` không khớp model nào đang bật trong catalog (§9.2).
    MODEL_UNKNOWN = "MODEL_UNKNOWN"
    #: Cả đường đi không còn message nào dùng được (`EmptyPathError`, §8.3).
    CONTEXT_EMPTY = "CONTEXT_EMPTY"
    #: Ngân sách không chứa nổi system prompt + khối mới nhất (`BudgetTooSmallError`).
    CONTEXT_TOO_LARGE = "CONTEXT_TOO_LARGE"
    #: Provider/LiteLLM lỗi hoặc đứt giữa chừng — ca của C19.
    UPSTREAM_ERROR = "UPSTREAM_ERROR"
    #: Job bị arq cắt vì quá `GENERATE_TIMEOUT_S`, hoặc container dừng giữa job.
    WORKER_TIMEOUT = "WORKER_TIMEOUT"
    #: Sinh xong nhưng KHÔNG ghi được Postgres. Tách riêng khỏi `INTERNAL_ERROR`
    #: vì nó là ca duy nhất mà chữ đã tới người dùng nhưng lịch sử thì không.
    PERSIST_FAILED = "PERSIST_FAILED"
    #: Lỗi không phân loại được. Còn thấy mã này trong log nghĩa là còn một
    #: nhánh chưa ai đặt tên.
    INTERNAL_ERROR = "INTERNAL_ERROR"
    #: §7.6 — do **reaper** (T-1.10) ghi, không phải `generate`. Khai ở đây để
    #: FE chỉ phải đọc một bảng mã, không phải hai.
    WORKER_LOST = "WORKER_LOST"
    #: §7.6 nhánh thứ hai — cũng do **reaper** ghi, nhưng cho message chưa bao
    #: giờ được nhận: worker chết *trước* `mark_streaming`, hoặc job rơi khỏi
    #: hàng đợi arq (B-123). Mã RIÊNG chứ không dùng lại `WORKER_LOST` vì hai
    #: ca khác nhau ở chỗ quan trọng nhất với người dùng: `WORKER_LOST` nghĩa
    #: là **đã sinh một phần** (và phần đó có thể còn trong Redis Stream tới hết
    #: `STREAM_TTL_S` — xem B-98), còn mã này nghĩa là **chưa một chữ nào**.
    #: Gộp làm một là bắt FE đoán, và §7.4 dựng bảng mã ra để không phải đoán.
    JOB_LOST = "JOB_LOST"


@dataclass(frozen=True, slots=True)
class Event:
    """Gốc của chín loại. Không có trường nào — mỗi loại tự khai trường của nó."""

    TYPE: ClassVar[EventType]

    def data(self) -> dict[str, Any]:
        """Payload sẽ được `json.dumps` vào trường `data` của bản ghi stream."""
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class StartEvent(Event):
    """§7.4: "Bắt đầu sinh, kèm `model_id`, `message_id`" → FE hiện con trỏ nháy."""

    TYPE: ClassVar[EventType] = "start"

    message_id: str
    model_id: str

    def data(self) -> dict[str, Any]:
        return {"message_id": self.message_id, "model_id": self.model_id}


@dataclass(frozen=True, slots=True)
class DeltaEvent(Event):
    """Một mẩu văn bản. Khoá `t` là chữ của §7.4, không phải `text`."""

    TYPE: ClassVar[EventType] = "delta"

    text: str

    def data(self) -> dict[str, Any]:
        return {"t": self.text}


@dataclass(frozen=True, slots=True)
class ReasoningEvent(Event):
    """Mẩu reasoning (B-33). Cùng hình dạng `delta` nhưng KHÁC `event:`.

    Tách hẳn loại thay vì thêm cờ vào `delta`: §7.4 giao cho FE hai chỗ hiển
    thị khác nhau (khối gấp được, tách khỏi nội dung chính), và phần reasoning
    **không** được nối vào `messages.content` — nó đi vào cột `reasoning` và
    không bao giờ quay lại ngữ cảnh lượt sau (B-33, `context.py`).
    """

    TYPE: ClassVar[EventType] = "reasoning"

    text: str

    def data(self) -> dict[str, Any]:
        return {"t": self.text}


def _doc_args(arguments: str) -> dict[str, Any] | None:
    """`arguments` (chuỗi JSON thô) → object, hoặc `None` nếu không đọc được."""
    if not arguments:
        return {}
    try:
        parsed = json.loads(arguments)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


@dataclass(frozen=True, slots=True)
class ToolCallEvent(Event):
    """Model gọi tool → FE hiện chip "đang tìm web…".

    Nhận `arguments` dưới dạng **chuỗi JSON thô** đúng như provider gửi (điểm 3
    docstring `client.py`, NQ-22) và chỉ parse ở đây, vì §7.4 quy định event
    mang `args` là một **object**. Chuỗi thô vẫn là thứ ghi xuống
    `messages.tool_calls` — parse rồi `json.dumps` lại có thể đổi thứ tự khoá.

    Provider gửi `arguments` không phải JSON hợp lệ (hoặc là JSON nhưng không
    phải object) thì `args` là `{}` và chuỗi gốc đi kèm ở `args_raw`: bỏ im
    lặng sẽ thành "model gọi tool mà không có tham số" — sai theo cách FE không
    phát hiện được.
    """

    TYPE: ClassVar[EventType] = "tool_call"

    call_id: str
    name: str
    arguments: str

    def data(self) -> dict[str, Any]:
        args = _doc_args(self.arguments)
        payload: dict[str, Any] = {
            "call_id": self.call_id,
            "name": self.name,
            "args": args if args is not None else {},
        }
        if args is None:
            payload["args_raw"] = self.arguments
        return payload


@dataclass(frozen=True, slots=True)
class ToolResultEvent(Event):
    """Tool trả kết quả → FE cập nhật chip, hiện nguồn.

    **Chưa có người sinh ở Phase 1** — tool registry là §12/§13 (Phase 6, 7).
    """

    TYPE: ClassVar[EventType] = "tool_result"

    call_id: str
    name: str
    ok: bool
    result: Any = None

    def data(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "name": self.name,
            "ok": self.ok,
            "result": self.result,
        }


@dataclass(frozen=True, slots=True)
class ArtifactEvent(Event):
    """Có artifact mới/cập nhật → FE mở panel phải.

    **Chưa có người sinh ở Phase 1** — artifact là §14 (Phase 5). `version` có
    mặt ngay từ đây vì §14.2 nói artifact có phiên bản, và một event không mang
    số phiên bản thì FE không biết nó đang mở bản nào.
    """

    TYPE: ClassVar[EventType] = "artifact"

    artifact_id: str
    version: int

    def data(self) -> dict[str, Any]:
        return {"artifact_id": self.artifact_id, "version": self.version}


def _usage_payload(usage: Usage) -> dict[str, Any]:
    """`Usage` (§9.1) → payload của §7.4. Xem `UsageEvent` cho luật `None`."""
    payload: dict[str, Any] = {"in": usage.prompt_tokens, "out": usage.completion_tokens}
    if usage.reasoning_tokens is not None:
        payload["reasoning"] = usage.reasoning_tokens
    if usage.cached_prompt_tokens is not None:
        payload["cached"] = usage.cached_prompt_tokens
    return payload


@dataclass(frozen=True, slots=True)
class UsageEvent(Event):
    """Số token tạm tính → FE cập nhật thanh quota.

    **Khoá vắng mặt nghĩa là provider KHÔNG báo, khác hẳn báo và bằng 0** — đó
    là toàn bộ lý do `Usage.reasoning_tokens`/`cached_prompt_tokens` là
    `int | None` chứ không phải `int` (NQ-23), và là điều kiện để C40 kiểm
    chứng được. Điền 0 vào chỗ vắng sẽ biến "không đo được" thành "đo được và
    bằng không", tức một lượt chat miễn phí trong sổ sách.

    **`cost_usd` cố ý KHÔNG có ở đây, kể cả sau T-2.12** — nó chỉ đi trên event
    `done`. Event này phát ra **giữa** lúc stream còn chảy, mà giá thì snapshot
    vào `usage_events` tại thời điểm gọi (A7, ADR-08) và chỉ chốt được khi lượt
    sinh đã khép. Nhân một con số tiền tạm ở tầng streaming là dựng nguồn sự
    thật thứ hai cho hoá đơn — và một thanh quota nhảy lùi khi `done` tới với
    con số thật.
    """

    TYPE: ClassVar[EventType] = "usage"

    usage: Usage

    def data(self) -> dict[str, Any]:
        return _usage_payload(self.usage)


@dataclass(frozen=True, slots=True)
class DoneEvent(Event):
    """Kết thúc bình thường → FE đóng `EventSource`, bật lại nút gửi.

    `finish_reason` là trường thứ năm của `Chunk` (NQ-23): `stop`, `length`,
    `tool_calls` dẫn tới ba hành vi FE khác nhau, và parser là module duy nhất
    nhìn thấy nó. `None` khi upstream đứt trước lúc báo lý do dừng.

    `usage` có thể `None` — provider không gửi chunk `usage` cuối (C40). Để
    `None` chứ không dựng một object toàn số 0, cùng lý do với `UsageEvent`.

    **`cost_usd` nằm TRONG khối `usage`, không phải cạnh nó** — §7.4 viết thẳng
    hình dạng đó:

        data: {"finish_reason":"stop","usage":{"in":1204,"out":389,"cost_usd":0.00231}}

    Đây là khác biệt duy nhất giữa `done` và `usage` giữa chừng (B-78): sự kiện
    `usage` là *số token tạm tính* trong lúc còn chảy, còn `done` là lúc duy
    nhất có một con số tiền đã **chốt** — nó do `app/quota/meter.py` tính rồi
    ghi vào `usage_events` (A7, ADR-08), và đi lên dây chỉ để FE hiển thị. Tầng
    streaming **không** tự nhân giá: làm thế là dựng nguồn sự thật thứ hai cho
    hoá đơn.

    **`usage=None` mà `cost_usd` có giá trị là một ca có thật, không phải lỗi.**
    Huỷ giữa chừng thì provider chưa kịp gửi chunk `usage` (B-94) nhưng meter
    vẫn đếm được phần đã sinh bằng `tiktoken` và vẫn ghi một dòng sổ. Khi đó
    khối `usage` trên dây mang **đúng một khoá** `cost_usd`: token thì vắng
    mặt, và "khoá vắng mặt nghĩa là provider KHÔNG báo" là luật đã có sẵn của
    file này (NQ-23) — điền 0 vào đó mới là nói dối.

    `float` chứ không chuỗi: §7.4 viết `0.00231`, một số JSON. Con số đã được
    `quantize_cost` ép về 6 chữ số thập phân trước khi tới đây, nên nó đi qua
    `float` mà vẫn in ra đúng chừng ấy chữ số. Nguồn sự thật của tiền là cột
    `NUMERIC(12,6)` trong Postgres, không phải giá trị này.
    """

    TYPE: ClassVar[EventType] = "done"

    finish_reason: str | None = None
    usage: Usage | None = None
    cost_usd: Decimal | None = None

    def data(self) -> dict[str, Any]:
        payload = _usage_payload(self.usage) if self.usage is not None else None
        if self.cost_usd is not None:
            payload = {**(payload or {}), "cost_usd": float(self.cost_usd)}
        return {"finish_reason": self.finish_reason, "usage": payload}


@dataclass(frozen=True, slots=True)
class ErrorEvent(Event):
    """Lỗi CÓ MÃ → FE hiện lỗi + nút Retry.

    `message` là chữ cho người đọc log, **không** phải để FE phân nhánh — và
    không bao giờ chứa nội dung message của người dùng (§20).
    """

    TYPE: ClassVar[EventType] = "error"

    code: ErrorCode
    message: str = ""

    def data(self) -> dict[str, Any]:
        return {"code": self.code.value, "message": self.message}


#: Mọi loại event — dùng cho test "đủ chín loại" và cho `match` ở consumer.
ALL_EVENT_TYPES: tuple[type[Event], ...] = (
    StartEvent,
    DeltaEvent,
    ReasoningEvent,
    ToolCallEvent,
    ToolResultEvent,
    ArtifactEvent,
    UsageEvent,
    DoneEvent,
    ErrorEvent,
)
