"""T-9.5a — test canh log: nội dung, prompt, kết quả tool, khoá BYOK KHÔNG vào log.

KH tham chiếu: §20 (Log: "không log … token, key BYOK, nội dung message đầy
đủ"), C20 · tasks.md T-9.5a (Cạm bẫy ⑦: nội dung tự do chặn ở chỗ gọi
`logger`, không trông vào bộ che).

Một lượt chat đầy đủ, chuỗi canary ở MỌI chỗ người dùng / model / tool đưa chữ
vào: câu hỏi (đường `api` — `POST …/messages` qua ASGI), câu trả lời giả có
khối artifact, chữ trang `fetch_url` trả về (đường `worker` — `generate` thật,
Postgres thật), và một khoá BYOK mà provider "nhại lại" trong thông báo lỗi.

`caplog` mức `DEBUG` cho cây `app` — đúng phạm vi mà `LOG_LEVEL=DEBUG` mở ở
production (`app/core/log_setup.py` chỉ đặt mức cho `app`; thư viện ngoài ở
mức mặc định `WARNING`). Mỗi ca khẳng định cả vế "có log" (record `app.*` của
đúng đường ấy) để một lượt không log gì không xanh vô nghĩa.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_generate import (
    MODEL_ID,
    FakeClient,
    FakeRedis,
    _ctx,
    _FakeByok,
    _minimal_tree,
    _normal_chunks,
)
from test_tool_loop import ROUND1, TOOLS_MODEL, FetchRecorder, SeqClient

from app.config.catalog import get_model
from app.core.access_token import encode_access_token
from app.core.crypto import mask_secret, seal
from app.core.deps import SESSION_COOKIE_NAME
from app.db.models import UserRole, UserStatus
from app.db.repositories import ConversationRepository, ProviderKeyRepository
from app.main import app
from app.tools import registry as registry_mod
from app.workers.generate import generate

pytestmark = pytest.mark.usefixtures("all_catalog_models_enabled")

CANARY = f"CANARY-{uuid.uuid4().hex}"


@pytest.fixture(autouse=True)
def _wire(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
    idempotency_redis_fake: Any,
    ratelimit_redis_fake: Any,
    blacklist_redis_fake: Any,
    quota_redis_fake: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Postgres của test + Redis giả cho cả hai đường; `caplog` thấy cây `app`."""
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr("app.core.idempotency.get_redis", lambda: idempotency_redis_fake)
    monkeypatch.setattr("app.core.ratelimit.get_redis", lambda: ratelimit_redis_fake)
    monkeypatch.setattr("app.core.deps.get_redis", lambda: blacklist_redis_fake)
    for module in ("estimator", "tiers", "snapshot", "web_searches"):
        monkeypatch.setattr(f"app.quota.{module}.get_redis", lambda: quota_redis_fake)
    # Một test khác (`cli`, `on_startup`) gọi `setup_logging()` ⇒ `propagate=False`
    # ⇒ record `app.*` không tới handler của `caplog` ở root.
    monkeypatch.setattr(logging.getLogger("app"), "propagate", True)
    caplog.set_level(logging.DEBUG, logger="app")


def _assert_clean(caplog: pytest.LogCaptureFixture, *secrets: str) -> None:
    # `caplog.text` = record đã format, gồm cả traceback (`exc_text`).
    for secret in secrets:
        assert secret not in caplog.text
        assert all(secret not in r.getMessage() for r in caplog.records)


class _Arq:
    """Pool arq giả: `generate` nhận, `title` trả `None` (ca "đã có trong hàng đợi")."""

    def __init__(self) -> None:
        self.pushed: list[tuple[str, tuple[Any, ...]]] = []

    async def enqueue_job(self, name: str, *args: Any, **_: Any) -> object | None:
        self.pushed.append((name, args))
        return None if name == "title" else object()


@pytest_asyncio.fixture
async def http(
    monkeypatch: pytest.MonkeyPatch, event_hooks: dict[str, Any]
) -> AsyncIterator[AsyncClient]:
    arq = _Arq()

    async def _pool() -> _Arq:
        return arq

    monkeypatch.setattr("app.api.v1.messages.get_arq_pool", _pool)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://localhost", event_hooks=event_hooks
    ) as client:
        yield client


async def test_full_turn_api_then_worker_tool_and_artifact_canary_not_logged(
    http: AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Câu hỏi → `api`; tool `fetch_url` + câu trả lời có artifact → `worker`."""
    async with session_factory() as s:
        conv = await ConversationRepository(s).create_conversation(user_id=user_a)
        await s.commit()
    token = encode_access_token(
        user_id=user_a, role=UserRole.USER, tier="free", status=UserStatus.ACTIVE, ttl_minutes=15
    )

    resp = await http.post(
        f"/api/v1/conversations/{conv.id}/messages",
        headers={"Cookie": f"{SESSION_COOKIE_NAME}={token}"},
        json={
            "content": f"Đọc trang này giúp tôi {CANARY}-question",
            "model_id": TOOLS_MODEL,
            "web_tools": True,
        },
    )
    assert resp.status_code == 202, resp.text
    api_lines = [r.getMessage() for r in caplog.records if r.name.startswith("app.api")]
    assert any("da co trong hang doi" in line for line in api_lines), api_lines

    fetch = FetchRecorder()
    fetch.text = f"Trang web nói {CANARY}-tool-result"
    monkeypatch.setattr(registry_mod, "fetch_url", fetch)
    answer = _normal_chunks(
        [f"Đây là {CANARY}-answer.\n\n", '```html title="Trang"\n', f"<p>{CANARY}</p>\n```\n"]
    )

    await generate(
        _ctx(FakeRedis(), SeqClient(ROUND1, answer)),  # type: ignore[arg-type]
        resp.json()["assistant_message_id"],
    )

    assert fetch.urls, "tool phải chạy thật — không thì kết quả tool không đi qua log nào"
    worker_lines = [r.getMessage() for r in caplog.records if r.name.startswith("app.workers")]
    assert any("generate: xong" in line and "ok" in line for line in worker_lines), worker_lines
    _assert_clean(caplog, CANARY)


async def test_byok_key_echoed_by_upstream_error_is_not_logged(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """C20 vế thứ hai: provider nhại khoá trong lỗi ⇒ `GenerationError` mang nó.

    `generate` log lỗi ấy bằng `%s` với **object exception** làm tham số — bộ che
    phải che cả tham số không phải `str`.
    """
    key = "sk-" + uuid.uuid4().hex + "BYOKCANARY"
    model = get_model(MODEL_ID)
    assert model is not None
    message = await _minimal_tree(session, user_a)
    async with session_factory() as s:
        await ProviderKeyRepository(s).upsert(
            user_id=user_a,
            provider=model.provider,
            sealed=seal(key),
            masked=mask_secret(key),
            verified_at=None,
        )
        await s.commit()
    upstream = _FakeByok([], error=RuntimeError(f"401 Incorrect API key provided: {key}"))
    monkeypatch.setattr("app.workers.generate.ByokAdapter.for_provider", lambda *_a, **_k: upstream)

    await generate(_ctx(FakeRedis(), FakeClient([])), str(message.id))

    lines = [r.getMessage() for r in caplog.records if r.name == "app.workers.generate"]
    assert any("dung vi UPSTREAM_ERROR" in line for line in lines), lines
    _assert_clean(caplog, key, key.removeprefix("sk-"))
