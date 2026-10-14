"""T-8.3 — `POST /s/{token}/fork` (§16.1 "Fork", UC-11 dòng 3, A8).

Đường DUY NHẤT dữ liệu của A thành của B ⇒ phần lớn ca ở đây canh "chép, không
trỏ": id mới, khoá object mới, và dữ liệu của chủ nguyên vẹn sau cả chuỗi thao
tác của người fork (lối T-2.18). MinIO giả ở `app.core.storage` (lối T-8.1).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
import urllib3
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Engine, event, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.catalog import get_catalog
from app.core import storage
from app.core.access_token import encode_access_token
from app.core.deps import SESSION_COOKIE_NAME
from app.core.idempotency import HEADER_IDEMPOTENCY, HEADER_REPLAY
from app.db.models import (
    Artifact,
    Attachment,
    Conversation,
    Message,
    MessageFeedback,
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
from app.llm import context
from app.llm.artifact_blocks import ArtifactBlock
from app.main import app

API = "/api/v1"
MODEL = get_catalog().models[0]
IMAGE_BYTES = 1234


@pytest.fixture(autouse=True)
def _db_for_tests(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


class FakeStorage:
    def __init__(self) -> None:
        self.objects: set[str] = set()
        self.copies: list[tuple[str, str]] = []
        self.removed: list[str] = []
        self.fail_on: int | None = None

    async def copy(self, source: str, target: str) -> None:
        if self.fail_on is not None and len(self.copies) == self.fail_on:
            raise urllib3.exceptions.MaxRetryError(None, target)  # type: ignore[arg-type]
        self.copies.append((source, target))
        self.objects.add(target)

    async def size(self, key: str) -> int:
        assert key in self.objects, key
        return IMAGE_BYTES

    async def remove(self, key: str) -> None:
        self.removed.append(key)
        self.objects.discard(key)


@pytest.fixture(autouse=True)
def fake_storage(monkeypatch: pytest.MonkeyPatch) -> FakeStorage:
    fake = FakeStorage()
    monkeypatch.setattr(storage, "copy", fake.copy)
    monkeypatch.setattr(storage, "size", fake.size)
    monkeypatch.setattr(storage, "remove", fake.remove)
    return fake


@pytest_asyncio.fixture
async def client(event_hooks: dict[str, Any]) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://localhost", event_hooks=event_hooks
    ) as http:
        yield http


def _auth(user_id: uuid.UUID, status: UserStatus = UserStatus.ACTIVE) -> dict[str, str]:
    token = encode_access_token(
        user_id=user_id, role=UserRole.USER, tier="free", status=status, ttl_minutes=15
    )
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


async def _owner_conversation(session: AsyncSession, owner: uuid.UUID) -> dict[str, Any]:
    """Cây của A: nhánh chính 2 lượt + một nhánh anh em; ảnh, tài liệu, artifact chữ + tệp."""
    conversations = ConversationRepository(session)
    messages = MessageRepository(session)
    conv = await conversations.create_conversation(user_id=owner, title="Kế hoạch")

    async def add(parent: uuid.UUID | None, role: MessageRole, content: str) -> Message:
        row = await messages.create_message(
            conversation_id=conv.id, user_id=owner, role=role, parent_id=parent, content=content,
            status=MessageStatus.COMPLETED,
            model_id=MODEL.id if role == MessageRole.ASSISTANT else None,
        )  # fmt: skip
        await conversations.set_active_leaf(conv.id, user_id=owner, message_id=row.id)
        return row

    q1 = await add(None, MessageRole.USER, "mot")
    a1 = await add(q1.id, MessageRole.ASSISTANT, "tra loi mot")
    await add(a1.id, MessageRole.USER, "nhanh bo")
    q2 = await add(a1.id, MessageRole.USER, "hai")
    a2 = await add(q2.id, MessageRole.ASSISTANT, "tra loi hai")
    await session.execute(
        update(Message).where(Message.id == a1.id).values(feedback=MessageFeedback.LIKE)
    )
    image = f"{owner}/2026/10/{uuid.uuid4()}.png"
    file_key = f"{owner}/2026/10/{uuid.uuid4()}.xlsx"
    await AttachmentRepository(session).create(
        user_id=owner, message_id=q1.id, kind="image", mime_type="image/png",
        original_name="anh.png", size_bytes=10, storage_key=image, width=4, height=3,
    )  # fmt: skip
    await AttachmentRepository(session).create(
        user_id=owner, message_id=q2.id, kind="file", mime_type="application/pdf",
        original_name="hop dong.pdf", size_bytes=10, storage_key=f"{owner}/x.pdf",
    )  # fmt: skip
    await ArtifactRepository(session).create_for_message(
        message_id=a2.id,
        user_id=owner,
        blocks=[
            ArtifactBlock(kind="html", language="html", title="Trang", content="<p>x</p>"),
            ArtifactBlock(kind="file", language=None, title="so.xlsx", content=None,
                          storage_key=file_key),
        ],
    )  # fmt: skip
    await session.commit()
    return {"id": conv.id, "image": image, "file": file_key}


async def _share(client: AsyncClient, owner: uuid.UUID, conversation_id: uuid.UUID) -> str:
    resp = await client.post(f"{API}/conversations/{conversation_id}/share", headers=_auth(owner))
    assert resp.status_code == 201, resp.text
    token: str = resp.json()["token"]
    return token


async def _fork(client: AsyncClient, user_id: uuid.UUID, token: str, **headers: str) -> Any:
    return await client.post(f"{API}/s/{token}/fork", headers={**_auth(user_id), **headers})


async def _owner_fingerprint(
    session_factory: async_sessionmaker[AsyncSession], owner: uuid.UUID
) -> tuple[Any, ...]:
    """Số hàng messages / artifacts / attachments của chủ + md5 mọi snapshot + feedback."""
    async with session_factory() as fresh:
        own_messages = (
            select(Message.id)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Conversation.user_id == owner)
        )
        return (
            await fresh.scalar(select(func.count()).select_from(own_messages.subquery())),
            await fresh.scalar(
                select(func.count()).select_from(Artifact).where(Artifact.message_id.in_(own_messages))
            ),
            await fresh.scalar(
                select(func.count()).select_from(Attachment).where(Attachment.user_id == owner)
            ),
            (
                await fresh.execute(
                    text("SELECT md5(snapshot_json::text) FROM shared_conversations ORDER BY token")
                )
            ).scalars().all(),
            sorted(
                (str(m.id), m.content, m.feedback)
                for m in (await fresh.execute(select(Message).where(Message.id.in_(own_messages))))
                .scalars()
                .all()
            ),
        )  # fmt: skip


async def _path(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID, cid: uuid.UUID
) -> list[Message]:
    async with session_factory() as fresh:
        conv = await ConversationRepository(fresh).get_conversation(cid, user_id=user_id)
        assert conv is not None and conv.active_leaf_id is not None
        nodes = await MessageRepository(fresh).get_path(conv.active_leaf_id, user_id=user_id)
        return [node.message for node in nodes]


# ═══════════════════════════ hội thoại mới của người gọi ═══════════════════════════


async def test_fork_is_new_conversation_of_caller_in_snapshot_order(
    client: AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
) -> None:
    owner = await _owner_conversation(session, user_a)
    await session.execute(update(User).where(User.id == user_b).values(default_model=MODEL.id))
    await session.commit()
    token = await _share(client, user_a, owner["id"])

    resp = await _fork(client, user_b, token)

    assert resp.status_code == 201, resp.text
    assert set(resp.json()) == {"conversation_id"}
    cid = uuid.UUID(resp.json()["conversation_id"])
    async with session_factory() as fresh:
        conv = await fresh.get(Conversation, cid)
        snapshot = (await fresh.execute(select(SharedConversation.snapshot_json))).scalar_one()
        total = await fresh.scalar(
            select(func.count()).select_from(Message).where(Message.conversation_id == cid)
        )
    assert conv is not None
    assert (conv.user_id, conv.title, conv.default_model) == (user_b, "Kế hoạch", MODEL.id)
    path = await _path(session_factory, user_b, cid)
    assert total == len(path) == len(snapshot["messages"]) == 4
    assert [m.content for m in path] == [m["content"] for m in snapshot["messages"]]
    assert [str(m.role) for m in path] == [m["role"] for m in snapshot["messages"]]
    # NQ-18 ③: mỗi hàng một INSERT ⇒ created_at tăng ngặt theo đường đi.
    stamps = [m.created_at for m in path]
    assert stamps == sorted(stamps) and len(set(stamps)) == len(stamps)
    assert conv.active_leaf_id == path[-1].id


async def test_fork_inserts_one_message_per_statement(
    client: AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
) -> None:
    """NQ-18 ③ / C13: mỗi message một `INSERT` — đếm CÂU LỆNH, không đếm `created_at` trùng.

    Đo 2026-10-14: một câu `INSERT … SELECT` 60 dòng vào `messages` (FK
    `parent_id` + 2 index, ~8 µs/dòng) vẫn ra 60 giá trị; bảng trần ra 12. Trùng
    giờ tuỳ tốc độ máy ⇒ canh chính luật, giữ phép kiểm giờ làm lớp hai.
    """
    conversations = ConversationRepository(session)
    conv = await conversations.create_conversation(user_id=user_a, title="Dai")
    parent: uuid.UUID | None = None
    for n in range(60):
        row = await MessageRepository(session).create_message(
            conversation_id=conv.id, user_id=user_a, parent_id=parent, content=f"m{n}",
            role=MessageRole.USER if n % 2 == 0 else MessageRole.ASSISTANT,
            status=MessageStatus.COMPLETED,
        )  # fmt: skip
        parent = row.id
    await conversations.set_active_leaf(conv.id, user_id=user_a, message_id=parent)
    await session.commit()
    token = await _share(client, user_a, conv.id)
    statements: list[str] = []

    def spy(_conn: Any, _cursor: Any, statement: str, *_rest: Any) -> None:
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", spy)
    try:
        cid = uuid.UUID((await _fork(client, user_b, token)).json()["conversation_id"])
    finally:
        event.remove(Engine, "before_cursor_execute", spy)

    assert sum(s.lstrip().startswith("INSERT INTO messages") for s in statements) == 60
    path = await _path(session_factory, user_b, cid)
    assert [m.content for m in path] == [f"m{n}" for n in range(60)]
    stamps = [m.created_at for m in path]
    assert stamps == sorted(stamps) and len(set(stamps)) == 60


async def test_feedback_and_model_id_are_null(
    client: AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
) -> None:
    """T-3.7a ③: chủ đã Thích `a1` — bản fork không được "Thích thay"."""
    owner = await _owner_conversation(session, user_a)
    token = await _share(client, user_a, owner["id"])

    cid = uuid.UUID((await _fork(client, user_b, token)).json()["conversation_id"])

    path = await _path(session_factory, user_b, cid)
    assert {(m.feedback, m.model_id, m.status) for m in path} == {
        (None, None, MessageStatus.COMPLETED)
    }


async def test_owner_data_untouched_by_fork_edit_and_delete(
    client: AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
) -> None:
    """Lối T-2.18: dữ liệu của chủ nguyên vẹn sau cả chuỗi thao tác của người fork."""
    owner = await _owner_conversation(session, user_a)
    token = await _share(client, user_a, owner["id"])
    before = await _owner_fingerprint(session_factory, user_a)

    cid = uuid.UUID((await _fork(client, user_b, token)).json()["conversation_id"])
    after_fork = await _owner_fingerprint(session_factory, user_a)
    first = (await _path(session_factory, user_b, cid))[0]
    # "Sửa câu hỏi" trên cây = anh em của câu hỏi (§8.2); rồi xoá cả bản fork.
    async with session_factory() as fresh:
        edited = await MessageRepository(fresh).create_message(
            conversation_id=cid, user_id=user_b, role=MessageRole.USER, content="sua"
        )
        await ConversationRepository(fresh).set_active_leaf(
            cid, user_id=user_b, message_id=edited.id
        )
        await MessageRepository(fresh).soft_delete_message(first.id, user_id=user_b)
        await fresh.commit()
    deleted = await client.delete(f"{API}/conversations/{cid}", headers=_auth(user_b))

    assert deleted.status_code == 204
    assert before == after_fork == await _owner_fingerprint(session_factory, user_a)
    assert before[:3] == (5, 2, 2)


async def test_objects_are_copied_to_caller_keys(
    client: AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    fake_storage: FakeStorage,
) -> None:
    """Luật ② P8: ảnh + tệp model sinh CHÉP từ `share/…` sang khoá của B; tài liệu chỉ tên."""
    owner = await _owner_conversation(session, user_a)
    token = await _share(client, user_a, owner["id"])
    shared = [target for _, target in fake_storage.copies]

    cid = uuid.UUID((await _fork(client, user_b, token)).json()["conversation_id"])

    forked = fake_storage.copies[len(shared) :]
    assert sorted(source for source, _ in forked) == sorted(shared)
    async with session_factory() as fresh:
        ids = select(Message.id).where(Message.conversation_id == cid)
        [image] = (
            (await fresh.execute(select(Attachment).where(Attachment.message_id.in_(ids))))
            .scalars()
            .all()
        )
        arts = (
            (await fresh.execute(select(Artifact).where(Artifact.message_id.in_(ids))))
            .scalars()
            .all()
        )
    [file_art] = [a for a in arts if a.kind == "file"]
    [html] = [a for a in arts if a.kind == "html"]
    for key in (image.storage_key, file_art.storage_key):
        assert key is not None and key.startswith(f"{user_b}/")
        assert key not in (owner["image"], owner["file"]) and not key.startswith("share/")
        assert key in fake_storage.objects  # tồn tại
    assert image.storage_key.endswith(".png") and file_art.storage_key.endswith(".xlsx")
    assert (image.user_id, image.kind, image.mime_type, image.size_bytes) == (
        user_b, "image", "image/png", IMAGE_BYTES,
    )  # fmt: skip
    assert (image.original_name, image.width, image.height) == ("anh.png", 4, 3)
    assert (html.content, html.version, html.parent_artifact_id, html.origin) == (
        "<p>x</p>", 1, None, "model",
    )  # fmt: skip
    assert (file_art.title, file_art.content) == ("so.xlsx", None)


async def test_owner_forking_own_link_gets_new_conversation(
    client: AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
) -> None:
    owner = await _owner_conversation(session, user_a)
    token = await _share(client, user_a, owner["id"])

    resp = await _fork(client, user_a, token)

    cid = uuid.UUID(resp.json()["conversation_id"])
    assert resp.status_code == 201 and cid != owner["id"]
    async with session_factory() as fresh:
        mine = await fresh.scalar(
            select(func.count()).select_from(Conversation).where(Conversation.user_id == user_a)
        )
    assert mine == 2


async def test_fork_does_not_count_a_view(
    client: AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
) -> None:
    owner = await _owner_conversation(session, user_a)
    token = await _share(client, user_a, owner["id"])

    assert (await _fork(client, user_b, token)).status_code == 201

    async with session_factory() as fresh:
        assert await fresh.scalar(select(SharedConversation.view_count)) == 0


# ═══════════════════════════ cửa vào ═══════════════════════════


async def test_unknown_or_revoked_token_is_404(
    client: AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
) -> None:
    owner = await _owner_conversation(session, user_a)
    token = await _share(client, user_a, owner["id"])
    await session.execute(update(SharedConversation).values(revoked_at=func.now()))
    await session.commit()

    unknown = await _fork(client, user_b, "khong-co-token-nay")
    revoked = await _fork(client, user_b, token)

    assert (unknown.status_code, revoked.status_code) == (404, 404)
    assert unknown.json()["error"]["code"] == "SHARE_NOT_FOUND"
    async with session_factory() as fresh:
        assert await fresh.scalar(
            select(func.count()).select_from(Conversation).where(Conversation.user_id == user_b)
        ) == 0  # fmt: skip


async def test_no_cookie_is_401(client: AsyncClient) -> None:
    resp = await client.post(f"{API}/s/bat-ky/fork")

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


@pytest.mark.parametrize("status", [UserStatus.PENDING_APPROVAL, UserStatus.PENDING_EMAIL])
async def test_pending_account_is_403(
    client: AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    status: UserStatus,
) -> None:
    owner = await _owner_conversation(session, user_a)
    token = await _share(client, user_a, owner["id"])

    resp = await client.post(f"{API}/s/{token}/fork", headers=_auth(user_b, status))

    assert resp.status_code == 403
    expected = "PENDING_APPROVAL" if status == UserStatus.PENDING_APPROVAL else "EMAIL_NOT_VERIFIED"
    assert resp.json()["error"]["code"] == expected
    async with session_factory() as fresh:
        assert await fresh.scalar(
            select(func.count()).select_from(Conversation).where(Conversation.user_id == user_b)
        ) == 0  # fmt: skip


async def test_missing_idempotency_key_is_400(
    session: AsyncSession, user_a: uuid.UUID, user_b: uuid.UUID, event_hooks: dict[str, Any]
) -> None:
    owner = await _owner_conversation(session, user_a)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://localhost", event_hooks=event_hooks
    ) as hooked:
        token = await _share(hooked, user_a, owner["id"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as bare:
        resp = await bare.post(f"{API}/s/{token}/fork", headers=_auth(user_b))

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


async def test_same_key_twice_is_one_conversation(
    client: AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
) -> None:
    """B-260: StrictMode / bấm hai lần cùng khoá ⇒ MỘT bản fork, lần hai là bản phát lại."""
    owner = await _owner_conversation(session, user_a)
    token = await _share(client, user_a, owner["id"])
    key = {HEADER_IDEMPOTENCY: uuid.uuid4().hex}

    first = await _fork(client, user_b, token, **key)
    second = await _fork(client, user_b, token, **key)

    assert (first.status_code, second.status_code) == (201, 201)
    assert second.json() == first.json()
    assert second.headers.get(HEADER_REPLAY) == "true"
    async with session_factory() as fresh:
        assert await fresh.scalar(
            select(func.count()).select_from(Conversation).where(Conversation.user_id == user_b)
        ) == 1  # fmt: skip


async def test_copy_failure_is_503_and_nothing_left(
    client: AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    fake_storage: FakeStorage,
) -> None:
    owner = await _owner_conversation(session, user_a)
    token = await _share(client, user_a, owner["id"])
    fake_storage.fail_on = len(fake_storage.copies) + 1  # bản chép thứ hai của fork hỏng

    resp = await _fork(client, user_b, token)

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "SHARE_STORAGE_UNAVAILABLE"
    assert fake_storage.removed == [fake_storage.copies[-1][1]]
    async with session_factory() as fresh:
        assert await fresh.scalar(
            select(func.count()).select_from(Conversation).where(Conversation.user_id == user_b)
        ) == 0  # fmt: skip


# ═══════════════════════════ C11 — lượt chat kế trên bản fork ═══════════════════════════


async def test_next_turn_on_fork_sends_fork_path_only(
    client: AsyncClient,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
) -> None:
    """Cây của chủ có nhánh bỏ; bản fork là một chuỗi ⇒ ngữ cảnh = system + đường đi fork."""
    owner = await _owner_conversation(session, user_a)
    token = await _share(client, user_a, owner["id"])
    cid = uuid.UUID((await _fork(client, user_b, token)).json()["conversation_id"])
    path = await _path(session_factory, user_b, cid)

    async with session_factory() as fresh:
        messages = MessageRepository(fresh)
        question = await messages.create_message(
            conversation_id=cid, user_id=user_b, role=MessageRole.USER, parent_id=path[-1].id,
            content="hoi tiep", status=MessageStatus.COMPLETED,
        )  # fmt: skip
        queued = await messages.create_message(
            conversation_id=cid, user_id=user_b, role=MessageRole.ASSISTANT,
            parent_id=question.id, status=MessageStatus.QUEUED, model_id=MODEL.id,
        )  # fmt: skip
        sent = await context.build(fresh, queued.id, MODEL, user_id=user_b)

    assert len(sent) == 1 + len(path) + 1
    assert [m["role"] for m in sent[1:]] == [str(m.role) for m in path] + ["user"]
    assert "nhanh bo" not in str(sent)
