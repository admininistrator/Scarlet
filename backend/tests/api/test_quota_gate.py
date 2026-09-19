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
from app.core.crypto import mask_secret, seal
from app.db.models import Conversation, Message, MessageRole, MessageStatus
from app.db.repositories import ConversationRepository, MessageRepository, ProviderKeyRepository
from app.main import app
from app.quota.windows import LimitType, Window, encode_member

DUONG_DAN_TAO = "/api/v1/conversations/{}/messages"
DUONG_DAN_RETRY = "/api/v1/messages/{}/retry"
DUONG_DAN_SUA = "/api/v1/messages/{}"


class ArqGia:
    """Pool arq giả — ở đây chỉ để đếm: lượt bị chặn phải đẩy **0** job."""

    def __init__(self) -> None:
        self.da_day: list[tuple[str, tuple[Any, ...]]] = []

    async def enqueue_job(self, ten: str, *args: Any, **kwargs: Any) -> object:
        self.da_day.append((ten, args))
        return object()


@pytest.fixture
def _debug_bat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DEBUG", True)


@pytest.fixture
def _db_cua_test(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


@pytest_asyncio.fixture
async def arq_gia(monkeypatch: pytest.MonkeyPatch) -> ArqGia:
    gia = ArqGia()

    async def _pool() -> ArqGia:
        return gia

    monkeypatch.setattr("app.api.v1.messages.get_arq_pool", _pool)
    return gia


@pytest_asyncio.fixture
async def client(event_hooks: dict[str, Any]) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://localhost", event_hooks=event_hooks
    ) as http:
        yield http


async def _het_quota(
    session_factory: async_sessionmaker[AsyncSession], redis: Any, user_id: uuid.UUID
) -> None:
    """Nạp đúng hạn mức 5 giờ của tier `free` vào cửa sổ ⇒ lượt tiếp theo bị chặn."""
    window = Window(LimitType.SHORT, settings.QUOTA_WINDOW_SHORT_S)
    redis.zset[window.key(user_id)] = {
        encode_member(uuid.uuid4(), Decimal("0.50")): time.time() - 17000
    }


async def _hoi_thoai(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> Conversation:
    async with session_factory() as session:
        conversation = await ConversationRepository(session).create_conversation(user_id=user_id)
        await session.commit()
        return conversation


async def _cap_cau_hoi_tra_loi(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Hội thoại + một cặp hỏi/đáp đã xong — nguyên liệu cho `retry` và `PATCH`."""
    conversation = await _hoi_thoai(session_factory, user_id)
    async with session_factory() as session:
        messages = MessageRepository(session)
        cau_hoi = await messages.create_message(
            conversation_id=conversation.id,
            user_id=user_id,
            role=MessageRole.USER,
            parent_id=None,
            content="cau hoi cu",
        )
        tra_loi = await messages.create_message(
            conversation_id=conversation.id,
            user_id=user_id,
            role=MessageRole.ASSISTANT,
            parent_id=cau_hoi.id,
            content="cau tra loi cu",
            status=MessageStatus.COMPLETED,
        )
        await session.commit()
        return conversation.id, cau_hoi.id, tra_loi.id


async def _dem_message(
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


async def test_post_messages_bi_chan_khi_het_quota(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    quota_redis: Any,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """S6 nửa kiểm được trong pytest: `429`, 0 message mới, 0 job."""
    conversation = await _hoi_thoai(session_factory, user_a)
    await _het_quota(session_factory, quota_redis, user_a)

    resp = await client.post(
        DUONG_DAN_TAO.format(conversation.id),
        headers={"X-User-Id": str(user_a)},
        json={"content": "xin chao"},
    )

    assert resp.status_code == 429
    loi = resp.json()["error"]
    assert loi["code"] == "QUOTA_EXCEEDED"
    assert loi["details"]["limit_type"] == "5h"
    assert resp.headers["Retry-After"] == str(loi["details"]["retry_after"])

    assert await _dem_message(session_factory, conversation.id) == 0, "transaction phải rollback"
    assert arq_gia.da_day == [], "0 job ⇒ 0 USD (S6)"


async def test_retry_bi_chan_khi_het_quota(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    quota_redis: Any,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """Đường tốn tiền dễ quên nhất: bấm Retry không tạo message user nào."""
    conversation_id, _, tra_loi_id = await _cap_cau_hoi_tra_loi(session_factory, user_a)
    truoc = await _dem_message(session_factory, conversation_id)
    await _het_quota(session_factory, quota_redis, user_a)

    resp = await client.post(
        DUONG_DAN_RETRY.format(tra_loi_id), headers={"X-User-Id": str(user_a)}, json={}
    )

    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "QUOTA_EXCEEDED"
    assert await _dem_message(session_factory, conversation_id) == truoc
    assert arq_gia.da_day == []


async def test_patch_message_bi_chan_khi_het_quota(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    quota_redis: Any,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    conversation_id, cau_hoi_id, _ = await _cap_cau_hoi_tra_loi(session_factory, user_a)
    truoc = await _dem_message(session_factory, conversation_id)
    await _het_quota(session_factory, quota_redis, user_a)

    resp = await client.patch(
        DUONG_DAN_SUA.format(cau_hoi_id),
        headers={"X-User-Id": str(user_a)},
        json={"content": "cau hoi da sua"},
    )

    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "QUOTA_EXCEEDED"
    assert await _dem_message(session_factory, conversation_id) == truoc
    assert arq_gia.da_day == []


# ═══════════════════════ cảnh báo UC-07 trong body ════════════════════════


async def test_con_it_quota_thi_202_kem_canh_bao_trong_body(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    quota_redis: Any,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """DoD dòng 4: còn 15% quota ⇒ request VẪN QUA, response có cảnh báo."""
    conversation = await _hoi_thoai(session_factory, user_a)
    window = Window(LimitType.SHORT, settings.QUOTA_WINDOW_SHORT_S)
    quota_redis.zset[window.key(user_a)] = {
        encode_member(uuid.uuid4(), Decimal("0.425")): time.time() - 60
    }

    resp = await client.post(
        DUONG_DAN_TAO.format(conversation.id),
        headers={"X-User-Id": str(user_a)},
        # Model không có giá ⇒ dự toán 0 ⇒ 0.425 + 0 < 0.50, đi qua. Test này
        # đo CẢNH BÁO, không đo cửa chặn.
        json={"content": "xin chao", "model_id": "nr-gemini-flash"},
    )

    assert resp.status_code == 202
    canh_bao = resp.json()["quota_warning"]
    assert canh_bao is not None
    assert canh_bao["limit_type"] == "5h"
    assert canh_bao["remaining_pct"] == 15
    assert Decimal(canh_bao["remaining_usd"]) == Decimal("0.075")
    assert len(arq_gia.da_day) == 1, "cảnh báo KHÔNG được chặn (UC-07 dòng 1)"


async def test_con_nhieu_quota_thi_khong_co_canh_bao(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    quota_redis: Any,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    conversation = await _hoi_thoai(session_factory, user_a)
    resp = await client.post(
        DUONG_DAN_TAO.format(conversation.id),
        headers={"X-User-Id": str(user_a)},
        json={"content": "xin chao"},
    )
    assert resp.status_code == 202
    assert resp.json()["quota_warning"] is None


async def test_han_muc_rieng_cua_user_duoc_ton_trong(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    quota_redis: Any,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """DoD dòng 1 chạy đúng bằng đường này: `limit_5h_usd = 0.001` cho một user."""
    conversation = await _hoi_thoai(session_factory, user_a)
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
        DUONG_DAN_TAO.format(conversation.id),
        headers={"X-User-Id": str(user_a)},
        json={"content": "xin chao"},
    )

    assert resp.status_code == 429
    loi = resp.json()["error"]
    assert loi["details"]["retry_after"] is None, "cửa sổ rỗng ⇒ không có gì để hẹn"
    assert "Retry-After" not in resp.headers
    assert await _dem_message(session_factory, conversation.id) == 0
    assert arq_gia.da_day == []


async def test_bi_chan_thi_KHONG_nhan_ghe_sinh(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    quota_redis: Any,
    ratelimit_redis: Any,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """Thứ tự trong `_mo_luot_sinh` là hợp đồng: quota TRƯỚC, ghế SAU.

    Ghế bận chỉ được nhả bằng phép đối chiếu Postgres sau `PHANTOM_GRACE_S`
    (60 s), nên nhận ghế rồi mới từ chối vì quota là khoá một trong ba ghế của
    người dùng suốt một phút — cho một lượt sinh chưa từng tồn tại. Đảo hai
    dòng ấy không làm test nào khác đỏ, nên phép kiểm phải nằm ở đây.
    """
    conversation = await _hoi_thoai(session_factory, user_a)
    await _het_quota(session_factory, quota_redis, user_a)

    resp = await client.post(
        DUONG_DAN_TAO.format(conversation.id),
        headers={"X-User-Id": str(user_a)},
        json={"content": "xin chao"},
    )

    assert resp.status_code == 429
    assert [ten for ten, _ in ratelimit_redis.calls] == ["bucket"], (
        "chỉ token bucket được chạy; script giữ ghế (`slot`) KHÔNG được chạm tới"
    )


# ═══════════ BYOK bỏ qua cửa quota, KHÔNG bỏ qua gì khác (§10.5, B-157) ═══════════
#
# §10.5 hàng "Quota": *"Request dùng BYOK **không** trừ quota, nhưng **vẫn**
# ghi `usage_events` với `key_source='byok'`"*, và hàng "Rate limit": *"Vẫn áp
# dụng"*. Ba test dưới đây đo đúng ba vế đó nhìn từ ngoài HTTP; vế ghi sổ nằm
# ở `tests/quota/test_meter.py` và `tests/workers/test_generate.py`.


async def _luu_khoa_byok(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> str:
    """Khoá BYOK cho provider của model MẶC ĐỊNH — đúng model mà request sẽ gọi."""
    model = catalog.get_default_model()
    assert model is not None
    khoa = "sk-" + "0123456789abcdef" * 2
    async with session_factory() as session:
        await ProviderKeyRepository(session).upsert(
            user_id=user_id,
            provider=model.provider,
            sealed=seal(khoa),
            masked=mask_secret(khoa),
            verified_at=None,
        )
        await session.commit()
    return model.provider


async def test_byok_van_chat_duoc_khi_het_quota_he_thong(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    quota_redis: Any,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """**DoD dòng 1 của T-2.15** (UC-07) ở mức HTTP: hết quota vẫn `202`.

    Cùng một người, cùng một hội thoại, cùng một cửa sổ quota đã đầy như
    `test_post_messages_bi_chan_khi_het_quota` — khác đúng một thứ: có khoá
    riêng. Gỡ nhánh `if key_source is KeySource.SYSTEM` ở `_mo_luot_sinh` ra
    thì test này thành `429`.
    """
    conversation = await _hoi_thoai(session_factory, user_a)
    await _het_quota(session_factory, quota_redis, user_a)
    await _luu_khoa_byok(session_factory, user_a)

    resp = await client.post(
        DUONG_DAN_TAO.format(conversation.id),
        headers={"X-User-Id": str(user_a)},
        json={"content": "xin chao"},
    )

    assert resp.status_code == 202, resp.text
    assert len(arq_gia.da_day) == 1, "lượt sinh phải thật sự mở ra"


async def test_byok_khong_kem_canh_bao_quota_trong_body(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    quota_redis: Any,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """Thanh cảnh báo UC-07 nói về quota **hệ thống** — hiện nó ở đây là nói sai.

    Cùng trạng thái ZSET với `test_con_it_quota_thi_202_kem_canh_bao_trong_body`
    (còn 15%), nhưng lượt này không trừ quota nên không có gì để cảnh báo.
    """
    conversation = await _hoi_thoai(session_factory, user_a)
    window = Window(LimitType.SHORT, settings.QUOTA_WINDOW_SHORT_S)
    quota_redis.zset[window.key(user_a)] = {
        encode_member(uuid.uuid4(), Decimal("0.425")): time.time() - 60
    }
    await _luu_khoa_byok(session_factory, user_a)

    resp = await client.post(
        DUONG_DAN_TAO.format(conversation.id),
        headers={"X-User-Id": str(user_a)},
        json={"content": "xin chao"},
    )

    assert resp.status_code == 202, resp.text
    assert resp.json()["quota_warning"] is None


async def test_byok_khong_doc_ZSET_quota(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    quota_redis: Any,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """Bỏ qua HẲN cửa chặn, không phải "ước tính rồi tha".

    Một `read_window` chỉ để vứt đi là một lần `503` không đáng có mỗi khi
    Redis chớp — cho một lượt mà quota không có quyền chặn.
    """
    conversation = await _hoi_thoai(session_factory, user_a)
    await _luu_khoa_byok(session_factory, user_a)
    quota_redis.zset.clear()
    truoc = len(quota_redis.zset)

    resp = await client.post(
        DUONG_DAN_TAO.format(conversation.id),
        headers={"X-User-Id": str(user_a)},
        json={"content": "xin chao"},
    )

    assert resp.status_code == 202, resp.text
    assert len(quota_redis.zset) == truoc, "không cửa sổ nào được đụng tới"
