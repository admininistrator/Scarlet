"""`POST /auth/register` (§11.1, §11.5, §11.6, UC-01) — T-2.1.

Cùng mô hình với `test_conversations.py`: `httpx.ASGITransport`, và
`session_scope()` trong handler bị trỏ về đúng kết nối của test qua
`_db_cua_test`. Không cần `_debug_bat`: `register` không đi qua
`Depends(get_current_user_id)` — đây là endpoint công khai.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import ApiErrorCode
from app.db.models import User
from app.main import app

DUONG_DAN = "/api/v1/auth/register"


@pytest.fixture
def _db_cua_test(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`session_scope()` trong handler trỏ vào ĐÚNG kết nối của test (NQ-17)."""
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as http:
        yield http


async def _dem_user_theo_email(
    session_factory: async_sessionmaker[AsyncSession], email: str
) -> int:
    async with session_factory() as session:
        stmt = select(func.count()).select_from(User).where(User.email == email)
        return int((await session.execute(stmt)).scalar_one())


# ═══════════════════════ POST /auth/register — thành công ═══════════════════


@pytest.mark.usefixtures("_db_cua_test")
async def test_dang_ky_thanh_cong_tao_dung_mot_user_pending_email(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    email = f"{uuid.uuid4().hex}@scarlet.example"

    resp = await client.post(
        DUONG_DAN, json={"email": email, "password": "mot-mat-khau-du-manh-123"}
    )

    assert resp.status_code == 200
    assert await _dem_user_theo_email(session_factory, email) == 1

    async with session_factory() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        # DoD: `SELECT password_hash FROM users` bắt đầu bằng `$argon2id$`.
        assert user.password_hash.startswith("$argon2id$")
        assert user.status.value == "pending_email"
        # Tier mặc định (server_default) — không có literal "free" trong auth.py.
        assert user.tier_name == "free"


@pytest.mark.usefixtures("_db_cua_test")
async def test_dang_ky_hai_lan_cung_email_hai_response_giong_het_va_chi_mot_user(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """DoD T-2.1: đăng ký hai lần cùng email → hai response giống nhau từng
    byte, DB có đúng MỘT user. Đây là §11.5 (chống dò) ở dạng kiểm được."""
    email = f"{uuid.uuid4().hex}@scarlet.example"
    body = {"email": email, "password": "mot-mat-khau-du-manh-123"}

    resp1 = await client.post(DUONG_DAN, json=body)
    resp2 = await client.post(DUONG_DAN, json=body)

    assert resp1.status_code == resp2.status_code == 200
    assert resp1.content == resp2.content

    assert await _dem_user_theo_email(session_factory, email) == 1


# ═══════════════════════ POST /auth/register — mật khẩu yếu ═════════════════


async def test_mat_khau_pho_bien_tra_422(client: AsyncClient) -> None:
    """DoD T-2.1: mật khẩu `password1234` → `422` với lý do "quá phổ biến"."""
    resp = await client.post(
        DUONG_DAN,
        json={"email": f"{uuid.uuid4().hex}@scarlet.example", "password": "password1234"},
    )

    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == ApiErrorCode.PASSWORD_TOO_WEAK
    assert "pho bien" in body["error"]["message"]


async def test_mat_khau_duoi_12_ky_tu_tra_422(client: AsyncClient) -> None:
    resp = await client.post(
        DUONG_DAN,
        # 11 ký tự — dưới ngưỡng PASSWORD_MIN_LENGTH=12.
        json={"email": f"{uuid.uuid4().hex}@scarlet.example", "password": "Ab1#Ab1#Ab1"},
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == ApiErrorCode.PASSWORD_TOO_SHORT


async def test_email_sai_dinh_dang_tra_422_validation_error(client: AsyncClient) -> None:
    resp = await client.post(
        DUONG_DAN,
        json={"email": "khong-phai-email", "password": "mot-mat-khau-du-manh-123"},
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == ApiErrorCode.VALIDATION_ERROR
