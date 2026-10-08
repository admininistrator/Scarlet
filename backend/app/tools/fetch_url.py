"""Client của `worker` tới service `fetcher` (§12, T-6.5). Chưa là tool — T-6.7a
đăng ký nó vào registry.

KH tham chiếu: §12.2, §12.3 · NQ-144 (Q-P6-2) · B-71.

URL người dùng **không** được nối từ đây: `worker` ở `internal`, nơi `redis`
resolve được. Nó chỉ chuyển URL cho `fetcher` (mạng `egress`, lớp 1) — kiểm URL,
ghim IP, theo redirect đều chạy ở đó. `fetcher` không đọc `.env`, nên mọi trần
đi trong body, đọc `Settings` **lúc gọi**.

**Hai timeout lồng nhau** (B-71): trần của client > trần của `fetcher`
(`FETCH_TIMEOUT_S` + `PLAYWRIGHT_TIMEOUT_S` — T-6.6 thêm chặng trình duyệt), để
cái trong nổ trước và trả `reason` thật thay vì một `timeout` mù ở đây.

Hỏng là dữ liệu (lối `web_search.py`): `fetcher` chết / trả rác ⇒
`FetchResult(ok=False, reason=…)`, không ném.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.config.settings import settings

logger = logging.getLogger(__name__)

_FETCH_PATH = "/fetch"
_BYTES_PER_MB = 1024 * 1024


@dataclass(frozen=True, slots=True)
class FetchResult:
    ok: bool
    final_url: str | None = None
    title: str | None = None
    text: str = ""
    fetch_method: str | None = None
    reason: str | None = None


def _client(timeout: float) -> httpx.AsyncClient:
    """Tách riêng để test bơm `httpx.MockTransport`."""
    return httpx.AsyncClient(timeout=timeout, trust_env=False)


def _parse(data: Any) -> FetchResult:
    if not isinstance(data, dict) or not isinstance(data.get("ok"), bool):
        raise ValueError("thân trả về sai hình")
    fields = ("final_url", "title", "fetch_method", "reason")
    if not all(data.get(k) is None or isinstance(data[k], str) for k in fields) or not isinstance(
        data.get("text", ""), str
    ):
        raise ValueError("thân trả về sai kiểu")
    return FetchResult(ok=data["ok"], text=data.get("text", ""), **{k: data.get(k) for k in fields})


async def fetch_url(url: str) -> FetchResult:
    body = {
        "url": url,
        "max_bytes": settings.MAX_FETCH_MB * _BYTES_PER_MB,
        "timeout_s": settings.FETCH_TIMEOUT_S,
        "max_redirects": settings.MAX_REDIRECTS,
        # T-6.6 — luật leo thang §12.3 bước 4 và trần của chặng trình duyệt.
        "js_escalate_min_chars": settings.JS_ESCALATE_MIN_CHARS,
        "playwright_timeout_s": settings.PLAYWRIGHT_TIMEOUT_S,
    }
    timeout = settings.FETCH_TIMEOUT_S + settings.PLAYWRIGHT_TIMEOUT_S
    try:
        async with _client(timeout) as client:
            response = await client.post(f"{settings.FETCHER_BASE_URL}{_FETCH_PATH}", json=body)
        response.raise_for_status()
        return _parse(response.json())
    except httpx.TimeoutException:
        logger.warning("fetch_url hong: reason=timeout tran=%ss", timeout)
        return FetchResult(ok=False, reason="timeout")
    except (httpx.HTTPError, ValueError) as exc:
        # Không ghi URL (thứ người dùng gõ) — chỉ loại lỗi.
        logger.warning("fetch_url hong: reason=fetcher_unavailable ly_do=%s", type(exc).__name__)
        return FetchResult(ok=False, reason="fetcher_unavailable")
