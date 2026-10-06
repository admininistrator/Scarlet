"""T-5.2a — dòng phiên bản do model (Q-P5-2), `GET /artifacts/{id}`, `/versions`,
artifact trên đường đi. IDOR ở `tests/security/test_idor.py` (B-182).

Hàng `artifacts` ghi qua đúng `ArtifactRepository.create_for_message` mà worker
gọi — không qua LLM. Cây dựng bằng `MessageRepository` như `test_tree.py`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from app.api.v1 import conversations as conversations_api
from app.core.access_token import encode_access_token
from app.core.deps import SESSION_COOKIE_NAME
from app.db.models import Artifact, Message, MessageRole, MessageStatus, UserRole, UserStatus
from app.db.repositories import ArtifactRepository, ConversationRepository, MessageRepository
from app.db.repositories import artifacts as artifacts_repo
from app.llm.artifact_blocks import ArtifactBlock
from app.main import app

API = "/api/v1"


@pytest.fixture(autouse=True)
def _db_for_tests(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


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


def _block(title: str, content: str = "<p>a</p>") -> ArtifactBlock:
    return ArtifactBlock(kind="html", language="html", title=title, content=content)


class _Tree:
    """Một hội thoại; `turn()` = câu hỏi + câu trả lời có artifact."""

    def __init__(self, session: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID):
        self.session = session
        self.user_id = user_id
        self.conversation_id = conversation_id

    async def turn(
        self, parent: uuid.UUID | None, *titles: str
    ) -> tuple[Message, Message, list[Artifact]]:
        messages = MessageRepository(self.session)
        question = await messages.create_message(
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            role=MessageRole.USER,
            parent_id=parent,
            content="hoi",
        )
        answer, artifacts = await self.answer(question.id, *titles)
        return question, answer, artifacts

    async def answer(self, question: uuid.UUID, *titles: str) -> tuple[Message, list[Artifact]]:
        answer = await MessageRepository(self.session).create_message(
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            role=MessageRole.ASSISTANT,
            parent_id=question,
            content="tra loi",
            status=MessageStatus.COMPLETED,
        )
        rows = await ArtifactRepository(self.session).create_for_message(
            message_id=answer.id, user_id=self.user_id, blocks=[_block(t) for t in titles]
        )
        return answer, rows


async def _tree(session: AsyncSession, user_id: uuid.UUID) -> _Tree:
    conv = await ConversationRepository(session).create_conversation(user_id=user_id)
    return _Tree(session, user_id, conv.id)


def _v(row: Artifact) -> tuple[int, uuid.UUID | None]:
    return row.version, row.parent_artifact_id


# ═══════════════════════ dòng phiên bản (Q-P5-2) ═══════════════════════


async def test_rewrites_on_path_continue_lineage_parent_is_root(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """Lượt 1 "Trang A" ⇒ v1; lượt 2 "  trang a " ⇒ v2; lượt 3 ⇒ v3 — parent luôn v1."""
    t = await _tree(session, user_a)
    _, a1, [v1] = await t.turn(None, "Trang A")
    _, a2, [v2] = await t.turn(a1.id, "  trang   a ")
    _, _, [v3] = await t.turn(a2.id, "TRANG A")

    assert _v(v1) == (1, None)
    assert _v(v2) == (2, v1.id)
    assert _v(v3) == (3, v1.id), "parent phai tro GOC, khong ve ban truoc"


async def test_edited_question_branch_gets_next_lineage_number(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """Sửa câu hỏi lượt 2 ⇒ nhánh mới "Trang A" ⇒ v4 (theo dòng, không trùng v2/v3)."""
    t = await _tree(session, user_a)
    _, a1, [v1] = await t.turn(None, "Trang A")
    _, a2, _ = await t.turn(a1.id, "Trang A")
    await t.turn(a2.id, "Trang A")
    _, _, [v4] = await t.turn(a1.id, "Trang A")  # anh em của câu hỏi lượt 2

    assert _v(v4) == (4, v1.id)
    versions = await ArtifactRepository(session).list_versions(user_id=user_a, artifact_id=v4.id)
    assert [r.version for r in versions] == [1, 2, 3, 4]


async def test_branches_split_before_turn_1_are_separate_lineages(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    t = await _tree(session, user_a)
    _, _, [left] = await t.turn(None, "Trang A")
    _, _, [right] = await t.turn(None, "Trang A")

    assert _v(left) == (1, None)
    assert _v(right) == (1, None)


async def test_same_title_in_other_conversation_is_separate_lineage(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    _, _, [first] = await (await _tree(session, user_a)).turn(None, "Trang A")
    _, _, [other] = await (await _tree(session, user_a)).turn(None, "Trang A")

    assert _v(first) == (1, None)
    assert _v(other) == (1, None)


async def test_empty_title_is_always_v1(session: AsyncSession, user_a: uuid.UUID) -> None:
    """Tiêu đề rỗng không bao giờ vào dòng, kể cả trùng nội dung."""
    t = await _tree(session, user_a)
    _, a1, [first] = await t.turn(None, "")
    _, _, [second] = await t.turn(a1.id, "")

    assert first.content == second.content
    assert [_v(first), _v(second)] == [(1, None), (1, None)]


async def test_retry_of_turn_1_starts_new_lineage(session: AsyncSession, user_a: uuid.UUID) -> None:
    """Bản cũ là message ANH EM, không nằm trên đường đi ⇒ dòng mới v1."""
    t = await _tree(session, user_a)
    q1, _, [old] = await t.turn(None, "Trang A")
    _, [retried] = await t.answer(q1.id, "Trang A")

    assert _v(old) == (1, None)
    assert _v(retried) == (1, None)


async def test_two_blocks_same_title_in_one_answer_are_v1_v2(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    t = await _tree(session, user_a)
    _, _, [first, second] = await t.turn(None, "Trang A", "trang a")

    assert [_v(first), _v(second)] == [(1, None), (2, first.id)]


async def test_db_rejects_duplicate_lineage_version(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """Chỉ mục UNIQUE `(COALESCE(parent_artifact_id, id), version)` — migration 0012."""
    t = await _tree(session, user_a)
    _, a1, [v1] = await t.turn(None, "Trang A")
    row = {"message_id": a1.id, "kind": "html", "title": "Trang A", "content": "x"}
    await session.execute(insert(Artifact).values(**row, parent_artifact_id=v1.id, version=2))

    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await session.execute(
                insert(Artifact).values(**row, parent_artifact_id=v1.id, version=2)
            )


async def test_unique_violation_recomputes_exactly_once(
    session: AsyncSession, user_a: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Đua ghi: lần đầu tính ra `version` đã có (bên kia vừa commit) ⇒ savepoint
    lùi, tính lại ⇒ v2. Hỏng cả lần hai ⇒ ném (chỉ thử lại MỘT lần)."""
    t = await _tree(session, user_a)
    _, a1, [v1] = await t.turn(None, "Trang A")
    real = artifacts_repo._insert_statement
    calls: list[int] = []

    def stale_first(*args: Any) -> Any:
        calls.append(1)
        stmt = real(*args)
        return stmt.values(version=1) if len(calls) == 1 else stmt

    monkeypatch.setattr(artifacts_repo, "_insert_statement", stale_first)
    [v2] = await ArtifactRepository(session).create_for_message(
        message_id=a1.id, user_id=user_a, blocks=[_block("Trang A")]
    )
    assert (len(calls), _v(v2)) == (2, (2, v1.id))

    monkeypatch.setattr(artifacts_repo, "_insert_statement", lambda *a: real(*a).values(version=1))
    with pytest.raises(IntegrityError):
        await ArtifactRepository(session).create_for_message(
            message_id=a1.id, user_id=user_a, blocks=[_block("Trang A")]
        )


# ═══════════════════════════ hai endpoint đọc ═══════════════════════════


async def test_get_artifact_and_versions_shape(
    client: AsyncClient, session: AsyncSession, user_a: uuid.UUID
) -> None:
    t = await _tree(session, user_a)
    _, a1, [v1] = await t.turn(None, "Trang A")
    _, a2, [v2] = await t.turn(a1.id, "Trang A")
    await session.commit()

    resp = await client.get(f"{API}/artifacts/{v2.id}", headers=_auth(user_a))
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {
        "id",
        "lineage_id",
        "version",
        "kind",
        "language",
        "title",
        "content",
        "message_id",
        "conversation_id",
        "created_at",
    }
    assert (body["lineage_id"], body["version"], body["message_id"]) == (
        str(v1.id),
        2,
        str(a2.id),
    )
    assert (body["conversation_id"], body["content"]) == (str(t.conversation_id), "<p>a</p>")

    resp = await client.get(f"{API}/artifacts/{v1.id}/versions", headers=_auth(user_a))
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert [(i["id"], i["version"]) for i in items] == [(str(v1.id), 1), (str(v2.id), 2)]
    assert all("content" not in i for i in items), "versions KHONG keo content (Cam bay 5)"


async def test_path_and_siblings_carry_artifacts_with_content(
    client: AsyncClient, session: AsyncSession, user_a: uuid.UUID
) -> None:
    t = await _tree(session, user_a)
    _, a1, [v1, untitled] = await t.turn(None, "Trang A", "")
    await ConversationRepository(session).set_active_leaf(
        t.conversation_id, user_id=user_a, message_id=a1.id
    )
    await session.commit()

    expected = [
        {"id": str(r.id), "kind": "html", "language": "html", "title": r.title, "version": 1,
         "content": "<p>a</p>"}
        for r in (v1, untitled)
    ]  # fmt: skip
    path = await client.get(f"{API}/conversations/{t.conversation_id}", headers=_auth(user_a))
    assert [m["artifacts"] for m in path.json()["path"]] == [[], expected]

    siblings = await client.get(f"{API}/messages/{a1.id}/siblings", headers=_auth(user_a))
    assert [m["artifacts"] for m in siblings.json()["items"]] == [expected]


# ═════════════════ một truy vấn cho cả đường đi (Cạm bẫy ④) ═════════════════


async def _path_of(session: AsyncSession, user_id: uuid.UUID, *, artifacts: bool) -> uuid.UUID:
    """20 message; `artifacts` ⇒ mỗi message một artifact."""
    t = await _tree(session, user_id)
    messages = MessageRepository(session)
    parent: uuid.UUID | None = None
    for n in range(20):
        msg = await messages.create_message(
            conversation_id=t.conversation_id,
            user_id=user_id,
            role=MessageRole.USER if n % 2 == 0 else MessageRole.ASSISTANT,
            parent_id=parent,
            content=f"m{n}",
            status=MessageStatus.COMPLETED,
        )
        parent = msg.id
        if artifacts:
            await ArtifactRepository(session).create_for_message(
                message_id=msg.id, user_id=user_id, blocks=[_block(f"Trang {n}")]
            )
    await ConversationRepository(session).set_active_leaf(
        t.conversation_id, user_id=user_id, message_id=parent
    )
    await session.commit()
    return t.conversation_id


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


async def test_path_of_20_with_artifacts_costs_same_queries(
    client: AsyncClient,
    session: AsyncSession,
    connection: AsyncConnection,
    user_a: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """DoD dòng 3: 20 msg × 1 artifact == 20 msg không artifact; tắt lớp đọc ⇒ −1."""
    with_art = await _path_of(session, user_a, artifacts=True)
    without_art = await _path_of(session, user_a, artifacts=False)
    auth = _auth(user_a)

    n_art = await _count_sql(client, connection, f"{API}/conversations/{with_art}", auth)
    n_plain = await _count_sql(client, connection, f"{API}/conversations/{without_art}", auth)

    async def _skip(_session: Any, items: Any, **_: Any) -> Any:
        return items

    monkeypatch.setattr(conversations_api, "with_artifacts", _skip)
    n_no_loader = await _count_sql(client, connection, f"{API}/conversations/{with_art}", auth)
    with capsys.disabled():
        print(
            f"\n[DoD-3] SQL: 20 msg x 1 artifact = {n_art}; 20 msg khong artifact = {n_plain}; "
            f"tat lop doc artifact = {n_no_loader}"
        )
    assert n_art == n_plain
    assert n_art == n_no_loader + 1
