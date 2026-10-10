"""`sandbox_client` — client của `worker` tới `sandbox` (T-7.3).

`httpx.MockTransport` thay `sandbox`: thứ được kiểm là hợp đồng phía `worker`
(trần đọc lúc gọi, timeout lồng nhau, hỏng ⇒ dữ liệu). Hành vi thật (setpriv,
giết, dọn) là `sandbox/test_server.py` trong image `sandbox` và DoD.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.config.settings import settings
from app.tools import sandbox_client as mod
from app.tools.sandbox_client import ExecResult, execute

REPLY = {
    "exit_code": 0,
    "stdout": "2\n",
    "stderr": "",
    "files_out": {"a.txt": "eA=="},
    "timeout": False,
    "error": None,
}


def _set_transport(
    monkeypatch: pytest.MonkeyPatch, handler: object
) -> list[tuple[httpx.Request, float]]:
    sent: list[tuple[httpx.Request, float]] = []

    def client(timeout: float) -> httpx.AsyncClient:
        def capture(request: httpx.Request) -> httpx.Response:
            sent.append((request, timeout))
            return handler(request)  # type: ignore[operator]

        return httpx.AsyncClient(transport=httpx.MockTransport(capture))

    monkeypatch.setattr(mod, "_client", client)
    return sent


async def test_sends_caps_read_at_call_time_and_decodes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SANDBOX_TIMEOUT_S", 7)
    monkeypatch.setattr(settings, "SANDBOX_CLIENT_GRACE_S", 2)
    monkeypatch.setattr(settings, "MAX_SKILL_OUTPUT_MB", 3)
    monkeypatch.setattr(settings, "SANDBOX_PID_LIMIT", 9)
    sent = _set_transport(monkeypatch, lambda _: httpx.Response(200, json=REPLY))

    result = await execute({"main.py": "print(1+1)"}, ["python", "main.py"])

    assert result == ExecResult(ok=True, exit_code=0, stdout="2\n", files_out={"a.txt": b"x"})
    request, timeout = sent[0]
    assert request.url.path == "/exec"
    assert json.loads(request.content) == {
        "files": {"main.py": "print(1+1)"},
        "cmd": ["python", "main.py"],
        "timeout_s": 7,
        "max_output_bytes": 3 * 1024 * 1024,
        "max_processes": 9,
    }
    assert timeout == 9  # trong nổ trước (C28)


def test_nested_timeouts_with_real_settings() -> None:
    # B-71 / C28: SANDBOX_TIMEOUT_S < trần client < GENERATE_TIMEOUT_S.
    client_cap = settings.SANDBOX_TIMEOUT_S + settings.SANDBOX_CLIENT_GRACE_S
    assert settings.SANDBOX_TIMEOUT_S < client_cap < settings.GENERATE_TIMEOUT_S


async def test_sandbox_error_code_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = {**REPLY, "files_out": {}, "error": "output_too_large"}
    _set_transport(monkeypatch, lambda _: httpx.Response(200, json=reply))

    result = await execute({}, ["true"])

    assert result.ok is False
    assert result.reason == "output_too_large"
    assert result.stdout == "2\n"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, json={"exit_code": None, "error": "internal"}),
        httpx.Response(200, text="khong phai json"),
        httpx.Response(200, json={**REPLY, "files_out": {"a": "khong-phai-base64!"}}),
        httpx.Response(200, json={**REPLY, "timeout": "no"}),
    ],
)
async def test_bad_reply_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, response: httpx.Response
) -> None:
    _set_transport(monkeypatch, lambda _: response)

    assert await execute({}, ["true"]) == ExecResult(ok=False, reason="sandbox_unavailable")


async def test_dead_socket_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SANDBOX_BASE_URL", "unix:///nonexistent/sandbox.sock")

    assert await execute({}, ["true"]) == ExecResult(ok=False, reason="sandbox_unavailable")
