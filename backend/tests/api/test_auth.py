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

from app.core.errors import ApiErrorCode
from app.core.security import hash_email_token
from app.db.models import EmailToken, EmailTokenPurpose, User
from app.db.repositories.users import UserRepository
from app.main import app

DUONG_DAN = "/api/v1/auth/register"
DUONG_DAN_VERIFY = "/api/v1/auth/verify-email"
DUONG_DAN_RESEND = "/api/v1/auth/resend-verification"


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
