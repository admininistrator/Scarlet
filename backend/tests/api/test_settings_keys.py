"""BYOK CRUD — `/settings/keys` (§18.4, §10.5) — T-2.14.

Sáu dòng DoD của T-2.14 nằm rải trong sáu nhóm dưới đây, và mỗi nhóm được đặt
tên theo **thứ nó chặn** chứ không theo endpoint nó gọi:

1. **Bản rõ không được vào DB** (DoD 1) và **nonce riêng mỗi bản ghi**
   (DoD 2) — hai dòng này đo trên hàng Postgres THẬT, không qua response.
2. **Không bao giờ hiện lại** (DoD 3) — cả `GET` lẫn `PUT` chỉ trả chuỗi che.
3. **Khoá sai ⇒ 400, thông điệp không chứa khoá** (DoD 4) — C20.
4. **Đổi `MASTER_ENCRYPTION_KEY` ⇒ hỏng có kiểm soát** (DoD 6).
5. **Phân quyền và cách ly giữa hai người dùng** (§20).
6. **Catalog quyết định provider nào hợp lệ** (§9.2, C42).

Hạ tầng giống `test_account_states.py`: `httpx.ASGITransport`, `session_scope()`
trỏ về đúng kết nối của test, Redis giả (mọi request mang cookie phiên đều hỏi
blacklist từ T-2.4), và `MockTransport` cho chặng đi hỏi provider — không lần
chạy nào của bộ test này chạm Internet.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import catalog
from app.config.settings import settings
from app.core.access_token import encode_access_token
from app.core.deps import SESSION_COOKIE_NAME
from app.core.errors import ApiErrorCode
from app.core.security import hash_password
from app.db.models import User, UserProviderKey, UserRole, UserStatus
from app.db.repositories.users import UserRepository
from app.llm import byok_verify as verify_mod
from app.main import app

LIST_PATH = "/api/v1/settings/keys"
ITEM_PATH = "/api/v1/settings/keys/{}"

#: Không phải khoá của ai — đủ dài để `mask_secret` giữ tiền tố, và đúng hình
#: dạng mà grep của C20 bắt.
FAKE_KEY = "sk-khong-phai-khoa-that-cua-ai-4f2a"
FAKE_KEY_2 = "sk-mot-khoa-gia-khac-hoan-toan-9e71"

_PASSWORD = "mot-mat-khau-du-manh-cho-test-t214-123"


# ═══════════════════════════ hạ tầng của bộ test ════════════════════════════


class _FakeRedis:
    """Blacklist rỗng — bộ test này đo BYOK, không đo §11.3."""

    async def mget(self, keys: list[str]) -> list[str | None]:
        return [None for _ in keys]

    async def incr(self, name: str) -> int:
        return 1

    async def expire(self, name: str, time: int, *, nx: bool = False) -> bool:
        return True


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    fake = _FakeRedis()
    monkeypatch.setattr("app.core.deps.get_redis", lambda: fake)
    return fake


@pytest.fixture(autouse=True)
def _db_for_tests(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`session_scope()` trong handler trỏ vào ĐÚNG kết nối của test (NQ-17)."""
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


@pytest.fixture(autouse=True)
def provider_accepts(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    """Mặc định: provider trả `200`, tức mọi khoá đều "sống".

    Autouse vì quên nó nghĩa là một test đi gọi Internet thật — kiểu hỏng vừa
    chậm vừa phụ thuộc máy ai chạy.
    """
    return set_transport(monkeypatch, lambda _r: httpx.Response(200, json={"data": []}))


def set_transport(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> list[httpx.Request]:
    sent: list[httpx.Request] = []

    def _capture(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return handler(request)

    monkeypatch.setattr(
        verify_mod, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(_capture))
    )
    return sent


@pytest_asyncio.fixture
async def client(event_hooks: dict[str, Any]) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://localhost", event_hooks=event_hooks
    ) as http:
        yield http


def provider_byok() -> str:
    """Một provider `byok_supported` trong catalog — A3: không gõ tay tên."""
    supported = [name for name, p in catalog.get_catalog().providers.items() if p.byok_supported]
    assert supported, "catalog phải có ít nhất một provider hỗ trợ BYOK"
    return sorted(supported)[0]


def provider_without_byok() -> str | None:
    unsupported = [
        name for name, p in catalog.get_catalog().providers.items() if not p.byok_supported
    ]
    return sorted(unsupported)[0] if unsupported else None


async def create_user(
    session_factory: async_sessionmaker[AsyncSession],
    status: UserStatus = UserStatus.ACTIVE,
) -> uuid.UUID:
    email = f"{uuid.uuid4().hex}@scarlet.example"
    async with session_factory() as session:
        user = await UserRepository(session).create_pending_user(
            email=email, password_hash=await hash_password(_PASSWORD)
        )
        assert user is not None
        await session.execute(update(User).where(User.id == user.id).values(status=status))
        await session.commit()
        return user.id


def login_resp(
    client: AsyncClient, user_id: uuid.UUID, status: UserStatus = UserStatus.ACTIVE
) -> None:
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


@pytest_asyncio.fixture
async def logged_in_user(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> uuid.UUID:
    user_id = await create_user(session_factory)
    login_resp(client, user_id)
    return user_id


async def key_row(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> list[UserProviderKey]:
    async with session_factory() as session:
        stmt = select(UserProviderKey).where(UserProviderKey.user_id == user_id)
        return list((await session.execute(stmt)).scalars().all())


# ═══════ 1. Bản rõ KHÔNG vào DB (DoD 1) · nonce riêng mỗi bản ghi (DoD 2) ═══


async def test_key_cipher_has_no_plaintext(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    logged_in_user: uuid.UUID,
) -> None:
    """DoD dòng 1, đo trên cột `key_cipher` THẬT của Postgres."""
    resp = await client.put(ITEM_PATH.format(provider_byok()), json={"key": FAKE_KEY})
    assert resp.status_code == 200, resp.text

    row = await key_row(session_factory, logged_in_user)
    assert len(row) == 1
    assert FAKE_KEY.encode() not in row[0].key_cipher
    assert FAKE_KEY not in row[0].key_last4


async def test_no_table_column_holds_plaintext(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    logged_in_user: uuid.UUID,
) -> None:
    """Chặt hơn dòng trên một bậc: quét **cả hàng** dưới dạng chữ.

    Phép kiểm ở trên chỉ nhìn `key_cipher`; một bản vá vụng về có thể lưu
    thêm bản rõ vào một cột khác mà nó vẫn xanh.
    """
    await client.put(ITEM_PATH.format(provider_byok()), json={"key": FAKE_KEY})
    async with session_factory() as session:
        whole_row = (
            await session.execute(text("SELECT user_provider_keys::text FROM user_provider_keys"))
        ).scalar_one()
    assert FAKE_KEY not in whole_row


async def test_two_users_same_key_get_different_ciphertexts(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """DoD dòng 2 — chứng minh nonce riêng mỗi bản ghi (cạm bẫy của task)."""
    provider = provider_byok()
    ciphertexts: list[bytes] = []
    nonce: list[bytes] = []
    for _ in range(2):
        user_id = await create_user(session_factory)
        login_resp(client, user_id)
        resp = await client.put(ITEM_PATH.format(provider), json={"key": FAKE_KEY})
        assert resp.status_code == 200, resp.text
        row = await key_row(session_factory, user_id)
        ciphertexts.append(row[0].key_cipher)
        nonce.append(row[0].key_nonce)

    assert ciphertexts[0] != ciphertexts[1]
    assert nonce[0] != nonce[1]


async def test_second_put_overwrites_nonce_too(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    logged_in_user: uuid.UUID,
) -> None:
    """`UNIQUE (user_id, provider)` ⇒ đổi khoá là ghi đè, không phải hàng thứ hai.

    Và phải ghi đè **cả** `key_nonce`: giữ nonce cũ với bản mã mới là một hàng
    không giải mã được nữa.
    """
    provider = provider_byok()
    await client.put(ITEM_PATH.format(provider), json={"key": FAKE_KEY})
    before = (await key_row(session_factory, logged_in_user))[0]
    cipher_before, nonce_before = before.key_cipher, before.key_nonce

    resp = await client.put(ITEM_PATH.format(provider), json={"key": FAKE_KEY_2})
    assert resp.status_code == 200

    after = await key_row(session_factory, logged_in_user)
    assert len(after) == 1
    assert after[0].key_cipher != cipher_before
    assert after[0].key_nonce != nonce_before
    assert resp.json()["masked_key"].endswith(FAKE_KEY_2[-4:])


# ═════════════════ 2. Không bao giờ hiện lại (DoD 3, §10.5) ═════════════════


async def test_get_returns_only_masked_string(
    client: AsyncClient, logged_in_user: uuid.UUID
) -> None:
    """DoD dòng 3: `sk-...4f2a`, không bao giờ trả đủ."""
    await client.put(ITEM_PATH.format(provider_byok()), json={"key": FAKE_KEY})

    resp = await client.get(LIST_PATH)
    assert resp.status_code == 200
    assert FAKE_KEY not in resp.text

    key = resp.json()["keys"][0]
    assert key["masked_key"] == "sk-...4f2a"
    assert key["provider"] == provider_byok()
    assert key["usable"] is True
    assert key["verified_at"] is not None


async def test_put_also_returns_only_masked_string(
    client: AsyncClient, logged_in_user: uuid.UUID
) -> None:
    """Response của chính lần lưu cũng không được vọng lại khoá — nếu không,
    "không bao giờ hiển thị lại" chỉ đúng với `GET`."""
    resp = await client.put(ITEM_PATH.format(provider_byok()), json={"key": FAKE_KEY})
    assert FAKE_KEY not in resp.text
    assert resp.json()["masked_key"] == "sk-...4f2a"


async def test_get_without_keys_returns_empty_list(
    client: AsyncClient, logged_in_user: uuid.UUID
) -> None:
    resp = await client.get(LIST_PATH)
    assert resp.status_code == 200
    assert resp.json()["keys"] == []


async def test_get_lists_every_byok_provider_per_catalog(
    client: AsyncClient, logged_in_user: uuid.UUID
) -> None:
    """T-3.12 — trang Cài đặt chọn provider từ `byok_providers`, không từ một
    mảng gõ sẵn ở FE (A3). Đúng tập `byok_supported` của catalog, kể cả khi
    người này chưa có khoá nào; provider không nhận khoá riêng thì vắng mặt.
    `provider` là KHOÁ catalog — thứ `PUT /settings/keys/{provider}` nhận."""
    cat = catalog.get_catalog()

    body = (await client.get(LIST_PATH)).json()

    assert {p["provider"] for p in body["byok_providers"]} == {
        name for name, p in cat.providers.items() if p.byok_supported
    }
    for p in body["byok_providers"]:
        assert p["label"] == cat.providers[p["provider"]].label
    unsupported = provider_without_byok()
    if unsupported is not None:
        assert unsupported not in {p["provider"] for p in body["byok_providers"]}


# ═══════════ 3. Khoá sai ⇒ 400, thông điệp KHÔNG chứa khoá (DoD 4) ══════════


@pytest.mark.parametrize("upstream_status", [401, 403])
async def test_key_rejected_by_provider_is_400(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    logged_in_user: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    upstream_status: int,
) -> None:
    """DoD dòng 4 — và khoá **không** được lưu (§10.5: kiểm TRƯỚC khi lưu)."""
    set_transport(monkeypatch, lambda _r: httpx.Response(upstream_status, json={"error": "nope"}))

    resp = await client.put(ITEM_PATH.format(provider_byok()), json={"key": FAKE_KEY})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == ApiErrorCode.PROVIDER_KEY_REJECTED
    assert FAKE_KEY not in resp.text
    assert await key_row(session_factory, logged_in_user) == []


async def test_unreachable_provider_is_503_not_400(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    logged_in_user: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ "Không biết" khác "khoá sai": nói với người dùng rằng khoá của họ hỏng
    khi thật ra mạng hỏng sẽ khiến họ đi tạo một khoá mới vô ích.

    Và khoá cũng KHÔNG được lưu: một sự cố tạm thời không được biến thành một
    hàng dữ liệu vĩnh viễn mang `verified_at IS NULL`.
    """

    def _no(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("khong noi duoc (gia lap)")

    set_transport(monkeypatch, _no)

    resp = await client.put(ITEM_PATH.format(provider_byok()), json={"key": FAKE_KEY})
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == ApiErrorCode.SERVICE_UNAVAILABLE
    assert FAKE_KEY not in resp.text
    assert await key_row(session_factory, logged_in_user) == []


async def test_body_without_key_422_and_echoes_nothing(
    client: AsyncClient, logged_in_user: uuid.UUID
) -> None:
    """§20: `details` của 422 không mang `input` — ở route này `input` chính
    là khoá người dùng vừa dán."""
    resp = await client.put(ITEM_PATH.format(provider_byok()), json={"khong-phai-key": "x"})
    assert resp.status_code == 422
    assert "input" not in resp.text


async def test_empty_key_is_422(client: AsyncClient, logged_in_user: uuid.UUID) -> None:
    resp = await client.put(ITEM_PATH.format(provider_byok()), json={"key": ""})
    assert resp.status_code == 422


# ══════════ 4. Đổi MASTER_ENCRYPTION_KEY ⇒ hỏng CÓ KIỂM SOÁT (DoD 6) ════════


async def test_master_key_change_usable_false_not_500(
    client: AsyncClient, logged_in_user: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DoD dòng 6. `GET` vẫn `200`, vẫn hiện chuỗi che, và nói rõ khoá không
    đọc được nữa để FE bảo người dùng nhập lại."""
    await client.put(ITEM_PATH.format(provider_byok()), json={"key": FAKE_KEY})

    monkeypatch.setattr(settings, "MASTER_ENCRYPTION_KEY", SecretStr("x" * 64))

    resp = await client.get(LIST_PATH)
    assert resp.status_code == 200
    key = resp.json()["keys"][0]
    assert key["usable"] is False
    assert key["masked_key"] == "sk-...4f2a"


async def test_master_key_change_then_reentry_makes_usable_again(
    client: AsyncClient, logged_in_user: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "Báo user nhập lại" chỉ có nghĩa nếu nhập lại thật sự chữa được."""
    await client.put(ITEM_PATH.format(provider_byok()), json={"key": FAKE_KEY})
    monkeypatch.setattr(settings, "MASTER_ENCRYPTION_KEY", SecretStr("x" * 64))
    assert (await client.get(LIST_PATH)).json()["keys"][0]["usable"] is False

    await client.put(ITEM_PATH.format(provider_byok()), json={"key": FAKE_KEY})
    assert (await client.get(LIST_PATH)).json()["keys"][0]["usable"] is True


# ═════════════════ 5. Phân quyền và cách ly giữa hai user ═══════════════════


async def test_not_logged_in_cannot_enter(client: AsyncClient) -> None:
    resp = await client.get(LIST_PATH)
    assert resp.status_code in (401, 503)


async def test_other_users_key_is_not_shown(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """§20 — lọc `user_id` trong câu SQL."""
    person_a = await create_user(session_factory)
    login_resp(client, person_a)
    await client.put(ITEM_PATH.format(provider_byok()), json={"key": FAKE_KEY})

    person_b = await create_user(session_factory)
    login_resp(client, person_b)
    assert (await client.get(LIST_PATH)).json()["keys"] == []


async def test_cannot_delete_other_users_key(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    person_a = await create_user(session_factory)
    login_resp(client, person_a)
    await client.put(ITEM_PATH.format(provider_byok()), json={"key": FAKE_KEY})

    person_b = await create_user(session_factory)
    login_resp(client, person_b)
    resp = await client.delete(ITEM_PATH.format(provider_byok()))
    assert resp.status_code == 404
    assert len(await key_row(session_factory, person_a)) == 1


async def test_pending_approval_can_add_key(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """§11.1 cho `pending_approval` chat bằng BYOK — cánh cửa đó chỉ mở khi họ
    **thêm được** khoá. Chặn ở đây là khoá vòng."""
    user_id = await create_user(session_factory, UserStatus.PENDING_APPROVAL)
    login_resp(client, user_id, UserStatus.PENDING_APPROVAL)
    resp = await client.put(ITEM_PATH.format(provider_byok()), json={"key": FAKE_KEY})
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("status", [UserStatus.REJECTED, UserStatus.SUSPENDED])
async def test_disabled_account_cannot_enter(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    status: UserStatus,
) -> None:
    """Router nằm trong `_AUTHENTICATED`, tức cột "Xem UI" của §11.1."""
    user_id = await create_user(session_factory, status)
    login_resp(client, user_id, status)
    resp = await client.get(LIST_PATH)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == ApiErrorCode.ACCOUNT_DISABLED


# ═══════════════ 6. Catalog quyết định provider nào hợp lệ ══════════════════


async def test_unknown_provider_is_404(client: AsyncClient, logged_in_user: uuid.UUID) -> None:
    resp = await client.put(ITEM_PATH.format("provider-khong-ton-tai"), json={"key": FAKE_KEY})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == ApiErrorCode.PROVIDER_UNKNOWN


async def test_provider_without_byok_support_is_400(
    client: AsyncClient, logged_in_user: uuid.UUID
) -> None:
    name = provider_without_byok()
    assert name is not None, "catalog phải có ít nhất một provider KHÔNG hỗ trợ BYOK"
    resp = await client.put(ITEM_PATH.format(name), json={"key": FAKE_KEY})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == ApiErrorCode.BYOK_NOT_SUPPORTED


async def test_missing_verify_path_saves_but_unverified(
    client: AsyncClient, logged_in_user: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C42 — và `verified_at` phải là `null`, không phải `now()`."""
    provider = provider_byok()
    original = catalog.get_catalog().providers[provider]
    monkeypatch.setitem(
        catalog.get_catalog().providers, provider, original.model_copy(update={"verify_path": None})
    )

    resp = await client.put(ITEM_PATH.format(provider), json={"key": FAKE_KEY})
    assert resp.status_code == 200
    assert resp.json()["verified_at"] is None


# ═══════════════════════════════ DELETE ═════════════════════════════════════


async def test_delete_key(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    logged_in_user: uuid.UUID,
) -> None:
    provider = provider_byok()
    await client.put(ITEM_PATH.format(provider), json={"key": FAKE_KEY})

    resp = await client.delete(ITEM_PATH.format(provider))
    assert resp.status_code == 204
    assert await key_row(session_factory, logged_in_user) == []


async def test_second_delete_is_404(client: AsyncClient, logged_in_user: uuid.UUID) -> None:
    provider = provider_byok()
    await client.put(ITEM_PATH.format(provider), json={"key": FAKE_KEY})
    assert (await client.delete(ITEM_PATH.format(provider))).status_code == 204

    resp = await client.delete(ITEM_PATH.format(provider))
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == ApiErrorCode.PROVIDER_KEY_NOT_FOUND


async def test_can_delete_key_of_provider_removed_from_catalog(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    logged_in_user: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`DELETE` cố ý KHÔNG hỏi catalog: một hàng mồ côi vẫn phải xoá được."""
    provider = provider_byok()
    await client.put(ITEM_PATH.format(provider), json={"key": FAKE_KEY})

    providers = dict(catalog.get_catalog().providers)
    del providers[provider]
    monkeypatch.setattr(catalog.get_catalog(), "providers", providers)

    assert (await client.delete(ITEM_PATH.format(provider))).status_code == 204
    assert await key_row(session_factory, logged_in_user) == []
