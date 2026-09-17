"""Cloudflare Turnstile (§11.6, RR-1) — T-2.6.

Bốn nhóm, tách ra vì chúng hỏng theo bốn kiểu khác nhau:

1. **Công tắc** — `TURNSTILE_SECRET` rỗng phải là "tắt" và chỉ là "tắt". Hỏng
   theo chiều này thì dev không đăng ký được; hỏng theo chiều kia thì
   production chạy không captcha (Cạm bẫy T-2.6).
2. **Hình dạng request gửi đi** — thiếu `secret`, sai tên field, hay quên
   `remoteip` thì Cloudflare trả `invalid-input-secret` và mọi lần đăng ký đều
   `400`, kể cả của người thật.
3. **Đọc kết quả** — `success` là boolean; `ket_qua.get("success")` mà so lỏng
   sẽ nhận `"false"` (chuỗi) là đạt.
4. **Không hỏi được** — timeout, 5xx, body rác. Cả ba phải ra `503`, KHÔNG
   phải cho qua (xem docstring `app/core/turnstile.py`).

`httpx.MockTransport` chứ không phải stub đặt lên `_hoi_cloudflare`: đường thật
đi qua việc dựng form, `raise_for_status`, `resp.json()` — đúng ba chỗ dễ sai
nhất — nên một stub ở tầng trên sẽ kiểm phần đã đúng sẵn.
"""

from __future__ import annotations

from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import SecretStr

from app.config.settings import settings
from app.core import turnstile as mod
from app.core.errors import ApiError, ApiErrorCode
from app.core.turnstile import da_bat, kiem_turnstile

SECRET_GIA = "0x-secret-cua-test-khong-phai-secret-that"
TOKEN_GIA = "0.mot-token-gia-cua-test"


@pytest.fixture
def bat_turnstile(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bật Turnstile bằng cách gán thẳng vào `settings` (đúng lối `test_generate.py`).

    `da_bat()` đọc `settings` lúc **gọi**, nên không cần nạp lại module nào.
    """
    monkeypatch.setattr(settings, "TURNSTILE_SECRET", SecretStr(SECRET_GIA))


def _dat_transport(monkeypatch: pytest.MonkeyPatch, handler: object) -> list[httpx.Request]:
    """Bơm `MockTransport` vào `_tao_client` và ghi lại mọi request đã gửi."""
    da_gui: list[httpx.Request] = []

    def _bat(request: httpx.Request) -> httpx.Response:
        da_gui.append(request)
        return handler(request)  # type: ignore[operator]

    monkeypatch.setattr(
        mod,
        "_tao_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(_bat)),
    )
    return da_gui


def _tra_json(body: dict[str, object], status_code: int = 200):  # noqa: ANN202 - helper nội bộ
    return lambda _request: httpx.Response(status_code, json=body)


# ═══════════════════════════ 1. Công tắc ════════════════════════════════════


def test_secret_rong_thi_da_bat_la_false() -> None:
    assert da_bat() is False


def test_secret_chi_co_khoang_trang_van_la_tat(monkeypatch: pytest.MonkeyPatch) -> None:
    """`"   "` là rỗng. Một `.env` viết `TURNSTILE_SECRET=   ` không được phép
    bật captcha lên với một secret trắng — Cloudflare sẽ từ chối tất cả."""
    monkeypatch.setattr(settings, "TURNSTILE_SECRET", SecretStr("   "))
    assert da_bat() is False


async def test_tat_thi_khong_goi_cloudflare_va_khong_doi_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DoD dòng 3: `TURNSTILE_SECRET=` rỗng → đăng ký được (không có token)."""
    da_gui = _dat_transport(monkeypatch, _tra_json({"success": False}))
    await kiem_turnstile(None, remote_ip="1.2.3.4")
    assert da_gui == []


@pytest.mark.usefixtures("bat_turnstile")
async def test_bat_thi_da_bat_la_true() -> None:
    assert da_bat() is True


# ═══════════════════ 2. Hình dạng request gửi đi ════════════════════════════


@pytest.mark.usefixtures("bat_turnstile")
async def test_gui_dung_url_va_ba_field_cua_cloudflare(monkeypatch: pytest.MonkeyPatch) -> None:
    da_gui = _dat_transport(monkeypatch, _tra_json({"success": True}))

    await kiem_turnstile(TOKEN_GIA, remote_ip="203.0.113.7")

    assert len(da_gui) == 1
    req = da_gui[0]
    assert str(req.url) == settings.TURNSTILE_VERIFY_URL
    assert req.method == "POST"
    form = parse_qs(req.content.decode())
    assert form[mod._FIELD_SECRET] == [SECRET_GIA]
    assert form[mod._FIELD_RESPONSE] == [TOKEN_GIA]
    assert form[mod._FIELD_REMOTEIP] == ["203.0.113.7"]


@pytest.mark.usefixtures("bat_turnstile")
async def test_khong_biet_ip_thi_bo_han_field_remoteip(monkeypatch: pytest.MonkeyPatch) -> None:
    """`remoteip` là tuỳ chọn của Cloudflare — gửi chuỗi rỗng thì nó từ chối cả
    request, nên "không biết" phải là "không gửi", không phải "gửi rỗng"."""
    da_gui = _dat_transport(monkeypatch, _tra_json({"success": True}))

    await kiem_turnstile(TOKEN_GIA, remote_ip=None)

    assert mod._FIELD_REMOTEIP not in da_gui[0].content.decode()


@pytest.mark.usefixtures("bat_turnstile")
async def test_token_bi_cat_khoang_trang_truoc_khi_gui(monkeypatch: pytest.MonkeyPatch) -> None:
    da_gui = _dat_transport(monkeypatch, _tra_json({"success": True}))

    await kiem_turnstile(f"  {TOKEN_GIA}  ", remote_ip=None)

    assert parse_qs(da_gui[0].content.decode())[mod._FIELD_RESPONSE] == [TOKEN_GIA]


# ═══════════════════════ 3. Đọc kết quả ═════════════════════════════════════


@pytest.mark.usefixtures("bat_turnstile")
async def test_success_true_thi_cho_qua(monkeypatch: pytest.MonkeyPatch) -> None:
    _dat_transport(monkeypatch, _tra_json({"success": True, "error-codes": []}))
    await kiem_turnstile(TOKEN_GIA)  # không raise là đạt


@pytest.mark.usefixtures("bat_turnstile")
async def test_success_false_thi_400_turnstile_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    """DoD dòng 2: token giả → 400. Body là bản ghi THẬT mà Cloudflare trả về
    cho khoá thử `2x0000…AA` (đo 2026-09-17 từ trong container `api`)."""
    _dat_transport(
        monkeypatch,
        _tra_json({"error-codes": ["invalid-input-response"], "success": False, "messages": []}),
    )

    with pytest.raises(ApiError) as exc:
        await kiem_turnstile(TOKEN_GIA)

    assert exc.value.status_code == 400
    assert exc.value.code is ApiErrorCode.TURNSTILE_FAILED


@pytest.mark.usefixtures("bat_turnstile")
async def test_success_la_chuoi_false_khong_duoc_coi_la_dat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`"false"` là chuỗi, và chuỗi khác rỗng thì truthy. Phép so phải là
    `is True`, không phải `if ket_qua.get("success")`."""
    _dat_transport(monkeypatch, _tra_json({"success": "false"}))

    with pytest.raises(ApiError) as exc:
        await kiem_turnstile(TOKEN_GIA)

    assert exc.value.status_code == 400


@pytest.mark.usefixtures("bat_turnstile")
async def test_thieu_han_truong_success_thi_tu_choi(monkeypatch: pytest.MonkeyPatch) -> None:
    _dat_transport(monkeypatch, _tra_json({"error-codes": ["internal-error"]}))

    with pytest.raises(ApiError) as exc:
        await kiem_turnstile(TOKEN_GIA)

    assert exc.value.code is ApiErrorCode.TURNSTILE_FAILED


@pytest.mark.usefixtures("bat_turnstile")
async def test_error_codes_khong_ro_ri_ra_response(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`invalid-input-secret` nói cho người gọi biết secret của mình hỏng —
    §20. Nó thuộc về log, không thuộc về response."""
    _dat_transport(
        monkeypatch, _tra_json({"success": False, "error-codes": ["invalid-input-secret"]})
    )

    with (
        caplog.at_level("WARNING", logger="app.core.turnstile"),
        pytest.raises(ApiError) as exc,
    ):
        await kiem_turnstile(TOKEN_GIA)

    assert "invalid-input-secret" not in str(exc.value.detail)
    assert "invalid-input-secret" not in str(exc.value.details)
    assert "invalid-input-secret" in caplog.text


@pytest.mark.usefixtures("bat_turnstile")
async def test_khong_bao_gio_log_secret(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """DoD chung §15: "Không log secret, key". `form` chứa `secret`, nên mọi
    dòng log của module này phải tránh in nó — kể cả dòng log lỗi."""
    _dat_transport(monkeypatch, _tra_json({"success": False, "error-codes": ["x"]}))

    with caplog.at_level("DEBUG", logger="app.core.turnstile"), pytest.raises(ApiError):
        await kiem_turnstile(TOKEN_GIA)

    assert SECRET_GIA not in caplog.text


# ═════════════════ 4. Thiếu token / không hỏi được ══════════════════════════


@pytest.mark.usefixtures("bat_turnstile")
@pytest.mark.parametrize("token", [None, "", "   "])
async def test_thieu_token_thi_400_va_KHONG_goi_cloudflare(
    monkeypatch: pytest.MonkeyPatch, token: str | None
) -> None:
    """DoD dòng 1: không kèm token → 400 (không phải 422).

    Phần "không gọi Cloudflare" quan trọng ngang phần mã lỗi: đường ngược lại
    biến endpoint thành một cách bắt server của mình gọi ra Internet bằng mỗi
    request rác.
    """
    da_gui = _dat_transport(monkeypatch, _tra_json({"success": True}))

    with pytest.raises(ApiError) as exc:
        await kiem_turnstile(token)

    assert exc.value.status_code == 400
    assert exc.value.code is ApiErrorCode.TURNSTILE_FAILED
    assert da_gui == []


@pytest.mark.usefixtures("bat_turnstile")
async def test_cloudflare_5xx_thi_503_chu_khong_cho_qua(monkeypatch: pytest.MonkeyPatch) -> None:
    _dat_transport(monkeypatch, lambda _r: httpx.Response(502, text="bad gateway"))

    with pytest.raises(ApiError) as exc:
        await kiem_turnstile(TOKEN_GIA)

    assert exc.value.status_code == 503
    assert exc.value.code is ApiErrorCode.SERVICE_UNAVAILABLE


@pytest.mark.usefixtures("bat_turnstile")
async def test_cloudflare_400_thi_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """Đo được trên stack thật: body rỗng → Cloudflare trả **HTTP 400**, không
    phải 200 kèm `error-codes`. Một `400` từ Cloudflare là lỗi phía mình
    (request dựng sai), không phải phán quyết về người dùng — nên nó là `503`,
    không phải `400 TURNSTILE_FAILED`."""
    _dat_transport(monkeypatch, lambda _r: httpx.Response(400, text="Bad Request"))

    with pytest.raises(ApiError) as exc:
        await kiem_turnstile(TOKEN_GIA)

    assert exc.value.status_code == 503


@pytest.mark.usefixtures("bat_turnstile")
async def test_dut_mang_thi_503(monkeypatch: pytest.MonkeyPatch) -> None:
    def _no(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("khong noi duoc (gia lap)")

    _dat_transport(monkeypatch, _no)

    with pytest.raises(ApiError) as exc:
        await kiem_turnstile(TOKEN_GIA)

    assert exc.value.status_code == 503


@pytest.mark.usefixtures("bat_turnstile")
async def test_body_khong_phai_json_object_thi_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """Một proxy chen giữa trả `"ok"` hoặc `[]`: `raise_for_status` qua được,
    và `ket_qua.get(...)` sẽ nổ thành `500` nếu không chặn ở đây."""
    _dat_transport(monkeypatch, _tra_json(["khong phai object"]))  # type: ignore[arg-type]

    with pytest.raises(ApiError) as exc:
        await kiem_turnstile(TOKEN_GIA)

    assert exc.value.status_code == 503


@pytest.mark.usefixtures("bat_turnstile")
async def test_body_khong_parse_duoc_json_thi_503(monkeypatch: pytest.MonkeyPatch) -> None:
    _dat_transport(monkeypatch, lambda _r: httpx.Response(200, text="<html>loi</html>"))

    with pytest.raises(ApiError) as exc:
        await kiem_turnstile(TOKEN_GIA)

    assert exc.value.status_code == 503
