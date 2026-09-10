"""Endpoint admin tối thiểu cho T-0.7 — chỉ `catalog/reload`.

Chưa có dependency `require_admin`: hệ thống auth chưa tồn tại (Phase 2,
xem `docs/tasks.md` T-2.x nơi `/admin/*` được gắn `require_admin`). Để endpoint
này mở trong lúc chưa có auth là lệch có chủ đích của riêng task này — đã ghi
vào báo cáo/Backlog, không phải bỏ sót.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.config import catalog

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/catalog/reload")
async def reload_catalog() -> dict[str, int]:
    cat = catalog.reload()
    return {"models": len(cat.models)}
