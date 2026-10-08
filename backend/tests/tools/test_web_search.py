"""`TavilySearch` — hỏng ⇒ `SearchResult(error=…)`, không bao giờ ném (T-6.1).

`httpx.MockTransport` thay đúng tầng mạng: đường thật vẫn đi qua dựng URL, gắn
khoá, đọc mã trạng thái, parse JSON — cùng lối `tests/llm/test_byok_verify.py`.
Không chạm Internet; hành vi thật (401, chặn 443) là lệnh DoD trong `worker`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable

import httpx
import pytest
from pydantic import SecretStr

from app.config.settings import settings
from app.tools import web_search as mod
from app.tools.web_search import SearchError, SearchHit, TavilySearch

FAKE_KEY = "tvly-khoa-gia-cua-test-0123456789"
QUERY = "cau hoi rieng tu cua nguoi dung ve benh tinh"
BASE = "https://tavily.test"

Handler = Callable[[httpx.Request], httpx.Response | Awaitable[httpx.Response]]


@pytest.fixture(autouse=True)
def _configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TAVILY_API_KEY", SecretStr(FAKE_KEY))
    monkeypatch.setattr(settings, "TAVILY_BASE_URL", BASE)


def _set_transport(monkeypatch: pytest.MonkeyPatch, handler: Handler) -> list[httpx.Request]:
    sent: list[httpx.Request] = []

    async def _capture(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        response = handler(request)
        return await response if isinstance(response, Awaitable) else response

    monkeypatch.setattr(
        mod, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(_capture))
    )
    return sent


def _results(*urls: str) -> dict[str, object]:
    return {
        "results": [{"title": f"T{i}", "url": u, "content": f"C{i}"} for i, u in enumerate(urls)]
    }


async def test_success_keeps_count_and_order(monkeypatch: pytest.MonkeyPatch) -> None:
    urls = ["https://a.example/1", "https://b.example/2", "http://c.example/3"]
    sent = _set_transport(monkeypatch, lambda _: httpx.Response(200, json=_results(*urls)))

    result = await TavilySearch().search(QUERY)

    assert result.error is None
    assert result.results == tuple(SearchHit(f"T{i}", u, f"C{i}") for i, u in enumerate(urls))
    [request] = sent
    assert request.method == "POST"
    assert str(request.url) == f"{BASE}/search"
    assert request.headers["Authorization"] == f"Bearer {FAKE_KEY}"
    assert FAKE_KEY not in str(request.url)
    body = json.loads(request.content)
    assert body == {"query": QUERY, "max_results": settings.WEB_SEARCH_MAX_RESULTS}
    assert FAKE_KEY not in request.content.decode()


async def test_explicit_max_results_is_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _set_transport(monkeypatch, lambda _: httpx.Response(200, json=_results()))
    await TavilySearch().search(QUERY, max_results=2)
    assert json.loads(sent[0].content)["max_results"] == 2


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, SearchError.UNAUTHORIZED),
        (403, SearchError.UNAUTHORIZED),
        (429, SearchError.RATE_LIMITED),
        (432, SearchError.RATE_LIMITED),
        (500, SearchError.UPSTREAM),
        (503, SearchError.UPSTREAM),
    ],
)
async def test_http_error_becomes_code(
    monkeypatch: pytest.MonkeyPatch, status: int, error: SearchError
) -> None:
    _set_transport(
        monkeypatch, lambda _: httpx.Response(status, json={"detail": {"error": "chu cua Tavily"}})
    )
    result = await TavilySearch().search(QUERY)
    assert result.error == error
    assert result.results == ()


async def test_total_timeout_read_at_call_time(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _slow(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(2)
        return httpx.Response(200, json=_results("https://a.example/"))

    _set_transport(monkeypatch, _slow)
    monkeypatch.setattr(settings, "WEB_SEARCH_TIMEOUT_S", 0.05)

    started = time.monotonic()
    result = await TavilySearch().search(QUERY)

    assert result.error == SearchError.TIMEOUT
    assert time.monotonic() - started < 1


async def test_httpx_timeout_becomes_code(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("het gio", request=request)

    _set_transport(monkeypatch, _raise)
    assert (await TavilySearch().search(QUERY)).error == SearchError.TIMEOUT


async def test_dns_failure_becomes_upstream(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("[Errno -2] Name or service not known", request=request)

    _set_transport(monkeypatch, _raise)
    assert (await TavilySearch().search(QUERY)).error == SearchError.UPSTREAM


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"<html>khong phai json"),
        httpx.Response(200, json={"answer": "thieu results"}),
        httpx.Response(200, json={"results": "khong phai danh sach dict"}),
    ],
    ids=["not-json", "missing-results", "wrong-shape"],
)
async def test_bad_json_becomes_upstream(
    monkeypatch: pytest.MonkeyPatch, response: httpx.Response
) -> None:
    _set_transport(monkeypatch, lambda _: response)
    assert (await TavilySearch().search(QUERY)).error == SearchError.UPSTREAM


async def test_empty_key_sends_zero_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _set_transport(monkeypatch, lambda _: httpx.Response(200, json=_results()))
    monkeypatch.setattr(settings, "TAVILY_API_KEY", SecretStr(""))

    result = await TavilySearch().search(QUERY)

    assert result.error == SearchError.NOT_CONFIGURED
    assert sent == []


async def test_only_absolute_http_urls_are_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    urls = [
        "javascript:alert(document.cookie)",
        "JavaScript:alert(1)",
        "/tuong-doi",
        "tuong-doi/khong-gach",
        "data:text/html,<script>x</script>",
        "https://",
        "https://giu.example/a",
    ]
    _set_transport(monkeypatch, lambda _: httpx.Response(200, json=_results(*urls)))

    result = await TavilySearch().search(QUERY)

    assert [hit.url for hit in result.results] == ["https://giu.example/a"]


async def test_key_and_query_never_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    for status in (200, 401, 500):
        _set_transport(monkeypatch, lambda _, s=status: httpx.Response(s, json=_results()))
        await TavilySearch().search(QUERY)

    def _raise(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns hong", request=request)

    _set_transport(monkeypatch, _raise)
    await TavilySearch().search(QUERY)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 3
    assert FAKE_KEY not in caplog.text
    assert QUERY not in caplog.text
