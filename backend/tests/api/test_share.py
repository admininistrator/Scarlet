"""T-8.1 — `POST /conversations/{id}/share` + `GET /s/{token}` (ADR-14, §16.1, UC-11).

Cây dựng bằng repository như `test_artifacts.py`. MinIO giả ở MỘT chỗ nối —
`storage.copy` / `storage.remove`; `presign_get` thật (ký là phép tính thuần).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlsplit

import pytest
import pytest_asyncio
import urllib3
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.v1 import share as share_api
from app.config.catalog import get_catalog
from app.config.settings import MINIO_RETRIES, settings
from app.core import storage
from app.core.access_token import encode_access_token
from app.core.deps import SESSION_COOKIE_NAME
from app.core.idempotency import HEADER_IDEMPOTENCY, HEADER_REPLAY
from app.db.models import (
    Message,
    MessageRole,
    MessageStatus,
    SharedConversation,
    User,
    UserRole,
    UserStatus,
)
from app.db.repositories import (
    ArtifactRepository,
    AttachmentRepository,
    ConversationRepository,
    MessageRepository,
)
from app.llm.artifact_blocks import ArtifactBlock
from app.main import app

API = "/api/v1"
MODEL_ID = get_catalog().models[0].id


@pytest.fixture(autouse=True)
def _db_for_tests(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


class FakeStorage:
    def __init__(self) -> None:
        self.copies: list[tuple[str, str]] = []
        self.removed: list[str] = []
        self.fail_on: int | None = None

    async def copy(self, source: str, target: str) -> None:
        if self.fail_on is not None and len(self.copies) == self.fail_on:
            raise urllib3.exceptions.MaxRetryError(None, target)  # type: ignore[arg-type]
        self.copies.append((source, target))

    async def remove(self, key: str) -> None:
        self.removed.append(key)


@pytest.fixture(autouse=True)
def fake_storage(monkeypatch: pytest.MonkeyPatch) -> FakeStorage:
    fake = FakeStorage()
    monkeypatch.setattr(storage, "copy", fake.copy)
    monkeypatch.setattr(storage, "remove", fake.remove)
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


class _Conv:
    def __init__(self, session: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID):
        self.session = session
        self.user_id = user_id
        self.id = conversation_id

    async def add(
        self,
        parent: uuid.UUID | None,
        role: MessageRole,
        content: str,
        status: MessageStatus = MessageStatus.COMPLETED,
    ) -> Message:
        message = await MessageRepository(self.session).create_message(
            conversation_id=self.id,
            user_id=self.user_id,
            role=role,
            parent_id=parent,
            content=content,
            status=status,
            model_id=MODEL_ID if role == MessageRole.ASSISTANT else None,
        )
        await ConversationRepository(self.session).set_active_leaf(
            self.id, user_id=self.user_id, message_id=message.id
        )
        return message

    async def turn(self, parent: uuid.UUID | None, text: str = "hoi") -> tuple[Message, Message]:
        question = await self.add(parent, MessageRole.USER, text)
        return question, await self.add(question.id, MessageRole.ASSISTANT, f"tra loi {text}")


async def _conv(session: AsyncSession, user_id: uuid.UUID) -> _Conv:
    repo = ConversationRepository(session)
    row = await repo.create_conversation(user_id=user_id, title="Kế hoạch")
    return _Conv(session, user_id, row.id)


async def _share(client: AsyncClient, conv: _Conv, **headers: str) -> Any:
    return await client.post(
        f"{API}/conversations/{conv.id}/share", headers={**_auth(conv.user_id), **headers}
    )


async def _rows(session_factory: async_sessionmaker[AsyncSession]) -> list[SharedConversation]:
    async with session_factory() as fresh:
        return list((await fresh.execute(select(SharedConversation))).scalars().all())


def _keys(node: Any) -> set[str]:
    if isinstance(node, dict):
        return set(node) | {k for v in node.values() for k in _keys(v)}
    if isinstance(node, list):
        return {k for v in node for k in _keys(v)}
    return set()


# ═══════════════════════════ POST …/share ═══════════════════════════


async def test_owner_gets_201_and_one_row(
    client: AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
) -> None:
    conv = await _conv(session, user_a)
    await conv.turn(None)
    await session.commit()

    resp = await _share(client, conv)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert set(body) == {"token", "url"}
    assert body["url"] == f"{settings.PUBLIC_BASE_URL.rstrip('/')}/s/{body['token']}"
    assert len(body["token"]) >= 22  # 16 byte url-safe
    [row] = await _rows(session_factory)
    assert (row.token, row.owner_id, row.conversation_id) == (body["token"], user_a, conv.id)


async def test_other_user_gets_404_and_no_row(
    client: AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
) -> None:
    """IDOR (§20, lối T-2.18): hội thoại của A, cookie của B ⇒ 404, không 403."""
    conv = await _conv(session, user_a)
    await conv.turn(None)
    await session.commit()

    resp = await client.post(f"{API}/conversations/{conv.id}/share", headers=_auth(user_b))

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"
    assert await _rows(session_factory) == []


async def test_missing_idempotency_key_is_400(session: AsyncSession, user_a: uuid.UUID) -> None:
    conv = await _conv(session, user_a)
    await conv.turn(None)
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as http:
        resp = await _share(http, conv)

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


async def test_same_key_twice_is_one_row_and_replay(
    client: AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
) -> None:
    conv = await _conv(session, user_a)
    await conv.turn(None)
    await session.commit()
    key = {HEADER_IDEMPOTENCY: uuid.uuid4().hex}

    first = await _share(client, conv, **key)
    second = await _share(client, conv, **key)

    assert (first.status_code, second.status_code) == (201, 201)
    assert second.json() == first.json()
    assert second.headers.get(HEADER_REPLAY) == "true"
    assert first.headers.get(HEADER_REPLAY) is None
    assert len(await _rows(session_factory)) == 1


async def test_three_branches_snapshot_is_path_only(
    client: AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
) -> None:
    """C11: hai nhánh anh em không vào snapshot; thứ tự gốc → lá (NQ-18)."""
    conv = await _conv(session, user_a)
    _, a1 = await conv.turn(None, "mot")
    await conv.turn(a1.id, "hai-cu")
    await conv.turn(a1.id, "hai-khac")
    _, a2 = await conv.turn(a1.id, "hai")
    await conv.turn(a2.id, "ba")
    await session.commit()

    resp = await _share(client, conv)
    [row] = await _rows(session_factory)

    contents = [m["content"] for m in row.snapshot_json["messages"]]
    assert contents == ["mot", "tra loi mot", "hai", "tra loi hai", "ba", "tra loi ba"]
    assert resp.status_code == 201


async def test_snapshot_keys_are_whitelist_and_no_leak(
    client: AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
) -> None:
    """Luật ① của P8: mọi khoá ⊆ `SNAPSHOT_KEYS`; không email / id / model_id / khoá gốc / cost."""
    conv = await _conv(session, user_a)
    question, answer = await conv.turn(None)
    image = f"{user_a}/2026/10/{uuid.uuid4()}.png"
    file_key = f"{user_a}/2026/10/{uuid.uuid4()}.xlsx"
    await AttachmentRepository(session).create(
        user_id=user_a, message_id=question.id, kind="image", mime_type="image/png",
        original_name="anh.png", size_bytes=10, storage_key=image, width=4, height=3,
    )  # fmt: skip
    await ArtifactRepository(session).create_for_message(
        message_id=answer.id,
        user_id=user_a,
        blocks=[
            ArtifactBlock(kind="html", language="html", title="Trang", content="<p>x</p>"),
            ArtifactBlock(kind="file", language=None, title="so.xlsx", content=None,
                          storage_key=file_key),
        ],
    )  # fmt: skip
    email = (await session.execute(select(User.email).where(User.id == user_a))).scalar_one()
    await session.commit()

    assert (await _share(client, conv)).status_code == 201
    [row] = await _rows(session_factory)

    assert _keys(row.snapshot_json) <= share_api.SNAPSHOT_KEYS
    text = json.dumps(row.snapshot_json, ensure_ascii=False)
    for secret in (email, str(user_a), str(conv.id), str(answer.id), MODEL_ID, image, file_key,
                   "cost", "reasoning", "feedback"):  # fmt: skip
        assert secret not in text, secret
    display_name = get_catalog().models[0].display_name
    assert row.snapshot_json["messages"][1]["model_display_name"] == display_name


async def test_image_copied_under_share_prefix_and_get_signs_copy(
    client: AsyncClient, session: AsyncSession, user_a: uuid.UUID, fake_storage: FakeStorage
) -> None:
    conv = await _conv(session, user_a)
    question, _ = await conv.turn(None)
    original = f"{user_a}/2026/10/{uuid.uuid4()}.png"
    await AttachmentRepository(session).create(
        user_id=user_a, message_id=question.id, kind="image", mime_type="image/png",
        original_name="anh.png", size_bytes=10, storage_key=original, width=4, height=3,
    )  # fmt: skip
    await session.commit()

    token = (await _share(client, conv)).json()["token"]
    [(source, target)] = fake_storage.copies
    body = (await client.get(f"{API}/s/{token}")).json()

    assert source == original
    assert target.startswith(f"share/{token}/") and target.endswith(".png")
    [image] = body["messages"][0]["attachments"]
    assert {k: image[k] for k in ("kind", "name", "key", "width", "height")} == {
        "kind": "image", "name": "anh.png", "key": target, "width": 4, "height": 3,
    }  # fmt: skip
    path = urlsplit(image["url"]).path
    assert path == f"/{settings.MINIO_BUCKET}/{target}"
    assert original not in image["url"]


async def test_file_artifact_copied_like_image(
    client: AsyncClient, session: AsyncSession, user_a: uuid.UUID, fake_storage: FakeStorage
) -> None:
    """B-372: `kind=file` có `content=NULL` — chép theo `storage_key`, ký kèm `download_name`."""
    conv = await _conv(session, user_a)
    _, answer = await conv.turn(None)
    original = f"{user_a}/2026/10/{uuid.uuid4()}.xlsx"
    await ArtifactRepository(session).create_for_message(
        message_id=answer.id,
        user_id=user_a,
        blocks=[ArtifactBlock(kind="file", language=None, title="báo cáo.xlsx", content=None,
                              storage_key=original)],
    )  # fmt: skip
    await session.commit()

    token = (await _share(client, conv)).json()["token"]
    [(source, target)] = fake_storage.copies
    [art] = (await client.get(f"{API}/s/{token}")).json()["messages"][1]["artifacts"]

    assert (source, target.startswith(f"share/{token}/")) == (original, True)
    assert {k: art[k] for k in ("kind", "title", "key")} == {
        "kind": "file", "title": "báo cáo.xlsx", "key": target,
    }  # fmt: skip
    assert urlsplit(art["url"]).path == f"/{settings.MINIO_BUCKET}/{target}"
    assert "response-content-disposition=attachment" in art["url"]


async def test_document_is_name_and_mime_only(
    client: AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_storage: FakeStorage,
) -> None:
    """Q-P8-4: tài liệu của user chỉ tên — không khoá, không chữ trích, không chép."""
    conv = await _conv(session, user_a)
    question, _ = await conv.turn(None)
    await AttachmentRepository(session).create(
        user_id=user_a, message_id=question.id, kind="file", mime_type="application/pdf",
        original_name="hop dong.pdf", size_bytes=10, storage_key=f"{user_a}/x.pdf",
        extracted_text="BI MAT trich tu PDF", extract_status="done",
    )  # fmt: skip
    await session.commit()

    assert (await _share(client, conv)).status_code == 201
    [row] = await _rows(session_factory)

    assert row.snapshot_json["messages"][0]["attachments"] == [
        {"kind": "document", "name": "hop dong.pdf", "mime_type": "application/pdf"}
    ]
    assert "BI MAT" not in json.dumps(row.snapshot_json)
    assert fake_storage.copies == []


async def test_latest_artifact_per_lineage_only(
    client: AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
) -> None:
    """Một dòng phiên bản ⇒ một thẻ: bản mới nhất (kể cả bản người dùng sửa)."""
    conv = await _conv(session, user_a)
    _, a1 = await conv.turn(None)
    [v1] = await ArtifactRepository(session).create_for_message(
        message_id=a1.id,
        user_id=user_a,
        blocks=[ArtifactBlock(kind="html", language="html", title="Trang", content="v1")],
    )
    await ArtifactRepository(session).create_user_version(
        user_id=user_a, artifact_id=v1.id, content="ban sua"
    )
    await session.commit()

    assert (await _share(client, conv)).status_code == 201
    [row] = await _rows(session_factory)

    assert row.snapshot_json["messages"][1]["artifacts"] == [
        {"kind": "html", "language": "html", "title": "Trang", "content": "ban sua"}
    ]


async def test_streaming_on_path_is_409(
    client: AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
) -> None:
    conv = await _conv(session, user_a)
    question = await conv.add(None, MessageRole.USER, "hoi")
    await conv.add(question.id, MessageRole.ASSISTANT, "", MessageStatus.STREAMING)
    await session.commit()

    resp = await _share(client, conv)

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "GENERATION_IN_PROGRESS"
    assert await _rows(session_factory) == []


async def test_empty_conversation_is_422_and_failed_empty_dropped(
    client: AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
) -> None:
    empty = await _conv(session, user_a)
    conv = await _conv(session, user_a)
    question = await conv.add(None, MessageRole.USER, "hoi")
    await conv.add(question.id, MessageRole.ASSISTANT, "", MessageStatus.FAILED)
    await session.commit()

    resp = await _share(client, empty)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "CONVERSATION_EMPTY"

    assert (await _share(client, conv)).status_code == 201
    [row] = await _rows(session_factory)
    assert [m["role"] for m in row.snapshot_json["messages"]] == ["user"]


async def test_copy_failure_is_503_no_row_and_partial_removed(
    client: AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_storage: FakeStorage,
) -> None:
    conv = await _conv(session, user_a)
    question, _ = await conv.turn(None)
    for name in ("a.png", "b.png"):
        await AttachmentRepository(session).create(
            user_id=user_a, message_id=question.id, kind="image", mime_type="image/png",
            original_name=name, size_bytes=1, storage_key=f"{user_a}/{name}", width=1, height=1,
        )  # fmt: skip
    await session.commit()
    fake_storage.fail_on = 1

    resp = await _share(client, conv)

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "SHARE_STORAGE_UNAVAILABLE"
    assert await _rows(session_factory) == []
    assert fake_storage.removed == [fake_storage.copies[0][1]]


# ═══════════════════════════ GET /s/{token} ═══════════════════════════


async def test_public_get_without_cookie_counts_view_and_noindex(
    client: AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
) -> None:
    conv = await _conv(session, user_a)
    await conv.turn(None)
    await session.commit()
    token = (await _share(client, conv)).json()["token"]

    resp = await client.get(f"{API}/s/{token}")  # không cookie

    assert resp.status_code == 200
    assert resp.headers["x-robots-tag"] == "noindex, nofollow"
    assert resp.headers["cache-control"] == "no-store"
    assert resp.json()["title"] == "Kế hoạch"
    [row] = await _rows(session_factory)
    assert row.view_count == 1


async def test_unknown_or_revoked_token_is_same_404(
    client: AsyncClient, session: AsyncSession, user_a: uuid.UUID
) -> None:
    conv = await _conv(session, user_a)
    await conv.turn(None)
    await session.commit()
    token = (await _share(client, conv)).json()["token"]
    await session.execute(
        update(SharedConversation)
        .where(SharedConversation.token == token)
        .values(revoked_at=func.now())
    )
    await session.commit()

    unknown = await client.get(f"{API}/s/khong-co-token-nay")
    revoked = await client.get(f"{API}/s/{token}")

    assert (unknown.status_code, revoked.status_code) == (404, 404)
    assert unknown.json() == revoked.json()
    assert unknown.json()["error"]["code"] == "SHARE_NOT_FOUND"


async def test_chat_after_share_does_not_change_snapshot(
    client: AsyncClient, session: AsyncSession, user_a: uuid.UUID
) -> None:
    """ADR-14: GET chỉ đọc `snapshot_json`, không dựng lại từ hội thoại gốc."""
    conv = await _conv(session, user_a)
    _, answer = await conv.turn(None, "truoc")
    await session.commit()
    token = (await _share(client, conv)).json()["token"]
    before = (await client.get(f"{API}/s/{token}")).json()

    await conv.turn(answer.id, "sau")
    await ConversationRepository(session).update_conversation(
        conv.id, user_id=user_a, changes={"title": "Doi ten"}
    )
    await session.commit()
    after = (await client.get(f"{API}/s/{token}")).json()

    assert after == before
    assert [m["content"] for m in after["messages"]] == ["truoc", "tra loi truoc"]


# ═══════════════════════════ B-349 ═══════════════════════════


def test_minio_client_has_timeout_and_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MINIO_TIMEOUT_S", 2.5)
    http = storage._minio(settings.MINIO_ENDPOINT)._http

    timeout = http.connection_pool_kw["timeout"]
    assert (timeout.connect_timeout, timeout.read_timeout) == (2.5, 2.5)
    assert http.connection_pool_kw["retries"].total == MINIO_RETRIES
