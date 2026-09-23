"""Máy trạng thái tài khoản + phân quyền (§11.1, UC-01) — T-2.7.

Ma trận **5 trạng thái × 4 hành động = 20 ca** của DoD nằm trong `MATRIX`
ngay dưới, một dòng một ô của bảng §11.1. Viết thành một bảng dữ liệu chứ
không 20 hàm rời: bảng trong kế hoạch có hình dạng gì thì bảng ở đây có đúng
hình dạng ấy, nên thêm một trạng thái thứ sáu là thêm bốn dòng — và quên mất
một ô là một chỗ trống nhìn thấy được.

**Hai hàng cuối của §11.1 (`rejected`, `suspended`) ghi "—" ở ba cột sau, và
"—" ở đó nghĩa là "không tới được vì không đăng nhập được" — KHÔNG phải "không
cần kiểm".** Test vẫn dựng token cho chúng bằng `encode_access_token`, vì một
token phát hành *trước* khi admin đổi trạng thái là thứ có thật: `rejected`
không nằm trong nhánh thu hồi nào của §11.3 (chỉ `suspend` mới "như đổi mật
khẩu"), nên một người bị từ chối vẫn cầm cookie phiên còn hạn tới 15 phút.
Ba cột ấy phải chặn được người đó, không thì "—" chỉ là một lời hứa.

Hạ tầng giống `test_auth.py`: `httpx.ASGITransport`, `session_scope()` trỏ về
đúng kết nối của test, Redis giả (autouse — từ T-2.4 **mọi** request mang
cookie phiên đều hỏi blacklist), arq giả (pool thật nối `redis:6379`, một host
chỉ phân giải được bên trong network `internal` của compose).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import LargeBinary, bindparam, text, update
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import catalog
from app.config.settings import settings
from app.core.access_token import encode_access_token
from app.core.crypto import mask_secret, seal
from app.core.deps import SESSION_COOKIE_NAME
from app.core.errors import ApiErrorCode
from app.core.security import hash_password
from app.db.models import User, UserRole, UserStatus
from app.db.repositories import ConversationRepository
from app.db.repositories.users import UserRepository
from app.main import app

LOGIN_PATH = "/api/v1/auth/login"
ME_PATH = "/api/v1/auth/me"
CONVERSATION_PATH = "/api/v1/conversations/{}"
MESSAGES_PATH = "/api/v1/conversations/{}/messages"
RETRY_PATH = "/api/v1/messages/{}/retry"
EDIT_PATH = "/api/v1/messages/{}"

_PASSWORD = "mot-mat-khau-du-manh-cho-test-t27-123"

#: Bốn cột của bảng §11.1, dưới dạng tên hành động.
LOGIN = "dang_nhap"
VIEW = "xem_ui"
CHAT_SYSTEM = "chat_system_key"
CHAT_BYOK = "chat_byok"


# ═══════════════════════════ hạ tầng của bộ test ════════════════════════════


class _FakeRedis:
    """Blacklist rỗng — mọi token đều "chưa bị thu hồi" (§11.3).

    Bộ test này đo phép kiểm **trạng thái**, không đo blacklist (đó là việc của
    `test_auth.py`): một Redis nói "không có khoá nào" giữ cho mọi ca ở đây
    dừng lại ở đúng lớp cần đo.
    """

    async def mget(self, keys: list[str]) -> list[str | None]:
        return [None for _ in keys]

    async def incr(self, name: str) -> int:
        return 1

    async def expire(self, name: str, time: int, *, nx: bool = False) -> bool:
        return True


class _FakeArq:
    """Pool arq giả — ghi lại lần enqueue thay vì nối `redis:6379`."""

    def __init__(self) -> None:
        self.pushed: list[tuple[str, tuple[Any, ...]]] = []

    async def enqueue_job(self, name: str, *args: Any, **_: Any) -> object:
        self.pushed.append((name, args))
        return object()


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    fake = _FakeRedis()
    monkeypatch.setattr("app.core.deps.get_redis", lambda: fake)
    # `app.core.ratelimit.get_redis` KHÔNG patch ở đây nữa (T-2.9): fixture
    # autouse `ratelimit_redis` của `tests/api/conftest.py` đã phủ cả ba lớp
    # của module đó, kể cả hai script Lua mà `_FakeRedis` không biết. Patch đè
    # lên nó sẽ làm ba route sinh chữ trả `503` — đúng cái đã đo được khi thử.
    return fake


@pytest_asyncio.fixture(autouse=True)
async def fake_arq(monkeypatch: pytest.MonkeyPatch) -> _FakeArq:
    fake = _FakeArq()

    async def _pool() -> _FakeArq:
        return fake

    monkeypatch.setattr("app.api.v1.messages.get_arq_pool", _pool)
    return fake


@pytest.fixture(autouse=True)
def _db_for_tests(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`session_scope()` trong handler trỏ vào ĐÚNG kết nối của test (NQ-17)."""
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


@pytest_asyncio.fixture
async def client(event_hooks: dict[str, Any]) -> AsyncIterator[AsyncClient]:
    # `event_hooks`: mỗi POST một `Idempotency-Key` mới, đúng hành vi FE của C22
    # — xem `tests/api/conftest.py`. Không có nó thì mọi POST tới
    # `.../messages` nhận `400 IDEMPOTENCY_KEY_REQUIRED` (§11.4, A8, T-2.8).
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://localhost", event_hooks=event_hooks
    ) as http:
        yield http


#: Khoá BYOK giả, GHÉP lúc chạy. Một chuỗi khớp `sk-[a-zA-Z0-9]{20,}` nằm
#: nguyên văn trong repo làm `scripts/check_hardcode.sh` lệnh 4 đỏ vĩnh viễn —
#: cùng lý do và cùng cách làm với `tests/core/test_log_redact.py` (T-2.14).
_FAKE_KEY = "sk-" + "abcdefghij" * 3


def _provider_byok() -> str:
    """Provider của model MẶC ĐỊNH, và nó phải hỗ trợ BYOK — A3: không gõ tay.

    **Đổi từ "một provider byok bất kỳ" sang "provider của model mặc định" ở
    T-2.15 (B-140).** Ba route sinh chữ không truyền `model_id` nên chúng dùng
    model `default` của catalog; từ T-2.15, cột "Chat bằng BYOK" của §11.1 hỏi
    *"có khoá cho provider của model **đang gọi**"* chứ không còn là *"có khoá
    nào đó"*. Một khoá của provider khác vì vậy **không** mở cửa ấy nữa — xem
    `test_pending_approval_co_byok_sai_provider_van_403`, phép kiểm ngược của
    chính khe hở này.
    """
    model = catalog.get_default_model()
    assert model is not None, "catalog phải có model default"
    provider = catalog.get_catalog().providers[model.provider]
    assert provider.byok_supported, (
        f"model default '{model.id}' thuộc provider '{model.provider}' không hỗ trợ BYOK — "
        "bảng §11.1 cột 'Chat bằng BYOK' không đo được bằng model mặc định nữa"
    )
    return model.provider


def _non_default_provider() -> str:
    """Một provider **khác** provider của model mặc định — nguyên liệu của B-140."""
    default = _provider_byok()
    others = [name for name in sorted(catalog.get_catalog().providers) if name != default]
    assert others, "catalog phải có ít nhất hai provider để đo khe hở B-140"
    return others[0]


async def _create_user(
    session_factory: async_sessionmaker[AsyncSession],
    status: UserStatus,
    *,
    with_byok: bool = False,
    provider_byok: str | None = None,
) -> tuple[uuid.UUID, str]:
    """User với hash Argon2 thật, đặt sẵn `status`, tuỳ chọn thêm một khoá BYOK.

    Hàng `user_provider_keys` chèn bằng SQL thô vì đây là file test của T-2.7,
    không phải của T-2.14 — nhưng bản mã thì **thật** (`crypto.seal`) kể từ
    T-2.15: khoá không giải mã được nay bị `llm/credentials.py` coi như không
    có (`MASTER_ENCRYPTION_KEY` đã xoay ⇒ bảo người dùng nhập lại), nên hai
    chuỗi byte vô nghĩa của bản cũ sẽ đo nhầm đúng thứ nó định đo.

    `provider_byok` để một test chỉ đích danh **provider khác** với provider
    của model mặc định — đó là khe hở B-140, và nó phải đo được.
    """
    email = f"{uuid.uuid4().hex}@scarlet.example"
    async with session_factory() as session:
        user = await UserRepository(session).create_pending_user(
            email=email, password_hash=await hash_password(_PASSWORD)
        )
        assert user is not None
        await session.execute(update(User).where(User.id == user.id).values(status=status))
        if with_byok:
            sealed = seal(_FAKE_KEY)
            await session.execute(
                text(
                    "INSERT INTO user_provider_keys "
                    "(user_id, provider, key_cipher, key_nonce, key_last4) "
                    "VALUES (:user_id, :provider, :cipher, :nonce, :last4)"
                ).bindparams(
                    bindparam("user_id", type_=PgUUID(as_uuid=True)),
                    bindparam("cipher", type_=LargeBinary),
                    bindparam("nonce", type_=LargeBinary),
                ),
                {
                    "user_id": user.id,
                    "provider": provider_byok or _provider_byok(),
                    "cipher": sealed.cipher,
                    "nonce": sealed.nonce,
                    "last4": mask_secret(_FAKE_KEY),
                },
            )
        await session.commit()
        return user.id, email


def _set_session_cookie(client: AsyncClient, user_id: uuid.UUID, status: UserStatus) -> None:
    """Cookie phiên mang đúng `status` cần đo — claim `status` là thứ
    `require_status` đọc (xem `app/core/deps.py`)."""
    client.cookies.set(
        SESSION_COOKIE_NAME,
        encode_access_token(
            user_id=user_id,
            role=UserRole.USER,
            tier="free",
            status=status,
            ttl_minutes=15,
        ),
    )


async def _create_conversation(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> uuid.UUID:
    async with session_factory() as session:
        conversation = await ConversationRepository(session).create_conversation(user_id=user_id)
        await session.commit()
        return conversation.id


# ══════════════════════ ma trận 5 trạng thái × 4 hành động ══════════════════
#
# `(trạng thái, hành động, status code chờ đợi, mã lỗi chờ đợi)`.
# `None` ở cột cuối = ca thành công, không có `error.code` nào để so.

MATRIX: list[tuple[UserStatus, str, int, ApiErrorCode | None]] = [
    # ── pending_email: vào được, nhìn được, KHÔNG chat bằng đường nào ──
    (UserStatus.PENDING_EMAIL, LOGIN, 200, None),
    (UserStatus.PENDING_EMAIL, VIEW, 200, None),
    (UserStatus.PENDING_EMAIL, CHAT_SYSTEM, 403, ApiErrorCode.EMAIL_NOT_VERIFIED),
    (UserStatus.PENDING_EMAIL, CHAT_BYOK, 403, ApiErrorCode.EMAIL_NOT_VERIFIED),
    # ── pending_approval: BYOK mở được cánh cửa mà system key thì không ──
    (UserStatus.PENDING_APPROVAL, LOGIN, 200, None),
    (UserStatus.PENDING_APPROVAL, VIEW, 200, None),
    (UserStatus.PENDING_APPROVAL, CHAT_SYSTEM, 403, ApiErrorCode.PENDING_APPROVAL),
    (UserStatus.PENDING_APPROVAL, CHAT_BYOK, 202, None),
    # ── active: cả bốn cột ──
    (UserStatus.ACTIVE, LOGIN, 200, None),
    (UserStatus.ACTIVE, VIEW, 200, None),
    (UserStatus.ACTIVE, CHAT_SYSTEM, 202, None),
    (UserStatus.ACTIVE, CHAT_BYOK, 202, None),
    # ── rejected / suspended: đóng cả bốn cột, BYOK không cứu được ──
    (UserStatus.REJECTED, LOGIN, 403, ApiErrorCode.ACCOUNT_DISABLED),
    (UserStatus.REJECTED, VIEW, 403, ApiErrorCode.ACCOUNT_DISABLED),
    (UserStatus.REJECTED, CHAT_SYSTEM, 403, ApiErrorCode.ACCOUNT_DISABLED),
    (UserStatus.REJECTED, CHAT_BYOK, 403, ApiErrorCode.ACCOUNT_DISABLED),
    (UserStatus.SUSPENDED, LOGIN, 403, ApiErrorCode.ACCOUNT_DISABLED),
    (UserStatus.SUSPENDED, VIEW, 403, ApiErrorCode.ACCOUNT_DISABLED),
    (UserStatus.SUSPENDED, CHAT_SYSTEM, 403, ApiErrorCode.ACCOUNT_DISABLED),
    (UserStatus.SUSPENDED, CHAT_BYOK, 403, ApiErrorCode.ACCOUNT_DISABLED),
]


@pytest.mark.parametrize(("status", "action", "http_status", "error_code"), MATRIX)
async def test_permission_table_11_1(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    status: UserStatus,
    action: str,
    http_status: int,
    error_code: ApiErrorCode | None,
) -> None:
    """DoD T-2.7: **cả 5 trạng thái × 4 hành động = 20 case** của bảng §11.1."""
    user_id, email = await _create_user(session_factory, status, with_byok=action == CHAT_BYOK)

    if action == LOGIN:
        resp = await client.post(LOGIN_PATH, json={"email": email, "password": _PASSWORD})
    elif action == VIEW:
        _set_session_cookie(client, user_id, status)
        resp = await client.get(ME_PATH)
    else:
        _set_session_cookie(client, user_id, status)
        conversation_id = await _create_conversation(session_factory, user_id)
        resp = await client.post(
            MESSAGES_PATH.format(conversation_id), json={"content": "xin chao"}
        )

    assert resp.status_code == http_status, resp.text
    if error_code is not None:
        body = resp.json()["error"]
        assert body["code"] == error_code
        # `details.status` nói đúng trạng thái đang chặn — thứ duy nhất phân
        # biệt `rejected` với `suspended` (hai ca dùng chung `ACCOUNT_DISABLED`).
        assert body["details"]["status"] == status.value


# ═══════════ năm dòng DoD, tách riêng cho đọc được một mình ═════════════════


async def test_pending_email_sending_message_403_email_not_verified(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """DoD T-2.7 dòng 2 (và UC-01): `pending_email` gọi `POST .../messages`."""
    user_id, _ = await _create_user(session_factory, UserStatus.PENDING_EMAIL)
    _set_session_cookie(client, user_id, UserStatus.PENDING_EMAIL)
    conversation_id = await _create_conversation(session_factory, user_id)

    resp = await client.post(MESSAGES_PATH.format(conversation_id), json={"content": "xin chao"})

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == ApiErrorCode.EMAIL_NOT_VERIFIED


async def test_pending_approval_without_byok_403_pending_approval(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """DoD T-2.7 dòng 3: chờ duyệt mà chưa có khoá riêng thì chưa chat được."""
    user_id, _ = await _create_user(session_factory, UserStatus.PENDING_APPROVAL)
    _set_session_cookie(client, user_id, UserStatus.PENDING_APPROVAL)
    conversation_id = await _create_conversation(session_factory, user_id)

    resp = await client.post(MESSAGES_PATH.format(conversation_id), json={"content": "xin chao"})

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == ApiErrorCode.PENDING_APPROVAL


async def test_pending_approval_with_byok_is_202(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], fake_arq: _FakeArq
) -> None:
    """DoD T-2.7 dòng 4 — "case dễ bỏ sót nhất" (§10.5, §11.1).

    Không chỉ đo mã `202`: job **thật sự** được đẩy đi, tức một lượt sinh đã mở
    ra chứ không phải một response lịch sự rồi thôi.
    """
    user_id, _ = await _create_user(session_factory, UserStatus.PENDING_APPROVAL, with_byok=True)
    _set_session_cookie(client, user_id, UserStatus.PENDING_APPROVAL)
    conversation_id = await _create_conversation(session_factory, user_id)

    resp = await client.post(MESSAGES_PATH.format(conversation_id), json={"content": "xin chao"})

    assert resp.status_code == 202, resp.text
    assert len(fake_arq.pushed) == 1


async def test_pending_approval_with_WRONG_PROVIDER_byok_still_403(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], fake_arq: _FakeArq
) -> None:
    """**B-140 đóng ở T-2.15**: khoá phải là khoá của provider model đang gọi.

    Trước T-2.15, `require_chat_access` chỉ hỏi "có khoá **nào đó** không",
    nên một `pending_approval` lưu khoá của provider A rồi chat bằng model
    của provider B sẽ đi lọt — và đi lọt bằng **system key**, tức tiêu tiền
    của người vận hành đúng thứ §11.1 cấm.

    Gỡ phép kiểm chính xác ở `_open_generation` ra thì test này thành `202`.
    """
    others = _non_default_provider()
    user_id, _ = await _create_user(
        session_factory, UserStatus.PENDING_APPROVAL, with_byok=True, provider_byok=others
    )
    _set_session_cookie(client, user_id, UserStatus.PENDING_APPROVAL)
    conversation_id = await _create_conversation(session_factory, user_id)

    resp = await client.post(MESSAGES_PATH.format(conversation_id), json={"content": "xin chao"})

    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == ApiErrorCode.PENDING_APPROVAL
    assert fake_arq.pushed == [], "0 job ⇒ 0 USD của người vận hành"


async def test_pending_approval_UNDECRYPTABLE_key_still_403(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    fake_arq: _FakeArq,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Khoá có hàng nhưng `MASTER_ENCRYPTION_KEY` đã xoay ⇒ coi như KHÔNG có.

    Hỏng về phía chặt hơn, có chủ ý (xem docstring `llm/credentials.py`): mở
    cửa cho một khoá không dùng được là để lượt sinh ấy rơi xuống system key
    — tức đúng cái §11.1 cấm, chỉ chậm hơn một bước.
    """
    user_id, _ = await _create_user(session_factory, UserStatus.PENDING_APPROVAL, with_byok=True)
    _set_session_cookie(client, user_id, UserStatus.PENDING_APPROVAL)
    conversation_id = await _create_conversation(session_factory, user_id)
    monkeypatch.setattr(
        settings, "MASTER_ENCRYPTION_KEY", SecretStr("khoa-khac-hoan-toan-de-xoay-vong")
    )

    resp = await client.post(MESSAGES_PATH.format(conversation_id), json={"content": "xin chao"})

    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == ApiErrorCode.PENDING_APPROVAL
    assert fake_arq.pushed == []


async def test_SOMEONE_ELSES_byok_does_not_open_the_door(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Phép kiểm BYOK lọc `user_id` **trong câu SQL** (§20, CLAUDE.md).

    Hai `pending_approval`: một người có khoá, một người không. Người không có
    khoá vẫn phải nhận `403` — một `SELECT EXISTS` quên mất `WHERE user_id`
    sẽ mở cửa cho cả nhà chỉ vì một người hàng xóm đã cấu hình BYOK, và
    không ca nào của ma trận ở trên bắt được điều đó (mỗi ca chỉ có một user).
    """
    await _create_user(session_factory, UserStatus.PENDING_APPROVAL, with_byok=True)
    user_id, _ = await _create_user(session_factory, UserStatus.PENDING_APPROVAL)
    _set_session_cookie(client, user_id, UserStatus.PENDING_APPROVAL)
    conversation_id = await _create_conversation(session_factory, user_id)

    resp = await client.post(MESSAGES_PATH.format(conversation_id), json={"content": "xin chao"})

    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == ApiErrorCode.PENDING_APPROVAL


async def test_suspended_cannot_log_in(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """DoD T-2.7 dòng 5: `suspended` → không đăng nhập được.

    `403 ACCOUNT_DISABLED` chứ không `401 INVALID_CREDENTIALS`: mật khẩu ĐÚNG,
    và nói "sai mật khẩu" ở đây là đẩy người dùng đi đặt lại mật khẩu để rồi
    vẫn không vào được. Không rò gì cho người lạ — phải qua được cửa mật khẩu
    mới thấy được câu này.
    """
    _, email = await _create_user(session_factory, UserStatus.SUSPENDED)

    resp = await client.post(LOGIN_PATH, json={"email": email, "password": _PASSWORD})

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == ApiErrorCode.ACCOUNT_DISABLED


async def test_suspended_wrong_password_still_401_invalid_credentials(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Thứ tự của hai phép kiểm trong `login`, đo được: mật khẩu TRƯỚC.

    Ngược lại thì gõ một email bất kỳ là biết tài khoản đó có tồn tại và đang
    ở trạng thái nào — đúng kênh dò mà §11.5 đóng.
    """
    _, email = await _create_user(session_factory, UserStatus.SUSPENDED)

    resp = await client.post(
        LOGIN_PATH, json={"email": email, "password": "mat-khau-khac-han-va-du-dai"}
    )

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == ApiErrorCode.INVALID_CREDENTIALS


async def test_suspended_failed_login_issues_no_cookie(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Phép kiểm trạng thái đứng TRƯỚC lúc phát hành refresh family.

    Một tài khoản bị khoá không có việc gì phải cầm một credential 30 ngày —
    và nếu nó cầm được thì `POST /auth/refresh` sẽ là một đường vòng đi quanh
    đúng bức tường vừa dựng.
    """
    _, email = await _create_user(session_factory, UserStatus.SUSPENDED)

    resp = await client.post(LOGIN_PATH, json={"email": email, "password": _PASSWORD})

    assert resp.status_code == 403
    assert "set-cookie" not in resp.headers


# ════════ cạm bẫy của task: MỘT luật, không phải mỗi endpoint một luật ══════


async def test_every_generation_route_blocks_pending_email(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Cạm bẫy T-2.7 ở dạng kiểm được: lặp qua **danh sách** route sinh chữ.

    `POST .../messages` là route duy nhất DoD gọi tên, nhưng `retry` và
    `PATCH /messages/{id}` cũng mở một lượt sinh — quên một trong ba là để hở
    đúng cánh cửa vừa khoá. Lặp qua danh sách thay vì viết tay từng cái, đúng
    lối mà cạm bẫy của T-2.16 dặn.

    `message_id` không cần tồn tại: `403` phải đến **trước** `404`, vì thứ tự
    ngược lại nói cho một tài khoản chưa xác thực email biết message nào có
    thật (§20).
    """
    user_id, _ = await _create_user(session_factory, UserStatus.PENDING_EMAIL)
    _set_session_cookie(client, user_id, UserStatus.PENDING_EMAIL)
    conversation_id = await _create_conversation(session_factory, user_id)
    message_id = uuid.uuid4()

    responses = [
        await client.post(MESSAGES_PATH.format(conversation_id), json={"content": "a"}),
        await client.post(RETRY_PATH.format(message_id), json={}),
        await client.patch(EDIT_PATH.format(message_id), json={"content": "b"}),
    ]
    for resp in responses:
        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["code"] == ApiErrorCode.EMAIL_NOT_VERIFIED


async def test_non_generation_route_not_blocked_by_chat_rule(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Mặt kia của cùng một luật: `pending_email` vẫn xem được hội thoại.

    §11.1 cho họ "Xem UI ✓". Chặn cả đường đọc là biến một banner nhắc verify
    thành một bức tường trắng — và người dùng không còn chỗ nào để bấm "gửi
    lại thư".
    """
    user_id, _ = await _create_user(session_factory, UserStatus.PENDING_EMAIL)
    _set_session_cookie(client, user_id, UserStatus.PENDING_EMAIL)
    conversation_id = await _create_conversation(session_factory, user_id)

    resp = await client.get(CONVERSATION_PATH.format(conversation_id))

    assert resp.status_code == 200


async def test_suspended_cannot_read_own_conversation(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Cột "Xem UI" của §11.1 áp cho CẢ router `conversations`, không chỉ `/me`.

    Đây là phép kiểm mà cách gắn dependency ở `api/v1/__init__.py` tồn tại vì
    nó: một route không ai nhớ tới vẫn phải đóng.
    """
    user_id, _ = await _create_user(session_factory, UserStatus.SUSPENDED)
    conversation_id = await _create_conversation(session_factory, user_id)
    _set_session_cookie(client, user_id, UserStatus.SUSPENDED)

    resp = await client.get(CONVERSATION_PATH.format(conversation_id))

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == ApiErrorCode.ACCOUNT_DISABLED
