"""T-4.4a — `attachment_ids` của `POST …/messages`, tệp trên đường đi, sửa câu hỏi có tệp.

Hàng `attachments` dựng thẳng bằng repository — object MinIO không cần có thật
(`presign_get` là phép tính thuần, T-4.2). arq giả như `test_messages.py`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from app.api.v1 import conversations as conversations_api
from app.config.settings import settings
from app.core.access_token import encode_access_token
from app.core.deps import SESSION_COOKIE_NAME
from app.db.models import (
    Attachment,
    AttachmentKind,
    ExtractStatus,
    Message,
    MessageRole,
    MessageStatus,
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
NOT_USABLE = "ATTACHMENT_NOT_FOUND"
_T0 = datetime(2026, 10, 3, tzinfo=UTC)


class _FakeArq:
    def __init__(self) -> None:
        self.pushed: list[tuple[str, tuple[Any, ...]]] = []

    async def enqueue_job(self, name: str, *args: Any, **_: Any) -> object:
        self.pushed.append((name, args))
        return object()


@pytest.fixture(autouse=True)
def _db_for_tests(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


@pytest_asyncio.fixture(autouse=True)
async def fake_arq(monkeypatch: pytest.MonkeyPatch) -> _FakeArq:
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


async def _conversation(factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID) -> uuid.UUID:
    async with factory() as session:
        conv = await ConversationRepository(session).create_conversation(user_id=user_id)
        await session.commit()
        return conv.id


async def _upload_row(
    factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID, n: int = 0
) -> uuid.UUID:
    """Một hàng như `POST /attachments` để lại.

    `created_at` đặt tay: mỗi upload thật là một transaction riêng nên `now()`
    khác nhau, còn trong pytest mọi thứ nằm trong MỘT transaction ngoài ⇒ `now()`
    trùng (NQ-18) và thứ tự chỉ còn là thứ tự `id` ngẫu nhiên.
    """
    async with factory() as session:
        row = await AttachmentRepository(session).create(
            user_id=user_id,
            kind=AttachmentKind.IMAGE,
            mime_type="image/png",
            original_name=f"anh {n}.png",
            size_bytes=100 + n,
            storage_key=f"{user_id}/2026/10/{uuid.uuid4()}.png",
            width=40,
            height=30,
            created_at=_T0 + timedelta(seconds=n),
        )
        await session.commit()
        return row.id


async def _send(
    client: AsyncClient, user_id: uuid.UUID, conv: uuid.UUID, ids: list[uuid.UUID], **extra: Any
) -> Any:
    headers = _auth(user_id) | extra.pop("headers", {})
    body = {"content": "DoD T-4.4a", "attachment_ids": [str(i) for i in ids], **extra}
    return await client.post(f"{API}/conversations/{conv}/messages", headers=headers, json=body)


async def _rows_of(
    factory: async_sessionmaker[AsyncSession], message_id: uuid.UUID
) -> list[tuple[str, datetime]]:
    async with factory() as session:
        stmt = (
            select(Attachment.storage_key, Attachment.created_at)
            .where(Attachment.message_id == message_id)
            .order_by(Attachment.created_at)
        )
        return [(k, c) for k, c in (await session.execute(stmt)).all()]


async def _message_id_of(
    factory: async_sessionmaker[AsyncSession], attachment_id: uuid.UUID
) -> uuid.UUID | None:
    async with factory() as session:
        row = await session.get(Attachment, attachment_id)
        assert row is not None
        return row.message_id


async def _count_messages(factory: async_sessionmaker[AsyncSession], conv: uuid.UUID) -> int:
    async with factory() as session:
        stmt = select(func.count()).select_from(Message).where(Message.conversation_id == conv)
        return int((await session.execute(stmt)).scalar_one())


# ═══════════════════════ gắn tệp vào POST …/messages ═══════════════════════


async def test_two_images_attach_to_new_user_message(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    conv = await _conversation(session_factory, user_a)
    ids = [await _upload_row(session_factory, user_a, n) for n in range(2)]

    resp = await _send(client, user_a, conv, ids)

    assert resp.status_code == 202, resp.text
    uid = uuid.UUID(resp.json()["user_message_id"])
    assert [await _message_id_of(session_factory, i) for i in ids] == [uid, uid]


async def test_empty_content_with_one_image_is_202(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    conv = await _conversation(session_factory, user_a)
    att = await _upload_row(session_factory, user_a)

    resp = await _send(client, user_a, conv, [att], content="")

    assert resp.status_code == 202, resp.text
    assert await _message_id_of(session_factory, att) == uuid.UUID(resp.json()["user_message_id"])


async def test_empty_content_without_files_is_422(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    conv = await _conversation(session_factory, user_a)

    resp = await _send(client, user_a, conv, [], content="")

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
    assert await _count_messages(session_factory, conv) == 0


async def test_file_of_other_user_is_unusable_and_writes_nothing(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    fake_arq: _FakeArq,
) -> None:
    conv = await _conversation(session_factory, user_a)
    mine = await _upload_row(session_factory, user_a)
    of_b = await _upload_row(session_factory, user_b)

    resp = await _send(client, user_a, conv, [mine, of_b])
    fabricated = await _send(client, user_a, conv, [mine, uuid.uuid4()])

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == NOT_USABLE
    # §20: "của người khác" và "không có" — cùng một câu, từng byte.
    assert (resp.status_code, resp.json()) == (fabricated.status_code, fabricated.json())
    assert await _count_messages(session_factory, conv) == 0
    assert await _message_id_of(session_factory, of_b) is None
    # Tất cả hoặc không: tệp hợp lệ đi cùng cũng không bị gắn.
    assert await _message_id_of(session_factory, mine) is None
    assert fake_arq.pushed == []


async def test_file_already_attached_is_unusable(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    conv = await _conversation(session_factory, user_a)
    att = await _upload_row(session_factory, user_a)
    first = await _send(client, user_a, conv, [att])
    assert first.status_code == 202
    before = await _count_messages(session_factory, conv)

    again = await _send(client, user_a, conv, [att])

    assert again.status_code == 404
    assert again.json()["error"]["code"] == NOT_USABLE
    assert await _count_messages(session_factory, conv) == before
    assert await _message_id_of(session_factory, att) == uuid.UUID(first.json()["user_message_id"])


async def test_over_tier_max_attachments_attaches_nothing(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    """Trần đọc lúc gọi từ tier (Cạm bẫy ⑤) — đè `max_attachments=2`, gửi 3."""
    async with session_factory() as session:
        await session.execute(
            update(User).where(User.id == user_a).values(limit_override_json={"max_attachments": 2})
        )
        await session.commit()
    conv = await _conversation(session_factory, user_a)
    ids = [await _upload_row(session_factory, user_a, n) for n in range(3)]

    resp = await _send(client, user_a, conv, ids)

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "ATTACHMENT_LIMIT_EXCEEDED"
    assert resp.json()["error"]["details"] == {"max_attachments": 2}
    assert [await _message_id_of(session_factory, i) for i in ids] == [None, None, None]
    assert await _count_messages(session_factory, conv) == 0
    # Đúng trần thì qua.
    assert (await _send(client, user_a, conv, ids[:2])).status_code == 202


async def test_same_idempotency_key_replays_and_keeps_two_rows(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    conv = await _conversation(session_factory, user_a)
    ids = [await _upload_row(session_factory, user_a, n) for n in range(2)]
    key = {"Idempotency-Key": "dod-t-4-4a-mot-lan-soan"}

    first = await _send(client, user_a, conv, ids, headers=key)
    second = await _send(client, user_a, conv, ids, headers=key)

    assert first.status_code == second.status_code == 202
    assert second.headers["Idempotent-Replay"] == "true"
    assert first.json() == second.json()
    uid = uuid.UUID(first.json()["user_message_id"])
    assert len(await _rows_of(session_factory, uid)) == 2
    assert await _count_messages(session_factory, conv) == 2


# ═════════════════ đường đi, siblings, sửa câu hỏi có tệp ═════════════════


async def test_path_returns_attachments_with_url(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    conv = await _conversation(session_factory, user_a)
    ids = [await _upload_row(session_factory, user_a, n) for n in range(2)]
    await _send(client, user_a, conv, ids)

    resp = await client.get(f"{API}/conversations/{conv}", headers=_auth(user_a))

    assert resp.status_code == 200
    user_msg, assistant_msg = resp.json()["path"]
    assert [a["id"] for a in user_msg["attachments"]] == [str(i) for i in ids]
    first = user_msg["attachments"][0]
    assert set(first) == {
        "id",
        "kind",
        "name",
        "bytes",
        "mime_type",
        "width",
        "height",
        "extract_status",
        "url",
    }
    assert first["kind"] == "image" and first["name"] == "anh 0.png"
    assert first["url"].startswith("https://localhost/")
    assert assistant_msg["attachments"] == []


async def test_patch_copies_three_images_in_same_order(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    """NQ-138 ③ + B-57: hàng mới, cùng `storage_key`, giữ `created_at` gốc."""
    conv = await _conversation(session_factory, user_a)
    ids = [await _upload_row(session_factory, user_a, n) for n in range(3)]
    sent = await _send(client, user_a, conv, ids)
    original = uuid.UUID(sent.json()["user_message_id"])
    before = await _rows_of(session_factory, original)

    resp = await client.patch(
        f"{API}/messages/{original}", headers=_auth(user_a), json={"content": "sua lai"}
    )

    assert resp.status_code == 202, resp.text
    edited = uuid.UUID(resp.json()["user_message_id"])
    assert len(before) == 3
    assert await _rows_of(session_factory, edited) == before
    assert await _rows_of(session_factory, original) == before

    siblings = await client.get(f"{API}/messages/{edited}/siblings", headers=_auth(user_a))
    assert siblings.status_code == 200
    names = [[a["name"] for a in item["attachments"]] for item in siblings.json()["items"]]
    assert names == [["anh 0.png", "anh 1.png", "anh 2.png"]] * 2


# ═══════════════ một truy vấn cho cả đường đi (Cạm bẫy ④) ═════════════════


async def _path_of(
    factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID, turns: int, *, files: bool
) -> uuid.UUID:
    async with factory() as session:
        conv = await ConversationRepository(session).create_conversation(user_id=user_id)
        messages = MessageRepository(session)
        parent: uuid.UUID | None = None
        for n in range(turns * 2):
            msg = await messages.create_message(
                conversation_id=conv.id,
                user_id=user_id,
                role=MessageRole.USER if n % 2 == 0 else MessageRole.ASSISTANT,
                parent_id=parent,
                content=f"m{n}",
                status=MessageStatus.COMPLETED,
            )
            parent = msg.id
            if files:
                await AttachmentRepository(session).create(
                    user_id=user_id,
                    message_id=msg.id,
                    kind=AttachmentKind.IMAGE,
                    mime_type="image/png",
                    original_name=f"{n}.png",
                    size_bytes=1,
                    storage_key=f"{user_id}/{n}.png",
                )
        await ConversationRepository(session).set_active_leaf(
            conv.id, user_id=user_id, message_id=parent
        )
        await session.commit()
        return conv.id


async def _count_sql(client: AsyncClient, connection: AsyncConnection, path: str, auth: Any) -> int:
    seen: list[str] = []

    def _on(_conn: Any, _cur: Any, statement: str, *_: Any) -> None:
        seen.append(statement)

    event.listen(connection.sync_engine, "before_cursor_execute", _on)
    try:
        resp = await client.get(path, headers=auth)
    finally:
        event.remove(connection.sync_engine, "before_cursor_execute", _on)
    assert resp.status_code == 200
    assert len(resp.json()["path"]) == 20
    return len(seen)


async def test_path_of_20_with_files_costs_one_query_more(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
    user_a: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """DoD dòng 2: 20 message × 1 tệp tốn đúng MỘT câu hơn đường đi không đọc tệp."""
    with_files = await _path_of(session_factory, user_a, 10, files=True)
    no_files = await _path_of(session_factory, user_a, 10, files=False)
    auth = _auth(user_a)

    n_files = await _count_sql(client, connection, f"{API}/conversations/{with_files}", auth)
    n_plain = await _count_sql(client, connection, f"{API}/conversations/{no_files}", auth)

    async def _skip(_session: Any, items: Any, **_: Any) -> Any:
        return items

    monkeypatch.setattr(conversations_api, "with_attachments", _skip)
    n_without_loader = await _count_sql(
        client, connection, f"{API}/conversations/{with_files}", auth
    )
    with capsys.disabled():
        print(
            f"\n[DoD-2] SQL: 20 msg x 1 tep = {n_files}; 20 msg khong tep = {n_plain}; "
            f"bo lop doc tep = {n_without_loader}"
        )
    assert n_files == n_without_loader + 1
    # Câu đọc tệp chạy cả khi không có tệp — biết "không có" cũng cần chính câu ấy.
    assert n_files == n_plain


# ═══════════════════════ chữ tệp ở biên vào (T-4.6a) ═══════════════════════


async def _file_row(
    factory: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
    *,
    status: ExtractStatus,
    text: str | None = None,
) -> uuid.UUID:
    async with factory() as session:
        row = await AttachmentRepository(session).create(
            user_id=user_id,
            kind=AttachmentKind.FILE,
            mime_type="application/pdf",
            original_name="tai-lieu.pdf",
            size_bytes=1000,
            storage_key=f"{user_id}/2026/10/{uuid.uuid4()}.pdf",
            extracted_text=text,
            extract_status=status,
        )
        await session.commit()
        return row.id


async def test_send_with_pending_file_is_409_and_writes_nothing(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_arq: _FakeArq,
) -> None:
    """**DoD**: gửi khi tệp còn `pending` ⇒ `409`, không message, không job, tệp chưa gắn."""
    conv = await _conversation(session_factory, user_a)
    att = await _file_row(session_factory, user_a, status=ExtractStatus.PENDING)

    resp = await _send(client, user_a, conv, [att])

    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "ATTACHMENT_NOT_READY"
    assert await _count_messages(session_factory, conv) == 0
    assert await _message_id_of(session_factory, att) is None
    assert fake_arq.pushed == []


async def test_file_text_over_cap_is_422_and_writes_nothing(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**DoD** Cạm bẫy ②: TỔNG chữ hai tệp vượt trần ⇒ `422`, `count(*) messages` không đổi.

    Mỗi tệp một mình vừa trần — chỉ tổng mới vượt. Trần đọc lúc gọi.
    """
    monkeypatch.setattr(settings, "ATTACHMENT_TEXT_MAX_CHARS", 100)
    conv = await _conversation(session_factory, user_a)
    ids = [
        await _file_row(session_factory, user_a, status=ExtractStatus.DONE, text="a" * 60)
        for _ in range(2)
    ]
    before = await _count_messages(session_factory, conv)

    resp = await _send(client, user_a, conv, ids)

    assert resp.status_code == 422, resp.text
    assert resp.json()["error"] == {
        "code": "ATTACHMENT_TEXT_TOO_LONG",
        "message": "chu trong tep vuot tran cho phep",
        "details": {"max_chars": 100},
    }
    assert await _count_messages(session_factory, conv) == before
    assert [await _message_id_of(session_factory, i) for i in ids] == [None, None]


async def test_file_text_at_cap_is_202(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Đúng bằng trần vẫn qua — ca đối chứng của ca trên."""
    monkeypatch.setattr(settings, "ATTACHMENT_TEXT_MAX_CHARS", 120)
    conv = await _conversation(session_factory, user_a)
    ids = [
        await _file_row(session_factory, user_a, status=ExtractStatus.DONE, text="a" * 60)
        for _ in range(2)
    ]

    resp = await _send(client, user_a, conv, ids)

    assert resp.status_code == 202, resp.text


# ─────────── trần chung: chữ tệp + bản sửa artifact (T-5.2b, B-208 / B-353) ───────────


async def _edited_turn(
    factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID, conv: uuid.UUID, edit_chars: int
) -> uuid.UUID:
    """Lượt 1 có artifact v1, rồi người dùng sửa nó (`edit_chars` ký tự, 0 = không sửa).
    Trả câu trả lời lượt 1 — đã là `active_leaf_id`, nên câu hỏi gửi tiếp nhận bản sửa."""
    async with factory() as session:
        messages = MessageRepository(session)
        q1 = await messages.create_message(
            conversation_id=conv,
            user_id=user_id,
            role=MessageRole.USER,
            parent_id=None,
            content="q1",
        )
        a1 = await messages.create_message(
            conversation_id=conv,
            user_id=user_id,
            role=MessageRole.ASSISTANT,
            parent_id=q1.id,
            content="a1",
            status=MessageStatus.COMPLETED,
        )
        artifacts = ArtifactRepository(session)
        [v1] = await artifacts.create_for_message(
            message_id=a1.id,
            user_id=user_id,
            blocks=[ArtifactBlock(kind="html", language="html", title="Trang A", content="<p/>")],
        )
        if edit_chars:
            await artifacts.create_user_version(
                user_id=user_id, artifact_id=v1.id, content="e" * edit_chars
            )
        await ConversationRepository(session).set_active_leaf(
            conv, user_id=user_id, message_id=a1.id
        )
        await session.commit()
        return a1.id


async def test_file_text_plus_artifact_edit_share_one_cap(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**DoD** T-5.2b: chữ tệp 20 000 + bản sửa 5 000, trần 24 000 ⇒ `422
    ATTACHMENT_TEXT_TOO_LONG`, `count(*) messages` không đổi. Mỗi phần một mình vừa trần."""
    monkeypatch.setattr(settings, "ATTACHMENT_TEXT_MAX_CHARS", 24_000)
    conv = await _conversation(session_factory, user_a)
    await _edited_turn(session_factory, user_a, conv, 5_000)
    att = await _file_row(session_factory, user_a, status=ExtractStatus.DONE, text="a" * 20_000)
    before = await _count_messages(session_factory, conv)

    resp = await _send(client, user_a, conv, [att])

    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "ATTACHMENT_TEXT_TOO_LONG"
    assert await _count_messages(session_factory, conv) == before
    assert await _message_id_of(session_factory, att) is None


async def test_edited_question_gets_unsent_edit_inside_same_cap(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`PATCH /messages/{id}` tạo câu hỏi mới — bản sửa chưa ai gửi vào nó, cộng
    chữ tệp chép từ bản gốc ⇒ cùng trần, cùng `422`."""
    monkeypatch.setattr(settings, "ATTACHMENT_TEXT_MAX_CHARS", 24_000)
    conv = await _conversation(session_factory, user_a)
    a1 = await _edited_turn(session_factory, user_a, conv, 0)
    att = await _file_row(session_factory, user_a, status=ExtractStatus.DONE, text="a" * 20_000)
    sent = await _send(client, user_a, conv, [att], parent_id=str(a1))
    assert sent.status_code == 202, sent.text
    async with session_factory() as session:
        [v1] = await ArtifactRepository(session).list_for_messages(user_id=user_a, message_ids=[a1])
        await ArtifactRepository(session).create_user_version(
            user_id=user_a, artifact_id=v1.id, content="e" * 5_000
        )
        await session.commit()
    before = await _count_messages(session_factory, conv)

    resp = await client.patch(
        f"{API}/messages/{sent.json()['user_message_id']}",
        headers=_auth(user_a),
        json={"content": "hoi lai"},
    )

    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "ATTACHMENT_TEXT_TOO_LONG"
    assert await _count_messages(session_factory, conv) == before
