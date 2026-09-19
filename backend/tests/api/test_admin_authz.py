"""Phân quyền của **MỌI** endpoint `/api/v1/admin/*` (§16.3, §20) — T-2.16.

DoD dòng 4: *"`pytest tests/api/test_admin_authz.py` phủ **mọi** endpoint
`/admin/*` với user thường"*. Cạm bẫy của task nói cách làm: *"quên
`require_admin` ở MỘT endpoint là đủ. Viết test lặp qua danh sách route thay vì
test từng cái bằng tay."*

**Danh sách route ở đây đọc từ chính app đang chạy, không phải từ một hằng số
chép tay.** Khác biệt là toàn bộ giá trị của file này: một danh sách chép tay
chỉ phủ những gì người viết nhớ tới hôm nay, nên endpoint `/admin/*` thứ tám
thêm vào tháng sau sẽ **không** có test và cũng **không** làm test nào đỏ. Đọc
từ app thì ngược lại — endpoint mới tự động rơi vào ma trận dưới đây, và nếu ai
đó gắn nó bằng một `APIRouter` riêng không có `require_admin` thì file này đỏ
ngay ở lần chạy kế tiếp.

Hai nguồn hợp lại (`_tu_openapi` + `_tu_router`) vì mỗi nguồn có một điểm mù,
và hai điểm mù ấy không giao nhau — xem docstring của từng hàm. Cố ý **không**
duyệt `app.routes`: phiên bản FastAPI đang dùng gắn router con dưới dạng một
object nội bộ (`_IncludedRouter`) không phơi ra `.routes`, nên một vòng lặp
trên `app.routes` trả về **danh sách rỗng** — tức xanh mà không kiểm gì. Đó
chính là ca mà `_TOI_THIEU` ngay dưới đây đã bắt được lần đầu chạy file này.

`_TOI_THIEU` là lưới đỡ cho chính cách đọc đó: một bộ lọc gõ sai (`/admin` đổi
prefix, `include_router` bị xoá) sẽ cho ra **danh sách rỗng**, và một
`parametrize` rỗng thì pytest báo **xanh**. Khẳng định số lượng tối thiểu biến
ca ấy thành một test đỏ.

Ba cột của ma trận là ba loại người gọi, và cột thứ ba là cột dễ quên nhất:

1. **user thường** (cookie phiên hợp lệ, `role=user`) → `403 ADMIN_REQUIRED`
2. **không có gì** (không cookie, không header) → `401 UNAUTHENTICATED`
3. **danh tính tạm của Phase 1** (`X-User-Id`, NQ-24) → `401`, **không** phải
   một lối vào. Đây là khác biệt cố ý so với `require_status` (thứ cho nhánh ấy
   đi thẳng qua): `X-User-Id` là một chuỗi người gọi tự gõ, nên cho nó qua
   nghĩa là bất kỳ ai gọi được `api` lúc `DEBUG=true` đều duyệt được tài khoản.
   Xem docstring `app/core/deps.py::require_admin`.

Không có test nào ở đây chạm Postgres: cả ba cột dừng lại ở dependency, trước
khi handler kịp mở một `session_scope()`. Đó cũng là một tính chất đáng giữ —
nếu một ngày nào đó một trong ba cột cần DB để trả lời, nghĩa là phép kiểm
quyền đã tụt xuống dưới tầng nó phải ở.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from app.api.v1 import admin
from app.core.access_token import encode_access_token
from app.core.deps import SESSION_COOKIE_NAME
from app.core.errors import ApiErrorCode
from app.db.models import UserRole, UserStatus
from app.main import app

#: Tiền tố mà `app/main.py` gắn `api/v1/__init__.py::router` vào.
API_PREFIX = "/api/v1"

#: Số endpoint `/admin/*` mà T-2.16 dựng: `users` (GET), `users/{id}/{hành
#: động}` (POST), `users/{id}` (PATCH), `usage` (GET), `catalog/reload` (POST).
#: **Tối thiểu**, không phải bằng đúng: thêm endpoint là chuyện bình thường, còn
#: mất endpoint (hoặc bộ lọc dưới đây hỏng) thì không.
_TOI_THIEU = 5

#: Giá trị điền vào tham số đường dẫn. `hanh_dong` phải khớp `pattern` của route
#: (`^(approve|reject|suspend)$`), nếu không FastAPI trả `404` và ca kiểm mất
#: nghĩa — nó sẽ "đạt" mà không chạm tới `require_admin` lần nào.
_THAM_SO: dict[str, str] = {
    "user_id": str(uuid.uuid4()),
    "hanh_dong": "approve",
}


#: Tiền tố mà mọi endpoint của §16.3 nằm dưới.
_PREFIX = "/api/v1/admin"


def _tu_openapi() -> set[tuple[str, str]]:
    """Đọc từ schema OpenAPI — nguồn thấy được **mọi** router, kể cả router khác.

    Đây là nguồn quan trọng hơn trong hai nguồn: nó bắt được cả trường hợp một
    ngày nào đó có người đăng ký một đường dẫn `/api/v1/admin/...` từ một
    `APIRouter` khác mà quên `require_admin` — thứ mà đọc thẳng `admin.router`
    sẽ không bao giờ thấy.
    """
    return {
        (method.upper(), duong_dan)
        for duong_dan, ops in app.openapi()["paths"].items()
        if duong_dan.startswith(_PREFIX)
        for method in ops
    }


def _tu_router() -> set[tuple[str, str]]:
    """Đọc thẳng `admin.router` — nguồn thấy được cả route `include_in_schema=False`.

    OpenAPI bỏ qua route ẩn, nên một endpoint gắn cờ ấy sẽ **biến mất** khỏi ma
    trận nếu chỉ có nguồn thứ nhất. Hợp hai tập lại thì không cờ nào giấu được
    một endpoint khỏi phép kiểm quyền.
    """
    return {
        (method, f"{API_PREFIX}{route.path}")
        for route in admin.router.routes
        if isinstance(route, APIRoute)
        for method in route.methods - {"HEAD", "OPTIONS"}
    }


def _duong_dan_admin() -> list[tuple[str, str]]:
    """Mọi `(method, path)` dưới `/api/v1/admin`, từ HAI nguồn hợp lại."""
    return sorted(
        (method, duong_dan.format(**_THAM_SO)) for method, duong_dan in _tu_openapi() | _tu_router()
    )


DUONG_DAN_ADMIN = _duong_dan_admin()


def test_co_it_nhat_nam_endpoint_admin() -> None:
    """Lưới đỡ của chính cách đọc route — xem docstring module."""
    assert len(DUONG_DAN_ADMIN) >= _TOI_THIEU, DUONG_DAN_ADMIN


class _RedisGia:
    """Blacklist rỗng — mọi token đều "chưa bị thu hồi" (§11.3).

    Cùng lý do với `_RedisGia` của `test_account_states.py`: bộ test này đo
    phép kiểm **quyền**, nên Redis phải im lặng để mọi ca dừng đúng ở lớp cần
    đo chứ không ở một `401 TOKEN_REVOKED`.
    """

    async def mget(self, keys: list[str]) -> list[str | None]:
        return [None for _ in keys]


@pytest.fixture(autouse=True)
def redis_gia(monkeypatch: pytest.MonkeyPatch) -> _RedisGia:
    gia = _RedisGia()
    monkeypatch.setattr("app.core.deps.get_redis", lambda: gia)
    return gia


@pytest_asyncio.fixture
async def client(event_hooks: dict[str, Any]) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://localhost", event_hooks=event_hooks
    ) as http:
        yield http


def _cookie(client: AsyncClient, role: UserRole) -> None:
    client.cookies.set(
        SESSION_COOKIE_NAME,
        encode_access_token(
            user_id=uuid.uuid4(),
            role=role,
            tier="free",
            status=UserStatus.ACTIVE,
            ttl_minutes=15,
        ),
    )


async def _goi(client: AsyncClient, method: str, duong_dan: str) -> Any:
    """Gửi request tới một ô của ma trận. Body `{}` cho method có body.

    `json={}` chứ không để trống: nếu một ngày `require_admin` biến mất, PATCH
    sẽ đi tiếp tới phần đọc body — và một `422 VALIDATION_ERROR` ở đó đọc rất
    giống một lần chặn thành công nếu test chỉ so mã HTTP. Gửi body hợp lệ giữ
    cho ca hỏng ấy lộ ra đúng hình dạng của nó (`200`).
    """
    if method in {"POST", "PATCH", "PUT"}:
        return await client.request(method, duong_dan, json={})
    return await client.request(method, duong_dan)


@pytest.mark.parametrize(("method", "duong_dan"), DUONG_DAN_ADMIN)
async def test_user_thuong_bi_chan_o_moi_endpoint(
    client: AsyncClient, method: str, duong_dan: str
) -> None:
    """DoD dòng 1 + dòng 4: *"user thường gọi `/admin/users` → 403"*, mọi endpoint."""
    _cookie(client, UserRole.USER)

    resp = await _goi(client, method, duong_dan)

    assert resp.status_code == 403, f"{method} {duong_dan} -> {resp.status_code} {resp.text}"
    body = resp.json()["error"]
    assert body["code"] == ApiErrorCode.ADMIN_REQUIRED
    assert body["details"]["role"] == UserRole.USER.value


@pytest.mark.parametrize(("method", "duong_dan"), DUONG_DAN_ADMIN)
async def test_khong_token_thi_401_o_moi_endpoint(
    client: AsyncClient, method: str, duong_dan: str
) -> None:
    """DoD dòng 1: *"`curl` không token → `401`"*, và cho **mọi** endpoint."""
    resp = await _goi(client, method, duong_dan)

    assert resp.status_code == 401, f"{method} {duong_dan} -> {resp.status_code} {resp.text}"
    assert resp.json()["error"]["code"] == ApiErrorCode.UNAUTHENTICATED


@pytest.mark.parametrize(("method", "duong_dan"), DUONG_DAN_ADMIN)
async def test_danh_tinh_tam_phase_1_khong_mo_duoc_cua_admin(
    client: AsyncClient, method: str, duong_dan: str
) -> None:
    """`X-User-Id` (NQ-24) **không** là một lối vào `/admin/*` — xem docstring module."""
    resp = await client.request(
        method,
        duong_dan,
        headers={"X-User-Id": str(uuid.uuid4())},
        **({"json": {}} if method in {"POST", "PATCH", "PUT"} else {}),
    )

    assert resp.status_code == 401, f"{method} {duong_dan} -> {resp.status_code} {resp.text}"
    assert resp.json()["error"]["code"] == ApiErrorCode.UNAUTHENTICATED


@pytest.mark.parametrize(("method", "duong_dan"), DUONG_DAN_ADMIN)
async def test_tai_khoan_bi_khoa_khong_vao_duoc_du_la_admin(
    client: AsyncClient, method: str, duong_dan: str
) -> None:
    """`require_app_access` chạy TRƯỚC `require_admin` — §11.1 vẫn áp cho admin.

    Một admin `suspended` nhận `403 ACCOUNT_DISABLED` (bảng §11.1), không phải
    `ADMIN_REQUIRED`: thứ chặn họ là trạng thái tài khoản chứ không phải vai
    trò. Nếu `/admin/*` chỉ có `require_admin` thì đây là cánh cửa duy nhất của
    app không chịu bảng §11.1 — và nó là cánh cửa quyền lực nhất.
    """
    client.cookies.set(
        SESSION_COOKIE_NAME,
        encode_access_token(
            user_id=uuid.uuid4(),
            role=UserRole.ADMIN,
            tier="free",
            status=UserStatus.SUSPENDED,
            ttl_minutes=15,
        ),
    )

    resp = await _goi(client, method, duong_dan)

    assert resp.status_code == 403, f"{method} {duong_dan} -> {resp.status_code} {resp.text}"
    body = resp.json()["error"]
    assert body["code"] == ApiErrorCode.ACCOUNT_DISABLED
    assert body["details"]["status"] == UserStatus.SUSPENDED.value
