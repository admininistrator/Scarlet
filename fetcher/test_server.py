"""Test của `fetcher` — chạy TRONG image `fetcher` (`make test`), không ra mạng.

Mạng giả ở chỗ socket được mở (`httpcore.AnyIOBackend.connect_tcp`), cùng lối
`backend/tests/tools/test_ssrf.py`: `MockTransport` thay đúng tầng đang kiểm,
nên một client resolve lại tên vẫn xanh (T-6.3 ①). Resolver là hàm giả bơm vào.
"""

from __future__ import annotations

import asyncio
import gzip
import ssl
from collections.abc import Sequence

import httpcore
import httpx
import pytest
import server

PUBLIC_V4 = "93.184.215.14"
VI = "Tiếng Việt có dấu: đường, nghiêng, ở, ữ"
CAPS = {"max_bytes": 64 * 1024, "timeout_s": 5.0, "max_redirects": 5}


class _Stream(httpcore.AsyncMockStream):
    def __init__(self, network: FakeNetwork, ip: str) -> None:
        super().__init__([])
        self._network, self._ip, self._pending = network, ip, list[bytes]()

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        if not buffer:  # `h11` báo hết request bằng một lần ghi rỗng
            return
        path = buffer.split(b" ", 2)[1].decode()
        self._pending = list(self._network.routes[(self._ip, path)])

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


def _fetch(url: str, resolver: SequenceResolver, **caps: object) -> server.FetchResult:
    return asyncio.run(server.fetch(url, resolver=resolver, **{**CAPS, **caps}))  # type: ignore[arg-type]


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
