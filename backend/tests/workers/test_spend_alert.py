"""T-2.17 — cron `spend_alert` + `sum_since` sau B-172 (RR-1, §21.5, C16).

KH tham chiếu: RR-1, RR-13, §21.5, §10.5, §9.5/C16, S13 · CLAUDE.md A3, A7 ·
tasks.md T-2.17, B-172.

Ba dòng DoD của task được kiểm ở đây, và cả ba kiểm bằng **Postgres thật**
(fixture `session_factory` của `tests/conftest.py`, NQ-17) vì thứ đáng kiểm
nhất là câu `GROUP BY cost_confidence` có lọc đúng tập hàng không — ngữ nghĩa
của Postgres, không phải của Python. Chỉ Redis và SMTP là giả.

- **DoD 1** — `DAILY_ALERT_USD` thấp → có thư: `test_over_daily_threshold_sends_mail`
- **DoD 2** — chạy lần hai cùng ngày → không thư thứ hai:
  `test_second_run_same_day_sends_nothing_more`
- **DoD 3** — thư ghi rõ ai tiêu nhiều nhất, bao nhiêu:
  `test_mail_names_top_spender`

Phần còn lại canh bốn quyết định NQ-62…NQ-65 và ba ngả hỏng (SMTP chết, không
có admin, Redis chết) — mỗi thứ một ca, vì cả bốn quyết định đều hỏng **im
lặng**: một lá thư có con số sai trông y hệt một lá thư đúng.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.db.session as db_session
from app.config.settings import settings
from app.core.mailer import _SUBJECTS, TEMPLATES_DIR
from app.db.models import CostConfidence, KeySource, UsagePurpose, User, UserRole
from app.db.repositories import CostSplit, UsageEventRepository, UserRepository
from app.workers.main import CRON_JOBS
from app.workers.spend_alert import (
    BUDGET_WINDOW_DAYS,
    SPEND_ALERT_JOB_NAME,
    SPEND_ALERT_MINUTES_IN_HOUR,
    TEMPLATE_BUDGET,
    TEMPLATE_DAILY,
    day_start_utc,
    spend_alert,
)

MODEL_ID = "deepseek-flash"


# ══════════════════════════════ hạ tầng giả ══════════════════════════════


class FakeRedis:
    """Đủ `set(nx=, ex=)` và `delete` — hai lệnh duy nhất của cờ chống lặp.

    `set` mô phỏng đúng ngữ nghĩa `NX` của Redis (khoá đã có ⇒ trả `None`), vì
    đó chính là thứ DoD dòng 2 đo: một bản giả luôn trả `True` sẽ cho hai lá
    thư mà mọi phép khẳng định khác vẫn xanh.
    """

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttl: dict[str, int] = {}
        self.deleted: list[str] = []
        self.fail = False

    async def set(
        self, name: str, value: str, *, ex: int | None = None, nx: bool = False
    ) -> bool | None:
        if self.fail:
            raise ConnectionError("redis chet (gia lap)")
        if nx and name in self.store:
            return None
        self.store[name] = value
        if ex is not None:
            self.ttl[name] = ex
        return True

    async def delete(self, name: str) -> int:
        if self.fail:
            raise ConnectionError("redis chet (gia lap)")
        self.deleted.append(name)
        return int(self.store.pop(name, None) is not None)


class FakeMailer:
    """Stub `Mailer`. `inbox_fails` làm hỏng đúng một hộp để kiểm cách ly."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.inbox_fails: str | None = None
        self.fail_all = False

    async def send(self, *, template: str, to: str, ctx: dict[str, Any]) -> None:
        if self.fail_all or to == self.inbox_fails:
            raise ConnectionError("smtp chet (gia lap)")
        self.calls.append({"template": template, "to": to, "ctx": ctx})

    def for_template(self, template: str) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["template"] == template]


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def fake_mailer(monkeypatch: pytest.MonkeyPatch) -> FakeMailer:
    """Thay `app.workers.spend_alert.mailer` — đúng tên đã import vào module đó."""
    stub = FakeMailer()
    monkeypatch.setattr("app.workers.spend_alert.mailer", stub)
    return stub


@pytest.fixture(autouse=True)
def _bind_session_to_test_db(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """`session_scope()` của job trỏ vào transaction của test — như T-1.10."""
    monkeypatch.setattr(db_session, "get_sessionmaker", lambda: session_factory)


@pytest.fixture(autouse=True)
def _high_default_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mặc định **không** ca nào vượt ngưỡng; ca nào cần vượt thì tự hạ xuống.

    Ngược lại thì một ca quên đặt ngưỡng sẽ xanh nhờ `.env` của người chạy
    test, và đỏ trên máy khác.
    """
    monkeypatch.setattr(settings, "DAILY_ALERT_USD", Decimal("1000"))
    monkeypatch.setattr(settings, "MONTHLY_BUDGET_USD", Decimal("1000"))


def _ctx(fake_redis: FakeRedis) -> dict[str, Any]:
    return {"redis": fake_redis, "job_id": "test-cron"}


# ═══════════════════════════ dữ liệu cho test ════════════════════════════


async def _write_ledger(
    session_factory: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
    *,
    cost: str,
    confidence: CostConfidence = CostConfidence.EXACT,
    key_source: KeySource = KeySource.SYSTEM,
    age_seconds: float = 0.0,
) -> uuid.UUID:
    """Một dòng `usage_events` có tuổi cho trước — cùng thân với T-2.13.

    Ghi qua `UsageEventRepository.record` (đường ghi thật của T-2.12) rồi mới
    lùi `created_at` bằng một `UPDATE` riêng: cột đó do Postgres sinh, và mở
    một tham số cho phép chọn nó là mở đúng cánh cửa A7 đóng.
    """
    async with session_factory() as session:
        event = await UsageEventRepository(session).record(
            user_id=user_id,
            message_id=None,
            model_id=MODEL_ID,
            provider="nha-cung-cap-test",
            key_source=key_source,
            prompt_tokens=10,
            completion_tokens=20,
            cached_tokens=0,
            cost_usd=Decimal(cost),
            cost_confidence=confidence,
            price_snapshot={},
            purpose=UsagePurpose.CHAT,
        )
        if age_seconds:
            await session.execute(
                text(
                    "UPDATE usage_events SET created_at = now() - make_interval(secs => :t) "
                    "WHERE id = :id"
                ),
                {"t": age_seconds, "id": event.id},
            )
        await session.commit()
        return event.id


async def _admin(
    session_factory: async_sessionmaker[AsyncSession], *, email: str | None = None
) -> str:
    """Một hàng `users` với `role='admin'`. Trả về email của nó."""
    address = email or f"admin-{uuid.uuid4().hex}@scarlet.example"
    async with session_factory() as session:
        user = await UserRepository(session).create_pending_user(
            email=address, password_hash="khong-phai-hash-that"
        )
        assert user is not None
        await session.execute(update(User).where(User.id == user.id).values(role=UserRole.ADMIN))
        await session.commit()
    return address


async def _email_of(session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID) -> str:
    async with session_factory() as session:
        person = await UserRepository(session).get_by_id(user_id)
        assert person is not None
        return person.email


# ════════════ B-172: `sum_since` nhận `key_source`, trả hai cột ════════════


async def test_sum_since_splits_two_columns_by_cost_confidence(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
) -> None:
    """C16 ở tầng dữ liệu: `exact` và `low` không bao giờ đi chung một con số."""
    await _write_ledger(session_factory, user_a, cost="0.100000")
    await _write_ledger(session_factory, user_a, cost="0.030000", confidence=CostConfidence.LOW)

    split = await UsageEventRepository(session).sum_since(
        user_id=user_a, since=datetime.now(UTC) - timedelta(hours=1), key_source=None
    )

    assert split == CostSplit(exact=Decimal("0.100000"), low=Decimal("0.030000"))


def test_cost_split_has_no_total_field() -> None:
    """C16 — `MeteredSplit` của T-2.16 cũng không có, và vì cùng một lý do.

    Một trường `total` tiện tay thì sẽ có người dùng, và chỗ dùng đầu tiên sẽ
    là chỗ hai cột im lặng nhập lại làm một. Phép cộng duy nhất được phép nằm
    ở `spend_alert._combined`, một cái tên `grep` ra được.
    """
    assert {f for f in CostSplit.__dataclass_fields__} == {"exact", "low"}
    assert not hasattr(CostSplit(exact=Decimal(1), low=Decimal(2)), "total")


async def test_sum_since_filters_key_source_on_request(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
) -> None:
    """NQ-62 — cùng một người, cùng một cửa sổ, hai câu trả lời khác nhau."""
    await _write_ledger(session_factory, user_a, cost="0.100000")
    await _write_ledger(session_factory, user_a, cost="0.070000", key_source=KeySource.BYOK)
    repo = UsageEventRepository(session)
    since = datetime.now(UTC) - timedelta(hours=1)

    system_only = await repo.sum_since(user_id=user_a, since=since, key_source=KeySource.SYSTEM)
    both = await repo.sum_since(user_id=user_a, since=since, key_source=None)

    assert system_only.exact == Decimal("0.100000")
    assert both.exact == Decimal("0.170000")


async def test_sum_since_filters_user_id_in_sql(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
) -> None:
    """§20 — tiền của B không được lọt vào câu trả lời cho A."""
    await _write_ledger(session_factory, user_a, cost="0.010000")
    await _write_ledger(session_factory, user_b, cost="0.990000")

    split = await UsageEventRepository(session).sum_since(
        user_id=user_a,
        since=datetime.now(UTC) - timedelta(hours=1),
        key_source=KeySource.SYSTEM,
    )

    assert split.exact == Decimal("0.010000")


async def test_sum_since_filters_time_bound(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
) -> None:
    """Dòng sổ ngoài cửa sổ không được cộng vào."""
    await _write_ledger(session_factory, user_a, cost="0.500000", age_seconds=7200)
    await _write_ledger(session_factory, user_a, cost="0.020000")

    split = await UsageEventRepository(session).sum_since(
        user_id=user_a,
        since=datetime.now(UTC) - timedelta(hours=1),
        key_source=KeySource.SYSTEM,
    )

    assert split.exact == Decimal("0.020000")


async def test_sum_since_non_spender_gets_two_zeros(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """Tập rỗng ⇒ `Decimal(0)`, không phải `None`: chỗ gọi cộng thẳng vào tổng."""
    split = await UsageEventRepository(session).sum_since(
        user_id=user_a, since=datetime.now(UTC), key_source=KeySource.SYSTEM
    )

    assert split == CostSplit(exact=Decimal(0), low=Decimal(0))


async def test_list_admins_returns_only_undeleted_admins(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
) -> None:
    """Người nhận thư đọc từ bảng `users`, không từ một biến `.env`."""
    address = await _admin(session_factory)
    deleted = await _admin(session_factory)
    async with session_factory() as other_session:
        await other_session.execute(
            update(User).where(User.email == deleted).values(deleted_at=datetime.now(UTC))
        )
        await other_session.commit()

    emails = [u.email for u in await UserRepository(session).list_admins()]

    assert emails == [address], "user thường hoặc admin đã xoá lọt vào danh sách nhận thư"


# ═══════════════════ DoD dòng 1 — vượt ngưỡng thì có thư ═══════════════════


async def test_over_daily_threshold_sends_mail(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    fake_mailer: FakeMailer,
    monkeypatch: pytest.MonkeyPatch,
    user_a: uuid.UUID,
) -> None:
    """DoD dòng 1: hạ `DAILY_ALERT_USD` → chạy cron → có thư."""
    address = await _admin(session_factory)
    await _write_ledger(session_factory, user_a, cost="0.000500")
    monkeypatch.setattr(settings, "DAILY_ALERT_USD", Decimal("0.0001"))

    await spend_alert(_ctx(fake_redis))

    sent_mails = fake_mailer.for_template(TEMPLATE_DAILY)
    assert len(sent_mails) == 1
    assert sent_mails[0]["to"] == address
    assert sent_mails[0]["ctx"]["total_usd"] == "0.000500"
    assert sent_mails[0]["ctx"]["limit_usd"] == "0.000100"


async def test_below_threshold_sends_nothing(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    fake_mailer: FakeMailer,
    monkeypatch: pytest.MonkeyPatch,
    user_a: uuid.UUID,
) -> None:
    """`>` chứ không `>=`: đúng bằng ngưỡng thì chưa phải "vượt"."""
    await _admin(session_factory)
    await _write_ledger(session_factory, user_a, cost="0.000500")
    monkeypatch.setattr(settings, "DAILY_ALERT_USD", Decimal("0.000500"))

    await spend_alert(_ctx(fake_redis))

    assert fake_mailer.calls == []
    assert fake_redis.store == {}


# ══════════ DoD dòng 2 — chống lặp: 24 nhịp một ngày, một lá thư ══════════


async def test_second_run_same_day_sends_nothing_more(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    fake_mailer: FakeMailer,
    monkeypatch: pytest.MonkeyPatch,
    user_a: uuid.UUID,
) -> None:
    """DoD dòng 2 — và Cạm bẫy của task: cảnh báo bị lọc là cảnh báo không có."""
    await _admin(session_factory)
    await _write_ledger(session_factory, user_a, cost="0.000500")
    monkeypatch.setattr(settings, "DAILY_ALERT_USD", Decimal("0.0001"))

    await spend_alert(_ctx(fake_redis))
    await spend_alert(_ctx(fake_redis))
    await spend_alert(_ctx(fake_redis))

    assert len(fake_mailer.for_template(TEMPLATE_DAILY)) == 1
    key = f"alert:{TEMPLATE_DAILY}:{datetime.now(UTC).date().isoformat()}"
    assert key in fake_redis.store, "cờ chống lặp phải mang NGÀY trong tên khoá"
    assert fake_redis.ttl[key] > 86400, "TTL ngắn hơn một ngày là cảnh báo lặp lúc nửa đêm"


async def test_dedup_flag_released_when_no_mail_sent(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    fake_mailer: FakeMailer,
    monkeypatch: pytest.MonkeyPatch,
    user_a: uuid.UUID,
) -> None:
    """SMTP chết ⇒ giờ sau phải thử lại, không im lặng mất cảnh báo cả ngày."""
    await _admin(session_factory)
    await _write_ledger(session_factory, user_a, cost="0.000500")
    monkeypatch.setattr(settings, "DAILY_ALERT_USD", Decimal("0.0001"))
    fake_mailer.fail_all = True

    await spend_alert(_ctx(fake_redis))
    assert fake_redis.store == {}, "giữ cờ sau khi gửi hỏng là mất cảnh báo cả ngày"

    fake_mailer.fail_all = False
    await spend_alert(_ctx(fake_redis))

    assert len(fake_mailer.for_template(TEMPLATE_DAILY)) == 1


async def test_one_broken_inbox_does_not_block_others(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    fake_mailer: FakeMailer,
    monkeypatch: pytest.MonkeyPatch,
    user_a: uuid.UUID,
) -> None:
    """Cùng luật cách ly với `reaper._notify_client`."""
    broken = await _admin(session_factory, email="admin-hong@scarlet.example")
    benign = await _admin(session_factory, email="admin-lanh@scarlet.example")
    await _write_ledger(session_factory, user_a, cost="0.000500")
    monkeypatch.setattr(settings, "DAILY_ALERT_USD", Decimal("0.0001"))
    fake_mailer.inbox_fails = broken

    await spend_alert(_ctx(fake_redis))

    assert [c["to"] for c in fake_mailer.for_template(TEMPLATE_DAILY)] == [benign]
    assert fake_redis.store != {}, "gửi được một lá thì cờ phải giữ"


async def test_dead_redis_sends_no_mail(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    fake_mailer: FakeMailer,
    monkeypatch: pytest.MonkeyPatch,
    user_a: uuid.UUID,
) -> None:
    """Không đặt được cờ ⇒ coi như đã gửi. Ngả kia là đúng 24 lá một ngày."""
    await _admin(session_factory)
    await _write_ledger(session_factory, user_a, cost="0.000500")
    monkeypatch.setattr(settings, "DAILY_ALERT_USD", Decimal("0.0001"))
    fake_redis.fail = True

    await spend_alert(_ctx(fake_redis))

    assert fake_mailer.calls == []


async def test_no_admin_keeps_no_flag(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    fake_mailer: FakeMailer,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    user_a: uuid.UUID,
) -> None:
    """Không có ai để gửi là sự cố cấu hình — mỗi nhịp phải nói lại."""
    await _write_ledger(session_factory, user_a, cost="0.000500")
    monkeypatch.setattr(settings, "DAILY_ALERT_USD", Decimal("0.0001"))

    with caplog.at_level(logging.WARNING, logger="app.workers.spend_alert"):
        await spend_alert(_ctx(fake_redis))

    assert fake_mailer.calls == []
    assert fake_redis.store == {}
    assert any("role='admin'" in r.getMessage() for r in caplog.records)


# ═════════════ DoD dòng 3 — thư nói ai tiêu nhiều nhất, bao nhiêu ═════════════


async def test_mail_names_top_spender(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    fake_mailer: FakeMailer,
    monkeypatch: pytest.MonkeyPatch,
    user_a: uuid.UUID,
    user_b: uuid.UUID,
) -> None:
    """DoD dòng 3. Hai người tiêu, thư phải chỉ đúng người tiêu nhiều hơn.

    `user_a` tiêu hai lần nhỏ, `user_b` một lần lớn hơn tổng của A — một bản
    chỉ so **từng dòng sổ** thay vì tổng của mỗi người sẽ chỉ nhầm sang A khi
    đảo con số, nên hai dòng của A cộng lại vẫn phải thua B.
    """
    await _admin(session_factory)
    await _write_ledger(session_factory, user_a, cost="0.000100")
    await _write_ledger(session_factory, user_a, cost="0.000100")
    await _write_ledger(session_factory, user_b, cost="0.000300")
    monkeypatch.setattr(settings, "DAILY_ALERT_USD", Decimal("0.0001"))

    await spend_alert(_ctx(fake_redis))

    ctx = fake_mailer.for_template(TEMPLATE_DAILY)[0]["ctx"]
    assert ctx["top_email"] == await _email_of(session_factory, user_b)
    assert ctx["top_usd"] == "0.000300"
    assert ctx["total_usd"] == "0.000500"


async def test_top_spender_sums_all_their_rows(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    fake_mailer: FakeMailer,
    monkeypatch: pytest.MonkeyPatch,
    user_a: uuid.UUID,
    user_b: uuid.UUID,
) -> None:
    """Chiều ngược của ca trên: A tiêu nhiều **lần nhỏ** nhưng tổng lớn hơn."""
    await _admin(session_factory)
    for _ in range(4):
        await _write_ledger(session_factory, user_a, cost="0.000100")
    await _write_ledger(session_factory, user_b, cost="0.000300")
    monkeypatch.setattr(settings, "DAILY_ALERT_USD", Decimal("0.0001"))

    await spend_alert(_ctx(fake_redis))

    ctx = fake_mailer.for_template(TEMPLATE_DAILY)[0]["ctx"]
    assert ctx["top_email"] == await _email_of(session_factory, user_a)
    assert ctx["top_usd"] == "0.000400"


# ════════════════ NQ-62 — chỉ đếm tiền của người vận hành ════════════════


async def test_byok_money_does_not_ring_the_bell(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    fake_mailer: FakeMailer,
    monkeypatch: pytest.MonkeyPatch,
    user_a: uuid.UUID,
) -> None:
    """NQ-62 (B-172) — §10.5: khoản BYOK không nằm trên hoá đơn của người vận hành."""
    await _admin(session_factory)
    await _write_ledger(session_factory, user_a, cost="9.000000", key_source=KeySource.BYOK)
    monkeypatch.setattr(settings, "DAILY_ALERT_USD", Decimal("0.0001"))

    await spend_alert(_ctx(fake_redis))

    assert fake_mailer.calls == [], "tiền người dùng tự trả đã bị tính vào ngân sách"


async def test_byok_stays_out_of_total_alongside_system_money(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    fake_mailer: FakeMailer,
    monkeypatch: pytest.MonkeyPatch,
    user_a: uuid.UUID,
) -> None:
    """Ca trên một mình không đủ: nó cũng xanh khi job **không gửi gì cả**."""
    await _admin(session_factory)
    await _write_ledger(session_factory, user_a, cost="0.000500")
    await _write_ledger(session_factory, user_a, cost="9.000000", key_source=KeySource.BYOK)
    monkeypatch.setattr(settings, "DAILY_ALERT_USD", Decimal("0.0001"))

    await spend_alert(_ctx(fake_redis))

    ctx = fake_mailer.for_template(TEMPLATE_DAILY)[0]["ctx"]
    assert ctx["total_usd"] == "0.000500"
    assert ctx["top_usd"] == "0.000500"


# ═══════ NQ-65 — `low` tính vào ngưỡng, nhưng thư in tách hai con số ═══════


async def test_estimated_rows_still_ring_the_bell(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    fake_mailer: FakeMailer,
    monkeypatch: pytest.MonkeyPatch,
    user_a: uuid.UUID,
) -> None:
    """NQ-65 — kẻ lạm dụng chỉ dùng model qua 9Router (§9.5) vẫn phải bị bắt."""
    await _admin(session_factory)
    await _write_ledger(session_factory, user_a, cost="0.000500", confidence=CostConfidence.LOW)
    monkeypatch.setattr(settings, "DAILY_ALERT_USD", Decimal("0.0001"))

    await spend_alert(_ctx(fake_redis))

    ctx = fake_mailer.for_template(TEMPLATE_DAILY)[0]["ctx"]
    assert ctx["total_usd"] == "0.000500"
    assert ctx["exact_usd"] == "0.000000"
    assert ctx["low_usd"] == "0.000500"


async def test_mail_always_prints_two_columns(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    fake_mailer: FakeMailer,
    monkeypatch: pytest.MonkeyPatch,
    user_a: uuid.UUID,
) -> None:
    """C16 — con số gộp chỉ được phép đứng cạnh hai con số thành phần."""
    await _admin(session_factory)
    await _write_ledger(session_factory, user_a, cost="0.000300")
    await _write_ledger(session_factory, user_a, cost="0.000200", confidence=CostConfidence.LOW)
    monkeypatch.setattr(settings, "DAILY_ALERT_USD", Decimal("0.0001"))

    await spend_alert(_ctx(fake_redis))

    ctx = fake_mailer.for_template(TEMPLATE_DAILY)[0]["ctx"]
    assert (ctx["exact_usd"], ctx["low_usd"], ctx["total_usd"]) == (
        "0.000300",
        "0.000200",
        "0.000500",
    )


# ═══════════ NQ-64 — hai cửa sổ: nửa đêm UTC và 30 ngày trượt ═══════════


async def test_day_window_starts_at_utc_midnight(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    fake_mailer: FakeMailer,
    monkeypatch: pytest.MonkeyPatch,
    user_a: uuid.UUID,
) -> None:
    """Chi tiêu của **hôm qua** không được tính vào ngưỡng ngày.

    Dòng sổ lùi 25 giờ nên nó nằm ngoài cửa sổ ở mọi giờ trong ngày, kể cả khi
    bộ test chạy lúc 00:30 UTC — một phép lùi 2 giờ sẽ nhấp nháy theo đồng hồ.
    """
    await _admin(session_factory)
    await _write_ledger(session_factory, user_a, cost="9.000000", age_seconds=25 * 3600)
    monkeypatch.setattr(settings, "DAILY_ALERT_USD", Decimal("0.0001"))

    await spend_alert(_ctx(fake_redis))

    assert fake_mailer.for_template(TEMPLATE_DAILY) == []


@pytest.mark.parametrize(
    ("mark", "expected"),
    [
        # Giữa ngày — chỗ `now - 1 ngày` sai nhiều nhất.
        (datetime(2026, 9, 19, 14, 30, 45, 123456, tzinfo=UTC), datetime(2026, 9, 19, tzinfo=UTC)),
        # Đúng nửa đêm: biên là `>=`, nên chính nó phải thuộc về ngày của nó.
        (datetime(2026, 9, 19, 0, 0, tzinfo=UTC), datetime(2026, 9, 19, tzinfo=UTC)),
        # Một giây trước nửa đêm: vẫn là ngày hôm trước.
        (datetime(2026, 9, 18, 23, 59, 59, tzinfo=UTC), datetime(2026, 9, 18, tzinfo=UTC)),
    ],
)
def test_day_lower_bound_is_utc_midnight(mark: datetime, expected: datetime) -> None:
    """ "Hôm nay" là một NGÀY, không phải một cửa sổ 24 giờ trượt.

    Hai công thức chỉ khác nhau tuỳ **giờ** lúc job chạy, nên phép kiểm này
    phải nhận một `now` cố định — đo qua job sẽ xanh hay đỏ theo đồng hồ của
    người chạy test. Ca giữa ngày là ca `now - timedelta(days=1)` trả về
    `2026-09-18 14:30`, tức nuốt nửa ngày hôm qua vào ngưỡng của hôm nay.
    """
    assert day_start_utc(mark) == expected


async def test_budget_window_is_rolling_thirty_days(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    fake_mailer: FakeMailer,
    monkeypatch: pytest.MonkeyPatch,
    user_a: uuid.UUID,
) -> None:
    """NQ-64 — dòng sổ 20 ngày trước VẪN tính, dòng 31 ngày trước thì không."""
    await _admin(session_factory)
    await _write_ledger(session_factory, user_a, cost="0.000500", age_seconds=20 * 86400)
    await _write_ledger(
        session_factory, user_a, cost="9.000000", age_seconds=(BUDGET_WINDOW_DAYS + 1) * 86400
    )
    monkeypatch.setattr(settings, "MONTHLY_BUDGET_USD", Decimal("0.0001"))

    await spend_alert(_ctx(fake_redis))

    ctx = fake_mailer.for_template(TEMPLATE_BUDGET)[0]["ctx"]
    assert ctx["total_usd"] == "0.000500"
    assert fake_mailer.for_template(TEMPLATE_DAILY) == [], (
        "ngưỡng ngày không được ăn theo cửa sổ 30 ngày"
    )


# ════════════ Ngân sách: thư khẩn RIÊNG + log WARNING mỗi nhịp ════════════


async def test_over_budget_sends_urgent_mail_and_logs_warning(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    fake_mailer: FakeMailer,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    user_a: uuid.UUID,
) -> None:
    """ "Việc cần làm": *"vượt `MONTHLY_BUDGET_USD` → mail khẩn + ghi log WARNING"*."""
    await _admin(session_factory)
    await _write_ledger(session_factory, user_a, cost="0.000500")
    monkeypatch.setattr(settings, "MONTHLY_BUDGET_USD", Decimal("0.0001"))

    with caplog.at_level(logging.WARNING, logger="app.workers.spend_alert"):
        await spend_alert(_ctx(fake_redis))

    assert len(fake_mailer.for_template(TEMPLATE_BUDGET)) == 1
    assert fake_mailer.for_template(TEMPLATE_DAILY) == [], "ngưỡng ngày vẫn cao, không được gửi kèm"
    assert any("VUOT NGAN SACH" in r.getMessage() for r in caplog.records)


async def test_warning_logged_every_tick_even_if_mail_deduped(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    fake_mailer: FakeMailer,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    user_a: uuid.UUID,
) -> None:
    """Log không phải hộp thư: nó là thứ còn lại khi SMTP chết (§21.1)."""
    await _admin(session_factory)
    await _write_ledger(session_factory, user_a, cost="0.000500")
    monkeypatch.setattr(settings, "MONTHLY_BUDGET_USD", Decimal("0.0001"))

    with caplog.at_level(logging.WARNING, logger="app.workers.spend_alert"):
        await spend_alert(_ctx(fake_redis))
        await spend_alert(_ctx(fake_redis))

    assert len(fake_mailer.for_template(TEMPLATE_BUDGET)) == 1
    assert sum("VUOT NGAN SACH" in r.getMessage() for r in caplog.records) == 2


async def test_two_thresholds_have_separate_flags(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    fake_mailer: FakeMailer,
    monkeypatch: pytest.MonkeyPatch,
    user_a: uuid.UUID,
) -> None:
    """Vượt cả hai ⇒ hai lá thư khác nhau, và một lá không nuốt lá kia."""
    await _admin(session_factory)
    await _write_ledger(session_factory, user_a, cost="0.000500")
    monkeypatch.setattr(settings, "DAILY_ALERT_USD", Decimal("0.0001"))
    monkeypatch.setattr(settings, "MONTHLY_BUDGET_USD", Decimal("0.0001"))

    await spend_alert(_ctx(fake_redis))

    assert len(fake_mailer.for_template(TEMPLATE_DAILY)) == 1
    assert len(fake_mailer.for_template(TEMPLATE_BUDGET)) == 1
    assert len(fake_redis.store) == 2


# ══════════════════════ đăng ký cron + template thật ══════════════════════


def test_cron_registered_hourly_not_run_on_startup() -> None:
    """Gõ `minute` thành `second` là chạy 60 lần mỗi giờ mà không ai báo."""
    job = next(c for c in CRON_JOBS if c.name == SPEND_ALERT_JOB_NAME)

    assert job.minute == set(SPEND_ALERT_MINUTES_IN_HOUR)
    # `second` KHÔNG được để `None`: arq đọc `None` là "mọi giá trị", tức 60
    # nhịp mỗi giờ. Mặc định của `arq.cron()` là `0`, và ca này ghim đúng mặc
    # định ấy — nó phải đỏ nếu một bản arq sau đổi nó thành `None`.
    assert job.second == 0, "second=None là 60 lần mỗi giờ, không phải một"
    assert job.run_at_startup is False


@pytest.mark.parametrize("template", [TEMPLATE_DAILY, TEMPLATE_BUDGET])
def test_both_templates_have_all_three_parts(template: str) -> None:
    """Thiếu tiêu đề hoặc thiếu một file là `KeyError`/`TemplateNotFound` **trong job**.

    Ở đó nó chỉ thành một dòng `logger.exception` của `_send` — tức cảnh báo
    biến mất lặng lẽ, đúng thứ cả task này sinh ra để tránh.
    """
    assert template in _SUBJECTS
    assert (TEMPLATES_DIR / f"{template}.txt").is_file()
    assert (TEMPLATES_DIR / f"{template}.html").is_file()


def test_two_mails_have_different_subjects() -> None:
    """ "Mail khẩn" chỉ phân biệt được với lá thường bằng dòng tiêu đề."""
    assert _SUBJECTS[TEMPLATE_DAILY] != _SUBJECTS[TEMPLATE_BUDGET]
