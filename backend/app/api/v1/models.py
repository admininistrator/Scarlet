"""`GET /api/v1/models` — danh sách model đã lọc cho FE (§9.3, ADR-12).

Không trả `base_url` (lộ hạ tầng nội bộ) hay `pricing` (giá vốn) — hai trường
đó chỉ dùng nội bộ (`ByokAdapter`, metering). CLAUDE.md A3.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import catalog

router = APIRouter(tags=["models"])


class PublicModel(BaseModel):
    id: str
    display_name: str
    provider: str
    capabilities: list[str]
    context_window: int
    max_output: int
    default: bool
    badge: str | None


@router.get("/models", response_model=list[PublicModel])
async def list_models() -> list[PublicModel]:
    cat = catalog.get_catalog()
    enabled = sorted((m for m in cat.models if m.enabled), key=lambda m: m.order)
    return [
        PublicModel(
            id=m.id,
            display_name=m.display_name,
            provider=cat.providers[m.provider].label,
            capabilities=m.capabilities,
            context_window=m.context_window,
            max_output=m.max_output,
            default=m.default,
            badge=m.badge,
        )
        for m in enabled
    ]
