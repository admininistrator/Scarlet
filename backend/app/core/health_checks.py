"""Kiểm song song năm phụ thuộc hạ tầng cho `GET /api/v1/health/deep`.

KH tham chiếu: §18.6, §21.2 · tasks.md T-0.11.

Đặt ở `app/core/`, KHÔNG phải `app/api/`: §5.3 cấm tầng `api` "gọi LLM/fetch
URL bên ngoài" (kiểm bằng đúng grep này trong `scripts/check_hardcode.sh`).
Rule đó nhắm vào việc sinh câu trả lời chạy trong request handler (A1) — health
check chỉ ping hạ tầng, không sinh nội dung — nhưng để giữ ranh giới tầng rõ
ràng và không phá vỡ phép kiểm §5.3, toàn bộ lệnh gọi mạng nằm ở module này;
router trong `app/api/v1/health.py` chỉ gọi `run_checks()`.

Cạm bẫy đã tránh: kiểm tuần tự sẽ khiến endpoint treo tới ~10 s khi một
service chết (5 mục × timeout). Ở đây mỗi mục có timeout riêng
(`CHECK_TIMEOUT_S`) và cả năm chạy đồng thời qua `asyncio.gather`, nên tổng
thời gian phản hồi bị chặn trên bởi `CHECK_TIMEOUT_S`, không phải tổng cộng.

9Router là NGOẠI LỆ DUY NHẤT: nó chỉ là một trong ba provider sau LiteLLM
(§9.5) — hỏng thì tổng thể `degraded` (vẫn dùng được DeepSeek/Anthropic).
Bốn phụ thuộc còn lại (Postgres, Redis, MinIO, LiteLLM) là hạ tầng lõi —
hỏng bất kỳ cái nào thì tổng thể `down`.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Coroutine
from typing import Any
from urllib.parse import urlsplit

import httpx
from minio import Minio
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config.settings import settings

#: Timeout riêng cho mỗi mục kiểm (Việc cần làm, T-0.11).
CHECK_TIMEOUT_S = 2.0

#: 9Router là phụ thuộc duy nhất mà hỏng chỉ hạ tổng thể xuống `degraded`.
NON_CRITICAL_CHECKS = frozenset({"ninerouter"})


class CheckResult(BaseModel):
    ok: bool
    latency_ms: int
    error: str | None = None


async def _check_postgres() -> None:
    engine = create_async_engine(str(settings.DATABASE_URL))
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    finally:
        await engine.dispose()


async def _check_redis() -> None:
    client: Redis = Redis.from_url(str(settings.REDIS_URL))
    try:
        await client.ping()
    finally:
        await client.aclose()


def _minio_list_buckets() -> None:
    parsed = urlsplit(settings.MINIO_ENDPOINT)
    client = Minio(
        parsed.netloc,
        access_key=settings.MINIO_ACCESS_KEY.get_secret_value(),
        secret_key=settings.MINIO_SECRET_KEY.get_secret_value(),
        secure=parsed.scheme == "https",
    )
    client.list_buckets()


async def _check_minio() -> None:
    # SDK `minio` chỉ có API đồng bộ — chạy trong thread riêng để không chặn
    # event loop trong lúc năm mục kiểm chạy song song.
    await asyncio.to_thread(_minio_list_buckets)


async def _check_litellm() -> None:
    # LITELLM_BASE_URL bao gồm hậu tố `/v1` (dùng cho OpenAI-compat, §9),
    # nhưng `/health/liveliness` nằm ở gốc host — không dưới `/v1` (đúng như
    # healthcheck của chính service `litellm` trong docker-compose.yml).
    root = urlsplit(settings.LITELLM_BASE_URL)
    liveliness_url = f"{root.scheme}://{root.netloc}/health/liveliness"
    async with httpx.AsyncClient() as client:
        resp = await client.get(liveliness_url)
        resp.raise_for_status()


async def _check_ninerouter() -> None:
    headers = {}
    key = settings.NINEROUTER_API_KEY.get_secret_value()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{settings.NINEROUTER_BASE_URL}/models", headers=headers)
        resp.raise_for_status()


async def _timed(name: str, check: Coroutine[Any, Any, None]) -> tuple[str, CheckResult]:
    start = time.monotonic()
    try:
        await asyncio.wait_for(check, timeout=CHECK_TIMEOUT_S)
        ok, error = True, None
    except Exception as exc:  # noqa: BLE001 — mỗi mục kiểm phải tự chứa lỗi của nó
        ok, error = False, str(exc)[:200]
    latency_ms = int((time.monotonic() - start) * 1000)
    return name, CheckResult(ok=ok, latency_ms=latency_ms, error=error)


async def run_checks() -> dict[str, CheckResult]:
    """Chạy song song cả năm mục kiểm, mỗi mục timeout riêng `CHECK_TIMEOUT_S`."""
    pairs = await asyncio.gather(
        _timed("postgres", _check_postgres()),
        _timed("redis", _check_redis()),
        _timed("minio", _check_minio()),
        _timed("litellm", _check_litellm()),
        _timed("ninerouter", _check_ninerouter()),
    )
    return dict(pairs)
