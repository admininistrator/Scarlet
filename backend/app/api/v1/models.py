"""`GET /api/v1/models` — danh sách model đã lọc cho FE (§9.3, ADR-12).

Không trả `base_url` (lộ hạ tầng nội bộ) — trường đó chỉ dùng nội bộ
(`ByokAdapter`, health). CLAUDE.md A3.

T-3.6 thêm hai trường §18.3 đã hứa từ đầu mà T-0.7 (*"`GET /models` tối
thiểu"*) chưa làm: `available` và `unavailable_reason`. Cả hai đến từ
`app/core/provider_health.py` — xem docstring module ấy cho lý do chúng có bộ
nhớ và vì sao phép đo không nằm ở đây (§5.3: tầng `api` không gọi ra ngoài).

Model **không** biến mất khỏi danh sách khi provider của nó tắt: UC-05 dòng 2
đòi hàng ấy *hiện xám, tooltip nói vì sao, không cho chọn*. Lọc nó đi thì
người dùng thấy một danh sách ngắn hơn hôm qua mà không ai nói vì sao — và
`conversations.default_model` của họ trỏ vào một model không còn trong danh
sách nào.

T-S.3 (catalog v4, §24.2b·S3, S14):

* `provider` là **hãng** (`Catalog.display_provider`), không còn là tên đường
  đi. Tên đường trung gian (`user_visible: false` — 9Router, Sub2API) không
  có lối nào ra response này (NQ-119): `provider_id` của model thuộc đường ấy
  là `null` (NQ-123 — khoá ấy không có khoá BYOK nào để so, vì provider trung
  gian không `byok_supported`), và `unavailable_reason` là một câu chung.
* `reasoning` chỉ mang `id` + `default`. `params` là tham số gửi provider, có
  thể mang cả ngân sách token — không bao giờ rời backend (Cạm bẫy ① T-S.3).
* `pricing` là giá **niêm yết** USD / 1M token vào và ra, dạng **chuỗi** giữ
  đúng chữ số của catalog (Cạm bẫy ③). Model bán theo khung giờ trả cả khung
  đang áp dụng lẫn khung còn lại; backend chọn khung theo múi giờ của catalog,
  FE không so giờ (NQ-120). Chỉ giá niêm yết đi ra — không có "giá vốn" nào
  khác trong catalog để giấu.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import catalog
from app.config.catalog import Catalog, ModelEntry, PriceWindow, PricingMode, WindowedRates
from app.core.provider_health import ProviderStatus, provider_statuses

router = APIRouter(tags=["models"])

#: Provider có trong `models[]` mà không có trong `providers{}` là bất khả:
#: `Catalog` validate quan hệ ấy lúc nạp (T-0.7). Giá trị này chỉ để `.get()`
#: có một đường lui không ném — hỏng về phía "chọn được", vì chặn thật nằm ở
#: lượt gọi model chứ không ở picker.
_AVAILABLE = ProviderStatus(available=True, reason=None)


def _now() -> datetime:
    """Thời điểm chọn khung giá — một hàm riêng để test thay bằng đồng hồ giả."""
    return datetime.now(UTC)


class PublicReasoningOption(BaseModel):
    id: str


class PublicReasoning(BaseModel):
    default: str
    options: list[PublicReasoningOption]


class PublicRates(BaseModel):
    #: `peak` / `off_peak` cho model bán theo khung giờ; `None` khi một giá.
    window: PriceWindow | None
    #: USD / 1M token, chuỗi thập phân đúng chữ số trong `model_catalog.json`.
    input_per_1m: str
    output_per_1m: str


class PublicPricing(BaseModel):
    #: Khung đang áp dụng lúc backend trả lời.
    current: PublicRates
    #: Khung còn lại nếu model có `pricing_schedules`, không thì `None`.
    other: PublicRates | None
    #: `True` = giá do người vận hành tự điền (`manual_pricing`, B-65), không
    #: phải giá niêm yết của provider.
    estimated: bool


class PublicModel(BaseModel):
    id: str
    display_name: str
    #: Tên HÃNG để hiện (`DeepSeek`, `Google AI`) — **không** dùng để so với
    #: thứ gì, và không bao giờ là tên đường trung gian (NQ-119).
    provider: str
    #: Khoá provider trong catalog (`deepseek`) — đúng chuỗi mà
    #: `/settings/keys/{provider}` nhận và `ProviderKeyOut.provider` trả về.
    #:
    #: B-257: T-3.11 so khoá BYOK của người dùng với `provider` ở trên — một
    #: NHÃN — nên phép so không bao giờ khớp và người tự trả tiền bằng khoá
    #: riêng vẫn bị khoá nút gửi khi hết quota hệ thống. Nhãn để đọc, khoá để
    #: so; hai vai trò thì hai trường.
    #:
    #: `None` cho model của provider `user_visible: false` (NQ-123): khoá ấy
    #: là tên đường đi, và không khoá BYOK nào so được với nó.
    provider_id: str | None
    capabilities: list[str]
    context_window: int
    max_output: int
    default: bool
    badge: str | None
    #: §18.3. `False` = provider của model này không trả lời lúc đo gần nhất.
    available: bool
    #: Câu tiếng Việt hiện nguyên văn trong tooltip. `None` khi `available`.
    unavailable_reason: str | None
    #: `None` = model không có tuỳ chọn suy luận (picker hiện hàng mờ).
    reasoning: PublicReasoning | None
    #: `None` = model chưa có giá ở cả hai nguồn (0 USD với quota, B-65).
    pricing: PublicPricing | None
    pricing_mode: PricingMode


def _public_rates(entry: WindowedRates) -> PublicRates:
    input_per_1m = entry.rates.usd("input_per_1m")
    output_per_1m = entry.rates.usd("output_per_1m")
    # `PricingRates` bắt buộc cả hai trường (`gt=0`) nên nhánh này bất khả;
    # nó ở đây để mypy biết, không để lặng lẽ trả một chuỗi rỗng.
    assert input_per_1m is not None and output_per_1m is not None
    return PublicRates(window=entry.window, input_per_1m=input_per_1m, output_per_1m=output_per_1m)


def _public_pricing(cat: Catalog, m: ModelEntry, at: datetime) -> PublicPricing | None:
    windows = cat.price_windows(m.id, at)
    if not windows:
        return None
    return PublicPricing(
        current=_public_rates(windows[0]),
        other=_public_rates(windows[1]) if len(windows) > 1 else None,
        estimated=cat.pricing_source(m.id) == "manual",
    )


def _public_reasoning(m: ModelEntry) -> PublicReasoning | None:
    if m.reasoning is None:
        return None
    return PublicReasoning(
        default=m.reasoning.default,
        options=[PublicReasoningOption(id=o.id) for o in m.reasoning.options],
    )


@router.get("/models", response_model=list[PublicModel])
async def list_models() -> list[PublicModel]:
    cat = catalog.get_catalog()
    statuses = await provider_statuses()
    at = _now()
    enabled = sorted((m for m in cat.models if m.enabled), key=lambda m: m.order)
    return [
        PublicModel(
            id=m.id,
            display_name=m.display_name,
            provider=cat.display_provider(m),
            provider_id=m.provider if cat.providers[m.provider].user_visible else None,
            capabilities=m.capabilities,
            context_window=m.context_window,
            max_output=m.max_output,
            default=m.default,
            badge=m.badge,
            available=statuses.get(m.provider, _AVAILABLE).available,
            unavailable_reason=statuses.get(m.provider, _AVAILABLE).reason,
            reasoning=_public_reasoning(m),
            pricing=_public_pricing(cat, m, at),
            pricing_mode=m.pricing_mode,
        )
        for m in enabled
    ]
