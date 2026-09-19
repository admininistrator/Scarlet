"""`SystemAdapter` — cài đặt `LLMClient` gọi model qua LiteLLM (§9.1, ADR-03).

KH tham chiếu: §9.1, ADR-03, ADR-04, C40 · CLAUDE.md A3, A4, A9.

Đây là adapter mặc định: mọi lượt chat không dùng BYOK đều đi qua đây, và chi
phí tính vào quota hệ thống. `base_url` **luôn** là LiteLLM
(`settings.LITELLM_BASE_URL`) — backend không biết provider nào đứng sau, đó là
A9 và là lý do tồn tại của ADR-03.

**Thân `stream()` nay sống ở `openai_compat.py`** (T-2.15): `ByokAdapter` cần
đúng thân ấy, và cạm bẫy của T-2.15 cấm chép nó ra một bản thứ hai. Phần riêng
của adapter này chỉ còn `from_settings()` — tức đúng phần mà bảng §9.1 nói là
khác nhau giữa hai hàng (`base_url`, credential).
"""

from __future__ import annotations

from app.config.settings import Settings, settings
from app.llm.adapters.openai_compat import OpenAICompatAdapter


class SystemAdapter(OpenAICompatAdapter):
    """`LLMClient` (§9.1) trỏ vào LiteLLM. Xem `OpenAICompatAdapter` cho thân.

    Giữ một instance cho cả vòng đời tiến trình (worker tạo lúc khởi động, cất
    trong `ctx` — T-1.5): `AsyncOpenAI` mang theo một connection pool gắn với
    event loop, tạo mới mỗi lượt chat là vứt pool đi mỗi lượt.
    """

    __slots__ = ()

    @classmethod
    def from_settings(cls, config: Settings | None = None) -> SystemAdapter:
        """Dựng adapter từ `Settings` — chỗ DUY NHẤT nối cấu hình vào tầng LLM (A4)."""
        config = config or settings
        return cls(
            base_url=config.LITELLM_BASE_URL,
            api_key=config.LITELLM_MASTER_KEY.get_secret_value(),
            timeout_s=float(config.LLM_REQUEST_TIMEOUT_S),
        )
