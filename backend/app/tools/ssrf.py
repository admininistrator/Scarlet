"""Kiểm một URL do người dùng gửi rồi nối tới đúng IP đã kiểm — T-6.2, T-6.3.

KH tham chiếu: §12.1, §12.2 lớp 2–4, §12.5 C23 · S10, RR-3 · CLAUDE.md A5 ·
NQ-134 ①.

`validate_url()` là lớp 2 (hình dạng URL) + lớp 3 (mọi IP sau khi resolve) của
§12.2. Nó **không** mở kết nối nào: nó trả `CheckedUrl` mang các IP đã kiểm, và
transport của T-6.3 nối thẳng tới đúng các IP ấy thay vì để `httpx` resolve lại
(C23 — DNS rebinding). Gọi hàm này rồi đưa URL gốc cho một client thường là
kiểm xong vứt đi.

Đường BYOK (NQ-134 ①) không có lớp 1: `api` / `worker` ở mạng `internal`, nên
hai lớp ở đây là tất cả những gì đứng giữa một base URL người dùng gõ và
`redis:6379`.

Ba chỗ dễ viết sai, đều đã đo (tasks.md T-6.2, Cạm bẫy):

* **Không cờ `ipaddress` nào một mình đủ.** `100.64.0.1` có `is_private` lẫn
  `is_global` đều `False`; `224.0.0.1` có `is_global = True`. Vì vậy CGNAT và
  multicast là vế riêng, và **không** dùng `is_global` (một vế `not is_global`
  sẽ che mất hai vế kia khỏi kiểm ngược).
* **Địa chỉ bọc IPv4 (`::ffff:a.b.c.d`) mở ra trước khi hỏi cờ.** Trên 3.12 mọi
  `::ffff:x` là `is_reserved` (nằm trong `::/8`) — chặn được nhưng là chặn tình
  cờ; còn `::ffff:100.64.0.1` lại `is_global`. Hỏi cờ trên phần IPv4 mới đúng
  luật IPv4.
* **IP dạng lạ không phải việc của bộ phân tích.** `2130706433`, `0x7f.1`,
  `127.1` với `httpx.URL` là **tên**, và `getaddrinfo` ra `127.0.0.1`. Mọi host
  không phải IP chữ đều đi qua resolve — không bao giờ "không parse được thì coi
  là tên an toàn".

Cổng và scheme dưới đây là luật của §12.2, **không** phải núm chỉnh: đưa ra
`.env` là cho phép mở `6379`.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Literal

import httpx

from app.config.settings import settings

# §12.2 lớp 2 — luật, không phải cấu hình (xem docstring module).
_SCHEMES = frozenset({"http", "https"})
_PORTS = frozenset({80, 443})
_DEFAULT_PORTS = {"http": 80, "https": 443}

# §12.2 lớp 3 — RFC 6598. `ipaddress` không xếp dải này vào `is_private`.
_CGNAT = ipaddress.ip_network("100.64.0.0/10")

Reason = Literal["scheme", "port", "userinfo", "host", "dns", "address"]
Resolver = Callable[[str, int], Awaitable[Sequence[str]]]
IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

# Thông điệp cố định theo mã: không chép host, không chép IP — thông điệp này
# có thể tới tay người dùng (T-S.19b) và tới log.
_MESSAGES: dict[Reason, str] = {
    "scheme": "URL bị từ chối: chỉ nhận http/https",
    "port": "URL bị từ chối: chỉ nhận cổng 80/443",
    "userinfo": "URL bị từ chối: không được chứa thông tin đăng nhập",
    "host": "URL bị từ chối: host không hợp lệ",
    "dns": "URL bị từ chối: không resolve được tên miền",
    "address": "URL bị từ chối: tên miền trỏ tới địa chỉ không công khai",
}


class UnsafeUrlError(Exception):
    """Một URL bị từ chối. `reason` là mã cố định; T-S.19b đổi nó thành `400`."""

    def __init__(self, reason: Reason) -> None:
        super().__init__(_MESSAGES[reason])
        self.reason: Reason = reason


@dataclass(frozen=True)
class CheckedUrl:
    """URL đã qua lớp 2–3. `ips` theo thứ tự `getaddrinfo`, đã bỏ trùng —
    T-6.3 ghim đúng danh sách này, không resolve lại."""

    scheme: str
    host: str  # chữ thường, không dấu chấm cuối, dạng ASCII (IDNA)
    port: int
    ips: tuple[str, ...]


async def _system_resolver(host: str, port: int) -> list[str]:
    # `loop.getaddrinfo` chạy trong executor — `socket.getaddrinfo` chặn event loop.
    # Family để trống ⇒ cả A lẫn AAAA.
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def _normalized_host(url: httpx.URL) -> str:
    # Dạng ASCII (`raw_host`, `xn--…`) — `url.host` trả dạng Unicode.
    host = url.raw_host.decode("ascii").lower()
    return host[:-1] if host.endswith(".") else host


def _is_public(ip: IpAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or ip in _CGNAT
    )


async def validate_url(url: str, *, resolver: Resolver = _system_resolver) -> CheckedUrl:
    """Lớp 2 + 3 của §12.2. Ném `UnsafeUrlError` nếu URL không được phép nối tới."""
    # Lớp 2 — cùng bộ phân tích transport T-6.3 dùng để quay số.
    try:
        parsed = httpx.URL(url)
    except httpx.InvalidURL:
        raise UnsafeUrlError("host") from None

    scheme = parsed.scheme
    if scheme not in _SCHEMES:
        raise UnsafeUrlError("scheme")
    if parsed.userinfo:
        raise UnsafeUrlError("userinfo")

    host = _normalized_host(parsed)
    if not host:
        raise UnsafeUrlError("host")

    port = parsed.port or _DEFAULT_PORTS[scheme]
    if port not in _PORTS:
        raise UnsafeUrlError("port")

    # Lớp 3.
    try:
        ips: list[IpAddress] = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            ips = [ipaddress.ip_address(raw) for raw in await resolver(host, port)]
        except (OSError, UnicodeError, ValueError):
            # `gaierror` là `OSError`; nhãn > 63 ký tự ném `UnicodeError`; resolver
            # trả thứ không phải IP ⇒ `ValueError`. Không chắc thì đóng.
            raise UnsafeUrlError("dns") from None
        if not ips:
            raise UnsafeUrlError("dns") from None

    # **Mọi** địa chỉ: một tên trả cả IP công khai lẫn IP riêng vẫn bị từ chối,
    # vì không biết transport sẽ nối tới cái nào.
    if not all(_is_public(ip) for ip in ips):
        raise UnsafeUrlError("address")

    return CheckedUrl(
        scheme=scheme,
        host=host,
        port=port,
        ips=tuple(dict.fromkeys(str(ip) for ip in ips)),
    )


# ---------------------------------------------------------------------------
# T-6.3 — nối tới IP đã kiểm (§12.2 "DNS rebinding", C23) + lớp 4 (redirect).
# ---------------------------------------------------------------------------


class PinnedTransport(httpx.AsyncBaseTransport):
    """Transport cho **một** host đã qua `validate_url()`.

    Mỗi request đổi host của URL thành một IP trong `checked.ips` — `httpcore`
    nối socket tới IP ấy, không resolve lại (C23) — và mang tên miền ở hai chỗ:
    header `Host` và `sni_hostname` (chứng chỉ được kiểm theo **tên**, `verify`
    mặc định). Request gốc không bị sửa: `AsyncClient` gán `response.request`
    bằng nó, nên IP không vào thông điệp `raise_for_status()` hay lỗi của SDK.

    Một transport một host: pool của `httpcore` khoá theo IP, nên hai tên chung
    một IP (CDN) không được chung transport — kết nối TLS đã kiểm cho tên này.
    """

    def __init__(self, checked: CheckedUrl) -> None:
        self._checked = checked
        self._inner = httpx.AsyncHTTPTransport(trust_env=False)
        netloc = f"[{checked.host}]" if ":" in checked.host else checked.host
        if checked.port != _DEFAULT_PORTS[checked.scheme]:
            netloc += f":{checked.port}"
        self._host_header = netloc

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        target = (url.scheme, _normalized_host(url), url.port or _DEFAULT_PORTS.get(url.scheme))
        checked = self._checked
        if target != (checked.scheme, checked.host, checked.port):
            # Host khác host đã kiểm: từ chối, không âm thầm nối.
            raise UnsafeUrlError("host")

        headers = httpx.Headers(request.headers)
        headers["Host"] = self._host_header
        extensions = {**request.extensions, "sni_hostname": checked.host}
        last_error: httpx.ConnectError | None = None
        for ip in checked.ips:
            pinned = httpx.Request(
                request.method,
                url.copy_with(host=ip),
                headers=headers,
                stream=request.stream,
                extensions=extensions,
            )
            try:
                return await self._inner.handle_async_request(pinned)
            except httpx.ConnectError as exc:
                # IP này không nối được (vd. AAAA trong container không có IPv6)
                # ⇒ thử IP đã kiểm kế tiếp, như `socket.create_connection`.
                last_error = exc
        assert last_error is not None  # `ips` không bao giờ rỗng
        raise last_error

    async def aclose(self) -> None:
        await self._inner.aclose()


def pinned_client(checked: CheckedUrl, *, timeout: httpx.Timeout | float) -> httpx.AsyncClient:
    """Client cho một URL đã kiểm — dùng thẳng làm `http_client=` của `AsyncOpenAI`.

    Không theo redirect (lớp 4 là `get_following_redirects`); `trust_env=False`
    để `HTTP(S)_PROXY` của môi trường không bẻ đường đi qua chỗ chưa kiểm.
    """
    return httpx.AsyncClient(
        transport=PinnedTransport(checked),
        follow_redirects=False,
        trust_env=False,
        timeout=timeout,
    )


async def get_following_redirects(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | float,
    resolver: Resolver = _system_resolver,
) -> httpx.Response:
    """GET theo redirect — lớp 4 của §12.2, cho chỗ gọi **cần** theo (P6 `fetcher`).

    Mỗi bước: `validate_url()` lại từ đầu và một transport mới cho host mới.
    Quá `settings.MAX_REDIRECTS` lần chuyển ⇒ `httpx.TooManyRedirects`.
    """
    # ponytail: đọc trọn body mỗi bước; P6 thêm trần MAX_FETCH_MB (C25) khi cần stream.
    request = httpx.Request("GET", url, headers=headers)
    # Đọc lúc gọi, không làm mặc định tham số (Cạm bẫy ③ của T-6.3).
    for _ in range(settings.MAX_REDIRECTS + 1):
        checked = await validate_url(str(request.url), resolver=resolver)
        async with pinned_client(checked, timeout=timeout) as client:
            response = await client.send(request)
        next_request = response.next_request
        if next_request is None:
            return response
        # `httpx` tự bỏ `Authorization` khi đổi origin; `x-api-key` (auth_style
        # của catalog, T-2.14) thì nó không biết.
        if _normalized_host(next_request.url) != _normalized_host(request.url):
            next_request.headers.pop("x-api-key", None)
        request = next_request
    raise httpx.TooManyRedirects("Vượt số lần chuyển hướng cho phép", request=request)
