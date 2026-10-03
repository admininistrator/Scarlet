"""Đếm token cho ngân sách ngữ cảnh (§9.6) và cho đường lùi C40.

KH tham chiếu: §9.6, C15, C40 · CLAUDE.md A3, §19.2 L4 · NQ-20.

Module này chỉ làm **một** việc: đổi một danh sách message đúng hình dạng dây
OpenAI thành một con số. Nó không biết ngân sách là bao nhiêu (`context.py`
biết), không biết tiền (§10.2 biết), và không đọc `Settings` lúc import — nhờ
vậy nó import được ở bất cứ đâu, kể cả trong bước build của Docker image. Ngoại
lệ duy nhất là token ảnh (T-4.4b), đọc muộn ngay khi gặp phần `image_url`.

**Hai chỗ dùng, đã chốt ở NQ-20:**

1. `app/llm/context.py` — cắt đường đi cho vừa `context_window` (§9.6). Đây là
   chỗ dùng hôm nay.
2. T-2.12 — khi provider **không** báo `usage` (`done.usage is None`), meter tự
   ước tính rồi ghi `cost_confidence='low'` (C40). Chưa provider nào đang bật
   cần tới; xem B-67.

**Vì sao con số chỉ là xấp xỉ, và vì sao thế là đủ.** `tiktoken` là bộ tách từ
của OpenAI. Không model nào trong catalog hôm nay là model OpenAI, nên với
`deepseek-flash`/`claude-haiku`/`nr-gemini-flash`/`ol-qwen-small` con số này
lệch vài phần trăm so với bộ tách từ thật của họ — tasks.md T-1.4 ghi rõ *"xấp
xỉ với model non-OpenAI là chấp nhận được"*. Điều đó chấp nhận được vì con số
này dùng để **cắt bớt**, không để tính tiền: `RESERVE_TOKENS` (§9.6) chính là
chỗ nuốt sai số đó. Tiền thì lấy từ `usage` thật của provider (A7).

**Vì sao không đếm bằng `len(text) // 4`.** Tiếng Việt có dấu tốn nhiều token
hơn tiếng Anh trên cùng số ký tự, và tỉ lệ đó đổi theo từng câu — đo trên
`o200k_base`: 33 ký tự tiếng Việt có dấu ra 9 token, cùng câu bỏ dấu ra 10.
Một hằng số chia sẽ sai theo hướng không đoán được, mà sai theo hướng *thiếu*
thì hậu quả là `400 context_length_exceeded` ngay giữa lượt chat.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping
from functools import cache
from typing import Any

import tiktoken
from tiktoken.model import encoding_name_for_model

logger = logging.getLogger(__name__)

#: Bộ tách từ dùng khi `tiktoken` không biết model — tức là **mọi** model trong
#: catalog hôm nay. Chọn `o200k_base` (đời mới nhất) chứ không `cl100k_base`:
#: nó gộp từ tốt hơn cho chữ ngoài tiếng Anh, nên xấp xỉ gần hơn với bộ tách từ
#: của DeepSeek/Anthropic/Gemini.
#:
#: Đây **không** phải chỗ cứng loại A3 cấm: A3 cấm tên model, giá, giới hạn và
#: URL provider. `o200k_base` là tên một thuật toán tách từ trong thư viện, cùng
#: loại với `_REASONING_KEYS` của `parser.py` — nó không đổi theo cấu hình sản
#: phẩm, và đưa nó ra `config/` sẽ tạo ra một nút vặn mà không ai có lý do vặn.
DEFAULT_ENCODING = "o200k_base"

#: Khung bao quanh MỘT message trong dây OpenAI (`<|start|>role<|message|>…
#: <|end|>`). Ba con số dưới đây là của protocol, không phải hạn mức sản phẩm,
#: nhưng vẫn có tên vì §19.2 L4 cấm số ma.
TOKENS_PER_MESSAGE = 3
#: Trường `name` (chưa dùng trong Phase 1) tốn thêm đúng một token.
TOKENS_PER_NAME = 1
#: Mọi request đều được mồi sẵn `<|start|>assistant<|message|>` trước khi model
#: viết chữ đầu tiên. Cộng đúng một lần cho cả danh sách, không phải mỗi message.
TOKENS_REPLY_PRIMING = 3

#: `type` của phần ảnh trong `content` nhiều phần (OpenAI Chat Completions).
IMAGE_PART_TYPE = "image_url"

#: Các khoá của một message trên dây mà giá trị là chuỗi và phải đếm.
_STRING_FIELDS = ("role", "name", "tool_call_id")


@cache
def encoding_name_for(model_id: str) -> str:
    """Tên bộ tách từ dùng cho `model_id`, hoặc `DEFAULT_ENCODING` nếu không biết.

    `model_id` là `id` trong catalog (§9.2) — `deepseek-flash`, `claude-haiku`…
    `tiktoken` chỉ biết model của OpenAI nên nhánh `KeyError` là nhánh chạy
    **luôn luôn** hôm nay. Vẫn hỏi `tiktoken` trước, vì ngày thêm một model
    OpenAI vào catalog thì con số sẽ chính xác mà không ai phải sửa gì.
    """
    try:
        return encoding_name_for_model(model_id)
    except KeyError:
        logger.debug(
            "tiktoken không biết model %r, dùng bộ tách từ %s (xấp xỉ, §9.6)",
            model_id,
            DEFAULT_ENCODING,
        )
        return DEFAULT_ENCODING


@cache
def _encoding(name: str) -> tiktoken.Encoding:
    """Nạp một bộ tách từ. Có cache vì lần đầu phải TẢI bảng BPE về.

    Tải từ `openaipublic.blob.core.windows.net` và ghi cache ra đĩa
    (`TIKTOKEN_CACHE_DIR`). Image backend nạp sẵn ở bước build (xem
    `backend/Dockerfile`) nên container đang phục vụ không bao giờ gọi ra
    ngoài — một lượt chat không được phép treo vì blob store của bên thứ ba.
    """
    return tiktoken.get_encoding(name)


def warm_cache(name: str = DEFAULT_ENCODING) -> str:
    """Nạp sẵn bảng BPE. Gọi từ `Dockerfile` lúc build image.

    Trả về tên bộ tách từ đã nạp để bước build có cái mà in ra log.
    """
    return _encoding(name).name


def count_text(text: str, *, model_id: str) -> int:
    """Số token của một chuỗi trần, không có khung message."""
    if not text:
        return 0
    return len(_encoding(encoding_name_for(model_id)).encode(text))


def count_message(message: Mapping[str, Any], *, model_id: str) -> int:
    """Số token của MỘT message trên dây, đã cộng khung bao quanh nó.

    Đếm cả các trường không phải văn bản người dùng — `role`, `tool_call_id`,
    và `tool_calls` — vì provider tính tiền cho toàn bộ JSON gửi lên, không chỉ
    phần chữ. Bỏ `tool_calls` ra ngoài phép đếm là cách tự tạo ra một cú
    `400 context_length_exceeded` ở đúng hội thoại có tool, tức là hội thoại
    dài nhất.
    """
    total = TOKENS_PER_MESSAGE

    for field in _STRING_FIELDS:
        value = message.get(field)
        if isinstance(value, str):
            total += count_text(value, model_id=model_id)
            if field == "name":
                total += TOKENS_PER_NAME

    total += _count_content(message.get("content"), model_id=model_id)

    tool_calls = message.get("tool_calls")
    if tool_calls:
        # `arguments` là chuỗi JSON thô do parser ghép lại (xem `client.py`),
        # và cả khối này đi nguyên văn lên dây ở lượt sau. Đếm bản đã
        # `json.dumps` là đếm đúng thứ được gửi.
        total += count_text(
            json.dumps(tool_calls, ensure_ascii=False, separators=(",", ":")),
            model_id=model_id,
        )

    return total


def count_messages(messages: Iterable[Mapping[str, Any]], *, model_id: str) -> int:
    """Số token của cả danh sách message, đã cộng phần mồi câu trả lời.

    Đây là con số đem so với ngân sách của §9.6 — không phải tổng `count_message`
    suông, vì mỗi request còn tốn thêm `TOKENS_REPLY_PRIMING`.
    """
    return sum(count_message(m, model_id=model_id) for m in messages) + TOKENS_REPLY_PRIMING


def _count_content(content: Any, *, model_id: str) -> int:
    """Đếm `content`, chịu được cả hai hình dạng mà OpenAI cho phép.

    Chuỗi là dạng của Phase 1. Dạng danh sách các phần (`[{"type":"text",…},
    {"type":"image_url",…}]`) là message có ảnh (T-4.4b): phần chữ đếm bằng
    `tiktoken`, mỗi phần `image_url` cộng đúng `VISION_TOKENS_PER_IMAGE` (NQ-138
    ④ — §15.3 không có công thức, mỗi provider tính một kiểu). Ảnh đã thay bằng
    dòng chữ ở lượt cũ (C33) là chữ, không phải phần ảnh, nên không cộng.
    """
    if isinstance(content, str):
        return count_text(content, model_id=model_id)
    if isinstance(content, list):
        total = 0
        for part in content:
            if isinstance(part, Mapping):
                text = part.get("text")
                if isinstance(text, str):
                    total += count_text(text, model_id=model_id)
                if part.get("type") == IMAGE_PART_TYPE:
                    # Import muộn: module này phải import được ở bước build
                    # image, nơi `Settings` thiếu biến và nổ (A4).
                    from app.config.settings import settings

                    total += settings.VISION_TOKENS_PER_IMAGE
        return total
    return 0
