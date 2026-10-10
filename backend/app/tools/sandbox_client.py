"""Client của `worker` tới service `sandbox` (§13.3, T-7.3). Chưa là tool —
T-7.7a bọc nó thành `run_code` trong registry.

KH tham chiếu: §13.3, ADR-09, C28, C29 · NQ-147 (Q-P7-1) · B-71.

`sandbox` chạy `network_mode: none` ⇒ gọi qua Unix socket trên volume chung
(Phụ lục C cách a). Nó không đọc `.env`, nên mọi trần đi trong body, đọc
`Settings` **lúc gọi** (lối `fetch_url.py`).

**Hai timeout lồng nhau** (C28, B-71): trần client = `SANDBOX_TIMEOUT_S` +
`SANDBOX_CLIENT_GRACE_S` — cái trong nổ trước và trả `timeout: true` thật.

Hỏng là dữ liệu: `sandbox` chết / trả rác ⇒ `ExecResult(ok=False,
reason="sandbox_unavailable")`, không ném.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config.settings import settings

logger = logging.getLogger(__name__)

# Host bất kỳ: transport `uds` bỏ qua nó, chỉ đường dẫn có nghĩa.
_EXEC_URL = "http://sandbox/exec"
_BYTES_PER_MB = 1024 * 1024


@dataclass(frozen=True, slots=True)
class ExecResult:
    ok: bool
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    files_out: dict[str, bytes] = field(default_factory=dict)
    timeout: bool = False
    reason: str | None = None


def _client(timeout: float) -> httpx.AsyncClient:
    """Tách riêng để test bơm `httpx.MockTransport`."""
    transport = httpx.AsyncHTTPTransport(uds=settings.SANDBOX_BASE_URL.removeprefix("unix://"))
    return httpx.AsyncClient(transport=transport, timeout=timeout, trust_env=False)


def _parse(data: Any) -> ExecResult:
    if not isinstance(data, dict):
        raise ValueError("thân trả về sai hình")
    exit_code, files_out, error = data.get("exit_code"), data.get("files_out"), data.get("error")
    if not (
        (exit_code is None or type(exit_code) is int)
        and isinstance(data.get("stdout"), str)
        and isinstance(data.get("stderr"), str)
        and isinstance(files_out, dict)
        and all(isinstance(v, str) for v in files_out.values())
        and isinstance(data.get("timeout"), bool)
        and (error is None or isinstance(error, str))
    ):
        raise ValueError("thân trả về sai kiểu")
    return ExecResult(
        ok=error is None,
        exit_code=exit_code,
        stdout=data["stdout"],
        stderr=data["stderr"],
        # `binascii.Error` là `ValueError`.
        files_out={k: base64.b64decode(v, validate=True) for k, v in files_out.items()},
        timeout=data["timeout"],
        reason=error,
    )


async def execute(files: dict[str, str], cmd: list[str]) -> ExecResult:
    """Ghi `files` (tên phẳng) vào thư mục tạm của lượt rồi chạy `cmd` trong đó."""
    body = {
        "files": files,
        "cmd": cmd,
        "timeout_s": settings.SANDBOX_TIMEOUT_S,
        "max_output_bytes": settings.MAX_SKILL_OUTPUT_MB * _BYTES_PER_MB,
        "max_processes": settings.SANDBOX_PID_LIMIT,
    }
    timeout = settings.SANDBOX_TIMEOUT_S + settings.SANDBOX_CLIENT_GRACE_S
    try:
        async with _client(timeout) as client:
            response = await client.post(_EXEC_URL, json=body)
        response.raise_for_status()
        return _parse(response.json())
    except (httpx.HTTPError, ValueError) as exc:
        # Không ghi code — thứ model sinh.
        logger.warning("sandbox hong: reason=sandbox_unavailable ly_do=%s", type(exc).__name__)
        return ExecResult(ok=False, reason="sandbox_unavailable")
