"""`POST /auth/register` + `/verify-email` + `/resend-verification` (§11.1,
§11.5, §11.6, UC-01) — T-2.1, T-2.2.

Cùng mô hình với `test_conversations.py`: `httpx.ASGITransport`, và
`session_scope()` trong handler bị trỏ về đúng kết nối của test qua
`_db_cua_test`. Không cần `_debug_bat`: cả ba endpoint không đi qua
`Depends(get_current_user_id)` — đều công khai.

`mailer_gia` (T-2.2) thay `app.api.v1.auth.mailer` bằng một stub ghi lại lời
gọi thay vì gửi SMTP thật: bộ test này kiểm HÀNH VI của handler (có gọi
`mailer.send` không, với `template`/`ctx` gì), không kiểm hạ tầng SMTP — phần
"thư có thật sự tới Mailpit trong ≤ 5 s" là phép đo tay trên stack thật (báo
cáo T-2.2 mục 2), không phải thứ `pytest` nên giả lập lại.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.v1.auth import REFRESH_COOKIE_NAME
from app.core.access_token import encode_access_token
from app.core.deps import SESSION_COOKIE_NAME
from app.core.errors import ApiErrorCode
from app.core.security import hash_email_token, hash_password
from app.db.models import EmailToken, EmailTokenPurpose, RefreshToken, User, UserRole, UserStatus
from app.db.repositories.users import UserRepository
from app.main import app

DUONG_DAN = "/api/v1/auth/register"
DUONG_DAN_VERIFY = "/api/v1/auth/verify-email"
DUONG_DAN_RESEND = "/api/v1/auth/resend-verification"
DUONG_DAN_LOGIN = "/api/v1/auth/login"
DUONG_DAN_REFRESH = "/api/v1/auth/refresh"
DUONG_DAN_ME = "/api/v1/auth/me"

#: Mật khẩu thật dùng trong test login — khác `user_a`/`user_b` của
#: `conftest.py` (những fixture đó gán `password_hash="khong-phai-hash-that"`,
#: một chuỗi KHÔNG phải Argon2 hợp lệ, nên `verify_password` luôn trả `False`
#: cho chúng — đúng ý đồ của conftest, vốn chỉ cần một user tồn tại cho các
#: test IDOR chứ không cần đăng nhập được).
_MAT_KHAU_TEST = "mot-mat-khau-du-manh-cho-test-login-123"


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


class _MailerGia:
    """Stub `Mailer` (§11.5, T-2.2): ghi lại lời gọi thay vì gửi SMTP thật."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def send(self, *, template: str, to: str, ctx: dict[str, Any]) -> None:
        self.calls.append({"template": template, "to": to, "ctx": ctx})


@pytest.fixture
def mailer_gia(monkeypatch: pytest.MonkeyPatch) -> _MailerGia:
    """Thay `app.api.v1.auth.mailer` — patch đúng tên đã import vào module đó,
    không phải `app.core.mailer.mailer` (import đã chép tham chiếu ra rồi)."""
    stub = _MailerGia()
    monkeypatch.setattr("app.api.v1.auth.mailer", stub)
    return stub


def _token_tu_verify_url(verify_url: str) -> str:
    return parse_qs(urlsplit(verify_url).query)["token"][0]


async def _tao_user_that(
    session_factory: async_sessionmaker[AsyncSession], *, mat_khau: str = _MAT_KHAU_TEST
) -> tuple[uuid.UUID, str]:
    """User với hash Argon2id THẬT của `mat_khau` — dùng cho test login."""
    email = f"{uuid.uuid4().hex}@scarlet.example"
    async with session_factory() as session:
        user = await UserRepository(session).create_pending_user(
            email=email, password_hash=await hash_password(mat_khau)
        )
        assert user is not None
        await session.commit()
        return user.id, email


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


# ═══════════════════ POST /auth/register — gửi email verify (T-2.2) ═════════


@pytest.mark.usefixtures("_db_cua_test")
async def test_dang_ky_thanh_cong_goi_mailer_voi_verify_url(
    client: AsyncClient, mailer_gia: _MailerGia
) -> None:
    """DoD T-2.2 (rút gọn cho unit test): đăng ký gọi đúng một lần
    `mailer.send(template="verify_email", ...)` với `verify_url` mang token.
    Phép đo "thư tới Mailpit trong ≤ 5 s" chạy tay trên stack thật — xem báo
    cáo mục 2, không phải thứ một unit test nên giả lập lại hạ tầng SMTP."""
    email = f"{uuid.uuid4().hex}@scarlet.example"

    resp = await client.post(
        DUONG_DAN, json={"email": email, "password": "mot-mat-khau-du-manh-123"}
    )

    assert resp.status_code == 200
    assert len(mailer_gia.calls) == 1
    goi = mailer_gia.calls[0]
    assert goi["template"] == "verify_email"
    assert goi["to"] == email
    assert "token=" in goi["ctx"]["verify_url"]
    assert goi["ctx"]["ttl_minutes"] > 0


@pytest.mark.usefixtures("_db_cua_test")
async def test_dang_ky_email_da_ton_tai_khong_goi_mailer_lan_hai(
    client: AsyncClient, mailer_gia: _MailerGia
) -> None:
    """Nhánh 'email đã tồn tại' không đọc/ghi gì thêm (§11.5) — kể cả không
    phát hành token/gửi mail lần thứ hai."""
    email = f"{uuid.uuid4().hex}@scarlet.example"
    body = {"email": email, "password": "mot-mat-khau-du-manh-123"}

    await client.post(DUONG_DAN, json=body)
    mailer_gia.calls.clear()
    await client.post(DUONG_DAN, json=body)

    assert mailer_gia.calls == []


# ═══════════════════════ POST /auth/verify-email (T-2.2) ════════════════════


@pytest.mark.usefixtures("_db_cua_test")
async def test_verify_email_dung_token_doi_status_pending_approval(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    mailer_gia: _MailerGia,
) -> None:
    """DoD T-2.2: bấm link → status đổi `pending_approval`."""
    email = f"{uuid.uuid4().hex}@scarlet.example"
    await client.post(DUONG_DAN, json={"email": email, "password": "mot-mat-khau-du-manh-123"})
    token = _token_tu_verify_url(mailer_gia.calls[0]["ctx"]["verify_url"])

    resp = await client.post(DUONG_DAN_VERIFY, json={"token": token})

    assert resp.status_code == 200
    assert resp.json() == {"status": "verified"}

    async with session_factory() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        assert user.status.value == "pending_approval"
        assert user.email_verified_at is not None


@pytest.mark.usefixtures("_db_cua_test")
async def test_verify_email_bam_lai_lan_hai_khong_loi(
    client: AsyncClient, mailer_gia: _MailerGia
) -> None:
    """DoD T-2.2: bấm lại cùng link → không lỗi, idempotent (UC-01)."""
    email = f"{uuid.uuid4().hex}@scarlet.example"
    await client.post(DUONG_DAN, json={"email": email, "password": "mot-mat-khau-du-manh-123"})
    token = _token_tu_verify_url(mailer_gia.calls[0]["ctx"]["verify_url"])

    resp1 = await client.post(DUONG_DAN_VERIFY, json={"token": token})
    resp2 = await client.post(DUONG_DAN_VERIFY, json={"token": token})

    assert resp1.status_code == resp2.status_code == 200
    assert resp1.json() == resp2.json() == {"status": "verified"}


@pytest.mark.usefixtures("_db_cua_test")
async def test_verify_email_token_khong_ton_tai_tra_400(client: AsyncClient) -> None:
    resp = await client.post(DUONG_DAN_VERIFY, json={"token": "token-bia-dat-khong-ton-tai"})

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == ApiErrorCode.TOKEN_INVALID


@pytest.mark.usefixtures("_db_cua_test")
async def test_verify_email_het_han_tra_200_khong_phai_500(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """DoD T-2.2: token quá hạn → trang "gửi lại", HTTP 200, không phải 500."""
    raw_token = f"token-het-han-{uuid.uuid4().hex}"
    async with session_factory() as session:
        user = await UserRepository(session).create_pending_user(
            email=f"{uuid.uuid4().hex}@scarlet.example", password_hash="khong-phai-hash-that"
        )
        assert user is not None
        session.add(
            EmailToken(
                user_id=user.id,
                purpose=EmailTokenPurpose.VERIFY.value,
                token_hash=hash_email_token(raw_token),
                expires_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        )
        await session.commit()

    resp = await client.post(DUONG_DAN_VERIFY, json={"token": raw_token})

    assert resp.status_code == 200
    assert resp.json() == {"status": "expired"}


@pytest.mark.usefixtures("_db_cua_test")
async def test_token_hash_khong_chua_token_ban_ro(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    mailer_gia: _MailerGia,
) -> None:
    """DoD T-2.2: `SELECT token_hash FROM email_tokens` không dòng nào chứa
    token bản rõ có trong URL."""
    email = f"{uuid.uuid4().hex}@scarlet.example"
    await client.post(DUONG_DAN, json={"email": email, "password": "mot-mat-khau-du-manh-123"})
    raw_token = _token_tu_verify_url(mailer_gia.calls[0]["ctx"]["verify_url"])

    async with session_factory() as session:
        hashes = (await session.execute(select(EmailToken.token_hash))).scalars().all()

    assert raw_token not in hashes
    assert hash_email_token(raw_token) in hashes


# ═══════════════════ POST /auth/resend-verification (T-2.2) ═════════════════


@pytest.mark.usefixtures("_db_cua_test")
async def test_resend_verification_user_pending_email_gui_token_moi(
    client: AsyncClient, mailer_gia: _MailerGia
) -> None:
    email = f"{uuid.uuid4().hex}@scarlet.example"
    await client.post(DUONG_DAN, json={"email": email, "password": "mot-mat-khau-du-manh-123"})
    mailer_gia.calls.clear()

    resp = await client.post(DUONG_DAN_RESEND, json={"email": email})

    assert resp.status_code == 200
    assert len(mailer_gia.calls) == 1
    assert mailer_gia.calls[0]["to"] == email


@pytest.mark.usefixtures("_db_cua_test")
async def test_resend_verification_email_khong_ton_tai_response_giong_het(
    client: AsyncClient, mailer_gia: _MailerGia
) -> None:
    """Chống dò (§11.5, cùng lối register): response giống hệt dù email không
    tồn tại, và không gửi mail nào."""
    resp1 = await client.post(
        DUONG_DAN_RESEND, json={"email": f"{uuid.uuid4().hex}@khong-ton-tai.example"}
    )
    resp2 = await client.post(
        DUONG_DAN_RESEND, json={"email": f"{uuid.uuid4().hex}@khong-ton-tai.example"}
    )

    assert resp1.status_code == resp2.status_code == 200
    assert resp1.content == resp2.content
    assert mailer_gia.calls == []


@pytest.mark.usefixtures("_db_cua_test")
async def test_resend_verification_user_da_verify_khong_gui_mail(
    client: AsyncClient, mailer_gia: _MailerGia
) -> None:
    """Resend cho user đã qua khỏi `pending_email` không phát hành token/gửi
    mail — response vẫn giống hệt (§11.5)."""
    email = f"{uuid.uuid4().hex}@scarlet.example"
    await client.post(DUONG_DAN, json={"email": email, "password": "mot-mat-khau-du-manh-123"})
    token = _token_tu_verify_url(mailer_gia.calls[0]["ctx"]["verify_url"])
    await client.post(DUONG_DAN_VERIFY, json={"token": token})
    mailer_gia.calls.clear()

    resp = await client.post(DUONG_DAN_RESEND, json={"email": email})

    assert resp.status_code == 200
    assert mailer_gia.calls == []


# ═══════════════════════ POST /auth/login (T-2.3) ═══════════════════════════


@pytest.mark.usefixtures("_db_cua_test")
async def test_login_thanh_cong_tra_ve_thong_tin_user(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id, email = await _tao_user_that(session_factory)

    resp = await client.post(DUONG_DAN_LOGIN, json={"email": email, "password": _MAT_KHAU_TEST})

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(user_id)
    assert body["email"] == email
    assert body["status"] == "pending_email"
    assert body["role"] == "user"
    assert body["tier_name"] == "free"


@pytest.mark.usefixtures("_db_cua_test")
async def test_login_dat_ca_hai_cookie_dung_thuoc_tinh(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """DoD T-2.3: cookie refresh có đủ `HttpOnly`, `Secure`, `SameSite` — kiểm
    bằng `curl -i` trên stack thật là phép đo tay bổ sung (xem báo cáo); đây là
    phiên bản kiểm được bằng pytest cho cả hai cookie (phiên lẫn refresh)."""
    _, email = await _tao_user_that(session_factory)

    resp = await client.post(DUONG_DAN_LOGIN, json={"email": email, "password": _MAT_KHAU_TEST})

    set_cookie_headers = resp.headers.get_list("set-cookie")
    assert len(set_cookie_headers) == 2

    phien = next(h for h in set_cookie_headers if h.startswith(f"{SESSION_COOKIE_NAME}="))
    lower = phien.lower()
    assert "httponly" in lower
    assert "secure" in lower
    assert "samesite=lax" in lower
    assert "path=/api/v1;" in lower or lower.endswith("path=/api/v1")

    refresh_ck = next(h for h in set_cookie_headers if h.startswith(f"{REFRESH_COOKIE_NAME}="))
    lower_refresh = refresh_ck.lower()
    assert "httponly" in lower_refresh
    assert "secure" in lower_refresh
    assert "samesite=lax" in lower_refresh
    assert "path=/api/v1/auth" in lower_refresh


@pytest.mark.usefixtures("_db_cua_test")
async def test_login_sai_mat_khau_tra_401_invalid_credentials(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    _, email = await _tao_user_that(session_factory)

    resp = await client.post(DUONG_DAN_LOGIN, json={"email": email, "password": "sai-mat-khau"})

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == ApiErrorCode.INVALID_CREDENTIALS


@pytest.mark.usefixtures("_db_cua_test")
async def test_login_email_khong_ton_tai_tra_401_invalid_credentials(client: AsyncClient) -> None:
    """Chống dò (cùng tinh thần §11.5): KHÔNG có mã riêng cho "email không tồn
    tại" so với "sai mật khẩu" — cùng mã, cùng status."""
    resp = await client.post(
        DUONG_DAN_LOGIN,
        json={"email": f"{uuid.uuid4().hex}@khong-ton-tai.example", "password": "gi-cung-duoc"},
    )

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == ApiErrorCode.INVALID_CREDENTIALS


@pytest.mark.usefixtures("_db_cua_test")
async def test_login_khong_kiem_trang_thai_pending_email_van_dang_nhap_duoc(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """§11.1: `pending_email` vẫn đăng nhập được — chặn theo trạng thái là việc
    của T-2.7, không phải T-2.3."""
    _, email = await _tao_user_that(session_factory)

    resp = await client.post(DUONG_DAN_LOGIN, json={"email": email, "password": _MAT_KHAU_TEST})

    assert resp.status_code == 200


# ═══════════════════════ GET /auth/me (T-2.3) ═══════════════════════════════


@pytest.mark.usefixtures("_db_cua_test")
async def test_me_sau_khi_login_tra_dung_user(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id, email = await _tao_user_that(session_factory)
    await client.post(DUONG_DAN_LOGIN, json={"email": email, "password": _MAT_KHAU_TEST})

    resp = await client.get(DUONG_DAN_ME)

    assert resp.status_code == 200
    assert resp.json()["id"] == str(user_id)


async def test_me_khong_dang_nhap_tra_401(client: AsyncClient) -> None:
    """Không cookie, không header, `DEBUG=false` (mặc định test) → nhánh Phase 1
    đóng, và giờ nhánh mới cũng không có cookie phiên nào để thử."""
    resp = await client.get(DUONG_DAN_ME)

    assert resp.status_code in (401, 503)  # xem app/core/deps.py — 503 la nhanh Phase 1


@pytest.mark.usefixtures("_db_cua_test")
async def test_access_token_het_han_tra_401_token_expired(
    client: AsyncClient, user_a: uuid.UUID
) -> None:
    """DoD T-2.3: access token hết hạn → 401 `TOKEN_EXPIRED`, phân biệt với
    token sai (test kế bên)."""
    token_het_han = encode_access_token(
        user_id=user_a,
        role=UserRole.USER,
        tier="free",
        status=UserStatus.PENDING_EMAIL,
        ttl_minutes=-1,
    )
    client.cookies.set(SESSION_COOKIE_NAME, token_het_han)

    resp = await client.get(DUONG_DAN_ME)

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == ApiErrorCode.TOKEN_EXPIRED


async def test_access_token_sai_tra_401_unauthenticated_khac_token_expired(
    client: AsyncClient,
) -> None:
    """Token sai chữ ký/định dạng → `UNAUTHENTICATED`, KHÁC `TOKEN_EXPIRED`
    của test trên (DoD: "phân biệt với token sai")."""
    client.cookies.set(SESSION_COOKIE_NAME, "khong-phai-jwt-hop-le")

    resp = await client.get(DUONG_DAN_ME)

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == ApiErrorCode.UNAUTHENTICATED


# ═══════════════════════ POST /auth/refresh (T-2.3) ═════════════════════════


@pytest.mark.usefixtures("_db_cua_test")
async def test_refresh_xoay_vong_sinh_cookie_moi_va_van_dang_nhap_duoc(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    _, email = await _tao_user_that(session_factory)
    await client.post(DUONG_DAN_LOGIN, json={"email": email, "password": _MAT_KHAU_TEST})
    refresh_token_cu = client.cookies.get(REFRESH_COOKIE_NAME)
    assert refresh_token_cu is not None

    resp = await client.post(DUONG_DAN_REFRESH)

    assert resp.status_code == 200
    refresh_token_moi = client.cookies.get(REFRESH_COOKIE_NAME)
    assert refresh_token_moi is not None
    assert refresh_token_moi != refresh_token_cu

    # Cookie phiên mới cũng phải dùng được ngay (không cần login lại).
    resp_me = await client.get(DUONG_DAN_ME)
    assert resp_me.status_code == 200


@pytest.mark.usefixtures("_db_cua_test")
async def test_refresh_thieu_cookie_tra_401(client: AsyncClient) -> None:
    resp = await client.post(DUONG_DAN_REFRESH)

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == ApiErrorCode.UNAUTHENTICATED


@pytest.mark.usefixtures("_db_cua_test")
async def test_refresh_token_gia_tra_401(client: AsyncClient) -> None:
    client.cookies.set(REFRESH_COOKIE_NAME, "token-bia-dat-khong-ton-tai")

    resp = await client.post(DUONG_DAN_REFRESH)

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == ApiErrorCode.UNAUTHENTICATED


@pytest.mark.usefixtures("_db_cua_test")
async def test_refresh_dung_lai_token_da_dung_tra_401_va_thu_hoi_ca_family(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """DoD T-2.3: dùng refresh token 2 lần → lần 2 trả 401 VÀ
    `SELECT revoked_at FROM refresh_tokens WHERE family_id=...` → tất cả khác
    NULL (cả token đã dùng lẫn token vừa xoay ra còn hợp lệ)."""
    _, email = await _tao_user_that(session_factory)
    await client.post(DUONG_DAN_LOGIN, json={"email": email, "password": _MAT_KHAU_TEST})
    token_dau_tien = client.cookies.get(REFRESH_COOKIE_NAME)
    assert token_dau_tien is not None

    # Lần 1 — hợp lệ, xoay vòng sinh token thứ hai.
    resp1 = await client.post(DUONG_DAN_REFRESH)
    assert resp1.status_code == 200

    # Lần 2 — trình LẠI token đầu tiên (đã dùng) → tái sử dụng.
    client.cookies.set(REFRESH_COOKIE_NAME, token_dau_tien)
    resp2 = await client.post(DUONG_DAN_REFRESH)

    assert resp2.status_code == 401
    assert resp2.json()["error"]["code"] == ApiErrorCode.UNAUTHENTICATED

    async with session_factory() as session:
        stmt = select(RefreshToken.family_id, RefreshToken.revoked_at).where(
            RefreshToken.user_id
            == (await session.execute(select(User.id).where(User.email == email))).scalar_one()
        )
        rows = (await session.execute(stmt)).all()

    assert len(rows) >= 2, "phai co it nhat token dau tien + token xoay ra lan 1"
    assert all(revoked_at is not None for _family_id, revoked_at in rows)
    assert len({family_id for family_id, _r in rows}) == 1, "ca family phai cung mot family_id"


@pytest.mark.usefixtures("_db_cua_test")
async def test_refresh_sau_khi_bi_thu_hoi_van_401(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Sau khi family đã bị thu hồi (test trên), ngay cả token MỚI NHẤT (chưa
    từng bị coi là tái sử dụng) cũng không dùng lại được nữa."""
    _, email = await _tao_user_that(session_factory)
    await client.post(DUONG_DAN_LOGIN, json={"email": email, "password": _MAT_KHAU_TEST})
    token_dau_tien = client.cookies.get(REFRESH_COOKIE_NAME)
    await client.post(DUONG_DAN_REFRESH)  # sinh token thứ hai
    token_thu_hai = client.cookies.get(REFRESH_COOKIE_NAME)
    client.cookies.set(REFRESH_COOKIE_NAME, token_dau_tien)
    await client.post(DUONG_DAN_REFRESH)  # tai su dung -> thu hoi ca family

    client.cookies.set(REFRESH_COOKIE_NAME, token_thu_hai)
    resp = await client.post(DUONG_DAN_REFRESH)

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == ApiErrorCode.UNAUTHENTICATED


# ═══════════════════════ Kiểm Origin (NQ-36, B-114) ══════════════════════════


@pytest.mark.usefixtures("_db_cua_test")
async def test_origin_khop_thi_cho_qua(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    _, email = await _tao_user_that(session_factory)

    resp = await client.post(
        DUONG_DAN_LOGIN,
        json={"email": email, "password": _MAT_KHAU_TEST},
        headers={"Origin": "https://localhost"},
    )

    assert resp.status_code == 200


@pytest.mark.usefixtures("_db_cua_test")
async def test_origin_khong_khop_bi_chan_403(client: AsyncClient) -> None:
    resp = await client.post(
        DUONG_DAN_LOGIN,
        json={"email": "khong-quan-trong@scarlet.example", "password": "x"},
        headers={"Origin": "https://ke-tan-cong.example"},
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == ApiErrorCode.FORBIDDEN


async def test_origin_vang_mat_thi_cho_qua(client: AsyncClient) -> None:
    """Không có `Origin` (mọi client hiện có: `curl`, `httpx`, script) → không
    bị chặn — xem docstring `app/core/origin.py` cho lý do."""
    resp = await client.get("/api/v1/models")

    assert resp.status_code == 200
