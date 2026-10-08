"""`fetcher` — đọc một URL người dùng đưa, trả chữ (§12, T-6.5).

Lớp 1 của §12.2: service này chỉ ở mạng `egress`, không `internal`, không
`env_file` — kể cả khi mọi thứ dưới đây vỡ, `redis` / `postgres` / `api` không
resolve được từ đây. Lớp 2–4 là `ssrf.py`, **cùng một file** với backend (chép
vào image qua `additional_contexts`).

Không đọc `.env`: mọi trần tới trong từng request từ `worker` (nơi đọc
`Settings` lúc gọi). `reason` là mã cố định — không bao giờ chép host / IP.
"""

from __future__ import annotations

import asyncio
import codecs
import logging
import re
import time
from dataclasses import asdict, dataclass
from typing import Any

import charset_normalizer
import httpx
import trafilatura
from ssrf import Resolver, ResponseTooLarge, UnsafeUrlError, get_following_redirects
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("fetcher")
# Dòng INFO của `httpx` chép nguyên URL — thứ người dùng gõ — vào log.
logging.getLogger("httpx").setLevel(logging.WARNING)

_TEXT_TYPES = frozenset({"text/html", "application/xhtml+xml", "text/plain"})
# HTML "prescan": trình duyệt chỉ tìm `<meta charset>` trong 1024 byte đầu. Bắt
# cả `<meta charset=x>` lẫn `<meta http-equiv=… content="…; charset=x">`.
_PRESCAN_BYTES = 1024
# `ssrf.get_following_redirects` gửi một `httpx.Request` trần — không có header
# mặc định của client. Thiếu `Accept-Encoding` thì server gửi bản không nén: đo
# html.spec.whatwg.org — 5 MiB không nén vượt `FETCH_TIMEOUT_S`, nén thì ~3 s.
# Không `br` / `zstd`: image không có bộ giải nén cho chúng.
_HEADERS = {
    "Accept-Encoding": "gzip, deflate",
    "User-Agent": f"python-httpx/{httpx.__version__}",
}
_META_CHARSET = re.compile(rb"""<meta[^>]*?charset\s*=\s*["']?\s*([A-Za-z0-9_.:-]+)""", re.I)


@dataclass(frozen=True)
class FetchResult:
    ok: bool
    final_url: str | None = None
    title: str | None = None
    text: str = ""
    fetch_method: str = "httpx"
    reason: str | None = None


def _codec(name: bytes | str | None) -> str | None:
    if not name:
        return None
    try:
        return codecs.lookup(name.decode("ascii") if isinstance(name, bytes) else name).name
    except (LookupError, UnicodeDecodeError):
        return None


def decode_body(body: bytes, media_type: str, header_charset: str | None) -> str:
    """C26: `<meta charset>` **trước** header; thiếu cả hai ⇒ `charset-normalizer`."""
    meta = None
    if media_type != "text/plain":
        found = _META_CHARSET.search(body[:_PRESCAN_BYTES])
        meta = found.group(1) if found else None
    encoding = _codec(meta) or _codec(header_charset)
    if encoding is None:
        best = charset_normalizer.from_bytes(body).best()
        encoding = best.encoding if best is not None else "utf-8"
    return body.decode(encoding, errors="replace")


def _extract(html: str) -> tuple[str | None, str]:
    # Không truyền `url=`: log lỗi của `trafilatura` chép nguyên nó.
    document = trafilatura.bare_extraction(html, with_metadata=True)
    if document is None:
        return None, ""
    return document.title or None, document.text or ""


async def fetch(
    url: str,
    *,
    max_bytes: int,
    timeout_s: float,
    max_redirects: int,
    resolver: Resolver | None = None,
) -> FetchResult:
    extra: dict[str, Any] = {} if resolver is None else {"resolver": resolver}
    try:
        # Trần TỔNG: trần của `httpx` chỉ tính từng chặng — một server nhỏ giọt
        # từng byte giữ được kết nối mãi.
        async with asyncio.timeout(timeout_s):
            response = await get_following_redirects(
                url,
                headers=_HEADERS,
                timeout=timeout_s,
                max_redirects=max_redirects,
                max_bytes=max_bytes,
                **extra,
            )
    except UnsafeUrlError as exc:
        return FetchResult(ok=False, reason=exc.reason)
    except ResponseTooLarge as exc:
        logger.info("too_large: bytes_read=%d max_bytes=%d", exc.bytes_read, max_bytes)
        return FetchResult(ok=False, reason="too_large")
    except httpx.TooManyRedirects:
        return FetchResult(ok=False, reason="too_many_redirects")
    except (TimeoutError, httpx.TimeoutException):
        return FetchResult(ok=False, reason="timeout")
    except httpx.HTTPError:
        # Nối không được, TLS hỏng, server ngắt giữa chừng.
        return FetchResult(ok=False, reason="network")

    if not response.is_success:
        return FetchResult(ok=False, reason=f"http_{response.status_code}")
    media_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if media_type not in _TEXT_TYPES:
        return FetchResult(ok=False, reason="unsupported_type")

    final_url = str(response.url)
    text = decode_body(response.content, media_type, response.charset_encoding)
    if media_type == "text/plain":
        return FetchResult(ok=True, final_url=final_url, text=text)
    # `trafilatura` ăn CPU — ra luồng riêng, không đứng mọi lượt khác.
    title, extracted = await asyncio.to_thread(_extract, text)
    return FetchResult(ok=True, final_url=final_url, title=title, text=extracted)


def _caps(body: Any) -> tuple[str, int, float, int]:
    if not isinstance(body, dict) or not isinstance(body.get("url"), str):
        raise ValueError
    max_bytes, timeout_s, max_redirects = (
        body.get("max_bytes"),
        body.get("timeout_s"),
        body.get("max_redirects"),
    )
    if not (
        type(max_bytes) is int
        and max_bytes > 0
        and type(timeout_s) in (int, float)
        and timeout_s > 0
        and type(max_redirects) is int
        and max_redirects >= 0
    ):
        raise ValueError
    return body["url"], max_bytes, float(timeout_s), max_redirects


async def fetch_endpoint(request: Request) -> JSONResponse:
    try:
        url, max_bytes, timeout_s, max_redirects = _caps(await request.json())
    except ValueError:  # gồm JSON hỏng
        return JSONResponse({"error": "bad_request"}, status_code=422)
    started = time.monotonic()
    result = await fetch(url, max_bytes=max_bytes, timeout_s=timeout_s, max_redirects=max_redirects)
    # Không ghi URL: đó là thứ người dùng gõ.
    logger.info(
        "fetch: ok=%s reason=%s fetch_method=%s chars=%d ms=%d",
        result.ok,
        result.reason,
        result.fetch_method,
        len(result.text),
        (time.monotonic() - started) * 1000,
    )
    return JSONResponse(asdict(result))


async def health(_: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


app = Starlette(
    routes=[
        Route("/fetch", fetch_endpoint, methods=["POST"]),
        Route("/health", health),
    ]
)
