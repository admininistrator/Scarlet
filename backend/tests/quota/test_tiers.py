"""Hạn mức có hiệu lực: tier + `limit_override_json` + cache 60 s (§10.4) — T-2.10.

Postgres THẬT (NQ-17) cho phần đọc, Redis GIẢ cho phần cache. Chia đôi như vậy
là có lý do, không phải tiện tay: thứ cần kiểm ở vế Postgres là chính câu JOIN
và `deleted_at IS NULL` — hai thứ mà một fake sẽ mô phỏng bằng đúng niềm tin
của người viết test. Vế Redis thì ngược lại: thứ cần kiểm là **thứ tự các lời
gọi** (đọc cache trước, chỉ ghi sau khi đã đọc DB, và `ex` đúng bằng
`TIER_CACHE_TTL_S`), nên một fake ghi lại được từng lời gọi kiểm chặt hơn
Redis thật.

Phép đo 60 giây **thật** không nằm ở đây mà chạy trên stack bằng `docker
compose exec` (DoD dòng 1, xem báo cáo T-2.10): một `sleep(60)` trong `pytest`
là một phút chết mỗi lần chạy bộ test, đổi lại không kiểm thêm được gì mà
`ex == 60` chưa kiểm.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import settings
from app.db.models import Tier
from app.db.repositories.tiers import TierRepository
from app.quota.tiers import (
    EffectiveLimits,
    UserLimitsNotFoundError,
    get_effective_limits,
    merge_override,
    tier_cache_key,
)

TIER_FREE = "free"
TIER_TRUSTED = "trusted"


# ════════════════════════════ hạ tầng của bộ test ═══════════════════════════


class FakeRedis:
    """`get`/`set` trong bộ nhớ, ghi lại `ex` và từng lời gọi.

    Cùng tinh thần `FakeIdempotencyRedis` của `tests/api/conftest.py`: mô phỏng
    **đúng** hai lệnh mà module dùng, không hơn. `fail` bật lên để dựng lại ca
    "Redis chết" mà §10.3 nói phải đi tiếp được bằng Postgres.
    """

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.gets: list[str] = []
        self.sets: list[tuple[str, str, int | None]] = []
        self.fail = False

    async def get(self, name: str) -> str | None:
        if self.fail:
            raise ConnectionError("redis chet (gia lap)")
        self.gets.append(name)
        return self.store.get(name)

    async def set(self, name: str, value: str, *, ex: int | None = None) -> bool:
        if self.fail:
            raise ConnectionError("redis chet (gia lap)")
        self.sets.append((name, value, ex))
        self.store[name] = value
        return True


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    fake = FakeRedis()
    monkeypatch.setattr("app.quota.tiers.get_redis", lambda: fake)
    return fake


@pytest.fixture
def db_cua_test(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`session_scope()` trong `app/quota/tiers.py` trỏ vào kết nối của test (NQ-17)."""
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


def _tier_mau(**ghi_de: Any) -> Tier:
    """Một hàng `tiers` dựng trong bộ nhớ — cho phép kiểm thuần `merge_override`."""
    gia_tri: dict[str, Any] = {
        "name": TIER_FREE,
        "limit_5h_usd": Decimal("0.5000"),
        "limit_7d_usd": Decimal("3.0000"),
        "can_execute_skills": False,
        "can_use_web": True,
        "web_searches_per_day": 50,
        "max_upload_mb": 10,
        "max_attachments": 5,
        "allowed_model_tags": [],
    }
    gia_tri.update(ghi_de)
    return Tier(**gia_tri)


async def _dat_override(
    session_factory: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
    override: str,
) -> None:
    async with session_factory() as session:
        await session.execute(
            text("UPDATE users SET limit_override_json = CAST(:v AS JSONB) WHERE id = :uid"),
            {"v": override, "uid": str(user_id)},
        )
        await session.commit()


async def _dat_tier(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID, tier_name: str
) -> None:
    async with session_factory() as session:
        await session.execute(
            text("UPDATE users SET tier_name = :t WHERE id = :uid"),
            {"t": tier_name, "uid": str(user_id)},
        )
        await session.commit()


# ══════════════════════ seed của T-H6 (migration 0001) ══════════════════════


async def test_seed_hai_tier_dung_han_muc_da_chot(session: AsyncSession) -> None:
    """T-H6: `free` 0.50/3.00, `trusted` 2.00/12.00 — chốt theo đề xuất mặc định."""
    rows = (
        await session.execute(
            text(
                "SELECT name, limit_5h_usd, limit_7d_usd, can_execute_skills, is_default "
                "FROM tiers ORDER BY name"
            )
        )
    ).all()
    assert [r[0] for r in rows] == [TIER_FREE, TIER_TRUSTED]
    free, trusted = rows
    assert (free[1], free[2]) == (Decimal("0.5000"), Decimal("3.0000"))
    assert (trusted[1], trusted[2]) == (Decimal("2.0000"), Decimal("12.0000"))
    assert free[3] is False
    assert trusted[3] is True
    assert free[4] is True
    assert trusted[4] is False


# ═══════════════════════════ repository (§10.4) ═════════════════════════════


async def test_repo_tra_tier_mac_dinh_cua_user_moi(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    found = await TierRepository(session).get_for_user(user_a)
    assert found is not None
    assert found.tier.name == TIER_FREE
    assert found.override is None


async def test_repo_doc_ca_override(
    session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    await _dat_override(session_factory, user_a, '{"limit_5h_usd": 5.0}')
    async with session_factory() as session:
        found = await TierRepository(session).get_for_user(user_a)
    assert found is not None
    assert found.override == {"limit_5h_usd": 5.0}


async def test_repo_user_khong_ton_tai_tra_none(session: AsyncSession) -> None:
    assert await TierRepository(session).get_for_user(uuid.uuid4()) is None


async def test_repo_user_da_xoa_mem_tra_none(
    session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    """§20: một tài khoản vừa xoá không được cấp hạn mức, kể cả hạn mức mặc định."""
    async with session_factory() as session:
        await session.execute(
            text("UPDATE users SET deleted_at = now() WHERE id = :uid"), {"uid": str(user_a)}
        )
        await session.commit()
    async with session_factory() as session:
        assert await TierRepository(session).get_for_user(user_a) is None


# ══════════════════════════ gộp ghi đè (§10.4) ══════════════════════════════


def test_khong_co_override_thi_dung_nguyen_tier() -> None:
    assert merge_override(_tier_mau(), None) == EffectiveLimits(
        tier_name=TIER_FREE,
        limit_5h_usd=Decimal("0.5000"),
        limit_7d_usd=Decimal("3.0000"),
        can_execute_skills=False,
        can_use_web=True,
        web_searches_per_day=50,
        max_upload_mb=10,
        max_attachments=5,
        allowed_model_tags=[],
    )


def test_override_de_tung_truong_chu_khong_thay_ca_khoi() -> None:
    """§10.4: "ghi đè từng trường". Một khoá đổi một số, tám trường kia y nguyên."""
    limits = merge_override(_tier_mau(), {"limit_5h_usd": 5.0})
    assert limits.limit_5h_usd == Decimal("5.0")
    assert limits.limit_7d_usd == Decimal("3.0000")
    assert limits.max_upload_mb == 10
    assert limits.can_use_web is True


def test_override_de_duoc_ca_truong_khong_phai_tien() -> None:
    limits = merge_override(_tier_mau(), {"can_execute_skills": True, "max_attachments": 20})
    assert limits.can_execute_skills is True
    assert limits.max_attachments == 20


def test_override_khong_doi_duoc_tier_name() -> None:
    """`tier_name` ngoài `OVERRIDABLE_FIELDS` — đổi tier là sửa cột `users.tier_name`."""
    limits = merge_override(_tier_mau(), {"tier_name": TIER_TRUSTED, "limit_5h_usd": 9.0})
    assert limits.tier_name == TIER_FREE
    assert limits.limit_5h_usd == Decimal("9.0")


def test_khoa_la_bi_bo_qua_phan_con_lai_van_chay(caplog: pytest.LogCaptureFixture) -> None:
    limits = merge_override(_tier_mau(), {"khong_ton_tai": 1, "limit_5h_usd": 5.0})
    assert limits.limit_5h_usd == Decimal("5.0")
    assert "khong_ton_tai" in caplog.text


def test_override_hong_kieu_lam_roi_ca_ban_ghi_de(caplog: pytest.LogCaptureFixture) -> None:
    """Gộp nửa bản ghi đè hỏng cho ra một tập hạn mức không ai từng viết ra."""
    limits = merge_override(_tier_mau(), {"limit_5h_usd": "khong-phai-so", "max_upload_mb": 999})
    assert limits.limit_5h_usd == Decimal("0.5000")
    assert limits.max_upload_mb == 10, "bản ghi đè rơi CẢ khối, không rơi một nửa"
    assert "limit_override_json" in caplog.text


# ═══════════════════════ cache Redis TTL 60 (§10.4) ═════════════════════════


async def test_lan_dau_doc_db_roi_ghi_cache_dung_ttl(
    db_cua_test: None, fake_redis: FakeRedis, user_a: uuid.UUID
) -> None:
    limits = await get_effective_limits(user_a)
    assert limits.tier_name == TIER_FREE
    assert limits.limit_5h_usd == Decimal("0.5000")

    key = tier_cache_key(user_a)
    assert fake_redis.gets == [key]
    assert len(fake_redis.sets) == 1
    assert fake_redis.sets[0][0] == key
    assert fake_redis.sets[0][2] == settings.TIER_CACHE_TTL_S == 60


async def test_lan_hai_doc_cache_khong_ghi_lai(
    db_cua_test: None,
    fake_redis: FakeRedis,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
) -> None:
    """Cache còn sống thì một thay đổi trong DB CHƯA thấy — đó chính là cái TTL mua."""
    await get_effective_limits(user_a)
    await _dat_tier(session_factory, user_a, TIER_TRUSTED)

    lan_hai = await get_effective_limits(user_a)
    assert lan_hai.tier_name == TIER_FREE
    assert len(fake_redis.sets) == 1, "lần hai không được ghi lại cache"
    assert len(fake_redis.gets) == 2


async def test_xoa_cache_thi_doc_lai_tu_db(
    db_cua_test: None,
    fake_redis: FakeRedis,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
) -> None:
    """DoD dòng 3: xoá khoá Redis → đọc lại từ DB, không lỗi."""
    await get_effective_limits(user_a)
    await _dat_tier(session_factory, user_a, TIER_TRUSTED)
    assert (await get_effective_limits(user_a)).tier_name == TIER_FREE

    fake_redis.store.clear()

    lai = await get_effective_limits(user_a)
    assert lai.tier_name == TIER_TRUSTED
    assert lai.limit_5h_usd == Decimal("2.0000")


async def test_override_chi_doi_han_muc_cua_dung_nguoi_do(
    db_cua_test: None,
    fake_redis: FakeRedis,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
) -> None:
    """DoD dòng 2: `{"limit_5h_usd": 5.0}` cho A; B cùng tier KHÔNG đổi."""
    await _dat_override(session_factory, user_a, '{"limit_5h_usd": 5.0}')

    cua_a = await get_effective_limits(user_a)
    cua_b = await get_effective_limits(user_b)

    assert cua_a.tier_name == cua_b.tier_name == TIER_FREE
    assert cua_a.limit_5h_usd == Decimal("5.0")
    assert cua_b.limit_5h_usd == Decimal("0.5000")


async def test_hai_user_hai_khoa_cache_rieng(
    db_cua_test: None, fake_redis: FakeRedis, user_a: uuid.UUID, user_b: uuid.UUID
) -> None:
    await get_effective_limits(user_a)
    await get_effective_limits(user_b)
    assert tier_cache_key(user_a) != tier_cache_key(user_b)
    assert tier_cache_key(user_a) in fake_redis.store
    assert tier_cache_key(user_b) in fake_redis.store


async def test_user_khong_ton_tai_thi_raise_chu_khong_tra_han_muc(
    db_cua_test: None, fake_redis: FakeRedis
) -> None:
    """ "Không biết người này là ai" KHÔNG được đọc thành "không có trần chi tiêu"."""
    lac = uuid.uuid4()
    with pytest.raises(UserLimitsNotFoundError):
        await get_effective_limits(lac)
    assert tier_cache_key(lac) not in fake_redis.store


async def test_redis_chet_van_doc_duoc_han_muc(
    db_cua_test: None,
    fake_redis: FakeRedis,
    user_a: uuid.UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """§10.3: Redis là cache, Postgres là sự thật — mất cache không phải mất app."""
    fake_redis.fail = True
    limits = await get_effective_limits(user_a)
    assert limits.tier_name == TIER_FREE
    assert "cache tier" in caplog.text


async def test_cache_hong_dinh_dang_thi_nap_lai_tu_db(
    db_cua_test: None,
    fake_redis: FakeRedis,
    user_a: uuid.UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Bản cache của một phiên bản trước không được thành `500` giữa lượt chat."""
    fake_redis.store[tier_cache_key(user_a)] = '{"tier_name": "free"}'
    limits = await get_effective_limits(user_a)
    assert limits.limit_5h_usd == Decimal("0.5000")
    assert "khong doc duoc" in caplog.text


async def test_decimal_di_vong_qua_cache_van_nguyen_con_so(
    db_cua_test: None,
    fake_redis: FakeRedis,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
) -> None:
    """Tiền không được biến thành `float` khi đi vòng qua JSON."""
    await _dat_override(session_factory, user_a, '{"limit_5h_usd": 0.1234}')
    tu_db = await get_effective_limits(user_a)
    tu_cache = await get_effective_limits(user_a)
    assert tu_db.limit_5h_usd == tu_cache.limit_5h_usd == Decimal("0.1234")
    assert isinstance(tu_cache.limit_5h_usd, Decimal)
