"""B-86 — MỌI lỗi HTTP phải ra đúng một hình dạng: `{"error":{...}}` của §18.

Bộ test này không kiểm một endpoint nào cả; nó kiểm **hợp đồng chung**. Vì vậy
mỗi ca cố tình đi một đường sinh lỗi KHÁC nhau, và bốn trong số đó không đi qua
một dòng code nào của `app/` — đó chính là lý do B-86 chọn exception handler
toàn cục thay vì sửa từng chỗ `raise`:

    1. route không tồn tại        → Starlette, trước mọi router
    2. method sai                 → Starlette, sau khi khớp đường dẫn
    3. body/header sai kiểu       → `RequestValidationError` của FastAPI
    4. ngoại lệ không ai bắt      → `ServerErrorMiddleware` của Starlette
    5. `ApiError` của mình        → có mã riêng, không suy từ status

Ca cuối (`Exception` trần) dựng một app rời chứ không dùng `app.main.app`:
thêm một route ném lỗi vào app thật là để lại một cái bẫy cho mọi test sau.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient

from app.core import errors
from app.core.errors import LOI_500, ApiError, ApiErrorCode
from app.main import app


def _kiem_khung(body: dict[str, Any], code: str) -> None:
    """Đúng ba trường của §18, không thừa không thiếu, `details` luôn có mặt."""
    assert set(body) == {"error"}, "body lỗi chỉ được có khoá `error`"
    loi = body["error"]
    assert set(loi) == {"code", "message", "details"}
    assert loi["code"] == code
    assert isinstance(loi["message"], str) and loi["message"]
    assert isinstance(loi["details"], dict)


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as http:
        yield http


# ═══════════ ba nguồn lỗi KHÔNG đi qua code của mình (§18, B-86) ═══════════


async def test_route_khong_ton_tai_van_ra_khung_18(client: AsyncClient) -> None:
    """404 do Starlette sinh — không router nào được hỏi tới."""
    resp = await client.get("/api/v1/khong-co-duong-nay")

    assert resp.status_code == 404
    _kiem_khung(resp.json(), ApiErrorCode.NOT_FOUND)


async def test_method_sai_van_ra_khung_18(client: AsyncClient) -> None:
    """405: đường dẫn khớp, method không. Cũng của Starlette."""
    resp = await client.post("/api/v1/models")

    assert resp.status_code == 405
    _kiem_khung(resp.json(), ApiErrorCode.METHOD_NOT_ALLOWED)


async def test_header_sai_kieu_ra_422_co_danh_sach_field(client: AsyncClient) -> None:
    """`RequestValidationError` → 422 `VALIDATION_ERROR`, `details.fields` có `loc`."""
    resp = await client.get(
        "/api/v1/messages/00000000-0000-0000-0000-000000000000/stream",
        headers={"X-User-Id": "khong-phai-uuid"},
    )

    assert resp.status_code == 422
    _kiem_khung(resp.json(), ApiErrorCode.VALIDATION_ERROR)
    fields = resp.json()["error"]["details"]["fields"]
    assert fields and all(set(f) == {"loc", "msg", "type"} for f in fields)


async def test_422_khong_vong_lai_gia_tri_nguoi_dung_gui(client: AsyncClient) -> None:
    """§20: `input` của pydantic là chữ người dùng vừa gõ — không được vọng lại.

    Ở endpoint này `input` chỉ là một `X-User-Id` bịa ra, nhưng cùng handler
    ấy phục vụ `POST /conversations/{id}/messages`, nơi `input` là nội dung
    câu hỏi. Kiểm ở đây vì đây là chỗ kiểm được mà không cần dựng cả một cây.
    """
    bi_mat = "khong-duoc-vong-lai-chuoi-nay"

    resp = await client.get(
        "/api/v1/messages/00000000-0000-0000-0000-000000000000/stream",
        headers={"X-User-Id": bi_mat},
    )

    assert resp.status_code == 422
    assert bi_mat not in resp.text


# ═══════════════════════ hai nguồn lỗi của chính mình ══════════════════════


async def test_api_error_giu_ma_rieng_chu_khong_suy_tu_status() -> None:
    """Hai `ApiError` cùng 404 phải ra HAI mã khác nhau — đó là điểm của B-86."""
    phu = FastAPI()
    errors.register(phu)

    @phu.get("/mot")
    async def _mot() -> None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ApiErrorCode.MESSAGE_NOT_FOUND, "khong co")

    @phu.get("/hai")
    async def _hai() -> None:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            ApiErrorCode.NOT_FOUND,
            "khong co",
            details={"vi_sao": "kiem details di duoc ra ngoai"},
        )

    async with AsyncClient(transport=ASGITransport(app=phu), base_url="http://t") as http:
        mot = await http.get("/mot")
        hai = await http.get("/hai")

    _kiem_khung(mot.json(), ApiErrorCode.MESSAGE_NOT_FOUND)
    _kiem_khung(hai.json(), ApiErrorCode.NOT_FOUND)
    assert hai.json()["error"]["details"] == {"vi_sao": "kiem details di duoc ra ngoai"}


async def test_api_error_giu_nguyen_header(client: AsyncClient) -> None:
    """401 kèm `WWW-Authenticate`, 429 kèm `Retry-After` — handler không được nuốt."""
    phu = FastAPI()
    errors.register(phu)

    @phu.get("/can-dang-nhap")
    async def _can_dang_nhap() -> None:
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            ApiErrorCode.UNAUTHENTICATED,
            "chua dang nhap",
            headers={"WWW-Authenticate": "Bearer"},
        )

    async with AsyncClient(transport=ASGITransport(app=phu), base_url="http://t") as http:
        resp = await http.get("/can-dang-nhap")

    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"] == "Bearer"
    _kiem_khung(resp.json(), ApiErrorCode.UNAUTHENTICATED)


async def test_ngoai_le_khong_ai_bat_ra_500_dung_khung_va_khong_lo_traceback() -> None:
    """§20: `message` là câu cố định, KHÔNG phải `str(exc)`.

    `ServerErrorMiddleware` gửi response rồi **ném tiếp** ngoại lệ, nên
    `raise_app_exceptions=False` là bắt buộc để đọc được chính response đó —
    đúng như uvicorn làm ở production (gửi 500 cho client, log traceback).
    """
    phu = FastAPI()
    errors.register(phu)

    @phu.get("/no")
    async def _no() -> None:
        raise RuntimeError("chi-tiet-noi-that-cua-server")

    transport = ASGITransport(app=phu, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://t") as http:
        resp = await http.get("/no")

    assert resp.status_code == 500
    _kiem_khung(resp.json(), ApiErrorCode.INTERNAL_ERROR)
    assert resp.json()["error"]["message"] == LOI_500
    assert "chi-tiet-noi-that-cua-server" not in resp.text


# ═════════════════ hai bảng mã, hai vai trò (xem docstring errors.py) ══════


def test_ma_trung_ten_giua_hai_bang_phai_trung_ca_chuoi() -> None:
    """`MESSAGE_NOT_FOUND` của HTTP và của SSE nói cùng một chuyện ⇒ cùng chuỗi.

    Hai bảng tách nhau là cố ý, nhưng chỗ chúng giao nhau mà lệch chữ thì FE
    phải học hai tên cho một nghĩa — và sẽ học sai đúng một lần.
    """
    from app.streaming.events import ErrorCode

    chung = {m.name for m in ApiErrorCode} & {m.name for m in ErrorCode}
    assert chung, "hai bảng phải còn ít nhất một mã chung, nếu không test này vô nghĩa"
    for ten in chung:
        assert ApiErrorCode[ten].value == ErrorCode[ten].value


@pytest.mark.parametrize("ma", list(ApiErrorCode))
def test_moi_ma_la_chu_hoa_gach_duoi(ma: ApiErrorCode) -> None:
    """Mã là hằng của protocol, không phải câu tiếng Việt (§7.4 áp cùng luật)."""
    assert ma.value == ma.name
    assert ma.value.replace("_", "").isalnum()
    assert ma.value.isupper()
