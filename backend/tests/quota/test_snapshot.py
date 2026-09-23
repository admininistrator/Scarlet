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
UNPRICED_MODEL = "nr-gemini-flash"


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
def _db_for_tests(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


def _load_5h_window(redis: Any, user_id: uuid.UUID, *item: tuple[float, str]) -> None:
    window = Window(LimitType.SHORT, settings.QUOTA_WINDOW_SHORT_S)
    redis.zset[window.key(user_id)] = {
        encode_member(uuid.uuid4(), Decimal(cost)): score for score, cost in item
    }


async def _single_turn_tree(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> uuid.UUID:
    """Một hội thoại + câu hỏi + một assistant `queued`. Trả `leaf_id` của nó."""
    async with session_factory() as session:
        conversation = await ConversationRepository(session).create_conversation(user_id=user_id)
        messages = MessageRepository(session)
        question = await messages.create_message(
            conversation_id=conversation.id,
            user_id=user_id,
            role=MessageRole.USER,
            parent_id=None,
            content="mot cau hoi ngan",
        )
        answer = await messages.create_message(
            conversation_id=conversation.id,
            user_id=user_id,
            role=MessageRole.ASSISTANT,
            parent_id=question.id,
            model_id=UNPRICED_MODEL,
        )
        await session.commit()
        return answer.id


# ═════════════════════════ hình dạng: hai cửa sổ ════════════════════════════


async def test_returns_both_windows_in_10_3_order(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_for_tests: None,
) -> None:
    async with session_factory() as session:
        out = await read_snapshot(session, user_id=user_a)

    assert out is not None
    assert [w.limit_type for w in out] == [LimitType.SHORT, LimitType.LONG]


async def test_nothing_spent_full_limit_and_no_retry_after(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_for_tests: None,
) -> None:
    limits = await get_effective_limits(user_a)

    async with session_factory() as session:
        out = await read_snapshot(session, user_id=user_a)

    assert out is not None
    short = out[0]
    assert short.spent_usd == Decimal(0)
    assert short.limit_usd == limits.limit_5h_usd
    assert short.remaining_usd == limits.limit_5h_usd
    assert short.remaining_pct == 100
    assert short.retry_after is None


async def test_overspending_leaves_0_not_negative(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_for_tests: None,
) -> None:
    """Một số âm đúng về số học nhưng vô nghĩa với một thanh tiến trình, và FE
    sẽ phải tự kẹp lại — tức luật kẹp sống ở hai nơi."""
    now = time.time()
    # Tier `free` có `limit_5h_usd = 0.50`; nạp gấp đôi.
    _load_5h_window(_quota_redis, user_a, (now - 1000, "1.00"))

    async with session_factory() as session:
        out = await read_snapshot(session, user_id=user_a)

    assert out is not None
    assert out[0].spent_usd == Decimal("1.00")
    assert out[0].remaining_usd == Decimal(0)
    assert out[0].remaining_pct == 0


async def test_percent_rounds_DOWN(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_for_tests: None,
) -> None:
    """Con số hiển thị không bao giờ được lạc quan hơn sự thật (luật của
    `QuotaWarning`, chép lại ở đây vì nó là cùng một thanh)."""
    now = time.time()
    # `free`: 0.50 − 0.4015 = 0.0985 còn lại ⇒ 19.7% ⇒ phải hiện **19**.
    _load_5h_window(_quota_redis, user_a, (now - 1000, "0.4015"))

    async with session_factory() as session:
        out = await read_snapshot(session, user_id=user_a)

    assert out is not None
    assert out[0].remaining_pct == 19


# ═══════════ retry_after: CÙNG một phép tính với `Retry-After` của 429 ══════


async def test_retry_after_matches_429_retry_after_to_the_second(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_for_tests: None,
) -> None:
    """Đây là dòng DoD thứ hai của T-3.0, đo trong một tiến trình thay vì hai.

    Với một model **không có giá** thì `est_max == 0`, nên hai công thức của
    §10.3 trùng nhau đúng từng số hạng:

        429:      need_to_free = spent + est_max − limit
        /auth/me: need_to_free = spent − limit

    Sai số duy nhất còn lại là `now` của hai lần gọi, tức dưới một giây.
    """
    leaf = await _single_turn_tree(session_factory, user_a)
    now = time.time()
    # Vượt trần 0.50 của tier `free` bằng hai phần tử, để `retry_after` phải
    # đi qua phép cộng dồn chứ không rơi vào ca "phần tử đầu tiên là đủ".
    _load_5h_window(_quota_redis, user_a, (now - 17000, "0.40"), (now - 16000, "0.30"))

    async with session_factory() as session:
        out = await read_snapshot(session, user_id=user_a)
        with pytest.raises(ApiError) as exc:
            await check_quota(session, user_id=user_a, leaf_id=leaf, model=_model(UNPRICED_MODEL))

    assert out is not None
    from_me = out[0].retry_after
    from_429 = exc.value.details["retry_after"]
    assert from_me is not None and from_429 is not None
    assert abs(from_me - from_429) <= 1
    assert exc.value.headers is not None
    assert exc.value.headers["Retry-After"] == str(from_429)


async def test_over_cap_ALWAYS_has_a_number_unlike_429(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_for_tests: None,
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
    _load_5h_window(_quota_redis, user_a, (now - 1000, "1.00"))
    async with session_factory() as session:
        await session.execute(text("UPDATE tiers SET limit_5h_usd = 0 WHERE name = 'free'"))
        await session.commit()
        out = await read_snapshot(session, user_id=user_a)

    assert out is not None
    # Phần tử duy nhất vào cửa sổ 1000 s trước ⇒ rơi ra sau 18000 − 1000 s nữa.
    assert out[0].retry_after is not None
    assert abs(out[0].retry_after - (settings.QUOTA_WINDOW_SHORT_S - 1000)) <= 1


# ═════════════════ Redis chết ⇒ `None`, KHÔNG phải một ngoại lệ ═════════════


async def test_dead_redis_returns_none_not_raise(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_for_tests: None,
) -> None:
    """Khác hẳn `check_quota`, nơi cùng sự cố ấy phải thành `503` — xem
    docstring của `app/quota/snapshot.py`."""
    await get_effective_limits(user_a)  # nạp cache tier trước khi Redis "chết"
    _quota_redis.fail = True

    async with session_factory() as session:
        out = await read_snapshot(session, user_id=user_a)

    assert out is None
