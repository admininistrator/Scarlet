"""`SystemAdapter` dựng request đúng hợp đồng §9.1/ADR-03, không gọi mạng.

KH tham chiếu: §9.1, §9.4, ADR-03, C40 · CLAUDE.md A3, A4, A9.

Ba thứ ở đây sai thì không test nào khác bắt được, mà hậu quả lại im lặng:
`stream_options` tắt ⇒ quota không bao giờ trừ (C40); `tools` gửi thành `null`
cho model không có capability ⇒ provider trả 400 (§9.4); `max_retries` > 0 ⇒
một câu trả lời tính tiền hai lần.

Stream giả trả về **object thật của SDK** (`ChatCompletionChunk`) dựng từ
fixture đã ghi, không phải một bản nhái: `_as_dicts` gọi `model_dump()` trên
nó, nên một bản nhái chỉ chứng minh bản nhái hoạt động.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from openai import omit
from openai.types.chat import ChatCompletionChunk

from app.config.settings import Settings
from app.llm.adapters.system import SystemAdapter

FIXTURES = Path(__file__).parent / "fixtures"


def load_sdk_chunks(name: str) -> list[ChatCompletionChunk]:
    lines = (FIXTURES / name).read_text(encoding="utf-8").splitlines()
    return [ChatCompletionChunk.model_validate(json.loads(x)) for x in lines if x.strip()]


class FakeStream:
    """Đóng vai `openai.AsyncStream` — chỉ hai thứ `_as_dicts` dùng tới."""

    def __init__(self, chunks: list[ChatCompletionChunk]) -> None:
        self._chunks = chunks
        self.closed = False

    async def __aiter__(self) -> Any:  # pragma: no cover - hình dạng do SDK quy định
        for chunk in self._chunks:
            yield chunk

    async def close(self) -> None:
        self.closed = True


class FakeCompletions:
    def __init__(self, stream: FakeStream) -> None:
        self.stream = stream
        self.kwargs: dict[str, Any] = {}

    async def create(self, **kwargs: Any) -> FakeStream:
        self.kwargs = kwargs
        return self.stream


def fake_adapter(name: str = "nr-gemini-flash.text.jsonl") -> tuple[SystemAdapter, FakeCompletions]:
    adapter = SystemAdapter(base_url="http://litellm:4000/v1", api_key="k", timeout_s=1.0)
    completions = FakeCompletions(FakeStream(load_sdk_chunks(name)))
    adapter._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))  # type: ignore[assignment]
    return adapter, completions


async def drain(adapter: SystemAdapter, **overrides: Any) -> list[Any]:
    kwargs: dict[str, Any] = {
        "model": "bat-ky",
        "messages": [{"role": "user", "content": "xin chào"}],
        "tools": None,
        "max_tokens": 128,
        "temperature": 0.0,
        "extra": {},
    }
    kwargs.update(overrides)
    return [chunk async for chunk in await adapter.stream(**kwargs)]


# ══════════════════════════════════════════════════════════════════════════


def test_from_settings_takes_litellm_base_url_and_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A4/A9: adapter không tự biết địa chỉ nào, nó nhận từ `Settings`."""
    monkeypatch.setenv("LITELLM_BASE_URL", "http://litellm:4000/v1")
    monkeypatch.setenv("LLM_REQUEST_TIMEOUT_S", "42")
    adapter = SystemAdapter.from_settings(Settings())
    assert str(adapter._client.base_url).rstrip("/") == "http://litellm:4000/v1"
    assert adapter._client.timeout == 42.0


def test_does_not_retry_by_itself() -> None:
    """Gọi lại một lượt đã sinh dở là trả tiền lần hai (cùng lý do T-1.5)."""
    adapter = SystemAdapter(base_url="http://litellm:4000/v1", api_key="k", timeout_s=1.0)
    assert adapter._client.max_retries == 0


async def test_always_enables_include_usage() -> None:
    """C40 — không có cờ này thì nhiều provider im lặng bỏ chunk `usage`."""
    adapter, completions = fake_adapter()
    await drain(adapter)
    assert completions.kwargs["stream_options"] == {"include_usage": True}
    assert completions.kwargs["stream"] is True


async def test_no_tools_omits_tools_key() -> None:
    """§9.4: model thiếu capability `tools` không được thấy khoá này."""
    adapter, completions = fake_adapter()
    await drain(adapter, tools=None)
    assert completions.kwargs["tools"] is omit
    await drain(adapter, tools=[])
    assert completions.kwargs["tools"] is omit


async def test_tools_sent_verbatim() -> None:
    adapter, completions = fake_adapter()
    tools = [{"type": "function", "function": {"name": "web_search"}}]
    await drain(adapter, tools=tools)
    assert completions.kwargs["tools"] == tools


async def test_extra_goes_into_body_and_empty_is_not_sent() -> None:
    """§9.8: tham số riêng của provider là dữ liệu, adapter không diễn giải."""
    adapter, completions = fake_adapter()
    await drain(adapter, extra={"reasoning_effort": "low"})
    assert completions.kwargs["extra_body"] == {"reasoning_effort": "low"}
    await drain(adapter, extra={})
    assert completions.kwargs["extra_body"] is None


async def test_model_max_tokens_temperature_pass_through() -> None:
    adapter, completions = fake_adapter()
    await drain(adapter, model="ten-tu-catalog", max_tokens=777, temperature=0.3)
    assert completions.kwargs["model"] == "ten-tu-catalog"
    assert completions.kwargs["max_tokens"] == 777
    assert completions.kwargs["temperature"] == 0.3


async def test_temperature_none_is_omitted_not_sent_as_null() -> None:
    """T-S.6 `omit_temperature`: `None` ⇒ `omit`, cùng lối `tools` (SDK gửi `None` thành `null`)."""
    adapter, completions = fake_adapter()
    await drain(adapter, temperature=None)
    assert completions.kwargs["temperature"] is omit


async def test_stream_returns_normalized_chunks() -> None:
    adapter, _ = fake_adapter()
    chunks = await drain(adapter)
    assert [c.kind for c in chunks][-1] == "done"
    assert "".join(c.text or "" for c in chunks if c.kind == "delta")
    assert chunks[-1].usage is not None


async def test_cancel_midway_closes_stream_immediately() -> None:
    """§7.5: chưa đóng là upstream vẫn sinh tiếp và vẫn tính tiền."""
    adapter, completions = fake_adapter("deepseek-flash.text.jsonl")
    stream = await adapter.stream(
        model="bat-ky",
        messages=[{"role": "user", "content": "x"}],
        tools=None,
        max_tokens=16,
        temperature=0.0,
        extra={},
    )
    async for chunk in stream:
        if chunk.kind == "reasoning":
            break
    assert completions.stream.closed is False
    await stream.aclose()
    assert completions.stream.closed is True


async def test_draining_stream_also_closes() -> None:
    adapter, completions = fake_adapter()
    await drain(adapter)
    assert completions.stream.closed is True
