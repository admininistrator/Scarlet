"""`sandbox` — chạy code do model/skill sinh, qua Unix socket (§13.3, T-7.3).

ADR-09 / Phụ lục C cách (a): container `network_mode: none`, `worker` gọi
`POST /exec` trên socket ở volume chung. Không đọc `.env` (C27): mọi trần tới
trong từng request, `worker` đọc `Settings` lúc gọi (lối `fetcher`).

**Danh tính tách** (NQ-147 / Q-P7-1): server chạy root nhưng chỉ còn
SETUID/SETGID, và **không bao giờ** chạy code trong tiến trình của nó — mỗi lượt
`setpriv` hạ code xuống uid 65534, 0 cap. Root không có CAP_KILL /
CAP_DAC_OVERRIDE (B-402 ①), nên giết và xoá đều chạy **dưới chính uid code**
qua một tiến trình phụ `setpriv`:

- giết: `kill -KILL -1` dưới uid code — mọi tiến trình của uid đó, kể cả con
  `setsid` đã thoát khỏi nhóm/phiên của lượt (B-402 ②); server root khác uid
  nên không bị. PID 1 (`tini`) gặt con mồ côi.
- dọn: mọi chỗ uid code ghi được (đo T-7.3: `/work`, `/dev/shm`, `/dev/mqueue`,
  cộng SysV IPC) — lượt sau, có thể của người khác, không thấy gì của lượt này.

Chạy **tuần tự** (RR-2): server một luồng, không `ThreadingMixIn` — lượt sau
chờ ở hàng đợi `listen` của socket. Peer có uid = uid code bị đóng ngay
(`SO_PEERCRED`, B-402 ③): socket phải `0666` cho `worker`, nên code cũng
`connect` được.

Không bao giờ ném ra socket: mọi ngả hỏng ⇒ JSON có `error`.
"""

from __future__ import annotations

import base64
import contextlib
import json
import logging
import os
import resource
import socket
import socketserver
import stat
import struct
import subprocess
import sys
import tempfile
from http.server import BaseHTTPRequestHandler
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("sandbox")

# `nobody` — uid của code (Q-P7-1), khác uid 0 của server.
CODE_UID = CODE_GID = 65534
WORK = "/work"
_SETPRIV = [
    "setpriv",
    f"--reuid={CODE_UID}",
    f"--regid={CODE_GID}",
    "--clear-groups",
    "--inh-caps=-all",
    "--no-new-privs",
    "--",
]
# Dưới uid code. `chmod` trước: code tự khoá thư mục của nó (0500) thì `find
# -delete` không vào được. `/work` chính nó và thư mục lượt (của root, `/work`
# sticky) không xoá được ⇒ server `rmdir` thư mục lượt sau đó.
_WIPE = (
    "chmod -R u+rwX /work /dev/shm /dev/mqueue 2>/dev/null;"
    " find /work /dev/shm /dev/mqueue -mindepth 1 -delete 2>/dev/null;"
    " ipcrm --all 2>/dev/null; true"
)


def _as_code(script: str) -> None:
    """Chạy `sh -c script` dưới uid code. Bị code giết giữa chừng (cùng uid, trước
    khi nó kịp `kill -1`) ⇒ chạy lại."""
    while subprocess.run([*_SETPRIV, "sh", "-c", script], env=_env("/")).returncode < 0:
        pass


def _env(home: str) -> dict[str, str]:
    # Tạo mới, không kế thừa môi trường của server (C27). HOME = thư mục lượt:
    # `matplotlib` ghi cache ở `$HOME/.config` (rootfs read-only).
    return {
        "PATH": os.environ["PATH"],
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "HOME": home,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
    }


def _check_name(name: Any) -> str:
    # Phẳng: không `/`, không `..` — thư mục lượt là nơi duy nhất ghi vào.
    if not isinstance(name, str) or name in ("", ".", "..") or "/" in name or "\0" in name:
        raise ValueError
    return name


def parse(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ValueError
    files, cmd = body.get("files"), body.get("cmd")
    timeout_s, max_bytes, max_procs = (
        body.get("timeout_s"),
        body.get("max_output_bytes"),
        body.get("max_processes"),
    )
    if not (
        isinstance(files, dict)
        and all(isinstance(v, str) for v in files.values())
        and isinstance(cmd, list)
        and cmd
        and all(isinstance(c, str) for c in cmd)
        and type(timeout_s) in (int, float)
        and timeout_s > 0
        and type(max_bytes) is int
        and max_bytes > 0
        and type(max_procs) is int
        and max_procs > 0
    ):
        raise ValueError
    return {
        "files": {_check_name(k): v for k, v in files.items()},
        "cmd": cmd,
        "timeout_s": float(timeout_s),
        "max_output_bytes": max_bytes,
        "max_processes": max_procs,
    }


def _head(f: Any, limit: int) -> str:
    f.seek(0)
    return f.read(limit).decode("utf-8", errors="replace")


def _collect(run_dir: str, inputs: set[str], limit: int) -> dict[str, str] | None:
    """File thường trong thư mục lượt, trừ file đầu vào và đường có thành phần
    `.` (cache `$HOME/.config`). Chạy SAU khi mọi tiến trình code đã chết — không
    ai đổi cây giữa chừng. Không theo symlink (`/proc/1/environ` của server…).
    Tổng vượt `limit` ⇒ `None`, không đọc byte nào (C29)."""
    found: list[tuple[str, str]] = []
    total = 0
    for root, dirs, names in os.walk(run_dir):  # thư mục code khoá ⇒ bỏ qua
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in names:
            path = os.path.join(root, name)
            rel = os.path.relpath(path, run_dir)
            if name.startswith(".") or rel in inputs:
                continue
            info = os.lstat(path)
            if stat.S_ISREG(info.st_mode):
                found.append((rel, path))
                total += info.st_size
    if total > limit:
        return None
    out: dict[str, str] = {}
    for rel, path in found:
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError:
            continue  # code `chmod 000` file của nó
        with os.fdopen(fd, "rb") as f:
            out[rel] = base64.b64encode(f.read(limit + 1)).decode("ascii")
    return out


def run(
    files: dict[str, str],
    cmd: list[str],
    timeout_s: float,
    max_output_bytes: int,
    max_processes: int,
) -> dict[str, Any]:
    run_dir = tempfile.mkdtemp(dir=WORK, prefix="run-")
    try:
        os.chmod(run_dir, 0o777)  # code (65534) ghi được; vẫn của root
        for name, content in files.items():
            with open(os.path.join(run_dir, name), "x", encoding="utf-8") as f:
                f.write(content)
        # Không tên, chỉ root mở được: code chỉ ghi qua fd 1/2 của nó; trần tmpfs
        # chặn RAM, server chỉ đọc `max_output_bytes` đầu.
        with tempfile.TemporaryFile(dir=WORK) as out, tempfile.TemporaryFile(dir=WORK) as err:
            proc = subprocess.Popen(
                [*_SETPRIV, *cmd],
                cwd=run_dir,
                env=_env(run_dir),
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                start_new_session=True,
                # RLIMIT_NPROC tính theo uid: fork bomb của code dừng ở trần này,
                # dưới `pids_limit` của container ⇒ server còn chỗ `fork` tiến
                # trình phụ để giết nó.
                preexec_fn=lambda: resource.setrlimit(
                    resource.RLIMIT_NPROC, (max_processes, max_processes)
                ),
            )
            timed_out = False
            try:
                proc.wait(timeout_s)
            except subprocess.TimeoutExpired:
                timed_out = True
            # `dash`: `kill -s KILL -1` ⇒ "Illegal option -1", im lặng không giết.
            _as_code("kill -KILL -1")
            exit_code = proc.wait()
            stdout, stderr = _head(out, max_output_bytes), _head(err, max_output_bytes)
        files_out = _collect(run_dir, set(files), max_output_bytes)
    finally:
        _as_code("kill -KILL -1; " + _WIPE)
        try:
            os.rmdir(run_dir)
        except OSError:
            # Còn sót ⇒ `_WIPE` của lượt sau dọn tiếp phần của uid code.
            logger.error("khong xoa duoc thu muc luot")
    return {
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "files_out": files_out or {},
        "timeout": timed_out,
        "error": "output_too_large" if files_out is None else None,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # Mặc định chép `client_address[0]` — rỗng với AF_UNIX.
        logger.info(format, *args)

    def _reply(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/exec":
            return self._reply(404, {"exit_code": None, "error": "not_found"})
        try:
            length = int(self.headers.get("Content-Length", ""))
            request = parse(json.loads(self.rfile.read(length)))
        except ValueError:  # gồm JSON hỏng, Content-Length thiếu
            return self._reply(422, {"exit_code": None, "error": "bad_request"})
        try:
            result = run(**request)
        except Exception:
            logger.exception("exec hong")
            return self._reply(500, {"exit_code": None, "error": "internal"})
        # Không ghi code / stdout: thứ người dùng và model đưa.
        logger.info(
            "exec: exit_code=%s timeout=%s files_out=%d error=%s",
            result["exit_code"],
            result["timeout"],
            len(result["files_out"]),
            result["error"],
        )
        self._reply(200, result)


class Server(socketserver.UnixStreamServer):
    def verify_request(self, request: Any, client_address: Any) -> bool:
        creds = request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _, uid, _ = struct.unpack("3i", creds)
        if uid == CODE_UID:
            logger.warning("tu choi peer uid=%d (uid cua code)", uid)
            return False
        return True

    def handle_error(self, request: Any, client_address: Any) -> None:
        # vd. `worker` hết giờ và đóng socket trước khi nhận trả lời.
        logger.warning("ket noi hong: %s", sys.exc_info()[0].__name__)  # type: ignore[union-attr]


def serve(path: str) -> None:
    with contextlib.suppress(FileNotFoundError):
        os.unlink(path)  # volume sống qua restart (B-402 ④)
    with Server(path, Handler) as server:
        os.chmod(path, 0o666)  # `worker` uid 1000; thư mục vẫn root 0755
        logger.info("nghe %s", path)
        server.serve_forever()


if __name__ == "__main__":
    serve(sys.argv[1])
