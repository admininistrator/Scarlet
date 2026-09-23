"""`GET /api/v1/models` — danh sách model đã lọc cho FE (§9.3, ADR-12).

Không trả `base_url` (lộ hạ tầng nội bộ) hay `pricing` (giá vốn) — hai trường
đó chỉ dùng nội bộ (`ByokAdapter`, metering). CLAUDE.md A3.

T-3.6 thêm hai trường §18.3 đã hứa từ đầu mà T-0.7 (*"`GET /models` tối
thiểu"*) chưa làm: `available` và `unavailable_reason`. Cả hai đến từ
`app/core/provider_health.py` — xem docstring module ấy cho lý do chúng có bộ
nhớ và vì sao phép đo không nằm ở đây (§5.3: tầng `api` không gọi ra ngoài).

Model **không** biến mất khỏi danh sách khi provider của nó tắt: UC-05 dòng 2
đòi hàng ấy *hiện xám, tooltip nói vì sao, không cho chọn*. Lọc nó đi thì
người dùng thấy một danh sách ngắn hơn hôm qua mà không ai nói vì sao — và
`conversations.default_model` của họ trỏ vào một model không còn trong danh
sách nào.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import catalog
from app.core.provider_health import ProviderStatus, provider_statuses

router = APIRouter(tags=["models"])

#: Provider có trong `models[]` mà không có trong `providers{}` là bất khả:
#: `Catalog` validate quan hệ ấy lúc nạp (T-0.7). Giá trị này chỉ để `.get()`
#: có một đường lui không ném — hỏng về phía "chọn được", vì chặn thật nằm ở
#: lượt gọi model chứ không ở picker.
_AVAILABLE = ProviderStatus(available=True, reason=None)


class PublicModel(BaseModel):
    id: str
    display_name: str
    #: NHÃN để hiện (`DeepSeek AI`) — **không** dùng để so với thứ gì.
    provider: str
    #: Khoá provider trong catalog (`deepseek`) — đúng chuỗi mà
    #: `/settings/keys/{provider}` nhận và `ProviderKeyOut.provider` trả về.
    #:
    #: B-257: T-3.11 so khoá BYOK của người dùng với `provider` ở trên — một
    #: NHÃN — nên phép so không bao giờ khớp và người tự trả tiền bằng khoá
    #: riêng vẫn bị khoá nút gửi khi hết quota hệ thống. Nhãn để đọc, khoá để
    #: so; hai vai trò thì hai trường.
    provider_id: str
    capabilities: list[str]
    context_window: int
    max_output: int
    default: bool
    badge: str | None
    #: §18.3. `False` = provider của model này không trả lời lúc đo gần nhất.
    available: bool
    #: Câu tiếng Việt hiện nguyên văn trong tooltip. `None` khi `available`.
    unavailable_reason: str | None


@router.get("/models", response_model=list[PublicModel])
async def list_models() -> list[PublicModel]:
    cat = catalog.get_catalog()
    statuses = await provider_statuses()
    enabled = sorted((m for m in cat.models if m.enabled), key=lambda m: m.order)
    return [
        PublicModel(
            id=m.id,
            display_name=m.display_name,
            provider=cat.providers[m.provider].label,
            provider_id=m.provider,
            capabilities=m.capabilities,
            context_window=m.context_window,
            max_output=m.max_output,
            default=m.default,
            badge=m.badge,
            available=statuses.get(m.provider, _AVAILABLE).available,
            unavailable_reason=statuses.get(m.provider, _AVAILABLE).reason,
        )
        for m in enabled
    ]
