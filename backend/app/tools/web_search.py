"""Tìm web qua `SearchProvider` (§12.4, §13.5) — T-6.1.

KH tham chiếu: §12.4, §13.5 · UC-08 dòng 5 · A3, A4 · B-165.

**Hỏng là dữ liệu, không phải ngoại lệ.** UC-08 dòng 5: Tavily hỏng / hết
quota thì chat vẫn chạy. Một `raise` lọt vào vòng lặp tool (T-6.7a) là event
`error` cho cả câu trả lời — nên mọi ngả hỏng ở đây (401/403, 429, 5xx, hết
giờ, DNS, JSON hỏng) thành `SearchResult(error=<mã cố định>)`, model được báo
và trả lời bằng kiến thức sẵn có. Mã cố định, **không** chép thân response của
Tavily: thân ấy là chữ của bên ngoài và sẽ đi vào ngữ cảnh model.

**Khoá chỉ ở header** (B-165): query string vào access log và dòng `INFO` của
`httpx`, header thì không. Log hỏng không chứa khoá, không chứa câu hỏi — chỉ
độ dài của nó.

**Không `tavily-python`:** nó kéo `requests` (đồng bộ — đứng event loop của
worker) và `tiktoken`. `httpx.AsyncClient` có sẵn là đủ.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

from app.config.settings import settings

logger = logging.getLogger(__name__)


class SearchError(StrEnum):
    """Mã hỏng cố định — thứ duy nhất của một lượt hỏng đi vào ngữ cảnh model."""

    NOT_CONFIGURED = "not_configured"
    UNAUTHORIZED = "unauthorized"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    UPSTREAM = "upstream"


@dataclass(frozen=True, slots=True)
class SearchHit:
    title: str
    url: str
    content: str


@dataclass(frozen=True, slots=True)
class SearchResult:
    results: tuple[SearchHit, ...] = ()
    error: SearchError | None = None


class SearchProvider(Protocol):
    """§12.4: thêm nguồn tìm khác không phải sửa call site."""

    async def search(self, query: str, *, max_results: int | None = None) -> SearchResult: ...


#: Đường dẫn và cách gắn khoá là hợp đồng của API Tavily, không phải cấu hình
#: vận hành — hằng ở đây; địa chỉ thì ở `Settings` (A3).
_SEARCH_PATH = "/search"
_BEARER_PREFIX = "Bearer "
_STATUS_UNAUTHORIZED = frozenset({401, 403})
#: 432 / 433 là "hết hạn mức gói / hạn mức trả theo lượt" của Tavily — với
#: người dùng cùng nghĩa với 429: chờ, khoá không sai.
_STATUS_RATE_LIMITED = frozenset({429, 432, 433})
_HTTP_SCHEMES = frozenset({"http", "https"})


def _client() -> httpx.AsyncClient:
    """Tách riêng để test bơm `httpx.MockTransport` (lối `llm/byok_verify.py`)."""
    return httpx.AsyncClient(timeout=settings.WEB_SEARCH_TIMEOUT_S)


def _is_absolute_http(url: object) -> bool:
    """Chỉ `http(s)` tuyệt đối — `javascript:`, `data:`, tương đối bị bỏ."""
    if not isinstance(url, str):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme in _HTTP_SCHEMES and bool(parts.hostname)


def _parse(data: Any) -> tuple[SearchHit, ...]:
    """Thiếu khoá / sai kiểu ⇒ `KeyError` / `TypeError` / `AttributeError` — gọi
    nơi bắt và đổi thành `upstream`."""
    return tuple(
        SearchHit(
            title=str(item.get("title") or ""),
            url=item["url"],
            content=str(item.get("content") or ""),
        )
        for item in data["results"]
        if _is_absolute_http(item.get("url"))
    )


def _fail(error: SearchError, query: str, reason: str) -> SearchResult:
    logger.warning(
        "web_search hong: error=%s ly_do=%s do_dai_cau_hoi=%d", error, reason, len(query)
    )
    return SearchResult(error=error)


class TavilySearch:
    """`SearchProvider` gọi `POST {TAVILY_BASE_URL}/search`. Mọi trần đọc lúc gọi."""

    async def search(self, query: str, *, max_results: int | None = None) -> SearchResult:
        key = settings.TAVILY_API_KEY.get_secret_value()
        if not key:
            return _fail(SearchError.NOT_CONFIGURED, query, "TAVILY_API_KEY rong")
        limit = settings.WEB_SEARCH_MAX_RESULTS if max_results is None else max_results
        try:
            # `asyncio.timeout` là trần TỔNG; trần của `httpx` chỉ tính từng
            # chặng, nên một server nhỏ giọt vượt được nó.
            async with asyncio.timeout(settings.WEB_SEARCH_TIMEOUT_S), _client() as client:
                resp = await client.post(
                    f"{settings.TAVILY_BASE_URL}{_SEARCH_PATH}",
                    headers={"Authorization": f"{_BEARER_PREFIX}{key}"},
                    json={"query": query, "max_results": limit},
                )
                resp.raise_for_status()
                hits = _parse(resp.json())
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in _STATUS_UNAUTHORIZED:
                error = SearchError.UNAUTHORIZED
            elif status in _STATUS_RATE_LIMITED:
                error = SearchError.RATE_LIMITED
            else:
                error = SearchError.UPSTREAM
            return _fail(error, query, f"HTTP {status}")
        except (TimeoutError, httpx.TimeoutException) as exc:
            return _fail(SearchError.TIMEOUT, query, type(exc).__name__)
        except httpx.HTTPError as exc:
            # DNS, kết nối bị từ chối, TLS, đứt giữa chừng.
            return _fail(SearchError.UPSTREAM, query, type(exc).__name__)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            # JSON hỏng (`JSONDecodeError` là `ValueError`) hoặc sai hình dạng.
            return _fail(SearchError.UPSTREAM, query, f"json {type(exc).__name__}")
        return SearchResult(results=hits)
