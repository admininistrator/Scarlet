"""Dựng lại ZSET quota từ `usage_events` — RR-7, §10.3 (T-2.13).

Postgres **thật** (NQ-17), Redis **giả**. Phép chia ấy không phải sự lười:

* Thứ cần kiểm ở đây là *một dòng sổ trong Postgres có thành đúng một member
  với đúng `score` hay không*, mà `created_at` là `timestamptz` do Postgres
  sinh và `cost_usd` là `NUMERIC(12,6)` do Postgres cắt — hai thứ chỉ Postgres
  trả lời đúng được.
* `FakeQuotaRedis` mô phỏng thật bốn lệnh ZSET (xem docstring của nó ở
  `tests/conftest.py`), trong đó có đúng tính chất mà file này dựa vào: member
  trùng thì **ghi đè** chứ không nhân đôi.

DoD dòng 1 (`redis-cli FLUSHDB` → gọi API → quota đúng như trước khi flush) có
mặt ở hai chỗ: bản tự động dưới đây đi qua `check_quota` với một Redis vừa bị
xoá sạch, và bản đo trên stack thật nằm ở `scripts/test_rebuild_quota.sh` +
báo cáo task. DoD dòng 3 (10k dòng dưới 2 giây) đo trên stack thật, nhưng thứ
làm nên con số ấy — `ZADD` theo lô — có một phép kiểm riêng ở đây.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import cli
from app.config import catalog
from app.config.settings import settings
from app.core.errors import ApiError, ApiErrorCode
from app.db.models import CostConfidence, KeySource, MessageRole, UsagePurpose
from app.db.repositories import (
    ConversationRepository,
    MessageRepository,
    UsageEventRepository,
)
from app.quota.estimator import check_quota
from app.quota.rebuild import (
    ZADD_BATCH,
    cutoff_at,
    rebuild_all,
    rebuild_quota,
    refill_if_empty,
)
from app.quota.windows import (
    LimitType,
    Window,
    encode_member,
    parse_member,
    read_window,
    windows,
)

#: `metered`, có giá niêm yết — cùng model mà `test_estimator.py` dùng.
PRICED_MODEL = "deepseek-flash"

#: Vài mốc tuổi, tính bằng giây, đặt tên để mỗi test nói được nó đang kiểm ca
#: nào. `QUOTA_WINDOW_SHORT_S` mặc định 18000 (5 giờ), `LONG` 604800 (7 ngày).
INSIDE_5H = 3600
OUTSIDE_5H_INSIDE_WEEK = 6 * 3600
OUTSIDE_BOTH = 8 * 24 * 3600


def _model(model_id: str = PRICED_MODEL) -> catalog.ModelEntry:
    model = catalog.get_model(model_id)
    assert model is not None, model_id
    return model


async def _write_ledger(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    cost: str,
    age_seconds: float = 0.0,
    key_source: KeySource = KeySource.SYSTEM,
    purpose: UsagePurpose = UsagePurpose.CHAT,
) -> uuid.UUID:
    """Một dòng `usage_events` có tuổi cho trước. Trả `id` của nó.

    Ghi qua `UsageEventRepository.record` — đường ghi **thật** của T-2.12 —
    rồi mới lùi `created_at` bằng một `UPDATE` riêng. Hai bước chứ không phải
    một tham số `created_at` trong repository: cột đó do Postgres sinh
    (`server_default now()`), và mở một cửa cho phép chọn nó là mở đúng cánh
    cửa mà A7 đóng. Lùi giờ trong test thì khác — nó không phải một đường đi
    của app, và nó hiện rõ ở đây thành hai dòng.
    """
    event = await UsageEventRepository(session).record(
        user_id=user_id,
        message_id=None,
        model_id=PRICED_MODEL,
        provider="deepseek",
        key_source=key_source,
        prompt_tokens=100,
        completion_tokens=10,
        cached_tokens=0,
        cost_usd=Decimal(cost),
        cost_confidence=CostConfidence.EXACT,
        price_snapshot={"source": "catalog"},
        purpose=purpose,
    )
    if age_seconds:
        await session.execute(
            text(
                "UPDATE usage_events SET created_at = now() - make_interval(secs => :t) "
                "WHERE id = :id"
            ),
            {"t": age_seconds, "id": event.id},
        )
    await session.flush()
    return event.id


def _zset(redis: Any, limit_type: LimitType, user_id: uuid.UUID) -> dict[str, float]:
    seconds = (
        settings.QUOTA_WINDOW_SHORT_S
        if limit_type is LimitType.SHORT
        else settings.QUOTA_WINDOW_LONG_S
    )
    return redis.zset.get(Window(limit_type, seconds).key(user_id), {})


def _total(redis: Any, limit_type: LimitType, user_id: uuid.UUID) -> Decimal:
    return sum(
        (parse_member(m) or Decimal(0) for m in _zset(redis, limit_type, user_id)),
        Decimal(0),
    )


# ═══════════════════ rebuild_quota: trong và ngoài cửa sổ ═══════════════════


async def test_rebuild_from_empty_redis_matches_postgres_amount(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    """Ca chính của RR-7: Redis trắng, Postgres có sổ ⇒ ZSET quay lại như cũ."""
    await _write_ledger(session, user_a, cost="0.120000", age_seconds=INSIDE_5H)
    await _write_ledger(session, user_a, cost="0.030000", age_seconds=INSIDE_5H * 2)

    report = await rebuild_quota(session, quota_redis_fake, user_id=user_a, now=time.time())

    assert report.members == 4  # hai dòng × hai cửa sổ
    assert _total(quota_redis_fake, LimitType.SHORT, user_a) == Decimal("0.150000")
    assert _total(quota_redis_fake, LimitType.LONG, user_a) == Decimal("0.150000")


async def test_row_outside_5h_window_only_enters_weekly(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    """DoD dòng 2 — "dữ liệu nằm trong và ngoài cửa sổ", vế thứ nhất."""
    await _write_ledger(session, user_a, cost="0.100000", age_seconds=INSIDE_5H)
    await _write_ledger(session, user_a, cost="0.200000", age_seconds=OUTSIDE_5H_INSIDE_WEEK)

    await rebuild_quota(session, quota_redis_fake, user_id=user_a, now=time.time())

    assert len(_zset(quota_redis_fake, LimitType.SHORT, user_a)) == 1
    assert _total(quota_redis_fake, LimitType.SHORT, user_a) == Decimal("0.100000")
    assert len(_zset(quota_redis_fake, LimitType.LONG, user_a)) == 2
    assert _total(quota_redis_fake, LimitType.LONG, user_a) == Decimal("0.300000")


async def test_row_outside_both_windows_goes_nowhere(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    """DoD dòng 2 — vế thứ hai. Tiền của tuần trước KHÔNG được sống lại."""
    await _write_ledger(session, user_a, cost="9.000000", age_seconds=OUTSIDE_BOTH)

    report = await rebuild_quota(session, quota_redis_fake, user_id=user_a, now=time.time())

    assert report.members == 0
    # Và không tạo khoá rỗng: một khoá rỗng khác một khoá không tồn tại ở đúng
    # phép đo `--scan --pattern 'quota:*'` của DoD T-2.12.
    assert quota_redis_fake.zset == {}
    assert quota_redis_fake.ttl_calls == []


async def test_score_is_created_at_not_now(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    """Chỗ mà "một truy vấn `SUM`" của §10.3 không làm được.

    Nạp bằng `score = now` thì khoản tiêu 4 giờ trước được gia hạn thêm 5 giờ
    nữa — người dùng bị phạt hai lần cho cùng một khoản. Phép kiểm: dựng lại
    rồi đọc cửa sổ ở một `now` **tương lai**, chỗ mà dòng ấy phải đã rơi ra.
    """
    four_hours = 4 * 3600
    await _write_ledger(session, user_a, cost="0.400000", age_seconds=four_hours)
    now = time.time()
    await rebuild_quota(session, quota_redis_fake, user_id=user_a, now=now)

    short_window, _ = windows()
    right_now = await read_window(quota_redis_fake, short_window, user_id=user_a, now=now)
    assert right_now.spent == Decimal("0.400000")

    # 1 giờ 1 phút nữa là dòng ấy tròn 5 giờ 1 phút tuổi ⇒ ngoài cửa sổ.
    later = now + 3660
    dropped_out = await read_window(quota_redis_fake, short_window, user_id=user_a, now=later)
    assert dropped_out.spent == Decimal(0)


async def test_member_count_equals_row_count_not_just_total(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    """Bất biến mà DoD T-2.12 dòng 5 đo, giữ nguyên sau khi dựng lại.

    Ba dòng **cùng giá** là ca duy nhất phân biệt được hai cách đọc §10.3:
    member mang `usage_id` thì ra ba, member chỉ mang `<cost>` (chữ của §10.2)
    thì ba dòng đè lên nhau còn một, và tổng tiền tụt xuống một phần ba.
    """
    for _ in range(3):
        await _write_ledger(session, user_a, cost="0.010000", age_seconds=INSIDE_5H)

    await rebuild_quota(session, quota_redis_fake, user_id=user_a, now=time.time())

    assert len(_zset(quota_redis_fake, LimitType.SHORT, user_a)) == 3
    assert _total(quota_redis_fake, LimitType.SHORT, user_a) == Decimal("0.030000")


async def test_rebuilding_twice_gives_same_result(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    """Không `DEL` thì phép này phải không đổi — nếu không, mỗi lần chạy là một
    lần nhân đôi hoá đơn."""
    await _write_ledger(session, user_a, cost="0.070000", age_seconds=INSIDE_5H)
    now = time.time()

    await rebuild_quota(session, quota_redis_fake, user_id=user_a, now=now)
    first_time = dict(_zset(quota_redis_fake, LimitType.SHORT, user_a))
    await rebuild_quota(session, quota_redis_fake, user_id=user_a, now=now)

    assert _zset(quota_redis_fake, LimitType.SHORT, user_a) == first_time
    assert _total(quota_redis_fake, LimitType.SHORT, user_a) == Decimal("0.070000")


async def test_does_not_delete_member_of_concurrently_billed_generation(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    """Vì sao hàm này HỢP chứ không THAY — xem docstring `quota/rebuild.py`.

    Mô phỏng khe giữa "chụp ảnh Postgres" và "ghi vào Redis": worker khép sổ
    một lượt sinh mà ảnh chụp chưa thấy. Một bản `DEL` + `ZADD` sẽ nuốt mất
    khoản ấy, và dòng `usage_events` của nó thì vẫn nằm trong Postgres.
    """
    await _write_ledger(session, user_a, cost="0.050000", age_seconds=INSIDE_5H)
    now = time.time()
    short_window, _ = windows()
    worker_member = encode_member(uuid.uuid4(), Decimal("0.020000"))
    quota_redis_fake.zset[short_window.key(user_a)] = {worker_member: now}

    await rebuild_quota(session, quota_redis_fake, user_id=user_a, now=now)

    assert worker_member in _zset(quota_redis_fake, LimitType.SHORT, user_a)
    assert _total(quota_redis_fake, LimitType.SHORT, user_a) == Decimal("0.070000")


async def test_each_window_ttl_equals_its_own_length(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    """Cùng luật với `add_to_windows` (nửa (b) của B-156).

    Không có nó thì một khoá dựng lại cho người đã ngừng chat nằm lại vô thời
    hạn — đúng thứ B-156 mở ra để sửa.
    """
    await _write_ledger(session, user_a, cost="0.010000", age_seconds=INSIDE_5H)
    await rebuild_quota(session, quota_redis_fake, user_id=user_a, now=time.time())

    short_window, long_window = windows()
    assert quota_redis_fake.ttl_calls == [
        (short_window.key(user_a), settings.QUOTA_WINDOW_SHORT_S),
        (long_window.key(user_a), settings.QUOTA_WINDOW_LONG_S),
    ]


async def test_loads_in_batches_not_one_command_per_row(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    """Thứ đứng sau DoD dòng 3 (10k dòng < 2 s), đo được mà không cần 10k dòng.

    `ZADD_BATCH + 1` dòng là con số nhỏ nhất chứng minh được phép chia lô: một
    lệnh đầy và một lệnh lẻ cho mỗi cửa sổ. Một bản hiện thực "một `ZADD` mỗi
    dòng" sẽ cho `2 × (ZADD_BATCH + 1)` lệnh và vẫn **đúng** — nó chỉ chậm,
    tức đúng loại hỏng mà không phép kiểm nào khác nhìn thấy.
    """
    row_count = ZADD_BATCH + 1
    repo = UsageEventRepository(session)
    for _ in range(row_count):
        await repo.record(
            user_id=user_a,
            message_id=None,
            model_id=PRICED_MODEL,
            provider="deepseek",
            key_source=KeySource.SYSTEM,
            prompt_tokens=1,
            completion_tokens=1,
            cached_tokens=0,
            cost_usd=Decimal("0.000001"),
            cost_confidence=CostConfidence.EXACT,
            price_snapshot={"source": "catalog"},
            purpose=UsagePurpose.CHAT,
        )
    await session.flush()

    await rebuild_quota(session, quota_redis_fake, user_id=user_a, now=time.time())

    command = [so for _, so in quota_redis_fake.written]
    assert command == [ZADD_BATCH, 1, ZADD_BATCH, 1]
    assert len(_zset(quota_redis_fake, LimitType.SHORT, user_a)) == row_count


async def test_rebuilds_only_for_that_user(
    session: AsyncSession, user_a: uuid.UUID, user_b: uuid.UUID, quota_redis_fake: Any
) -> None:
    """§20 — phép lọc `user_id` nằm trong câu SQL, và đây là chỗ nó được đo."""
    await _write_ledger(session, user_a, cost="0.100000", age_seconds=INSIDE_5H)
    await _write_ledger(session, user_b, cost="0.900000", age_seconds=INSIDE_5H)

    await rebuild_quota(session, quota_redis_fake, user_id=user_a, now=time.time())

    assert _total(quota_redis_fake, LimitType.SHORT, user_a) == Decimal("0.100000")
    assert _zset(quota_redis_fake, LimitType.SHORT, user_b) == {}


def test_window_bounds_are_timezone_aware_datetimes() -> None:
    """NQ-50 ⑦ cùng bài học: một `datetime` trần đi vào `timestamptz` là một
    phép so sánh do driver đoán hộ."""
    short_window, _ = windows()
    bound = cutoff_at(short_window, time.time())
    assert bound.tzinfo is not None
    assert bound.utcoffset() == datetime.now(UTC).utcoffset()


# ═══════════════════ refill_if_empty: tự gọi khi phát hiện lệch ═════════════


async def test_empty_window_with_postgres_spend_self_rebuilds(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    await _write_ledger(session, user_a, cost="0.250000", age_seconds=INSIDE_5H)
    now = time.time()
    short_window, _ = windows()

    before = await read_window(quota_redis_fake, short_window, user_id=user_a, now=now)
    assert before.spent == Decimal(0)

    after = await refill_if_empty(session, quota_redis_fake, before, user_id=user_a, now=now)
    assert after.spent == Decimal("0.250000")
    assert len(after.entries) == 1


async def test_empty_window_and_empty_postgres_write_nothing(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    """Ca thường của một người dùng mới — nó không được tốn một lệnh ghi nào."""
    now = time.time()
    short_window, _ = windows()
    before = await read_window(quota_redis_fake, short_window, user_id=user_a, now=now)

    after = await refill_if_empty(session, quota_redis_fake, before, user_id=user_a, now=now)

    assert after is before
    assert quota_redis_fake.written == []
    assert quota_redis_fake.zset == {}


async def test_window_with_data_does_not_ask_postgres(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    """Đường nóng: ZSET có dữ liệu ⇒ không một lượt dựng lại nào.

    Postgres ở đây có một dòng sổ **khác** với thứ đang nằm trong ZSET, và đó
    là chỗ phép kiểm có răng: một bản hiện thực bỏ mất cửa `if state.entries`
    sẽ nạp thêm 0.05 vào một cửa sổ đang đúng, tức cộng hai lần cùng một lượt
    chi tiêu vào đúng con số chặn người dùng.

    *(Bản đầu của phép kiểm này cho Postgres rỗng, và nó **xanh** với cả bản
    hiện thực bỏ cửa ấy — không có gì để nạp thì không có gì để thấy.)*
    """
    now = time.time()
    short_window, _ = windows()
    await _write_ledger(session, user_a, cost="0.050000", age_seconds=INSIDE_5H)
    quota_redis_fake.zset[short_window.key(user_a)] = {
        encode_member(uuid.uuid4(), Decimal("0.300000")): now - 60
    }
    before = await read_window(quota_redis_fake, short_window, user_id=user_a, now=now)

    after = await refill_if_empty(session, quota_redis_fake, before, user_id=user_a, now=now)

    assert after is before
    assert after.spent == Decimal("0.300000")
    assert quota_redis_fake.written == []


async def test_money_outside_window_does_not_trigger_rebuild(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    """Vế "trong cửa sổ" của điều kiện, đo riêng.

    Một người tiêu tiền 6 giờ trước có cửa sổ 5 giờ **đúng là** rỗng. Dựng lại
    ở đó là ghi đè một câu trả lời đúng bằng chính nó, mỗi request một lần.
    """
    await _write_ledger(session, user_a, cost="0.500000", age_seconds=OUTSIDE_5H_INSIDE_WEEK)
    now = time.time()
    short_window, _ = windows()
    before = await read_window(quota_redis_fake, short_window, user_id=user_a, now=now)

    after = await refill_if_empty(session, quota_redis_fake, before, user_id=user_a, now=now)

    assert after is before
    assert quota_redis_fake.written == []


# ═════════════════ qua check_quota: bản pytest của DoD dòng 1 ═══════════════


@pytest.fixture
def _quota_redis(monkeypatch: pytest.MonkeyPatch, quota_redis_fake: Any) -> Any:
    monkeypatch.setattr("app.quota.estimator.get_redis", lambda: quota_redis_fake)
    monkeypatch.setattr("app.quota.tiers.get_redis", lambda: quota_redis_fake)
    return quota_redis_fake


@pytest.fixture
def _db_for_tests(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


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


async def test_wiped_redis_gate_still_sees_spent_money(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_for_tests: None,
) -> None:
    """DoD dòng 1 ở dạng tự động: `FLUSHDB` rồi gọi API ⇒ quota KHÔNG về 0.

    Tier `free` có `limit_5h_usd = 0.50`. Người này đã tiêu 0.50 theo sổ cái,
    nên cửa chặn phải trả `429` — mà nó chỉ làm được thế nếu đã tự dựng lại
    ZSET từ Postgres. Không có `refill_if_empty` thì request này đi qua, và đó
    đúng là câu "quota của mọi người reset" trong Cạm bẫy của T-2.13.
    """
    leaf = await _single_turn_tree(session_factory, user_a)
    async with session_factory() as record_statement:
        await _write_ledger(record_statement, user_a, cost="0.500000", age_seconds=INSIDE_5H)
        await record_statement.commit()

    # Redis trắng — đúng trạng thái sau `redis-cli FLUSHDB`.
    assert _quota_redis.zset == {}

    async with session_factory() as session:
        with pytest.raises(ApiError) as exc:
            await check_quota(session, user_id=user_a, leaf_id=leaf, model=_model())

    assert exc.value.status_code == 429
    assert exc.value.code is ApiErrorCode.QUOTA_EXCEEDED
    assert exc.value.details["limit_type"] == "5h"
    assert exc.value.details["spent_usd"] == "0.500000"
    # …và ZSET đã được nạp lại, nên request kế tiếp không phải hỏi Postgres nữa.
    assert _total(_quota_redis, LimitType.SHORT, user_a) == Decimal("0.500000")


async def test_postgres_dying_mid_rebuild_503_not_let_through(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_for_tests: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Không hỏi được Postgres ⇒ vẫn "không biết còn bao nhiêu tiền" ⇒ `503`.

    Cùng câu trả lời với ca Redis chết (NQ-53). Cho qua ở đây là gỡ lớp phòng
    thủ P2 vào đúng lúc cả hai kho đều không trả lời được.
    """
    leaf = await _single_turn_tree(session_factory, user_a)

    async def no(*_a: Any, **_k: Any) -> bool:
        raise RuntimeError("postgres chet (gia lap)")

    monkeypatch.setattr(
        "app.db.repositories.UsageEventRepository.has_events_since", no, raising=True
    )

    async with session_factory() as session:
        with pytest.raises(ApiError) as exc:
            await check_quota(session, user_id=user_a, leaf_id=leaf, model=_model())

    assert exc.value.status_code == 503
    assert exc.value.code is ApiErrorCode.SERVICE_UNAVAILABLE


# ══════════════════════ rebuild_all: lệnh CLI `--all` ═══════════════════════


async def test_rebuild_all_rebuilds_every_spender(
    session: AsyncSession, user_a: uuid.UUID, user_b: uuid.UUID, quota_redis_fake: Any
) -> None:
    await _write_ledger(session, user_a, cost="0.110000", age_seconds=INSIDE_5H)
    await _write_ledger(session, user_b, cost="0.220000", age_seconds=OUTSIDE_5H_INSIDE_WEEK)

    reports = await rebuild_all(session, quota_redis_fake, now=time.time())

    by_user = {r.user_id: r for r in reports}
    assert {user_a, user_b} <= set(by_user)
    assert _total(quota_redis_fake, LimitType.SHORT, user_a) == Decimal("0.110000")
    assert _total(quota_redis_fake, LimitType.LONG, user_b) == Decimal("0.220000")
    # `user_b` tiêu tiền ngoài cửa sổ 5 giờ ⇒ cửa sổ ấy vẫn phải rỗng.
    assert _zset(quota_redis_fake, LimitType.SHORT, user_b) == {}


async def test_rebuild_all_skips_users_without_ledger_rows(
    session: AsyncSession, user_a: uuid.UUID, user_b: uuid.UUID, quota_redis_fake: Any
) -> None:
    """Tập người đọc từ `usage_events`, không từ `users`."""
    await _write_ledger(session, user_a, cost="0.010000", age_seconds=INSIDE_5H)

    reports = await rebuild_all(session, quota_redis_fake, now=time.time())

    assert user_b not in {r.user_id for r in reports}


# ══════════════════════════ app/cli.py — vỏ lệnh ═══════════════════════════


def test_missing_all_flag_argparse_errors_not_runs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--all` là bắt buộc — xem docstring `app/cli.py`.

    Lỗi `argparse` (mã thoát 2) chứ không phải một lần chạy im lặng lên toàn
    bộ người dùng: lệnh này ghi vào Redis của tất cả mọi người, và "tôi lỡ
    gõ" phải dừng ở đây.
    """
    with pytest.raises(SystemExit) as exc:
        cli.main([cli.REBUILD_QUOTA])
    assert exc.value.code == 2
    assert "--all" in capsys.readouterr().err


def test_no_command_also_errors() -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == 2


async def test_rebuild_quota_all_command_reloads_zset_exit_0(
    user_a: uuid.UUID,
    quota_redis_fake: Any,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Thân lệnh, gọi thẳng — `main()` tự bọc nó trong `asyncio.run`.

    Gọi `main()` ở đây sẽ là một `asyncio.run` lồng trong vòng lặp của pytest.
    Thứ cần kiểm là thân lệnh có nối đúng ba mảnh hay không (session, Redis,
    `rebuild_all`), và nó nằm ở `_rebuild_quota_all`.
    """
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr("app.cli.get_redis", lambda: quota_redis_fake)
    async with session_factory() as record_statement:
        await _write_ledger(record_statement, user_a, cost="0.330000", age_seconds=INSIDE_5H)
        await record_statement.commit()

    exit_code = await cli._rebuild_quota_all()

    assert exit_code == 0
    assert _total(quota_redis_fake, LimitType.SHORT, user_a) == Decimal("0.330000")
    assert str(user_a) in capsys.readouterr().out


# ════════ T-2.15 — dòng sổ BYOK KHÔNG được quay lại ZSET quota (§10.5) ════════
#
# Trước T-2.15 mọi dòng `usage_events` đều là `system`, nên ba câu đọc của
# `rebuild_quota` không cần lọc gì. Từ khi đường BYOK sống thật, **không lọc**
# nghĩa là §10.5 bị phá một nhịp sau: lúc ghi sổ thì đúng (không `ZADD`), rồi
# lần đầu tiên ZSET rỗng — `FLUSHDB`, `down -v`, hết TTL — `refill_if_empty`
# nạp khoản BYOK ấy vào như một khoản system.
#
# Ca này đo được trên stack thật ở DoD T-2.15 dòng 3 **trước** khi có bộ lọc:
# ZSET dựng lại ra 2 member, một trong đó là đúng khoản BYOK vừa tiêu.


async def test_BYOK_rows_stay_out_of_ZSET_on_rebuild(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    """`rebuild_quota` chỉ dựng lại phần tiền của NGƯỜI VẬN HÀNH."""
    await _write_ledger(session, user_a, cost="0.100000", age_seconds=INSIDE_5H)
    await _write_ledger(
        session, user_a, cost="0.900000", age_seconds=INSIDE_5H, key_source=KeySource.BYOK
    )
    await session.commit()

    await rebuild_quota(session, quota_redis_fake, user_id=user_a, now=time.time())

    assert _total(quota_redis_fake, LimitType.SHORT, user_a) == Decimal("0.100000")
    assert len(_zset(quota_redis_fake, LimitType.SHORT, user_a)) == 1
    assert _total(quota_redis_fake, LimitType.LONG, user_a) == Decimal("0.100000")


async def test_only_BYOK_rows_does_NOT_ASK_postgres_twice(
    session: AsyncSession,
    user_a: uuid.UUID,
    quota_redis_fake: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`has_events_since` cũng phải lọc, không chỉ `list_since` — và cái giá là SỐ CÂU SQL.

    Chỉ nhìn kết quả thì hai bản giống hệt nhau: `list_since` đã lọc rồi nên
    dù `has_events_since` nói "có tiền", lượt dựng lại vẫn nạp **không** dòng
    nào và ZSET vẫn rỗng. Thứ khác nhau là **cái giá**: mỗi request của một
    người dùng BYOK thuần sẽ kéo theo một lượt đọc cả cửa sổ để không ghi gì
    — đúng cái mà điều kiện hai vế của T-2.13 sinh ra để tránh (RR-7).

    Vì vậy phép kiểm đếm câu SQL, không đếm kết quả: bỏ bộ lọc khỏi
    `has_events_since` thì `list_since` bị gọi và test đỏ.
    """
    await _write_ledger(
        session, user_a, cost="0.900000", age_seconds=INSIDE_5H, key_source=KeySource.BYOK
    )
    await session.commit()
    state = await read_window(quota_redis_fake, windows()[0], user_id=user_a, now=time.time())
    full_window_reads = 0
    original = UsageEventRepository.list_since

    async def counting(self: UsageEventRepository, **kwargs: Any) -> Any:
        nonlocal full_window_reads
        full_window_reads += 1
        return await original(self, **kwargs)

    monkeypatch.setattr(UsageEventRepository, "list_since", counting)

    after = await refill_if_empty(session, quota_redis_fake, state, user_id=user_a, now=time.time())

    assert after.spent == Decimal(0)
    assert _zset(quota_redis_fake, LimitType.SHORT, user_a) == {}
    assert full_window_reads == 0, (
        "chỉ có tiền BYOK thì `has_events_since` phải nói KHÔNG, và lượt đọc cả "
        "cửa sổ không được xảy ra"
    )


async def test_rebuild_all_skips_byok_only_spenders(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    quota_redis_fake: Any,
) -> None:
    """`user_ids_since` là vế thứ ba — bỏ sót nó thì `--all` vẫn nạp nhầm."""
    async with session_factory() as record_statement:
        await _write_ledger(record_statement, user_a, cost="0.200000", age_seconds=INSIDE_5H)
        await _write_ledger(
            record_statement,
            user_b,
            cost="0.700000",
            age_seconds=INSIDE_5H,
            key_source=KeySource.BYOK,
        )
        await record_statement.commit()

    async with session_factory() as reader:
        rebuilt = await rebuild_all(reader, quota_redis_fake, now=time.time())

    assert [report.user_id for report in rebuilt] == [user_a]
    assert _zset(quota_redis_fake, LimitType.SHORT, user_b) == {}


# ══════ T-S.7 — lượt đặt tên (`purpose=title`) KHÔNG quay lại quota khi dựng ══════
#
# Cạm bẫy ① của T-S.7: `record_usage` bỏ `ZADD` cho dòng `title` thì quota hôm
# nay đúng, nhưng lần đầu Redis mất dữ liệu (§10.3) ba câu dưới đây đọc lại
# `usage_events` — thiếu bộ lọc `purpose=chat` là trừ oan mọi lượt đặt tên.
# Cùng ba vế với nhóm BYOK ở trên, và cùng lý do phải kiểm từng vế riêng.


async def test_TITLE_rows_stay_out_of_ZSET_on_rebuild(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    """`list_since` — `rebuild_quota` chỉ nạp lại dòng `chat`."""
    await _write_ledger(session, user_a, cost="0.100000", age_seconds=INSIDE_5H)
    await _write_ledger(
        session, user_a, cost="0.000300", age_seconds=INSIDE_5H, purpose=UsagePurpose.TITLE
    )
    await session.commit()

    report = await rebuild_quota(session, quota_redis_fake, user_id=user_a, now=time.time())

    assert _total(quota_redis_fake, LimitType.SHORT, user_a) == Decimal("0.100000")
    assert len(_zset(quota_redis_fake, LimitType.SHORT, user_a)) == 1
    assert _total(quota_redis_fake, LimitType.LONG, user_a) == Decimal("0.100000")
    assert report.members == 2, "moi cua so dung 1 member — dong title khong duoc nap"


async def test_only_TITLE_rows_does_NOT_ASK_postgres_twice(
    session: AsyncSession,
    user_a: uuid.UUID,
    quota_redis_fake: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`has_events_since` — người chỉ có lượt đặt tên thì cửa sổ rỗng là ĐÚNG."""
    await _write_ledger(
        session, user_a, cost="0.000300", age_seconds=INSIDE_5H, purpose=UsagePurpose.TITLE
    )
    await session.commit()
    state = await read_window(quota_redis_fake, windows()[0], user_id=user_a, now=time.time())
    full_window_reads = 0
    original = UsageEventRepository.list_since

    async def counting(self: UsageEventRepository, **kwargs: Any) -> Any:
        nonlocal full_window_reads
        full_window_reads += 1
        return await original(self, **kwargs)

    monkeypatch.setattr(UsageEventRepository, "list_since", counting)

    after = await refill_if_empty(session, quota_redis_fake, state, user_id=user_a, now=time.time())

    assert after.spent == Decimal(0)
    assert _zset(quota_redis_fake, LimitType.SHORT, user_a) == {}
    assert full_window_reads == 0


async def test_rebuild_all_skips_title_only_spenders(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    quota_redis_fake: Any,
) -> None:
    """`user_ids_since` — `rebuild-quota --all` không nạp ai chỉ vì một lượt đặt tên."""
    async with session_factory() as record_statement:
        await _write_ledger(record_statement, user_a, cost="0.200000", age_seconds=INSIDE_5H)
        await _write_ledger(
            record_statement,
            user_b,
            cost="0.000300",
            age_seconds=INSIDE_5H,
            purpose=UsagePurpose.TITLE,
        )
        await record_statement.commit()

    async with session_factory() as reader:
        rebuilt = await rebuild_all(reader, quota_redis_fake, now=time.time())

    assert [report.user_id for report in rebuilt] == [user_a]
    assert _zset(quota_redis_fake, LimitType.SHORT, user_b) == {}
