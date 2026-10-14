"""T-8.5 — `GET /conversations/{id}/export?format=md` (§18.2, NQ-149 ⑤).

Cây dựng bằng repository như `test_share.py`; StreamingResponse đọc qua ASGI.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.catalog import get_catalog
from app.config.settings import settings
from app.core.access_token import encode_access_token
from app.core.deps import SESSION_COOKIE_NAME
from app.db.models import Message, MessageRole, MessageStatus, UserRole, UserStatus
from app.db.repositories import (
    ArtifactRepository,
    AttachmentRepository,
    ConversationRepository,
    MessageRepository,
)
from app.llm.artifact_blocks import ArtifactBlock
from app.main import app

API = "/api/v1"
MODEL = get_catalog().models[0]


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


class _Conv:
    def __init__(self, session: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID):
        self.session = session
        self.user_id = user_id
        self.id = conversation_id

    async def add(self, parent: uuid.UUID | None, role: MessageRole, content: str) -> Message:
        message = await MessageRepository(self.session).create_message(
            conversation_id=self.id,
            user_id=self.user_id,
            role=role,
            parent_id=parent,
            content=content,
            status=MessageStatus.COMPLETED,
            model_id=MODEL.id if role == MessageRole.ASSISTANT else None,
        )
        await ConversationRepository(self.session).set_active_leaf(
            self.id, user_id=self.user_id, message_id=message.id
        )
        return message

    async def turn(
        self, parent: uuid.UUID | None, text: str = "hoi", answer: str | None = None
    ) -> tuple[Message, Message]:
        question = await self.add(parent, MessageRole.USER, text)
        reply = answer if answer is not None else f"tra loi {text}"
        return question, await self.add(question.id, MessageRole.ASSISTANT, reply)


async def _conv(session: AsyncSession, user_id: uuid.UUID, title: str | None = "Kế hoạch") -> _Conv:
    row = await ConversationRepository(session).create_conversation(user_id=user_id, title=title)
    return _Conv(session, user_id, row.id)


async def _export(client: AsyncClient, conv: _Conv, user_id: uuid.UUID | None = None) -> Response:
    return await client.get(
        f"{API}/conversations/{conv.id}/export",
        params={"format": "md"},
        headers=_auth(user_id or conv.user_id),
    )


async def test_owner_gets_markdown_attachment_with_utf8_name_and_date(
    client: AsyncClient, session: AsyncSession, user_a: uuid.UUID
) -> None:
    conv = await _conv(session, user_a)
    await conv.turn(None)
    await session.commit()

    resp = await _export(client, conv)

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "text/markdown; charset=utf-8"
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    disposition = resp.headers["content-disposition"]
    assert disposition.startswith("attachment; ")
    assert f"filename*=UTF-8''k%E1%BA%BF-ho%E1%BA%A1ch-{today}.md" in disposition
    assert f'filename="ke-hoach-{today}.md"' in disposition
    body = resp.text
    assert body.startswith("# Kế hoạch\n\n_Xuất lúc ")
    assert "\n## Bạn · " in body
    assert f"\n## {MODEL.display_name} · " in body
    assert "\ntra loi hoi\n" in body


async def test_other_user_gets_404(
    client: AsyncClient, session: AsyncSession, user_a: uuid.UUID, user_b: uuid.UUID
) -> None:
    """IDOR (§20): hội thoại của A, cookie của B ⇒ 404, không 403, không byte nào của A."""
    conv = await _conv(session, user_a)
    await conv.turn(None, "bi mat cua A")
    await session.commit()

    resp = await _export(client, conv, user_b)

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"
    assert "bi mat" not in resp.text


async def test_three_branches_exports_path_only(
    client: AsyncClient, session: AsyncSession, user_a: uuid.UUID
) -> None:
    """C11 / A2: nhánh anh em không vào tệp; thứ tự gốc → lá."""
    conv = await _conv(session, user_a)
    _, a1 = await conv.turn(None, "mot")
    await conv.turn(a1.id, "hai-cu")
    await conv.turn(a1.id, "hai-khac")
    _, a2 = await conv.turn(a1.id, "hai")
    await conv.turn(a2.id, "ba")
    await session.commit()

    body = (await _export(client, conv)).text

    assert "hai-cu" not in body and "hai-khac" not in body
    order = [body.index(f"\n{t}\n") for t in ("mot", "tra loi mot", "hai", "ba", "tra loi ba")]
    assert order == sorted(order)
    assert body.count("\n## ") == 6


async def test_content_with_fence_is_byte_exact(
    client: AsyncClient, session: AsyncSession, user_a: uuid.UUID
) -> None:
    answer = "Đây:\n\n```python\nprint('xin chào')\n```\n\nHết."
    conv = await _conv(session, user_a)
    await conv.turn(None, "viet code", answer)
    await session.commit()

    body = (await _export(client, conv)).content

    assert answer.encode() + b"\n" in body


async def test_artifact_with_backticks_gets_longer_fence_and_latest_version(
    client: AsyncClient, session: AsyncSession, user_a: uuid.UUID
) -> None:
    """CommonMark: fence phụ lục dài hơn chuỗi backtick dài nhất; chỉ bản mới nhất mỗi dòng."""
    conv = await _conv(session, user_a)
    _, answer = await conv.turn(None)
    inner = "# README\n\n```bash\nmake test\n```\n"
    [v1] = await ArtifactRepository(session).create_for_message(
        message_id=answer.id,
        user_id=user_a,
        blocks=[ArtifactBlock(kind="code", language="markdown", title="README.md", content="cu")],
    )
    await ArtifactRepository(session).create_user_version(
        user_id=user_a, artifact_id=v1.id, content=inner
    )
    await session.commit()

    body = (await _export(client, conv)).text

    appendix = body.split("\n## Artifact\n", 1)[1]
    assert f"\n### README.md\n\n````markdown\n{inner}````\n" in appendix
    assert "\ncu\n" not in appendix


async def test_file_artifact_is_name_only_no_signed_url(
    client: AsyncClient, session: AsyncSession, user_a: uuid.UUID
) -> None:
    """B-372 / B-406 ②: `kind=file` ⇒ tên, không URL ký, không khoá MinIO."""
    conv = await _conv(session, user_a)
    question, answer = await conv.turn(None)
    key = f"{user_a}/2026/10/{uuid.uuid4()}.xlsx"
    await ArtifactRepository(session).create_for_message(
        message_id=answer.id,
        user_id=user_a,
        blocks=[ArtifactBlock(kind="file", language=None, title="báo cáo.xlsx", content=None,
                              storage_key=key)],
    )  # fmt: skip
    await AttachmentRepository(session).create(
        user_id=user_a, message_id=question.id, kind="image", mime_type="image/png",
        original_name="anh.png", size_bytes=10, storage_key=f"{user_a}/a.png", width=4, height=3,
    )  # fmt: skip
    await session.commit()

    body = (await _export(client, conv)).text

    assert "\n### báo cáo.xlsx\n" in body
    assert "\nTệp đính kèm: anh.png\n" in body
    assert "X-Amz-" not in body and key not in body and str(user_a) not in body


async def test_untitled_conversation_uses_default_name(
    client: AsyncClient, session: AsyncSession, user_a: uuid.UUID
) -> None:
    conv = await _conv(session, user_a, title=None)
    await conv.turn(None)
    await session.commit()

    resp = await _export(client, conv)

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    assert f'filename="hoi-thoai-{today}.md"' in resp.headers["content-disposition"]
    assert resp.text.startswith("# Hội thoại\n")


async def test_batch_size_one_is_same_bytes_as_large_batch(
    client: AsyncClient, session: AsyncSession, user_a: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    conv = await _conv(session, user_a)
    parent = None
    for i in range(4):
        _, answer = await conv.turn(parent, f"cau {i}")
        await ArtifactRepository(session).create_for_message(
            message_id=answer.id,
            user_id=user_a,
            blocks=[ArtifactBlock(kind="code", language="py", title=f"a{i}.py", content=f"x={i}")],
        )
        parent = answer.id
    await session.commit()

    def without_time(text: str) -> str:
        return "\n".join(line for line in text.split("\n") if not line.startswith("_Xuất lúc"))

    monkeypatch.setattr(settings, "EXPORT_BATCH_SIZE", 1000)
    large = without_time((await _export(client, conv)).text)
    monkeypatch.setattr(settings, "EXPORT_BATCH_SIZE", 1)
    small = without_time((await _export(client, conv)).text)

    assert small == large
    assert large.count("\n### a") == 4


async def test_format_other_than_md_is_422(
    client: AsyncClient, session: AsyncSession, user_a: uuid.UUID
) -> None:
    conv = await _conv(session, user_a)
    await session.commit()

    resp = await client.get(
        f"{API}/conversations/{conv.id}/export", params={"format": "json"}, headers=_auth(user_a)
    )

    assert resp.status_code == 422
