"""T-8.5 / T-8.6 — `GET /conversations/{id}/export?format=md|json` (§18.2, NQ-149 ⑤).

Cây dựng bằng repository như `test_share.py`; StreamingResponse đọc qua ASGI.
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import func, update
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


async def test_format_other_than_md_or_json_is_422(
    client: AsyncClient, session: AsyncSession, user_a: uuid.UUID
) -> None:
    conv = await _conv(session, user_a)
    await session.commit()

    resp = await client.get(
        f"{API}/conversations/{conv.id}/export", params={"format": "xml"}, headers=_auth(user_a)
    )

    assert resp.status_code == 422


# ─────────────────────────── T-8.6 — JSON ───────────────────────────

CHECK_EXPORT = Path(__file__).resolve().parents[3] / "scripts" / "check_export.py"


async def _export_json(
    client: AsyncClient, conv: _Conv, *, full: bool = False, user_id: uuid.UUID | None = None
) -> Response:
    return await client.get(
        f"{API}/conversations/{conv.id}/export",
        params={"format": "json", "full": str(full).lower()},
        headers=_auth(user_id or conv.user_id),
    )


async def _branches(conv: _Conv) -> dict[str, Message]:
    """Gốc r → a1 → a2 và r → b1 → b2, tạo theo thứ tự r, a1, b1, a2, b2: sắp
    `created_at` thuần sẽ XEN hai nhánh (a1, b1, a2, b2); lá hoạt động = a2."""
    r = await conv.add(None, MessageRole.USER, "r")
    a1 = await conv.add(r.id, MessageRole.ASSISTANT, "a1")
    b1 = await conv.add(r.id, MessageRole.ASSISTANT, "b1")
    a2 = await conv.add(a1.id, MessageRole.USER, "a2")
    b2 = await conv.add(b1.id, MessageRole.USER, "b2")
    await ConversationRepository(conv.session).set_active_leaf(
        conv.id, user_id=conv.user_id, message_id=a2.id
    )
    return {"r": r, "a1": a1, "b1": b1, "a2": a2, "b2": b2}


async def test_json_body_parses_and_follows_contract(
    client: AsyncClient, session: AsyncSession, user_a: uuid.UUID
) -> None:
    conv = await _conv(session, user_a)
    question, answer = await conv.turn(None)
    await AttachmentRepository(session).create(
        user_id=user_a, message_id=question.id, kind="image", mime_type="image/png",
        original_name="anh.png", size_bytes=10, storage_key=f"{user_a}/a.png", width=4, height=3,
    )  # fmt: skip
    await session.commit()

    resp = await _export_json(client, conv)

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/json"
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    assert f'filename="ke-hoach-{today}.json"' in resp.headers["content-disposition"]
    data = json.loads(resp.content)
    assert (data["format"], data["version"], data["scope"]) == ("scarlet-conversation", 1, "path")
    assert data["conversation"] == {
        "id": str(conv.id),
        "title": "Kế hoạch",
        "created_at": data["conversation"]["created_at"],
        "default_model": None,
        "active_leaf_id": str(answer.id),
    }
    first, second = data["messages"]
    assert set(first) == {
        "id", "parent_id", "role", "status", "content", "reasoning", "model_id",
        "model_display_name", "created_at", "finish_reason", "attachments", "artifacts",
    }  # fmt: skip
    assert first["attachments"] == [{"name": "anh.png", "mime_type": "image/png", "size_bytes": 10}]
    assert second["model_display_name"] == MODEL.display_name
    assert "storage_key" not in resp.text and "cost" not in resp.text


async def test_json_three_branches_path_vs_full(
    client: AsyncClient, session: AsyncSession, user_a: uuid.UUID
) -> None:
    """C11: `full=false` = đường đi; `full=true` = mọi message."""
    conv = await _conv(session, user_a)
    _, a1 = await conv.turn(None, "mot")
    await conv.turn(a1.id, "hai-cu")
    await conv.turn(a1.id, "hai-khac")
    _, a2 = await conv.turn(a1.id, "hai")
    await conv.turn(a2.id, "ba")
    await session.commit()

    path = json.loads((await _export_json(client, conv)).content)
    tree = json.loads((await _export_json(client, conv, full=True)).content)

    assert [m["content"] for m in path["messages"]] == [
        "mot", "tra loi mot", "hai", "tra loi hai", "ba", "tra loi ba",
    ]  # fmt: skip
    assert tree["scope"] == "tree"
    assert len(tree["messages"]) == 10


async def test_json_full_tree_parent_first_branches_contiguous(
    client: AsyncClient, session: AsyncSession, user_a: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Duyệt sâu trước, anh em `(created_at, id)`: r, a1, a2, b1, b2 — không phải
    r, a1, b1, a2, b2 của `created_at` thuần. Lô 1 để thứ tự đi qua ranh giới lô."""
    conv = await _conv(session, user_a)
    await _branches(conv)
    await session.commit()
    monkeypatch.setattr(settings, "EXPORT_BATCH_SIZE", 1)

    data = json.loads((await _export_json(client, conv, full=True)).content)

    assert [m["content"] for m in data["messages"]] == ["r", "a1", "a2", "b1", "b2"]
    seen: set[str | None] = {None}
    for m in data["messages"]:
        assert m["parent_id"] in seen
        seen.add(m["id"])


async def test_json_soft_deleted_message_and_its_subtree_are_absent(
    client: AsyncClient, session: AsyncSession, user_a: uuid.UUID
) -> None:
    """C12: b1 xoá mềm ⇒ b1 và b2 (con của nó) đều vắng; không con nào mồ côi."""
    conv = await _conv(session, user_a)
    nodes = await _branches(conv)
    await session.execute(
        update(Message).where(Message.id == nodes["b1"].id).values(deleted_at=func.now())
    )
    await session.commit()

    data = json.loads((await _export_json(client, conv, full=True)).content)

    assert [m["content"] for m in data["messages"]] == ["r", "a1", "a2"]


async def test_json_includes_reasoning_and_file_artifact_content_null(
    client: AsyncClient, session: AsyncSession, user_a: uuid.UUID
) -> None:
    conv = await _conv(session, user_a)
    _, answer = await conv.turn(None)
    await session.execute(
        update(Message).where(Message.id == answer.id).values(reasoning="suy nghi cua model")
    )
    key = f"{user_a}/2026/10/{uuid.uuid4()}.xlsx"
    await ArtifactRepository(session).create_for_message(
        message_id=answer.id,
        user_id=user_a,
        blocks=[ArtifactBlock(kind="file", language=None, title="báo cáo.xlsx", content=None,
                              storage_key=key)],
    )  # fmt: skip
    await session.commit()

    resp = await _export_json(client, conv)

    reply = json.loads(resp.content)["messages"][1]
    assert reply["reasoning"] == "suy nghi cua model"
    [artifact] = reply["artifacts"]
    assert artifact["kind"] == "file" and artifact["content"] is None
    assert artifact["title"] == "báo cáo.xlsx"
    assert key not in resp.text and "X-Amz-" not in resp.text


async def test_json_other_user_gets_404(
    client: AsyncClient, session: AsyncSession, user_a: uuid.UUID, user_b: uuid.UUID
) -> None:
    conv = await _conv(session, user_a)
    await conv.turn(None, "bi mat cua A")
    await session.commit()

    resp = await _export_json(client, conv, full=True, user_id=user_b)

    assert resp.status_code == 404
    assert "bi mat" not in resp.text


async def test_check_export_script_accepts_output_and_rejects_orphan(
    client: AsyncClient, session: AsyncSession, user_a: uuid.UUID, tmp_path: Path
) -> None:
    """`check_export.py` (tiến trình con) trên đầu ra thật ⇒ exit 0; bỏ b1 giữa tệp
    ⇒ b2 mồ côi ⇒ exit ≠ 0 kèm lý do. b1 nằm NGOÀI đường đi: chỉ phép kiểm "cha
    trước con" bắt được, dựng đường đi từ lá vẫn trót lọt."""
    conv = await _conv(session, user_a)
    await _branches(conv)
    await session.commit()
    body = (await _export_json(client, conv, full=True)).content
    good = tmp_path / "t.json"
    good.write_bytes(body)

    ok = subprocess.run(
        [sys.executable, str(CHECK_EXPORT), str(good)], capture_output=True, text=True
    )

    assert ok.returncode == 0, ok.stderr
    assert "messages=5 roots=1 leaves=2 path=3" in ok.stdout

    data = json.loads(body)
    assert data["messages"][3]["content"] == "b1"
    del data["messages"][3]
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(data))
    broken = subprocess.run(
        [sys.executable, str(CHECK_EXPORT), str(bad)], capture_output=True, text=True
    )

    assert broken.returncode != 0
    assert "chua xuat hien truoc" in broken.stderr
