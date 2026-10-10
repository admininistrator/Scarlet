"""T-7.4 — bộ test phòng vệ S11 + C27 của `sandbox`, mỗi lớp đỏ được.

Chạy TRONG image `sandbox` (`docker compose run --rm --no-deps sandbox python -m
pytest`), tức cùng `network_mode` / `read_only` / cap / tmpfs / env của service.
Độc lập với code nó kiểm (như T-2.18, HUONG-DAN-AGENT §2.3): không import
`server.py` — chạy nó như một tiến trình, nói giao thức `POST /exec` qua Unix
socket, rồi kiểm HÀNH VI của container. Mỗi ca khẳng định "code không làm được
X"; kiểm ngược (gỡ đúng lớp ⇒ ca đỏ) ở báo cáo T-7.4, không để lại trong cây.

| Ca | Lớp nó canh |
|---|---|
| `test_no_route_out`, `test_no_dns` | `network_mode: none` (ADR-09) |
| `test_container_env_has_no_scarlet_key` | không `env_file` (C27) |
| `test_code_env_is_built_fresh` | server dựng env mới cho code (C27) |
| `test_only_scratch_dirs_are_writable` | `read_only` + tmpfs `/work` |
| `test_code_cannot_replace_the_socket` | danh tính server ≠ code (Q-P7-1) |
| `test_no_process_outlives_its_run` | giết mọi tiến trình uid code + `tini` gặt |
| `test_infinite_loop_is_killed_within_sandbox_timeout` | trần `timeout_s` (S11, C28) |
"""

from __future__ import annotations

import errno
import http.client
import json
import os
import signal
import socket
import struct
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest

SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.py")
# Cùng thư mục với socket thật (volume `sandbox_socket`, root 0755) — ca danh
# tính kiểm đúng quyền entrypoint đặt. Tên riêng: không đụng `sandbox.sock`.
SOCKET_DIR = "/run/sandbox"
CODE_UID = 65534
CAPS = {"max_output_bytes": 65536, "max_processes": 32}
# Trần đọc của client cho các ca không đo thời gian — server treo ⇒ đỏ, không treo.
READ_TIMEOUT_S = 30
# B-278: monotonic trong container lệch 5–7.5 % ⇒ biên ±10 %.
CLOCK_MARGIN = 0.1

# Đo ở T-7.2 / T-7.4: biến của image `python:3.12-slim` + Dockerfile, `PWD` của
# entrypoint, và hai biến `make test` truyền (`TMPDIR`, `SANDBOX_TIMEOUT_S`).
CONTAINER_ENV = {
    "GPG_KEY",
    "HOME",
    "HOSTNAME",
    "LANG",
    "PATH",
    "PWD",
    "PYTHONDONTWRITEBYTECODE",
    "PYTHONUNBUFFERED",
    "PYTHON_SHA256",
    "PYTHON_VERSION",
    "SANDBOX_TIMEOUT_S",
    "TMPDIR",
}
CODE_ENV = {"HOME", "LANG", "PATH", "PYTHONDONTWRITEBYTECODE", "PYTHONUNBUFFERED"}
# tmpfs: `/work` (compose) và `/dev/shm`, `/dev/mqueue` (mặc định Docker — server
# xoá cả hai sau mỗi lượt).
SCRATCH = ("/work", "/dev/shm", "/dev/mqueue")


@dataclass
class Sandbox:
    path: str
    pid: int


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float) -> None:
        super().__init__("sandbox", timeout=timeout)
        self.path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


@pytest.fixture
def sandbox() -> Iterator[Sandbox]:
    path = os.path.join(SOCKET_DIR, f"test-isolation-{os.getpid()}.sock")
    proc = subprocess.Popen([sys.executable, SERVER, path])
    try:
        deadline = time.monotonic() + 10
        while True:
            try:
                with socket.socket(socket.AF_UNIX) as probe:
                    probe.connect(path)
                break
            except OSError:
                assert proc.poll() is None and time.monotonic() < deadline, "server khong len"
                time.sleep(0.05)
        yield Sandbox(path, proc.pid)
    finally:
        proc.kill()
        proc.wait()
        if os.path.exists(path):
            os.unlink(path)


def _exec(
    box: Sandbox, code: str, *args: str, timeout_s: float = 10, read_timeout: float = READ_TIMEOUT_S
) -> tuple[dict[str, Any], int]:
    """Một lượt `POST /exec`. Trả kết quả và pid của tiến trình đang NGHE socket
    — kernel cấp (`SO_PEERCRED`), code không giả được."""
    body = json.dumps(
        {
            "files": {"main.py": code},
            "cmd": ["python", "main.py", *args],
            "timeout_s": timeout_s,
            **CAPS,
        }
    )
    conn = _UnixHTTPConnection(box.path, read_timeout)
    try:
        conn.connect()
        assert conn.sock is not None
        creds = conn.sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        peer_pid = struct.unpack("3i", creds)[0]
        conn.request("POST", "/exec", body, {"Content-Type": "application/json"})
        response = conn.getresponse()
        assert response.status == 200
        return json.loads(response.read()), peer_pid
    finally:
        conn.close()


def _json_out(box: Sandbox, code: str) -> Any:
    result, _ = _exec(box, code)
    assert result["exit_code"] == 0, result["stderr"]
    return json.loads(result["stdout"])


def test_no_route_out(sandbox: Sandbox) -> None:
    out = _json_out(
        sandbox,
        "import json, socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 53), timeout=5); code = None\n"
        "except OSError as e:\n"
        "    code = e.errno\n"
        "print(json.dumps([code, [name for _, name in socket.if_nameindex()]]))\n",
    )

    assert out == [errno.ENETUNREACH, ["lo"]]


def test_no_dns(sandbox: Sandbox) -> None:
    out = _json_out(
        sandbox,
        "import json, socket\n"
        "try:\n"
        "    socket.getaddrinfo('example.com', 443); code = None\n"
        "except socket.gaierror as e:\n"
        "    code = e.errno\n"
        "print(json.dumps(code))\n",
    )

    assert out is not None  # gaierror, không phải một địa chỉ


def test_container_env_has_no_scarlet_key() -> None:
    # Môi trường compose cấp cho container = của PID 1 (`tini`), server kế thừa
    # nó. `env_file` ⇒ JWT_SECRET, DATABASE_URL… hiện ở đây.
    with open("/proc/1/environ", "rb") as f:
        keys = {item.split(b"=", 1)[0].decode() for item in f.read().split(b"\0") if item}

    assert keys <= CONTAINER_ENV, sorted(keys - CONTAINER_ENV)


def test_code_env_is_built_fresh(sandbox: Sandbox) -> None:
    keys = set(_json_out(sandbox, "import json, os; print(json.dumps(sorted(os.environ)))"))

    assert keys <= CODE_ENV, sorted(keys - CODE_ENV)


def test_only_scratch_dirs_are_writable(sandbox: Sandbox) -> None:
    out = _json_out(
        sandbox,
        "import json, os\n"
        "try:\n"
        "    open('/etc/x', 'w'); code = None\n"
        "except OSError as e:\n"
        "    code = e.errno\n"
        "writable = []\n"
        "for root, dirs, _ in os.walk('/'):\n"
        "    if root == '/':\n"
        "        dirs[:] = [d for d in dirs if d not in ('proc', 'sys')]\n"
        "    if os.access(root, os.W_OK):\n"
        "        writable.append(root)\n"
        "print(json.dumps([code, writable]))\n",
    )
    code, writable = out

    assert code == errno.EROFS
    assert "/work" in writable  # phép đo có thấy chỗ ghi được
    outside = [d for d in writable if not any(d == s or d.startswith(s + "/") for s in SCRATCH)]
    assert outside == []


def test_code_cannot_replace_the_socket(sandbox: Sandbox) -> None:
    # T-7.1: cùng uid với server thì code gỡ được socket và dựng listener của
    # nó ⇒ lượt sau của `worker` nói với kẻ khác. Phép thử: sau một lượt code cố
    # gỡ, lượt kế vẫn tới ĐÚNG tiến trình server (pid nghe socket) và chạy được.
    probe, _ = _exec(
        sandbox,
        "import os, socket, sys\n"
        "try:\n"
        "    os.unlink(sys.argv[1])\n"
        "except OSError as e:\n"
        "    print(type(e).__name__)\n"
        "else:\n"
        "    socket.socket(socket.AF_UNIX).bind(sys.argv[1]); print('replaced')\n",
        sandbox.path,
    )
    after, peer_pid = _exec(sandbox, "print('probe')")

    assert probe["stdout"] == "PermissionError\n"
    assert peer_pid == sandbox.pid
    assert after["stdout"] == "probe\n"


def _ps() -> list[list[str]]:
    out = subprocess.run(["ps", "-eo", "stat=,uid="], capture_output=True, text=True, check=True)
    return [line.split() for line in out.stdout.splitlines()]


def test_no_process_outlives_its_run(sandbox: Sandbox) -> None:
    # Một con ở lại nhóm của lượt, một con `setsid` thoát nhóm/phiên (B-402 ②).
    result, _ = _exec(
        sandbox,
        "import os, time\n"
        "for escape in (False, True):\n"
        "    if os.fork() == 0:\n"
        "        if escape:\n"
        "            os.setsid()\n"
        "        time.sleep(300)\n"
        "        os._exit(0)\n"
        "print('ok')\n",
    )
    assert result["stdout"] == "ok\n"

    # `tini` gặt bất đồng bộ — chờ có hạn, rồi khẳng định.
    deadline = time.monotonic() + 2
    while True:
        rows = _ps()
        code_alive = [r for r in rows if r[1] == str(CODE_UID) and not r[0].startswith("Z")]
        zombies = [r for r in rows if r[0].startswith("Z")]
        if not (code_alive or zombies) or time.monotonic() > deadline:
            break
        time.sleep(0.05)

    assert code_alive == []
    assert zombies == []


# Cuối tệp: khi kiểm ngược gỡ trần này, vòng lặp sống tiếp ăn CPU của ca sau.
def test_infinite_loop_is_killed_within_sandbox_timeout(sandbox: Sandbox) -> None:
    # Sandbox không đọc `.env` (C27): `worker` gửi `SANDBOX_TIMEOUT_S` trong từng
    # request; `make test` truyền đúng giá trị của `.env` vào đây (A3).
    raw = os.environ.get("SANDBOX_TIMEOUT_S")
    if not raw:
        pytest.fail("thieu bien SANDBOX_TIMEOUT_S (make test truyen tu .env)")
    limit = float(raw)

    start = time.monotonic()  # mốc tường minh (B-290)
    # Trần đọc của client = mép trên ⇒ server không giết thì ca đỏ ở đó, không treo.
    result, _ = _exec(
        sandbox, "while True: pass", timeout_s=limit, read_timeout=limit * (1 + CLOCK_MARGIN)
    )
    elapsed = time.monotonic() - start

    assert result["timeout"] is True
    assert result["exit_code"] == -signal.SIGKILL
    assert limit * (1 - CLOCK_MARGIN) <= elapsed <= limit * (1 + CLOCK_MARGIN)
