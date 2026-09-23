"""`app/llm/parser.py` chạy trên chunk THẬT của cả bốn provider (§9.1, §7.4).

KH tham chiếu: §9.1, §7.4, §9.4, C9, C19, C40 · B-33 · DoD T-1.3.

Fixture trong `fixtures/` là đúng nội dung dòng `data:` mà provider đã gửi,
ghi lại bằng `scripts/record_llm_fixtures.py` (xem `fixtures/manifest.json`
cho ngày ghi và prompt). Không fixture nào viết tay: mỗi provider lệch chuẩn
OpenAI một kiểu, và đúng những chỗ lệch đó mới là thứ parser phải chịu được.

Nửa đầu file chạy trên fixture thật. Nửa sau là các ca biên dựng tay — những
tình huống không đặt hàng được từ provider (usage thiếu hẳn, stream đứt giữa
tool call, hai tool call song song).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from openai.types.chat import ChatCompletionChunk

from app.llm.client import Chunk
from app.llm.parser import StreamParser, parse_stream

FIXTURES = Path(__file__).parent / "fixtures"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
ENTRIES: list[dict[str, Any]] = MANIFEST["entries"]
FIXTURE_NAMES = [e["file"] for e in ENTRIES]

#: Ký tự thay thế của Unicode. Nó xuất hiện khi một chuỗi bị cắt giữa hai byte
#: của một ký tự nhiều byte rồi mới decode — đúng hiện tượng của C9.
REPLACEMENT_CHAR = "�"

#: Dấu tiếng Việt trong câu trả lời. Có mặt chúng thì phép kiểm C9 mới có
#: nghĩa: một fixture toàn ASCII sẽ "đạt" C9 mà không chứng minh được gì.
VIETNAMESE_MARKS = "ăâđêôơưàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ"


def load_raw(name: str) -> list[dict[str, Any]]:
    lines = (FIXTURES / name).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def run_parser(raws: list[dict[str, Any]]) -> list[Chunk]:
    parser = StreamParser()
    out: list[Chunk] = []
    for raw in raws:
        out.extend(parser.feed(raw))
    out.extend(parser.finish())
    return out


def text_of(chunks: list[Chunk], kind: str) -> str:
    return "".join(c.text or "" for c in chunks if c.kind == kind)


def entry_for(name: str) -> dict[str, Any]:
    return next(e for e in ENTRIES if e["file"] == name)


# ══════════════════════════════════════════════════════════════════════════
# Trên fixture THẬT
# ══════════════════════════════════════════════════════════════════════════


def test_manifest_covers_all_catalog_providers() -> None:
    """DoD đòi fixture của *mọi* provider đang bật, không phải "ba provider".

    Bảng đổi ước lượng ở tasks.md §14 đã ghi: từ T-0.12 catalog có **bốn**
    provider chứ không ba. Test này là chỗ con số đó không lệch âm thầm được —
    thêm provider mới vào catalog mà quên ghi fixture thì đỏ ngay.
    """
    catalog_path = Path(__file__).resolve().parents[3] / "config" / "model_catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    enabled_providers = {m["provider"] for m in catalog["models"] if m.get("enabled", True)}
    providers_with_fixture = {e["provider"] for e in ENTRIES}
    assert enabled_providers <= providers_with_fixture, (
        f"provider chưa có fixture: {sorted(enabled_providers - providers_with_fixture)}"
    )


def test_fixtures_exist_for_both_cases() -> None:
    assert {e["case"] for e in ENTRIES} == {"text", "tools"}


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_every_fixture_ends_with_exactly_one_done(name: str) -> None:
    chunks = run_parser(load_raw(name))
    assert chunks, f"{name}: parser không sinh chunk nào"
    assert chunks[-1].kind == "done"
    assert sum(1 for c in chunks if c.kind == "done") == 1


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_every_fixture_captures_usage_at_stream_end(name: str) -> None:
    """C40: `usage` về 0 hoặc thiếu thì quota không bao giờ trừ."""
    chunks = run_parser(load_raw(name))
    done = chunks[-1]
    assert done.usage is not None, f"{name}: chunk done không mang usage"
    assert done.usage.prompt_tokens > 0
    assert done.usage.completion_tokens > 0
    assert done.usage.total_tokens >= done.usage.prompt_tokens + done.usage.completion_tokens - 1

    before_done = [c for c in chunks if c.kind == "usage"]
    assert len(before_done) == 1, f"{name}: phải có đúng một event usage (§7.4)"
    assert before_done[0].usage == done.usage


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_every_fixture_has_finish_reason(name: str) -> None:
    chunks = run_parser(load_raw(name))
    assert chunks[-1].finish_reason in {"stop", "length", "tool_calls"}


@pytest.mark.parametrize("name", [e["file"] for e in ENTRIES if e["case"] == "text"])
def test_joined_deltas_have_no_replacement_char(name: str) -> None:
    """C9 — phép kiểm chính của DoD, chạy trên chữ thật của model."""
    chunks = run_parser(load_raw(name))
    joined = text_of(chunks, "delta")
    assert joined, f"{name}: không có delta nào"
    assert REPLACEMENT_CHAR not in joined
    assert any(ch in VIETNAMESE_MARKS for ch in joined), (
        f"{name}: câu trả lời không có dấu tiếng Việt — phép kiểm C9 vô nghĩa"
    )


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_no_chunk_carries_empty_text(name: str) -> None:
    """B-33: `content: ""` không phải lỗi, nhưng cũng không phải một event.

    `claude-haiku` gửi `content: ""` kèm **mỗi** mảnh tool call. Để chúng lọt
    ra ngoài là bơm hàng chục event `delta` rỗng qua SSE cho mỗi lần gọi tool.
    """
    for chunk in run_parser(load_raw(name)):
        if chunk.kind in {"delta", "reasoning"}:
            assert chunk.text, f"{name}: chunk {chunk.kind} có text rỗng"


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_sdk_model_dump_loses_nothing(name: str) -> None:
    """Adapter đưa `chunk.model_dump()` vào parser, không phải dict thô.

    Test này là cây cầu giữa fixture (dòng `data:` thật) và đường chạy thật
    (`SystemAdapter._as_dicts`). Nếu SDK `openai` một ngày nào đó nuốt mất
    `reasoning_content` vì nó ngoài schema, chỗ đỏ sẽ là đây chứ không phải
    một hội thoại im lặng mất khối "Đang suy nghĩ…".
    """
    raws = load_raw(name)
    through_sdk = [ChatCompletionChunk.model_validate(raw).model_dump() for raw in raws]
    assert run_parser(raws) == run_parser(through_sdk)


def test_deepseek_streams_reasoning_via_reasoning_content() -> None:
    """B-33: `deepseek-flash` sinh trọn khối reasoning TRƯỚC content."""
    chunks = run_parser(load_raw("deepseek-flash.text.jsonl"))
    kinds = [c.kind for c in chunks]
    assert "reasoning" in kinds
    assert text_of(chunks, "reasoning")

    last_reasoning_index = max(i for i, k in enumerate(kinds) if k == "reasoning")
    first_delta_index = min(i for i, k in enumerate(kinds) if k == "delta")
    assert last_reasoning_index < first_delta_index

    done = chunks[-1]
    assert done.usage is not None
    assert done.usage.reasoning_tokens is not None and done.usage.reasoning_tokens > 0


def test_non_reasoning_provider_has_no_reasoning_chunks() -> None:
    """`reasoning` không nằm trong `capabilities` của `claude-haiku` (§9.4)."""
    chunks = run_parser(load_raw("claude-haiku.text.jsonl"))
    assert not any(c.kind == "reasoning" for c in chunks)
    done = chunks[-1]
    assert done.usage is not None
    assert done.usage.reasoning_tokens == 0  # báo và bằng 0, khác hẳn None


def test_reads_prompt_cached_tokens() -> None:
    """`cached_input_per_1m` đã có trong catalog (§9.2) nên §10.2 cần số này."""
    done = run_parser(load_raw("deepseek-flash.tools.jsonl"))[-1]
    assert done.usage is not None
    assert done.usage.cached_prompt_tokens is not None and done.usage.cached_prompt_tokens > 0


def test_ollama_reports_finish_reason_length() -> None:
    """`max_tokens` chạm trần là `length`, không phải `stop` — §9.6 dựa vào đó."""
    done = run_parser(load_raw("ol-qwen-small.text.jsonl"))[-1]
    assert done.finish_reason == "length"


@pytest.mark.parametrize("name", [e["file"] for e in ENTRIES if e["case"] == "tools"])
def test_tool_call_assembled_from_all_pieces(name: str) -> None:
    """Ba provider gửi tool call ba kiểu; parser phải trả ra cùng một thứ.

    `deepseek-flash` nhỏ giọt `arguments` từng vài ký tự (31 chunk),
    `claude-haiku` gửi vài mảnh kèm `content: ""`, `nr-gemini-flash` gói trọn
    vào một chunk. Chỉ có một cách biết ba đường đó gặp nhau: chạy cả ba.
    """
    chunks = run_parser(load_raw(name))
    tool_calls = [c for c in chunks if c.kind == "tool_call"]
    assert len(tool_calls) == 1, f"{name}: mong đúng một tool call"

    call = tool_calls[0].tool_call
    assert call is not None
    assert call.name == "get_weather"
    assert call.call_id, f"{name}: tool call không có id — lượt sau không ghép cặp được"

    args = json.loads(call.arguments)
    assert "city" in args, f"{name}: arguments ghép lại thiếu tham số bắt buộc"

    assert chunks[-1].finish_reason == "tool_calls"
    assert chunks.index(tool_calls[0]) < len(chunks) - 1, "tool_call phải ra trước done"


# ══════════════════════════════════════════════════════════════════════════
# Ca biên dựng tay — không đặt hàng được từ provider
# ══════════════════════════════════════════════════════════════════════════


def chunk_delta(**delta: Any) -> dict[str, Any]:
    return {"choices": [{"index": 0, "delta": delta}]}


def test_reasoning_field_without_content_suffix_also_accepted() -> None:
    """Provider dùng `delta.reasoning` thay `delta.reasoning_content`."""
    out = run_parser([chunk_delta(reasoning="đang nghĩ")])
    assert [c.kind for c in out] == ["reasoning", "done"]
    assert out[0].text == "đang nghĩ"


def test_one_chunk_carrying_both_reasoning_and_content() -> None:
    out = run_parser([chunk_delta(reasoning_content="nghĩ", content="nói")])
    assert [(c.kind, c.text) for c in out[:2]] == [("reasoning", "nghĩ"), ("delta", "nói")]


def test_rejoins_vietnamese_char_split_across_chunks(  # C9 ở tầng parser
) -> None:
    """`claude-haiku` thật sự chia "Hà Nội" thành "Hà N" + "ội" (xem fixture)."""
    out = run_parser([chunk_delta(content="Hà N"), chunk_delta(content="ội")])
    assert text_of(out, "delta") == "Hà Nội"
    assert REPLACEMENT_CHAR not in text_of(out, "delta")


def test_no_usage_at_all_done_carries_usage_none() -> None:
    """C40 phải *nhìn thấy được*: `None` là tín hiệu để ước tính bằng tiktoken."""
    out = run_parser([chunk_delta(content="xin chào")])
    assert out[-1].kind == "done"
    assert out[-1].usage is None
    assert not any(c.kind == "usage" for c in out)


def test_all_null_usage_is_not_a_token_report() -> None:
    raw = {"choices": [], "usage": {"prompt_tokens": None, "completion_tokens": None}}
    out = run_parser([raw])
    assert out[-1].usage is None


def test_missing_total_tokens_is_summed() -> None:
    raw = {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 7}}
    out = run_parser([raw])
    assert out[-1].usage is not None
    assert out[-1].usage.total_tokens == 17


def test_stream_cut_midway_still_flushes_partial_tool_call() -> None:
    """C19: upstream đứt mà chưa gửi `finish_reason`."""
    out = run_parser(
        [
            chunk_delta(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "call_1",
                        "function": {"name": "web_search", "arguments": '{"q":'},
                    }
                ]
            ),
            chunk_delta(tool_calls=[{"index": 0, "function": {"arguments": '"phở"}'}}]),
        ]
    )
    assert [c.kind for c in out] == ["tool_call", "done"]
    assert out[0].tool_call is not None
    assert out[0].tool_call.arguments == '{"q":"phở"}'
    assert out[-1].finish_reason is None


def test_two_parallel_tool_calls_in_index_order() -> None:
    out = run_parser(
        [
            chunk_delta(
                tool_calls=[
                    {"index": 1, "id": "b", "function": {"name": "hai", "arguments": "{}"}},
                    {"index": 0, "id": "a", "function": {"name": "mot", "arguments": "{}"}},
                ]
            ),
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
        ]
    )
    name = [c.tool_call.name for c in out if c.kind == "tool_call" and c.tool_call]
    assert name == ["mot", "hai"]


def test_nameless_tool_call_still_emitted_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Bỏ im lặng sẽ thành "model không gọi tool" — lỗi vô hình."""
    with caplog.at_level("WARNING", logger="app.llm.parser"):
        out = run_parser(
            [
                chunk_delta(tool_calls=[{"index": 0, "id": "x", "function": {"arguments": "{}"}}]),
                {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
            ]
        )
    assert any(c.kind == "tool_call" for c in out)
    assert "không có tên hàm" in caplog.text


def test_skips_choices_other_than_index_0() -> None:
    raw = {
        "choices": [
            {"index": 0, "delta": {"content": "giữ"}},
            {"index": 1, "delta": {"content": "bỏ"}},
        ]
    }
    assert text_of(run_parser([raw]), "delta") == "giữ"


def test_second_finish_emits_no_extra_done() -> None:
    parser = StreamParser()
    parser.feed(chunk_delta(content="x"))
    assert len(parser.finish()) == 1
    assert parser.finish() == []


def test_odd_chunk_does_not_break_parser() -> None:
    """Thà bỏ qua một chunk lạ còn hơn cho cả lượt chat chết vì `TypeError`."""
    out = run_parser(
        [
            {},
            {"choices": None},
            {"choices": ["không phải object"]},
            {"choices": [{"index": 0, "delta": "không phải object"}]},
            {"choices": [{"index": 0, "delta": {"content": None, "tool_calls": None}}]},
            chunk_delta(content="sống sót"),
        ]
    )
    assert text_of(out, "delta") == "sống sót"


# ══════════════════════════════════════════════════════════════════════════
# `parse_stream` — lớp async
# ══════════════════════════════════════════════════════════════════════════


async def aiter(raws: list[dict[str, Any]]) -> Any:
    for raw in raws:
        yield raw


async def test_parse_stream_matches_streamparser() -> None:
    raws = load_raw("nr-gemini-flash.text.jsonl")
    through_stream = [c async for c in parse_stream(aiter(raws))]
    assert through_stream == run_parser(raws)


async def test_cancel_midway_raises_no_runtime_error() -> None:
    """§7.5: consumer thoát sớm. `yield` trong `finally` sẽ nổ ở đúng chỗ này."""
    stream = parse_stream(aiter(load_raw("deepseek-flash.text.jsonl")))
    async for chunk in stream:
        if chunk.kind == "delta":
            break
    await stream.aclose()  # không được raise
