"""`SystemAdapter` — cài đặt `LLMClient` gọi model qua LiteLLM (§9.1, ADR-03).

KH tham chiếu: §9.1, ADR-03, ADR-04, C40 · CLAUDE.md A3, A4, A9.

Đây là adapter mặc định: mọi lượt chat không dùng BYOK đều đi qua đây, và chi
phí tính vào quota hệ thống. `base_url` **luôn** là LiteLLM
(`settings.LITELLM_BASE_URL`) — backend không biết provider nào đứng sau, đó là
A9 và là lý do tồn tại của ADR-03.

File này là một trong hai chỗ duy nhất trong `app/` được import SDK `openai`
(chỗ còn lại là `ByokAdapter` của Phase 2). `app/api/` bị `make check-hardcode`
chặn thẳng.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from typing import TYPE_CHECKING, Any, cast

from openai import AsyncOpenAI, omit
from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionStreamOptionsParam,
    ChatCompletionToolUnionParam,
)

from app.config.settings import Settings, settings
from app.llm.client import Chunk
from app.llm.parser import RawChunk, parse_stream

if TYPE_CHECKING:
    from openai import AsyncStream
    from openai.types.chat import ChatCompletionChunk

#: Retry của generation **không** phải một nút xoay. Gọi lại một lượt đã sinh
#: dở là trả tiền lần hai cho cùng một câu trả lời (cùng lý do với
#: `max_tries: 1` của arq ở T-1.5). LiteLLM đã có `num_retries: 2` cho chặng
#: LiteLLM→provider, nơi biết chắc request nào chưa tiêu token nào.
_NO_RETRY = 0

#: §7.4 và §10.2 đều cần số token thật. Không bật cờ này thì nhiều provider
#: không gửi chunk `usage` cuối, `cost_usd` bằng 0 và quota không bao giờ trừ
#: (C40). `drop_params: true` trong `litellm.config.yaml` lo phần provider
#: không hiểu tham số này.
_STREAM_OPTIONS: ChatCompletionStreamOptionsParam = {"include_usage": True}


async def _as_dicts(stream: AsyncStream[ChatCompletionChunk]) -> AsyncIterator[RawChunk]:
    """Đổi object của SDK thành dict, và đóng kết nối trên MỌI đường thoát.

    `model_dump()` giữ nguyên cả trường ngoài schema của SDK — đã kiểm:
    `reasoning_content` (B-33) và `completion_tokens_details.reasoning_tokens`
    đều còn nguyên. Xem `parser.py` cho lý do parser làm việc với dict.

    `finally: await stream.close()` là bắt buộc chứ không phải cho gọn: khi
    người dùng bấm Huỷ (§7.5) worker thoát vòng lặp giữa chừng, và không đóng
    thì kết nối HTTP tới LiteLLM nằm treo tới lúc timeout — upstream vẫn sinh
    tiếp và vẫn tính tiền.
    """
    try:
        async for chunk in stream:
            yield chunk.model_dump()
    finally:
        await stream.close()


class SystemAdapter:
    """Cài đặt `LLMClient` (§9.1) dùng SDK `openai` async trỏ vào LiteLLM.

    Giữ một instance cho cả vòng đời tiến trình (worker tạo lúc khởi động, cất
    trong `ctx` — T-1.5): `AsyncOpenAI` mang theo một connection pool gắn với
    event loop, tạo mới mỗi lượt chat là vứt pool đi mỗi lượt. Cũng vì gắn với
    event loop nên **không** có instance toàn cục ở tầng module.
    """

    __slots__ = ("_client",)

    def __init__(self, *, base_url: str, api_key: str, timeout_s: float) -> None:
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout_s,
            max_retries=_NO_RETRY,
        )

    @classmethod
    def from_settings(cls, config: Settings | None = None) -> SystemAdapter:
        """Dựng adapter từ `Settings` — chỗ DUY NHẤT nối cấu hình vào tầng LLM (A4)."""
        config = config or settings
        return cls(
            base_url=config.LITELLM_BASE_URL,
            api_key=config.LITELLM_MASTER_KEY.get_secret_value(),
            timeout_s=float(config.LLM_REQUEST_TIMEOUT_S),
        )

    async def close(self) -> None:
        """Đóng connection pool. Worker gọi lúc shutdown."""
        await self._client.close()

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
        """Xem `LLMClient.stream`. Gọi bằng `async for c in await adapter.stream(...)`.

        `await` ở đây gửi request và chờ header, nên `401/400/429` nổ tại đây
        chứ không đội lốt stream rỗng — lý do §9.1 khai `async def` thay vì
        async generator (xem docstring `client.py`).
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
            temperature=temperature,
            stream=True,
            stream_options=_STREAM_OPTIONS,
            # Tham số riêng của provider (`reasoning_effort`, `thinking`…) đi
            # thẳng vào body. Adapter không diễn giải: diễn giải là bắt đầu
            # hardcode tên provider vào code (A3, §9.8).
            extra_body=extra or None,
        )
        return parse_stream(_as_dicts(raw))
