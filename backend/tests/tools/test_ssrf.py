"""`app/tools/ssrf.py::validate_url()` — T-6.2 (lớp 2 + 3 của §12.2).

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
from collections.abc import Sequence

import pytest

from app.tools.ssrf import CheckedUrl, UnsafeUrlError, validate_url

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
        ("http://redis/", ["172.18.0.5"]),
        ("https://2130706433/", ["127.0.0.1"]),
        ("https://127.0.0.1.nip.io/", ["127.0.0.1"]),
        ("http://localhost./", ["::1", "127.0.0.1"]),
    ],
)
async def test_rejects_name_resolving_to_non_public_ip(url: str, resolved: list[str]) -> None:
    exc = await _rejected(url, FakeResolver(resolved))

    assert exc.reason == "address"
    _assert_no_ip_leak(exc, resolved)


async def test_rejects_when_any_resolved_address_is_private() -> None:
    # Địa chỉ công khai đứng ĐẦU: một bản chỉ kiểm `infos[0]` sẽ nhận URL này.
    resolved = [PUBLIC_V4, "10.0.0.7"]

    exc = await _rejected("https://mixed.example/", FakeResolver(resolved))

    assert exc.reason == "address"
    _assert_no_ip_leak(exc, resolved)
