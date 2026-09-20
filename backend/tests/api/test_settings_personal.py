"""`PUT /settings` — model mặc định theo NGƯỜI (§18.4, UC-05) — T-3.0, B-206.

Năm nhóm, mỗi nhóm đặt tên theo **thứ nó chặn**:

1. Ghi rồi đọc lại qua `GET /auth/me` — hai endpoint, một sự thật.
2. Model lạ hoặc đã tắt ⇒ `400 MODEL_UNKNOWN`, và **không** ghi gì.
3. `null` bỏ chọn được — nếu không thì người dùng chọn xong là kẹt.
4. Validate lúc **GHI**, không lúc đọc: model biến khỏi catalog sau đó vẫn đọc
   ra bình thường (Cạm bẫy ③ của T-3.0).
5. §20 — không tham số nào trỏ sang người khác, và hai người không thấy nhau.

Hạ tầng giống `test_settings_keys.py`: `httpx.ASGITransport`, `session_scope()`
trỏ về đúng kết nối của test, Redis giả cho blacklist. Bộ test này **không**
đụng BYOK nên không cần `MockTransport` của provider.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import catalog
from app.core.access_token import encode_access_token
from app.core.deps import SESSION_COOKIE_NAME
from app.core.errors import ApiErrorCode
from app.core.security import hash_password
from app.db.models import User, UserRole, UserStatus
from app.db.repositories.users import UserRepository
from app.main import app

DUONG_DAN = "/api/v1/settings"
DUONG_DAN_ME = "/api/v1/auth/me"

_MAT_KHAU = "mot-mat-khau-du-manh-cho-test-t30-123"


class _RedisGia:
    """Blacklist rỗng — bộ test này đo cài đặt cá nhân, không đo §11.3."""

    async def mget(self, keys: list[str]) -> list[str | None]:
        return [None for _ in keys]

    async def incr(self, name: str) -> int:
        return 1

    async def expire(self, name: str, time: int, *, nx: bool = False) -> bool:
        return True


@pytest.fixture(autouse=True)
def redis_gia(monkeypatch: pytest.MonkeyPatch) -> _RedisGia:
    gia = _RedisGia()
    monkeypatch.setattr("app.core.deps.get_redis", lambda: gia)
    return gia


@pytest.fixture(autouse=True)
def _db_cua_test(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`session_scope()` trong handler trỏ vào ĐÚNG kết nối của test (NQ-17)."""
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


@pytest_asyncio.fixture
async def client(event_hooks: dict[str, Any]) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://localhost", event_hooks=event_hooks
    ) as http:
        yield http


async def tao_user(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    email = f"{uuid.uuid4().hex}@scarlet.example"
    async with session_factory() as session:
        user = await UserRepository(session).create_pending_user(
            email=email, password_hash=await hash_password(_MAT_KHAU)
        )
        assert user is not None
        await session.execute(
            update(User).where(User.id == user.id).values(status=UserStatus.ACTIVE)
        )
        await session.commit()
        return user.id


def dang_nhap(client: AsyncClient, user_id: uuid.UUID) -> None:
    client.cookies.set(
        SESSION_COOKIE_NAME,
        encode_access_token(
            user_id=user_id,
            role=UserRole.USER,
            tier="free",
            status=UserStatus.ACTIVE,
            ttl_minutes=15,
        ),
    )


async def doc_cot(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> str | None:
    """Đọc thẳng cột `users.default_model` — không qua response nào."""
    async with session_factory() as session:
        stmt = select(User.default_model).where(User.id == user_id)
        return (await session.execute(stmt)).scalar_one()


def mot_model_bat() -> str:
    """Một `model_id` đang bật. A3: không gõ tên model vào file test."""
    bat = [m.id for m in catalog.get_catalog().models if m.enabled]
    assert bat, "catalog phải có ít nhất một model bật"
    return bat[0]


# ══════════════ 1. Ghi rồi đọc lại — hai endpoint, một sự thật ══════════════


async def test_ghi_roi_doc_lai_qua_auth_me(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id = await tao_user(session_factory)
    dang_nhap(client, user_id)
    model = mot_model_bat()

    ghi = await client.put(DUONG_DAN, json={"default_model": model})

    assert ghi.status_code == 200, ghi.text
    assert ghi.json() == {"default_model": model}
    assert await doc_cot(session_factory, user_id) == model
    assert (await client.get(DUONG_DAN_ME)).json()["default_model"] == model


# ═════════ 2. Model lạ hoặc đã tắt ⇒ 400 MODEL_UNKNOWN, không ghi gì ════════


async def test_model_khong_co_trong_catalog_tra_400_va_khong_ghi_gi(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id = await tao_user(session_factory)
    dang_nhap(client, user_id)

    resp = await client.put(DUONG_DAN, json={"default_model": "khong-ton-tai"})

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == ApiErrorCode.MODEL_UNKNOWN.value
    assert resp.json()["error"]["details"] == {"model_id": "khong-ton-tai"}
    assert await doc_cot(session_factory, user_id) is None


async def test_model_da_tat_cung_tra_400(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`enabled: false` là công tắc của §9.2 — chọn mặc định một model đang tắt
    là hẹn trước một `MODEL_UNKNOWN` cho mọi lượt chat sau đó."""
    user_id = await tao_user(session_factory)
    dang_nhap(client, user_id)
    model = mot_model_bat()
    monkeypatch.setattr(catalog, "get_model", lambda _id: None)

    resp = await client.put(DUONG_DAN, json={"default_model": model})

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == ApiErrorCode.MODEL_UNKNOWN.value
    assert await doc_cot(session_factory, user_id) is None


async def test_khoa_la_trong_body_tra_422(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`extra="forbid"`: gõ sai tên trường phải NỔ, không phải im lặng.

    `{"defaultModel": ...}` mà được nhận là một lần bấm Lưu không có tác dụng
    gì và không ai biết vì sao.
    """
    user_id = await tao_user(session_factory)
    dang_nhap(client, user_id)

    resp = await client.put(DUONG_DAN, json={"defaultModel": mot_model_bat()})

    assert resp.status_code == 422
    assert await doc_cot(session_factory, user_id) is None


# ════════════════════════ 3. `null` bỏ chọn được ═══════════════════════════


async def test_null_xoa_lua_chon(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Không có đường về mặc định thì người dùng chọn xong là kẹt (T-3.6)."""
    user_id = await tao_user(session_factory)
    dang_nhap(client, user_id)
    await client.put(DUONG_DAN, json={"default_model": mot_model_bat()})

    resp = await client.put(DUONG_DAN, json={"default_model": None})

    assert resp.status_code == 200
    assert resp.json() == {"default_model": None}
    assert await doc_cot(session_factory, user_id) is None


async def test_body_rong_cung_xoa_lua_chon(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`PUT` thay cả tài nguyên: vắng mặt đọc thành `null`, không phải "giữ nguyên".

    Hôm nay tài nguyên có đúng một trường nên hai cách đọc trùng nhau; test này
    chốt cách đọc lại để ngày có trường thứ hai thì người thêm nó phải quyết
    định một cách tường minh (thêm `PATCH`), không phải sửa lén luật ở đây.
    """
    user_id = await tao_user(session_factory)
    dang_nhap(client, user_id)
    await client.put(DUONG_DAN, json={"default_model": mot_model_bat()})

    resp = await client.put(DUONG_DAN, json={})

    assert resp.status_code == 200
    assert await doc_cot(session_factory, user_id) is None


# ═══════ 4. Validate lúc GHI, không lúc đọc (Cạm bẫy ③ của T-3.0) ═══════════


async def test_model_bien_khoi_catalog_sau_do_van_doc_ra_binh_thuong(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catalog là file sửa nóng (§19.1): một dòng admin vừa sửa không được phép
    ném lỗi vào mặt một người không làm gì cả."""
    user_id = await tao_user(session_factory)
    dang_nhap(client, user_id)
    model = mot_model_bat()
    await client.put(DUONG_DAN, json={"default_model": model})

    # admin gỡ model khỏi catalog rồi `POST /admin/catalog/reload`
    monkeypatch.setattr(catalog, "get_model", lambda _id: None)

    resp = await client.get(DUONG_DAN_ME)

    assert resp.status_code == 200
    assert resp.json()["default_model"] == model, "tra nguyen van, FE tu roi ve mac dinh"


# ═══════════════════════════ 5. §20 — cách ly ══════════════════════════════


async def test_khong_dang_nhap_tra_401(client: AsyncClient) -> None:
    resp = await client.put(DUONG_DAN, json={"default_model": mot_model_bat()})

    # `401` va chi `401`: nhanh danh tinh tam Phase 1 (`503`) chet o T-3.1c.
    assert resp.status_code == 401


async def test_ghi_cua_nguoi_nay_khong_cham_nguoi_kia(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Không có tham số nào trỏ sang người khác, nên phép đo duy nhất còn lại
    là: sau khi A ghi, cột của B vẫn nguyên (§20)."""
    user_a = await tao_user(session_factory)
    user_b = await tao_user(session_factory)
    dang_nhap(client, user_a)

    await client.put(DUONG_DAN, json={"default_model": mot_model_bat()})

    assert await doc_cot(session_factory, user_b) is None
