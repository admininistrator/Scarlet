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
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from minio import Minio
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config.catalog import get_catalog
from app.config.settings import settings
from app.core.provider_health import probe_provider

#: Timeout riêng cho mỗi mục kiểm (Việc cần làm, T-0.11).
CHECK_TIMEOUT_S = 2.0

#: Khoá của 9Router trong `model_catalog.json` — cũng là tên mục kiểm.
NINEROUTER = "ninerouter"

#: 9Router là phụ thuộc duy nhất mà hỏng chỉ hạ tổng thể xuống `degraded`.
NON_CRITICAL_CHECKS = frozenset({NINEROUTER})


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
    # Phép đo nằm ở `core/provider_health.py` kể từ T-3.6, không chép lại ở
    # đây: `GET /models` hỏi ĐÚNG câu hỏi này để làm xám model (§9.3, UC-05),
    # và hai bản sao của một lệnh gọi là hai chỗ để `base_url` được ghép khác
    # nhau (C43). Khác biệt duy nhất giữa hai người gọi là bộ nhớ: mục kiểm
    # của `/health/deep` luôn đo TƯƠI (người vận hành đang nhìn màn hình để
    # chẩn đoán), còn picker đọc lượt đo nền gần nhất (T-S.4).
    await probe_provider(get_catalog().providers[NINEROUTER])


#: Trần độ dài của `CheckResult.error` — một traceback của asyncpg dài vài KB.
ERROR_MAX_CHARS = 200


def describe_error(exc: BaseException) -> str:
    """Lý do hỏng đọc được — **không bao giờ là chuỗi rỗng** (B-193).

    `asyncio.wait_for` hết giờ ném `TimeoutError` với `str()` rỗng, và vài
    exception của `redis-py` cũng vậy: `str(exc)` trần cho ra `"error": ""`
    đúng lúc Redis chết — màn "Hệ thống" nói "hỏng" mà không nói hỏng vì gì,
    tức đúng thứ người ta mở nó ra để đọc. Tên kiểu exception luôn có mặt,
    thông điệp đi kèm khi có.
    """
    message = str(exc).strip()
    name = type(exc).__name__
    return (f"{name}: {message}" if message else name)[:ERROR_MAX_CHARS]


async def _timed(name: str, check: Coroutine[Any, Any, None]) -> tuple[str, CheckResult]:
    start = time.monotonic()
    try:
        await asyncio.wait_for(check, timeout=CHECK_TIMEOUT_S)
        ok, error = True, None
    except Exception as exc:  # noqa: BLE001 — mỗi mục kiểm phải tự chứa lỗi của nó
        ok, error = False, describe_error(exc)
    latency_ms = int((time.monotonic() - start) * 1000)
    return name, CheckResult(ok=ok, latency_ms=latency_ms, error=error)


async def run_checks() -> dict[str, CheckResult]:
    """Chạy song song cả năm mục kiểm, mỗi mục timeout riêng `CHECK_TIMEOUT_S`."""
    pairs = await asyncio.gather(
        _timed("postgres", _check_postgres()),
        _timed("redis", _check_redis()),
        _timed("minio", _check_minio()),
        _timed("litellm", _check_litellm()),
        _timed(NINEROUTER, _check_ninerouter()),
    )
    return dict(pairs)


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    """Một lượt `run_checks()` cùng **thời điểm nó chạy**."""

    checked_at: datetime
    checks: dict[str, CheckResult]


class CachedChecks:
    """Nhớ một lượt `run_checks()` trong `ttl_s` giây — màn "Hệ thống" (B-192).

    B-192 đo `GET /admin/system` ba lần liên tiếp: 9Router 854 / 806 / 941 ms,
    mỗi lần năm lượt đi mạng. Một màn hình chẩn đoán mà mỗi F5 là một loạt
    request tới nhà cung cấp là một màn hình tự làm nặng thêm sự cố nó báo.

    Nhớ **ở server** chứ không để FE tự giãn nhịp: FE chỉ giãn được trong một
    tab — hai tab, hai admin, hay một chuỗi F5 vẫn đi thẳng ra mạng. Cái giá
    là con số có thể cũ tới `ttl_s` giây, và `checked_at` đi cùng response để
    màn hình **nói ra** điều đó ("Kiểm lúc …") thay vì giấu nó.

    Một khoá `asyncio.Lock` gộp các lượt hỏi trùng lúc bộ nhớ vừa hết hạn làm
    một lượt đo — cùng lối `core/provider_health.py`. Bộ nhớ sống trong tiến
    trình, không trong Redis: nó phải còn dùng được đúng lúc Redis là thứ đang
    hỏng.

    `run` truyền vào lúc gọi chứ không gắn cứng `run_checks`: test thay được
    hàm đo mà không phải thay cả bộ nhớ.

    `GET /health/deep` **không** đi qua đây — máy hỏi (Docker, người vận hành
    gõ `curl`) thì luôn đo tươi.
    """

    def __init__(self) -> None:
        self._snapshot: HealthSnapshot | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def get(
        self,
        run: Callable[[], Awaitable[dict[str, CheckResult]]],
        *,
        ttl_s: float,
    ) -> HealthSnapshot:
        if self._snapshot is not None and time.monotonic() < self._expires_at:
            return self._snapshot
        async with self._lock:
            # Người khác vừa đo xong trong lúc mình chờ khoá.
            if self._snapshot is not None and time.monotonic() < self._expires_at:
                return self._snapshot
            checks = await run()
            self._snapshot = HealthSnapshot(checked_at=datetime.now(UTC), checks=checks)
            self._expires_at = time.monotonic() + ttl_s
            return self._snapshot

    def clear(self) -> None:
        """Vứt bộ nhớ — cho test, và cho một lượt đo lại tường minh."""
        self._snapshot = None
        self._expires_at = 0.0
