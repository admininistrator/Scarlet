"""`fetcher` — đọc một URL người dùng đưa, trả chữ (§12, T-6.5).

Lớp 1 của §12.2: service này chỉ ở mạng `egress`, không `internal`, không
`env_file` — kể cả khi mọi thứ dưới đây vỡ, `redis` / `postgres` / `api` không
resolve được từ đây. Lớp 2–4 là `ssrf.py`, **cùng một file** với backend (chép
vào image qua `additional_contexts`).

Không đọc `.env`: mọi trần tới trong từng request từ `worker` (nơi đọc
`Settings` lúc gọi). `reason` là mã cố định — không bao giờ chép host / IP.

T-6.6 — leo thang Playwright (§12.3 bước 4–5): trình duyệt tự resolve DNS và tự
mở mọi request con, nên **không request nào của nó tự ra mạng**: `context.route`
nhận tất cả, tự GET bằng đúng đường đã kiểm ở trên (lớp 2–4 + trần byte) rồi
`route.fulfill`. `route.continue_()` / `route.fetch()` để mạng của Chromium tự
resolve lại — C23 trong trình duyệt. Thứ lọt khỏi `route` (preconnect, …) đi vào
một proxy chết; rào `iptables` của `entrypoint.sh` (B-382) là lớp dưới cùng.
"""

from __future__ import annotations

import asyncio
import codecs
import hashlib
import logging
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

import charset_normalizer
import httpx
import trafilatura
from playwright.async_api import (
    Browser,
    BrowserContext,
    Playwright,
    WebSocketRoute,
    async_playwright,
)
from playwright.async_api import Error as BrowserError
from playwright.async_api import Route as BrowserRoute
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

# §12.3 bước 4 — luật của KH, không phải núm chỉnh: "> 3 thẻ <script>".
_SCRIPT_TAG = re.compile(r"<script\b", re.I)
_JS_HEAVY_SCRIPTS = 3
# Loại request con trình duyệt được nhận (qua đường đã kiểm). Ảnh / font / media
# bỏ (§12.3 bước 5); loại lạ (`ping`, `manifest`, `other`, …) cũng bỏ — đóng,
# không mở.
_FULFILLED_TYPES = frozenset({"document", "script", "xhr", "fetch", "stylesheet"})
# Không còn đúng sau khi `httpx` đã giải nén và gom body.
_DROPPED_HEADERS = frozenset({"content-encoding", "content-length", "transfer-encoding"})
# Cổng `discard` trên loopback: không ai nghe. Mọi kết nối Chromium tự mở ngoài
# `route` (preconnect, DNS prefetch) đi vào đây chứ không ra mạng.
_DEAD_PROXY = "http://127.0.0.1:9"
# `/dev/shm` của Docker mặc định 64 MB ⇒ tab chết (T-5.6 ⑦). KHÔNG
# `--single-process` (chữ "Sửa" của C24): renderer chung tiến trình với browser
# thì một trang `while (true)` đứng cả browser (B-374); context mỗi lượt là đủ.
# `--no-sandbox` Playwright tự thêm (`chromium_sandbox` mặc định tắt): container
# không root, `cap_drop: ALL`, `no-new-privileges` — sandbox của Chromium không
# dựng được ở đây; cách ly là container + mạng `egress` + rào `iptables`.
_CHROMIUM_ARGS = ["--disable-dev-shm-usage"]


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


async def _checked_get(
    url: str, *, max_bytes: int, timeout_s: float, max_redirects: int, extra: dict[str, Any]
) -> httpx.Response | str:
    """GET qua lớp 2–4 + trần byte. Trả response, hoặc `reason` (mã cố định)."""
    try:
        # Trần TỔNG: trần của `httpx` chỉ tính từng chặng — một server nhỏ giọt
        # từng byte giữ được kết nối mãi.
        async with asyncio.timeout(timeout_s):
            return await get_following_redirects(
                url,
                headers=_HEADERS,
                timeout=timeout_s,
                max_redirects=max_redirects,
                max_bytes=max_bytes,
                **extra,
            )
    except UnsafeUrlError as exc:
        return exc.reason
    except ResponseTooLarge as exc:
        logger.info("too_large: bytes_read=%d max_bytes=%d", exc.bytes_read, max_bytes)
        return "too_large"
    except httpx.TooManyRedirects:
        return "too_many_redirects"
    except (TimeoutError, httpx.TimeoutException):
        return "timeout"
    except httpx.HTTPError:
        # Nối không được, TLS hỏng, server ngắt giữa chừng.
        return "network"


# ── Trình duyệt (T-6.6) ───────────────────────────────────────────────────────
# MỘT browser cho cả tiến trình, khởi LƯỜI ở lượt leo thang đầu tiên: boot và
# healthcheck không chờ Chromium, và `fetcher` không giữ RAM của nó khi chưa
# trang nào cần. Mỗi lượt một context mới, đóng trong `finally` (C24).
_playwright: Playwright | None = None
_browser: Browser | None = None
_browser_lock = asyncio.Lock()
# Task dọn sau lượt hết giờ — giữ tham chiếu để không bị GC giữa chừng.
_cleanups: set[asyncio.Task[None]] = set()


async def _get_browser() -> Browser:
    global _playwright, _browser
    async with _browser_lock:
        if _browser is None or not _browser.is_connected():
            if _playwright is None:
                _playwright = await async_playwright().start()
            _browser = await _playwright.chromium.launch(
                args=_CHROMIUM_ARGS, proxy={"server": _DEAD_PROXY}
            )
        return _browser


async def close_browser() -> None:
    """Dừng driver Playwright — nó giết mọi tiến trình Chromium nó đã mở, kể cả
    khi browser không còn trả lời (`browser.close()` thì có thể chờ mãi)."""
    global _playwright, _browser
    playwright, _playwright, _browser = _playwright, None, None
    if playwright is not None:
        await playwright.stop()


async def _cleanup_after_timeout(context: BrowserContext, timeout_s: float) -> None:
    # B-374: renderer kẹt có thể kéo theo cả browser. Đóng context rồi hỏi browser
    # một câu; không trả lời trong cùng trần ⇒ khởi lại (lượt kế tự mở browser mới).
    try:
        async with asyncio.timeout(timeout_s):
            await context.close()
            if context.browser is not None:
                probe = await context.browser.new_context()
                await probe.close()
    except (TimeoutError, BrowserError):
        logger.warning("browser khong tra loi sau timeout: khoi lai")
        await close_browser()


def _url_digest(url: str) -> str:
    # Không ghi URL (trang người dùng đưa và mọi thứ nó gọi) — chỉ dấu băm, đủ để
    # đối chiếu khi đã biết URL.
    return hashlib.sha256(url.encode()).hexdigest()[:12]


async def _render(
    url: str, *, max_bytes: int, timeout_s: float, max_redirects: int, extra: dict[str, Any]
) -> FetchResult:
    used = 0  # MỘT trần byte cho mọi request của trình duyệt trong lượt
    fulfilled: Counter[str] = Counter()
    blocked: Counter[str] = Counter()

    async def block(route: BrowserRoute, kind: str, reason: str) -> None:
        blocked[kind] += 1
        logger.info(
            "route: chan reason=%s type=%s url_sha=%s",
            reason,
            kind,
            _url_digest(route.request.url),
        )
        await route.abort("blockedbyclient")

    async def handle(route: BrowserRoute) -> None:
        nonlocal used
        request = route.request
        kind = request.resource_type
        try:
            if request.method != "GET":
                return await block(route, kind, "method")
            if kind not in _FULFILLED_TYPES:
                return await block(route, kind, "type")
            upstream = await _checked_get(
                request.url,
                max_bytes=max_bytes - used,
                timeout_s=timeout_s,
                max_redirects=max_redirects,
                extra=extra,
            )
            if isinstance(upstream, str):
                return await block(route, kind, upstream)
            body = upstream.content
            # ponytail: request song song mỗi cái đọc tới phần còn lại LÚC BẮT ĐẦU —
            # RAM tạm ≤ số request đang bay × trần; byte VÀO trình duyệt thì không
            # bao giờ vượt trần (phép so + cộng dưới đây không có `await` xen giữa).
            if used + len(body) > max_bytes:
                return await block(route, kind, "too_large")
            used += len(body)
            fulfilled[kind] += 1
            headers = {k: v for k, v in upstream.headers.items() if k not in _DROPPED_HEADERS}
            await route.fulfill(status=upstream.status_code, headers=headers, body=body)
        except BrowserError:
            pass  # context đã đóng giữa chừng (lượt hết giờ)

    async def close_socket(socket: WebSocketRoute) -> None:
        blocked["websocket"] += 1
        logger.info(
            "route: chan reason=websocket type=websocket url_sha=%s", _url_digest(socket.url)
        )
        await socket.close()

    context: BrowserContext | None = None
    timed_out = False
    try:
        # Trần gồm cả mở browser (lượt đầu) — không bước nào ngoài trần.
        async with asyncio.timeout(timeout_s):
            browser = await _get_browser()
            context = await browser.new_context(service_workers="block")
            await context.route("**/*", handle)
            await context.route_web_socket("**/*", close_socket)
            page = await context.new_page()
            await page.goto(url, wait_until="networkidle", timeout=0)
            html = await page.content()
    except TimeoutError:
        timed_out = True
        return FetchResult(ok=False, fetch_method="playwright", reason="timeout")
    except BrowserError as exc:
        logger.warning("render hong: %s", type(exc).__name__)
        return FetchResult(ok=False, fetch_method="playwright", reason="browser")
    finally:
        logger.info(
            "render: fulfilled=%s blocked=%s bytes=%d", dict(fulfilled), dict(blocked), used
        )
        if context is not None and timed_out:
            # `worker` không chờ việc dọn: trả `timeout` ngay.
            task = asyncio.create_task(_cleanup_after_timeout(context, timeout_s))
            _cleanups.add(task)
            task.add_done_callback(_cleanups.discard)
        elif context is not None:
            await context.close()
    title, text = await asyncio.to_thread(_extract, html)
    return FetchResult(ok=True, final_url=url, title=title, text=text, fetch_method="playwright")


async def fetch(
    url: str,
    *,
    max_bytes: int,
    timeout_s: float,
    max_redirects: int,
    js_escalate_min_chars: int,
    playwright_timeout_s: float,
    resolver: Resolver | None = None,
) -> FetchResult:
    extra: dict[str, Any] = {} if resolver is None else {"resolver": resolver}
    response = await _checked_get(
        url, max_bytes=max_bytes, timeout_s=timeout_s, max_redirects=max_redirects, extra=extra
    )
    if isinstance(response, str):
        return FetchResult(ok=False, reason=response)

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
    # §12.3 bước 4: ít chữ VÀ nhiều script ⇒ trang JS-heavy. Trình duyệt đi lại từ
    # `final_url` (redirect đã kiểm xong ở trên); mọi request của nó qua `route`.
    if (
        len(extracted) < js_escalate_min_chars
        and len(_SCRIPT_TAG.findall(text)) > _JS_HEAVY_SCRIPTS
    ):
        return await _render(
            final_url,
            max_bytes=max_bytes,
            timeout_s=playwright_timeout_s,
            max_redirects=max_redirects,
            extra=extra,
        )
    return FetchResult(ok=True, final_url=final_url, title=title, text=extracted)


def _positive_number(value: Any) -> bool:
    return type(value) in (int, float) and value > 0


def _caps(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict) or not isinstance(body.get("url"), str):
        raise ValueError
    max_bytes, max_redirects, min_chars = (
        body.get("max_bytes"),
        body.get("max_redirects"),
        body.get("js_escalate_min_chars"),
    )
    if not (
        type(max_bytes) is int
        and max_bytes > 0
        and _positive_number(body.get("timeout_s"))
        and type(max_redirects) is int
        and max_redirects >= 0
        and type(min_chars) is int
        and min_chars >= 0
        and _positive_number(body.get("playwright_timeout_s"))
    ):
        raise ValueError
    return {
        "url": body["url"],
        "max_bytes": max_bytes,
        "timeout_s": float(body["timeout_s"]),
        "max_redirects": max_redirects,
        "js_escalate_min_chars": min_chars,
        "playwright_timeout_s": float(body["playwright_timeout_s"]),
    }


async def fetch_endpoint(request: Request) -> JSONResponse:
    try:
        caps = _caps(await request.json())
    except ValueError:  # gồm JSON hỏng
        return JSONResponse({"error": "bad_request"}, status_code=422)
    started = time.monotonic()
    result = await fetch(**caps)
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
