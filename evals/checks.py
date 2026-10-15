"""Phép kiểm của eval golden set (§21.3) — hàm thuần trên dữ liệu runner đã thu.

KH tham chiếu: §21.3, §7.4, §7.5, §9.6, §13.5, §15.3, C9, C10, C11, C41 · tasks.md T-9.1.

Kiểm **tầng tích hợp**, không chấm chất lượng câu trả lời. Mỗi hàm nhận các
lượt (`Turn`) của một ca và ngưỡng của tệp ca, trả danh sách lý do hỏng —
rỗng là đạt. Không I/O ở đây để `backend/tests/evals/` dựng SSE / usage giả
mà kiểm được từng phép.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

REPLACEMENT_CHAR = "�"
#: Rào mở ở cột 0 (lối `app/llm/artifact_blocks.py`) — lấy chữ ngôn ngữ.
_FENCE_OPEN = re.compile(r"^(?:```|~~~)\s*([\w+#.-]+)", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class SseEvent:
    event: str
    data: str


@dataclass(slots=True)
class Turn:
    """Một lượt: event SSE đọc được + hàng `messages` của câu trả lời sau `done`."""

    events: list[SseEvent]
    status: str | None = None
    content: str = ""
    reasoning: str | None = None
    finish_reason: str | None = None
    error_code: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    #: Số hàng `usage_events` của message này (§7.5: huỷ vẫn đúng một hàng).
    usage_rows: int = 0
    tool_rounds: list[dict[str, Any]] | None = None
    artifact_languages: list[str | None] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Context:
    thresholds: Mapping[str, Any]
    context_window: int = 0
    #: `token_budget()` của §9.6 cho model đang chạy.
    budget: int = 0
    #: Token (tiktoken, cách §9.6 đếm) của lịch sử seed thẳng DB — ca ⑩.
    history_tokens: int = 0


Check = Callable[[list[Turn], Context], list[str]]


# ─────────────────────────────── dùng chung ────────────────────────────────


def _payloads(turn: Turn) -> tuple[list[tuple[str, Any]], list[str]]:
    """Mọi event `json.loads` được (C10) — trả payload đã đọc + lý do hỏng."""
    out: list[tuple[str, Any]] = []
    errors: list[str] = []
    for ev in turn.events:
        try:
            out.append((ev.event, json.loads(ev.data)))
        except ValueError as exc:
            errors.append(f"event `{ev.event}` không phải JSON (C10): {exc}: {ev.data[:80]!r}")
    return out, errors


def _joined(payloads: list[tuple[str, Any]], kind: str) -> str:
    return "".join(str(p.get("t", "")) for name, p in payloads if name == kind)


def _completed(turn: Turn, label: str = "") -> list[str]:
    """`completed` + event cuối là `done` + mọi event là JSON."""
    _, errors = _payloads(turn)
    if turn.status != "completed":
        errors.append(f"{label}status={turn.status} error_code={turn.error_code} (cần completed)")
    last = turn.events[-1].event if turn.events else None
    if last != "done":
        errors.append(f"{label}event cuối là `{last}` (cần `done`)")
    return errors


def _single_call(turn: Turn, label: str = "") -> list[str]:
    """Phép so `prompt_tokens` chỉ có nghĩa với MỘT lần gọi model: lượt có vòng
    tool mang usage là tổng mọi lần gọi (B-160) — model tự gọi tool khi không ai
    bảo là hỏng của ca, không phải số để so."""
    if turn.tool_rounds:
        return [
            f"{label}model tự gọi tool ({len(turn.tool_rounds)} vòng) — usage là tổng nhiều lần gọi"
        ]
    return []


def _done_usage(turn: Turn) -> Mapping[str, Any]:
    for ev in reversed(turn.events):
        if ev.event == "done":
            try:
                usage = json.loads(ev.data).get("usage")
            except ValueError:
                return {}
            return usage if isinstance(usage, dict) else {}
    return {}


def _tool_events(turn: Turn, kind: str, name: str) -> list[Mapping[str, Any]]:
    payloads, _ = _payloads(turn)
    return [p for ev, p in payloads if ev == kind and p.get("name") == name]


# ─────────────────────────────── 12 phép kiểm ──────────────────────────────


def check_text(turns: list[Turn], ctx: Context) -> list[str]:
    """① / ⑪ — chữ ghép từ `delta` == `messages.content` từng byte, 0 `U+FFFD` (C9, C10)."""
    turn = turns[0]
    errors = _completed(turn)
    payloads, _ = _payloads(turn)
    streamed = _joined(payloads, "delta")
    if streamed != turn.content:
        errors.append(f"delta ({len(streamed)} ký tự) ≠ content ({len(turn.content)} ký tự) — C9")
    if REPLACEMENT_CHAR in turn.content or REPLACEMENT_CHAR in streamed:
        errors.append("có U+FFFD (C9)")
    nfd = unicodedata.normalize("NFD", turn.content)
    if ctx.thresholds.get("require_diacritics") and not any(map(unicodedata.combining, nfd)):
        errors.append("content không có ký tự có dấu nào")
    for needle in ctx.thresholds.get("must_contain", []):
        if needle not in turn.content:
            errors.append(f"content thiếu {needle!r}")
    return errors


def check_long(turns: list[Turn], ctx: Context) -> list[str]:
    """② — `completion_tokens ≥ min`, `completed`, không `WORKER_TIMEOUT`."""
    turn = turns[0]
    errors = _completed(turn)
    floor = int(ctx.thresholds["min_completion_tokens"])
    if (turn.completion_tokens or 0) < floor:
        errors.append(f"completion_tokens={turn.completion_tokens} < {floor}")
    if turn.error_code == "WORKER_TIMEOUT":
        errors.append("WORKER_TIMEOUT")
    return errors


def check_code(turns: list[Turn], ctx: Context) -> list[str]:
    """③ — rào mang `language`, artifact cùng `language` (T-5.1)."""
    turn = turns[0]
    errors = _completed(turn)
    want = str(ctx.thresholds["language"])
    fences = [m.lower() for m in _FENCE_OPEN.findall(turn.content)]
    if want not in fences:
        errors.append(f"không có rào ```{want} (rào thấy: {fences})")
    if want not in turn.artifact_languages:
        errors.append(f"không artifact language={want} (artifact: {turn.artifact_languages})")
    return errors


def check_one_tool(turns: list[Turn], ctx: Context) -> list[str]:
    """④ — đúng một cặp `tool_call` / `tool_result` của tool, cùng `call_id`, `ok`."""
    turn = turns[0]
    errors = _completed(turn)
    tool = str(ctx.thresholds["tool"])
    payloads, _ = _payloads(turn)
    calls = [p for ev, p in payloads if ev == "tool_call"]
    results = [p for ev, p in payloads if ev == "tool_result"]
    if len(calls) != 1 or len(results) != 1:
        errors.append(f"{len(calls)} tool_call / {len(results)} tool_result (cần 1 / 1)")
        return errors
    if calls[0].get("name") != tool:
        errors.append(f"tool_call tên {calls[0].get('name')!r} (cần {tool!r})")
    if calls[0].get("call_id") != results[0].get("call_id"):
        errors.append("call_id của tool_call và tool_result khác nhau")
    if results[0].get("ok") is not True:
        errors.append(f"tool_result ok={results[0].get('ok')} result={results[0].get('result')}")
    return errors


def check_tool_rounds(turns: list[Turn], ctx: Context) -> list[str]:
    """⑤ — ≥ `min_rounds` vòng tool trong một lượt (§13.5, `messages.tool_rounds`)."""
    turn = turns[0]
    errors = _completed(turn)
    floor = int(ctx.thresholds["min_rounds"])
    rounds = len(turn.tool_rounds or [])
    if rounds < floor:
        errors.append(f"{rounds} vòng tool < {floor}")
    return errors


def check_tool_error(turns: list[Turn], ctx: Context) -> list[str]:
    """⑥ — tool hỏng ⇒ `tool_result` mang lỗi, lượt vẫn `completed` có chữ."""
    turn = turns[0]
    errors = _completed(turn)
    tool = str(ctx.thresholds["tool"])
    if not _tool_events(turn, "tool_call", tool):
        errors.append(f"model không gọi {tool}")
    results = _tool_events(turn, "tool_result", tool)
    if not results:
        errors.append(f"không có tool_result của {tool}")
    elif any(r.get("ok") is not False for r in results):
        errors.append(f"tool_result của {tool} không mang lỗi: {results}")
    if not turn.content.strip():
        errors.append("content rỗng sau tool lỗi")
    return errors


def check_image(turns: list[Turn], ctx: Context) -> list[str]:
    """⑦ — `prompt_tokens` lượt có ảnh − lượt không ảnh ≥ ngưỡng (§15.3)."""
    plain, image = turns
    errors = _completed(plain, "không ảnh: ") + _completed(image, "có ảnh: ")
    errors += _single_call(plain, "không ảnh: ") + _single_call(image, "có ảnh: ")
    floor = int(ctx.thresholds["min_image_tokens"])
    delta = (image.prompt_tokens or 0) - (plain.prompt_tokens or 0)
    if delta < floor:
        errors.append(
            f"prompt_tokens có ảnh {image.prompt_tokens} − không ảnh {plain.prompt_tokens}"
            f" = {delta} < {floor}"
        )
    return errors


def check_reasoning(turns: list[Turn], ctx: Context) -> list[str]:
    """⑧ — có event `reasoning`, khớp `messages.reasoning`, không lọt vào `content`."""
    turn = turns[0]
    errors = _completed(turn)
    payloads, _ = _payloads(turn)
    thought = _joined(payloads, "reasoning")
    if not thought.strip():
        errors.append("không có event `reasoning`")
        return errors
    if thought != (turn.reasoning or ""):
        errors.append("chữ event `reasoning` ≠ messages.reasoning")
    if _joined(payloads, "delta") != turn.content:
        errors.append("delta ≠ content")
    probe = thought.strip()[: int(ctx.thresholds.get("leak_probe_chars", 200))]
    if probe in turn.content:
        errors.append("chữ reasoning lọt vào content")
    return errors


def check_cancel(turns: list[Turn], ctx: Context) -> list[str]:
    """⑨ — huỷ sau `delta` đầu ⇒ `cancelled` + đúng một dòng `usage_events` (§7.5)."""
    turn = turns[0]
    _, errors = _payloads(turn)
    if turn.status != "cancelled" or turn.finish_reason != "cancelled":
        errors.append(f"status={turn.status} finish_reason={turn.finish_reason} (cần cancelled)")
    if turn.usage_rows != 1:
        errors.append(f"{turn.usage_rows} dòng usage_events (cần 1)")
    if not turn.events or turn.events[-1].event != "done":
        errors.append("không kết thúc bằng `done`")
    return errors


def check_context_full(turns: list[Turn], ctx: Context) -> list[str]:
    """⑩ — lịch sử > ngân sách §9.6 ⇒ đã cắt: `prompt_tokens` ≤ cửa sổ, < lịch sử.

    Thêm hai biên quanh `budget` (Cạm bẫy ③): dưới ⇒ provider cắt im lặng
    (Ollama `num_ctx` nhỏ hơn catalog); trên ⇒ `context.build` không cắt mà
    provider nuốt hết hoặc tự cắt ở cửa sổ của nó.
    """
    turn = turns[0]
    errors = _completed(turn) + _single_call(turn)
    prompt = turn.prompt_tokens or 0
    if prompt > ctx.context_window:
        errors.append(f"prompt_tokens={prompt} > context_window={ctx.context_window}")
    if prompt >= ctx.history_tokens:
        errors.append(f"prompt_tokens={prompt} ≥ lịch sử {ctx.history_tokens} — không cắt")
    low = float(ctx.thresholds["min_budget_fill"]) * ctx.budget
    high = float(ctx.thresholds["max_budget_fill"]) * ctx.budget
    if not low <= prompt <= high:
        errors.append(
            f"prompt_tokens={prompt} ngoài [{low:.0f}, {high:.0f}] quanh ngân sách {ctx.budget}"
        )
    return errors


def check_history(turns: list[Turn], ctx: Context) -> list[str]:
    """⑫ — `prompt_tokens` lượt 2 ≥ prompt + completion lượt 1 (C11).

    Token suy luận nằm trong `completion_tokens` nhưng không gửi lại (B-33)
    ⇒ trừ khoá `reasoning` của `done` lượt 1 nếu provider báo.
    """
    first, second = turns
    errors = _completed(first, "lượt 1: ") + _completed(second, "lượt 2: ")
    errors += _single_call(first, "lượt 1: ")
    if errors:
        return errors
    hidden = int(_done_usage(first).get("reasoning") or 0)
    carried = (first.prompt_tokens or 0) + (first.completion_tokens or 0) - hidden
    if (second.prompt_tokens or 0) < carried:
        errors.append(
            f"prompt_tokens lượt 2 = {second.prompt_tokens} < {carried}"
            f" (prompt {first.prompt_tokens} + completion {first.completion_tokens}"
            f" − reasoning {hidden} của lượt 1)"
        )
    return errors


CHECKS: dict[str, Check] = {
    "text": check_text,
    "long": check_long,
    "code": check_code,
    "one_tool": check_one_tool,
    "tool_rounds": check_tool_rounds,
    "tool_error": check_tool_error,
    "image": check_image,
    "reasoning": check_reasoning,
    "cancel": check_cancel,
    "context_full": check_context_full,
    "history": check_history,
}
