"""`fetch_url` — client của `worker` tới `fetcher` (T-6.5).

`httpx.MockTransport` thay `fetcher`: thứ được kiểm là hợp đồng phía `worker`
(trần đọc lúc gọi, timeout lồng nhau, hỏng ⇒ dữ liệu). Hành vi thật của
`fetcher` (lớp 1–4, trần byte, charset) là test trong image `fetcher` và DoD.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.config.settings import settings
from app.tools import fetch_url as mod
from app.tools.fetch_url import FetchResult, fetch_url


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


async def test_sends_caps_read_at_call_time_and_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MAX_FETCH_MB", 3)
    monkeypatch.setattr(settings, "FETCH_TIMEOUT_S", 7)
    monkeypatch.setattr(settings, "MAX_REDIRECTS", 2)
    monkeypatch.setattr(settings, "FETCHER_BASE_URL", "http://fetcher.test:8080")
    reply = {
        "ok": True,
        "final_url": "https://a.example/",
        "title": "T",
        "text": "chữ",
        "fetch_method": "httpx",
        "reason": None,
    }
    sent = _set_transport(monkeypatch, lambda _: httpx.Response(200, json=reply))

    result = await fetch_url("https://a.example/")

    assert result == FetchResult(**reply)
    request, timeout = sent[0]
    assert str(request.url) == "http://fetcher.test:8080/fetch"
    assert json.loads(request.content) == {
        "url": "https://a.example/",
        "max_bytes": 3 * 1024 * 1024,
        "timeout_s": 7,
        "max_redirects": 2,
    }
    # B-71: trần của client lớn hơn trần gửi cho `fetcher`.
    assert timeout > 7


async def test_fetcher_refusal_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = {
        "ok": False,
        "final_url": None,
        "title": None,
        "text": "",
        "fetch_method": "httpx",
        "reason": "address",
    }
    _set_transport(monkeypatch, lambda _: httpx.Response(200, json=reply))

    assert (await fetch_url("http://169.254.169.254/")).reason == "address"


def _raises(exc: type[httpx.TransportError]) -> object:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc("x", request=request)

    return handler


@pytest.mark.parametrize(
    ("handler", "reason"),
    [
        (_raises(httpx.ConnectError), "fetcher_unavailable"),
        (_raises(httpx.ReadTimeout), "timeout"),
        (lambda _: httpx.Response(500, text="boom"), "fetcher_unavailable"),
        (lambda _: httpx.Response(200, text="khong-phai-json"), "fetcher_unavailable"),
        (lambda _: httpx.Response(200, json={"ok": "yes"}), "fetcher_unavailable"),
        (lambda _: httpx.Response(200, json={"ok": True, "text": 3}), "fetcher_unavailable"),
    ],
    ids=["connect", "timeout", "500", "not-json", "ok-not-bool", "text-not-str"],
)
async def test_failures_become_data(
    monkeypatch: pytest.MonkeyPatch, handler: object, reason: str
) -> None:
    _set_transport(monkeypatch, handler)

    result = await fetch_url("https://a.example/")

    assert (result.ok, result.reason) == (False, reason)
