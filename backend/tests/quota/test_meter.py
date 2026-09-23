"""Cửa SAU của §10.2: `cost_usd`, `price_snapshot`, `cost_confidence`, ZADD — T-2.12.

Ba nửa, ba cách kiểm khác nhau:

* `cost_of`/`measure`/`confidence_of`/`snapshot_of` là **thuần tính toán** —
  không Redis, không Postgres. Phép nhân tiền mà A7 đòi đúng tới 1e-6 kiểm
  được bằng số, không phải bằng một lượt sinh giả.
* `record_usage` chạm Postgres (**thật**, NQ-17 — `usage_events.cost_usd` là
  `NUMERIC(12,6)`, và chuyện một `Decimal` đi vòng qua đó rồi về có còn **đúng**
  con số hay không là chuyện chỉ Postgres trả lời được) và Redis (giả).
* Ba ngả khép sổ của worker nằm ở `tests/workers/test_generate.py`.

DoD dòng 5 — `SUM(cost_usd)` Postgres khớp tổng ZSET Redis ±0.000001 — có mặt
ở cả hai chỗ: dưới đây là bản tự động trên nhiều lượt, và bản đo trên stack
thật nằm trong báo cáo task.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import catalog
from app.db.models import CostConfidence, KeySource, UsageEvent
from app.llm.client import Usage
from app.quota.meter import (
    Spent,
    confidence_of,
    cost_of,
    measure,
    record_usage,
    snapshot_of,
)
from app.quota.windows import COST_DECIMALS, parse_member, windows

#: `metered`, có giá niêm yết, và **bán theo khung giờ** (B-35) — model duy
#: nhất trong catalog kiểm được cả A7 lẫn phép tách peak/off-peak.
MODEL_METERED = "deepseek-flash"
#: `unmetered`, đi qua 9Router, chưa ai điền `manual_pricing` (B-65) — ca
#: `cost_confidence='low'` của DoD dòng 3.
MODEL_9ROUTER = "nr-gemini-flash"
#: `metered`, có giá **ghi** cache riêng (Anthropic) — xem test snapshot.
MODEL_CACHE_WRITE = "claude-haiku"

#: Trong khung `deepseek-peak-vn` (thứ Sáu 09:00 giờ Việt Nam = 02:00 UTC).
PEAK_HOUR = datetime(2026, 9, 18, 2, 0, tzinfo=UTC)
#: Ngoài khung (thứ Sáu 22:00 giờ Việt Nam = 15:00 UTC).
OFF_PEAK_HOUR = datetime(2026, 9, 18, 15, 0, tzinfo=UTC)


def _model(model_id: str) -> catalog.ModelEntry:
    model = catalog.get_model(model_id)
    assert model is not None, model_id
    return model


def _rates(model_id: str, at: datetime | None = None) -> catalog.PricingRates:
    pricing = catalog.get_catalog().effective_pricing(model_id, at)
    assert pricing is not None, model_id
    return pricing


# ═════════════════ phần thuần tính toán: cost_of (§10.2, A7) ════════════════


def test_cache_hit_tokens_billed_at_cache_price_not_twice() -> None:
    """Lệch có chủ ý so với chữ §10.2 — xem docstring `quota/meter.py`.

    `cached_tokens` là **tập con** của `prompt_tokens`, nên phần trúng cache
    phải bị TRỪ khỏi phần tính giá cache-miss. Đọc thẳng công thức của §10.2
    (`in*in_price + cached*cached_price`) là tính hai lần.
    """
    pricing = _rates(MODEL_METERED, PEAK_HOUR)
    assert pricing.cached_input_per_1m is not None
    spent = Spent(prompt_tokens=1000, completion_tokens=0, cached_tokens=400, measured=True)

    expected = (
        Decimal(600) * Decimal(str(pricing.input_per_1m))
        + Decimal(400) * Decimal(str(pricing.cached_input_per_1m))
    ) / Decimal(1_000_000)
    assert cost_of(pricing, spent) == expected.quantize(Decimal("0.000001"))


def test_literal_10_2_reading_costs_far_more_than_correct_one() -> None:
    """Phép kiểm ngược của test trên: hai cách đọc lệch nhau bao nhiêu.

    Với `deepseek-flash` giờ cao điểm (0.30 miss / 0.006 hit) thì tính hai lần
    làm hoá đơn của phần prompt đắt lên **gấp nhiều lần**. Con số ấy phải nhìn
    thấy được trong test, nếu không thì lệch kế hoạch chỉ là một câu trong
    docstring.
    """
    pricing = _rates(MODEL_METERED, PEAK_HOUR)
    assert pricing.cached_input_per_1m is not None
    spent = Spent(prompt_tokens=1000, completion_tokens=0, cached_tokens=1000, measured=True)

    correct = cost_of(pricing, spent)
    per_plan_text = (
        Decimal(1000) * Decimal(str(pricing.input_per_1m))
        + Decimal(1000) * Decimal(str(pricing.cached_input_per_1m))
    ) / Decimal(1_000_000)
    assert correct < per_plan_text
    # 0.006 vs 0.30 + 0.006 — tức chữ của §10.2 đắt hơn 51 lần trên ca này.
    assert per_plan_text > correct * 50


def test_no_cache_price_bills_cache_hits_at_normal_price() -> None:
    """`cached_input_per_1m is None` = "provider KHÔNG bán cache", không phải 0 USD."""
    pricing = catalog.PricingRates(input_per_1m=1.0, output_per_1m=2.0, cached_input_per_1m=None)
    spent = Spent(prompt_tokens=1000, completion_tokens=0, cached_tokens=1000, measured=True)
    # 1000 token × 1.0 USD/1M, y như khi không trúng cache lần nào.
    assert cost_of(pricing, spent) == Decimal("0.001000")


def test_price_varies_by_window_which_is_why_snapshot_exists() -> None:
    """B-35 + A7: cùng số token, hai thời điểm, hai con số tiền."""
    spent = Spent(prompt_tokens=10_000, completion_tokens=1_000, cached_tokens=0, measured=True)
    peak = cost_of(_rates(MODEL_METERED, PEAK_HOUR), spent)
    off_peak = cost_of(_rates(MODEL_METERED, OFF_PEAK_HOUR), spent)
    assert peak == off_peak * 2  # bảng off-peak đúng bằng một nửa


def test_unpriced_model_is_0_usd_not_an_exception() -> None:
    """B-65: `manual_pricing` còn trống ⇒ model vẫn chạy, quota không trừ."""
    assert catalog.get_catalog().effective_pricing(MODEL_9ROUTER) is None
    spent = Spent(prompt_tokens=9_999, completion_tokens=9_999, cached_tokens=0, measured=True)
    assert cost_of(None, spent) == Decimal("0.000000")


def test_cost_usd_always_has_exactly_six_decimals() -> None:
    """Cùng độ chính xác với `NUMERIC(12,6)` và với `encode_member` — DoD dòng 5."""
    pricing = _rates(MODEL_METERED, PEAK_HOUR)
    spent = Spent(prompt_tokens=7, completion_tokens=3, cached_tokens=0, measured=True)
    assert cost_of(pricing, spent).as_tuple().exponent == -COST_DECIMALS


def test_provider_cached_above_prompt_yields_no_negative_charge() -> None:
    """Dữ liệu hỏng phải ra một con số vô hại, không phải một hoá đơn âm."""
    pricing = _rates(MODEL_METERED, PEAK_HOUR)
    spent = Spent(prompt_tokens=100, completion_tokens=0, cached_tokens=100_000, measured=True)
    assert cost_of(pricing, spent) >= 0


# ═════════════════ phần thuần tính toán: measure (C40, B-67, B-94) ══════════


def test_provider_usage_taken_verbatim() -> None:
    model = _model(MODEL_METERED)
    usage = Usage(
        prompt_tokens=214, completion_tokens=37, total_tokens=251, cached_prompt_tokens=64
    )
    spent = measure(
        model,
        usage=usage,
        sent=[{"role": "user", "content": "x"}],
        content="y",
        reasoning="",
        tool_calls=None,
    )
    assert spent == Spent(prompt_tokens=214, completion_tokens=37, cached_tokens=64, measured=True)


def test_provider_without_cached_counts_no_cache_hits() -> None:
    """NQ-23: khoá vắng mặt ≠ báo và bằng 0 — nhưng khi tính tiền thì đoán theo
    chiều **đắt**, không theo chiều rẻ."""
    model = _model(MODEL_METERED)
    usage = Usage(prompt_tokens=100, completion_tokens=5, total_tokens=105)
    assert usage.cached_prompt_tokens is None
    spent = measure(model, usage=usage, sent=[], content="", reasoning="", tool_calls=None)
    assert spent.cached_tokens == 0


def test_provider_without_usage_self_counts_and_marks_unmeasured() -> None:
    """Đường lùi C40 (B-67) và ca huỷ giữa chừng (B-94) — cùng một chỗ cắm."""
    model = _model(MODEL_METERED)
    spent = measure(
        model,
        usage=None,
        sent=[{"role": "user", "content": "Mùa thu Hà Nội thế nào?"}],
        content="Hà Nội mùa thu đẹp.",
        reasoning="",
        tool_calls=None,
    )
    assert spent.measured is False
    assert spent.prompt_tokens > 0
    assert spent.completion_tokens > 0


def test_reasoning_still_counts_as_output_when_self_counting() -> None:
    """B-33 + B-97: huỷ `deepseek-flash` trong khối reasoning cho `content` RỖNG.

    Provider tính reasoning vào `completion_tokens`, nên bỏ nó ra là ghi 0 đồng
    cho một lượt sinh đã tiêu thật.
    """
    model = _model(MODEL_METERED)
    without_reasoning = measure(
        model, usage=None, sent=[], content="", reasoning="", tool_calls=None
    )
    with_reasoning = measure(
        model,
        usage=None,
        sent=[],
        content="",
        reasoning="Người dùng hỏi về mùa thu. Ta nên trả lời ngắn gọn." * 5,
        tool_calls=None,
    )
    assert with_reasoning.completion_tokens > without_reasoning.completion_tokens


def test_self_counted_prompt_includes_provider_injected_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B-65: 9Router bơm ~2000 token vào mọi request, và cửa TRƯỚC đã cộng nó.

    Hai cửa của cùng §10.2 không được nói hai chuyện khác nhau về một lượt chat.
    """
    model = _model(MODEL_9ROUTER)
    sent = [{"role": "user", "content": "xin chao"}]
    without_overhead = measure(
        model, usage=None, sent=sent, content="hi", reasoning="", tool_calls=None
    )

    monkeypatch.setattr(catalog.Catalog, "prompt_overhead_tokens", lambda self, model_id: 2000)
    with_overhead = measure(
        model, usage=None, sent=sent, content="hi", reasoning="", tool_calls=None
    )
    assert with_overhead.prompt_tokens == without_overhead.prompt_tokens + 2000


def test_empty_context_prompt_is_0_not_the_answer_part() -> None:
    """`count_messages([])` vẫn trả `TOKENS_REPLY_PRIMING` — một request chưa
    từng gửi không được tính ba token."""
    spent = measure(
        _model(MODEL_METERED), usage=None, sent=[], content="", reasoning="", tool_calls=None
    )
    assert spent.prompt_tokens == 0


# ═════════════════ cost_confidence (§9.5, C16, DoD dòng 3) ══════════════════


def test_metered_model_with_real_usage_is_exact() -> None:
    spent = Spent(prompt_tokens=1, completion_tokens=1, cached_tokens=0, measured=True)
    assert confidence_of(_model(MODEL_METERED), spent) is CostConfidence.EXACT


def test_9router_model_always_low_even_if_provider_reports_usage() -> None:
    """DoD dòng 3. §9.5: model trả lời có thể khác model đã yêu cầu ⇒ giá sai."""
    spent = Spent(prompt_tokens=2003, completion_tokens=9, cached_tokens=0, measured=True)
    assert _model(MODEL_9ROUTER).is_metered is False
    assert confidence_of(_model(MODEL_9ROUTER), spent) is CostConfidence.LOW


def test_tiktoken_self_count_is_low_even_for_metered_model() -> None:
    """B-67, B-94: số xấp xỉ không được mang nhãn `exact`."""
    spent = Spent(prompt_tokens=214, completion_tokens=37, cached_tokens=0, measured=False)
    assert confidence_of(_model(MODEL_METERED), spent) is CostConfidence.LOW


# ═════════════════ price_snapshot (A7, ADR-08, §17.2) ═══════════════════════


def test_snapshot_keeps_four_prices_and_three_provenance_fields() -> None:
    model = _model(MODEL_CACHE_WRITE)
    pricing = _rates(model.id)
    snap = snapshot_of(model, pricing, PEAK_HOUR)

    assert snap["input_per_1m"] == pricing.input_per_1m
    assert snap["output_per_1m"] == pricing.output_per_1m
    assert snap["cached_input_per_1m"] == pricing.cached_input_per_1m
    # Anthropic thu riêng tiền GHI cache; công thức chưa dùng, snapshot vẫn giữ.
    assert snap["cache_write_per_1m"] == pricing.cache_write_per_1m is not None
    assert snap["source"] == "catalog"
    assert snap["pricing_mode"] == model.pricing_mode
    assert snap["catalog_version"] == catalog.get_catalog().version
    assert snap["at"] == PEAK_HOUR.isoformat()


def test_unpriced_model_snapshot_is_none_not_0() -> None:
    """`0.0` nghĩa là "provider thu 0 USD", `None` nghĩa là "chưa ai điền"."""
    snap = snapshot_of(_model(MODEL_9ROUTER), None, OFF_PEAK_HOUR)
    assert snap["input_per_1m"] is None
    assert snap["output_per_1m"] is None
    assert snap["source"] == "none"


def test_snapshot_records_price_at_call_time_not_now() -> None:
    """A7 — hai thời điểm, hai snapshot, và chúng phải khác nhau."""
    model = _model(MODEL_METERED)
    peak = snapshot_of(model, _rates(model.id, PEAK_HOUR), PEAK_HOUR)
    off_peak = snapshot_of(model, _rates(model.id, OFF_PEAK_HOUR), OFF_PEAK_HOUR)
    assert peak["input_per_1m"] != off_peak["input_per_1m"]


# ═════════════════ record_usage: Postgres thật + Redis giả ══════════════════


@pytest.fixture
def _db_for_tests(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


async def _write_one_row(
    session: AsyncSession,
    redis: Any,
    user_id: uuid.UUID,
    *,
    model_id: str = MODEL_METERED,
    usage: Usage | None = None,
    at: datetime = PEAK_HOUR,
    now: float | None = None,
    content: str = "Ha Noi mua thu dep.",
    key_source: KeySource = KeySource.SYSTEM,
) -> Any:
    record = await record_usage(
        session,
        redis,
        user_id=user_id,
        message_id=None,
        model=_model(model_id),
        at=at,
        now=time.time() if now is None else now,
        usage=usage,
        sent=[{"role": "user", "content": "Mua thu Ha Noi the nao?"}],
        content=content,
        reasoning="",
        tool_calls=None,
        key_source=key_source,
    )
    await session.commit()
    return record


async def test_one_chat_turn_yields_one_row_with_full_cost_and_snapshot(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    """DoD dòng 1."""
    usage = Usage(prompt_tokens=1204, completion_tokens=389, total_tokens=1593)
    record = await _write_one_row(session, quota_redis_fake, user_a, usage=usage)

    rows = (
        (await session.execute(select(UsageEvent).where(UsageEvent.user_id == user_a)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.cost_usd > 0
    assert row.cost_usd == record.cost_usd
    assert row.prompt_tokens == 1204
    assert row.completion_tokens == 389
    assert row.cost_confidence == CostConfidence.EXACT
    assert row.key_source == KeySource.SYSTEM
    assert row.provider == _model(MODEL_METERED).provider
    assert set(row.price_snapshot) == {
        "input_per_1m",
        "output_per_1m",
        "cached_input_per_1m",
        "cache_write_per_1m",
        "pricing_mode",
        "source",
        "catalog_version",
        "at",
    }
    # B-32 — đã đo trên 9Router thật: không lấy được. Xem docstring `meter.py`.
    assert row.upstream_model_reported is None


async def test_changing_catalog_price_does_not_change_old_rows(
    session: AsyncSession,
    user_a: uuid.UUID,
    quota_redis_fake: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DoD dòng 2 — A7, và đây là phép kiểm mà `price_snapshot` sinh ra để phục vụ."""
    usage = Usage(prompt_tokens=1_000_000, completion_tokens=0, total_tokens=1_000_000)
    record = await _write_one_row(session, quota_redis_fake, user_a, usage=usage)
    old_cost = record.cost_usd
    old_snapshot = (
        await session.execute(select(UsageEvent.price_snapshot).where(UsageEvent.id == record.id))
    ).scalar_one()

    # Tăng giá gấp mười trong catalog, y như một lần sửa `model_catalog.json`.
    original = catalog.Catalog.effective_pricing

    def new_pricing(self: catalog.Catalog, model_id: str, at: Any = None) -> Any:
        old = original(self, model_id, at)
        if old is None:
            return None
        return catalog.PricingRates(
            input_per_1m=old.input_per_1m * 10,
            output_per_1m=old.output_per_1m * 10,
            cached_input_per_1m=old.cached_input_per_1m,
            cache_write_per_1m=old.cache_write_per_1m,
        )

    monkeypatch.setattr(catalog.Catalog, "effective_pricing", new_pricing)

    reloaded = (
        await session.execute(select(UsageEvent).where(UsageEvent.id == record.id))
    ).scalar_one()
    await session.refresh(reloaded)
    assert reloaded.cost_usd == old_cost
    assert reloaded.price_snapshot == old_snapshot

    # …còn một lượt sinh MỚI thì phải thấy giá mới. Nếu không thì test trên
    # xanh vì không có gì đổi cả, chứ không phải vì A7 được giữ.
    new_row = await _write_one_row(session, quota_redis_fake, user_a, usage=usage)
    assert new_row.cost_usd == old_cost * 10


async def test_9router_model_yields_low_row(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    """DoD dòng 3."""
    usage = Usage(prompt_tokens=2003, completion_tokens=9, total_tokens=2012)
    record = await _write_one_row(
        session, quota_redis_fake, user_a, model_id=MODEL_9ROUTER, usage=usage
    )
    assert record.confidence is CostConfidence.LOW
    row = (await session.execute(select(UsageEvent).where(UsageEvent.id == record.id))).scalar_one()
    assert row.cost_confidence == CostConfidence.LOW


async def test_one_ledger_row_is_one_member_in_EACH_window(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    """§10.2 vế SAU + B-156: `ZADD` bằng `encode_member`, cả hai cửa sổ."""
    usage = Usage(prompt_tokens=1204, completion_tokens=389, total_tokens=1593)
    record = await _write_one_row(session, quota_redis_fake, user_a, usage=usage)

    for window in windows():
        seats = quota_redis_fake.zset[window.key(user_a)]
        assert len(seats) == 1
        member = next(iter(seats))
        assert member.startswith(f"{record.id}:")
        assert parse_member(member) == record.cost_usd


async def test_every_write_resets_TTL_on_both_keys(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    """Nửa (b) của B-156: không có `EXPIRE` thì member quá hạn nằm đó vô thời hạn."""
    usage = Usage(prompt_tokens=10, completion_tokens=10, total_tokens=20)
    await _write_one_row(session, quota_redis_fake, user_a, usage=usage)
    await _write_one_row(session, quota_redis_fake, user_a, usage=usage)

    expected = [(w.key(user_a), w.seconds) for w in windows()]
    assert quota_redis_fake.ttl_calls == expected * 2


async def test_byok_still_writes_ledger_but_does_NOT_charge_quota(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    """§10.5 — nhánh chưa chạy được tới T-2.15, nhưng luật đã sống ở đúng chỗ."""
    usage = Usage(prompt_tokens=1204, completion_tokens=389, total_tokens=1593)
    record = await _write_one_row(
        session, quota_redis_fake, user_a, usage=usage, key_source=KeySource.BYOK
    )
    row = (await session.execute(select(UsageEvent).where(UsageEvent.id == record.id))).scalar_one()
    assert row.key_source == KeySource.BYOK
    assert row.cost_usd > 0
    assert quota_redis_fake.zset == {}


async def test_postgres_sum_matches_redis_zset_total(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    """DoD dòng 5 — bản tự động, trên nhiều lượt với nhiều hình dạng usage khác nhau.

    Trộn cả ba ca vào một phép cộng có chủ ý: có `usage` thật, không có `usage`
    (tự đếm), và một model không có giá. Nếu một trong ba đi một đường ghi khác
    thì hai con số sẽ lệch, mà lệch ở đâu thì `SUM` không nói — đó đúng là lý do
    phép kiểm này phải chạy trên hỗn hợp chứ không trên một ca sạch.
    """
    turns: list[dict[str, Any]] = [
        {"usage": Usage(prompt_tokens=1204, completion_tokens=389, total_tokens=1593)},
        {"usage": Usage(prompt_tokens=7, completion_tokens=3, total_tokens=10)},
        {"usage": None},
        {"usage": None, "content": "x" * 400},
        {"usage": Usage(prompt_tokens=99, completion_tokens=1, total_tokens=100)},
        {"model_id": MODEL_9ROUTER, "usage": None},
    ]
    for turn in turns:
        await _write_one_row(session, quota_redis_fake, user_a, **turn)

    postgres_total = (
        (await session.execute(select(UsageEvent.cost_usd).where(UsageEvent.user_id == user_a)))
        .scalars()
        .all()
    )
    assert len(postgres_total) == len(turns)

    for window in windows():
        seats = quota_redis_fake.zset[window.key(user_a)]
        assert len(seats) == len(turns)
        redis_total = sum((parse_member(m) or Decimal(0) for m in seats), Decimal(0))
        assert abs(sum(postgres_total, Decimal(0)) - redis_total) <= Decimal("0.000001")


async def test_postgres_keeps_computed_number_without_rerounding(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    """`quantize_cost` chạy MỘT lần: nếu không, `NUMERIC(12,6)` làm tròn lần hai
    theo một luật khác `f"{…:.6f}"` của `encode_member`, và DoD dòng 5 đo đúng
    khoảng lệch đó."""
    usage = Usage(prompt_tokens=3_333_333, completion_tokens=777_777, total_tokens=4_111_110)
    record = await _write_one_row(session, quota_redis_fake, user_a, usage=usage)
    row = (await session.execute(select(UsageEvent).where(UsageEvent.id == record.id))).scalar_one()
    assert row.cost_usd == record.cost_usd
    seats = quota_redis_fake.zset[windows()[0].key(user_a)]
    assert parse_member(next(iter(seats))) == row.cost_usd


async def test_dead_redis_row_is_absent_not_half_present(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    """Postgres TRƯỚC, Redis SAU — và ngoại lệ đi thẳng ra ngoài.

    Chỗ gọi (`workers/generate.py::_record_usage`) mở transaction, nên ngoại lệ
    ở `ZADD` làm cả `INSERT` rollback: không có dòng sổ mồ côi, và cũng không
    có khoản tiền nào trong ZSET mà sổ không giải thích được.
    """
    quota_redis_fake.fail = True
    with pytest.raises(ConnectionError):
        await _write_one_row(
            session,
            quota_redis_fake,
            user_a,
            usage=Usage(prompt_tokens=10, completion_tokens=10, total_tokens=20),
        )
    await session.rollback()
    remaining = (
        (await session.execute(select(UsageEvent).where(UsageEvent.user_id == user_a)))
        .scalars()
        .all()
    )
    assert remaining == []
