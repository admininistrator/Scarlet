"""B-86 — MỌI lỗi HTTP phải ra đúng một hình dạng: `{"error":{...}}` của §18.

Bộ test này không kiểm một endpoint nào cả; nó kiểm **hợp đồng chung**. Vì vậy
mỗi ca cố tình đi một đường sinh lỗi KHÁC nhau, và bốn trong số đó không đi qua
một dòng code nào của `app/` — đó chính là lý do B-86 chọn exception handler
toàn cục thay vì sửa từng chỗ `raise`:

    1. route không tồn tại        → Starlette, trước mọi router
    2. method sai                 → Starlette, sau khi khớp đường dẫn
    3. path/body sai kiểu         → `RequestValidationError` của FastAPI
    4. ngoại lệ không ai bắt      → `ServerErrorMiddleware` của Starlette
    5. `ApiError` của mình        → có mã riêng, không suy từ status

Ca cuối (`Exception` trần) dựng một app rời chứ không dùng `app.main.app`:
thêm một route ném lỗi vào app thật là để lại một cái bẫy cho mọi test sau.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient

from app.core import errors
from app.core.access_token import encode_access_token
from app.core.deps import SESSION_COOKIE_NAME
from app.core.errors import INTERNAL_ERROR_MSG, ApiError, ApiErrorCode
from app.db.models import UserRole, UserStatus
from app.main import app


def _check_envelope(body: dict[str, Any], code: str) -> None:
    """Đúng ba trường của §18, không thừa không thiếu, `details` luôn có mặt."""
    assert set(body) == {"error"}, "body lỗi chỉ được có khoá `error`"
    error = body["error"]
    assert set(error) == {"code", "message", "details"}
    assert error["code"] == code
    assert isinstance(error["message"], str) and error["message"]
    assert isinstance(error["details"], dict)


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as http:
        yield http


def _session() -> dict[str, str]:
    """Một phiên hợp lệ — điều kiện để chạm được tới lớp validate của FastAPI.

    Hai ca `422` dưới đây trước T-3.1c gửi một header danh tính sai kiểu: nhánh
    tạm của Phase 1 khai tham số ấy là `uuid.UUID`, nên FastAPI validate nó rồi
    trả `422` mà không cần ai đăng nhập. Nhánh ấy chết, và `401` nay chặn từ
    dependency — tức không có `422` nào để đo nếu không có phiên. Nguồn lỗi
    đổi từ **header** sang **path param**; hình dạng lỗi đang đo thì không đổi,
    và đó mới là thứ B-86 nói tới.

    Không chạm Postgres: `RequestValidationError` ném trước khi handler chạy.
    """
    token = encode_access_token(
        user_id=uuid.uuid4(),
        role=UserRole.USER,
        tier="free",
        status=UserStatus.ACTIVE,
        ttl_minutes=15,
    )
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


# ═══════════ ba nguồn lỗi KHÔNG đi qua code của mình (§18, B-86) ═══════════


async def test_missing_route_still_gets_18_envelope(client: AsyncClient) -> None:
    """404 do Starlette sinh — không router nào được hỏi tới."""
    resp = await client.get("/api/v1/khong-co-duong-nay")

    assert resp.status_code == 404
    _check_envelope(resp.json(), ApiErrorCode.NOT_FOUND)


async def test_wrong_method_still_gets_18_envelope(client: AsyncClient) -> None:
    """405: đường dẫn khớp, method không. Cũng của Starlette."""
    resp = await client.post("/api/v1/models")

    assert resp.status_code == 405
    _check_envelope(resp.json(), ApiErrorCode.METHOD_NOT_ALLOWED)


async def test_wrong_type_path_param_422_with_field_list(client: AsyncClient) -> None:
    """`RequestValidationError` → 422 `VALIDATION_ERROR`, `details.fields` có `loc`."""
    resp = await client.get("/api/v1/messages/khong-phai-uuid/stream", headers=_session())

    assert resp.status_code == 422
    _check_envelope(resp.json(), ApiErrorCode.VALIDATION_ERROR)
    fields = resp.json()["error"]["details"]["fields"]
    assert fields and all(set(f) == {"loc", "msg", "type"} for f in fields)


async def test_422_does_not_echo_user_value(client: AsyncClient) -> None:
    """§20: `input` của pydantic là chữ người dùng vừa gõ — không được vọng lại.

    Ở endpoint này `input` chỉ là một mẩu đường dẫn bịa ra, nhưng cùng handler
    ấy phục vụ `POST /conversations/{id}/messages`, nơi `input` là nội dung
    câu hỏi. Kiểm ở đây vì đây là chỗ kiểm được mà không cần dựng cả một cây.
    """
    secret = "khong-duoc-vong-lai-chuoi-nay"

    resp = await client.get(f"/api/v1/messages/{secret}/stream", headers=_session())

    assert resp.status_code == 422
    assert secret not in resp.text


# ═══════════════════════ hai nguồn lỗi của chính mình ══════════════════════


async def test_api_error_keeps_own_code_not_derived_from_status() -> None:
    """Hai `ApiError` cùng 404 phải ra HAI mã khác nhau — đó là điểm của B-86."""
    sub_app = FastAPI()
    errors.register(sub_app)

    @sub_app.get("/mot")
    async def _one() -> None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ApiErrorCode.MESSAGE_NOT_FOUND, "khong co")

    @sub_app.get("/hai")
    async def _two() -> None:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            ApiErrorCode.NOT_FOUND,
            "khong co",
            details={"vi_sao": "kiem details di duoc ra ngoai"},
        )

    async with AsyncClient(transport=ASGITransport(app=sub_app), base_url="http://t") as http:
        first = await http.get("/mot")
        second = await http.get("/hai")

    _check_envelope(first.json(), ApiErrorCode.MESSAGE_NOT_FOUND)
    _check_envelope(second.json(), ApiErrorCode.NOT_FOUND)
    assert second.json()["error"]["details"] == {"vi_sao": "kiem details di duoc ra ngoai"}


async def test_api_error_keeps_headers(client: AsyncClient) -> None:
    """401 kèm `WWW-Authenticate`, 429 kèm `Retry-After` — handler không được nuốt."""
    sub_app = FastAPI()
    errors.register(sub_app)

    @sub_app.get("/can-dang-nhap")
    async def _needs_login() -> None:
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            ApiErrorCode.UNAUTHENTICATED,
            "chua dang nhap",
            headers={"WWW-Authenticate": "Bearer"},
        )

    async with AsyncClient(transport=ASGITransport(app=sub_app), base_url="http://t") as http:
        resp = await http.get("/can-dang-nhap")

    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"] == "Bearer"
    _check_envelope(resp.json(), ApiErrorCode.UNAUTHENTICATED)


async def test_uncaught_exception_500_right_envelope_no_traceback_leak() -> None:
    """§20: `message` là câu cố định, KHÔNG phải `str(exc)`.

    `ServerErrorMiddleware` gửi response rồi **ném tiếp** ngoại lệ, nên
    `raise_app_exceptions=False` là bắt buộc để đọc được chính response đó —
    đúng như uvicorn làm ở production (gửi 500 cho client, log traceback).
    """
    sub_app = FastAPI()
    errors.register(sub_app)

    @sub_app.get("/no")
    async def _no() -> None:
        raise RuntimeError("chi-tiet-noi-that-cua-server")

    transport = ASGITransport(app=sub_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://t") as http:
        resp = await http.get("/no")

    assert resp.status_code == 500
    _check_envelope(resp.json(), ApiErrorCode.INTERNAL_ERROR)
    assert resp.json()["error"]["message"] == INTERNAL_ERROR_MSG
    assert "chi-tiet-noi-that-cua-server" not in resp.text


# ═════════════════ hai bảng mã, hai vai trò (xem docstring errors.py) ══════


def test_codes_shared_by_name_must_share_string() -> None:
    """`MESSAGE_NOT_FOUND` của HTTP và của SSE nói cùng một chuyện ⇒ cùng chuỗi.

    Hai bảng tách nhau là cố ý, nhưng chỗ chúng giao nhau mà lệch chữ thì FE
    phải học hai tên cho một nghĩa — và sẽ học sai đúng một lần.
    """
    from app.streaming.events import ErrorCode

    common = {m.name for m in ApiErrorCode} & {m.name for m in ErrorCode}
    assert common, "hai bảng phải còn ít nhất một mã chung, nếu không test này vô nghĩa"
    for name in common:
        assert ApiErrorCode[name].value == ErrorCode[name].value


@pytest.mark.parametrize("code", list(ApiErrorCode))
def test_every_code_is_upper_snake_case(code: ApiErrorCode) -> None:
    """Mã là hằng của protocol, không phải câu tiếng Việt (§7.4 áp cùng luật)."""
    assert code.value == code.name
    assert code.value.replace("_", "").isalnum()
    assert code.value.isupper()
