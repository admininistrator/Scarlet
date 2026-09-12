"""`GET /api/v1/health/deep` — router mỏng, gọi vào `app/core/health_checks.py`.

KH tham chiếu: §18.6, §21.2 · tasks.md T-0.11.

Toàn bộ lệnh gọi mạng (Postgres/Redis/MinIO/LiteLLM/9Router) nằm ở
`app/core/health_checks.py`, không phải ở đây — lý do nằm trong docstring
của module đó (§5.3, `scripts/check_hardcode.sh`).
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel

from app.core.health_checks import NON_CRITICAL_CHECKS, CheckResult, run_checks

router = APIRouter(prefix="/health", tags=["health"])


class DeepHealth(BaseModel):
    status: Literal["ok", "degraded", "down"]
    checks: dict[str, CheckResult]


@router.get("/deep", response_model=DeepHealth)
async def health_deep(response: Response) -> DeepHealth:
    checks = await run_checks()

    critical_down = any(
        not result.ok for name, result in checks.items() if name not in NON_CRITICAL_CHECKS
    )
    if critical_down:
        status: Literal["ok", "degraded", "down"] = "down"
        response.status_code = 503
    elif any(not result.ok for result in checks.values()):
        status = "degraded"
    else:
        status = "ok"

    return DeepHealth(status=status, checks=checks)
