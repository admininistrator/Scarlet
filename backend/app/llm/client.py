"""Protocol `LLMClient` và kiểu dữ liệu chuẩn hoá của tầng model (§9.1, A9).

KH tham chiếu: §9.1, §7.4, ADR-03, ADR-04 · CLAUDE.md A9, A3.

Đây là **toàn bộ** bề mặt mà phần còn lại của backend nhìn thấy khi nói chuyện
với model. Không chỗ nào ngoài `app/llm/adapters/` được import SDK của
provider, và không chỗ nào được biết provider nào đang trả lời — đó là A9.

Ba điểm dễ hiểu sai, ghi ngay ở đây vì chúng quyết định cách các task sau dùng
module này:

1. **`stream()` là `async def` trả về `AsyncIterator`, KHÔNG phải async
   generator.** Gọi là `async for c in await client.stream(...)`, có `await`.
   §9.1 viết đúng như vậy và đó là lựa chọn có lý do: `await` thực hiện request
   HTTP và nhận header, nên lỗi `401/400/429` nổ ngay tại dòng `await` — trước
   khi worker kịp `XADD` bất cứ thứ gì. Nếu là async generator thì thân hàm chỉ
   chạy ở vòng lặp đầu tiên, và lỗi xác thực sẽ đội lốt "stream rỗng".

2. **`Chunk.kind` trùng tên với `event` của SSE (§7.4).** `delta`, `reasoning`,
   `tool_call`, `usage`, `done`. Cố ý: worker (T-1.6) map một-một sang
   `XADD`, không cần bảng dịch — một bảng dịch là một chỗ để hai bên lệch nhau.
   Các event còn lại của §7.4 (`start`, `tool_result`, `artifact`, `error`)
   **không** sinh ra từ stream của model nên không có mặt ở đây.

3. **`ToolCall.arguments` là CHUỖI JSON thô, chưa parse.** Lượt sau phải gửi
   lại nguyên chuỗi đó trong `messages[].tool_calls[].function.arguments`
   (§9.6 dựng context); parse rồi `json.dumps()` lại có thể đổi thứ tự khoá và
   khoảng trắng. Tầng SSE (`streaming/events.py::ToolCallEvent`) tự `json.loads`
   khi phát event `tool_call` với `args` dạng object như §7.4 mô tả.

4. **`ToolCall.to_wire()` là nguồn sự thật DUY NHẤT cho hình dạng cột
   `messages.tool_calls`** (NQ-22, B-68). Worker ghi cột đó bằng chính hàm này;
   `llm/context.py::_to_wire` đọc lại nguyên văn ở lượt sau. Hai đầu ở hai file
   khác nhau và hai task khác nhau, nên chỗ chống lệch phải là code dùng chung
   — ghi lệch thì lượt **sau** mới vỡ, bằng `400 invalid request` không nói lý do.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal, Protocol

#: Trùng tên `event` của §7.4 — xem điểm 2 ở docstring module.
ChunkKind = Literal["delta", "reasoning", "tool_call", "usage", "done"]


@dataclass(frozen=True, slots=True)
class ToolCall:
    """Một lời gọi tool đã ghép đủ mảnh từ stream.

    Provider gửi tool call thành nhiều mảnh: mảnh đầu có `id` và `name`, các
    mảnh sau chỉ có thêm một đoạn `arguments`. `parser.py` ghép lại và chỉ phát
    ra `ToolCall` khi đã đủ — không ai ngoài parser nhìn thấy mảnh vỡ.
    """

    call_id: str
    name: str
    #: Chuỗi JSON thô — xem điểm 3 ở docstring module.
    arguments: str

    def to_wire(self) -> dict[str, Any]:
        """Khối `tool_calls[i]` đúng hình dạng dây OpenAI — xem điểm 4.

        ``{"id": …, "type": "function", "function": {"name": …, "arguments": …}}``

        `type` luôn là `"function"`: đó là giá trị DUY NHẤT mà Chat Completions
        định nghĩa cho phần tử của `tool_calls`, nên nó là hằng của protocol,
        không phải một lựa chọn cấu hình (A3 nói về tên model, giá, giới hạn,
        URL provider, màu sắc).

        `arguments` đi qua **nguyên văn**, không `json.loads` rồi `json.dumps`
        lại: vài provider so khớp chính chuỗi đó với `tool_call_id` ở lượt sau,
        và một lần round-trip là đủ để đổi thứ tự khoá và khoảng trắng.
        """
        return {
            "id": self.call_id,
            "type": "function",
            "function": {"name": self.name, "arguments": self.arguments},
        }


@dataclass(frozen=True, slots=True)
class Usage:
    """Số token của một lượt gọi, đọc từ chunk `usage` của provider.

    `reasoning_tokens` và `cached_prompt_tokens` không phải trang trí:
    B-33 đo được `deepseek-flash` tiêu `max_tokens` cho reasoning **trước** khi
    sinh `content`, nên ngân sách token của §9.6 phải trừ hao chúng; và
    `cached_input_per_1m` đã có sẵn trong catalog (§9.2) nên metering (§10.2)
    cần biết bao nhiêu token đọc từ cache. Cả hai đều nằm sẵn trong payload —
    bỏ đi là mất luôn, không dựng lại được sau.

    `None` nghĩa là provider **không** báo trường đó, khác hẳn `0` (báo và bằng
    không). Phân biệt hai cái này là điều kiện để C40 kiểm chứng được.
    """

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    reasoning_tokens: int | None = None
    cached_prompt_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class Chunk:
    """Một mẩu đã chuẩn hoá của stream, bất kể provider nào sinh ra nó.

    Chỉ trường ứng với `kind` là có giá trị:

    | `kind`      | trường mang dữ liệu                  |
    |-------------|--------------------------------------|
    | `delta`     | `text`                               |
    | `reasoning` | `text`                               |
    | `tool_call` | `tool_call`                          |
    | `usage`     | `usage`                              |
    | `done`      | `finish_reason`, `usage` (có thể None) |

    `finish_reason` không nằm trong bốn trường mà tasks.md liệt kê, nhưng §7.4
    bắt event `done` mang nó (`{"finish_reason":"stop","usage":{...}}`) và
    parser là chỗ **duy nhất** nhìn thấy nó — xem báo cáo T-1.3 phần lệch.
    """

    kind: ChunkKind
    text: str | None = None
    tool_call: ToolCall | None = None
    usage: Usage | None = None
    finish_reason: str | None = None


class LLMClient(Protocol):
    """Giao diện DUY NHẤT của cả hệ thống để gọi model (§9.1, A9).

    Hai cài đặt dự kiến, cùng dùng SDK `openai` và **chung** parser:
    `SystemAdapter` (qua LiteLLM, tính vào quota) và `ByokAdapter` (key của
    user, Phase 2). Xem bảng ở §9.1.
    """

    async def stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
        temperature: float,
        extra: dict[str, Any],
    ) -> AsyncIterator[Chunk]:
        """Gọi model và trả về iterator các `Chunk` đã chuẩn hoá.

        `model` là `upstream_model`/alias lấy từ catalog (§9.2) — **không** bao
        giờ là chuỗi literal trong code gọi (A3). `extra` mang tham số riêng
        của provider (ví dụ `reasoning_effort`) và đi thẳng vào body request;
        adapter không diễn giải nó.
        """
        ...
