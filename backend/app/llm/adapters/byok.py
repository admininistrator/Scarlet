"""`ByokAdapter` — gọi thẳng provider bằng khoá của người dùng (§9.1, §10.5) — T-2.15.

KH tham chiếu: §9.1 (bảng hai adapter), §10.5, §9.2, B-166 · CLAUDE.md A3, A5,
A9 · tasks.md T-2.15.

Hàng thứ hai của bảng §9.1: `base_url` lấy từ `provider.base_url` trong
catalog, credential là khoá của user đã giải mã, dùng khi user đã cấu hình
BYOK cho provider đó. Thân `stream()` là thân **chung** ở
`openai_compat.py` — xem cạm bẫy của T-2.15 ghi trong docstring file đó.

┌──────────────────────────────────────────────────────────────────────────┐
│  VÒNG ĐỜI: MỘT LƯỢT SINH, KHÔNG PHẢI MỘT TIẾN TRÌNH                     │
└──────────────────────────────────────────────────────────────────────────┘

`SystemAdapter` sống bằng vòng đời worker vì cả hệ thống dùng chung **một**
credential. Ở đây thì không: credential thuộc về một người dùng cụ thể, nên
một instance dùng lại giữa hai lượt sinh là một instance mang khoá của người
này đi gọi cho người kia. Vì vậy `workers/generate.py` dựng mới mỗi lượt và
`await close()` trong `finally` — cái giá là một lần bắt tay TLS cho mỗi lượt
chat BYOK, và với 15–20 người dùng (R1) thì đó là cái giá rẻ hơn nhiều so với
một bảng cache credential trong RAM của worker (§5.2 cấm worker giữ state
giữa các job, và đây đúng là loại state không được phép giữ).

┌──────────────────────────────────────────────────────────────────────────┐
│  A5 KHÔNG ÁP — URL Ở ĐÂY KHÔNG DO NGƯỜI DÙNG GỬI                        │
└──────────────────────────────────────────────────────────────────────────┘

Cùng lý lẽ đã ghi ở `llm/byok_verify.py`: `base_url` do **người vận hành**
viết trong `config/model_catalog.json`. Thứ người dùng gửi là `model_id`, một
khoá tra cứu vào catalog; một giá trị bịa ra bị `get_model()` trả `None` và
dừng ở tầng API (`400 MODEL_UNKNOWN`) trước khi tới đây.

`auth_style` **không** được đọc ở file này, khác `byok_verify.py`. Cửa xác
thực của một endpoint OpenAI-compatible là `Authorization: Bearer` — đó là
hợp đồng của chính protocol mà A9 chốt, và SDK `openai` đặt header đó từ
`api_key`. Provider nào đòi khác thì đòi ở đường **kiểm** (một endpoint riêng
của họ), không phải ở `/chat/completions`.
"""

from __future__ import annotations

from app.config.catalog import Provider
from app.config.settings import Settings, settings
from app.llm.adapters.openai_compat import OpenAICompatAdapter


class ByokAdapter(OpenAICompatAdapter):
    """`LLMClient` (§9.1) trỏ thẳng vào provider, dùng khoá của một người dùng."""

    __slots__ = ()

    @classmethod
    def for_provider(
        cls, provider: Provider, *, api_key: str, config: Settings | None = None
    ) -> ByokAdapter:
        """Dựng adapter cho một bản ghi provider của catalog và một khoá đã giải mã.

        Args:
            provider: bản ghi trong `model_catalog.json::providers`. Ba trường
                được đọc: `base_url` (§9.1), và `extra_headers` (B-166).
            api_key: khoá BYOK **bản rõ**. Nó chỉ đi vào `AsyncOpenAI` rồi ra
                header `Authorization`; không vào log, không vào exception của
                lớp này (C20).
            config: để test bơm `Settings` riêng, cùng lối `from_settings`.

        `LLM_REQUEST_TIMEOUT_S` chứ không `BYOK_VERIFY_TIMEOUT_S`: đây là một
        lượt **sinh chữ** có quyền chảy mười phút, không phải một nút "Lưu
        khoá" đang quay (xem `Settings.BYOK_VERIFY_TIMEOUT_S`).
        """
        config = config or settings
        return cls(
            base_url=provider.base_url,
            api_key=api_key,
            timeout_s=float(config.LLM_REQUEST_TIMEOUT_S),
            default_headers=dict(provider.extra_headers) or None,
        )
