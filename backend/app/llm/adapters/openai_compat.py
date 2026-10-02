"""Thân chung của mọi adapter OpenAI-compatible (§9.1, ADR-03, ADR-04) — T-2.15.

KH tham chiếu: §9.1, ADR-03, ADR-04, C40 · CLAUDE.md A3, A9 · tasks.md T-2.15.

┌──────────────────────────────────────────────────────────────────────────┐
│  CẠM BẪY CỦA T-2.15 — VÀ VÌ SAO FILE NÀY TỒN TẠI                        │
└──────────────────────────────────────────────────────────────────────────┘

*"Hai code path streaming khác nhau cho hai adapter. Cả hai đều
OpenAI-compatible nên phải dùng **chung** parser — nếu thấy mình copy code,
dừng lại."*

Chép `stream()` sang một file thứ hai là chép luôn năm quyết định mà không ai
sẽ nhớ đồng bộ về sau: `stream_options={"include_usage": True}` (thiếu ⇒ quota
không bao giờ trừ, C40), `tools=omit` thay vì `None` (§9.4, C18),
`max_retries=0` (thử lại ⇒ hoá đơn lần hai), `extra_body` đi thẳng không diễn
giải (A3), và `finally: await stream.close()` (thiếu ⇒ huỷ giữa chừng để
upstream chảy tiếp và vẫn tính tiền, §7.5).

Vì vậy §9.1 chỉ có **một** thân: hai adapter khác nhau đúng ba tham số của
`__init__` — địa chỉ, credential, và header phụ — nên chúng là hai lớp con
rỗng chứ không phải hai bản sao. `SystemAdapter.from_settings()` và
`ByokAdapter.for_provider()` là toàn bộ phần riêng của mỗi bên.

**A9 không bị vi phạm khi `ByokAdapter` bỏ qua LiteLLM.** A9 nói backend chỉ
nói **một protocol** với model (OpenAI Chat Completions streaming) — và cả hai
adapter nói đúng protocol đó, qua đúng một SDK, đúng một parser. Bảng §9.1
viết thẳng rằng `ByokAdapter` lấy `base_url` "từ `provider.base_url` trong
catalog": gửi khoá của người dùng qua LiteLLM là bất khả vì LiteLLM xác thực
bằng `LITELLM_MASTER_KEY` của chính nó (xem `llm/byok_verify.py`).

`app/llm/adapters/` là chỗ DUY NHẤT trong `app/` được import SDK `openai`;
`app/api/` bị `scripts/check_hardcode.sh` lệnh 1 chặn thẳng.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from typing import TYPE_CHECKING, Any, cast

import httpx
from openai import AsyncOpenAI, omit
from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionStreamOptionsParam,
    ChatCompletionToolUnionParam,
)

from app.llm.client import Chunk
from app.llm.parser import RawChunk, parse_stream

if TYPE_CHECKING:
    from openai import AsyncStream
    from openai.types.chat import ChatCompletionChunk

#: Retry của generation **không** phải một nút xoay. Gọi lại một lượt đã sinh
#: dở là trả tiền lần hai cho cùng một câu trả lời (cùng lý do với
#: `max_tries: 1` của arq ở T-1.5). LiteLLM đã có `num_retries: 2` cho chặng
#: LiteLLM→provider, nơi biết chắc request nào chưa tiêu token nào. Với
#: `ByokAdapter` thì không có chặng nào như vậy, nên con số 0 ở đây càng đúng:
#: tiền bị tính lần hai là tiền của **người dùng**.
_NO_RETRY = 0

#: §7.4 và §10.2 đều cần số token thật. Không bật cờ này thì nhiều provider
#: không gửi chunk `usage` cuối, `cost_usd` bằng 0 và quota không bao giờ trừ
#: (C40). `drop_params: true` trong `litellm.config.yaml` lo phần provider
#: không hiểu tham số này — trên đường BYOK thì không có ai lo, nên một
#: provider không hiểu sẽ nói ra bằng `400` thay vì im lặng.
_STREAM_OPTIONS: ChatCompletionStreamOptionsParam = {"include_usage": True}


async def _as_dicts(stream: AsyncStream[ChatCompletionChunk]) -> AsyncIterator[RawChunk]:
    """Đổi object của SDK thành dict, và đóng kết nối trên MỌI đường thoát.

    `model_dump()` giữ nguyên cả trường ngoài schema của SDK — đã kiểm:
    `reasoning_content` (B-33) và `completion_tokens_details.reasoning_tokens`
    đều còn nguyên. Xem `parser.py` cho lý do parser làm việc với dict.

    `finally: await stream.close()` là bắt buộc chứ không phải cho gọn: khi
    người dùng bấm Huỷ (§7.5) worker thoát vòng lặp giữa chừng, và không đóng
    thì kết nối HTTP tới upstream nằm treo tới lúc timeout — upstream vẫn sinh
    tiếp và vẫn tính tiền.
    """
    try:
        async for chunk in stream:
            yield chunk.model_dump()
    finally:
        await stream.close()


class OpenAICompatAdapter:
    """Cài đặt `LLMClient` (§9.1) dùng SDK `openai` async. Xem docstring module.

    Giữ một instance cho cả vòng đời của **người sở hữu nó**: `AsyncOpenAI`
    mang theo một connection pool gắn với event loop. `SystemAdapter` sống
    bằng vòng đời tiến trình worker (dựng ở `on_startup`, cất trong `ctx`);
    `ByokAdapter` sống bằng vòng đời **một lượt sinh**, vì credential của nó
    thuộc về một người dùng cụ thể. Cũng vì gắn với event loop nên **không**
    có instance toàn cục ở tầng module.
    """

    __slots__ = ("_client",)

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_s: float,
        default_headers: dict[str, str] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout_s,
            max_retries=_NO_RETRY,
            # `Provider.extra_headers` của catalog (B-166). `None` chứ không
            # `{}`: SDK phân biệt hai cái, và một dict rỗng vẫn đi qua đường
            # merge header của nó mỗi request.
            default_headers=default_headers or None,
            # Endpoint BYOK tự nhập: client ghim IP của T-6.3 (A5, T-S.19b).
            # `close()` của SDK đóng luôn client này.
            # Chữ ký của SDK 3.x ghi `httpx2.AsyncClient`, nhưng lúc chạy SDK
            # nhận cả `httpx.AsyncClient` (đo trong container, openai 3.16.2).
            http_client=cast("Any", http_client),
        )

    async def close(self) -> None:
        """Đóng connection pool. Chủ sở hữu gọi — xem docstring lớp."""
        await self._client.close()

    async def stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
        temperature: float | None,
        extra: dict[str, Any],
    ) -> AsyncIterator[Chunk]:
        """Xem `LLMClient.stream`. Gọi bằng `async for c in await adapter.stream(...)`.

        `await` ở đây gửi request và chờ header, nên `401/400/429` nổ tại đây
        chứ không đội lốt stream rỗng — lý do §9.1 khai `async def` thay vì
        async generator (xem docstring `client.py`).

        `model` là tên upstream hiểu, và **ai gọi thì người đó chọn**: alias
        LiteLLM cho `SystemAdapter`, `ModelEntry.provider_model` cho
        `ByokAdapter`. Adapter không tự tra catalog — nó không biết catalog
        tồn tại (A3, §9.1).
        """
        raw = await self._client.chat.completions.create(
            model=model,
            # `cast` chứ không phải `type: ignore`: message là dict thô dựng ở
            # `app/llm/context.py` (T-1.4) theo đúng schema OpenAI, nhưng
            # TypedDict của SDK không nhận `dict[str, Any]` — chỗ này khai
            # tường minh rằng người gọi chịu trách nhiệm về hình dạng đó.
            messages=cast(Iterable[ChatCompletionMessageParam], messages),
            # `tools=None` và `tools=[]` đều bị SDK gửi đi thành `"tools": null`;
            # model không có capability `tools` (§9.4) thì không được thấy khoá
            # này, nên phải là `omit`.
            tools=cast(Iterable[ChatCompletionToolUnionParam], tools) if tools else omit,
            max_tokens=max_tokens,
            # `None` ⇒ khoá vắng hẳn khỏi body, cùng lý do `tools` ở trên: SDK
            # gửi `None` thành `"temperature": null`, và Anthropic bật thinking
            # từ chối mọi `temperature` khác 1 (T-S.2) — `omit_temperature` của
            # catalog chỉ có nghĩa khi khoá thật sự không có mặt.
            temperature=temperature if temperature is not None else omit,
            stream=True,
            stream_options=_STREAM_OPTIONS,
            # Tham số riêng của provider (`reasoning_effort`, `thinking`…) đi
            # thẳng vào body. Adapter không diễn giải: diễn giải là bắt đầu
            # hardcode tên provider vào code (A3, §9.8).
            extra_body=extra or None,
        )
        return parse_stream(_as_dicts(raw))
