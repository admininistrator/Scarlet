"""Endpoint BYOK người dùng tự nhập — T-S.19b (NQ-134 ② ③, A5, A8, §20).

Không ca nào chạm Internet: DNS là resolver giả bơm vào `validate_url()` qua
`byok_endpoints.validate_url`, và mạng là `PinnedTransport.handle_async_request`
bị thay — tức request **có** đi qua transport ghim IP của T-6.3 (Cạm bẫy ②);
một đường gọi quên client ấy sẽ không chạm bộ ghi ở đây.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from decimal import Decimal
from typing import Any

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import settings
from app.core.access_token import encode_access_token
from app.core.crypto import Sealed, mask_secret, seal
from app.core.deps import SESSION_COOKIE_NAME
from app.db.models import (
    CostConfidence,
    KeySource,
    Message,
    MessageRole,
    UsagePurpose,
    UserByokEndpoint,
    UserRole,
    UserStatus,
)
from app.db.repositories import (
    ByokEndpointRepository,
    ProviderKeyRepository,
    UsageEventRepository,
)
from app.llm import byok_endpoints
from app.llm.byok_endpoints import BaseUrlRejected, normalize_base_url, parse_model_id
from app.main import app
from app.tools import ssrf
from app.tools.ssrf import PinnedTransport

LIST = "/api/v1/settings/byok-endpoints"
PROBE = LIST + "/probe"
ITEM = LIST + "/{}"
MESSAGES = "/api/v1/conversations/{}/messages"

KEY = "sk-" + "khongphaikhoathat" * 2
BASE = "https://llm.example/v1"
PUBLIC_IP = "93.184.215.14"

#: Resolver giả: tên → địa chỉ. Tên lạ ⇒ `gaierror` (mã `dns`).
_DNS = {"llm.example": [PUBLIC_IP], "127.0.0.1.nip.io": ["127.0.0.1"], "host": [PUBLIC_IP]}


class _Net:
    """Thay chỗ socket dưới `PinnedTransport` — ghi request, trả lời theo `handler`."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.handler: Callable[[httpx.Request], httpx.Response] = lambda _r: httpx.Response(
            200, json={"data": [{"id": "model-b"}, {"id": "model-a"}, {"x": 1}]}
        )


@pytest.fixture(autouse=True)
def net(monkeypatch: pytest.MonkeyPatch) -> _Net:
    fake = _Net()

    async def _handle(self: PinnedTransport, request: httpx.Request) -> httpx.Response:
        fake.requests.append(request)
        return fake.handler(request)

    async def _resolve(host: str, port: int) -> list[str]:
        if host not in _DNS:
            raise OSError("gaierror gia lap")
        return _DNS[host]

    monkeypatch.setattr(PinnedTransport, "handle_async_request", _handle)
    monkeypatch.setattr(
        byok_endpoints, "validate_url", lambda url: ssrf.validate_url(url, resolver=_resolve)
    )
    return fake


@pytest.fixture(autouse=True)
def _db_for_tests(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


class _FakeArq:
    def __init__(self) -> None:
        self.pushed: list[tuple[str, tuple[Any, ...]]] = []

    async def enqueue_job(self, name: str, *args: Any, **kwargs: Any) -> object:
        self.pushed.append((name, args))
        return object()


@pytest.fixture
def fake_arq(monkeypatch: pytest.MonkeyPatch) -> _FakeArq:
    fake = _FakeArq()

    async def _pool() -> _FakeArq:
        return fake

    monkeypatch.setattr("app.api.v1.messages.get_arq_pool", _pool)
    return fake


@pytest_asyncio.fixture
async def client(event_hooks: dict[str, Any]) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://localhost", event_hooks=event_hooks
    ) as http:
        yield http


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    token = encode_access_token(
        user_id=user_id, role=UserRole.USER, tier="free", status=UserStatus.ACTIVE, ttl_minutes=15
    )
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


async def _create(client: AsyncClient, user_id: uuid.UUID, **body: Any) -> httpx.Response:
    payload = {"label": "Cua toi", "base_url": BASE, "key": KEY, "models": ["model-a"], **body}
    return await client.post(LIST, headers=_auth(user_id), json=payload)


# ─────────────────────────── base URL (A5, C43) ───────────────────────────


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("http://llm.example/v1", "scheme"),
        ("https://redis:6379/v1", "port"),
        ("https://169.254.169.254/v1", "address"),
        ("https://u@host/v1", "userinfo"),
        ("https://127.0.0.1.nip.io/v1", "address"),
        ("https://khong-resolve-duoc.example/v1", "dns"),
        ("https://llm.example/v1?x=1", "query"),
        ("https://llm.example/v1#a", "query"),
        ("https://llm.example/api", "version"),
    ],
)
async def test_probe_rejects_unsafe_base_url(
    client: AsyncClient, user_a: uuid.UUID, net: _Net, url: str, reason: str
) -> None:
    """DoD 1: năm URL của task ⇒ `400 URL_UNSAFE`; không gói nào đi ra."""
    resp = await client.post(PROBE, headers=_auth(user_a), json={"base_url": url, "key": KEY})

    assert resp.status_code == 400, resp.text
    error = resp.json()["error"]
    assert error["code"] == "URL_UNSAFE"
    assert error["details"] == {"reason": reason}
    assert "127.0.0.1" not in resp.text.replace(url, "")
    assert net.requests == []


def test_normalize_strips_trailing_slash_and_keeps_version() -> None:
    assert normalize_base_url("  https://LLM.example/v1/  ") == "https://llm.example/v1"
    assert normalize_base_url("https://llm.example/api/v1beta") == "https://llm.example/api/v1beta"
    with pytest.raises(BaseUrlRejected):
        normalize_base_url("https://llm.example/v1?")


def test_parse_model_id_keeps_slashes_in_model_name() -> None:
    eid = uuid.uuid4()
    assert parse_model_id(f"byok:{eid}/deepseek/deepseek-chat") == (eid, "deepseek/deepseek-chat")
    assert parse_model_id(f"byok:{eid}/") is None
    assert parse_model_id("byok:khong-phai-uuid/m") is None
    assert parse_model_id("deepseek-flash") is None


# ─────────────────────────── probe ───────────────────────────


async def test_probe_lists_models_through_pinned_transport(
    client: AsyncClient, user_a: uuid.UUID, net: _Net
) -> None:
    resp = await client.post(
        PROBE, headers=_auth(user_a), json={"base_url": BASE + "/", "key": KEY}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"models": ["model-a", "model-b"], "verified": True}
    (sent,) = net.requests
    assert str(sent.url) == BASE + "/models"
    assert sent.headers["authorization"] == f"Bearer {KEY}"


async def test_probe_rejected_key_is_400_without_key_in_body(
    client: AsyncClient, user_a: uuid.UUID, net: _Net
) -> None:
    net.handler = lambda _r: httpx.Response(401, json={"error": "bad key"})

    resp = await client.post(PROBE, headers=_auth(user_a), json={"base_url": BASE, "key": KEY})

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "PROVIDER_KEY_REJECTED"
    assert KEY not in resp.text


async def test_probe_without_models_endpoint_is_empty_list_unverified(
    client: AsyncClient, user_a: uuid.UUID, net: _Net
) -> None:
    """C42: endpoint không có `/models` ⇒ `models: []`, FE cho gõ tay."""
    net.handler = lambda _r: httpx.Response(404)

    resp = await client.post(PROBE, headers=_auth(user_a), json={"base_url": BASE, "key": KEY})

    assert resp.status_code == 200
    assert resp.json() == {"models": [], "verified": False}


async def test_probe_network_failure_is_503(
    client: AsyncClient, user_a: uuid.UUID, net: _Net
) -> None:
    def _down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("mang hong", request=request)

    net.handler = _down

    resp = await client.post(PROBE, headers=_auth(user_a), json={"base_url": BASE, "key": KEY})

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


# ─────────────────────────── CRUD ───────────────────────────


async def test_create_without_idempotency_key_is_400(user_a: uuid.UUID, net: _Net) -> None:
    """DoD 1 / A8 — client không có hook tự gắn khoá."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as raw:
        resp = await raw.post(
            LIST,
            headers=_auth(user_a),
            json={"label": "x", "base_url": BASE, "key": KEY, "models": ["m"]},
        )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert net.requests == []


async def test_create_verifies_then_stores_sealed_key(
    client: AsyncClient,
    user_a: uuid.UUID,
    net: _Net,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    resp = await _create(client, user_a, base_url=BASE + "/", models=["m1", "m1", "m2"])

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert KEY not in resp.text
    assert body["masked_key"] == mask_secret(KEY)
    assert body["base_url"] == BASE
    assert body["models"] == ["m1", "m2"]
    assert body["verified_at"] is not None
    assert (body["prompt_tokens"], body["completion_tokens"]) == (0, 0)
    assert len(net.requests) == 1, "§10.5: kiểm lại trước khi lưu"
    async with session_factory() as s:
        row = (await s.execute(select(UserByokEndpoint))).scalar_one()
    assert KEY.encode() not in row.key_cipher
    assert row.user_id == user_a


async def test_create_with_rejected_key_stores_nothing(
    client: AsyncClient,
    user_a: uuid.UUID,
    net: _Net,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    net.handler = lambda _r: httpx.Response(403)

    resp = await _create(client, user_a)

    assert resp.status_code == 400
    async with session_factory() as s:
        assert (await s.execute(select(UserByokEndpoint))).first() is None


async def test_duplicate_label_is_409_and_limit_is_400(
    client: AsyncClient, user_a: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert (await _create(client, user_a)).status_code == 201

    duplicate = await _create(client, user_a)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "BYOK_ENDPOINT_LABEL_TAKEN"

    monkeypatch.setattr(settings, "BYOK_ENDPOINTS_MAX_PER_USER", 1)
    over = await _create(client, user_a, label="Thu hai")
    assert over.status_code == 400
    assert over.json()["error"]["code"] == "BYOK_ENDPOINT_LIMIT"


async def test_patch_only_label_and_models(client: AsyncClient, user_a: uuid.UUID) -> None:
    eid = (await _create(client, user_a)).json()["id"]

    resp = await client.patch(
        ITEM.format(eid), headers=_auth(user_a), json={"label": "Moi", "models": ["x", "y"]}
    )
    assert resp.status_code == 200
    assert (resp.json()["label"], resp.json()["models"]) == ("Moi", ["x", "y"])

    url_change = await client.patch(
        ITEM.format(eid), headers=_auth(user_a), json={"base_url": "https://khac.example/v1"}
    )
    assert url_change.status_code == 422, "đổi URL / khoá là xoá rồi thêm (§10.5)"


async def test_other_user_gets_404_and_cannot_see_or_use(
    client: AsyncClient, user_a: uuid.UUID, user_b: uuid.UUID, fake_arq: _FakeArq
) -> None:
    """DoD 1 / §20: B `GET` / `PATCH` / `DELETE` endpoint của A ⇒ `404`."""
    eid = (await _create(client, user_a)).json()["id"]

    listed = await client.get(LIST, headers=_auth(user_b))
    assert listed.json()["endpoints"] == []
    patched = await client.patch(ITEM.format(eid), headers=_auth(user_b), json={"label": "B"})
    assert patched.status_code == 404
    assert patched.json()["error"]["code"] == "BYOK_ENDPOINT_NOT_FOUND"
    deleted = await client.delete(ITEM.format(eid), headers=_auth(user_b))
    assert deleted.status_code == 404

    conv = await client.post("/api/v1/conversations", headers=_auth(user_b), json={})
    sent = await client.post(
        MESSAGES.format(conv.json()["id"]),
        headers=_auth(user_b),
        json={"content": "a", "model_id": f"byok:{eid}/model-a"},
    )
    assert sent.status_code == 400
    assert sent.json()["error"]["code"] == "MODEL_UNKNOWN"
    assert fake_arq.pushed == []

    still = await client.get(LIST, headers=_auth(user_a))
    assert [e["label"] for e in still.json()["endpoints"]] == ["Cua toi"]
    assert (await client.delete(ITEM.format(eid), headers=_auth(user_a))).status_code == 204
    assert (await client.delete(ITEM.format(eid), headers=_auth(user_a))).status_code == 404


# ─────────────── model của endpoint đã lưu + trần (NQ-137 ①) ───────────────


async def test_saved_endpoint_models_use_stored_key_and_owner_only(
    client: AsyncClient, user_a: uuid.UUID, user_b: uuid.UUID, net: _Net
) -> None:
    """Form "Sửa endpoint": hỏi `/models` bằng khoá ĐÃ LƯU, qua transport ghim IP;
    của người khác ⇒ `404` và không gói nào đi ra."""
    eid = (await _create(client, user_a)).json()["id"]
    net.requests.clear()

    resp = await client.get(ITEM.format(eid) + "/models", headers=_auth(user_a))

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"models": ["model-a", "model-b"], "verified": True}
    (sent,) = net.requests
    assert str(sent.url) == BASE + "/models"
    assert sent.headers["authorization"] == f"Bearer {KEY}"
    assert KEY not in resp.text

    other = await client.get(ITEM.format(eid) + "/models", headers=_auth(user_b))
    assert other.status_code == 404
    assert other.json()["error"]["code"] == "BYOK_ENDPOINT_NOT_FOUND"
    assert len(net.requests) == 1

    listed = await client.get(LIST, headers=_auth(user_a))
    assert listed.json()["max_endpoints"] == settings.BYOK_ENDPOINTS_MAX_PER_USER


async def test_saved_endpoint_models_with_unreadable_key_is_400(
    client: AsyncClient,
    user_a: uuid.UUID,
    net: _Net,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Khoá không giải mã được (đổi `MASTER_ENCRYPTION_KEY`) ⇒ `PROVIDER_KEY_REJECTED`,
    không gọi endpoint."""
    sealed = seal(KEY)
    async with session_factory() as s:
        row = await ByokEndpointRepository(s).create(
            user_id=user_a,
            label="Hong",
            base_url=BASE,
            sealed=Sealed(cipher=b"\x00" * len(sealed.cipher), nonce=sealed.nonce),
            masked="x",
            models=["m"],
            verified_at=None,
        )
        await s.commit()

    resp = await client.get(ITEM.format(row.id) + "/models", headers=_auth(user_a))

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "PROVIDER_KEY_REJECTED"
    assert net.requests == []


# ─────────────────────────── tổng token (NQ-134 ③) ───────────────────────────


async def _ledger(
    session_factory: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
    provider: str,
    key_source: KeySource,
    tokens: tuple[int, int],
) -> None:
    async with session_factory() as s:
        await UsageEventRepository(s).record(
            user_id=user_id,
            message_id=None,
            model_id="m",
            provider=provider,
            key_source=key_source,
            prompt_tokens=tokens[0],
            completion_tokens=tokens[1],
            cached_tokens=0,
            cost_usd=Decimal(0),
            cost_confidence=CostConfidence.EXACT,
            price_snapshot={},
            purpose=UsagePurpose.CHAT,
        )
        await s.commit()


async def test_token_totals_are_byok_sums_of_the_caller(
    client: AsyncClient,
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    eid = uuid.UUID((await _create(client, user_a)).json()["id"])
    provider = byok_endpoints.provider_for(eid)
    await _ledger(session_factory, user_a, provider, KeySource.BYOK, (100, 20))
    await _ledger(session_factory, user_a, provider, KeySource.BYOK, (5, 1))
    await _ledger(session_factory, user_b, provider, KeySource.BYOK, (999, 999))
    async with session_factory() as s:
        await ProviderKeyRepository(s).upsert(
            user_id=user_a, provider="deepseek", sealed=seal(KEY), masked="x", verified_at=None
        )
        await s.commit()
    await _ledger(session_factory, user_a, "deepseek", KeySource.BYOK, (7, 3))
    await _ledger(session_factory, user_a, "deepseek", KeySource.SYSTEM, (1000, 1000))

    endpoints = (await client.get(LIST, headers=_auth(user_a))).json()["endpoints"]
    keys = (await client.get("/api/v1/settings/keys", headers=_auth(user_a))).json()["keys"]

    assert (endpoints[0]["prompt_tokens"], endpoints[0]["completion_tokens"]) == (105, 21)
    assert [(k["provider"], k["prompt_tokens"], k["completion_tokens"]) for k in keys] == [
        ("deepseek", 7, 3)
    ]


# ─────────────────────────── chọn model `byok:<id>/<model>` ──────────────────


async def test_message_with_endpoint_model_skips_quota_and_pins_model(
    client: AsyncClient,
    user_a: uuid.UUID,
    fake_arq: _FakeArq,
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Không qua cửa quota (§10.5) — `check_quota` nổ nếu bị gọi."""

    async def _boom(*_a: Any, **_k: Any) -> None:
        raise AssertionError("BYOK không được qua cửa quota")

    monkeypatch.setattr("app.api.v1.messages.check_quota", _boom)
    eid = (await _create(client, user_a, models=["deepseek/deepseek-chat"])).json()["id"]
    model_id = f"byok:{eid}/deepseek/deepseek-chat"
    conv = (await client.post("/api/v1/conversations", headers=_auth(user_a), json={})).json()

    resp = await client.post(
        MESSAGES.format(conv["id"]),
        headers=_auth(user_a),
        json={"content": "xin chao", "model_id": model_id},
    )

    assert resp.status_code == 202, resp.text
    async with session_factory() as s:
        answer = await s.get(Message, uuid.UUID(resp.json()["assistant_message_id"]))
    assert answer is not None
    assert (answer.role, answer.model_id) == (MessageRole.ASSISTANT, model_id)


async def test_endpoint_model_rejects_reasoning_and_unknown_model(
    client: AsyncClient, user_a: uuid.UUID, fake_arq: _FakeArq
) -> None:
    eid = (await _create(client, user_a)).json()["id"]
    conv = (await client.post("/api/v1/conversations", headers=_auth(user_a), json={})).json()
    path = MESSAGES.format(conv["id"])

    reasoning = await client.post(
        path,
        headers=_auth(user_a),
        json={"content": "a", "model_id": f"byok:{eid}/model-a", "reasoning_effort": "high"},
    )
    unlisted = await client.post(
        path, headers=_auth(user_a), json={"content": "a", "model_id": f"byok:{eid}/khac"}
    )

    assert reasoning.json()["error"]["code"] == "REASONING_UNSUPPORTED"
    assert unlisted.json()["error"]["code"] == "MODEL_UNKNOWN"
    assert fake_arq.pushed == []


async def test_conversation_default_model_accepts_own_endpoint_only(
    client: AsyncClient, user_a: uuid.UUID, user_b: uuid.UUID
) -> None:
    eid = (await _create(client, user_a)).json()["id"]
    model_id = f"byok:{eid}/model-a"

    own = await client.post(
        "/api/v1/conversations", headers=_auth(user_a), json={"default_model": model_id}
    )
    other = await client.post(
        "/api/v1/conversations", headers=_auth(user_b), json={"default_model": model_id}
    )
    account_default = await client.put(
        "/api/v1/settings", headers=_auth(user_a), json={"default_model": model_id}
    )

    assert own.status_code == 201
    assert own.json()["default_model"] == model_id
    assert other.json()["error"]["code"] == "MODEL_UNKNOWN"
    assert account_default.json()["error"]["code"] == "MODEL_UNKNOWN", "mặc định tài khoản: catalog"


async def test_repository_filters_user_in_sql(
    session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID, user_b: uuid.UUID
) -> None:
    async with session_factory() as s:
        repo = ByokEndpointRepository(s)
        row = await repo.create(
            user_id=user_a,
            label="a",
            base_url=BASE,
            sealed=seal(KEY),
            masked="x",
            models=["m"],
            verified_at=None,
        )
        assert await repo.get(user_id=user_b, endpoint_id=row.id) is None
        assert await repo.update(user_id=user_b, endpoint_id=row.id, label="b", models=None) is None
        assert await repo.delete(user_id=user_b, endpoint_id=row.id) is False
