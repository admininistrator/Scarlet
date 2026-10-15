"""T-9.1 — phép kiểm của eval golden set (`evals/checks.py`) trên SSE / usage dựng sẵn.

Mỗi phép một ca đạt + một ca hỏng; nạp `evals/` theo đường dẫn (lối
`check_export.py` của T-8.6) — `evals/` nằm ngoài gói `app`.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

EVALS = Path(__file__).resolve().parents[3] / "evals"
_spec = importlib.util.spec_from_file_location("eval_checks", EVALS / "checks.py")
assert _spec is not None and _spec.loader is not None
checks = importlib.util.module_from_spec(_spec)
sys.modules["eval_checks"] = checks  # dataclass cần module có trong sys.modules
_spec.loader.exec_module(checks)

Turn = checks.Turn
Context = checks.Context


def ev(kind: str, **data: Any) -> Any:
    return checks.SseEvent(kind, json.dumps(data, ensure_ascii=False))


def done(**usage: Any) -> Any:
    return ev("done", finish_reason="stop", usage=usage or None)


def text_turn(content: str, streamed: str | None = None) -> Any:
    streamed = content if streamed is None else streamed
    return Turn(
        events=[ev("start"), ev("delta", t=streamed[:3]), ev("delta", t=streamed[3:]), done()],
        status="completed",
        content=content,
    )


def tool_turn(name: str, ok: bool, *, call_id: str = "c1", content: str = "xong") -> Any:
    return Turn(
        events=[
            ev("tool_call", call_id=call_id, name=name, args={}),
            ev("tool_result", call_id=call_id, name=name, ok=ok, result={}),
            ev("delta", t=content),
            done(),
        ],
        status="completed",
        content=content,
        tool_rounds=[{"tool_calls": [], "results": []}],
    )


def run(check: str, turns: list[Any], **ctx: Any) -> list[str]:
    thresholds = ctx.pop("thresholds", {})
    return checks.CHECKS[check](turns, Context(thresholds=thresholds, **ctx))  # type: ignore[no-any-return]


# ① / ⑪ — chữ đi nguyên vẹn (C9, C10)


def test_text_vi_passes_when_delta_equals_content() -> None:
    assert (
        run("text", [text_turn("Lá có diệp lục.")], thresholds={"require_diacritics": True}) == []
    )


def test_text_vi_fails_when_content_mangled_by_ascii_replace() -> None:
    errors = run(
        "text",
        [text_turn("L? c? di?p l?c.", streamed="Lá có diệp lục.")],
        thresholds={"require_diacritics": True},
    )
    assert any("delta" in e for e in errors)
    assert any("có dấu" in e for e in errors)


def test_text_special_chars_pass() -> None:
    content = '👩\u200d💻 nói "xin chào" \\ C:\\tmp\ndòng hai'
    thresholds = {"must_contain": ["\u200d", '"', "\\", "\n"]}
    assert run("text", [text_turn(content)], thresholds=thresholds) == []


def test_text_special_chars_fail_on_broken_json_and_missing_chars() -> None:
    turn = text_turn("xin chao")
    turn.events.insert(1, checks.SseEvent("delta", '{"t":"a\nb"'))
    errors = run("text", [turn], thresholds={"must_contain": ["\u200d"]})
    assert any("C10" in e for e in errors)
    assert any("thiếu" in e for e in errors)


# ② dài


def test_long_passes() -> None:
    turn = text_turn("1\n2")
    turn.completion_tokens = 2400
    assert run("long", [turn], thresholds={"min_completion_tokens": 2000}) == []


def test_long_fails_on_worker_timeout() -> None:
    turn = Turn(
        events=[ev("error", code="WORKER_TIMEOUT")], status="failed", error_code="WORKER_TIMEOUT"
    )
    errors = run("long", [turn], thresholds={"min_completion_tokens": 2000})
    assert any("WORKER_TIMEOUT" in e for e in errors)
    assert any("completion_tokens" in e for e in errors)


# ③ khối mã


def test_code_passes_when_artifact_language_matches_fence() -> None:
    turn = text_turn("```python\nprint(1)\n```")
    turn.artifact_languages = ["python"]
    assert run("code", [turn], thresholds={"language": "python"}) == []


def test_code_fails_without_artifact() -> None:
    turn = text_turn("```python\nprint(1)\n```")
    assert run("code", [turn], thresholds={"language": "python"}) != []


# ④ một tool


def test_one_tool_passes() -> None:
    assert run("one_tool", [tool_turn("load_skill", True)], thresholds={"tool": "load_skill"}) == []


def test_one_tool_fails_without_tool_result() -> None:
    turn = tool_turn("load_skill", True)
    del turn.events[1]
    errors = run("one_tool", [turn], thresholds={"tool": "load_skill"})
    assert errors == ["1 tool_call / 0 tool_result (cần 1 / 1)"]


# ⑤ hai tool liên tiếp


def test_tool_rounds_passes_with_two_rounds() -> None:
    turn = tool_turn("load_skill", True)
    turn.tool_rounds = [{}, {}]
    assert run("tool_rounds", [turn], thresholds={"min_rounds": 2}) == []


def test_tool_rounds_fails_with_parallel_calls_in_one_round() -> None:
    errors = run("tool_rounds", [tool_turn("load_skill", True)], thresholds={"min_rounds": 2})
    assert errors == ["1 vòng tool < 2"]


# ⑥ tool lỗi


def test_tool_error_passes_when_result_carries_error_and_turn_completes() -> None:
    assert (
        run("tool_error", [tool_turn("fetch_url", False)], thresholds={"tool": "fetch_url"}) == []
    )


def test_tool_error_fails_when_tool_reports_ok() -> None:
    errors = run("tool_error", [tool_turn("fetch_url", True)], thresholds={"tool": "fetch_url"})
    assert any("không mang lỗi" in e for e in errors)


# ⑦ ảnh


def _image_pair(plain: int, image: int) -> list[Any]:
    a, b = text_turn("không có ảnh"), text_turn("ba hình")
    a.prompt_tokens, b.prompt_tokens = plain, image
    return [a, b]


def test_image_passes_when_image_adds_tokens() -> None:
    assert run("image", _image_pair(300, 700), thresholds={"min_image_tokens": 100}) == []


def test_image_fails_when_image_dropped() -> None:
    errors = run("image", _image_pair(300, 305), thresholds={"min_image_tokens": 100})
    assert any("< 100" in e for e in errors)


# ⑧ reasoning


def test_reasoning_passes_when_separated() -> None:
    turn = text_turn("10")
    turn.events.insert(0, ev("reasoning", t="5 người, C(5,2) = 10"))
    turn.reasoning = "5 người, C(5,2) = 10"
    assert run("reasoning", [turn]) == []


def test_reasoning_fails_when_reasoning_streamed_as_delta() -> None:
    thought = "5 người, C(5,2) = 10"
    turn = text_turn(thought + "10")
    errors = run("reasoning", [turn])
    assert errors == ["không có event `reasoning`"]


# ⑨ huỷ


def test_cancel_passes() -> None:
    turn = Turn(
        events=[
            ev("delta", t="Hà"),
            ev("done", finish_reason="cancelled", usage={"cost_usd": 0.0}),
        ],
        status="cancelled",
        finish_reason="cancelled",
        usage_rows=1,
    )
    assert run("cancel", [turn]) == []


def test_cancel_fails_without_usage_row() -> None:
    turn = Turn(
        events=[ev("delta", t="Hà"), ev("done", finish_reason="cancelled", usage=None)],
        status="cancelled",
        finish_reason="cancelled",
        usage_rows=0,
    )
    assert run("cancel", [turn]) == ["0 dòng usage_events (cần 1)"]


# ⑩ context gần đầy


FULL = {"min_budget_fill": 0.8, "max_budget_fill": 1.1}


def _full(prompt: int) -> Any:
    turn = text_turn("four")
    turn.prompt_tokens = prompt
    return turn


def test_context_full_passes_when_trimmed_to_budget() -> None:
    ctx = {"context_window": 32768, "budget": 27672, "history_tokens": 33278}
    assert run("context_full", [_full(27548)], thresholds=FULL, **ctx) == []


def test_context_full_fails_on_silent_provider_truncation() -> None:
    # Cạm bẫy ③ — Ollama `num_ctx` 4096: "đã cắt" giả, xa dưới ngân sách.
    ctx = {"context_window": 32768, "budget": 27672, "history_tokens": 33278}
    errors = run("context_full", [_full(3838)], thresholds=FULL, **ctx)
    assert any("ngoài" in e for e in errors)


def test_context_full_fails_when_budget_ignored() -> None:
    ctx = {"context_window": 200000, "budget": 118808, "history_tokens": 143180}
    errors = run("context_full", [_full(143900)], thresholds=FULL, **ctx)
    assert any("không cắt" in e for e in errors)


# ⑫ hai lượt


def _two(p1: int, c1: int, p2: int, reasoning: int | None = None) -> list[Any]:
    first, second = text_turn("Hà Nội, Huế"), text_turn("Huế")
    first.prompt_tokens, first.completion_tokens, second.prompt_tokens = p1, c1, p2
    if reasoning is not None:
        first.events[-1] = done(reasoning=reasoning)
    return [first, second]


def test_history_passes_when_turn_one_is_carried() -> None:
    assert run("history", _two(500, 200, 760)) == []


def test_history_discounts_hidden_reasoning() -> None:
    # grok / deepseek: suy luận nằm trong completion nhưng không gửi lại (B-33).
    assert run("history", _two(494, 3864, 872, reasoning=3600)) == []


def test_history_fails_when_only_last_turn_sent() -> None:
    errors = run("history", _two(500, 200, 520))
    assert errors and "< 700" in errors[0]


def test_history_fails_when_turn_one_called_tools() -> None:
    turns = _two(1835, 344, 917)
    turns[0].tool_rounds = [{}]
    assert any("tự gọi tool" in e for e in run("history", turns))


# tệp ca


def test_case_files_are_twelve_and_well_formed() -> None:
    cases = [
        json.loads(p.read_text(encoding="utf-8")) for p in sorted((EVALS / "cases").glob("*.json"))
    ]
    assert len(cases) == 12
    assert len({c["id"] for c in cases}) == 12
    assert {c["check"] for c in cases} == set(checks.CHECKS)  # không phép kiểm nào mồ côi
    for case in cases:
        assert case["check"] in checks.CHECKS, case["id"]
        assert set(case["needs"]) <= {"tools", "vision", "reasoning"}, case["id"]
        assert case["turns"], case["id"]
        for turn in case["turns"]:
            if "attachment" in turn:
                assert (EVALS / "cases" / turn["attachment"]).is_file()
