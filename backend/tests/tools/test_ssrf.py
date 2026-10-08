"""`app/tools/ssrf.py` — T-6.2 (lớp 2 + 3), T-6.3 (ghim IP + lớp 4), T-6.4 (S10).

Không ca nào chạm DNS thật (`make test` không ra Internet): resolver là hàm giả
bơm vào. Vì thế mọi ca từ chối khẳng định **mã lý do** — trên host WSL `redis`
không resolve được, nên một ca "có ném là được" sẽ xanh vì DNS hỏng chứ không
vì IP riêng.

"IP công khai" ở đây là địa chỉ công khai thật (`93.184.215.14`, `1.1.1.1`),
không phải dải tài liệu `192.0.2.0/24` / `2001:db8::/32` — `ipaddress` xếp
những dải đó vào `is_private`, nên chính `validate_url()` sẽ từ chối chúng.
"""

from __future__ import annotations

import socket
import ssl
from collections.abc import Awaitable, Callable, Sequence

import httpcore
import httpx
import pytest

from app.config.settings import settings
from app.tools.ssrf import (
    CheckedUrl,
    UnsafeUrlError,
    get_following_redirects,
    pinned_client,
    validate_url,
)

PUBLIC_V4 = "93.184.215.14"
PUBLIC_V4_B = "1.1.1.1"


class FakeResolver:
    def __init__(self, result: Sequence[str] | Exception) -> None:
        self.result = result
        self.calls: list[tuple[str, int]] = []

    async def __call__(self, host: str, port: int) -> Sequence[str]:
        self.calls.append((host, port))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _never_called() -> FakeResolver:
    return FakeResolver(AssertionError("resolver không được gọi"))


async def _rejected(url: str, resolver: FakeResolver) -> UnsafeUrlError:
    with pytest.raises(UnsafeUrlError) as info:
        await validate_url(url, resolver=resolver)
    return info.value


def _assert_no_ip_leak(exc: UnsafeUrlError, ips: Sequence[str]) -> None:
    for ip in ips:
        assert ip not in str(exc)
        assert ip not in repr(exc)


# ── Nhận ──────────────────────────────────────────────────────────────────────


async def test_accepts_name_resolving_to_public_ips_and_normalizes_host() -> None:
    resolver = FakeResolver([PUBLIC_V4, PUBLIC_V4_B, PUBLIC_V4])

    checked = await validate_url("https://API.Example.COM./v1/models", resolver=resolver)

    assert checked == CheckedUrl(
        scheme="https", host="api.example.com", port=443, ips=(PUBLIC_V4, PUBLIC_V4_B)
    )
    assert resolver.calls == [("api.example.com", 443)]


async def test_accepts_public_ipv6_literal_without_resolving() -> None:
    checked = await validate_url("https://[2606:4700:4700::1111]/", resolver=_never_called())

    assert checked.ips == ("2606:4700:4700::1111",)
    assert checked.host == "2606:4700:4700::1111"


async def test_idna_host_is_resolved_in_ascii_form() -> None:
    resolver = FakeResolver([PUBLIC_V4])

    checked = await validate_url("http://Bücher.example/", resolver=resolver)

    assert (checked.host, checked.port) == ("xn--bcher-kva.example", 80)
    assert resolver.calls == [("xn--bcher-kva.example", 80)]


async def test_accepts_ipv4_mapped_public_address() -> None:
    # Python 3.12.3 (`.venv`) xếp mọi `::ffff:x` là `is_reserved` — không mở
    # `ipv4_mapped` ra trước thì địa chỉ công khai này bị chặn oan, và ca này đỏ.
    # Cặp với ca `[::ffff:100.64.0.1]` bên dưới (đỏ trên 3.12.14 của container
    # khi thiếu nhánh mở): nhánh `::ffff:` có một ca canh trên cả hai bản vá.
    checked = await validate_url("https://[::ffff:8.8.8.8]/", resolver=_never_called())

    assert checked.ips == ("::ffff:808:808",)


# ── Lớp 2 ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("url", ["file:///etc/passwd", "gopher://h/", "ftp://h/", "h/x"])
async def test_rejects_scheme(url: str) -> None:
    assert (await _rejected(url, _never_called())).reason == "scheme"


@pytest.mark.parametrize(
    "url", ["http://redis:6379/", "http://litellm:4000/v1/models", "https://h:8080/"]
)
async def test_rejects_port_before_resolving(url: str) -> None:
    assert (await _rejected(url, _never_called())).reason == "port"


@pytest.mark.parametrize(
    "url", ["https://u@h/", "https://u:p@h/", "https://u:@h/", "https://:p@h/"]
)
async def test_rejects_userinfo(url: str) -> None:
    assert (await _rejected(url, _never_called())).reason == "userinfo"


@pytest.mark.parametrize("url", ["http:///x", "http://./", "http://0177.0.0.1/"])
async def test_rejects_empty_or_unparseable_host(url: str) -> None:
    assert (await _rejected(url, _never_called())).reason == "host"


# ── Lớp 3 ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "result",
    [socket.gaierror(socket.EAI_NONAME, "Name or service not known"), [], ["not-an-ip"]],
    ids=["gaierror", "empty", "garbage"],
)
async def test_rejects_when_dns_fails_or_is_empty(result: Sequence[str] | Exception) -> None:
    assert (await _rejected("https://example.com/", FakeResolver(result))).reason == "dns"


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "[::1]",
        "0.0.0.0",
        "[::]",
        "169.254.169.254",
        "10.0.0.1",
        "172.18.0.5",
        "192.168.1.1",
        "100.64.0.1",
        "224.0.0.1",
        "[ff02::1]",
        "[fe80::1]",
        "[fc00::1]",
        "[::ffff:127.0.0.1]",
        "[::ffff:100.64.0.1]",
        "[::ffff:169.254.169.254]",
    ],
)
async def test_rejects_non_public_ip_literal_without_resolving(host: str) -> None:
    exc = await _rejected(f"http://{host}/", _never_called())

    assert exc.reason == "address"
    _assert_no_ip_leak(exc, [host.strip("[]")])


@pytest.mark.parametrize(
    ("url", "resolved"),
    [
        # IP dạng lạ là **tên** với `httpx.URL` ⇒ phải đi qua resolve (T-6.2 Cạm bẫy ③).
        ("https://2130706433/", ["127.0.0.1"]),
        ("https://0x7f.1/", ["127.0.0.1"]),
        ("https://127.1/", ["127.0.0.1"]),
        ("https://127.0.0.1.nip.io/", ["127.0.0.1"]),
        ("http://localhost./", ["::1", "127.0.0.1"]),
    ],
)
async def test_rejects_name_resolving_to_non_public_ip(url: str, resolved: list[str]) -> None:
    resolver = FakeResolver(resolved)

    exc = await _rejected(url, resolver)

    assert exc.reason == "address"
    assert len(resolver.calls) == 1
    _assert_no_ip_leak(exc, resolved)


@pytest.mark.parametrize(
    ("url", "resolved"),
    [
        ("http://redis/", "172.18.0.5"),
        ("http://redis./", "172.18.0.5"),
        ("http://postgres/", "172.18.0.2"),
        ("http://litellm/", "172.18.0.3"),
        ("http://minio/", "172.18.0.4"),
        ("http://api/", "172.18.0.7"),
    ],
)
async def test_rejects_docker_service_name_at_layer_3(url: str, resolved: str) -> None:
    # Cổng mặc định: `redis:6379` đã chết ở lớp 2 (cổng) trước khi DNS được hỏi.
    # Resolver được gọi với tên đã chuẩn hoá ⇒ ca này chứng minh lớp 3, không phải lớp 2.
    resolver = FakeResolver([resolved])

    exc = await _rejected(url, resolver)

    assert exc.reason == "address"
    assert resolver.calls == [(httpx.URL(url).host.rstrip("."), 80)]
    _assert_no_ip_leak(exc, [resolved])


async def test_rejects_when_any_resolved_address_is_private() -> None:
    # Địa chỉ công khai đứng ĐẦU: một bản chỉ kiểm `infos[0]` sẽ nhận URL này.
    resolved = [PUBLIC_V4, "10.0.0.7"]

    exc = await _rejected("https://mixed.example/", FakeResolver(resolved))

    assert exc.reason == "address"
    _assert_no_ip_leak(exc, resolved)


# ── T-6.3: nối tới IP đã kiểm + lớp 4 ─────────────────────────────────────────
#
# Đo ở chỗ socket được mở: `connect_tcp` của `httpcore` (host đối số) và
# `start_tls` (`server_hostname`). Không dùng `MockTransport` — nó thay đúng tầng
# đang được kiểm, nên một transport resolve lại tên vẫn xanh (Cạm bẫy ①).


def _http(status: int, location: str | None = None) -> bytes:
    head = f"HTTP/1.1 {status} X\r\nContent-Length: 2\r\n"
    if location is not None:
        head += f"Location: {location}\r\n"
    return head.encode() + b"\r\nok"


class _Stream(httpcore.AsyncMockStream):
    def __init__(self, network: FakeNetwork, ip: str) -> None:
        super().__init__([])
        self._network, self._ip, self._sent = network, ip, b""

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self._sent += buffer

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        if not self._sent:
            return b""
        sent, self._sent = self._sent, b""
        path = sent.split(b" ", 2)[1].decode()
        self._network.requests.append((self._ip, sent))
        return self._network.routes[(self._ip, path)]

    async def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore.AsyncNetworkStream:
        self._network.tls_names.append(server_hostname)
        return self


class FakeNetwork:
    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], bytes] = {}
        self.unreachable: set[str] = set()
        self.connects: list[str] = []
        self.tls_names: list[str | None] = []
        self.requests: list[tuple[str, bytes]] = []

    def connect(self, host: str) -> _Stream:
        self.connects.append(host)
        if host in self.unreachable:
            raise httpcore.ConnectError("unreachable")
        return _Stream(self, host)


@pytest.fixture
def network(monkeypatch: pytest.MonkeyPatch) -> FakeNetwork:
    fake = FakeNetwork()

    async def connect_tcp(_backend: object, host: str, port: int, **_: object) -> _Stream:
        return fake.connect(host)

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


def _resolver_for(table: dict[str, list[str]]) -> Callable[[str, int], Awaitable[Sequence[str]]]:
    async def resolve(host: str, port: int) -> Sequence[str]:
        return table[host]

    return resolve


async def test_rebinding_connects_to_checked_ip_and_resolves_once(network: FakeNetwork) -> None:
    resolver = SequenceResolver([PUBLIC_V4], ["127.0.0.1"])
    network.routes[(PUBLIC_V4, "/a")] = _http(200)
    network.routes[(PUBLIC_V4, "/b")] = _http(200)
    checked = await validate_url("https://rebind.example/", resolver=resolver)

    async with pinned_client(checked, timeout=5) as client:
        await client.get("https://rebind.example/a")
        await client.get("https://rebind.example/b")

    assert network.connects and set(network.connects) == {PUBLIC_V4}
    assert network.tls_names and set(network.tls_names) == {"rebind.example"}
    assert resolver.calls == 1


async def test_host_header_and_sni_carry_ascii_name_and_ip_does_not_leak(
    network: FakeNetwork,
) -> None:
    network.routes[(PUBLIC_V4, "/x")] = _http(500)
    checked = await validate_url("https://Bücher.Example./", resolver=FakeResolver([PUBLIC_V4]))

    async with pinned_client(checked, timeout=5) as client:
        response = await client.get("https://bücher.example/x")

    assert network.connects == [PUBLIC_V4]
    assert network.tls_names == ["xn--bcher-kva.example"]
    assert b"\r\nhost: xn--bcher-kva.example\r\n" in network.requests[0][1].lower()
    # `response.request` là request gốc mang tên ⇒ IP không vào thông điệp lỗi.
    with pytest.raises(httpx.HTTPStatusError) as info:
        response.raise_for_status()
    assert PUBLIC_V4 not in str(info.value)


@pytest.mark.parametrize(
    "url", ["https://other.example/", "http://pinned.example/", "https://pinned.example:80/"]
)
async def test_pinned_client_refuses_other_host(network: FakeNetwork, url: str) -> None:
    checked = await validate_url("https://pinned.example/", resolver=FakeResolver([PUBLIC_V4]))

    async with pinned_client(checked, timeout=5) as client:
        with pytest.raises(UnsafeUrlError) as info:
            await client.get(url)

    assert info.value.reason == "host"
    assert network.connects == []


async def test_unreachable_checked_ip_falls_back_to_next_checked_ip(network: FakeNetwork) -> None:
    network.unreachable.add("2606:4700:4700::1111")
    network.routes[(PUBLIC_V4, "/")] = _http(200)
    resolver = FakeResolver(["2606:4700:4700::1111", PUBLIC_V4])
    checked = await validate_url("https://dual.example/", resolver=resolver)

    async with pinned_client(checked, timeout=5) as client:
        response = await client.get("https://dual.example/")

    assert response.status_code == 200
    assert network.connects == ["2606:4700:4700::1111", PUBLIC_V4]


def _caps() -> dict[str, int]:
    # T-6.5: `ssrf.py` không còn đọc `Settings` (nó chạy trong `fetcher`); người gọi
    # đọc lúc gọi rồi truyền vào — đúng như ca này làm sau `monkeypatch`.
    return {"max_redirects": settings.MAX_REDIRECTS, "max_bytes": settings.MAX_FETCH_MB << 20}


# ── Lớp 4 ─────────────────────────────────────────────────────────────────────


async def test_redirect_to_metadata_stops_before_second_request(network: FakeNetwork) -> None:
    network.routes[(PUBLIC_V4, "/")] = _http(302, "http://169.254.169.254/latest/meta-data/")

    with pytest.raises(UnsafeUrlError) as info:
        await get_following_redirects(
            "https://public.example/", timeout=5, resolver=FakeResolver([PUBLIC_V4]), **_caps()
        )

    assert info.value.reason == "address"
    assert network.connects == [PUBLIC_V4]


@pytest.mark.parametrize(("redirects", "allowed"), [(2, True), (3, False)])
async def test_redirect_cap_reads_max_redirects_at_call_time(
    network: FakeNetwork, monkeypatch: pytest.MonkeyPatch, redirects: int, allowed: bool
) -> None:
    monkeypatch.setattr(settings, "MAX_REDIRECTS", 2)
    for step in range(redirects):
        # `Location` tương đối — ghép theo URL hiện tại.
        network.routes[(PUBLIC_V4, f"/{step}")] = _http(302, f"/{step + 1}")
    network.routes[(PUBLIC_V4, f"/{redirects}")] = _http(200)
    resolver = FakeResolver([PUBLIC_V4])

    if allowed:
        response = await get_following_redirects(
            "https://loop.example/0", timeout=5, resolver=resolver, **_caps()
        )
        assert response.status_code == 200
    else:
        with pytest.raises(httpx.TooManyRedirects):
            await get_following_redirects(
                "https://loop.example/0", timeout=5, resolver=resolver, **_caps()
            )
    assert len(network.connects) == min(redirects, 2) + 1
    # Mỗi bước chạy lại `validate_url()`.
    assert len(resolver.calls) == len(network.connects)


async def test_redirect_to_other_host_drops_credentials(network: FakeNetwork) -> None:
    network.routes[(PUBLIC_V4, "/")] = _http(302, "https://b.example/")
    network.routes[(PUBLIC_V4_B, "/")] = _http(200)
    resolver = _resolver_for({"a.example": [PUBLIC_V4], "b.example": [PUBLIC_V4_B]})

    await get_following_redirects(
        "https://a.example/",
        headers={"Authorization": "Bearer k", "x-api-key": "k", "X-Trace": "t"},
        timeout=5,
        resolver=resolver,
        **_caps(),
    )

    first, second = (sent.lower() for _, sent in network.requests)
    assert b"authorization:" in first and b"x-api-key:" in first
    assert b"authorization:" not in second and b"x-api-key:" not in second
    assert b"x-trace: t" in second
    assert b"\r\nhost: b.example\r\n" in second
