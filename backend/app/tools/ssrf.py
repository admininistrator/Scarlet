"""Kiểm một URL do người dùng gửi trước khi backend nối tới nó — T-6.2.

KH tham chiếu: §12.1, §12.2 lớp 2–3, §12.5 C23 · S10, RR-3 · CLAUDE.md A5 ·
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

    host = parsed.raw_host.decode("ascii").lower()
    if host.endswith("."):
        host = host[:-1]
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
