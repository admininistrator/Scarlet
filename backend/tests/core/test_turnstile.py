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

`httpx.MockTransport` chứ không phải stub đặt lên `_ask_cloudflare`: đường thật
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
from app.core.turnstile import is_enabled, verify_turnstile

FAKE_SECRET = "0x-secret-cua-test-khong-phai-secret-that"
FAKE_TOKEN = "0.mot-token-gia-cua-test"


@pytest.fixture
def enable_turnstile(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bật Turnstile bằng cách gán thẳng vào `settings` (đúng lối `test_generate.py`).

    `is_enabled()` đọc `settings` lúc **gọi**, nên không cần nạp lại module nào.
    """
    monkeypatch.setattr(settings, "TURNSTILE_SECRET", SecretStr(FAKE_SECRET))


def _set_transport(monkeypatch: pytest.MonkeyPatch, handler: object) -> list[httpx.Request]:
    """Bơm `MockTransport` vào `_tao_client` và ghi lại mọi request đã gửi."""
    sent: list[httpx.Request] = []

    def _capture(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return handler(request)  # type: ignore[operator]

    monkeypatch.setattr(
        mod,
        "_make_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(_capture)),
    )
    return sent


def _json_response(body: dict[str, object], status_code: int = 200):  # noqa: ANN202 - helper nội bộ
    return lambda _request: httpx.Response(status_code, json=body)


# ═══════════════════════════ 1. Công tắc ════════════════════════════════════


def test_empty_secret_is_enabled_false() -> None:
    assert is_enabled() is False


def test_whitespace_secret_still_means_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """`"   "` là rỗng. Một `.env` viết `TURNSTILE_SECRET=   ` không được phép
    bật captcha lên với một secret trắng — Cloudflare sẽ từ chối tất cả."""
    monkeypatch.setattr(settings, "TURNSTILE_SECRET", SecretStr("   "))
    assert is_enabled() is False


async def test_off_skips_cloudflare_and_needs_no_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DoD dòng 3: `TURNSTILE_SECRET=` rỗng → đăng ký được (không có token)."""
    sent = _set_transport(monkeypatch, _json_response({"success": False}))
    await verify_turnstile(None, remote_ip="1.2.3.4")
    assert sent == []


@pytest.mark.usefixtures("enable_turnstile")
async def test_on_means_is_enabled_true() -> None:
    assert is_enabled() is True


# ═══════════════════ 2. Hình dạng request gửi đi ════════════════════════════


@pytest.mark.usefixtures("enable_turnstile")
async def test_sends_right_url_and_three_cloudflare_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _set_transport(monkeypatch, _json_response({"success": True}))

    await verify_turnstile(FAKE_TOKEN, remote_ip="203.0.113.7")

    assert len(sent) == 1
    req = sent[0]
    assert str(req.url) == settings.TURNSTILE_VERIFY_URL
    assert req.method == "POST"
    form = parse_qs(req.content.decode())
    assert form[mod._FIELD_SECRET] == [FAKE_SECRET]
    assert form[mod._FIELD_RESPONSE] == [FAKE_TOKEN]
    assert form[mod._FIELD_REMOTEIP] == ["203.0.113.7"]


@pytest.mark.usefixtures("enable_turnstile")
async def test_unknown_ip_omits_remoteip_field(monkeypatch: pytest.MonkeyPatch) -> None:
    """`remoteip` là tuỳ chọn của Cloudflare — gửi chuỗi rỗng thì nó từ chối cả
    request, nên "không biết" phải là "không gửi", không phải "gửi rỗng"."""
    sent = _set_transport(monkeypatch, _json_response({"success": True}))

    await verify_turnstile(FAKE_TOKEN, remote_ip=None)

    assert mod._FIELD_REMOTEIP not in sent[0].content.decode()


@pytest.mark.usefixtures("enable_turnstile")
async def test_token_is_stripped_before_sending(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _set_transport(monkeypatch, _json_response({"success": True}))

    await verify_turnstile(f"  {FAKE_TOKEN}  ", remote_ip=None)

    assert parse_qs(sent[0].content.decode())[mod._FIELD_RESPONSE] == [FAKE_TOKEN]


# ═══════════════════════ 3. Đọc kết quả ═════════════════════════════════════


@pytest.mark.usefixtures("enable_turnstile")
async def test_success_true_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_transport(monkeypatch, _json_response({"success": True, "error-codes": []}))
    await verify_turnstile(FAKE_TOKEN)  # không raise là đạt


@pytest.mark.usefixtures("enable_turnstile")
async def test_success_false_is_400_turnstile_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    """DoD dòng 2: token giả → 400. Body là bản ghi THẬT mà Cloudflare trả về
    cho khoá thử `2x0000…AA` (đo 2026-09-17 từ trong container `api`)."""
    _set_transport(
        monkeypatch,
        _json_response(
            {"error-codes": ["invalid-input-response"], "success": False, "messages": []}
        ),
    )

    with pytest.raises(ApiError) as exc:
        await verify_turnstile(FAKE_TOKEN)

    assert exc.value.status_code == 400
    assert exc.value.code is ApiErrorCode.TURNSTILE_FAILED


@pytest.mark.usefixtures("enable_turnstile")
async def test_success_string_false_not_treated_as_passed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`"false"` là chuỗi, và chuỗi khác rỗng thì truthy. Phép so phải là
    `is True`, không phải `if ket_qua.get("success")`."""
    _set_transport(monkeypatch, _json_response({"success": "false"}))

    with pytest.raises(ApiError) as exc:
        await verify_turnstile(FAKE_TOKEN)

    assert exc.value.status_code == 400


@pytest.mark.usefixtures("enable_turnstile")
async def test_missing_success_field_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_transport(monkeypatch, _json_response({"error-codes": ["internal-error"]}))

    with pytest.raises(ApiError) as exc:
        await verify_turnstile(FAKE_TOKEN)

    assert exc.value.code is ApiErrorCode.TURNSTILE_FAILED


@pytest.mark.usefixtures("enable_turnstile")
async def test_error_codes_do_not_leak_into_response(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`invalid-input-secret` nói cho người gọi biết secret của mình hỏng —
    §20. Nó thuộc về log, không thuộc về response."""
    _set_transport(
        monkeypatch, _json_response({"success": False, "error-codes": ["invalid-input-secret"]})
    )

    with (
        caplog.at_level("WARNING", logger="app.core.turnstile"),
        pytest.raises(ApiError) as exc,
    ):
        await verify_turnstile(FAKE_TOKEN)

    assert "invalid-input-secret" not in str(exc.value.detail)
    assert "invalid-input-secret" not in str(exc.value.details)
    assert "invalid-input-secret" in caplog.text


@pytest.mark.usefixtures("enable_turnstile")
async def test_never_logs_secret(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """DoD chung §15: "Không log secret, key". `form` chứa `secret`, nên mọi
    dòng log của module này phải tránh in nó — kể cả dòng log lỗi."""
    _set_transport(monkeypatch, _json_response({"success": False, "error-codes": ["x"]}))

    with caplog.at_level("DEBUG", logger="app.core.turnstile"), pytest.raises(ApiError):
        await verify_turnstile(FAKE_TOKEN)

    assert FAKE_SECRET not in caplog.text


# ═════════════════ 4. Thiếu token / không hỏi được ══════════════════════════


@pytest.mark.usefixtures("enable_turnstile")
@pytest.mark.parametrize("token", [None, "", "   "])
async def test_missing_token_400_and_does_NOT_call_cloudflare(
    monkeypatch: pytest.MonkeyPatch, token: str | None
) -> None:
    """DoD dòng 1: không kèm token → 400 (không phải 422).

    Phần "không gọi Cloudflare" quan trọng ngang phần mã lỗi: đường ngược lại
    biến endpoint thành một cách bắt server của mình gọi ra Internet bằng mỗi
    request rác.
    """
    sent = _set_transport(monkeypatch, _json_response({"success": True}))

    with pytest.raises(ApiError) as exc:
        await verify_turnstile(token)

    assert exc.value.status_code == 400
    assert exc.value.code is ApiErrorCode.TURNSTILE_FAILED
    assert sent == []


@pytest.mark.usefixtures("enable_turnstile")
async def test_cloudflare_5xx_is_503_not_let_through(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_transport(monkeypatch, lambda _r: httpx.Response(502, text="bad gateway"))

    with pytest.raises(ApiError) as exc:
        await verify_turnstile(FAKE_TOKEN)

    assert exc.value.status_code == 503
    assert exc.value.code is ApiErrorCode.SERVICE_UNAVAILABLE


@pytest.mark.usefixtures("enable_turnstile")
async def test_cloudflare_400_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """Đo được trên stack thật: body rỗng → Cloudflare trả **HTTP 400**, không
    phải 200 kèm `error-codes`. Một `400` từ Cloudflare là lỗi phía mình
    (request dựng sai), không phải phán quyết về người dùng — nên nó là `503`,
    không phải `400 TURNSTILE_FAILED`."""
    _set_transport(monkeypatch, lambda _r: httpx.Response(400, text="Bad Request"))

    with pytest.raises(ApiError) as exc:
        await verify_turnstile(FAKE_TOKEN)

    assert exc.value.status_code == 503


@pytest.mark.usefixtures("enable_turnstile")
async def test_network_drop_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    def _no(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("khong noi duoc (gia lap)")

    _set_transport(monkeypatch, _no)

    with pytest.raises(ApiError) as exc:
        await verify_turnstile(FAKE_TOKEN)

    assert exc.value.status_code == 503


@pytest.mark.usefixtures("enable_turnstile")
async def test_non_object_json_body_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """Một proxy chen giữa trả `"ok"` hoặc `[]`: `raise_for_status` qua được,
    và `ket_qua.get(...)` sẽ nổ thành `500` nếu không chặn ở đây."""
    _set_transport(monkeypatch, _json_response(["khong phai object"]))  # type: ignore[arg-type]

    with pytest.raises(ApiError) as exc:
        await verify_turnstile(FAKE_TOKEN)

    assert exc.value.status_code == 503


@pytest.mark.usefixtures("enable_turnstile")
async def test_unparseable_json_body_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_transport(monkeypatch, lambda _r: httpx.Response(200, text="<html>loi</html>"))

    with pytest.raises(ApiError) as exc:
        await verify_turnstile(FAKE_TOKEN)

    assert exc.value.status_code == 503
