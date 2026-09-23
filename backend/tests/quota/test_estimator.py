"""Cửa chặn TRƯỚC của §10.2: dự toán xấu nhất, `429`, và cảnh báo UC-07 — T-2.11.

Hai nửa, hai cách kiểm khác nhau:

* `estimate()` là **thuần tính toán** — không Redis, không Postgres. Phép nhân
  tiền của A7 kiểm được bằng số, không cần dựng request nào.
* `check_quota()` chạm Redis (giả) và Postgres (**thật**, NQ-17: hạn mức đến
  từ `tiers`/`users`, và JOIN đó là thứ một fake sẽ mô phỏng bằng đúng niềm
  tin của người viết test).

Phép đo "0 USD phát sinh" của S6 **không** nằm ở đây: nó cần cả stack và log
LiteLLM thật (DoD dòng 1, xem báo cáo T-2.11).
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
from app.core.errors import ApiError, ApiErrorCode
from app.db.models import MessageRole
from app.db.repositories import ConversationRepository, MessageRepository
from app.quota.estimator import check_quota, estimate, estimate_from_tokens
from app.quota.windows import LimitType, Window, encode_member

PRICED_MODEL = "deepseek-flash"
UNPRICED_MODEL = "nr-gemini-flash"


def _model(model_id: str) -> catalog.ModelEntry:
    model = catalog.get_model(model_id)
    assert model is not None, model_id
    return model


# ═══════════════════ phần thuần tính toán: est_max (§10.2) ══════════════════


def test_est_max_uses_max_output_not_question_length() -> None:
    """Cạm bẫy của task: ước tính lạc quan = một câu hỏi vượt hạn mức hàng chục lần."""
    model = _model(PRICED_MODEL)
    pricing = catalog.get_catalog().effective_pricing(model.id)
    assert pricing is not None

    est = estimate_from_tokens(model, 1000)

    expected = (
        Decimal(1000) * Decimal(str(pricing.input_per_1m))
        + Decimal(model.max_output) * Decimal(str(pricing.output_per_1m))
    ) / Decimal(1_000_000)
    assert est.est_max_usd == expected
    assert est.max_output_tokens == model.max_output


def test_output_dominates_estimate_of_short_question() -> None:
    """Phép kiểm ngược của test trên: bỏ `max_output` thì con số tụt hàng chục lần."""
    model = _model(PRICED_MODEL)
    prompt_only = estimate_from_tokens(model, 1000).est_max_usd
    pricing = catalog.get_catalog().effective_pricing(model.id)
    assert pricing is not None
    prompt_only_cost = Decimal(1000) * Decimal(str(pricing.input_per_1m)) / Decimal(1_000_000)
    assert prompt_only > prompt_only_cost * 10


def test_unpriced_model_gives_0_and_priced_false() -> None:
    """B-65/NQ-52: không có ngoại lệ nào, chỉ là giá bằng `None` ⇒ `est_max` = 0."""
    est = estimate_from_tokens(_model(UNPRICED_MODEL), 5000)
    assert est.est_max_usd == Decimal(0)
    assert est.priced is False


def test_prompt_overhead_added_to_est_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """~2000 token 9Router bơm vào mọi request (B-65) phải vào dự toán."""
    model = _model(PRICED_MODEL)
    without_surcharge = estimate_from_tokens(model, 1000)
    monkeypatch.setattr(catalog.Catalog, "prompt_overhead_tokens", lambda self, mid: 2000)
    with_surcharge = estimate_from_tokens(model, 1000)

    assert with_surcharge.est_in_tokens == without_surcharge.est_in_tokens + 2000
    assert with_surcharge.est_max_usd > without_surcharge.est_max_usd


def test_estimate_counts_system_prompt_and_message_framing() -> None:
    model = _model(PRICED_MODEL)
    est = estimate(model, [{"role": "user", "content": "xin chao"}])
    assert est.est_in_tokens > 0
    assert est.model_id == model.id


# ═════════════════════ cửa chặn: 429, retry_after, cảnh báo ═════════════════


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
            model_id=PRICED_MODEL,
        )
        await session.commit()
        return answer.id


@pytest.fixture
def _quota_redis(monkeypatch: pytest.MonkeyPatch, quota_redis_fake: Any) -> Any:
    """Cùng bản vá mà `tests/api/conftest.py` gắn autouse, nhưng cho bộ test này."""
    monkeypatch.setattr("app.quota.estimator.get_redis", lambda: quota_redis_fake)
    monkeypatch.setattr("app.quota.tiers.get_redis", lambda: quota_redis_fake)
    return quota_redis_fake


@pytest.fixture
def _db_for_tests(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


def _load_spend(redis: Any, user_id: uuid.UUID, *item: tuple[float, str]) -> None:
    for window in (Window(LimitType.SHORT, settings.QUOTA_WINDOW_SHORT_S),):
        redis.zset[window.key(user_id)] = {
            encode_member(uuid.uuid4(), Decimal(cost)): score for score, cost in item
        }


async def test_nothing_spent_passes_without_warning(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_for_tests: None,
) -> None:
    leaf = await _single_turn_tree(session_factory, user_a)
    async with session_factory() as session:
        warning = await check_quota(
            session, user_id=user_a, leaf_id=leaf, model=_model(PRICED_MODEL)
        )
    assert warning is None


async def test_exhausted_5h_limit_429_with_limit_type_and_retry_after(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_for_tests: None,
) -> None:
    """UC-07 dòng 3 + DoD dòng 2 và 3."""
    leaf = await _single_turn_tree(session_factory, user_a)
    # Tier `free` có `limit_5h_usd = 0.50`; nạp 0.50 là đã chạm trần.
    now = time.time()
    _load_spend(_quota_redis, user_a, (now - 17000, "0.50"))

    async with session_factory() as session:
        with pytest.raises(ApiError) as exc:
            await check_quota(session, user_id=user_a, leaf_id=leaf, model=_model(PRICED_MODEL))

    err = exc.value
    assert err.status_code == 429
    assert err.code is ApiErrorCode.QUOTA_EXCEEDED
    assert err.details["limit_type"] == "5h"
    # Phần tử duy nhất rơi khỏi cửa sổ 18000 s sau 1000 s nữa (±1 s làm tròn).
    assert 999 <= err.details["retry_after"] <= 1001
    assert err.headers is not None and err.headers["Retry-After"] == str(err.details["retry_after"])


async def test_exhausted_weekly_limit_has_limit_type_weekly(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_for_tests: None,
) -> None:
    """DoD dòng 3: body phân biệt được `5h` với `weekly`."""
    leaf = await _single_turn_tree(session_factory, user_a)
    now = time.time()
    # Cửa sổ 5 giờ rỗng, cửa sổ tuần đã tiêu hết 3.00 USD của tier `free`.
    window = Window(LimitType.LONG, settings.QUOTA_WINDOW_LONG_S)
    _quota_redis.zset[window.key(user_a)] = {
        encode_member(uuid.uuid4(), Decimal("3.00")): now - 600000
    }

    async with session_factory() as session:
        with pytest.raises(ApiError) as exc:
            await check_quota(session, user_id=user_a, leaf_id=leaf, model=_model(PRICED_MODEL))
    assert exc.value.details["limit_type"] == "weekly"


async def test_single_turn_over_cap_has_none_retry_after(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_for_tests: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ca của DoD dòng 1 (`limit_5h_usd = 0.001`): nhả cả cửa sổ cũng không đủ."""
    leaf = await _single_turn_tree(session_factory, user_a)
    async with session_factory() as session:
        await session.execute(
            text(
                "UPDATE users SET limit_override_json = '{\"limit_5h_usd\": 0.001}'::jsonb "
                "WHERE id = :uid"
            ),
            {"uid": user_a},
        )
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(ApiError) as exc:
            await check_quota(session, user_id=user_a, leaf_id=leaf, model=_model(PRICED_MODEL))

    assert exc.value.details["retry_after"] is None
    # KHÔNG đặt `Retry-After`: không có con số thật nào để đặt.
    assert not (exc.value.headers or {}).get("Retry-After")


async def test_unpriced_model_passes_even_with_0_limit(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_for_tests: None,
) -> None:
    """B-65/NQ-52 nhìn từ phía cửa chặn: không có giá ⇒ không có gì để trừ."""
    leaf = await _single_turn_tree(session_factory, user_a)
    async with session_factory() as session:
        await session.execute(
            text(
                "UPDATE users SET limit_override_json = "
                '\'{"limit_5h_usd": 0, "limit_7d_usd": 0}\'::jsonb WHERE id = :uid'
            ),
            {"uid": user_a},
        )
        await session.commit()

    async with session_factory() as session:
        warning = await check_quota(
            session, user_id=user_a, leaf_id=leaf, model=_model(UNPRICED_MODEL)
        )
    assert warning is None


async def test_15_percent_left_passes_with_warning(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_for_tests: None,
) -> None:
    """DoD dòng 4 + UC-07 dòng 1. Tier `free`: 0.50 USD/5 h ⇒ tiêu 0.425 là còn 15%."""
    leaf = await _single_turn_tree(session_factory, user_a)
    _load_spend(_quota_redis, user_a, (time.time() - 60, "0.425"))

    async with session_factory() as session:
        warning = await check_quota(
            session, user_id=user_a, leaf_id=leaf, model=_model(UNPRICED_MODEL)
        )

    assert warning is not None
    assert warning.limit_type is LimitType.SHORT
    assert warning.remaining_pct == 15
    assert warning.spent_usd == Decimal("0.425")
    assert warning.remaining_usd == Decimal("0.075")


async def test_warning_threshold_read_from_settings(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_for_tests: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A3: 20% là cấu hình, không phải một số ma trong `estimator.py`."""
    leaf = await _single_turn_tree(session_factory, user_a)
    _load_spend(_quota_redis, user_a, (time.time() - 60, "0.425"))
    monkeypatch.setattr(settings, "QUOTA_WARN_REMAINING_PCT", 10)

    async with session_factory() as session:
        warning = await check_quota(
            session, user_id=user_a, leaf_id=leaf, model=_model(UNPRICED_MODEL)
        )
    assert warning is None


async def test_dead_redis_is_503_not_let_through(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_for_tests: None,
) -> None:
    """Không hỏi được Redis = không biết còn bao nhiêu tiền. Cho qua là gỡ P2."""
    leaf = await _single_turn_tree(session_factory, user_a)
    _quota_redis.fail = True

    async with session_factory() as session:
        with pytest.raises(ApiError) as exc:
            await check_quota(session, user_id=user_a, leaf_id=leaf, model=_model(PRICED_MODEL))
    assert exc.value.status_code == 503


async def test_unbuildable_context_estimates_from_budget_cap(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_for_tests: None,
) -> None:
    """Không ước tính được **không** được đọc thành "không tốn gì".

    Đo bằng hai chiều dưới **cùng một** hạn mức, vì một chiều không chứng minh
    được gì: hạn mức 0.015 USD nằm giữa dự toán của một câu hỏi thật (~0.005–
    0.010 USD tuỳ khung giờ của `deepseek-flash`) và dự toán theo trần ngân
    sách §9.6 (118 808 token ⇒ ~0.023–0.045 USD). Lá có thật đi qua; lá không
    tồn tại — tức `context.build()` ném và đường lùi chạy — bị chặn.
    """
    leaf = await _single_turn_tree(session_factory, user_a)
    async with session_factory() as session:
        await session.execute(
            text(
                "UPDATE users SET limit_override_json = '{\"limit_5h_usd\": 0.015}'::jsonb "
                "WHERE id = :uid"
            ),
            {"uid": user_a},
        )
        await session.commit()

    async with session_factory() as session:
        assert (
            await check_quota(session, user_id=user_a, leaf_id=leaf, model=_model(PRICED_MODEL))
            is None
        )

    async with session_factory() as session:
        with pytest.raises(ApiError) as exc:
            await check_quota(
                session, user_id=user_a, leaf_id=uuid.uuid4(), model=_model(PRICED_MODEL)
            )
    assert exc.value.code is ApiErrorCode.QUOTA_EXCEEDED
