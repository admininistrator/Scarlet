"""Test của `fetcher` — chạy TRONG image `fetcher` (`make test`), không ra mạng.

Mạng giả ở chỗ socket được mở (`httpcore.AnyIOBackend.connect_tcp`), cùng lối
`backend/tests/tools/test_ssrf.py`: `MockTransport` thay đúng tầng đang kiểm,
nên một client resolve lại tên vẫn xanh (T-6.3 ①). Resolver là hàm giả bơm vào.
"""

from __future__ import annotations

import asyncio
import gzip
import logging
import socket
import ssl
import time
from collections.abc import Awaitable, Callable, Sequence

import httpcore
import httpx
import pytest
import server

PUBLIC_V4 = "93.184.215.14"
CDN_V4 = "93.184.215.15"
VI = "Tiếng Việt có dấu: đường, nghiêng, ở, ữ"
CAPS = {
    "max_bytes": 64 * 1024,
    "timeout_s": 5.0,
    "max_redirects": 5,
    "js_escalate_min_chars": 200,
    "playwright_timeout_s": 10.0,
}


class _Stream(httpcore.AsyncMockStream):
    def __init__(self, network: FakeNetwork, ip: str) -> None:
        super().__init__([])
        self._network, self._ip, self._pending = network, ip, list[bytes]()

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        if not buffer:  # `h11` báo hết request bằng một lần ghi rỗng
            return
        path = buffer.split(b" ", 2)[1].decode()
        self._network.requests.append((self._ip, path))
        not_found = [b"HTTP/1.1 404 X\r\nContent-Length: 0\r\n\r\n"]
        self._pending = list(self._network.routes.get((self._ip, path), not_found))

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        if not self._pending:
            return b""
        self._network.reads += 1
        return self._pending.pop(0)

    async def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore.AsyncNetworkStream:
        return self


class FakeNetwork:
    def __init__(self) -> None:
        # (ip, path) -> các mảnh byte server gửi, mỗi lần `read` một mảnh.
        self.routes: dict[tuple[str, str], list[bytes]] = {}
        self.connects: list[str] = []
        self.reads = 0
        self.requests: list[tuple[str, str]] = []


@pytest.fixture
def network(monkeypatch: pytest.MonkeyPatch) -> FakeNetwork:
    fake = FakeNetwork()

    async def connect_tcp(_backend: object, host: str, port: int, **_: object) -> _Stream:
        fake.connects.append(host)
        return _Stream(fake, host)

    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", connect_tcp)
    return fake


class SequenceResolver:
    """Trả lần lượt từng phần tử của `answers`, phần tử cuối lặp mãi."""

    def __init__(self, *answers: list[str]) -> None:
        self.answers = list(answers)
        self.calls = 0

    async def __call__(self, host: str, port: int) -> Sequence[str]:
        self.calls += 1
        return self.answers[min(self.calls, len(self.answers)) - 1]


Resolver = Callable[[str, int], Awaitable[Sequence[str]]]


def by_host(**table: Resolver | list[str]) -> Resolver:
    """Resolver theo tên (`page_example` ⇒ `page.example`); tên lạ ⇒ không resolve."""

    async def resolve(host: str, port: int) -> Sequence[str]:
        answer = table.get(host.replace(".", "_"))
        if answer is None:
            raise socket.gaierror(socket.EAI_NONAME, "không có")
        return answer if isinstance(answer, list) else await answer(host, port)

    return resolve


def _response(body: bytes, *, status: int = 200, headers: str = "") -> list[bytes]:
    head = f"HTTP/1.1 {status} X\r\nContent-Length: {len(body)}\r\n{headers}\r\n"
    return [head.encode() + body]


def _chunked(chunks: list[bytes], content_type: str = "text/html") -> list[bytes]:
    head = f"HTTP/1.1 200 X\r\nContent-Type: {content_type}\r\nTransfer-Encoding: chunked\r\n\r\n"
    return [head.encode()] + [b"%x\r\n%s\r\n" % (len(c), c) for c in chunks] + [b"0\r\n\r\n"]


def _article(marker: str) -> str:
    para = f"<p>{VI}. Mã kiểm tra {marker} nằm trong đoạn văn đủ dài để trích. </p>"
    return (
        "<html><head><meta charset='utf-8'><title>Trang thử</title></head>"
        f"<body><article><h1>Trang thử</h1>{para * 6}</article></body></html>"
    )


def _fetch(url: str, resolver: Resolver, **caps: object) -> server.FetchResult:
    async def run() -> server.FetchResult:
        try:
            return await server.fetch(url, resolver=resolver, **{**CAPS, **caps})  # type: ignore[arg-type]
        finally:
            # Đối tượng Playwright gắn với event loop đã mở nó — mỗi `asyncio.run`
            # một loop, nên mỗi ca dừng browser của chính nó.
            await server.close_browser()

    return asyncio.run(run())


# ── Ghim IP (C23) ─────────────────────────────────────────────────────────────


def test_rebinding_connects_only_to_checked_ip(network: FakeNetwork) -> None:
    resolver = SequenceResolver([PUBLIC_V4], ["127.0.0.1"])
    body = _article("X7Q2").encode()
    network.routes[(PUBLIC_V4, "/")] = _response(body, headers="Content-Type: text/html\r\n")

    result = _fetch("https://rebind.example/", resolver)

    assert result.ok and "X7Q2" in result.text
    # Nối tới IP đã kiểm — không phải tên (client thường sẽ resolve lại, và lần hai
    # của resolver này là 127.0.0.1).
    assert network.connects == [PUBLIC_V4]
    assert resolver.calls == 1


# ── Trần byte (C25) ───────────────────────────────────────────────────────────


def test_stream_stops_at_cap_without_content_length(network: FakeNetwork) -> None:
    # 50 mảnh × 16 KiB, không `Content-Length`: đọc trọn rồi mới so là kéo cả 800 KiB.
    network.routes[(PUBLIC_V4, "/")] = _chunked([b"a" * 16384] * 50)

    result = _fetch("https://big.example/", SequenceResolver([PUBLIC_V4]))

    assert result.reason == "too_large"
    assert network.reads <= 64 * 1024 // 16384 + 3  # đầu + mảnh tới trần + một mảnh


def test_lying_content_length_gzip_counts_decompressed_bytes(network: FakeNetwork) -> None:
    # `Content-Length` khai cỡ NÉN (~1 KiB); giải nén ra 1 MiB > trần 64 KiB.
    bomb = gzip.compress(b"<p>" + b"a" * (1 << 20) + b"</p>")
    assert len(bomb) < CAPS["max_bytes"]
    network.routes[(PUBLIC_V4, "/")] = _response(
        bomb, headers="Content-Type: text/html\r\nContent-Encoding: gzip\r\n"
    )

    result = _fetch("https://bomb.example/", SequenceResolver([PUBLIC_V4]))

    assert result.reason == "too_large"


# ── Charset (C26) ─────────────────────────────────────────────────────────────


def test_meta_charset_wins_over_header() -> None:
    html = f"<html><head><meta charset='utf-8'></head><body>{VI}</body></html>".encode()

    assert VI in server.decode_body(html, "text/html", "iso-8859-1")


def test_http_equiv_meta_charset_wins_over_header() -> None:
    html = (
        '<meta http-equiv="Content-Type" content="text/html; charset=windows-1252"><p>café</p>'
    ).encode("cp1252")

    assert "café" in server.decode_body(html, "text/html", "utf-8")


def test_no_meta_no_header_uses_charset_normalizer() -> None:
    html = f"<html><body><p>{VI}. {VI}.</p></body></html>".encode()

    assert VI in server.decode_body(html, "text/html", None)


def test_meta_only_charset_end_to_end(network: FakeNetwork) -> None:
    network.routes[(PUBLIC_V4, "/")] = _response(
        _article("M3T4").encode(), headers="Content-Type: text/html\r\n"
    )

    result = _fetch("https://vi.example/", SequenceResolver([PUBLIC_V4]))

    assert result.ok and result.fetch_method == "httpx"
    assert VI in result.text and "M3T4" in result.text
    assert result.title == "Trang thử"
    assert result.final_url == "https://vi.example/"


# ── Mã lý do ──────────────────────────────────────────────────────────────────


def test_redirect_to_metadata_is_address(network: FakeNetwork) -> None:
    network.routes[(PUBLIC_V4, "/")] = _response(
        b"", status=302, headers="Location: http://169.254.169.254/latest/meta-data/\r\n"
    )

    result = _fetch("https://public.example/", SequenceResolver([PUBLIC_V4]))

    assert (result.ok, result.reason) == (False, "address")
    assert network.connects == [PUBLIC_V4]


@pytest.mark.parametrize(
    ("status", "content_type", "reason"),
    [
        (200, "application/pdf", "unsupported_type"),
        (200, "", "unsupported_type"),
        (404, "text/html", "http_404"),
    ],
)
def test_failure_reasons(network: FakeNetwork, status: int, content_type: str, reason: str) -> None:
    headers = f"Content-Type: {content_type}\r\n" if content_type else ""
    network.routes[(PUBLIC_V4, "/")] = _response(b"x", status=status, headers=headers)

    result = _fetch("https://r.example/", SequenceResolver([PUBLIC_V4]))

    assert (result.ok, result.reason) == (False, reason)


def test_total_timeout(network: FakeNetwork) -> None:
    async def slow(host: str, port: int) -> Sequence[str]:
        await asyncio.sleep(5)
        return [PUBLIC_V4]

    result = asyncio.run(
        server.fetch("https://slow.example/", resolver=slow, **{**CAPS, "timeout_s": 0.05})
    )  # type: ignore[arg-type]

    assert result.reason == "timeout"


def test_reason_never_carries_host_or_ip(network: FakeNetwork) -> None:
    result = _fetch("http://10.1.2.3/", SequenceResolver([PUBLIC_V4]))

    assert result.reason == "address"
    assert "10.1.2.3" not in repr(result)


# ── HTTP ──────────────────────────────────────────────────────────────────────


async def _post(body: dict[str, object]) -> httpx.Response:
    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://fetcher") as client:
        return await client.post("/fetch", json=body)


@pytest.mark.parametrize(
    "body",
    [
        {"url": "https://x.example/"},
        {"url": 1, **CAPS},
        {"url": "https://x.example/", **CAPS, "max_bytes": 0},
        {"url": "https://x.example/", **CAPS, "max_redirects": True},
        {"url": "https://x.example/", **CAPS, "js_escalate_min_chars": -1},
        {"url": "https://x.example/", **CAPS, "playwright_timeout_s": 0},
    ],
)
def test_endpoint_rejects_bad_body(body: dict[str, object]) -> None:
    assert asyncio.run(_post(body)).status_code == 422


def test_endpoint_returns_result_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    async def fake_fetch(url: str, **caps: object) -> server.FetchResult:
        seen.update(url=url, **caps)
        return server.FetchResult(ok=False, reason="dns")

    monkeypatch.setattr(server, "fetch", fake_fetch)

    response = asyncio.run(_post({"url": "https://x.example/", **CAPS}))

    assert response.json() == {
        "ok": False,
        "final_url": None,
        "title": None,
        "text": "",
        "fetch_method": "httpx",
        "reason": "dns",
    }
    assert seen == {"url": "https://x.example/", **CAPS}


# ── Leo thang Playwright (T-6.6) — Chromium THẬT, mạng giả ───────────────────
# Trình duyệt chỉ thấy byte do `route` tự lấy qua `connect_tcp` giả ở trên. Request
# nào để Chromium tự đi (`continue_`, `fetch`, bỏ `route`) thì vào proxy chết,
# không bao giờ tới mạng giả ⇒ mã không có trong trang ⇒ đỏ.


def _js_page(last_script: str, *, scripts: int = 4) -> bytes:
    filler = "<script>var x = 1;</script>" * (scripts - 1)
    return (
        "<html><head><meta charset='utf-8'><title>JS</title></head>"
        f"<body><div id='out'></div>{filler}{last_script}</body></html>"
    ).encode()


def _writer_js(marker: str) -> bytes:
    para = f"<p>{VI}. Mã kiểm tra {marker} chỉ có sau khi script chạy. </p>"
    return (
        f"document.getElementById('out').innerHTML = "
        f"'<article>' + {para!r}.repeat(6) + '</article>';"
    ).encode()


def _html(body: bytes) -> list[bytes]:
    return _response(body, headers="Content-Type: text/html\r\n")


def _js(body: bytes) -> list[bytes]:
    return _response(body, headers="Content-Type: text/javascript\r\n")


@pytest.mark.parametrize(("scripts", "method"), [(4, "playwright"), (3, "httpx")])
def test_js_heavy_page_escalates_and_subrequests_are_pinned(
    network: FakeNetwork, scripts: int, method: str
) -> None:
    network.routes[(PUBLIC_V4, "/")] = _html(
        _js_page('<script src="https://cdn.example/app.js"></script>', scripts=scripts)
    )
    network.routes[(CDN_V4, "/app.js")] = _js(_writer_js("R8B3"))
    # Rebinding: lần resolve thứ hai của `cdn.example` là loopback. Mã chỉ tới
    # trang khi script được lấy từ đúng IP đã kiểm lần đầu.
    cdn = SequenceResolver([CDN_V4], ["127.0.0.1"])

    result = _fetch("https://page.example/", by_host(page_example=[PUBLIC_V4], cdn_example=cdn))

    assert result.ok and result.fetch_method == method
    if method == "httpx":  # 3 thẻ <script> — không leo thang (§12.3: "> 3")
        assert "R8B3" not in result.text
        assert (CDN_V4, "/app.js") not in network.requests
    else:
        assert "R8B3" in result.text and VI in result.text
        assert set(network.connects) == {PUBLIC_V4, CDN_V4}
        assert cdn.calls == 1


def test_browser_requests_outside_checked_path_are_blocked(
    network: FakeNetwork, caplog: pytest.LogCaptureFixture
) -> None:
    blocked = {
        # Cổng lạ, tên công khai. `http://` từ trang `https` thì Chromium tự chặn
        # (mixed content) trước khi tới `route` — xanh giả, đã đo.
        "https://page.example:8443/": "port",
        "https://intra.example/": "address",  # tên trỏ vào IP riêng
        "https://cdn.example/post": "method",
        "https://cdn.example/pic.png": "type",  # ảnh (§12.3 bước 5)
    }
    calls = "".join(
        f"fetch('{url}', {{mode: 'no-cors'}}).catch(() => {{}});"
        for url in ("https://page.example:8443/", "https://intra.example/")
    )
    calls += (
        "fetch('https://cdn.example/post', {method: 'POST', mode: 'no-cors', body: 'x'})"
        ".catch(() => {});"
    )
    calls += "fetch('https://cdn.example/ok.json').catch(() => {});"  # đối chứng: được đi
    network.routes[(PUBLIC_V4, "/")] = _html(
        _js_page(f"<img src='https://cdn.example/pic.png'><script>{calls}</script>")
    )
    network.routes[(CDN_V4, "/ok.json")] = _response(
        b"{}", headers="Content-Type: application/json\r\n"
    )
    resolver = by_host(page_example=[PUBLIC_V4], cdn_example=[CDN_V4], intra_example=["10.0.0.5"])

    with caplog.at_level(logging.INFO, logger="fetcher"):
        result = _fetch("https://page.example/", resolver)

    assert result.ok and result.fetch_method == "playwright"
    # Mạng chỉ thấy trang (lượt httpx + lượt trình duyệt) và đối chứng.
    assert set(network.requests) == {(PUBLIC_V4, "/"), (CDN_V4, "/ok.json")}
    for url, reason in blocked.items():
        line = f"reason={reason} "
        digest = f"url_sha={server._url_digest(url)}"
        assert any(line in m and digest in m for m in caplog.messages), url


def test_one_byte_cap_for_all_browser_requests(
    network: FakeNetwork, caplog: pytest.LogCaptureFixture
) -> None:
    # Mỗi script 40 KiB < trần 64 KiB, nhưng hai cái cộng lại thì vượt.
    big = b"/*" + b"a" * (40 * 1024) + b"*/"
    network.routes[(PUBLIC_V4, "/")] = _html(
        _js_page(
            '<script src="https://cdn.example/a.js"></script>'
            '<script src="https://cdn.example/b.js"></script>',
            scripts=3,
        )
    )
    network.routes[(CDN_V4, "/a.js")] = _js(big)
    network.routes[(CDN_V4, "/b.js")] = _js(big)

    with caplog.at_level(logging.INFO, logger="fetcher"):
        result = _fetch(
            "https://page.example/", by_host(page_example=[PUBLIC_V4], cdn_example=[CDN_V4])
        )

    assert result.fetch_method == "playwright"
    assert sum("reason=too_large type=script" in m for m in caplog.messages) == 1


def test_stuck_page_times_out_and_next_render_works(network: FakeNetwork) -> None:
    network.routes[(PUBLIC_V4, "/hang")] = _html(_js_page("<script>while (true) {}</script>"))
    network.routes[(PUBLIC_V4, "/ok")] = _html(
        _js_page('<script src="https://cdn.example/app.js"></script>')
    )
    network.routes[(CDN_V4, "/app.js")] = _js(_writer_js("H5N2"))
    resolver = by_host(page_example=[PUBLIC_V4], cdn_example=[CDN_V4])

    async def run() -> tuple[server.FetchResult, float, server.FetchResult]:
        try:
            started = time.monotonic()
            stuck = await server.fetch(
                "https://page.example/hang",
                resolver=resolver,
                **{**CAPS, "playwright_timeout_s": 2.0},  # type: ignore[arg-type]
            )
            elapsed = time.monotonic() - started
            after = await server.fetch("https://page.example/ok", resolver=resolver, **CAPS)  # type: ignore[arg-type]
            return stuck, elapsed, after
        finally:
            await server.close_browser()

    stuck, elapsed, after = asyncio.run(run())

    assert (stuck.ok, stuck.reason, stuck.fetch_method) == (False, "timeout", "playwright")
    assert elapsed < 2.0 * 1.1 + 0.5  # trần + lượt httpx giả (B-278: biên 10 %)
    assert after.ok and "H5N2" in after.text
