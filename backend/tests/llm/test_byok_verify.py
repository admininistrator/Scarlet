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

KHOA_GIA = "sk-khong-phai-khoa-that-cua-ai-1234"
TEN_PROVIDER = "provider-cua-test"


def _provider(**doi: object) -> Provider:
    """Provider mẫu — chỉ những field mà `byok_verify` đọc mới có nghĩa ở đây."""
    mac_dinh: dict[str, object] = {
        "label": "Provider cua test",
        "base_url": "https://vi-du.test/v1",
        "availability": "always",
        "byok_supported": True,
        "cost_reporting": "exact",
        "auth_style": "bearer",
        "verify_path": "/models",
    }
    return Provider.model_validate(mac_dinh | doi)


def _dat_transport(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> list[httpx.Request]:
    da_gui: list[httpx.Request] = []

    def _bat(request: httpx.Request) -> httpx.Response:
        da_gui.append(request)
        return handler(request)

    monkeypatch.setattr(
        mod, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(_bat))
    )
    return da_gui


def _tra(status_code: int) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _request: httpx.Response(status_code, json={"data": []})


# ═════════════════════ 1. Hình dạng request gửi đi ══════════════════════════


async def test_url_la_base_url_noi_verify_path(monkeypatch: pytest.MonkeyPatch) -> None:
    da_gui = _dat_transport(monkeypatch, _tra(200))
    await verify_key(TEN_PROVIDER, _provider(), KHOA_GIA)
    assert str(da_gui[0].url) == "https://vi-du.test/v1/models"


async def test_auth_style_bearer_gan_header_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    da_gui = _dat_transport(monkeypatch, _tra(200))
    await verify_key(TEN_PROVIDER, _provider(auth_style="bearer"), KHOA_GIA)
    assert da_gui[0].headers["authorization"] == f"Bearer {KHOA_GIA}"


async def test_auth_style_x_api_key_gan_header_x_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C44: hai kiểu xác thực khác nhau, và dùng nhầm kiểu thì khoá đúng vẫn
    bị từ chối."""
    da_gui = _dat_transport(monkeypatch, _tra(200))
    await verify_key(TEN_PROVIDER, _provider(auth_style="x-api-key"), KHOA_GIA)
    assert da_gui[0].headers["x-api-key"] == KHOA_GIA
    assert "authorization" not in da_gui[0].headers


async def test_khoa_khong_di_vao_query_string(monkeypatch: pytest.MonkeyPatch) -> None:
    """C20: một khoá trong URL là một khoá trong access log của nginx."""
    da_gui = _dat_transport(monkeypatch, _tra(200))
    await verify_key(TEN_PROVIDER, _provider(), KHOA_GIA)
    assert KHOA_GIA not in str(da_gui[0].url)


# ═══════════════════════ 2. Đọc câu trả lời ═════════════════════════════════


@pytest.mark.parametrize("ma", [200, 204])
async def test_2xx_la_ALIVE(monkeypatch: pytest.MonkeyPatch, ma: int) -> None:
    _dat_transport(monkeypatch, _tra(ma))
    assert await verify_key(TEN_PROVIDER, _provider(), KHOA_GIA) is VerifyOutcome.ALIVE


@pytest.mark.parametrize("ma", [401, 403])
async def test_401_403_la_REJECTED(monkeypatch: pytest.MonkeyPatch, ma: int) -> None:
    """Hai mã này — và chỉ hai — nghĩa là "provider nói khoá này không dùng
    được"."""
    _dat_transport(monkeypatch, _tra(ma))
    assert await verify_key(TEN_PROVIDER, _provider(), KHOA_GIA) is VerifyOutcome.REJECTED


# ═════════════ 3. Không hỏi được ≠ khoá sai (xem docstring module) ══════════


@pytest.mark.parametrize("ma", [404, 429, 500, 502])
async def test_ma_khac_la_VerifyUnavailable(monkeypatch: pytest.MonkeyPatch, ma: int) -> None:
    """`404` là `verify_path` sai (lỗi catalog), `429` là bị siết nhịp, `5xx`
    là provider hỏng — không mã nào nói gì về khoá."""
    _dat_transport(monkeypatch, _tra(ma))
    with pytest.raises(VerifyUnavailable):
        await verify_key(TEN_PROVIDER, _provider(), KHOA_GIA)


async def test_mang_hong_la_VerifyUnavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def _no(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("khong noi duoc (gia lap)")

    _dat_transport(monkeypatch, _no)
    with pytest.raises(VerifyUnavailable):
        await verify_key(TEN_PROVIDER, _provider(), KHOA_GIA)


async def test_log_cua_ca_mang_hong_khong_chua_khoa(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """C20 — `logger.exception` in cả traceback của `httpx`."""

    def _no(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("khong noi duoc (gia lap)")

    _dat_transport(monkeypatch, _no)
    with caplog.at_level(logging.INFO), pytest.raises(VerifyUnavailable):
        await verify_key(TEN_PROVIDER, _provider(), KHOA_GIA)
    assert KHOA_GIA not in caplog.text


# ═══════════════════════ 4. C42 / C44 — thiếu thông tin ═════════════════════


async def test_thieu_verify_path_thi_SKIPPED_va_khong_goi_ai(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """C42. Không có `verify_path` thì không có gì để gọi — và **không** được
    im lặng: `verified_at` sẽ là NULL, người vận hành phải biết vì sao."""
    da_gui = _dat_transport(monkeypatch, _tra(200))
    with caplog.at_level(logging.WARNING):
        ket_cuc = await verify_key(TEN_PROVIDER, _provider(verify_path=None), KHOA_GIA)
    assert ket_cuc is VerifyOutcome.SKIPPED
    assert da_gui == []
    assert TEN_PROVIDER in caplog.text


async def test_auth_style_query_thi_SKIPPED_chu_khong_doan_ten_tham_so(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Xem docstring `app/llm/byok_verify.py`: đoán một tên tham số query là
    dựng sẵn đường rò của C20."""
    da_gui = _dat_transport(monkeypatch, _tra(200))
    with caplog.at_level(logging.WARNING):
        ket_cuc = await verify_key(TEN_PROVIDER, _provider(auth_style="query"), KHOA_GIA)
    assert ket_cuc is VerifyOutcome.SKIPPED
    assert da_gui == []
    assert "query" in caplog.text
