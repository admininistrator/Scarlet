"""`POST /auth/register` + `/verify-email` + `/resend-verification` (§11.1,
§11.5, §11.6, UC-01) — T-2.1, T-2.2. `/login` + `/refresh` + `/me` (§11.2) —
T-2.3. `/logout` + blacklist (§11.3, C21) — T-2.4.

Cùng mô hình với `test_conversations.py`: `httpx.ASGITransport`, và
`session_scope()` trong handler bị trỏ về đúng kết nối của test qua
`_db_cua_test`. Ba endpoint của T-2.1/T-2.2 không đi
qua `Depends(get_current_user_id)` — đều công khai — còn `/me` đi vào bằng
cookie phiên thật (T-2.3), không phải nhánh tạm DEBUG của Phase 1.

`fake_mailer` (T-2.2) thay `app.api.v1.auth.mailer` bằng một stub ghi lại lời
gọi thay vì gửi SMTP thật: bộ test này kiểm HÀNH VI của handler (có gọi
`mailer.send` không, với `template`/`ctx` gì), không kiểm hạ tầng SMTP — phần
"thư có thật sự tới Mailpit trong ≤ 5 s" là phép đo tay trên stack thật (báo
cáo T-2.2 mục 2), không phải thứ `pytest` nên giả lập lại.

`fake_redis` (T-2.4) là **autouse**, khác `fake_mailer`, và khác cả `fake_redis`
của `test_messages_cancel.py` (nơi nó chỉ ghi lại lời gọi). Hai lý do:

1. Từ T-2.4, **mọi** request mang cookie phiên đều hỏi Redis xem token có bị
   thu hồi chưa (§11.3, `app/core/deps.py`), nên các test T-2.3 vốn đang xanh
   sẽ chuyển thành `503` nếu không có Redis — `redis:6379` chỉ phân giải được
   bên trong network `internal` của compose, còn `pytest` chạy từ WSL host.
2. Blacklist là một cái **kho**, không phải một lời gọi: phép kiểm của T-2.4 là
   "ghi vào rồi request sau có bị chặn không", nên stub phải nhớ được thứ nó
   đã ghi, kèm TTL (DoD dòng 3 đọc đúng TTL đó).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.v1.auth import REFRESH_COOKIE_NAME
from app.config.settings import settings
from app.core import turnstile as turnstile_mod
from app.core.access_token import decode_access_token, encode_access_token
from app.core.blacklist import jti_key, revoke_all_sessions, user_key
from app.core.deps import SESSION_COOKIE_NAME
from app.core.errors import ApiErrorCode
from app.core.security import hash_email_token, hash_password, verify_password
from app.db.models import EmailToken, EmailTokenPurpose, RefreshToken, User, UserRole, UserStatus
from app.db.repositories.users import UserRepository
from app.main import app

PATH = "/api/v1/auth/register"
VERIFY_PATH = "/api/v1/auth/verify-email"
RESEND_PATH = "/api/v1/auth/resend-verification"
LOGIN_PATH = "/api/v1/auth/login"
REFRESH_PATH = "/api/v1/auth/refresh"
ME_PATH = "/api/v1/auth/me"
LOGOUT_PATH = "/api/v1/auth/logout"
FORGOT_PASSWORD_PATH = "/api/v1/auth/forgot-password"
RESET_PASSWORD_PATH = "/api/v1/auth/reset-password"

#: Mật khẩu thật dùng trong test login — khác `user_a`/`user_b` của
#: `conftest.py` (những fixture đó gán `password_hash="khong-phai-hash-that"`,
#: một chuỗi KHÔNG phải Argon2 hợp lệ, nên `verify_password` luôn trả `False`
#: cho chúng — đúng ý đồ của conftest, vốn chỉ cần một user tồn tại cho các
#: test IDOR chứ không cần đăng nhập được).
_TEST_PASSWORD = "mot-mat-khau-du-manh-cho-test-login-123"

#: Hai mật khẩu mới của T-2.5. Hai chứ không một: test "dùng token hai lần"
#: phải chứng minh lần thứ hai KHÔNG đổi được gì, mà muốn vậy thì lần hai phải
#: xin một mật khẩu KHÁC lần một — trùng nhau thì phép kiểm không phân biệt
#: được "bị từ chối" với "đổi lại đúng thứ đang có".
_NEW_PASSWORD = "mot-mat-khau-moi-du-manh-cho-t25-456"
_NEW_PASSWORD_2 = "mot-mat-khau-moi-nua-du-manh-cho-t25-789"


@pytest.fixture
def _db_for_tests(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`session_scope()` trong handler trỏ vào ĐÚNG kết nối của test (NQ-17)."""
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as http:
        yield http


class _FakeMailer:
    """Stub `Mailer` (§11.5, T-2.2): ghi lại lời gọi thay vì gửi SMTP thật."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def send(self, *, template: str, to: str, ctx: dict[str, Any]) -> None:
        self.calls.append({"template": template, "to": to, "ctx": ctx})


@pytest.fixture
def fake_mailer(monkeypatch: pytest.MonkeyPatch) -> _FakeMailer:
    """Thay `app.api.v1.auth.mailer` — patch đúng tên đã import vào module đó,
    không phải `app.core.mailer.mailer` (import đã chép tham chiếu ra rồi)."""
    stub = _FakeMailer()
    monkeypatch.setattr("app.api.v1.auth.mailer", stub)
    return stub


class _FakeRedis:
    """Redis trong bộ nhớ — blacklist (T-2.4) + bộ đếm rate limit (B-127/B-131).

    Giữ cả TTL đã đặt cho từng khoá vì DoD dòng 3 của T-2.4 đo đúng nó
    (`redis-cli TTL bl:jti:{jti}` ≤ 900, **không** phải `-1`). `ttl()` trả về
    `-2`/`-1` đúng quy ước Redis (không có khoá / có khoá nhưng không TTL) chứ
    không trả `None`: nếu stub tự bịa quy ước riêng thì test có thể xanh trong
    khi `redis-cli` trên stack thật nói chuyện khác.

    **HAI công tắc hỏng, không phải một.** Từ B-127/B-131, một request tới
    `/auth/logout` hỏi Redis ở **hai** bước khác nhau: bộ đếm rate limit
    (dependency, chạy trước) rồi blacklist (thân handler). Một công tắc chung
    sẽ làm mọi test "Redis chết" đo đúng chỗ ĐẦU TIÊN, và nửa sau — chính là
    nửa mà C21 quan tâm — mất phép kiểm mà không ai thấy. `raises` giữ nguyên
    nghĩa cũ (các lệnh của blacklist), `counter_raises` là của bộ đếm.
    """

    def __init__(self) -> None:
        self.store: dict[str, tuple[str, int | None]] = {}
        self.counts: dict[str, int] = {}
        self.counter_ttls: dict[str, int] = {}
        self.raises = False
        self.counter_raises = False

    async def set(self, name: str, value: str, *, ex: int | None = None) -> bool:
        if self.raises:
            raise ConnectionError("redis chet (gia lap)")
        self.store[name] = (value, ex)
        return True

    async def mget(self, keys: list[str]) -> list[str | None]:
        if self.raises:
            raise ConnectionError("redis chet (gia lap)")
        return [self.store[k][0] if k in self.store else None for k in keys]

    async def incr(self, name: str) -> int:
        if self.counter_raises:
            raise ConnectionError("redis chet (gia lap)")
        self.counts[name] = self.counts.get(name, 0) + 1
        return self.counts[name]

    async def expire(self, name: str, time: int, *, nx: bool = False) -> bool:
        if self.counter_raises:
            raise ConnectionError("redis chet (gia lap)")
        if nx and name in self.counter_ttls:
            return False
        self.counter_ttls[name] = time
        return True

    async def ttl(self, name: str) -> int:
        if name in self.store:
            ex = self.store[name][1]
            return -1 if ex is None else ex
        if name in self.counts:
            return self.counter_ttls.get(name, -1)
        return -2


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    """Autouse — xem docstring module cho lý do (T-2.4).

    Từ B-127/B-131 phải patch thêm `app.core.ratelimit.get_redis`: dependency
    rate limit chạy TRƯỚC handler, nên không patch nghĩa là mọi route có hạn
    mức trả `503` (không nối được `redis:6379` từ WSL host) chứ không phải mã
    mà test đang chờ.
    """
    fake = _FakeRedis()
    monkeypatch.setattr("app.core.deps.get_redis", lambda: fake)
    monkeypatch.setattr("app.api.v1.auth.get_redis", lambda: fake)
    monkeypatch.setattr("app.core.ratelimit.get_redis", lambda: fake)
    return fake


def _token_from_url(url: str) -> str:
    """Token bản rõ moi ra khỏi link trong thư — dùng cho cả `verify_url`
    (T-2.2) lẫn `reset_url` (T-2.5): hai template, một hình dạng `?token=`."""
    return parse_qs(urlsplit(url).query)["token"][0]


async def _create_real_user(
    session_factory: async_sessionmaker[AsyncSession], *, password: str = _TEST_PASSWORD
) -> tuple[uuid.UUID, str]:
    """User với hash Argon2id THẬT của `mat_khau` — dùng cho test login."""
    email = f"{uuid.uuid4().hex}@scarlet.example"
    async with session_factory() as session:
        user = await UserRepository(session).create_pending_user(
            email=email, password_hash=await hash_password(password)
        )
        assert user is not None
        await session.commit()
        return user.id, email


async def _count_users_by_email(
    session_factory: async_sessionmaker[AsyncSession], email: str
) -> int:
    async with session_factory() as session:
        stmt = select(func.count()).select_from(User).where(User.email == email)
        return int((await session.execute(stmt)).scalar_one())


# ═══════════════════════ POST /auth/register — thành công ═══════════════════


@pytest.mark.usefixtures("_db_for_tests")
async def test_register_success_creates_one_pending_email_user(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    email = f"{uuid.uuid4().hex}@scarlet.example"

    resp = await client.post(PATH, json={"email": email, "password": "mot-mat-khau-du-manh-123"})

    assert resp.status_code == 200
    assert await _count_users_by_email(session_factory, email) == 1

    async with session_factory() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        # DoD: `SELECT password_hash FROM users` bắt đầu bằng `$argon2id$`.
        assert user.password_hash.startswith("$argon2id$")
        assert user.status.value == "pending_email"
        # Tier mặc định (server_default) — không có literal "free" trong auth.py.
        assert user.tier_name == "free"


@pytest.mark.usefixtures("_db_for_tests")
async def test_register_twice_same_email_identical_responses_one_user(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """DoD T-2.1: đăng ký hai lần cùng email → hai response giống nhau từng
    byte, DB có đúng MỘT user. Đây là §11.5 (chống dò) ở dạng kiểm được."""
    email = f"{uuid.uuid4().hex}@scarlet.example"
    body = {"email": email, "password": "mot-mat-khau-du-manh-123"}

    resp1 = await client.post(PATH, json=body)
    resp2 = await client.post(PATH, json=body)

    assert resp1.status_code == resp2.status_code == 200
    assert resp1.content == resp2.content

    assert await _count_users_by_email(session_factory, email) == 1


# ═══════════════════════ POST /auth/register — mật khẩu yếu ═════════════════


async def test_common_password_is_422(client: AsyncClient) -> None:
    """DoD T-2.1: mật khẩu `password1234` → `422` với lý do "quá phổ biến"."""
    resp = await client.post(
        PATH,
        json={"email": f"{uuid.uuid4().hex}@scarlet.example", "password": "password1234"},
    )

    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == ApiErrorCode.PASSWORD_TOO_WEAK
    assert "pho bien" in body["error"]["message"]


async def test_password_under_12_chars_is_422(client: AsyncClient) -> None:
    resp = await client.post(
        PATH,
        # 11 ký tự — dưới ngưỡng PASSWORD_MIN_LENGTH=12.
        json={"email": f"{uuid.uuid4().hex}@scarlet.example", "password": "Ab1#Ab1#Ab1"},
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == ApiErrorCode.PASSWORD_TOO_SHORT


async def test_malformed_email_is_422_validation_error(client: AsyncClient) -> None:
    resp = await client.post(
        PATH,
        json={"email": "khong-phai-email", "password": "mot-mat-khau-du-manh-123"},
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == ApiErrorCode.VALIDATION_ERROR


# ═══════════════════ POST /auth/register — gửi email verify (T-2.2) ═════════


@pytest.mark.usefixtures("_db_for_tests")
async def test_register_success_calls_mailer_with_verify_url(
    client: AsyncClient, fake_mailer: _FakeMailer
) -> None:
    """DoD T-2.2 (rút gọn cho unit test): đăng ký gọi đúng một lần
    `mailer.send(template="verify_email", ...)` với `verify_url` mang token.
    Phép đo "thư tới Mailpit trong ≤ 5 s" chạy tay trên stack thật — xem báo
    cáo mục 2, không phải thứ một unit test nên giả lập lại hạ tầng SMTP."""
    email = f"{uuid.uuid4().hex}@scarlet.example"

    resp = await client.post(PATH, json={"email": email, "password": "mot-mat-khau-du-manh-123"})

    assert resp.status_code == 200
    assert len(fake_mailer.calls) == 1
    call = fake_mailer.calls[0]
    assert call["template"] == "verify_email"
    assert call["to"] == email
    assert "token=" in call["ctx"]["verify_url"]
    assert call["ctx"]["ttl_minutes"] > 0


@pytest.mark.usefixtures("_db_for_tests")
async def test_register_existing_email_does_not_mail_twice(
    client: AsyncClient, fake_mailer: _FakeMailer
) -> None:
    """Nhánh 'email đã tồn tại' không đọc/ghi gì thêm (§11.5) — kể cả không
    phát hành token/gửi mail lần thứ hai."""
    email = f"{uuid.uuid4().hex}@scarlet.example"
    body = {"email": email, "password": "mot-mat-khau-du-manh-123"}

    await client.post(PATH, json=body)
    fake_mailer.calls.clear()
    await client.post(PATH, json=body)

    assert fake_mailer.calls == []


# ═══════════════════════ POST /auth/verify-email (T-2.2) ════════════════════


@pytest.mark.usefixtures("_db_for_tests")
async def test_verify_email_valid_token_sets_pending_approval(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    fake_mailer: _FakeMailer,
) -> None:
    """DoD T-2.2: bấm link → status đổi `pending_approval`."""
    email = f"{uuid.uuid4().hex}@scarlet.example"
    await client.post(PATH, json={"email": email, "password": "mot-mat-khau-du-manh-123"})
    token = _token_from_url(fake_mailer.calls[0]["ctx"]["verify_url"])

    resp = await client.post(VERIFY_PATH, json={"token": token})

    assert resp.status_code == 200
    assert resp.json() == {"status": "verified"}

    async with session_factory() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        assert user.status.value == "pending_approval"
        assert user.email_verified_at is not None


@pytest.mark.usefixtures("_db_for_tests")
async def test_verify_email_second_click_is_not_an_error(
    client: AsyncClient, fake_mailer: _FakeMailer
) -> None:
    """DoD T-2.2: bấm lại cùng link → không lỗi, idempotent (UC-01).

    T-3.1b tách `already_verified` khỏi `verified` — xem docstring
    `VerifyEmailResponse.status`. Thứ UC-01 dòng 5 đòi vẫn nguyên: cùng `200`,
    không lỗi, không tác dụng phụ. Thứ đổi là FE nay **biết** đây là lần thứ
    hai, nên nó đưa người dùng tới `/dang-nhap` thay vì `/cho-duyet`.
    """
    email = f"{uuid.uuid4().hex}@scarlet.example"
    await client.post(PATH, json={"email": email, "password": "mot-mat-khau-du-manh-123"})
    token = _token_from_url(fake_mailer.calls[0]["ctx"]["verify_url"])

    resp1 = await client.post(VERIFY_PATH, json={"token": token})
    resp2 = await client.post(VERIFY_PATH, json={"token": token})

    assert resp1.status_code == resp2.status_code == 200
    assert resp1.json() == {"status": "verified"}
    assert resp2.json() == {"status": "already_verified"}


@pytest.mark.usefixtures("_db_for_tests")
async def test_verify_email_second_time_changes_NOTHING_in_db(
    client: AsyncClient,
    fake_mailer: _FakeMailer,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """`already_verified` là một cái tên khác, không một hành vi khác.

    Ca này canh đúng chỗ dễ hỏng khi tách nhánh: `email_verified_at` của lần
    đầu không được ghi đè bởi lần thứ hai, và `status` không được nhảy thêm
    một bước nào.
    """
    email = f"{uuid.uuid4().hex}@scarlet.example"
    await client.post(PATH, json={"email": email, "password": "mot-mat-khau-du-manh-123"})
    token = _token_from_url(fake_mailer.calls[0]["ctx"]["verify_url"])

    await client.post(VERIFY_PATH, json={"token": token})
    async with session_factory() as session:
        user = await UserRepository(session).get_by_email(email)
        assert user is not None
        first_verified_at = user.email_verified_at

    await client.post(VERIFY_PATH, json={"token": token})

    async with session_factory() as session:
        user = await UserRepository(session).get_by_email(email)
        assert user is not None
        assert user.email_verified_at == first_verified_at
        assert user.status.value == "pending_approval"


@pytest.mark.usefixtures("_db_for_tests")
async def test_verify_email_unknown_token_is_400(client: AsyncClient) -> None:
    resp = await client.post(VERIFY_PATH, json={"token": "token-bia-dat-khong-ton-tai"})

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == ApiErrorCode.TOKEN_INVALID


@pytest.mark.usefixtures("_db_for_tests")
async def test_verify_email_expired_is_200_not_500(
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

    resp = await client.post(VERIFY_PATH, json={"token": raw_token})

    assert resp.status_code == 200
    assert resp.json() == {"status": "expired"}


@pytest.mark.usefixtures("_db_for_tests")
async def test_token_hash_does_not_contain_plaintext_token(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    fake_mailer: _FakeMailer,
) -> None:
    """DoD T-2.2: `SELECT token_hash FROM email_tokens` không dòng nào chứa
    token bản rõ có trong URL."""
    email = f"{uuid.uuid4().hex}@scarlet.example"
    await client.post(PATH, json={"email": email, "password": "mot-mat-khau-du-manh-123"})
    raw_token = _token_from_url(fake_mailer.calls[0]["ctx"]["verify_url"])

    async with session_factory() as session:
        hashes = (await session.execute(select(EmailToken.token_hash))).scalars().all()

    assert raw_token not in hashes
    assert hash_email_token(raw_token) in hashes


# ═══════════════════ POST /auth/resend-verification (T-2.2) ═════════════════


@pytest.mark.usefixtures("_db_for_tests")
async def test_resend_verification_pending_email_user_gets_new_token(
    client: AsyncClient, fake_mailer: _FakeMailer
) -> None:
    email = f"{uuid.uuid4().hex}@scarlet.example"
    await client.post(PATH, json={"email": email, "password": "mot-mat-khau-du-manh-123"})
    fake_mailer.calls.clear()

    resp = await client.post(RESEND_PATH, json={"email": email})

    assert resp.status_code == 200
    assert len(fake_mailer.calls) == 1
    assert fake_mailer.calls[0]["to"] == email


@pytest.mark.usefixtures("_db_for_tests")
async def test_resend_verification_unknown_email_same_response(
    client: AsyncClient, fake_mailer: _FakeMailer
) -> None:
    """Chống dò (§11.5, cùng lối register): response giống hệt dù email không
    tồn tại, và không gửi mail nào."""
    resp1 = await client.post(
        RESEND_PATH, json={"email": f"{uuid.uuid4().hex}@khong-ton-tai.example"}
    )
    resp2 = await client.post(
        RESEND_PATH, json={"email": f"{uuid.uuid4().hex}@khong-ton-tai.example"}
    )

    assert resp1.status_code == resp2.status_code == 200
    assert resp1.content == resp2.content
    assert fake_mailer.calls == []


@pytest.mark.usefixtures("_db_for_tests")
async def test_resend_verification_verified_user_gets_no_mail(
    client: AsyncClient, fake_mailer: _FakeMailer
) -> None:
    """Resend cho user đã qua khỏi `pending_email` không phát hành token/gửi
    mail — response vẫn giống hệt (§11.5)."""
    email = f"{uuid.uuid4().hex}@scarlet.example"
    await client.post(PATH, json={"email": email, "password": "mot-mat-khau-du-manh-123"})
    token = _token_from_url(fake_mailer.calls[0]["ctx"]["verify_url"])
    await client.post(VERIFY_PATH, json={"token": token})
    fake_mailer.calls.clear()

    resp = await client.post(RESEND_PATH, json={"email": email})

    assert resp.status_code == 200
    assert fake_mailer.calls == []


# ═══════════════════════ POST /auth/login (T-2.3) ═══════════════════════════


@pytest.mark.usefixtures("_db_for_tests")
async def test_login_success_returns_user_info(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id, email = await _create_real_user(session_factory)

    resp = await client.post(LOGIN_PATH, json={"email": email, "password": _TEST_PASSWORD})

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(user_id)
    assert body["email"] == email
    assert body["status"] == "pending_email"
    assert body["role"] == "user"
    assert body["tier_name"] == "free"


@pytest.mark.usefixtures("_db_for_tests")
async def test_login_sets_both_cookies_with_right_attributes(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """DoD T-2.3: cookie refresh có đủ `HttpOnly`, `Secure`, `SameSite` — kiểm
    bằng `curl -i` trên stack thật là phép đo tay bổ sung (xem báo cáo); đây là
    phiên bản kiểm được bằng pytest cho cả hai cookie (phiên lẫn refresh)."""
    _, email = await _create_real_user(session_factory)

    resp = await client.post(LOGIN_PATH, json={"email": email, "password": _TEST_PASSWORD})

    set_cookie_headers = resp.headers.get_list("set-cookie")
    assert len(set_cookie_headers) == 2

    session = next(h for h in set_cookie_headers if h.startswith(f"{SESSION_COOKIE_NAME}="))
    lower = session.lower()
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


@pytest.mark.usefixtures("_db_for_tests")
async def test_login_wrong_password_401_invalid_credentials(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    _, email = await _create_real_user(session_factory)

    resp = await client.post(LOGIN_PATH, json={"email": email, "password": "sai-mat-khau"})

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == ApiErrorCode.INVALID_CREDENTIALS


@pytest.mark.usefixtures("_db_for_tests")
async def test_login_unknown_email_401_invalid_credentials(client: AsyncClient) -> None:
    """Chống dò (cùng tinh thần §11.5): KHÔNG có mã riêng cho "email không tồn
    tại" so với "sai mật khẩu" — cùng mã, cùng status."""
    resp = await client.post(
        LOGIN_PATH,
        json={"email": f"{uuid.uuid4().hex}@khong-ton-tai.example", "password": "gi-cung-duoc"},
    )

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == ApiErrorCode.INVALID_CREDENTIALS


@pytest.mark.usefixtures("_db_for_tests")
async def test_login_pending_email_status_can_still_log_in(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """§11.1: `pending_email` vẫn đăng nhập được — chặn theo trạng thái là việc
    của T-2.7, không phải T-2.3."""
    _, email = await _create_real_user(session_factory)

    resp = await client.post(LOGIN_PATH, json={"email": email, "password": _TEST_PASSWORD})

    assert resp.status_code == 200


# ═══════════════════════ GET /auth/me (T-2.3) ═══════════════════════════════


@pytest.mark.usefixtures("_db_for_tests")
async def test_me_after_login_returns_right_user(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id, email = await _create_real_user(session_factory)
    await client.post(LOGIN_PATH, json={"email": email, "password": _TEST_PASSWORD})

    resp = await client.get(ME_PATH)

    assert resp.status_code == 200
    assert resp.json()["id"] == str(user_id)


@pytest.mark.usefixtures("_db_for_tests")
async def test_me_returns_all_four_groups_of_18_1(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """§18.1: *"User + tier + quota còn lại + trạng thái"* — T-3.0, B-158.

    Một test cho cả bốn nhóm chứ không bốn test: NQ-81 gộp ba mảnh backend của
    P3 vào **một** response schema chính vì chúng phải cùng có mặt trong cùng
    một lần gọi; tách ra kiểm riêng là bỏ mất đúng tính chất ấy.
    """
    _, email = await _create_real_user(session_factory)
    await client.post(LOGIN_PATH, json={"email": email, "password": _TEST_PASSWORD})

    body = (await client.get(ME_PATH)).json()

    assert body["tier_name"] == "free"
    assert body["status"] == UserStatus.PENDING_EMAIL.value
    assert body["message_max_chars"] == settings.MESSAGE_MAX_CHARS
    assert body["quota_warn_remaining_pct"] == settings.QUOTA_WARN_REMAINING_PCT, (
        "T-3.11: FE doc nguong canh bao tu day, cung bien voi quota_warning cua 202"
    )
    assert body["default_model"] is None, "chua ai chon gi ⇒ FE roi ve default cua catalog"
    assert body["limits_cache_ttl_s"] == settings.TIER_CACHE_TTL_S, (
        "T-S.11: tab Muc su dung noi 'co hieu luc trong N giay' — N doc tu day (A3)"
    )
    assert body["stream_ttl_s"] == settings.STREAM_TTL_S, (
        "T-S.13: sidebar nghe tieu de chay trong cua so nay, het cua so = het han (A3)"
    )
    # T-S.5 — hồ sơ của Phase S, người chưa từng `PUT /settings`.
    assert body["display_name"] is None, "NQ-116: FE hien nguyen email"
    assert body["display_name_max_chars"] == settings.DISPLAY_NAME_MAX_CHARS
    assert body["avatar_color"] is None, "chua co hang user_settings ⇒ mau mac dinh cua FE"
    assert body["reasoning_prefs"] == {}
    assert body["last_login_at"] is not None, "vua dang nhap xong"

    assert [w["limit_type"] for w in body["quota"]] == ["5h", "weekly"], "du HAI cua so (§10.3)"
    for window in body["quota"]:
        # A7/T-2.16: tiền đi tới FE dưới dạng CHUỖI, không `float`.
        assert isinstance(window["limit_usd"], str)
        assert isinstance(window["spent_usd"], str)
        assert isinstance(window["remaining_usd"], str)
        assert window["spent_usd"] == "0"
        assert window["retry_after"] is None, "chua tieu gi thi khong co gi de cho"


@pytest.mark.usefixtures("_db_for_tests")
async def test_me_with_dead_redis_still_200_with_null_quota(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    quota_redis: Any,
) -> None:
    """Redis chớp mắt KHÔNG được khoá cả giao diện (xem `app/quota/snapshot.py`).

    Khác hẳn `check_quota`, nơi cùng sự cố ấy phải thành `503`: ở đó Redis chết
    nghĩa là không biết người ta còn bao nhiêu tiền trước một lượt **tiêu tiền**;
    ở đây nó chỉ nghĩa là một thanh trên màn hình chưa vẽ được. `/auth/me` còn
    là endpoint FE dùng để định tuyến theo `status` (§11.1, T-3.1b).
    """
    _, email = await _create_real_user(session_factory)
    await client.post(LOGIN_PATH, json={"email": email, "password": _TEST_PASSWORD})
    quota_redis.fail = True

    resp = await client.get(ME_PATH)

    assert resp.status_code == 200
    assert resp.json()["quota"] is None
    assert resp.json()["email"] == email, "phan ho so van day du"


@pytest.mark.usefixtures("_db_for_tests")
async def test_login_and_refresh_do_not_return_quota(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`quota` chỉ có ở `/me` — hai endpoint kia không trả giá hai lượt đọc Redis.

    Đây là ranh giới giữa `UserOut` và `ProfileOut`, và nó là một hợp đồng chứ
    không phải một chi tiết hiện thực: FE không được đọc `quota` từ response
    của `login` rồi tin rằng nó có ở đó.
    """
    _, email = await _create_real_user(session_factory)

    login_resp = await client.post(LOGIN_PATH, json={"email": email, "password": _TEST_PASSWORD})
    refreshed = await client.post(REFRESH_PATH)

    for resp in (login_resp, refreshed):
        assert resp.status_code == 200, resp.text
        assert "quota" not in resp.json()
        assert "message_max_chars" not in resp.json()
        assert "quota_warn_remaining_pct" not in resp.json()
        assert "limits_cache_ttl_s" not in resp.json()
        assert "stream_ttl_s" not in resp.json()
        assert resp.json()["default_model"] is None, "cot cua chinh hang users ⇒ co o ca ba"
        # T-S.5: hai trường của `user_settings` là một lượt đọc thêm ⇒ chỉ `/me`.
        assert "avatar_color" not in resp.json()
        assert "reasoning_prefs" not in resp.json()
        assert "display_name_max_chars" not in resp.json()


@pytest.mark.usefixtures("_db_for_tests")
async def test_login_stamps_last_login_at_and_refresh_does_not(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`last_login_at` đổi **đúng** khi đăng nhập lại — T-S.5, NQ-114.

    T-S.11 chạy thanh quota từ 0 khi giá trị này đổi. `refresh` mà cũng ghi thì
    F5 sau khi access token hết hạn chạy lại hoạt ảnh — đúng thứ Cạm bẫy ② của
    T-S.11 cấm; login mà không ghi thì đăng nhập lại không chạy.
    """
    user_id, email = await _create_real_user(session_factory)

    first = await client.post(LOGIN_PATH, json={"email": email, "password": _TEST_PASSWORD})
    stamped = first.json()["last_login_at"]
    refreshed = await client.post(REFRESH_PATH)
    me = await client.get(ME_PATH)
    second = await client.post(LOGIN_PATH, json={"email": email, "password": _TEST_PASSWORD})

    assert stamped is not None, "response cua login mang dung gia tri vua ghi"
    assert refreshed.json()["last_login_at"] == stamped, "refresh KHONG phai dang nhap lai"
    assert me.json()["last_login_at"] == stamped
    restamped = datetime.fromisoformat(second.json()["last_login_at"])
    assert restamped > datetime.fromisoformat(stamped), "dang nhap lai ⇒ doi"
    async with session_factory() as session:
        column = await session.scalar(select(User.last_login_at).where(User.id == user_id))
    assert column == restamped, "cot trong DB = gia tri response tra ve"


@pytest.mark.usefixtures("_db_for_tests")
async def test_wrong_password_does_not_stamp_last_login_at(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id, email = await _create_real_user(session_factory)

    resp = await client.post(LOGIN_PATH, json={"email": email, "password": "sai-mat-khau-roi-123"})

    assert resp.status_code == 401
    async with session_factory() as session:
        column = await session.scalar(select(User.last_login_at).where(User.id == user_id))
    assert column is None


async def test_me_not_logged_in_is_401(client: AsyncClient) -> None:
    """Không cookie phiên ⇒ `401`, và `401` là kết cục DUY NHẤT (T-3.1c).

    Tới T-3.1b ca này phải nhận cả `503`: nhánh danh tính tạm Phase 1 trả mã
    ấy khi `DEBUG=false`. Nhánh đã chết, nên một `in (401, 503)` còn lại chỉ
    là một lưới rộng hơn thứ nó đang canh."""
    resp = await client.get(ME_PATH)

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


@pytest.mark.usefixtures("_db_for_tests")
async def test_expired_access_token_401_token_expired(
    client: AsyncClient, user_a: uuid.UUID
) -> None:
    """DoD T-2.3: access token hết hạn → 401 `TOKEN_EXPIRED`, phân biệt với
    token sai (test kế bên)."""
    expired_token = encode_access_token(
        user_id=user_a,
        role=UserRole.USER,
        tier="free",
        status=UserStatus.PENDING_EMAIL,
        ttl_minutes=-1,
    )
    client.cookies.set(SESSION_COOKIE_NAME, expired_token)

    resp = await client.get(ME_PATH)

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == ApiErrorCode.TOKEN_EXPIRED


async def test_bad_access_token_401_unauthenticated_not_token_expired(
    client: AsyncClient,
) -> None:
    """Token sai chữ ký/định dạng → `UNAUTHENTICATED`, KHÁC `TOKEN_EXPIRED`
    của test trên (DoD: "phân biệt với token sai")."""
    client.cookies.set(SESSION_COOKIE_NAME, "khong-phai-jwt-hop-le")

    resp = await client.get(ME_PATH)

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == ApiErrorCode.UNAUTHENTICATED


# ═══════════════════════ POST /auth/refresh (T-2.3) ═════════════════════════


@pytest.mark.usefixtures("_db_for_tests")
async def test_refresh_rotation_issues_new_cookie_and_stays_logged_in(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    _, email = await _create_real_user(session_factory)
    await client.post(LOGIN_PATH, json={"email": email, "password": _TEST_PASSWORD})
    old_refresh_token = client.cookies.get(REFRESH_COOKIE_NAME)
    assert old_refresh_token is not None

    resp = await client.post(REFRESH_PATH)

    assert resp.status_code == 200
    new_refresh_token = client.cookies.get(REFRESH_COOKIE_NAME)
    assert new_refresh_token is not None
    assert new_refresh_token != old_refresh_token

    # Cookie phiên mới cũng phải dùng được ngay (không cần login lại).
    resp_me = await client.get(ME_PATH)
    assert resp_me.status_code == 200


@pytest.mark.usefixtures("_db_for_tests")
async def test_refresh_missing_cookie_is_401(client: AsyncClient) -> None:
    resp = await client.post(REFRESH_PATH)

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == ApiErrorCode.UNAUTHENTICATED


@pytest.mark.usefixtures("_db_for_tests")
async def test_refresh_fake_token_is_401(client: AsyncClient) -> None:
    client.cookies.set(REFRESH_COOKIE_NAME, "token-bia-dat-khong-ton-tai")

    resp = await client.post(REFRESH_PATH)

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == ApiErrorCode.UNAUTHENTICATED


@pytest.mark.usefixtures("_db_for_tests")
async def test_refresh_reusing_used_token_401_and_revokes_family(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """DoD T-2.3: dùng refresh token 2 lần → lần 2 trả 401 VÀ
    `SELECT revoked_at FROM refresh_tokens WHERE family_id=...` → tất cả khác
    NULL (cả token đã dùng lẫn token vừa xoay ra còn hợp lệ)."""
    _, email = await _create_real_user(session_factory)
    await client.post(LOGIN_PATH, json={"email": email, "password": _TEST_PASSWORD})
    first_token = client.cookies.get(REFRESH_COOKIE_NAME)
    assert first_token is not None

    # Lần 1 — hợp lệ, xoay vòng sinh token thứ hai.
    resp1 = await client.post(REFRESH_PATH)
    assert resp1.status_code == 200

    # Lần 2 — trình LẠI token đầu tiên (đã dùng) → tái sử dụng.
    client.cookies.set(REFRESH_COOKIE_NAME, first_token)
    resp2 = await client.post(REFRESH_PATH)

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


@pytest.mark.usefixtures("_db_for_tests")
async def test_refresh_after_revocation_is_still_401(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Sau khi family đã bị thu hồi (test trên), ngay cả token MỚI NHẤT (chưa
    từng bị coi là tái sử dụng) cũng không dùng lại được nữa."""
    _, email = await _create_real_user(session_factory)
    await client.post(LOGIN_PATH, json={"email": email, "password": _TEST_PASSWORD})
    first_token = client.cookies.get(REFRESH_COOKIE_NAME)
    await client.post(REFRESH_PATH)  # sinh token thứ hai
    second_token = client.cookies.get(REFRESH_COOKIE_NAME)
    client.cookies.set(REFRESH_COOKIE_NAME, first_token)
    await client.post(REFRESH_PATH)  # tai su dung -> thu hoi ca family

    client.cookies.set(REFRESH_COOKIE_NAME, second_token)
    resp = await client.post(REFRESH_PATH)

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == ApiErrorCode.UNAUTHENTICATED


# ═══════════════════ POST /auth/logout + blacklist (T-2.4) ══════════════════


async def _login(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> tuple[uuid.UUID, str]:
    """Tạo user + đăng nhập trên `client`. Trả `(user_id, email)`."""
    user_id, email = await _create_real_user(session_factory)
    resp = await client.post(LOGIN_PATH, json={"email": email, "password": _TEST_PASSWORD})
    assert resp.status_code == 200
    return user_id, email


@pytest_asyncio.fixture
async def client_second_device() -> AsyncIterator[AsyncClient]:
    """Client THỨ HAI — "thiết bị khác" của DoD dòng 2 (jar cookie riêng)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as http:
        yield http


@pytest.mark.usefixtures("_db_for_tests")
async def test_logout_then_reusing_old_access_token_is_401(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """DoD T-2.4 dòng 1 (C21): lưu access token → logout → dùng lại → **401**."""
    await _login(client, session_factory)
    old_token = client.cookies.get(SESSION_COOKIE_NAME)
    assert old_token is not None
    assert (await client.get(ME_PATH)).status_code == 200, "truoc logout phai vao duoc"

    resp_logout = await client.post(LOGOUT_PATH)
    assert resp_logout.status_code == 200
    assert resp_logout.json() == {"status": "logged_out"}

    # "dùng lại token đó": cookie đã bị server xoá khỏi jar, nên đặt lại tay —
    # đúng thứ một kẻ đã chép được token sẽ làm.
    client.cookies.set(SESSION_COOKIE_NAME, old_token)
    resp_me = await client.get(ME_PATH)

    assert resp_me.status_code == 401
    assert resp_me.json()["error"]["code"] == ApiErrorCode.TOKEN_REVOKED


@pytest.mark.usefixtures("_db_for_tests")
async def test_logout_clears_both_cookies_on_right_path(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`delete_cookie` phải mang đúng `Path` đã `set_cookie`, nếu không trình
    duyệt giữ nguyên cookie cũ mà response vẫn 200 (xem `api/v1/auth.py`)."""
    await _login(client, session_factory)

    resp = await client.post(LOGOUT_PATH)

    headers = [h.lower() for h in resp.headers.get_list("set-cookie")]
    session = next(h for h in headers if h.startswith(f"{SESSION_COOKIE_NAME}="))
    refresh_ck = next(h for h in headers if h.startswith(f"{REFRESH_COOKIE_NAME}="))
    assert "path=/api/v1;" in session
    assert "path=/api/v1/auth" in refresh_ck
    # Cả hai đều phải hết hạn ngay (Max-Age=0 hoặc Expires trong quá khứ).
    assert "max-age=0" in session and "max-age=0" in refresh_ck
    assert client.cookies.get(SESSION_COOKIE_NAME) is None
    assert client.cookies.get(REFRESH_COOKIE_NAME) is None


@pytest.mark.usefixtures("_db_for_tests")
async def test_logout_sets_jti_blacklist_ttl_to_remaining_life_not_forever(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: _FakeRedis,
) -> None:
    """DoD T-2.4 dòng 3: `TTL bl:jti:{jti}` ≤ 900 và **không** phải `-1`.

    Cạm bẫy của task: "blacklist không có TTL sẽ phình vô hạn" — `-1` là đúng
    cái giá trị Redis trả cho một khoá không bao giờ hết hạn.
    """
    await _login(client, session_factory)
    token = client.cookies.get(SESSION_COOKIE_NAME)
    assert token is not None
    jti = decode_access_token(token).jti

    await client.post(LOGOUT_PATH)

    ttl = await fake_redis.ttl(jti_key(jti))
    assert ttl != -1, "khoa khong co TTL se phinh vo han"
    assert ttl != -2, "khoa phai ton tai"
    assert 0 < ttl <= settings.ACCESS_TOKEN_TTL_MIN * 60


@pytest.mark.usefixtures("_db_for_tests")
async def test_logout_revokes_refresh_family(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Nửa "+ revoke family" của §11.3: refresh token của phiên vừa đóng chết theo.

    Không có nửa này thì access token chết 15 phút còn refresh token sống tiếp
    30 ngày — logout chỉ là một hiệu ứng hình ảnh.
    """
    _, email = await _login(client, session_factory)
    old_refresh = client.cookies.get(REFRESH_COOKIE_NAME)
    assert old_refresh is not None

    await client.post(LOGOUT_PATH)

    client.cookies.set(REFRESH_COOKIE_NAME, old_refresh)
    resp = await client.post(REFRESH_PATH)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == ApiErrorCode.UNAUTHENTICATED

    async with session_factory() as session:
        uid = (await session.execute(select(User.id).where(User.email == email))).scalar_one()
        revoked = (
            (
                await session.execute(
                    select(RefreshToken.revoked_at).where(RefreshToken.user_id == uid)
                )
            )
            .scalars()
            .all()
        )
    assert revoked and all(r is not None for r in revoked)


@pytest.mark.usefixtures("_db_for_tests")
async def test_logout_closes_this_session_not_other_devices(
    client: AsyncClient,
    client_second_device: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """`bl:jti:` chặn MỘT token, không chặn tài khoản — đăng xuất trên điện
    thoại không được đá người dùng ra khỏi máy tính (§11.2 nói phiên, không
    nói tài khoản). Đây là phép kiểm ngược của test DoD dòng 2 ngay dưới."""
    _, email = await _create_real_user(session_factory)
    body = {"email": email, "password": _TEST_PASSWORD}
    assert (await client.post(LOGIN_PATH, json=body)).status_code == 200
    assert (await client_second_device.post(LOGIN_PATH, json=body)).status_code == 200

    await client.post(LOGOUT_PATH)

    assert (await client_second_device.get(ME_PATH)).status_code == 200


@pytest.mark.usefixtures("_db_for_tests")
async def test_password_change_kills_old_tokens_on_every_device(
    client: AsyncClient,
    client_second_device: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: _FakeRedis,
) -> None:
    """DoD T-2.4 dòng 2: đổi mật khẩu → mọi token cũ trên **mọi** thiết bị 401.

    Kích hoạt bằng `revoke_all_sessions()` chứ không bằng một endpoint: §18.1 KHÔNG
    có route đổi mật khẩu, và luồng đổi mật khẩu duy nhất của kế hoạch là
    `POST /auth/reset-password` — việc của T-2.5, vốn khai T-2.4 là phụ thuộc.
    T-2.4 dựng **cơ chế**; đây là phép đo của chính cơ chế đó.
    """
    user_id, email = await _create_real_user(session_factory)
    body = {"email": email, "password": _TEST_PASSWORD}
    assert (await client.post(LOGIN_PATH, json=body)).status_code == 200
    assert (await client_second_device.post(LOGIN_PATH, json=body)).status_code == 200
    second_device_refresh = client_second_device.cookies.get(REFRESH_COOKIE_NAME)

    async with session_factory() as session:
        await revoke_all_sessions(session, fake_redis, user_id)  # type: ignore[arg-type]
        await session.commit()

    for device in (client, client_second_device):
        resp = await device.get(ME_PATH)
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == ApiErrorCode.TOKEN_REVOKED

    # Và refresh token cũng không đổi ra được access token mới — nếu không thì
    # "mọi token cũ đều 401" chỉ đúng trong 15 phút.
    assert second_device_refresh is not None
    client_second_device.cookies.set(REFRESH_COOKIE_NAME, second_device_refresh)
    assert (await client_second_device.post(REFRESH_PATH)).status_code == 401


@pytest.mark.usefixtures("_db_for_tests")
async def test_password_change_does_not_block_tokens_issued_after(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: _FakeRedis,
) -> None:
    """Mốc `bl:user:` chặn theo `iat`, nên đăng nhập LẠI phải dùng được ngay —
    nếu không thì đổi mật khẩu = khoá tài khoản 15 phút.

    Mốc đặt lùi 2 giây thay vì `now()`, và đó là phép đo chứ không phải mẹo
    tránh né: `iat` của JWT là giây NGUYÊN, còn mốc giữ cả phần thập phân (xem
    `core/blacklist.py`), nên một token phát hành trong **cùng giây** với lần
    thu hồi vẫn bị chặn — có chủ ý, và test ngay trên đo đúng mặt kia của cùng
    một lựa chọn. Lùi mốc ra khỏi giây hiện tại là cách duy nhất đo được "token
    phát hành SAU khi thu hồi thì đi qua" mà không phải `sleep(1)` trong test.
    """
    user_id, email = await _create_real_user(session_factory)
    async with session_factory() as session:
        await revoke_all_sessions(
            session,
            fake_redis,  # type: ignore[arg-type]
            user_id,
            now=datetime.now(UTC) - timedelta(seconds=2),
        )
        await session.commit()

    resp_login = await client.post(LOGIN_PATH, json={"email": email, "password": _TEST_PASSWORD})
    assert resp_login.status_code == 200

    assert (await client.get(ME_PATH)).status_code == 200


@pytest.mark.usefixtures("_db_for_tests")
async def test_user_cutoff_blocks_token_issued_in_same_second(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: _FakeRedis,
) -> None:
    """`iat` của JWT là giây NGUYÊN. Mốc mà cũng làm tròn xuống thì token phát
    hành cùng giây với lần đổi mật khẩu sống sót (`iat == mốc`, `<` cho False).

    Phép kiểm ngược: đổi `repr(moc)` trong `set_user_cutoff` thành `str(int(moc))`
    làm test này đỏ. Nó phải chạy nhanh hơn một giây để có nghĩa — `_create_real_user`
    tốn ~100 ms Argon2, `login` thêm ~100 ms, nên biên vẫn rộng.
    """
    user_id, email = await _create_real_user(session_factory)
    await client.post(LOGIN_PATH, json={"email": email, "password": _TEST_PASSWORD})
    token = client.cookies.get(SESSION_COOKIE_NAME)
    assert token is not None
    iat = decode_access_token(token).issued_at

    async with session_factory() as session:
        mark = await revoke_all_sessions(session, fake_redis, user_id)  # type: ignore[arg-type]
        await session.commit()

    if int(mark) != int(iat.timestamp()):
        pytest.skip("hai moc roi vao hai giay khac nhau — khong do duoc ca bien nay")
    resp = await client.get(ME_PATH)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == ApiErrorCode.TOKEN_REVOKED


@pytest.mark.usefixtures("_db_for_tests")
async def test_empty_blacklist_lets_valid_token_through(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: _FakeRedis,
) -> None:
    """DoD T-2.4 dòng 4: blacklist trống mà token hợp lệ → vẫn qua (không chặn
    nhầm). Một blacklist chặn tất cả cũng "đạt" ba dòng DoD kia."""
    await _login(client, session_factory)
    assert fake_redis.store == {}, "chua ai logout/doi mat khau thi kho phai rong"

    for _ in range(3):
        assert (await client.get(ME_PATH)).status_code == 200


@pytest.mark.usefixtures("_db_for_tests")
async def test_corrupt_user_blacklist_value_blocks_not_allows(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: _FakeRedis,
) -> None:
    """Khoá `bl:user:` chỉ tồn tại vì có người yêu cầu thu hồi. Nội dung không
    đọc được (ai đó `SET` tay lúc debug) → chặn, không tha."""
    user_id, _ = await _login(client, session_factory)
    await fake_redis.set(user_key(user_id), "khong-phai-so", ex=900)

    resp = await client.get(ME_PATH)

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == ApiErrorCode.TOKEN_REVOKED


@pytest.mark.usefixtures("_db_for_tests")
async def test_logout_with_expired_access_token_200_and_still_revokes_family(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    """Logout KHÔNG đòi access token còn hạn (xem docstring `api/v1/auth.py`).

    Access token sống 15 phút, refresh token sống 30 ngày: trả `401` ở đây
    nghĩa là người rời máy quá 15 phút không đóng được phiên 30 ngày của chính
    mình — đúng C21, chỉ đổi nguyên nhân.
    """
    _, email = await _login(client, session_factory)
    old_refresh = client.cookies.get(REFRESH_COOKIE_NAME)
    client.cookies.set(
        SESSION_COOKIE_NAME,
        encode_access_token(
            user_id=user_a,
            role=UserRole.USER,
            tier="free",
            status=UserStatus.PENDING_EMAIL,
            ttl_minutes=-1,
        ),
    )

    resp = await client.post(LOGOUT_PATH)

    assert resp.status_code == 200
    assert old_refresh is not None
    client.cookies.set(REFRESH_COOKIE_NAME, old_refresh)
    assert (await client.post(REFRESH_PATH)).status_code == 401


async def test_logout_without_cookies_is_still_200(client: AsyncClient) -> None:
    """Không có gì để đóng và đã đóng xong là cùng một trạng thái cuối — và
    phân biệt hai ca đó là nói cho người gọi biết cookie họ gửi có thật hay
    không (§11.5)."""
    resp = await client.post(LOGOUT_PATH)

    assert resp.status_code == 200
    assert resp.json() == {"status": "logged_out"}


@pytest.mark.usefixtures("_db_for_tests")
async def test_logout_dead_redis_503_not_reported_success(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: _FakeRedis,
) -> None:
    """Nuốt lỗi Redis ở logout là C21 nguyên vẹn: người dùng đọc "đã đăng
    xuất" trong khi access token còn chạy thêm 15 phút."""
    await _login(client, session_factory)
    fake_redis.raises = True

    resp = await client.post(LOGOUT_PATH)

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == ApiErrorCode.SERVICE_UNAVAILABLE


@pytest.mark.usefixtures("_db_for_tests")
async def test_dead_redis_request_is_503_not_let_through(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: _FakeRedis,
) -> None:
    """Không hỏi được Redis nghĩa là KHÔNG BIẾT token có bị thu hồi hay chưa.
    Cho qua là mở lại C21 đúng lúc hệ thống đang hỏng; `503` chứ không `401` vì
    đây là sự cố hạ tầng, không phải lỗi của phiên đăng nhập."""
    await _login(client, session_factory)
    fake_redis.raises = True

    resp = await client.get(ME_PATH)

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == ApiErrorCode.SERVICE_UNAVAILABLE


# ═══════════════════════ Kiểm Origin (NQ-36, B-114) ══════════════════════════


@pytest.mark.usefixtures("_db_for_tests")
async def test_matching_origin_passes(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    _, email = await _create_real_user(session_factory)

    resp = await client.post(
        LOGIN_PATH,
        json={"email": email, "password": _TEST_PASSWORD},
        headers={"Origin": "https://localhost"},
    )

    assert resp.status_code == 200


@pytest.mark.usefixtures("_db_for_tests")
async def test_mismatched_origin_blocked_403(client: AsyncClient) -> None:
    resp = await client.post(
        LOGIN_PATH,
        json={"email": "khong-quan-trong@scarlet.example", "password": "x"},
        headers={"Origin": "https://ke-tan-cong.example"},
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == ApiErrorCode.FORBIDDEN


@pytest.mark.usefixtures("_db_for_tests")
async def test_missing_origin_passes(client: AsyncClient) -> None:
    """Không có `Origin` (mọi client hiện có: `curl`, `httpx`, script) → không
    bị chặn — xem docstring `app/core/origin.py` cho lý do."""
    resp = await client.get("/api/v1/models")

    assert resp.status_code == 200


# ═════ POST /auth/forgot-password + /reset-password (T-2.5, §11.5, §11.6) ════


async def _request_reset_link(client: AsyncClient, fake_mailer: _FakeMailer, email: str) -> str:
    """Gọi `forgot-password` rồi moi token bản rõ ra khỏi thư đã gửi."""
    resp = await client.post(FORGOT_PASSWORD_PATH, json={"email": email})
    assert resp.status_code == 200
    assert fake_mailer.calls, "khong co thu nao duoc gui"
    call = fake_mailer.calls[-1]
    assert call["template"] == "reset_password"
    return _token_from_url(call["ctx"]["reset_url"])


@pytest.mark.usefixtures("_db_for_tests")
async def test_forgot_password_mails_reset_to_existing_email(
    client: AsyncClient, fake_mailer: _FakeMailer, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    _, email = await _create_real_user(session_factory)

    resp = await client.post(FORGOT_PASSWORD_PATH, json={"email": email})

    assert resp.status_code == 200
    assert len(fake_mailer.calls) == 1
    assert fake_mailer.calls[0]["template"] == "reset_password"
    assert fake_mailer.calls[0]["to"] == email
    assert "reset_url" in fake_mailer.calls[0]["ctx"]


def _fe_path(key_name: str) -> str:
    """Giá trị của một hàng `PATHS` trong `frontend/src/app/paths.ts`.

    Đọc file nguồn của FE từ một test backend là cố ý, và nó canh đúng thứ
    vừa hỏng: `reset_url` trỏ vào `/reset-password` suốt từ T-2.5, trong khi
    bảng route của T-3.1a gọi đường ấy là `/dat-lai-mat-khau`. Không một phép
    kiểm nào ở hai bên bắt được — backend chỉ thấy một chuỗi, FE chỉ thấy một
    route không ai gọi tới — nên mọi link đặt lại mật khẩu rơi vào trang 404
    mà cả hai bộ test vẫn xanh. Cặp chuỗi này là một hợp đồng giữa hai tầng;
    hợp đồng thì phải có người đọc cả hai vế.
    """
    source = (
        Path(__file__).resolve().parents[3] / "frontend" / "src" / "app" / "paths.ts"
    ).read_text(encoding="utf-8")
    match = re.search(rf'^\s*{key_name}:\s*"([^"]+)"', source, re.MULTILINE)
    assert match is not None, f"khong thay hang {key_name} trong paths.ts"
    return match.group(1)


@pytest.mark.usefixtures("_db_for_tests")
async def test_both_mail_links_point_to_the_two_FE_routes(
    client: AsyncClient, fake_mailer: _FakeMailer, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`verify_url` và `reset_url` phải khớp `PATHS` — xem `_fe_path`."""
    _, email = await _create_real_user(session_factory)
    await client.post(
        PATH,
        json={"email": f"{uuid.uuid4().hex}@scarlet.example", "password": _TEST_PASSWORD},
    )
    await client.post(FORGOT_PASSWORD_PATH, json={"email": email})

    by_template = {call["template"]: call["ctx"] for call in fake_mailer.calls}

    assert urlsplit(by_template["verify_email"]["verify_url"]).path == _fe_path("verifyEmail")
    assert urlsplit(by_template["reset_password"]["reset_url"]).path == _fe_path("resetPassword")


@pytest.mark.usefixtures("_db_for_tests")
async def test_forgot_password_unknown_email_same_response_and_no_mail(
    client: AsyncClient, fake_mailer: _FakeMailer, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """DoD dòng 1: response **giống hệt** email có thật, và không thư nào.

    So sánh `content` (byte-for-byte) chứ không so `status_code`: chống dò của
    §11.5 hỏng ngay khi hai nhánh khác nhau một dấu chấm.
    """
    _, real_email = await _create_real_user(session_factory)
    resp_existing = await client.post(FORGOT_PASSWORD_PATH, json={"email": real_email})
    fake_mailer.calls.clear()

    resp_missing = await client.post(
        FORGOT_PASSWORD_PATH, json={"email": f"{uuid.uuid4().hex}@khong-ton-tai.example"}
    )

    assert resp_missing.status_code == resp_existing.status_code == 200
    assert resp_missing.content == resp_existing.content
    assert fake_mailer.calls == []


@pytest.mark.usefixtures("_db_for_tests")
async def test_forgot_password_does_not_store_plaintext_token(
    client: AsyncClient, fake_mailer: _FakeMailer, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Cạm bẫy T-2.2 áp lại nguyên vẹn cho token `reset` (§11.5)."""
    _, email = await _create_real_user(session_factory)
    token = await _request_reset_link(client, fake_mailer, email)

    async with session_factory() as session:
        row = (
            await session.execute(
                select(EmailToken).where(EmailToken.token_hash == hash_email_token(token))
            )
        ).scalar_one()
        assert row.purpose == EmailTokenPurpose.RESET.value
        assert token not in row.token_hash


@pytest.mark.usefixtures("_db_for_tests")
async def test_reset_password_changes_it_and_new_password_logs_in(
    client: AsyncClient, fake_mailer: _FakeMailer, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id, email = await _create_real_user(session_factory)
    token = await _request_reset_link(client, fake_mailer, email)

    resp = await client.post(RESET_PASSWORD_PATH, json={"token": token, "password": _NEW_PASSWORD})

    assert resp.status_code == 200
    assert resp.json() == {"status": "reset"}
    async with session_factory() as session:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
        assert await verify_password(user.password_hash, _NEW_PASSWORD)
        assert not await verify_password(user.password_hash, _TEST_PASSWORD)
    resp_login = await client.post(LOGIN_PATH, json={"email": email, "password": _NEW_PASSWORD})
    assert resp_login.status_code == 200


@pytest.mark.usefixtures("_db_for_tests")
async def test_reset_password_revokes_session_in_other_tab(
    client: AsyncClient,
    client_second_device: AsyncClient,
    fake_mailer: _FakeMailer,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """DoD dòng 2: session cũ ở tab khác trả `401` ở request TIẾP THEO.

    Cạm bẫy của task: "không revoke session sau khi đổi mật khẩu = kẻ đã chiếm
    tài khoản vẫn ở trong đó sau khi nạn nhân đổi mật khẩu."
    """
    _, email = await _create_real_user(session_factory)
    body = {"email": email, "password": _TEST_PASSWORD}
    assert (await client_second_device.post(LOGIN_PATH, json=body)).status_code == 200
    assert (await client_second_device.get(ME_PATH)).status_code == 200
    other_tab_refresh = client_second_device.cookies.get(REFRESH_COOKIE_NAME)
    token = await _request_reset_link(client, fake_mailer, email)

    assert (
        await client.post(RESET_PASSWORD_PATH, json={"token": token, "password": _NEW_PASSWORD})
    ).status_code == 200

    resp = await client_second_device.get(ME_PATH)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == ApiErrorCode.TOKEN_REVOKED
    # Và refresh token 30 ngày cũng chết — nếu không thì "thu hồi" chỉ kéo dài
    # 15 phút rồi kẻ tấn công đổi ra một access token mới.
    assert other_tab_refresh is not None
    client_second_device.cookies.set(REFRESH_COOKIE_NAME, other_tab_refresh)
    assert (await client_second_device.post(REFRESH_PATH)).status_code == 401


@pytest.mark.usefixtures("_db_for_tests")
async def test_reset_password_token_used_twice_second_is_400(
    client: AsyncClient, fake_mailer: _FakeMailer, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """DoD dòng 3. Khác `verify-email` (bấm lại = thành công idempotent): dùng
    lại link reset là **đổi mật khẩu lần thứ hai**."""
    _, email = await _create_real_user(session_factory)
    token = await _request_reset_link(client, fake_mailer, email)
    first_try = await client.post(
        RESET_PASSWORD_PATH, json={"token": token, "password": _NEW_PASSWORD}
    )
    assert first_try.status_code == 200

    second_time = await client.post(
        RESET_PASSWORD_PATH, json={"token": token, "password": _NEW_PASSWORD_2}
    )

    assert second_time.status_code == 400
    assert second_time.json()["error"]["code"] == ApiErrorCode.TOKEN_INVALID
    # Mật khẩu vẫn là của lần đặt lại THỨ NHẤT.
    assert (
        await client.post(LOGIN_PATH, json={"email": email, "password": _NEW_PASSWORD})
    ).status_code == 200


@pytest.mark.usefixtures("_db_for_tests")
async def test_reset_password_expired_token_400_same_as_fake_token(
    client: AsyncClient, fake_mailer: _FakeMailer, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Ba kiểu token hỏng trả CÙNG một câu — xem docstring `api/v1/auth.py`."""
    _, email = await _create_real_user(session_factory)
    token = await _request_reset_link(client, fake_mailer, email)
    async with session_factory() as session:
        await session.execute(
            update(EmailToken)
            .where(EmailToken.token_hash == hash_email_token(token))
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await session.commit()

    resp_expired = await client.post(
        RESET_PASSWORD_PATH, json={"token": token, "password": _NEW_PASSWORD}
    )
    resp_fabricated = await client.post(
        RESET_PASSWORD_PATH, json={"token": "khong-phai-token", "password": _NEW_PASSWORD}
    )

    assert resp_expired.status_code == resp_fabricated.status_code == 400
    assert resp_expired.content == resp_fabricated.content


@pytest.mark.usefixtures("_db_for_tests")
async def test_reset_password_rejects_verify_token(
    client: AsyncClient, fake_mailer: _FakeMailer
) -> None:
    """`purpose` lọc trong SQL: token `verify` không mở được cửa `reset`."""
    email = f"{uuid.uuid4().hex}@scarlet.example"
    await client.post(PATH, json={"email": email, "password": "mot-mat-khau-du-manh-123"})
    token_verify = _token_from_url(fake_mailer.calls[0]["ctx"]["verify_url"])

    resp = await client.post(
        RESET_PASSWORD_PATH, json={"token": token_verify, "password": _NEW_PASSWORD}
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == ApiErrorCode.TOKEN_INVALID


@pytest.mark.usefixtures("_db_for_tests")
@pytest.mark.parametrize(
    ("password", "error_code"),
    [
        ("ngan", ApiErrorCode.PASSWORD_TOO_SHORT),
        ("password1234", ApiErrorCode.PASSWORD_TOO_WEAK),
    ],
)
async def test_reset_password_weak_rejected_and_token_STILL_usable(
    client: AsyncClient,
    fake_mailer: _FakeMailer,
    session_factory: async_sessionmaker[AsyncSession],
    password: str,
    error_code: ApiErrorCode,
) -> None:
    """§11.6 áp cho cả mật khẩu đặt lại, **và** một lần gõ sai không được giết
    link: `session_scope()` không commit khi có ngoại lệ nên `used_at` bị
    rollback (xem docstring `api/v1/auth.py` — đây là công của transaction,
    không phải của thứ tự hai phép kiểm)."""
    _, email = await _create_real_user(session_factory)
    token = await _request_reset_link(client, fake_mailer, email)

    resp = await client.post(RESET_PASSWORD_PATH, json={"token": token, "password": password})

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == error_code
    assert (
        await client.post(RESET_PASSWORD_PATH, json={"token": token, "password": _NEW_PASSWORD})
    ).status_code == 200


@pytest.mark.usefixtures("_db_for_tests")
async def test_reset_password_does_NOT_log_in_and_clears_both_cookies(
    client: AsyncClient, fake_mailer: _FakeMailer, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """NQ-44 (đóng B-130): không phát hành cookie phiên mới.

    Mốc `bl:user:` giữ phần thập phân (NQ-42 ②) nên nó chặn cả token phát hành
    trong cùng giây — một endpoint vừa đặt mốc vừa tự ký cookie sẽ trả về đúng
    một cookie mà chính nó vừa làm cho vô hiệu.
    """
    _, email = await _create_real_user(session_factory)
    assert (
        await client.post(LOGIN_PATH, json={"email": email, "password": _TEST_PASSWORD})
    ).status_code == 200
    token = await _request_reset_link(client, fake_mailer, email)

    resp = await client.post(RESET_PASSWORD_PATH, json={"token": token, "password": _NEW_PASSWORD})

    assert resp.status_code == 200
    set_cookies = [c for c in resp.headers.get_list("set-cookie")]
    assert all("Max-Age=0" in c or "expires=Thu, 01 Jan 1970" in c.lower() for c in set_cookies), (
        f"reset-password khong duoc phat hanh cookie phien moi: {set_cookies}"
    )
    assert client.cookies.get(SESSION_COOKIE_NAME) is None
    assert client.cookies.get(REFRESH_COOKIE_NAME) is None


@pytest.mark.usefixtures("_db_for_tests")
async def test_reset_password_dead_redis_503_and_does_NOT_change_password(
    client: AsyncClient,
    fake_mailer: _FakeMailer,
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: _FakeRedis,
) -> None:
    """Nửa Redis của §11.3 trượt ⇒ rollback cả nửa Postgres.

    Thà bắt người dùng bấm lại link còn hơn đổi xong mật khẩu mà phiên của kẻ
    tấn công vẫn sống thêm 15 phút — đúng Cạm bẫy của task.
    """
    user_id, email = await _create_real_user(session_factory)
    token = await _request_reset_link(client, fake_mailer, email)
    fake_redis.raises = True

    resp = await client.post(RESET_PASSWORD_PATH, json={"token": token, "password": _NEW_PASSWORD})

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == ApiErrorCode.SERVICE_UNAVAILABLE
    async with session_factory() as session:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
        assert await verify_password(user.password_hash, _TEST_PASSWORD)


@pytest.mark.usefixtures("_db_for_tests")
async def test_forgot_password_over_hourly_limit_is_429(client: AsyncClient) -> None:
    """DoD dòng 4: gọi 4 lần trong 1 giờ từ cùng IP → lần 4 trả `429`."""
    email = f"{uuid.uuid4().hex}@khong-ton-tai.example"
    for _ in range(settings.RATE_LIMIT_EMAIL_IP_PER_HOUR):
        assert (await client.post(FORGOT_PASSWORD_PATH, json={"email": email})).status_code == 200

    resp = await client.post(FORGOT_PASSWORD_PATH, json={"email": email})

    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == ApiErrorCode.RATE_LIMITED
    assert int(resp.headers["Retry-After"]) > 0


@pytest.mark.usefixtures("_db_for_tests")
async def test_reset_password_uses_per_minute_limit_not_per_hour(
    client: AsyncClient, fake_mailer: _FakeMailer, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Gõ sai mật khẩu vài lần KHÔNG được khoá nạn nhân ra một tiếng.

    `reset-password` vì vậy dùng hạn mức nhóm `auth` (5/phút) chứ không 3/giờ
    của route gửi thư — xem `core/ratelimit.py`.
    """
    _, email = await _create_real_user(session_factory)
    token = await _request_reset_link(client, fake_mailer, email)
    for _ in range(settings.RATE_LIMIT_EMAIL_IP_PER_HOUR):
        assert (
            await client.post(RESET_PASSWORD_PATH, json={"token": token, "password": "ngan"})
        ).status_code == 422

    resp = await client.post(RESET_PASSWORD_PATH, json={"token": token, "password": _NEW_PASSWORD})

    assert resp.status_code == 200


# ════════════════ Rate limit theo IP (§10.6) — B-127, B-131 ══════════════════


@pytest.mark.usefixtures("_db_for_tests")
async def test_resend_verification_over_hourly_limit_is_429(client: AsyncClient) -> None:
    """§18.1 ghi "Rate limit 3/giờ" cho đúng route này (B-127).

    Đếm cả lượt gọi với email không tồn tại: thứ cần chặn là lượt *thử*, và
    một lần dò email thất bại cũng là một lần dò.
    """
    email = f"{uuid.uuid4().hex}@khong-ton-tai.example"
    for _ in range(settings.RATE_LIMIT_EMAIL_IP_PER_HOUR):
        assert (await client.post(RESEND_PATH, json={"email": email})).status_code == 200

    resp = await client.post(RESEND_PATH, json={"email": email})

    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == ApiErrorCode.RATE_LIMITED
    assert int(resp.headers["Retry-After"]) > 0


@pytest.mark.usefixtures("_db_for_tests")
async def test_register_over_hourly_limit_is_429(
    client: AsyncClient,
    fake_mailer: _FakeMailer,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """§10.6 ghi "đăng ký: 3/giờ" theo IP — B-133, đóng ở T-2.9.

    Mỗi lượt gọi gửi một lá thư tới một hộp thư người gọi tự nhập **và** băm
    Argon2id 192 MiB (T-2.1), nên endpoint này vừa là đường gửi thư hàng loạt
    vừa là đường làm cạn RAM của `api` rẻ nhất.

    Turnstile không thay được lớp này: `TURNSTILE_SECRET` rỗng ở dev thì captcha
    bị bỏ qua hoàn toàn (§11.6), còn khi bật thì nó chặn trình duyệt chứ không
    chặn một script gọi thẳng API.
    """
    for _ in range(settings.RATE_LIMIT_EMAIL_IP_PER_HOUR):
        resp = await client.post(
            PATH,
            json={"email": f"{uuid.uuid4().hex}@scarlet.example", "password": _TEST_PASSWORD},
        )
        assert resp.status_code == 200

    fourth_email = f"{uuid.uuid4().hex}@scarlet.example"
    mails_sent = len(fake_mailer.calls)

    resp = await client.post(PATH, json={"email": fourth_email, "password": _TEST_PASSWORD})

    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == ApiErrorCode.RATE_LIMITED
    assert int(resp.headers["Retry-After"]) > 0
    assert len(fake_mailer.calls) == mails_sent, "bị chặn thì không gửi thư nào"
    assert await _count_users_by_email(session_factory, fourth_email) == 0, (
        "dependency chạy TRƯỚC handler nên không hàng `users` nào được ghi"
    )


@pytest.mark.usefixtures("_db_for_tests")
async def test_register_and_resend_use_TWO_separate_counters(
    client: AsyncClient, fake_mailer: _FakeMailer
) -> None:
    """Khoá mang tên route (§10.6 cho mỗi route một hạn mức riêng): người vừa
    dùng hết hạn mức đăng ký vẫn phải xin lại được thư xác thực."""
    for _ in range(settings.RATE_LIMIT_EMAIL_IP_PER_HOUR):
        assert (
            await client.post(
                PATH,
                json={
                    "email": f"{uuid.uuid4().hex}@scarlet.example",
                    "password": _TEST_PASSWORD,
                },
            )
        ).status_code == 200
    assert (
        await client.post(PATH, json={"email": "x@scarlet.example", "password": _TEST_PASSWORD})
    ).status_code == 429

    resp = await client.post(RESEND_PATH, json={"email": "x@scarlet.example"})

    assert resp.status_code == 200


@pytest.mark.usefixtures("_db_for_tests")
async def test_logout_over_per_minute_limit_is_429(client: AsyncClient) -> None:
    """Logout cố ý không đòi xác thực (NQ-42) nên bất kỳ ai cũng tạo được một
    lượt ghi Redis + một `UPDATE` — bề mặt duy nhất của `/auth/*` chưa đếm sau
    T-2.5 (B-131)."""
    for _ in range(settings.RATE_LIMIT_AUTH_IP_PER_MIN):
        assert (await client.post(LOGOUT_PATH)).status_code == 200

    resp = await client.post(LOGOUT_PATH)

    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == ApiErrorCode.RATE_LIMITED


@pytest.mark.usefixtures("_db_for_tests")
async def test_limit_counts_by_real_ip_not_nginx(client: AsyncClient) -> None:
    """Nếu đếm nhầm theo `request.client` (IP của Nginx) thì người thứ tư
    trong giờ bị chặn vì ba người khác — cả nhà chung một bộ đếm."""
    email = f"{uuid.uuid4().hex}@khong-ton-tai.example"
    for _ in range(settings.RATE_LIMIT_EMAIL_IP_PER_HOUR + 1):
        await client.post(RESEND_PATH, json={"email": email}, headers={"X-Real-IP": "203.0.113.10"})

    resp = await client.post(
        RESEND_PATH, json={"email": email}, headers={"X-Real-IP": "203.0.113.11"}
    )

    assert resp.status_code == 200


# ═══════════════════ Turnstile (§11.6, RR-1) — T-2.6 ═════════════════════════
#
# Hai endpoint, MỘT hàm (`app/core/turnstile.py`), nên bộ test này KHÔNG lặp
# lại phần đã kiểm ở `tests/core/test_turnstile.py` (hình dạng request gửi đi,
# cách đọc `success`, bốn kiểu "không hỏi được"). Nó chỉ kiểm phần chỉ thấy
# được ở tầng HTTP: mã lỗi ra tới client, và **chỗ đặt** phép kiểm trong thân
# handler.
#
# `httpx.MockTransport` bơm vào `_tao_client` — cùng cách và cùng lý do với
# `tests/core/test_turnstile.py`: không test nào được gọi ra Internet thật.


def _enable_turnstile(monkeypatch: pytest.MonkeyPatch, body: dict[str, Any]) -> list[httpx.Request]:
    """Bật Turnstile + ghim câu trả lời của Cloudflare. Trả về sổ ghi request."""
    monkeypatch.setattr(settings, "TURNSTILE_SECRET", SecretStr("0x-secret-cua-test"))
    sent: list[httpx.Request] = []

    def _capture(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json=body)

    monkeypatch.setattr(
        turnstile_mod,
        "_make_client",
        lambda: AsyncClient(transport=httpx.MockTransport(_capture)),
    )
    return sent


@pytest.fixture
def turnstile_passes(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    """Turnstile bật, Cloudflare luôn trả `success: true`."""
    return _enable_turnstile(monkeypatch, {"success": True, "error-codes": []})


@pytest.fixture
def turnstile_fails(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    """Turnstile bật, Cloudflare luôn từ chối.

    Body là bản ghi THẬT mà khoá thử `2x0000…AA` của Cloudflare trả về, đo
    2026-09-17 từ trong container `api` — không phải một dict bịa ra.
    """
    return _enable_turnstile(
        monkeypatch,
        {"error-codes": ["invalid-input-response"], "success": False, "messages": []},
    )


@pytest.mark.usefixtures("_db_for_tests", "turnstile_passes")
async def test_register_without_token_is_400_not_422(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """DoD T-2.6 dòng 1: đăng ký không kèm token → `400`.

    `400` chứ không `422`, và đó là lý do `turnstile_token` khai
    `str | None = None`: một field pydantic **bắt buộc** mà thiếu sẽ ra
    `422 VALIDATION_ERROR` ("body sai kiểu, sửa client đi") thay vì
    `400 TURNSTILE_FAILED` ("giải lại captcha").
    """
    email = f"{uuid.uuid4().hex}@scarlet.example"

    resp = await client.post(PATH, json={"email": email, "password": _TEST_PASSWORD})

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == ApiErrorCode.TURNSTILE_FAILED
    # Không có user nào được tạo: phép kiểm đứng TRƯỚC mọi việc khác.
    assert await _count_users_by_email(session_factory, email) == 0


@pytest.mark.usefixtures("_db_for_tests")
async def test_register_fake_token_is_400(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    turnstile_fails: list[httpx.Request],
) -> None:
    """DoD T-2.6 dòng 2: token giả → `400`."""
    email = f"{uuid.uuid4().hex}@scarlet.example"

    resp = await client.post(
        PATH,
        json={"email": email, "password": _TEST_PASSWORD, "turnstile_token": "0.token-gia"},
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == ApiErrorCode.TURNSTILE_FAILED
    assert len(turnstile_fails) == 1, "phải HỎI Cloudflare khi có token, không tự phán"
    assert await _count_users_by_email(session_factory, email) == 0


@pytest.mark.usefixtures("_db_for_tests", "turnstile_passes")
async def test_register_passing_token_creates_user_normally(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], fake_mailer: _FakeMailer
) -> None:
    """Phép kiểm ngược của hai test trên: bật Turnstile KHÔNG làm hỏng đường
    đăng ký thật."""
    email = f"{uuid.uuid4().hex}@scarlet.example"

    resp = await client.post(
        PATH,
        json={"email": email, "password": _TEST_PASSWORD, "turnstile_token": "0.token-that"},
    )

    assert resp.status_code == 200
    assert await _count_users_by_email(session_factory, email) == 1
    assert len(fake_mailer.calls) == 1


@pytest.mark.usefixtures("_db_for_tests")
async def test_register_with_turnstile_off_needs_no_token(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """DoD T-2.6 dòng 3, nửa "đăng ký được".

    Bộ test không đặt `TURNSTILE_SECRET` (`tests/conftest.py` chỉ nạp biến bắt
    buộc), nên đây cũng là lý do hơn ba mươi test T-2.1…T-2.5 phía trên không
    phải sửa một dòng nào.
    """
    email = f"{uuid.uuid4().hex}@scarlet.example"

    resp = await client.post(PATH, json={"email": email, "password": _TEST_PASSWORD})

    assert resp.status_code == 200
    assert await _count_users_by_email(session_factory, email) == 1


@pytest.mark.usefixtures("_db_for_tests", "turnstile_passes")
async def test_turnstile_runs_BEFORE_password_check(client: AsyncClient) -> None:
    """Mật khẩu rác + thiếu token → `400` (captcha), không phải `422`.

    Đây là cổng chống *máy*: đặt nó sau `hash_password` (~100 ms và 192 MiB
    mỗi lượt, T-2.1) là trả tiền cho đúng những request mình sắp từ chối.
    """
    resp = await client.post(
        PATH, json={"email": f"{uuid.uuid4().hex}@scarlet.example", "password": "abc"}
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == ApiErrorCode.TURNSTILE_FAILED


@pytest.mark.usefixtures("_db_for_tests", "turnstile_passes")
async def test_forgot_password_without_token_is_400(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], fake_mailer: _FakeMailer
) -> None:
    """§11.6 chỉ định captcha cho CẢ HAI form, không riêng đăng ký."""
    _, email = await _create_real_user(session_factory)

    resp = await client.post(FORGOT_PASSWORD_PATH, json={"email": email})

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == ApiErrorCode.TURNSTILE_FAILED
    assert fake_mailer.calls == [], "không được gửi thư khi captcha chưa qua"


@pytest.mark.usefixtures("_db_for_tests", "turnstile_passes")
async def test_forgot_password_passing_token_still_mails(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], fake_mailer: _FakeMailer
) -> None:
    _, email = await _create_real_user(session_factory)

    resp = await client.post(
        FORGOT_PASSWORD_PATH, json={"email": email, "turnstile_token": "0.token-that"}
    )

    assert resp.status_code == 200
    assert len(fake_mailer.calls) == 1


@pytest.mark.usefixtures("_db_for_tests", "turnstile_passes")
async def test_forgot_password_two_emails_same_response(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """§11.5 không bị Turnstile làm sứt: phép kiểm captcha không đọc `email`
    nên nó không tạo được nhánh nào rẽ theo "email này có tồn tại không"."""
    _, existing = await _create_real_user(session_factory)
    missing_email = f"{uuid.uuid4().hex}@khong-ton-tai.example"
    body = {"turnstile_token": "0.token-that"}

    resp1 = await client.post(FORGOT_PASSWORD_PATH, json={"email": existing, **body})
    resp2 = await client.post(FORGOT_PASSWORD_PATH, json={"email": missing_email, **body})

    assert resp1.status_code == resp2.status_code == 200
    assert resp1.content == resp2.content


@pytest.mark.usefixtures("_db_for_tests", "turnstile_passes")
async def test_forgot_password_limit_counts_captcha_blocked_calls(client: AsyncClient) -> None:
    """Dependency hạn mức chạy TRƯỚC thân handler, nên một lượt bị captcha
    chặn vẫn là một lượt đã đếm (NQ-43 — đếm lượt *thử*).

    Đường ngược lại: ai cũng gọi vô hạn miễn là không kèm token, và hạn mức
    3/giờ của §10.6 thành trang trí.
    """
    email = f"{uuid.uuid4().hex}@khong-ton-tai.example"
    for _ in range(settings.RATE_LIMIT_EMAIL_IP_PER_HOUR):
        assert (await client.post(FORGOT_PASSWORD_PATH, json={"email": email})).status_code == 400

    resp = await client.post(FORGOT_PASSWORD_PATH, json={"email": email})

    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == ApiErrorCode.RATE_LIMITED


# ═════════ HAI cookie phiên cùng tên — cookie tossing (2026-09-22) ══════════
#
# Lỗi đo được trên stack thật: người dùng đăng nhập, `POST /auth/login` trả
# `200`, và request ngay sau đó nhận `401 TOKEN_EXPIRED`. Log nginx cho thấy
# trình duyệt gửi **hai** `scarlet_session` (`ss=1 dup=1`), còn
# `cookie_parser` của Starlette giữ giá trị **cuối cùng** — mà RFC 6265 §5.4
# xếp cookie `Path` dài hơn lên trước, nên cookie vừa cấp (`Path=/api/v1`) đi
# trước và một cookie cũ ở path rộng hơn đi sau và thắng.
#
# Sáu ca dưới đây gửi header `Cookie` THÔ thay vì dùng `client.cookies`: kho
# cookie của httpx là một `dict` theo tên nên nó **không thể** dựng lại tình
# huống này — chính là lý do bộ test cũ xanh suốt trong khi trình duyệt hỏng.


def _two_cookies(*value: str) -> dict[str, str]:
    """Header `Cookie` mang nhiều `scarlet_session`, đúng thứ tự truyền vào."""
    return {"Cookie": "; ".join(f"{SESSION_COOKIE_NAME}={v}" for v in value)}


def _token_of(user_id: uuid.UUID, ttl_minutes: int) -> str:
    return encode_access_token(
        user_id=user_id,
        role=UserRole.USER,
        tier="free",
        status=UserStatus.ACTIVE,
        ttl_minutes=ttl_minutes,
    )


@pytest.mark.usefixtures("_db_for_tests")
async def test_expired_old_cookie_AFTER_cannot_mask_new_cookie(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Đúng thứ tự trình duyệt gửi trong sự cố thật: mới trước, cũ sau."""
    user_id, _ = await _create_real_user(session_factory)

    resp = await client.get(
        ME_PATH,
        headers=_two_cookies(_token_of(user_id, 15), _token_of(user_id, -1)),
    )

    assert resp.status_code == 200
    assert resp.json()["id"] == str(user_id)


@pytest.mark.usefixtures("_db_for_tests")
async def test_expired_old_cookie_BEFORE_cannot_mask_either(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Thứ tự nào cũng phải ra cùng một kết quả — thứ tự do trình duyệt quyết,
    không do ta."""
    user_id, _ = await _create_real_user(session_factory)

    resp = await client.get(
        ME_PATH,
        headers=_two_cookies(_token_of(user_id, -1), _token_of(user_id, 15)),
    )

    assert resp.status_code == 200
    assert resp.json()["id"] == str(user_id)


@pytest.mark.usefixtures("_db_for_tests")
async def test_garbage_non_jwt_cookie_alongside_cannot_mask(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Cookie tossing không cần một token hợp lệ — một chuỗi rác là đủ, nếu
    tầng đọc cookie chỉ nhìn một giá trị."""
    user_id, _ = await _create_real_user(session_factory)

    resp = await client.get(
        ME_PATH,
        headers=_two_cookies(_token_of(user_id, 15), "khong-phai-jwt-hop-le"),
    )

    assert resp.status_code == 200
    assert resp.json()["id"] == str(user_id)


@pytest.mark.usefixtures("_db_for_tests")
async def test_BOTH_cookies_expired_still_token_expired(
    client: AsyncClient, user_a: uuid.UUID
) -> None:
    """Không được nới lỏng chẩn đoán: `TOKEN_EXPIRED` là mã FE đọc để đi
    `/auth/refresh` thay vì đẩy người dùng ra màn đăng nhập."""
    resp = await client.get(
        ME_PATH,
        headers=_two_cookies(_token_of(user_a, -1), _token_of(user_a, -2)),
    )

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == ApiErrorCode.TOKEN_EXPIRED


async def test_one_expired_one_garbage_cookie_prefers_token_expired(
    client: AsyncClient, user_a: uuid.UUID
) -> None:
    """Một cookie rác đi kèm KHÔNG được hạ `TOKEN_EXPIRED` xuống
    `UNAUTHENTICATED` — hạ xuống là đẩy người dùng ra màn đăng nhập trong khi
    refresh token của họ còn sống 30 ngày."""
    resp = await client.get(ME_PATH, headers=_two_cookies("rac-hoan-toan", _token_of(user_a, -1)))

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == ApiErrorCode.TOKEN_EXPIRED


async def test_both_cookies_malformed_is_unauthenticated(
    client: AsyncClient,
) -> None:
    resp = await client.get(ME_PATH, headers=_two_cookies("rac-mot", "rac-hai"))

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == ApiErrorCode.UNAUTHENTICATED


@pytest.mark.usefixtures("_db_for_tests")
async def test_logout_sweeps_broader_paths_too(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`Set-Cookie` là đường DUY NHẤT xoá một cookie `HttpOnly`, và nó phải
    trúng đúng `Path`. Không quét `/` và `/api` thì cookie rác sống tới khi
    người dùng tự đi dọn trong cài đặt trình duyệt."""
    _, email = await _create_real_user(session_factory)
    await client.post(LOGIN_PATH, json={"email": email, "password": _TEST_PASSWORD})

    resp = await client.post("/api/v1/auth/logout")

    assert resp.status_code == 200
    session_clears = [
        h for h in resp.headers.get_list("set-cookie") if h.startswith(f"{SESSION_COOKIE_NAME}=")
    ]
    paths = {h.split("Path=")[1].split(";")[0] for h in session_clears}
    assert paths == {"/api/v1", "/api", "/"}
