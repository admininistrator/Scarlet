"""T-2.17 — cron `spend_alert` + `sum_since` sau B-172 (RR-1, §21.5, C16).

KH tham chiếu: RR-1, RR-13, §21.5, §10.5, §9.5/C16, S13 · CLAUDE.md A3, A7 ·
tasks.md T-2.17, B-172.

Ba dòng DoD của task được kiểm ở đây, và cả ba kiểm bằng **Postgres thật**
(fixture `session_factory` của `tests/conftest.py`, NQ-17) vì thứ đáng kiểm
nhất là câu `GROUP BY cost_confidence` có lọc đúng tập hàng không — ngữ nghĩa
của Postgres, không phải của Python. Chỉ Redis và SMTP là giả.

- **DoD 1** — `DAILY_ALERT_USD` thấp → có thư: `test_vuot_nguong_ngay_thi_gui_thu`
- **DoD 2** — chạy lần hai cùng ngày → không thư thứ hai:
  `test_chay_lan_hai_cung_ngay_khong_gui_them`
- **DoD 3** — thư ghi rõ ai tiêu nhiều nhất, bao nhiêu:
  `test_thu_ghi_ro_nguoi_tieu_nhieu_nhat`

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
from app.db.models import CostConfidence, KeySource, User, UserRole
from app.db.repositories import CostSplit, UsageEventRepository, UserRepository
from app.workers.main import CRON_JOBS
from app.workers.spend_alert import (
    BUDGET_WINDOW_DAYS,
    SPEND_ALERT_JOB_NAME,
    SPEND_ALERT_PHUT_TRONG_GIO,
    TEMPLATE_BUDGET,
    TEMPLATE_DAILY,
    day_start_utc,
    spend_alert,
)

MODEL_ID = "deepseek-flash"


# ══════════════════════════════ hạ tầng giả ══════════════════════════════


class RedisGia:
    """Đủ `set(nx=, ex=)` và `delete` — hai lệnh duy nhất của cờ chống lặp.

    `set` mô phỏng đúng ngữ nghĩa `NX` của Redis (khoá đã có ⇒ trả `None`), vì
    đó chính là thứ DoD dòng 2 đo: một bản giả luôn trả `True` sẽ cho hai lá
    thư mà mọi phép khẳng định khác vẫn xanh.
    """

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttl: dict[str, int] = {}
        self.da_xoa: list[str] = []
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
        self.da_xoa.append(name)
        return int(self.store.pop(name, None) is not None)


class MailerGia:
    """Stub `Mailer`. `hop_thu_no` làm hỏng đúng một hộp để kiểm cách ly."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.hop_thu_no: str | None = None
        self.no_het = False

    async def send(self, *, template: str, to: str, ctx: dict[str, Any]) -> None:
        if self.no_het or to == self.hop_thu_no:
            raise ConnectionError("smtp chet (gia lap)")
        self.calls.append({"template": template, "to": to, "ctx": ctx})

    def cua(self, template: str) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["template"] == template]


@pytest.fixture
def redis_gia() -> RedisGia:
    return RedisGia()


@pytest.fixture
def mailer_gia(monkeypatch: pytest.MonkeyPatch) -> MailerGia:
    """Thay `app.workers.spend_alert.mailer` — đúng tên đã import vào module đó."""
    stub = MailerGia()
    monkeypatch.setattr("app.workers.spend_alert.mailer", stub)
    return stub


@pytest.fixture(autouse=True)
def _noi_session_vao_db_test(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """`session_scope()` của job trỏ vào transaction của test — như T-1.10."""
    monkeypatch.setattr(db_session, "get_sessionmaker", lambda: session_factory)


@pytest.fixture(autouse=True)
def _nguong_cao_mac_dinh(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mặc định **không** ca nào vượt ngưỡng; ca nào cần vượt thì tự hạ xuống.

    Ngược lại thì một ca quên đặt ngưỡng sẽ xanh nhờ `.env` của người chạy
    test, và đỏ trên máy khác.
    """
    monkeypatch.setattr(settings, "DAILY_ALERT_USD", Decimal("1000"))
    monkeypatch.setattr(settings, "MONTHLY_BUDGET_USD", Decimal("1000"))


def _ctx(redis_gia: RedisGia) -> dict[str, Any]:
    return {"redis": redis_gia, "job_id": "test-cron"}


# ═══════════════════════════ dữ liệu cho test ════════════════════════════


async def _ghi_so(
    session_factory: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
    *,
    cost: str,
    confidence: CostConfidence = CostConfidence.EXACT,
    key_source: KeySource = KeySource.SYSTEM,
    tuoi_giay: float = 0.0,
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
        )
        if tuoi_giay:
            await session.execute(
                text(
                    "UPDATE usage_events SET created_at = now() - make_interval(secs => :t) "
                    "WHERE id = :id"
                ),
                {"t": tuoi_giay, "id": event.id},
            )
        await session.commit()
        return event.id


async def _admin(
    session_factory: async_sessionmaker[AsyncSession], *, email: str | None = None
) -> str:
    """Một hàng `users` với `role='admin'`. Trả về email của nó."""
    dia_chi = email or f"admin-{uuid.uuid4().hex}@scarlet.example"
    async with session_factory() as session:
        user = await UserRepository(session).create_pending_user(
            email=dia_chi, password_hash="khong-phai-hash-that"
        )
        assert user is not None
        await session.execute(update(User).where(User.id == user.id).values(role=UserRole.ADMIN))
        await session.commit()
    return dia_chi


async def _email_cua(session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID) -> str:
    async with session_factory() as session:
        nguoi = await UserRepository(session).get_by_id(user_id)
        assert nguoi is not None
        return nguoi.email


# ════════════ B-172: `sum_since` nhận `key_source`, trả hai cột ════════════


async def test_sum_since_tach_hai_cot_theo_cost_confidence(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
) -> None:
    """C16 ở tầng dữ liệu: `exact` và `low` không bao giờ đi chung một con số."""
    await _ghi_so(session_factory, user_a, cost="0.100000")
    await _ghi_so(session_factory, user_a, cost="0.030000", confidence=CostConfidence.LOW)

    split = await UsageEventRepository(session).sum_since(
        user_id=user_a, since=datetime.now(UTC) - timedelta(hours=1), key_source=None
    )

    assert split == CostSplit(exact=Decimal("0.100000"), low=Decimal("0.030000"))


def test_cost_split_khong_co_truong_tong() -> None:
    """C16 — `HaiCot` của T-2.16 cũng không có, và vì cùng một lý do.

    Một trường `total` tiện tay thì sẽ có người dùng, và chỗ dùng đầu tiên sẽ
    là chỗ hai cột im lặng nhập lại làm một. Phép cộng duy nhất được phép nằm
    ở `spend_alert._combined`, một cái tên `grep` ra được.
    """
    assert {f for f in CostSplit.__dataclass_fields__} == {"exact", "low"}
    assert not hasattr(CostSplit(exact=Decimal(1), low=Decimal(2)), "total")


async def test_sum_since_loc_key_source_khi_duoc_yeu_cau(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
) -> None:
    """NQ-62 — cùng một người, cùng một cửa sổ, hai câu trả lời khác nhau."""
    await _ghi_so(session_factory, user_a, cost="0.100000")
    await _ghi_so(session_factory, user_a, cost="0.070000", key_source=KeySource.BYOK)
    repo = UsageEventRepository(session)
    since = datetime.now(UTC) - timedelta(hours=1)

    chi_system = await repo.sum_since(user_id=user_a, since=since, key_source=KeySource.SYSTEM)
    ca_hai = await repo.sum_since(user_id=user_a, since=since, key_source=None)

    assert chi_system.exact == Decimal("0.100000")
    assert ca_hai.exact == Decimal("0.170000")


async def test_sum_since_loc_user_id_trong_sql(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
) -> None:
    """§20 — tiền của B không được lọt vào câu trả lời cho A."""
    await _ghi_so(session_factory, user_a, cost="0.010000")
    await _ghi_so(session_factory, user_b, cost="0.990000")

    split = await UsageEventRepository(session).sum_since(
        user_id=user_a,
        since=datetime.now(UTC) - timedelta(hours=1),
        key_source=KeySource.SYSTEM,
    )

    assert split.exact == Decimal("0.010000")


async def test_sum_since_loc_bien_thoi_gian(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
) -> None:
    """Dòng sổ ngoài cửa sổ không được cộng vào."""
    await _ghi_so(session_factory, user_a, cost="0.500000", tuoi_giay=7200)
    await _ghi_so(session_factory, user_a, cost="0.020000")

    split = await UsageEventRepository(session).sum_since(
        user_id=user_a,
        since=datetime.now(UTC) - timedelta(hours=1),
        key_source=KeySource.SYSTEM,
    )

    assert split.exact == Decimal("0.020000")


async def test_sum_since_nguoi_chua_tieu_gi_ra_hai_so_khong(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """Tập rỗng ⇒ `Decimal(0)`, không phải `None`: chỗ gọi cộng thẳng vào tổng."""
    split = await UsageEventRepository(session).sum_since(
        user_id=user_a, since=datetime.now(UTC), key_source=KeySource.SYSTEM
    )

    assert split == CostSplit(exact=Decimal(0), low=Decimal(0))


async def test_list_admins_chi_tra_admin_chua_xoa(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
) -> None:
    """Người nhận thư đọc từ bảng `users`, không từ một biến `.env`."""
    dia_chi = await _admin(session_factory)
    da_xoa = await _admin(session_factory)
    async with session_factory() as khac:
        await khac.execute(
            update(User).where(User.email == da_xoa).values(deleted_at=datetime.now(UTC))
        )
        await khac.commit()

    emails = [u.email for u in await UserRepository(session).list_admins()]

    assert emails == [dia_chi], "user thường hoặc admin đã xoá lọt vào danh sách nhận thư"


# ═══════════════════ DoD dòng 1 — vượt ngưỡng thì có thư ═══════════════════


async def test_vuot_nguong_ngay_thi_gui_thu(
    session_factory: async_sessionmaker[AsyncSession],
    redis_gia: RedisGia,
    mailer_gia: MailerGia,
    monkeypatch: pytest.MonkeyPatch,
    user_a: uuid.UUID,
) -> None:
    """DoD dòng 1: hạ `DAILY_ALERT_USD` → chạy cron → có thư."""
    dia_chi = await _admin(session_factory)
    await _ghi_so(session_factory, user_a, cost="0.000500")
    monkeypatch.setattr(settings, "DAILY_ALERT_USD", Decimal("0.0001"))

    await spend_alert(_ctx(redis_gia))

    gui = mailer_gia.cua(TEMPLATE_DAILY)
    assert len(gui) == 1
    assert gui[0]["to"] == dia_chi
    assert gui[0]["ctx"]["total_usd"] == "0.000500"
    assert gui[0]["ctx"]["limit_usd"] == "0.000100"


async def test_duoi_nguong_thi_khong_gui_gi(
    session_factory: async_sessionmaker[AsyncSession],
    redis_gia: RedisGia,
    mailer_gia: MailerGia,
    monkeypatch: pytest.MonkeyPatch,
    user_a: uuid.UUID,
) -> None:
    """`>` chứ không `>=`: đúng bằng ngưỡng thì chưa phải "vượt"."""
    await _admin(session_factory)
    await _ghi_so(session_factory, user_a, cost="0.000500")
    monkeypatch.setattr(settings, "DAILY_ALERT_USD", Decimal("0.000500"))

    await spend_alert(_ctx(redis_gia))

    assert mailer_gia.calls == []
    assert redis_gia.store == {}


# ══════════ DoD dòng 2 — chống lặp: 24 nhịp một ngày, một lá thư ══════════


async def test_chay_lan_hai_cung_ngay_khong_gui_them(
    session_factory: async_sessionmaker[AsyncSession],
    redis_gia: RedisGia,
    mailer_gia: MailerGia,
    monkeypatch: pytest.MonkeyPatch,
    user_a: uuid.UUID,
) -> None:
    """DoD dòng 2 — và Cạm bẫy của task: cảnh báo bị lọc là cảnh báo không có."""
    await _admin(session_factory)
    await _ghi_so(session_factory, user_a, cost="0.000500")
    monkeypatch.setattr(settings, "DAILY_ALERT_USD", Decimal("0.0001"))

    await spend_alert(_ctx(redis_gia))
    await spend_alert(_ctx(redis_gia))
    await spend_alert(_ctx(redis_gia))

    assert len(mailer_gia.cua(TEMPLATE_DAILY)) == 1
    khoa = f"alert:{TEMPLATE_DAILY}:{datetime.now(UTC).date().isoformat()}"
    assert khoa in redis_gia.store, "cờ chống lặp phải mang NGÀY trong tên khoá"
    assert redis_gia.ttl[khoa] > 86400, "TTL ngắn hơn một ngày là cảnh báo lặp lúc nửa đêm"


async def test_co_chong_lap_duoc_nha_ra_khi_khong_gui_duoc_la_nao(
    session_factory: async_sessionmaker[AsyncSession],
    redis_gia: RedisGia,
    mailer_gia: MailerGia,
    monkeypatch: pytest.MonkeyPatch,
    user_a: uuid.UUID,
) -> None:
    """SMTP chết ⇒ giờ sau phải thử lại, không im lặng mất cảnh báo cả ngày."""
    await _admin(session_factory)
    await _ghi_so(session_factory, user_a, cost="0.000500")
    monkeypatch.setattr(settings, "DAILY_ALERT_USD", Decimal("0.0001"))
    mailer_gia.no_het = True

    await spend_alert(_ctx(redis_gia))
    assert redis_gia.store == {}, "giữ cờ sau khi gửi hỏng là mất cảnh báo cả ngày"

    mailer_gia.no_het = False
    await spend_alert(_ctx(redis_gia))

    assert len(mailer_gia.cua(TEMPLATE_DAILY)) == 1


async def test_mot_hop_thu_hong_khong_chan_hop_con_lai(
    session_factory: async_sessionmaker[AsyncSession],
    redis_gia: RedisGia,
    mailer_gia: MailerGia,
    monkeypatch: pytest.MonkeyPatch,
    user_a: uuid.UUID,
) -> None:
    """Cùng luật cách ly với `reaper._bao_cho_client`."""
    hong = await _admin(session_factory, email="admin-hong@scarlet.example")
    lanh = await _admin(session_factory, email="admin-lanh@scarlet.example")
    await _ghi_so(session_factory, user_a, cost="0.000500")
    monkeypatch.setattr(settings, "DAILY_ALERT_USD", Decimal("0.0001"))
    mailer_gia.hop_thu_no = hong

    await spend_alert(_ctx(redis_gia))

    assert [c["to"] for c in mailer_gia.cua(TEMPLATE_DAILY)] == [lanh]
    assert redis_gia.store != {}, "gửi được một lá thì cờ phải giữ"


async def test_redis_chet_thi_khong_gui_thu(
    session_factory: async_sessionmaker[AsyncSession],
    redis_gia: RedisGia,
    mailer_gia: MailerGia,
    monkeypatch: pytest.MonkeyPatch,
    user_a: uuid.UUID,
) -> None:
    """Không đặt được cờ ⇒ coi như đã gửi. Ngả kia là đúng 24 lá một ngày."""
    await _admin(session_factory)
    await _ghi_so(session_factory, user_a, cost="0.000500")
    monkeypatch.setattr(settings, "DAILY_ALERT_USD", Decimal("0.0001"))
    redis_gia.fail = True

    await spend_alert(_ctx(redis_gia))

    assert mailer_gia.calls == []


async def test_khong_co_admin_thi_khong_giu_co(
    session_factory: async_sessionmaker[AsyncSession],
    redis_gia: RedisGia,
    mailer_gia: MailerGia,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    user_a: uuid.UUID,
) -> None:
    """Không có ai để gửi là sự cố cấu hình — mỗi nhịp phải nói lại."""
    await _ghi_so(session_factory, user_a, cost="0.000500")
    monkeypatch.setattr(settings, "DAILY_ALERT_USD", Decimal("0.0001"))

    with caplog.at_level(logging.WARNING, logger="app.workers.spend_alert"):
        await spend_alert(_ctx(redis_gia))

    assert mailer_gia.calls == []
    assert redis_gia.store == {}
    assert any("role='admin'" in r.getMessage() for r in caplog.records)


# ═════════════ DoD dòng 3 — thư nói ai tiêu nhiều nhất, bao nhiêu ═════════════


async def test_thu_ghi_ro_nguoi_tieu_nhieu_nhat(
    session_factory: async_sessionmaker[AsyncSession],
    redis_gia: RedisGia,
    mailer_gia: MailerGia,
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
    await _ghi_so(session_factory, user_a, cost="0.000100")
    await _ghi_so(session_factory, user_a, cost="0.000100")
    await _ghi_so(session_factory, user_b, cost="0.000300")
    monkeypatch.setattr(settings, "DAILY_ALERT_USD", Decimal("0.0001"))

    await spend_alert(_ctx(redis_gia))

    ctx = mailer_gia.cua(TEMPLATE_DAILY)[0]["ctx"]
    assert ctx["top_email"] == await _email_cua(session_factory, user_b)
    assert ctx["top_usd"] == "0.000300"
    assert ctx["total_usd"] == "0.000500"


async def test_nguoi_tieu_nhieu_nhat_cong_ca_nhieu_dong_so(
    session_factory: async_sessionmaker[AsyncSession],
    redis_gia: RedisGia,
    mailer_gia: MailerGia,
    monkeypatch: pytest.MonkeyPatch,
    user_a: uuid.UUID,
    user_b: uuid.UUID,
) -> None:
    """Chiều ngược của ca trên: A tiêu nhiều **lần nhỏ** nhưng tổng lớn hơn."""
    await _admin(session_factory)
    for _ in range(4):
        await _ghi_so(session_factory, user_a, cost="0.000100")
    await _ghi_so(session_factory, user_b, cost="0.000300")
    monkeypatch.setattr(settings, "DAILY_ALERT_USD", Decimal("0.0001"))

    await spend_alert(_ctx(redis_gia))

    ctx = mailer_gia.cua(TEMPLATE_DAILY)[0]["ctx"]
    assert ctx["top_email"] == await _email_cua(session_factory, user_a)
    assert ctx["top_usd"] == "0.000400"


# ════════════════ NQ-62 — chỉ đếm tiền của người vận hành ════════════════


async def test_tien_byok_khong_lam_chuong_keu(
    session_factory: async_sessionmaker[AsyncSession],
    redis_gia: RedisGia,
    mailer_gia: MailerGia,
    monkeypatch: pytest.MonkeyPatch,
    user_a: uuid.UUID,
) -> None:
    """NQ-62 (B-172) — §10.5: khoản BYOK không nằm trên hoá đơn của người vận hành."""
    await _admin(session_factory)
    await _ghi_so(session_factory, user_a, cost="9.000000", key_source=KeySource.BYOK)
    monkeypatch.setattr(settings, "DAILY_ALERT_USD", Decimal("0.0001"))

    await spend_alert(_ctx(redis_gia))

    assert mailer_gia.calls == [], "tiền người dùng tự trả đã bị tính vào ngân sách"


async def test_byok_khong_lot_vao_tong_khi_van_co_tien_system(
    session_factory: async_sessionmaker[AsyncSession],
    redis_gia: RedisGia,
    mailer_gia: MailerGia,
    monkeypatch: pytest.MonkeyPatch,
    user_a: uuid.UUID,
) -> None:
    """Ca trên một mình không đủ: nó cũng xanh khi job **không gửi gì cả**."""
    await _admin(session_factory)
    await _ghi_so(session_factory, user_a, cost="0.000500")
    await _ghi_so(session_factory, user_a, cost="9.000000", key_source=KeySource.BYOK)
    monkeypatch.setattr(settings, "DAILY_ALERT_USD", Decimal("0.0001"))

    await spend_alert(_ctx(redis_gia))

    ctx = mailer_gia.cua(TEMPLATE_DAILY)[0]["ctx"]
    assert ctx["total_usd"] == "0.000500"
    assert ctx["top_usd"] == "0.000500"


# ═══════ NQ-65 — `low` tính vào ngưỡng, nhưng thư in tách hai con số ═══════


async def test_dong_uoc_luong_van_lam_chuong_keu(
    session_factory: async_sessionmaker[AsyncSession],
    redis_gia: RedisGia,
    mailer_gia: MailerGia,
    monkeypatch: pytest.MonkeyPatch,
    user_a: uuid.UUID,
) -> None:
    """NQ-65 — kẻ lạm dụng chỉ dùng model qua 9Router (§9.5) vẫn phải bị bắt."""
    await _admin(session_factory)
    await _ghi_so(session_factory, user_a, cost="0.000500", confidence=CostConfidence.LOW)
    monkeypatch.setattr(settings, "DAILY_ALERT_USD", Decimal("0.0001"))

    await spend_alert(_ctx(redis_gia))

    ctx = mailer_gia.cua(TEMPLATE_DAILY)[0]["ctx"]
    assert ctx["total_usd"] == "0.000500"
    assert ctx["exact_usd"] == "0.000000"
    assert ctx["low_usd"] == "0.000500"


async def test_thu_luon_in_tach_hai_cot(
    session_factory: async_sessionmaker[AsyncSession],
    redis_gia: RedisGia,
    mailer_gia: MailerGia,
    monkeypatch: pytest.MonkeyPatch,
    user_a: uuid.UUID,
) -> None:
    """C16 — con số gộp chỉ được phép đứng cạnh hai con số thành phần."""
    await _admin(session_factory)
    await _ghi_so(session_factory, user_a, cost="0.000300")
    await _ghi_so(session_factory, user_a, cost="0.000200", confidence=CostConfidence.LOW)
    monkeypatch.setattr(settings, "DAILY_ALERT_USD", Decimal("0.0001"))

    await spend_alert(_ctx(redis_gia))

    ctx = mailer_gia.cua(TEMPLATE_DAILY)[0]["ctx"]
    assert (ctx["exact_usd"], ctx["low_usd"], ctx["total_usd"]) == (
        "0.000300",
        "0.000200",
        "0.000500",
    )


# ═══════════ NQ-64 — hai cửa sổ: nửa đêm UTC và 30 ngày trượt ═══════════


async def test_cua_so_ngay_bat_dau_tu_nua_dem_utc(
    session_factory: async_sessionmaker[AsyncSession],
    redis_gia: RedisGia,
    mailer_gia: MailerGia,
    monkeypatch: pytest.MonkeyPatch,
    user_a: uuid.UUID,
) -> None:
    """Chi tiêu của **hôm qua** không được tính vào ngưỡng ngày.

    Dòng sổ lùi 25 giờ nên nó nằm ngoài cửa sổ ở mọi giờ trong ngày, kể cả khi
    bộ test chạy lúc 00:30 UTC — một phép lùi 2 giờ sẽ nhấp nháy theo đồng hồ.
    """
    await _admin(session_factory)
    await _ghi_so(session_factory, user_a, cost="9.000000", tuoi_giay=25 * 3600)
    monkeypatch.setattr(settings, "DAILY_ALERT_USD", Decimal("0.0001"))

    await spend_alert(_ctx(redis_gia))

    assert mailer_gia.cua(TEMPLATE_DAILY) == []


@pytest.mark.parametrize(
    ("moc", "mong_doi"),
    [
        # Giữa ngày — chỗ `now - 1 ngày` sai nhiều nhất.
        (datetime(2026, 9, 19, 14, 30, 45, 123456, tzinfo=UTC), datetime(2026, 9, 19, tzinfo=UTC)),
        # Đúng nửa đêm: biên là `>=`, nên chính nó phải thuộc về ngày của nó.
        (datetime(2026, 9, 19, 0, 0, tzinfo=UTC), datetime(2026, 9, 19, tzinfo=UTC)),
        # Một giây trước nửa đêm: vẫn là ngày hôm trước.
        (datetime(2026, 9, 18, 23, 59, 59, tzinfo=UTC), datetime(2026, 9, 18, tzinfo=UTC)),
    ],
)
def test_bien_duoi_cua_ngay_la_nua_dem_utc(moc: datetime, mong_doi: datetime) -> None:
    """ "Hôm nay" là một NGÀY, không phải một cửa sổ 24 giờ trượt.

    Hai công thức chỉ khác nhau tuỳ **giờ** lúc job chạy, nên phép kiểm này
    phải nhận một `now` cố định — đo qua job sẽ xanh hay đỏ theo đồng hồ của
    người chạy test. Ca giữa ngày là ca `now - timedelta(days=1)` trả về
    `2026-09-18 14:30`, tức nuốt nửa ngày hôm qua vào ngưỡng của hôm nay.
    """
    assert day_start_utc(moc) == mong_doi


async def test_cua_so_ngan_sach_la_ba_muoi_ngay_truot(
    session_factory: async_sessionmaker[AsyncSession],
    redis_gia: RedisGia,
    mailer_gia: MailerGia,
    monkeypatch: pytest.MonkeyPatch,
    user_a: uuid.UUID,
) -> None:
    """NQ-64 — dòng sổ 20 ngày trước VẪN tính, dòng 31 ngày trước thì không."""
    await _admin(session_factory)
    await _ghi_so(session_factory, user_a, cost="0.000500", tuoi_giay=20 * 86400)
    await _ghi_so(
        session_factory, user_a, cost="9.000000", tuoi_giay=(BUDGET_WINDOW_DAYS + 1) * 86400
    )
    monkeypatch.setattr(settings, "MONTHLY_BUDGET_USD", Decimal("0.0001"))

    await spend_alert(_ctx(redis_gia))

    ctx = mailer_gia.cua(TEMPLATE_BUDGET)[0]["ctx"]
    assert ctx["total_usd"] == "0.000500"
    assert mailer_gia.cua(TEMPLATE_DAILY) == [], "ngưỡng ngày không được ăn theo cửa sổ 30 ngày"


# ════════════ Ngân sách: thư khẩn RIÊNG + log WARNING mỗi nhịp ════════════


async def test_vuot_ngan_sach_gui_thu_khan_va_ghi_log_warning(
    session_factory: async_sessionmaker[AsyncSession],
    redis_gia: RedisGia,
    mailer_gia: MailerGia,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    user_a: uuid.UUID,
) -> None:
    """ "Việc cần làm": *"vượt `MONTHLY_BUDGET_USD` → mail khẩn + ghi log WARNING"*."""
    await _admin(session_factory)
    await _ghi_so(session_factory, user_a, cost="0.000500")
    monkeypatch.setattr(settings, "MONTHLY_BUDGET_USD", Decimal("0.0001"))

    with caplog.at_level(logging.WARNING, logger="app.workers.spend_alert"):
        await spend_alert(_ctx(redis_gia))

    assert len(mailer_gia.cua(TEMPLATE_BUDGET)) == 1
    assert mailer_gia.cua(TEMPLATE_DAILY) == [], "ngưỡng ngày vẫn cao, không được gửi kèm"
    assert any("VUOT NGAN SACH" in r.getMessage() for r in caplog.records)


async def test_log_warning_ghi_moi_nhip_du_thu_da_chong_lap(
    session_factory: async_sessionmaker[AsyncSession],
    redis_gia: RedisGia,
    mailer_gia: MailerGia,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    user_a: uuid.UUID,
) -> None:
    """Log không phải hộp thư: nó là thứ còn lại khi SMTP chết (§21.1)."""
    await _admin(session_factory)
    await _ghi_so(session_factory, user_a, cost="0.000500")
    monkeypatch.setattr(settings, "MONTHLY_BUDGET_USD", Decimal("0.0001"))

    with caplog.at_level(logging.WARNING, logger="app.workers.spend_alert"):
        await spend_alert(_ctx(redis_gia))
        await spend_alert(_ctx(redis_gia))

    assert len(mailer_gia.cua(TEMPLATE_BUDGET)) == 1
    assert sum("VUOT NGAN SACH" in r.getMessage() for r in caplog.records) == 2


async def test_hai_nguong_co_hai_co_rieng(
    session_factory: async_sessionmaker[AsyncSession],
    redis_gia: RedisGia,
    mailer_gia: MailerGia,
    monkeypatch: pytest.MonkeyPatch,
    user_a: uuid.UUID,
) -> None:
    """Vượt cả hai ⇒ hai lá thư khác nhau, và một lá không nuốt lá kia."""
    await _admin(session_factory)
    await _ghi_so(session_factory, user_a, cost="0.000500")
    monkeypatch.setattr(settings, "DAILY_ALERT_USD", Decimal("0.0001"))
    monkeypatch.setattr(settings, "MONTHLY_BUDGET_USD", Decimal("0.0001"))

    await spend_alert(_ctx(redis_gia))

    assert len(mailer_gia.cua(TEMPLATE_DAILY)) == 1
    assert len(mailer_gia.cua(TEMPLATE_BUDGET)) == 1
    assert len(redis_gia.store) == 2


# ══════════════════════ đăng ký cron + template thật ══════════════════════


def test_cron_dang_ky_hang_gio_khong_chay_luc_khoi_dong() -> None:
    """Gõ `minute` thành `second` là chạy 60 lần mỗi giờ mà không ai báo."""
    job = next(c for c in CRON_JOBS if c.name == SPEND_ALERT_JOB_NAME)

    assert job.minute == set(SPEND_ALERT_PHUT_TRONG_GIO)
    # `second` KHÔNG được để `None`: arq đọc `None` là "mọi giá trị", tức 60
    # nhịp mỗi giờ. Mặc định của `arq.cron()` là `0`, và ca này ghim đúng mặc
    # định ấy — nó phải đỏ nếu một bản arq sau đổi nó thành `None`.
    assert job.second == 0, "second=None là 60 lần mỗi giờ, không phải một"
    assert job.run_at_startup is False


@pytest.mark.parametrize("template", [TEMPLATE_DAILY, TEMPLATE_BUDGET])
def test_hai_template_co_du_ba_manh(template: str) -> None:
    """Thiếu tiêu đề hoặc thiếu một file là `KeyError`/`TemplateNotFound` **trong job**.

    Ở đó nó chỉ thành một dòng `logger.exception` của `_send` — tức cảnh báo
    biến mất lặng lẽ, đúng thứ cả task này sinh ra để tránh.
    """
    assert template in _SUBJECTS
    assert (TEMPLATES_DIR / f"{template}.txt").is_file()
    assert (TEMPLATES_DIR / f"{template}.html").is_file()


def test_hai_thu_co_hai_tieu_de_khac_nhau() -> None:
    """ "Mail khẩn" chỉ phân biệt được với lá thường bằng dòng tiêu đề."""
    assert _SUBJECTS[TEMPLATE_DAILY] != _SUBJECTS[TEMPLATE_BUDGET]
