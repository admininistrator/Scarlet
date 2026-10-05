"""S9 — guard vision ở cả ba đường sinh chữ (T-4.5, §9.4, UC-06 dòng 1–2).

Câu hỏi của lượt sắp sinh có ảnh + model (đã resolve, đã gộp ghi đè admin)
không `vision` ⇒ `422 MODEL_NO_VISION`, không message nào được tạo. Ảnh ở lượt
cũ không chặn (T-4.4b đã thay nó bằng chữ). Phần cuối: ghi đè `vision` của
admin (`PATCH /admin/models/{id}`, NQ-139) — guard và `GET /models` theo nó.

Model thật của catalog: chọn theo `capabilities` lúc chạy, không ghim tên —
người vận hành đổi cờ trong `model_catalog.json` thì test vẫn nói đúng chuyện.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import catalog
from app.config.settings import settings
from app.core.access_token import encode_access_token
from app.core.crypto import seal
from app.core.deps import SESSION_COOKIE_NAME
from app.db.models import (
    AttachmentKind,
    AuditAction,
    AuditLog,
    ExtractStatus,
    Message,
    MessageRole,
    MessageStatus,
    User,
    UserRole,
    UserStatus,
)
from app.db.models.attachment import PDF_MIME
from app.db.repositories import (
    AttachmentRepository,
    ByokEndpointRepository,
    ConversationRepository,
    MessageRepository,
)
from app.llm import byok_endpoints
from app.main import app

API = "/api/v1"
NO_VISION = "MODEL_NO_VISION"


def _model(*, vision: bool) -> str:
    """Một model đang bật của catalog thật, có / không có `vision`."""
    return next(
        m.id
        for m in catalog.get_catalog().models
        if m.enabled and (catalog.VISION_CAPABILITY in m.capabilities) == vision
    )


class _FakeArq:
    def __init__(self) -> None:
        self.pushed: list[str] = []

    async def enqueue_job(self, name: str, *_: Any, **__: Any) -> object:
        self.pushed.append(name)
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


def _auth(user_id: uuid.UUID, role: UserRole = UserRole.USER) -> dict[str, str]:
    token = encode_access_token(
        user_id=user_id, role=role, tier="free", status=UserStatus.ACTIVE, ttl_minutes=15
    )
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


async def _upload(factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID) -> uuid.UUID:
    """Một hàng như `POST /attachments` để lại — chưa gắn message nào."""
    async with factory() as session:
        row = await AttachmentRepository(session).create(
            user_id=user_id,
            kind=AttachmentKind.IMAGE,
            mime_type="image/png",
            original_name="anh.png",
            size_bytes=100,
            storage_key=f"{user_id}/2026/10/{uuid.uuid4()}.png",
            width=40,
            height=30,
        )
        await session.commit()
        return row.id


async def _turn_with_image(
    factory: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
    *,
    default_model: str | None = None,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Hội thoại một lượt đã xong: câu hỏi CÓ ảnh → câu trả lời `completed`.

    Trả `(conversation, câu hỏi, câu trả lời)`. Câu trả lời mang model có vision.
    """
    async with factory() as session:
        conv = await ConversationRepository(session).create_conversation(
            user_id=user_id, default_model=default_model
        )
        messages = MessageRepository(session)
        question = await messages.create_message(
            conversation_id=conv.id,
            user_id=user_id,
            role=MessageRole.USER,
            parent_id=None,
            content="anh nay la gi",
            status=MessageStatus.COMPLETED,
        )
        await AttachmentRepository(session).create(
            user_id=user_id,
            message_id=question.id,
            kind=AttachmentKind.IMAGE,
            mime_type="image/png",
            original_name="anh.png",
            size_bytes=1,
            storage_key=f"{user_id}/old.png",
        )
        answer = await messages.create_message(
            conversation_id=conv.id,
            user_id=user_id,
            role=MessageRole.ASSISTANT,
            parent_id=question.id,
            content="mot con meo",
            status=MessageStatus.COMPLETED,
            model_id=_model(vision=True),
        )
        await ConversationRepository(session).set_active_leaf(
            conv.id, user_id=user_id, message_id=answer.id
        )
        await session.commit()
        return conv.id, question.id, answer.id


async def _count(factory: async_sessionmaker[AsyncSession]) -> int:
    async with factory() as session:
        return int((await session.execute(select(func.count()).select_from(Message))).scalar_one())


def _assert_no_vision(resp: Any, model_id: str) -> None:
    assert resp.status_code == 422, resp.text
    error = resp.json()["error"]
    assert error["code"] == NO_VISION
    assert error["details"] == {"model_id": model_id}


async def _post(
    client: AsyncClient, user_id: uuid.UUID, conv: uuid.UUID, ids: list[uuid.UUID], model: str
) -> Any:
    return await client.post(
        f"{API}/conversations/{conv}/messages",
        headers=_auth(user_id),
        json={"content": "DoD T-4.5", "attachment_ids": [str(i) for i in ids], "model_id": model},
    )


# ═══════════════════════════ ba đường × model không vision ═══════════════════


async def test_post_image_to_model_without_vision_is_422_and_writes_nothing(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_arq: _FakeArq,
) -> None:
    async with session_factory() as session:
        conv = (await ConversationRepository(session).create_conversation(user_id=user_a)).id
        await session.commit()
    att = await _upload(session_factory, user_a)
    before = await _count(session_factory)
    model = _model(vision=False)

    resp = await _post(client, user_a, conv, [att], model)

    _assert_no_vision(resp, model)
    assert await _count(session_factory) == before
    assert fake_arq.pushed == []
    async with session_factory() as session:
        row = await AttachmentRepository(session).get(user_id=user_a, attachment_id=att)
        assert row is not None and row.message_id is None


async def test_retry_with_model_without_vision_is_422_and_writes_nothing(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_arq: _FakeArq,
) -> None:
    """Cạm bẫy ①: "Đổi model & thử lại" là đường bypass S9 nói tới."""
    _conv, _question, answer = await _turn_with_image(session_factory, user_a)
    before = await _count(session_factory)
    model = _model(vision=False)

    resp = await client.post(
        f"{API}/messages/{answer}/retry", headers=_auth(user_a), json={"model_id": model}
    )

    _assert_no_vision(resp, model)
    assert await _count(session_factory) == before
    assert fake_arq.pushed == []


async def test_patch_question_with_image_on_model_without_vision_is_422(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_arq: _FakeArq,
) -> None:
    """Bản sửa mang theo ảnh của bản gốc (NQ-138 ③) ⇒ cũng là ảnh lượt này."""
    model = _model(vision=False)
    _conv, question, _answer = await _turn_with_image(session_factory, user_a, default_model=model)
    before = await _count(session_factory)

    resp = await client.patch(
        f"{API}/messages/{question}", headers=_auth(user_a), json={"content": "sua lai"}
    )

    _assert_no_vision(resp, model)
    assert await _count(session_factory) == before
    assert fake_arq.pushed == []


# ═══════════════════════════════ những ca được qua ══════════════════════════


async def test_model_with_vision_is_202_on_all_three_routes(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    vision = _model(vision=True)
    conv, question, answer = await _turn_with_image(session_factory, user_a, default_model=vision)
    att = await _upload(session_factory, user_a)

    posted = await _post(client, user_a, conv, [att], vision)
    retried = await client.post(
        f"{API}/messages/{answer}/retry", headers=_auth(user_a), json={"model_id": vision}
    )

    assert posted.status_code == 202, posted.text
    assert retried.status_code == 202, retried.text
    edited = await client.patch(
        f"{API}/messages/{question}", headers=_auth(user_a), json={"content": "sua lai"}
    )
    assert edited.status_code == 202, edited.text


async def test_image_in_older_turn_does_not_block_model_without_vision(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    """Ảnh ở lượt 1 đã thành `[ảnh: …]` trong ngữ cảnh (T-4.4b) — lượt 2 chỉ chữ ⇒ qua."""
    conv, _question, answer = await _turn_with_image(session_factory, user_a)

    resp = await client.post(
        f"{API}/conversations/{conv}/messages",
        headers=_auth(user_a),
        json={"content": "con gi nua", "parent_id": str(answer), "model_id": _model(vision=False)},
    )

    assert resp.status_code == 202, resp.text


async def test_byok_endpoint_model_with_image_is_422(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    """Cạm bẫy ②: model endpoint dựng tại chỗ với `capabilities: []`."""
    async with session_factory() as session:
        endpoint = await ByokEndpointRepository(session).create(
            user_id=user_a,
            label="Groq",
            base_url="https://api.groq.com/openai/v1",
            sealed=seal("khoa-gia"),
            masked="x",
            models=["llama"],
            verified_at=None,
        )
        conv = (await ConversationRepository(session).create_conversation(user_id=user_a)).id
        await session.commit()
    att = await _upload(session_factory, user_a)
    model = byok_endpoints.model_id_for(endpoint.id, "llama")
    before = await _count(session_factory)

    resp = await _post(client, user_a, conv, [att], model)

    _assert_no_vision(resp, model)
    assert await _count(session_factory) == before


# ═══════════════════ ghi đè `vision` của admin (NQ-139) ══════════════════════


async def _admin(factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID) -> dict[str, str]:
    async with factory() as session:
        await session.execute(update(User).where(User.id == user_id).values(role=UserRole.ADMIN))
        await session.commit()
    return _auth(user_id, UserRole.ADMIN)


async def _set_vision(client: AsyncClient, auth: dict[str, str], model: str, vision: Any) -> Any:
    return await client.patch(f"{API}/admin/models/{model}", headers=auth, json={"vision": vision})


async def _public_capabilities(client: AsyncClient, auth: dict[str, str], model: str) -> list[str]:
    resp = await client.get(f"{API}/models", headers=auth)
    assert resp.status_code == 200
    return next(m["capabilities"] for m in resp.json() if m["id"] == model)


async def test_admin_override_turns_vision_on_and_off_for_guard_and_models(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
) -> None:
    admin = await _admin(session_factory, user_b)
    no_vision, vision = _model(vision=False), _model(vision=True)
    async with session_factory() as session:
        conv = (await ConversationRepository(session).create_conversation(user_id=user_a)).id
        await session.commit()

    # Bật cho model file khai không ⇒ guard cho qua, `GET /models` có `vision`.
    assert (await _set_vision(client, admin, no_vision, True)).status_code == 204
    assert "vision" in await _public_capabilities(client, _auth(user_a), no_vision)
    ok = await _post(client, user_a, conv, [await _upload(session_factory, user_a)], no_vision)
    assert ok.status_code == 202, ok.text

    # Tắt cho model file khai có ⇒ guard chặn.
    assert (await _set_vision(client, admin, vision, False)).status_code == 204
    assert "vision" not in await _public_capabilities(client, _auth(user_a), vision)
    blocked = await _post(client, user_a, conv, [await _upload(session_factory, user_a)], vision)
    _assert_no_vision(blocked, vision)

    # `null` ⇒ về giá trị file.
    assert (await _set_vision(client, admin, vision, None)).status_code == 204
    assert "vision" in await _public_capabilities(client, _auth(user_a), vision)

    listed = (await client.get(f"{API}/admin/models", headers=admin)).json()["models"]
    by_id = {m["id"]: m for m in listed}
    assert (by_id[no_vision]["vision"], by_id[no_vision]["vision_override"]) == (True, True)
    assert (by_id[vision]["vision"], by_id[vision]["vision_override"]) == (True, None)


async def test_admin_override_writes_audit_only_on_change_and_404_for_unknown(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], user_b: uuid.UUID
) -> None:
    admin = await _admin(session_factory, user_b)
    model = _model(vision=False)

    for _ in range(2):
        assert (await _set_vision(client, admin, model, True)).status_code == 204
    unknown = await _set_vision(client, admin, "khong-co-model-nay", True)
    missing_field = await client.patch(f"{API}/admin/models/{model}", headers=admin, json={})

    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "MODEL_UNKNOWN"
    assert missing_field.status_code == 422
    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(AuditLog).where(AuditLog.action == AuditAction.MODEL_UPDATE)
                )
            )
            .scalars()
            .all()
        )
    assert [(r.target_id, r.details) for r in rows] == [
        (model, {"changed": {"vision_override": {"from": None, "to": True}}})
    ]


async def test_user_cannot_override_vision(client: AsyncClient, user_a: uuid.UUID) -> None:
    resp = await _set_vision(client, _auth(user_a), _model(vision=False), True)

    assert resp.status_code == 403


# ═══════════════════════ PDF quét cần vision (T-4.6b) ═══════════════════════


async def _upload_pdf(
    factory: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
    *,
    status: ExtractStatus,
    pages: int,
    text: str | None = None,
) -> uuid.UUID:
    """PDF đã qua job `extract` (T-4.6a) — chưa gắn message nào."""
    async with factory() as session:
        row = await AttachmentRepository(session).create(
            user_id=user_id,
            kind=AttachmentKind.FILE,
            mime_type=PDF_MIME,
            original_name="tai-lieu.pdf",
            size_bytes=100,
            storage_key=f"{user_id}/2026/10/{uuid.uuid4()}.pdf",
            extract_status=status,
            extracted_text=text,
            page_count=pages,
        )
        await session.commit()
        return row.id


async def _new_conversation(
    factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> uuid.UUID:
    async with factory() as session:
        conv = (await ConversationRepository(session).create_conversation(user_id=user_id)).id
        await session.commit()
        return conv


@pytest.mark.parametrize(
    "status", [ExtractStatus.NEEDS_VISION, ExtractStatus.TOO_MANY_PAGES], ids=str
)
async def test_scanned_pdf_over_page_cap_is_422_and_writes_nothing(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_arq: _FakeArq,
    monkeypatch: pytest.MonkeyPatch,
    status: ExtractStatus,
) -> None:
    """**DoD**: trần = 2 (đọc lúc gọi) + PDF quét 3 trang ⇒ `422` nêu trần, cả model có vision."""
    monkeypatch.setattr(settings, "MAX_PDF_PAGES_VISION", 2)
    conv = await _new_conversation(session_factory, user_a)
    att = await _upload_pdf(session_factory, user_a, status=status, pages=3)
    before = await _count(session_factory)

    resp = await _post(client, user_a, conv, [att], _model(vision=True))

    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "PDF_TOO_MANY_PAGES"
    assert resp.json()["error"]["details"] == {"max_pages": 2}
    assert await _count(session_factory) == before
    assert fake_arq.pushed == []


async def test_scanned_pdf_to_model_without_vision_is_422(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_arq: _FakeArq,
) -> None:
    """**DoD**: PDF quét + model không vision ⇒ `422 MODEL_NO_VISION` (T-4.5 coi nó như ảnh)."""
    conv = await _new_conversation(session_factory, user_a)
    att = await _upload_pdf(session_factory, user_a, status=ExtractStatus.NEEDS_VISION, pages=2)
    before = await _count(session_factory)
    model = _model(vision=False)

    resp = await _post(client, user_a, conv, [att], model)

    _assert_no_vision(resp, model)
    assert await _count(session_factory) == before
    assert fake_arq.pushed == []


async def test_text_pdf_to_model_without_vision_is_202(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    """**DoD**: PDF có chữ + model không vision ⇒ `202` — chữ là chữ (T-4.6a)."""
    conv = await _new_conversation(session_factory, user_a)
    att = await _upload_pdf(
        session_factory, user_a, status=ExtractStatus.DONE, pages=12, text="Bao cao quy 3."
    )

    resp = await _post(client, user_a, conv, [att], _model(vision=False))

    assert resp.status_code == 202, resp.text
