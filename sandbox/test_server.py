"""`server.py` (T-7.3) — chạy TRONG image `sandbox`, cùng cap / tmpfs / uid của
service (`docker compose run --rm --no-deps sandbox python -m pytest`).

Đây là test hành vi của server (lượt, dọn, trần). Bộ phòng vệ S11 / C27 — mỗi
lớp đỏ được — là `test_isolation.py` của T-7.4.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import threading

import pytest
import server

CAPS = {"timeout_s": 10, "max_output_bytes": 1024, "max_processes": 32}


def _py(code: str, **caps: object) -> dict[str, object]:
    return server.run(files={"main.py": code}, cmd=["python", "main.py"], **{**CAPS, **caps})


def _code_pids() -> list[str]:
    """Tiến trình còn sống (không tính zombie) của uid code."""
    alive = []
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            with open(f"/proc/{pid}/status") as f:
                status = dict(line.split(":", 1) for line in f if ":" in line)
        except FileNotFoundError:
            continue
        if status["Uid"].split()[0] == str(server.CODE_UID) and not status["State"].startswith("Z"):
            alive.append(pid)
    return alive


def test_runs_as_code_uid_and_leaves_nothing() -> None:
    result = _py("import os; print(1 + 1); print(os.getuid(), sorted(os.environ))")

    assert result["exit_code"] == 0
    assert result["stdout"].splitlines()[0] == "2"
    assert result["stdout"].splitlines()[1].startswith(f"{server.CODE_UID} ")
    assert "JWT_SECRET" not in result["stdout"]
    assert result["files_out"] == {} and result["error"] is None
    assert os.listdir(server.WORK) == []


def test_orphan_that_escaped_the_session_is_killed() -> None:
    # Con `setsid` thoát nhóm/phiên của lượt (B-402 ②) — `killpg` không với tới.
    result = _py(
        "import os, time\nif os.fork() == 0:\n    os.setsid(); time.sleep(300)\nprint('ok')"
    )

    assert result["stdout"] == "ok\n"
    assert _code_pids() == []


def test_timeout_kills() -> None:
    result = _py("while True: pass", timeout_s=1)

    assert result["timeout"] is True
    assert result["exit_code"] == -9
    assert _code_pids() == []


def test_files_out_only_from_run_dir_and_next_run_sees_nothing() -> None:
    first = _py(
        "import os\n"
        "open('a.txt', 'w').write('x')\n"
        "open('/work/b.txt', 'w').write('y')\n"
        "open('/dev/shm/c', 'w').write('z')\n"
        "os.symlink('/etc/hostname', 'link')\n"
        "os.mkdir('locked'); open('locked/d', 'w').write('w'); os.chmod('locked', 0)\n"
    )
    assert first["exit_code"] == 0, first["stderr"]
    assert first["files_out"] == {"a.txt": base64.b64encode(b"x").decode()}

    second = _py(
        "import json, os\n"
        "print(json.dumps([os.listdir('.'), os.listdir('/work'), os.listdir('/dev/shm')]))"
    )
    cwd, work, shm = json.loads(second["stdout"])
    assert cwd == ["main.py"]
    assert len(work) == 1 and work[0].startswith("run-")  # chỉ thư mục của chính lượt này
    assert shm == []


def test_output_over_limit_is_refused_without_reading() -> None:
    result = _py("open('big.bin', 'wb').write(b'0' * 11)", max_output_bytes=10)

    assert result["error"] == "output_too_large"
    assert result["files_out"] == {}


@pytest.mark.parametrize("name", ["../x", "a/b", "", ".."])
def test_file_names_must_be_flat(name: str) -> None:
    with pytest.raises(ValueError):
        server.parse({"files": {name: ""}, "cmd": ["true"], **CAPS})


def test_peer_with_code_uid_is_refused() -> None:
    path = os.path.join(server.WORK, "t.sock")
    srv = server.Server(path, server.Handler)
    os.chmod(path, 0o666)
    thread = threading.Thread(target=srv.serve_forever)
    thread.start()
    probe = (
        "import socket, sys\n"
        "s = socket.socket(socket.AF_UNIX); s.connect(sys.argv[1])\n"
        "try:\n"
        "    s.sendall(b'POST /exec HTTP/1.0\\r\\nContent-Length: 2\\r\\n\\r\\n{}')\n"
        "    print(len(s.recv(100)))\n"
        "except ConnectionError:\n"  # server đóng trước khi đọc
        "    print(0)\n"
    )
    try:
        as_code = subprocess.run(
            [*server._SETPRIV, "python", "-c", probe, path], capture_output=True, text=True
        )
        as_root = subprocess.run(["python", "-c", probe, path], capture_output=True, text=True)
    finally:
        srv.shutdown()
        thread.join()
        srv.server_close()
        os.unlink(path)

    assert as_code.stdout == "0\n"  # đóng, không một byte trả lời
    assert int(as_root.stdout) > 0  # 422 bad_request
