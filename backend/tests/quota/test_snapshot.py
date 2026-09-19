"""Bản chụp quota của `GET /auth/me` (§18.1, §10.3) — T-3.0, B-158.

Cùng hạ tầng `tests/quota/test_estimator.py`: Redis giả, Postgres **thật**
(NQ-17 — hạn mức đến từ JOIN `users`/`tiers`, thứ một fake sẽ mô phỏng bằng
đúng niềm tin của người viết test).

Điều bộ test này canh, và là lý do nó tồn tại: `retry_after` của `/auth/me` và
`Retry-After` của `429` phải là **cùng một phép tính** trên **cùng một dữ
liệu**. Hai con số ấy xuất hiện cạnh nhau trên màn hình người dùng (thanh quota
đếm ngược, rồi một lần bấm Gửi bị từ chối), nên lệch nhau là một thứ nhìn thấy
được.
"""

from __future__ import annotations

import time
import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import catalog
from app.config.settings import settings
from app.core.errors import ApiError
from app.db.models import MessageRole
from app.db.repositories import ConversationRepository, MessageRepository
from app.quota.estimator import check_quota
from app.quota.snapshot import read_snapshot
from app.quota.tiers import get_effective_limits
from app.quota.windows import LimitType, Window, encode_member

#: Model KHÔNG có giá (`pricing_mode: unmetered`, B-65) ⇒ `est_max_usd == 0`.
#: Chọn nó cho phép so `retry_after` của hai đường **bằng nhau tuyệt đối**: chỗ
#: duy nhất hai công thức lệch là số hạng `est_max`, và ở đây nó bằng 0. Một
#: model có giá vẫn so được nhưng chỉ so được "xấp xỉ", và một phép kiểm xấp xỉ
#: không chứng minh được rằng hai đường dùng chung một hàm.
MODEL_KHONG_GIA = "nr-gemini-flash"


def _model(model_id: str) -> catalog.ModelEntry:
    model = catalog.get_model(model_id)
    assert model is not None, model_id
    return model


@pytest.fixture
def _quota_redis(monkeypatch: pytest.MonkeyPatch, quota_redis_fake: Any) -> Any:
    monkeypatch.setattr("app.quota.estimator.get_redis", lambda: quota_redis_fake)
    monkeypatch.setattr("app.quota.tiers.get_redis", lambda: quota_redis_fake)
    monkeypatch.setattr("app.quota.snapshot.get_redis", lambda: quota_redis_fake)
    return quota_redis_fake


@pytest.fixture
def _db_cua_test(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


def _nap_cua_so_5h(redis: Any, user_id: uuid.UUID, *muc: tuple[float, str]) -> None:
    window = Window(LimitType.SHORT, settings.QUOTA_WINDOW_SHORT_S)
    redis.zset[window.key(user_id)] = {
        encode_member(uuid.uuid4(), Decimal(cost)): score for score, cost in muc
    }


async def _cay_mot_luot(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> uuid.UUID:
    """Một hội thoại + câu hỏi + một assistant `queued`. Trả `leaf_id` của nó."""
    async with session_factory() as session:
        conversation = await ConversationRepository(session).create_conversation(user_id=user_id)
        messages = MessageRepository(session)
        cau_hoi = await messages.create_message(
            conversation_id=conversation.id,
            user_id=user_id,
            role=MessageRole.USER,
            parent_id=None,
            content="mot cau hoi ngan",
        )
        tra_loi = await messages.create_message(
            conversation_id=conversation.id,
            user_id=user_id,
            role=MessageRole.ASSISTANT,
            parent_id=cau_hoi.id,
            model_id=MODEL_KHONG_GIA,
        )
        await session.commit()
        return tra_loi.id


# ═════════════════════════ hình dạng: hai cửa sổ ════════════════════════════


async def test_tra_du_hai_cua_so_dung_thu_tu_cua_10_3(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_cua_test: None,
) -> None:
    async with session_factory() as session:
        ra = await read_snapshot(session, user_id=user_a)

    assert ra is not None
    assert [w.limit_type for w in ra] == [LimitType.SHORT, LimitType.LONG]


async def test_chua_tieu_gi_thi_con_nguyen_han_muc_va_khong_co_retry_after(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_cua_test: None,
) -> None:
    limits = await get_effective_limits(user_a)

    async with session_factory() as session:
        ra = await read_snapshot(session, user_id=user_a)

    assert ra is not None
    ngan = ra[0]
    assert ngan.spent_usd == Decimal(0)
    assert ngan.limit_usd == limits.limit_5h_usd
    assert ngan.remaining_usd == limits.limit_5h_usd
    assert ngan.remaining_pct == 100
    assert ngan.retry_after is None


async def test_tieu_qua_tran_thi_con_lai_bang_0_chu_khong_am(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_cua_test: None,
) -> None:
    """Một số âm đúng về số học nhưng vô nghĩa với một thanh tiến trình, và FE
    sẽ phải tự kẹp lại — tức luật kẹp sống ở hai nơi."""
    now = time.time()
    # Tier `free` có `limit_5h_usd = 0.50`; nạp gấp đôi.
    _nap_cua_so_5h(_quota_redis, user_a, (now - 1000, "1.00"))

    async with session_factory() as session:
        ra = await read_snapshot(session, user_id=user_a)

    assert ra is not None
    assert ra[0].spent_usd == Decimal("1.00")
    assert ra[0].remaining_usd == Decimal(0)
    assert ra[0].remaining_pct == 0


async def test_phan_tram_lam_tron_XUONG(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_cua_test: None,
) -> None:
    """Con số hiển thị không bao giờ được lạc quan hơn sự thật (luật của
    `QuotaWarning`, chép lại ở đây vì nó là cùng một thanh)."""
    now = time.time()
    # `free`: 0.50 − 0.4015 = 0.0985 còn lại ⇒ 19.7% ⇒ phải hiện **19**.
    _nap_cua_so_5h(_quota_redis, user_a, (now - 1000, "0.4015"))

    async with session_factory() as session:
        ra = await read_snapshot(session, user_id=user_a)

    assert ra is not None
    assert ra[0].remaining_pct == 19


# ═══════════ retry_after: CÙNG một phép tính với `Retry-After` của 429 ══════


async def test_retry_after_khop_tung_giay_voi_retry_after_cua_429(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_cua_test: None,
) -> None:
    """Đây là dòng DoD thứ hai của T-3.0, đo trong một tiến trình thay vì hai.

    Với một model **không có giá** thì `est_max == 0`, nên hai công thức của
    §10.3 trùng nhau đúng từng số hạng:

        429:      need_to_free = spent + est_max − limit
        /auth/me: need_to_free = spent − limit

    Sai số duy nhất còn lại là `now` của hai lần gọi, tức dưới một giây.
    """
    leaf = await _cay_mot_luot(session_factory, user_a)
    now = time.time()
    # Vượt trần 0.50 của tier `free` bằng hai phần tử, để `retry_after` phải
    # đi qua phép cộng dồn chứ không rơi vào ca "phần tử đầu tiên là đủ".
    _nap_cua_so_5h(_quota_redis, user_a, (now - 17000, "0.40"), (now - 16000, "0.30"))

    async with session_factory() as session:
        ra = await read_snapshot(session, user_id=user_a)
        with pytest.raises(ApiError) as exc:
            await check_quota(session, user_id=user_a, leaf_id=leaf, model=_model(MODEL_KHONG_GIA))

    assert ra is not None
    tu_me = ra[0].retry_after
    tu_429 = exc.value.details["retry_after"]
    assert tu_me is not None and tu_429 is not None
    assert abs(tu_me - tu_429) <= 1
    assert exc.value.headers is not None
    assert exc.value.headers["Retry-After"] == str(tu_429)


async def test_da_vuot_tran_thi_LUON_co_mot_con_so_khac_han_429(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_cua_test: None,
) -> None:
    """Tính chất riêng của đường `/auth/me`, và nó khác `429` một cách có ích.

    `429` trả `retry_after: null` được — `need_to_free = spent + est_max −
    limit` có thể lớn hơn **cả** cửa sổ, tức nhả hết cũng không đủ cho lượt
    sinh đang xin. Ở đây thì `need_to_free = spent − limit ≤ spent`, mà tổng
    của cả cửa sổ **bằng** `spent`, nên phép cộng dồn luôn tới đích.

    Nói cách khác: hễ `/auth/me` báo hết quota thì nó luôn nói được lúc nào hết
    "hết". Hạ `limit_5h_usd` về 0 là ca cực đoan nhất còn nghĩ ra được, và nó
    vẫn có câu trả lời — đúng thời điểm phần tử cuối rơi khỏi cửa sổ.
    """
    now = time.time()
    _nap_cua_so_5h(_quota_redis, user_a, (now - 1000, "1.00"))
    async with session_factory() as session:
        await session.execute(text("UPDATE tiers SET limit_5h_usd = 0 WHERE name = 'free'"))
        await session.commit()
        ra = await read_snapshot(session, user_id=user_a)

    assert ra is not None
    # Phần tử duy nhất vào cửa sổ 1000 s trước ⇒ rơi ra sau 18000 − 1000 s nữa.
    assert ra[0].retry_after is not None
    assert abs(ra[0].retry_after - (settings.QUOTA_WINDOW_SHORT_S - 1000)) <= 1


# ═════════════════ Redis chết ⇒ `None`, KHÔNG phải một ngoại lệ ═════════════


async def test_redis_chet_tra_none_chu_khong_nem(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_cua_test: None,
) -> None:
    """Khác hẳn `check_quota`, nơi cùng sự cố ấy phải thành `503` — xem
    docstring của `app/quota/snapshot.py`."""
    await get_effective_limits(user_a)  # nạp cache tier trước khi Redis "chết"
    _quota_redis.fail = True

    async with session_factory() as session:
        ra = await read_snapshot(session, user_id=user_a)

    assert ra is None
