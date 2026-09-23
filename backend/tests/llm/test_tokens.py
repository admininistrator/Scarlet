"""T-1.4 — `app/llm/tokens.py`: đếm token cho ngân sách §9.6 và đường lùi C40.

KH tham chiếu: §9.6, C40 · NQ-20.

Bộ này KHÔNG kiểm "con số đúng bao nhiêu" — `tiktoken` là bộ tách từ của
OpenAI và mọi model trong catalog hôm nay đều không phải của OpenAI, nên con số
vốn dĩ là xấp xỉ (xem docstring của module). Cái được kiểm là ba tính chất mà
`context.py` và T-2.12 dựa vào và sẽ hỏng âm thầm nếu mất:

1. đơn điệu — chữ nhiều hơn thì token không bao giờ ít đi;
2. `tool_calls` được tính, không bị bỏ quên (đó là chỗ khiến hội thoại có tool
   vỡ context window trong khi hội thoại thường thì không);
3. model lạ không làm hàm nổ, mà rơi về bộ tách từ mặc định.
"""

from __future__ import annotations

from app.llm.tokens import (
    DEFAULT_ENCODING,
    TOKENS_PER_MESSAGE,
    TOKENS_REPLY_PRIMING,
    count_message,
    count_messages,
    count_text,
    encoding_name_for,
    warm_cache,
)

#: Không phải model OpenAI — tức là đúng trường hợp của cả bốn model đang bật.
MODEL_ID = "model-thu-nghiem"


def test_unknown_model_falls_back_to_default_tokenizer() -> None:
    assert encoding_name_for(MODEL_ID) == DEFAULT_ENCODING


def test_openai_model_uses_its_own_tokenizer() -> None:
    """Nhánh này chưa chạy trong production, nhưng nó là lý do có `try/except`.

    Ngày một model OpenAI vào catalog, con số phải chính xác mà không ai sửa gì.
    """
    assert encoding_name_for("gpt-4o") == "o200k_base"
    assert encoding_name_for("gpt-4") == "cl100k_base"


def test_empty_string_costs_no_tokens() -> None:
    assert count_text("", model_id=MODEL_ID) == 0


def test_count_is_monotonic_in_length() -> None:
    short = count_text("Xin chào", model_id=MODEL_ID)
    long_text = count_text("Xin chào thế giới, đây là một câu dài hơn hẳn", model_id=MODEL_ID)
    assert 0 < short < long_text


def test_message_costs_extra_for_framing() -> None:
    """Một message luôn đắt hơn phần chữ của nó — đó là `TOKENS_PER_MESSAGE`."""
    content = "Hôm nay trời đẹp"
    text_only = count_text(content, model_id=MODEL_ID)
    ca_message = count_message(
        {"role": "user", "content": content},
        model_id=MODEL_ID,
    )
    assert ca_message >= text_only + TOKENS_PER_MESSAGE


def test_tool_calls_are_counted() -> None:
    """Bỏ quên `tool_calls` là cách tự tạo ra `400` ở đúng hội thoại dài nhất."""
    without_tool = {"role": "assistant", "content": ""}
    with_tool = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "web_search", "arguments": '{"query":"thời tiết Hà Nội"}'},
            }
        ],
    }
    assert count_message(with_tool, model_id=MODEL_ID) > count_message(
        without_tool, model_id=MODEL_ID
    )


def test_list_content_still_counts_text_parts() -> None:
    """Hình dạng của Phase 4 (vision). Token của ẢNH là việc của §15.3, không phải ở đây."""
    as_string = count_message({"role": "user", "content": "mô tả ảnh này"}, model_id=MODEL_ID)
    as_list = count_message(
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "mô tả ảnh này"},
                {"type": "image_url", "image_url": {"url": "https://example.test/a.png"}},
            ],
        },
        model_id=MODEL_ID,
    )
    assert as_list == as_string


def test_whole_list_adds_reply_priming_exactly_once() -> None:
    messages = [
        {"role": "system", "content": "bạn là trợ lý"},
        {"role": "user", "content": "chào"},
    ]
    separate_total = sum(count_message(m, model_id=MODEL_ID) for m in messages)
    assert count_messages(messages, model_id=MODEL_ID) == separate_total + TOKENS_REPLY_PRIMING


def test_warm_cache_returns_tokenizer_name() -> None:
    """Hàm mà `backend/Dockerfile` gọi lúc build image."""
    assert warm_cache() == DEFAULT_ENCODING
