"""Kiểm khoá BYOK còn sống trước khi lưu (§10.5, C42, C44) — T-2.14.

Bốn nhóm, theo bốn thứ có thể sai khác nhau:

1. **Hình dạng request gửi đi** — sai `base_url + verify_path` thì mọi khoá đều
   `404`; sai cách gắn khoá (C44 `auth_style`) thì mọi khoá đều bị từ chối, kể
   cả khoá đúng, và người dùng sẽ đi tạo khoá mới để chữa một lỗi của mình.
2. **Đọc câu trả lời** — ba kết cục của §10.5, và ranh giới giữa chúng.
3. **Không hỏi được ≠ khoá sai** — nhóm này là lý do `VerifyUnavailable` tồn
   tại; gộp nó vào `REJECTED` là nói dối người dùng khi mạng hỏng.
4. **C42/C44** — catalog thiếu thông tin thì lưu mà KHÔNG kiểm, có cảnh báo.

`httpx.MockTransport` chứ không stub đặt lên `verify_key`: đường thật đi qua
việc ghép URL, dựng header và đọc `status_code` — đúng ba chỗ dễ sai nhất.
Cùng lối `tests/core/test_turnstile.py`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import httpx
import pytest

from app.config.catalog import Provider
from app.llm import byok_verify as mod
from app.llm.byok_verify import VerifyOutcome, VerifyUnavailable, verify_key

FAKE_KEY = "sk-khong-phai-khoa-that-cua-ai-1234"
PROVIDER_NAME = "provider-cua-test"


def _provider(**overrides: object) -> Provider:
    """Provider mẫu — chỉ những field mà `byok_verify` đọc mới có nghĩa ở đây."""
    default: dict[str, object] = {
        "label": "Provider cua test",
        "base_url": "https://vi-du.test/v1",
        "availability": "always",
        "byok_supported": True,
        "cost_reporting": "exact",
        "auth_style": "bearer",
        "verify_path": "/models",
    }
    return Provider.model_validate(default | overrides)


def _set_transport(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> list[httpx.Request]:
    sent: list[httpx.Request] = []

    def _capture(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return handler(request)

    monkeypatch.setattr(
        mod, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(_capture))
    )
    return sent


def _respond_with(status_code: int) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _request: httpx.Response(status_code, json={"data": []})


# ═════════════════════ 1. Hình dạng request gửi đi ══════════════════════════


async def test_url_is_base_url_joined_with_verify_path(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _set_transport(monkeypatch, _respond_with(200))
    await verify_key(PROVIDER_NAME, _provider(), FAKE_KEY)
    assert str(sent[0].url) == "https://vi-du.test/v1/models"


async def test_auth_style_bearer_sets_authorization_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = _set_transport(monkeypatch, _respond_with(200))
    await verify_key(PROVIDER_NAME, _provider(auth_style="bearer"), FAKE_KEY)
    assert sent[0].headers["authorization"] == f"Bearer {FAKE_KEY}"


async def test_auth_style_x_api_key_sets_x_api_key_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C44: hai kiểu xác thực khác nhau, và dùng nhầm kiểu thì khoá đúng vẫn
    bị từ chối."""
    sent = _set_transport(monkeypatch, _respond_with(200))
    await verify_key(PROVIDER_NAME, _provider(auth_style="x-api-key"), FAKE_KEY)
    assert sent[0].headers["x-api-key"] == FAKE_KEY
    assert "authorization" not in sent[0].headers


async def test_catalog_extra_headers_travel_with_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**B-166** — Anthropic đòi `anthropic-version`, thiếu là `400` rồi `503`.

    Đo trên API thật ở T-2.14: `GET https://api.anthropic.com/v1/models` trả
    `400 "anthropic-version: header is required"` với **cả** hai `auth_style`.
    Catalog nay khai được header ấy, và đây là phép kiểm rằng nó đi kèm thật.
    """
    sent = _set_transport(monkeypatch, _respond_with(200))
    provider = _provider(auth_style="x-api-key", extra_headers={"anthropic-version": "2023-06-01"})

    await verify_key(PROVIDER_NAME, provider, FAKE_KEY)

    assert sent[0].headers["anthropic-version"] == "2023-06-01"
    assert sent[0].headers["x-api-key"] == FAKE_KEY


async def test_extra_headers_can_NOT_override_auth_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`extra_headers` merge TRƯỚC, header mang khoá ghi đè SAU — thứ tự là hợp đồng.

    Một `Authorization` gõ nhầm vào catalog mà thắng được credential thật
    nghĩa là mọi phép kiểm khoá từ đó trở đi đo một khoá khác.
    """
    sent = _set_transport(monkeypatch, _respond_with(200))
    provider = _provider(
        auth_style="bearer", extra_headers={"Authorization": "Bearer khoa-cua-nguoi-khac"}
    )

    await verify_key(PROVIDER_NAME, provider, FAKE_KEY)

    assert sent[0].headers["authorization"] == f"Bearer {FAKE_KEY}"


async def test_key_never_goes_into_query_string(monkeypatch: pytest.MonkeyPatch) -> None:
    """C20: một khoá trong URL là một khoá trong access log của nginx."""
    sent = _set_transport(monkeypatch, _respond_with(200))
    await verify_key(PROVIDER_NAME, _provider(), FAKE_KEY)
    assert FAKE_KEY not in str(sent[0].url)


# ═══════════════════════ 2. Đọc câu trả lời ═════════════════════════════════


@pytest.mark.parametrize("code", [200, 204])
async def test_2xx_is_ALIVE(monkeypatch: pytest.MonkeyPatch, code: int) -> None:
    _set_transport(monkeypatch, _respond_with(code))
    assert await verify_key(PROVIDER_NAME, _provider(), FAKE_KEY) is VerifyOutcome.ALIVE


@pytest.mark.parametrize("code", [401, 403])
async def test_401_403_is_REJECTED(monkeypatch: pytest.MonkeyPatch, code: int) -> None:
    """Hai mã này — và chỉ hai — nghĩa là "provider nói khoá này không dùng
    được"."""
    _set_transport(monkeypatch, _respond_with(code))
    assert await verify_key(PROVIDER_NAME, _provider(), FAKE_KEY) is VerifyOutcome.REJECTED


# ═════════════ 3. Không hỏi được ≠ khoá sai (xem docstring module) ══════════


@pytest.mark.parametrize("code", [404, 429, 500, 502])
async def test_other_status_is_VerifyUnavailable(
    monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    """`404` là `verify_path` sai (lỗi catalog), `429` là bị siết nhịp, `5xx`
    là provider hỏng — không mã nào nói gì về khoá."""
    _set_transport(monkeypatch, _respond_with(code))
    with pytest.raises(VerifyUnavailable):
        await verify_key(PROVIDER_NAME, _provider(), FAKE_KEY)


async def test_network_failure_is_VerifyUnavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def _no(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("khong noi duoc (gia lap)")

    _set_transport(monkeypatch, _no)
    with pytest.raises(VerifyUnavailable):
        await verify_key(PROVIDER_NAME, _provider(), FAKE_KEY)


async def test_network_failure_log_does_not_contain_key(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """C20 — `logger.exception` in cả traceback của `httpx`."""

    def _no(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("khong noi duoc (gia lap)")

    _set_transport(monkeypatch, _no)
    with caplog.at_level(logging.INFO), pytest.raises(VerifyUnavailable):
        await verify_key(PROVIDER_NAME, _provider(), FAKE_KEY)
    assert FAKE_KEY not in caplog.text


# ═══════════════════════ 4. C42 / C44 — thiếu thông tin ═════════════════════


async def test_missing_verify_path_is_SKIPPED_and_calls_nobody(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """C42. Không có `verify_path` thì không có gì để gọi — và **không** được
    im lặng: `verified_at` sẽ là NULL, người vận hành phải biết vì sao."""
    sent = _set_transport(monkeypatch, _respond_with(200))
    with caplog.at_level(logging.WARNING):
        outcome = await verify_key(PROVIDER_NAME, _provider(verify_path=None), FAKE_KEY)
    assert outcome is VerifyOutcome.SKIPPED
    assert sent == []
    assert PROVIDER_NAME in caplog.text


async def test_auth_style_query_is_SKIPPED_not_guessing_param_name(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Xem docstring `app/llm/byok_verify.py`: đoán một tên tham số query là
    dựng sẵn đường rò của C20."""
    sent = _set_transport(monkeypatch, _respond_with(200))
    with caplog.at_level(logging.WARNING):
        outcome = await verify_key(PROVIDER_NAME, _provider(auth_style="query"), FAKE_KEY)
    assert outcome is VerifyOutcome.SKIPPED
    assert sent == []
    assert "query" in caplog.text
