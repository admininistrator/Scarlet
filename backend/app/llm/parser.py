"""Chuẩn hoá stream OpenAI Chat Completions thành `Chunk` (§9.1, §7.4, A9).

KH tham chiếu: §9.1, §7.4, §9.4, C9, C19, C40 · B-33.

Cả `SystemAdapter` lẫn `ByokAdapter` (Phase 2) dùng **chung** file này: sau
LiteLLM thì mọi provider đều nói cùng một protocol, và đó là toàn bộ giá trị
của ADR-03 + ADR-04. Thêm provider mức 1/2 (§9.8) không được sửa file này.

**Đầu vào là `Mapping`, không phải object của SDK.** Adapter gọi
`chunk.model_dump()` trước khi đưa vào đây. Ba lý do:

- Trường như `reasoning_content` (B-33) không có trong schema của SDK, nó sống
  trong `model_extra`. Làm việc với dict thì nó là một khoá bình thường, không
  phải một `getattr` có thể gãy khi SDK đổi phiên bản.
- Fixture của test là **đúng payload `data:` thật** ghi lại từ provider
  (`tests/llm/fixtures/`), nên test chạy trên cùng hình dạng dữ liệu mà
  production thấy, không phải trên một bản dựng lại bằng tay.
- Không buộc `ByokAdapter` phải đi qua SDK `openai` nếu sau này nó gọi thẳng.

**Vì sao không có `kind="error"`.** Lỗi của provider tới dưới dạng exception
của SDK, không phải chunk. Worker bắt nó trong `try/finally` và tự `XADD`
event `error` (C19) — parser không có thẩm quyền quyết định cái gì là lỗi.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.llm.client import Chunk, ToolCall, Usage

logger = logging.getLogger(__name__)

#: Một chunk thô, tức nội dung của một dòng `data:` đã `json.loads`.
RawChunk = Mapping[str, Any]

#: Tên trường reasoning, theo thứ tự ưu tiên. `deepseek-flash` dùng
#: `reasoning_content` (đo được ở B-33); một số provider khác dùng `reasoning`.
#: Đây là danh sách **tên trường của protocol**, không phải cấu hình sản phẩm,
#: nên nó ở đây chứ không ở `config/` (A3 nói về tên model, giá, giới hạn, URL).
_REASONING_KEYS: tuple[str, ...] = ("reasoning_content", "reasoning")

#: Chỉ xử lý choice thứ nhất: `LLMClient.stream()` (§9.1) không có tham số `n`,
#: nên không có đường nào yêu cầu nhiều hơn một lựa chọn.
_ONLY_CHOICE_INDEX = 0


@dataclass(slots=True)
class _ToolCallBuffer:
    """Nơi ghép các mảnh của MỘT tool call trong lúc stream còn chạy."""

    call_id: str = ""
    name: str = ""
    arguments: list[str] = field(default_factory=list)


def _as_int(value: Any) -> int | None:
    """`None` khi provider không báo trường đó — khác hẳn `0` (báo và bằng 0)."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _has_usage(raw: RawChunk) -> bool:
    """Chunk `usage` rỗng hoặc toàn `null` không phải là báo cáo token."""
    return any(
        _as_int(raw.get(k)) is not None
        for k in ("prompt_tokens", "completion_tokens", "total_tokens")
    )


def _parse_usage(raw: RawChunk) -> Usage:
    details_out = raw.get("completion_tokens_details")
    details_in = raw.get("prompt_tokens_details")
    prompt = _as_int(raw.get("prompt_tokens")) or 0
    completion = _as_int(raw.get("completion_tokens")) or 0
    total = _as_int(raw.get("total_tokens"))
    return Usage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        # Thiếu `total_tokens` thì cộng lại, đừng để 0: quota (§10.2) trừ theo
        # con số này và một số 0 im lặng là một lượt chat miễn phí (C40).
        total_tokens=total if total is not None else prompt + completion,
        reasoning_tokens=(
            _as_int(details_out.get("reasoning_tokens"))
            if isinstance(details_out, Mapping)
            else None
        ),
        cached_prompt_tokens=(
            _as_int(details_in.get("cached_tokens")) if isinstance(details_in, Mapping) else None
        ),
    )


class StreamParser:
    """Máy trạng thái một chiều cho MỘT stream. Không dùng lại cho stream khác.

    Có trạng thái vì hai thứ bắt buộc phải nhớ qua nhiều chunk: các mảnh
    `tool_calls` (provider gửi `arguments` từng vài ký tự một) và `usage` +
    `finish_reason` (tới ở hai chunk khác nhau, sau khi văn bản đã hết).
    """

    __slots__ = ("_tool_calls", "_finish_reason", "_usage", "_done_emitted")

    def __init__(self) -> None:
        self._tool_calls: dict[int, _ToolCallBuffer] = {}
        self._finish_reason: str | None = None
        self._usage: Usage | None = None
        self._done_emitted = False

    def feed(self, raw: RawChunk) -> list[Chunk]:
        """Nạp một chunk thô, trả về các `Chunk` phát sinh từ nó (có thể rỗng)."""
        out: list[Chunk] = []

        for choice in raw.get("choices") or ():
            if not isinstance(choice, Mapping):
                continue
            index = choice.get("index")
            if index is not None and _as_int(index) != _ONLY_CHOICE_INDEX:
                continue

            delta = choice.get("delta")
            if isinstance(delta, Mapping):
                out.extend(self._feed_delta(delta))

            finish_reason = choice.get("finish_reason")
            if isinstance(finish_reason, str) and finish_reason:
                self._finish_reason = finish_reason
                # Provider đã chốt phần tool call ở đây; phát ngay để FE đổi
                # chip "đang tìm web…" mà không phải chờ chunk `usage` (§7.4).
                out.extend(self._flush_tool_calls())

        usage_raw = raw.get("usage")
        if isinstance(usage_raw, Mapping) and _has_usage(usage_raw):
            self._usage = _parse_usage(usage_raw)
            out.append(Chunk(kind="usage", usage=self._usage))

        return out

    def finish(self) -> list[Chunk]:
        """Đóng stream: xả nốt tool call còn treo rồi phát đúng MỘT `done`.

        Xả lại lần nữa là phòng C19: upstream đứt mà chưa kịp gửi
        `finish_reason` thì `feed()` chưa xả bao giờ, và một tool call đã ghép
        đủ mảnh vẫn còn nằm trong bộ đệm.
        """
        if self._done_emitted:
            return []
        self._done_emitted = True
        out = self._flush_tool_calls()
        out.append(Chunk(kind="done", finish_reason=self._finish_reason, usage=self._usage))
        return out

    # ── nội bộ ────────────────────────────────────────────────────────────

    def _feed_delta(self, delta: Mapping[str, Any]) -> list[Chunk]:
        out: list[Chunk] = []

        # Reasoning trước content: `deepseek-flash` sinh trọn khối reasoning
        # rồi mới tới content (B-33), và khi một chunk mang cả hai thì thứ tự
        # này giữ đúng trình tự model đã nghĩ.
        for key in _REASONING_KEYS:
            piece = delta.get(key)
            if isinstance(piece, str) and piece:
                out.append(Chunk(kind="reasoning", text=piece))
                break

        content = delta.get("content")
        if isinstance(content, str) and content:
            out.append(Chunk(kind="delta", text=content))
        # `content` rỗng hoặc `null` KHÔNG phải lỗi (B-33): `claude-haiku` gửi
        # `content: ""` kèm mỗi mảnh tool call, và `deepseek-flash` có thể trả
        # content rỗng khi `max_tokens` đã bị reasoning tiêu hết.

        self._absorb_tool_calls(delta.get("tool_calls"))
        return out

    def _absorb_tool_calls(self, fragments: Any) -> None:
        if not isinstance(fragments, list):
            return
        for fragment in fragments:
            if not isinstance(fragment, Mapping):
                continue
            # Thiếu `index` thì coi là tool call thứ nhất. Cả ba provider có
            # `tools` trong catalog đều gửi `index` (đo ở T-1.3); mặc định này
            # chỉ để một provider lệch chuẩn không làm mất trắng tool call.
            index = _as_int(fragment.get("index")) or 0
            buffer = self._tool_calls.setdefault(index, _ToolCallBuffer())

            call_id = fragment.get("id")
            if isinstance(call_id, str) and call_id:
                buffer.call_id = call_id

            function = fragment.get("function")
            if isinstance(function, Mapping):
                name = function.get("name")
                if isinstance(name, str) and name:
                    buffer.name = name
                arguments = function.get("arguments")
                if isinstance(arguments, str) and arguments:
                    buffer.arguments.append(arguments)

    def _flush_tool_calls(self) -> list[Chunk]:
        if not self._tool_calls:
            return []
        out: list[Chunk] = []
        for index in sorted(self._tool_calls):
            buffer = self._tool_calls[index]
            if not buffer.name:
                # Vẫn phát ra. Parser chuẩn hoá chứ không xét duyệt: bỏ im lặng
                # một tool call hỏng sẽ thành "model không gọi tool" — đúng
                # kiểu lỗi vô hình mà tool registry (§12) lẽ ra báo rõ được.
                logger.warning(
                    "tool call index=%s không có tên hàm, vẫn phát ra để tầng "
                    "trên báo lỗi tường minh",
                    index,
                )
            out.append(
                Chunk(
                    kind="tool_call",
                    tool_call=ToolCall(
                        call_id=buffer.call_id,
                        name=buffer.name,
                        arguments="".join(buffer.arguments),
                    ),
                )
            )
        self._tool_calls.clear()
        return out


async def parse_stream(raw_stream: AsyncIterator[RawChunk]) -> AsyncIterator[Chunk]:
    """Bọc một stream chunk thô thành stream `Chunk`.

    **Không** `yield` trong `finally`. Hai lý do, cả hai đều là lỗi thật:

    1. `yield` trong `finally` của async generator sẽ nổ `RuntimeError` khi
       consumer huỷ giữa chừng (§7.5) — lúc đó generator đang bị `aclose()`.
    2. Nghĩa vụ "mọi đường thoát đều ghi event kết thúc" (C19) là của
       **worker**, vì chỉ worker biết phân biệt huỷ, timeout và lỗi upstream.
       Parser chỉ phát `done` khi upstream thật sự kết thúc bình thường.

    `await` trong `finally` thì ngược lại là bắt buộc: huỷ giữa chừng phải
    đóng ngay stream nguồn, không chờ bộ thu gom rác. Chưa đóng nghĩa là
    upstream vẫn sinh tiếp và vẫn tính tiền cho chữ không ai đọc (§7.5).
    """
    parser = StreamParser()
    try:
        async for raw in raw_stream:
            for chunk in parser.feed(raw):
                yield chunk
        for chunk in parser.finish():
            yield chunk
    finally:
        aclose = getattr(raw_stream, "aclose", None)
        if aclose is not None:
            await aclose()
