"""T-2.9 — §10.6 gắn vào đâu trong `api/v1` (hai lớp theo user).

Tên file là `..._routes` chứ không trùng `tests/core/test_ratelimit.py`: `tests/`
không có `__init__.py`, nên hai file cùng basename là một lỗi collect của pytest
("import file mismatch") — đo được ngay khi thử.

`tests/core/test_ratelimit.py` kiểm *cơ chế*; file này kiểm *chỗ gắn*, và đó
là hai kiểu hỏng khác nhau. Một token bucket đúng từng con số mà quên gắn vào
`retry` thì hạn mức 20/phút chỉ là 20/phút cho một trong ba đường tốn tiền —
và không phép kiểm nào ở tầng `core/` thấy được điều đó.

Ba câu file này trả lời:

1. **Ba route SINH CHỮ** (`POST .../messages`, `retry`, `PATCH /messages/{id}`)
   đi qua token bucket; `cancel`/`siblings`/`stream` thì **không** (chúng không
   tốn tiền, và chặn `cancel` nghĩa là một lượt sinh đang chảy không ai dừng
   được nữa — cùng lý lẽ `require_chat_access` của T-2.7).
2. **`GET /messages/{id}/stream` không đếm ghế** — NQ-49, chỗ dễ đọc nhầm nhất
   của B-85.
3. Bị chặn ở **cả hai** lớp đều để lại **0 hàng** trong `messages` và **0** job
   trong hàng đợi: phép kiểm nằm trong transaction, nên ném là rollback.

`ratelimit_redis` (autouse, `tests/api/conftest.py`) mặc định trả lời "cho
qua"; mỗi test ở đây tự đặt kịch bản của mình.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import catalog
from app.config.settings import settings
from app.core import ratelimit
from app.core.crypto import mask_secret, seal
from app.core.errors import ApiErrorCode
from app.db.models import Conversation, Message, MessageRole, MessageStatus
from app.db.repositories import ConversationRepository, MessageRepository, ProviderKeyRepository
from app.main import app

#: Kiểu thật là `FakeRateLimitRedis` của `tests/api/conftest.py`, nhưng `tests/`
#: không phải package nên `from tests.api.conftest import …` không chạy (cùng
#: lý do fixture `event_hooks` tồn tại thay cho một hằng import được).
FakeRateLimitRedis = Any

DUONG_DAN_TAO = "/api/v1/conversations/{}/messages"
DUONG_DAN_RETRY = "/api/v1/messages/{}/retry"
DUONG_DAN_SUA = "/api/v1/messages/{}"
DUONG_DAN_HUY = "/api/v1/messages/{}/cancel"
DUONG_DAN_ANH_EM = "/api/v1/messages/{}/siblings"
DUONG_DAN_STREAM = "/api/v1/messages/{}/stream"

#: `[allowed, remaining, retry_after_ms, reset_ms]` — xô đã cạn.
XO_CAN = [0, 0, 3000, 60000]
#: `[cho_phep, dang_chay]` — đã đủ ghế.
HET_GHE = [0, settings.MAX_CONCURRENT_STREAMS]


class _RedisCoHuy:
    """Chỉ đúng một lệnh mà `POST /messages/{id}/cancel` dùng (§7.5)."""

    async def set(self, name: str, value: str, *, ex: int | None = None) -> bool:
        return True


class _ArqGia:
    def __init__(self) -> None:
        self.da_day: list[tuple[str, tuple[Any, ...]]] = []
        self.no_ra = False

    async def enqueue_job(self, ten: str, *args: Any, **_: Any) -> object:
        if self.no_ra:
            raise ConnectionError("redis chet giua chung (gia lap)")
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
async def arq_gia(monkeypatch: pytest.MonkeyPatch) -> _ArqGia:
    gia = _ArqGia()

    async def _pool() -> _ArqGia:
        return gia

    monkeypatch.setattr("app.api.v1.messages.get_arq_pool", _pool)
    return gia


@pytest_asyncio.fixture
async def client(event_hooks: dict[str, Any]) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://localhost", event_hooks=event_hooks
    ) as http:
        yield http


async def _hoi_thoai_co_luot_sinh(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> tuple[Conversation, Message, Message]:
    """Một hội thoại với một câu hỏi và một câu trả lời đã `completed`."""
    async with session_factory() as session:
        conversations = ConversationRepository(session)
        messages = MessageRepository(session)
        conversation = await conversations.create_conversation(user_id=user_id)
        cau_hoi = await messages.create_message(
            conversation_id=conversation.id,
            user_id=user_id,
            role=MessageRole.USER,
            content="viet ham sort",
        )
        tra_loi = await messages.create_message(
            conversation_id=conversation.id,
            user_id=user_id,
            role=MessageRole.ASSISTANT,
            parent_id=cau_hoi.id,
            status=MessageStatus.COMPLETED,
            content="xong",
        )
        await session.commit()
        return conversation, cau_hoi, tra_loi


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


def _cac_script(redis: FakeRateLimitRedis) -> list[str]:
    return [ten for ten, _ in redis.calls]


# ═════════════ ba route sinh chữ đi qua token bucket, ba route kia thì không ═


@pytest.mark.usefixtures("_debug_bat", "_db_cua_test", "arq_gia")
async def test_tao_message_bi_chan_boi_token_bucket(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    ratelimit_redis: FakeRateLimitRedis,
    arq_gia: _ArqGia,
) -> None:
    """DoD dòng 1, nhìn từ tầng route: hết token ⇒ `429` + `Retry-After`."""
    conversation, _, _ = await _hoi_thoai_co_luot_sinh(session_factory, user_a)
    truoc = await _dem_message(session_factory, conversation.id)
    ratelimit_redis.bucket = XO_CAN

    resp = await client.post(
        DUONG_DAN_TAO.format(conversation.id),
        headers={"X-User-Id": str(user_a)},
        json={"content": "xin chao"},
    )

    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == ApiErrorCode.RATE_LIMITED
    assert resp.headers["retry-after"] == "3"
    assert await _dem_message(session_factory, conversation.id) == truoc
    assert arq_gia.da_day == []


@pytest.mark.usefixtures("_debug_bat", "_db_cua_test", "arq_gia")
async def test_retry_bi_chan_boi_token_bucket(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    ratelimit_redis: FakeRateLimitRedis,
) -> None:
    _, _, tra_loi = await _hoi_thoai_co_luot_sinh(session_factory, user_a)
    ratelimit_redis.bucket = XO_CAN

    resp = await client.post(DUONG_DAN_RETRY.format(tra_loi.id), headers={"X-User-Id": str(user_a)})

    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == ApiErrorCode.RATE_LIMITED


@pytest.mark.usefixtures("_debug_bat", "_db_cua_test", "arq_gia")
async def test_sua_cau_hoi_bi_chan_boi_token_bucket(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    ratelimit_redis: FakeRateLimitRedis,
) -> None:
    _, cau_hoi, _ = await _hoi_thoai_co_luot_sinh(session_factory, user_a)
    ratelimit_redis.bucket = XO_CAN

    resp = await client.patch(
        DUONG_DAN_SUA.format(cau_hoi.id),
        headers={"X-User-Id": str(user_a)},
        json={"content": "hoi lai"},
    )

    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == ApiErrorCode.RATE_LIMITED


@pytest.mark.usefixtures("_debug_bat", "_db_cua_test")
async def test_cancel_khong_di_qua_han_muc_nao(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    ratelimit_redis: FakeRateLimitRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chặn nút Dừng nghĩa là một lượt sinh đang chảy không ai dừng được nữa —
    và nó cũng không tốn đồng nào (cùng lý lẽ T-2.7 không gắn
    `require_chat_access` cho `cancel`)."""
    _, _, tra_loi = await _hoi_thoai_co_luot_sinh(session_factory, user_a)
    ratelimit_redis.bucket = XO_CAN
    ratelimit_redis.slot = HET_GHE
    # Cờ huỷ `cancel:{id}` đi qua một Redis KHÁC (`app.api.v1.messages.get_redis`)
    # — giữ hai đường riêng để phép đếm script bên dưới không lẫn.
    monkeypatch.setattr("app.api.v1.messages.get_redis", lambda: _RedisCoHuy())

    resp = await client.post(DUONG_DAN_HUY.format(tra_loi.id), headers={"X-User-Id": str(user_a)})

    assert resp.status_code == 200
    assert _cac_script(ratelimit_redis) == []


@pytest.mark.usefixtures("_debug_bat", "_db_cua_test")
async def test_siblings_khong_di_qua_han_muc_nao(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    ratelimit_redis: FakeRateLimitRedis,
) -> None:
    _, _, tra_loi = await _hoi_thoai_co_luot_sinh(session_factory, user_a)
    ratelimit_redis.bucket = XO_CAN

    resp = await client.get(DUONG_DAN_ANH_EM.format(tra_loi.id), headers={"X-User-Id": str(user_a)})

    assert resp.status_code == 200
    assert _cac_script(ratelimit_redis) == []


@pytest.mark.usefixtures("_debug_bat", "_db_cua_test")
async def test_stream_khong_dem_ghe_va_khong_ton_token(
    client: AsyncClient,
    user_a: uuid.UUID,
    ratelimit_redis: FakeRateLimitRedis,
) -> None:
    """NQ-49 — chỗ dễ đọc nhầm nhất của B-85.

    Đếm kết nối SSE sẽ chặn tab thứ tư của cùng một hội thoại, tức chặn đúng
    thứ ADR-01 (không consumer group, hai tab cùng đọc được) và UC-03 (F5 giữa
    lúc đang stream) dựng ra. Trần của §10.6 đếm **lượt sinh**, không đếm tab.

    Dùng một `message_id` không tồn tại: `404` xảy ra trước khi có byte nào của
    stream, nên test không phải dựng Redis Stream — mà `404` vẫn chứng minh
    điều cần chứng minh, vì hạn mức là *dependency*, chạy trước handler.
    """
    resp = await client.get(
        DUONG_DAN_STREAM.format(uuid.uuid4()), headers={"X-User-Id": str(user_a)}
    )

    assert resp.status_code == 404
    assert _cac_script(ratelimit_redis) == [], "không xô, không ghế"


# ═══════════════════ trần đồng thời (§10.6 hàng 4, B-85, NQ-49) ═════════════


@pytest.mark.usefixtures("_debug_bat", "_db_cua_test")
async def test_het_ghe_tra_429_TOO_MANY_STREAMS_va_khong_ghi_hang_nao(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    ratelimit_redis: FakeRateLimitRedis,
    arq_gia: _ArqGia,
) -> None:
    """DoD dòng 3. Và phần quan trọng hơn con số `429`: phép kiểm nằm **trong**
    transaction, nên một lượt bị từ chối không để lại message mồ côi nào."""
    conversation, _, _ = await _hoi_thoai_co_luot_sinh(session_factory, user_a)
    truoc = await _dem_message(session_factory, conversation.id)
    ratelimit_redis.slot = HET_GHE

    resp = await client.post(
        DUONG_DAN_TAO.format(conversation.id),
        headers={"X-User-Id": str(user_a)},
        json={"content": "cau hoi thu tu"},
    )

    assert resp.status_code == 429
    loi = resp.json()["error"]
    assert loi["code"] == ApiErrorCode.TOO_MANY_STREAMS
    assert loi["details"] == {
        "limit": settings.MAX_CONCURRENT_STREAMS,
        "active": settings.MAX_CONCURRENT_STREAMS,
    }
    assert "retry-after" not in resp.headers, "không ai biết model sinh xong lúc nào"
    assert await _dem_message(session_factory, conversation.id) == truoc
    assert arq_gia.da_day == []


@pytest.mark.usefixtures("_debug_bat", "_db_cua_test")
async def test_ghe_giu_TRUOC_khi_day_job(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    ratelimit_redis: FakeRateLimitRedis,
    arq_gia: _ArqGia,
) -> None:
    """Thứ tự là hợp đồng: giữ ghế xong mới đẩy job. Đảo lại thì một lượt bị
    từ chối vẫn có job trong hàng đợi, và worker vẫn sinh chữ, vẫn tính tiền."""
    conversation, _, _ = await _hoi_thoai_co_luot_sinh(session_factory, user_a)
    ratelimit_redis.slot = HET_GHE

    await client.post(
        DUONG_DAN_TAO.format(conversation.id),
        headers={"X-User-Id": str(user_a)},
        json={"content": "xin chao"},
    )

    assert "slot" in _cac_script(ratelimit_redis)
    assert arq_gia.da_day == []


@pytest.mark.usefixtures("_debug_bat", "_db_cua_test")
async def test_day_job_that_bai_thi_NHA_ghe_ngay(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    ratelimit_redis: FakeRateLimitRedis,
    arq_gia: _ArqGia,
) -> None:
    """Transaction sắp rollback ⇒ hàng `messages` mang id đó sẽ không tồn tại.

    Không nhả ngay thì đó là một ghế trỏ vào hư không, và phép đối chiếu
    Postgres phải đợi hết `PHANTOM_GRACE_S` mới dọn được — 60 giây trong đó
    người dùng mất một phần ba hạn mức của mình vì một sự cố của Redis.
    """
    conversation, _, _ = await _hoi_thoai_co_luot_sinh(session_factory, user_a)
    arq_gia.no_ra = True

    resp = await client.post(
        DUONG_DAN_TAO.format(conversation.id),
        headers={"X-User-Id": str(user_a)},
        json={"content": "xin chao"},
    )

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == ApiErrorCode.ENQUEUE_FAILED
    assert len(ratelimit_redis.da_nha) == 1
    khoa, _ = ratelimit_redis.da_nha[0]
    assert khoa == ratelimit.stream_slot_key(user_a)


@pytest.mark.usefixtures("_debug_bat", "_db_cua_test", "arq_gia")
async def test_duong_chay_dung_co_du_ba_header_ratelimit(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    ratelimit_redis: FakeRateLimitRedis,
) -> None:
    """§10.6 đòi `X-RateLimit-*` chứ không chỉ `Retry-After`: FE cần biết mình
    sắp hết hạn mức TRƯỚC khi hết."""
    conversation, _, _ = await _hoi_thoai_co_luot_sinh(session_factory, user_a)
    ratelimit_redis.bucket = [1, 17, 0, 9000]

    resp = await client.post(
        DUONG_DAN_TAO.format(conversation.id),
        headers={"X-User-Id": str(user_a)},
        json={"content": "xin chao"},
    )

    assert resp.status_code == 202
    assert resp.headers[ratelimit.HEADER_LIMIT] == str(settings.RATE_LIMIT_CHAT_PER_MIN)
    assert resp.headers[ratelimit.HEADER_REMAINING] == "17"
    assert resp.headers[ratelimit.HEADER_RESET] == "9"
    assert ratelimit.HEADER_RETRY_AFTER not in resp.headers


@pytest.mark.usefixtures("_debug_bat", "_db_cua_test", "arq_gia")
async def test_ghe_cap_cho_dung_message_assistant_vua_tao(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    ratelimit_redis: FakeRateLimitRedis,
) -> None:
    """Member của ZSET phải là `assistant_message_id` — đó là thứ duy nhất
    Postgres trả lời được câu "còn đang sinh không". Cấp ghế cho một token
    ngẫu nhiên thì phép đối chiếu mất luôn điểm tựa."""
    conversation, _, _ = await _hoi_thoai_co_luot_sinh(session_factory, user_a)

    resp = await client.post(
        DUONG_DAN_TAO.format(conversation.id),
        headers={"X-User-Id": str(user_a)},
        json={"content": "xin chao"},
    )

    assert resp.status_code == 202
    ten, argv = next(goi for goi in ratelimit_redis.calls if goi[0] == "slot")
    assert ten == "slot"
    assert argv[0] == ratelimit.stream_slot_key(user_a)
    assert argv[4] == resp.json()["assistant_message_id"]


# ═══════ BYOK không mua được quyền miễn rate limit (§10.5, T-2.15) ═══════


@pytest.mark.usefixtures("_debug_bat", "_db_cua_test", "arq_gia")
async def test_byok_van_bi_token_bucket_chan(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    ratelimit_redis: FakeRateLimitRedis,
    arq_gia: _ArqGia,
) -> None:
    """**DoD dòng 4 của T-2.15.** §10.5 hàng "Rate limit": *"Vẫn áp dụng"*.

    Quota giới hạn **tiền của người vận hành**, rate limit giới hạn **tần
    suất** (§10.6) — hai thứ khác nhau, và BYOK chỉ mua được miễn thứ nhất.
    Người dùng BYOK vẫn dùng worker, vẫn chiếm kết nối Postgres/Redis, vẫn
    gửi được 1000 request/phút nếu không ai chặn.

    Lớp chặn là một **dependency** của route (`_ROUTE_SINH_CHU`), tức nó chạy
    xong trước khi handler biết BYOK tồn tại — nên tính chất này giữ được
    "miễn phí". Test canh đúng chiều đó: chuyển nó thành một phép kiểm bên
    trong `_mo_luot_sinh` là mở đường cho một nhánh `if byok: bo_qua`.
    """
    conversation, _, _ = await _hoi_thoai_co_luot_sinh(session_factory, user_a)
    model = catalog.get_default_model()
    assert model is not None
    khoa = "sk-" + "0123456789abcdef" * 2
    async with session_factory() as session:
        await ProviderKeyRepository(session).upsert(
            user_id=user_a,
            provider=model.provider,
            sealed=seal(khoa),
            masked=mask_secret(khoa),
            verified_at=None,
        )
        await session.commit()
    truoc = await _dem_message(session_factory, conversation.id)
    ratelimit_redis.bucket = XO_CAN

    resp = await client.post(
        DUONG_DAN_TAO.format(conversation.id),
        headers={"X-User-Id": str(user_a)},
        json={"content": "xin chao"},
    )

    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == ApiErrorCode.RATE_LIMITED
    assert resp.headers["retry-after"] == "3"
    assert await _dem_message(session_factory, conversation.id) == truoc
    assert arq_gia.da_day == []
