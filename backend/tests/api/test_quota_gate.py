"""Cửa chặn §10.2 nhìn từ ngoài HTTP: ba route sinh chữ, `429`, cảnh báo — T-2.11.

`tests/quota/test_estimator.py` kiểm phép tính và hình dạng `ApiError`; file
này kiểm ba thứ mà chỉ tầng HTTP trả lời được:

1. **Cả ba** route sinh chữ đều đi qua cửa — quên một route là một đường chi
   tiêu không có trần, và nó sẽ là đường `retry` (bấm Retry 50 lần tốn đúng 50
   lần tiền).
2. Lượt bị chặn **không để lại gì**: không hàng `messages`, không job trong
   hàng đợi. Đó là nửa kiểm được trong `pytest` của S6 ("0 USD phát sinh");
   nửa còn lại — log LiteLLM không có request nào — nằm ở DoD dòng 1 trên
   stack thật.
3. Cảnh báo UC-07 ra tới **body** của `202`.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import catalog
from app.config.settings import settings
from app.core.access_token import encode_access_token
from app.core.crypto import mask_secret, seal
from app.core.deps import SESSION_COOKIE_NAME
from app.db.models import Conversation, Message, MessageRole, MessageStatus, UserRole, UserStatus
from app.db.repositories import ConversationRepository, MessageRepository, ProviderKeyRepository
from app.main import app
from app.quota.windows import LimitType, Window, encode_member

CREATE_PATH = "/api/v1/conversations/{}/messages"
RETRY_PATH = "/api/v1/messages/{}/retry"
EDIT_PATH = "/api/v1/messages/{}"


class FakeArq:
    """Pool arq giả — ở đây chỉ để đếm: lượt bị chặn phải đẩy **0** job."""

    def __init__(self) -> None:
        self.pushed: list[tuple[str, tuple[Any, ...]]] = []

    async def enqueue_job(self, name: str, *args: Any, **kwargs: Any) -> object:
        self.pushed.append((name, args))
        return object()


@pytest.fixture
def _db_for_tests(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


@pytest_asyncio.fixture
async def fake_arq(monkeypatch: pytest.MonkeyPatch) -> FakeArq:
    fake = FakeArq()

    async def _pool() -> FakeArq:
        return fake

    monkeypatch.setattr("app.api.v1.messages.get_arq_pool", _pool)
    return fake


@pytest_asyncio.fixture
async def client(event_hooks: dict[str, Any]) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://localhost", event_hooks=event_hooks
    ) as http:
        yield http


def _session(user_id: uuid.UUID) -> dict[str, str]:
    """Header `Cookie` mang phiên thật (§11.2) của `user_id` — T-3.1c.

    Trả một `dict` để truyền vào `headers=` của **từng request**, đúng chỗ mà
    header danh tính tạm của Phase 1 đứng trước đây: danh tính theo request
    chứ không đặt lên `client`, nên hai danh tính trong cùng một ca (phép kiểm
    quyền sở hữu, §20) vẫn viết được cạnh nhau mà không ai phải nhớ dọn.

    **Một header `Cookie`, không phải tham số `cookies=` của httpx.** httpx đã
    deprecate `cookies=` theo request (*"expected behaviour on cookie
    persistence is ambiguous"*) — và ở đây không có gì để persist: mỗi request
    tự mang phiên của nó. Một `dict` header còn ghép được bằng `|` với
    `Idempotency-Key` hay `Last-Event-ID` mà không phải trộn hai cơ chế.

    `status=ACTIVE` chứ không đọc từ bảng `users`: §11.1 kiểm trạng thái từ
    **claim** của access token (xem `core/deps.py`), và bộ test này đo chuyện
    khác — ma trận 5×4 của bảng ấy là việc của `test_account_states.py`.
    """
    token = encode_access_token(
        user_id=user_id,
        role=UserRole.USER,
        tier="free",
        status=UserStatus.ACTIVE,
        ttl_minutes=15,
    )
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


async def _exhaust_quota(
    session_factory: async_sessionmaker[AsyncSession], redis: Any, user_id: uuid.UUID
) -> None:
    """Nạp đúng hạn mức 5 giờ của tier `free` vào cửa sổ ⇒ lượt tiếp theo bị chặn."""
    window = Window(LimitType.SHORT, settings.QUOTA_WINDOW_SHORT_S)
    redis.zset[window.key(user_id)] = {
        encode_member(uuid.uuid4(), Decimal("0.50")): time.time() - 17000
    }


async def _conversation(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> Conversation:
    async with session_factory() as session:
        conversation = await ConversationRepository(session).create_conversation(user_id=user_id)
        await session.commit()
        return conversation


async def _question_answer_pair(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Hội thoại + một cặp hỏi/đáp đã xong — nguyên liệu cho `retry` và `PATCH`."""
    conversation = await _conversation(session_factory, user_id)
    async with session_factory() as session:
        messages = MessageRepository(session)
        question = await messages.create_message(
            conversation_id=conversation.id,
            user_id=user_id,
            role=MessageRole.USER,
            parent_id=None,
            content="cau hoi cu",
        )
        answer = await messages.create_message(
            conversation_id=conversation.id,
            user_id=user_id,
            role=MessageRole.ASSISTANT,
            parent_id=question.id,
            content="cau tra loi cu",
            status=MessageStatus.COMPLETED,
        )
        await session.commit()
        return conversation.id, question.id, answer.id


async def _count_messages(
    session_factory: async_sessionmaker[AsyncSession], conversation_id: uuid.UUID
) -> int:
    async with session_factory() as session:
        stmt = (
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == conversation_id)
        )
        return int((await session.execute(stmt)).scalar_one())


# ════════════════════ ba route sinh chữ, cùng một cửa ════════════════════


async def test_post_messages_blocked_when_quota_exhausted(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    quota_redis: Any,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """S6 nửa kiểm được trong pytest: `429`, 0 message mới, 0 job."""
    conversation = await _conversation(session_factory, user_a)
    await _exhaust_quota(session_factory, quota_redis, user_a)

    resp = await client.post(
        CREATE_PATH.format(conversation.id),
        headers=_session(user_a),
        json={"content": "xin chao"},
    )

    assert resp.status_code == 429
    error = resp.json()["error"]
    assert error["code"] == "QUOTA_EXCEEDED"
    assert error["details"]["limit_type"] == "5h"
    assert resp.headers["Retry-After"] == str(error["details"]["retry_after"])

    assert await _count_messages(session_factory, conversation.id) == 0, "transaction phải rollback"
    assert fake_arq.pushed == [], "0 job ⇒ 0 USD (S6)"


async def test_retry_blocked_when_quota_exhausted(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    quota_redis: Any,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """Đường tốn tiền dễ quên nhất: bấm Retry không tạo message user nào."""
    conversation_id, _, answer_id = await _question_answer_pair(session_factory, user_a)
    before = await _count_messages(session_factory, conversation_id)
    await _exhaust_quota(session_factory, quota_redis, user_a)

    resp = await client.post(RETRY_PATH.format(answer_id), headers=_session(user_a), json={})

    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "QUOTA_EXCEEDED"
    assert await _count_messages(session_factory, conversation_id) == before
    assert fake_arq.pushed == []


async def test_patch_message_blocked_when_quota_exhausted(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    quota_redis: Any,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    conversation_id, question_id, _ = await _question_answer_pair(session_factory, user_a)
    before = await _count_messages(session_factory, conversation_id)
    await _exhaust_quota(session_factory, quota_redis, user_a)

    resp = await client.patch(
        EDIT_PATH.format(question_id),
        headers=_session(user_a),
        json={"content": "cau hoi da sua"},
    )

    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "QUOTA_EXCEEDED"
    assert await _count_messages(session_factory, conversation_id) == before
    assert fake_arq.pushed == []


# ═══════════════════════ cảnh báo UC-07 trong body ════════════════════════


async def test_low_quota_202_with_warning_in_body(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    quota_redis: Any,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """DoD dòng 4: còn 15% quota ⇒ request VẪN QUA, response có cảnh báo."""
    conversation = await _conversation(session_factory, user_a)
    window = Window(LimitType.SHORT, settings.QUOTA_WINDOW_SHORT_S)
    quota_redis.zset[window.key(user_a)] = {
        encode_member(uuid.uuid4(), Decimal("0.425")): time.time() - 60
    }

    resp = await client.post(
        CREATE_PATH.format(conversation.id),
        headers=_session(user_a),
        # Model không có giá ⇒ dự toán 0 ⇒ 0.425 + 0 < 0.50, đi qua. Test này
        # đo CẢNH BÁO, không đo cửa chặn.
        json={"content": "xin chao", "model_id": "nr-gemini-flash"},
    )

    assert resp.status_code == 202
    warning = resp.json()["quota_warning"]
    assert warning is not None
    assert warning["limit_type"] == "5h"
    assert warning["remaining_pct"] == 15
    assert Decimal(warning["remaining_usd"]) == Decimal("0.075")
    # "cảnh báo KHÔNG được chặn (UC-07 dòng 1)"; `title` là của T-S.7 (câu đầu).
    assert [name for name, _ in fake_arq.pushed] == ["generate", "title"]


async def test_ample_quota_has_no_warning(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    quota_redis: Any,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    conversation = await _conversation(session_factory, user_a)
    resp = await client.post(
        CREATE_PATH.format(conversation.id),
        headers=_session(user_a),
        json={"content": "xin chao"},
    )
    assert resp.status_code == 202
    assert resp.json()["quota_warning"] is None


async def test_user_specific_limit_is_honored(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    quota_redis: Any,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """DoD dòng 1 chạy đúng bằng đường này: `limit_5h_usd = 0.001` cho một user."""
    conversation = await _conversation(session_factory, user_a)
    async with session_factory() as session:
        await session.execute(
            text(
                "UPDATE users SET limit_override_json = '{\"limit_5h_usd\": 0.001}'::jsonb "
                "WHERE id = :uid"
            ),
            {"uid": user_a},
        )
        await session.commit()

    resp = await client.post(
        CREATE_PATH.format(conversation.id),
        headers=_session(user_a),
        json={"content": "xin chao"},
    )

    assert resp.status_code == 429
    error = resp.json()["error"]
    assert error["details"]["retry_after"] is None, "cửa sổ rỗng ⇒ không có gì để hẹn"
    assert "Retry-After" not in resp.headers
    assert await _count_messages(session_factory, conversation.id) == 0
    assert fake_arq.pushed == []


async def test_blocked_does_NOT_take_generation_seat(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    quota_redis: Any,
    ratelimit_redis: Any,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """Thứ tự trong `_open_generation` là hợp đồng: quota TRƯỚC, ghế SAU.

    Ghế bận chỉ được nhả bằng phép đối chiếu Postgres sau `PHANTOM_GRACE_S`
    (60 s), nên nhận ghế rồi mới từ chối vì quota là khoá một trong ba ghế của
    người dùng suốt một phút — cho một lượt sinh chưa từng tồn tại. Đảo hai
    dòng ấy không làm test nào khác đỏ, nên phép kiểm phải nằm ở đây.
    """
    conversation = await _conversation(session_factory, user_a)
    await _exhaust_quota(session_factory, quota_redis, user_a)

    resp = await client.post(
        CREATE_PATH.format(conversation.id),
        headers=_session(user_a),
        json={"content": "xin chao"},
    )

    assert resp.status_code == 429
    assert [name for name, _ in ratelimit_redis.calls] == ["bucket"], (
        "chỉ token bucket được chạy; script giữ ghế (`slot`) KHÔNG được chạm tới"
    )


# ═══════════ BYOK bỏ qua cửa quota, KHÔNG bỏ qua gì khác (§10.5, B-157) ═══════════
#
# §10.5 hàng "Quota": *"Request dùng BYOK **không** trừ quota, nhưng **vẫn**
# ghi `usage_events` với `key_source='byok'`"*, và hàng "Rate limit": *"Vẫn áp
# dụng"*. Ba test dưới đây đo đúng ba vế đó nhìn từ ngoài HTTP; vế ghi sổ nằm
# ở `tests/quota/test_meter.py` và `tests/workers/test_generate.py`.


async def _save_byok_key(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> str:
    """Khoá BYOK cho provider của model MẶC ĐỊNH — đúng model mà request sẽ gọi."""
    model = catalog.get_default_model()
    assert model is not None
    key = "sk-" + "0123456789abcdef" * 2
    async with session_factory() as session:
        await ProviderKeyRepository(session).upsert(
            user_id=user_id,
            provider=model.provider,
            sealed=seal(key),
            masked=mask_secret(key),
            verified_at=None,
        )
        await session.commit()
    return model.provider


async def test_byok_still_chats_when_system_quota_exhausted(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    quota_redis: Any,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """**DoD dòng 1 của T-2.15** (UC-07) ở mức HTTP: hết quota vẫn `202`.

    Cùng một người, cùng một hội thoại, cùng một cửa sổ quota đã đầy như
    `test_post_messages_blocked_when_quota_exhausted` — khác đúng một thứ: có khoá
    riêng. Gỡ nhánh `if key_source is KeySource.SYSTEM` ở `_open_generation` ra
    thì test này thành `429`.
    """
    conversation = await _conversation(session_factory, user_a)
    await _exhaust_quota(session_factory, quota_redis, user_a)
    await _save_byok_key(session_factory, user_a)

    resp = await client.post(
        CREATE_PATH.format(conversation.id),
        headers=_session(user_a),
        json={"content": "xin chao"},
    )

    assert resp.status_code == 202, resp.text
    # "lượt sinh phải thật sự mở ra"; `title` là của T-S.7 (câu đầu).
    assert [name for name, _ in fake_arq.pushed] == ["generate", "title"]


async def test_byok_body_has_no_quota_warning(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    quota_redis: Any,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """Thanh cảnh báo UC-07 nói về quota **hệ thống** — hiện nó ở đây là nói sai.

    Cùng trạng thái ZSET với `test_low_quota_202_with_warning_in_body`
    (còn 15%), nhưng lượt này không trừ quota nên không có gì để cảnh báo.
    """
    conversation = await _conversation(session_factory, user_a)
    window = Window(LimitType.SHORT, settings.QUOTA_WINDOW_SHORT_S)
    quota_redis.zset[window.key(user_a)] = {
        encode_member(uuid.uuid4(), Decimal("0.425")): time.time() - 60
    }
    await _save_byok_key(session_factory, user_a)

    resp = await client.post(
        CREATE_PATH.format(conversation.id),
        headers=_session(user_a),
        json={"content": "xin chao"},
    )

    assert resp.status_code == 202, resp.text
    assert resp.json()["quota_warning"] is None


async def test_byok_does_not_read_quota_ZSET(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    quota_redis: Any,
    _db_for_tests: None,
    fake_arq: FakeArq,
) -> None:
    """Bỏ qua HẲN cửa chặn, không phải "ước tính rồi tha".

    Một `read_window` chỉ để vứt đi là một lần `503` không đáng có mỗi khi
    Redis chớp — cho một lượt mà quota không có quyền chặn.
    """
    conversation = await _conversation(session_factory, user_a)
    await _save_byok_key(session_factory, user_a)
    quota_redis.zset.clear()
    before = len(quota_redis.zset)

    resp = await client.post(
        CREATE_PATH.format(conversation.id),
        headers=_session(user_a),
        json={"content": "xin chao"},
    )

    assert resp.status_code == 202, resp.text
    assert len(quota_redis.zset) == before, "không cửa sổ nào được đụng tới"
