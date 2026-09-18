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

MODEL_CO_GIA = "deepseek-flash"
MODEL_KHONG_GIA = "nr-gemini-flash"


def _model(model_id: str) -> catalog.ModelEntry:
    model = catalog.get_model(model_id)
    assert model is not None, model_id
    return model


# ═══════════════════ phần thuần tính toán: est_max (§10.2) ══════════════════


def test_est_max_tinh_theo_max_output_chu_khong_theo_do_dai_cau_hoi() -> None:
    """Cạm bẫy của task: ước tính lạc quan = một câu hỏi vượt hạn mức hàng chục lần."""
    model = _model(MODEL_CO_GIA)
    gia = catalog.get_catalog().effective_pricing(model.id)
    assert gia is not None

    du_toan = estimate_from_tokens(model, 1000)

    mong_doi = (
        Decimal(1000) * Decimal(str(gia.input_per_1m))
        + Decimal(model.max_output) * Decimal(str(gia.output_per_1m))
    ) / Decimal(1_000_000)
    assert du_toan.est_max_usd == mong_doi
    assert du_toan.max_output_tokens == model.max_output


def test_phan_output_chiem_gan_het_du_toan_cua_mot_cau_hoi_ngan() -> None:
    """Phép kiểm ngược của test trên: bỏ `max_output` thì con số tụt hàng chục lần."""
    model = _model(MODEL_CO_GIA)
    chi_prompt = estimate_from_tokens(model, 1000).est_max_usd
    gia = catalog.get_catalog().effective_pricing(model.id)
    assert gia is not None
    chi_co_prompt = Decimal(1000) * Decimal(str(gia.input_per_1m)) / Decimal(1_000_000)
    assert chi_prompt > chi_co_prompt * 10


def test_model_khong_co_gia_ra_0_va_priced_false() -> None:
    """B-65/NQ-52: không có ngoại lệ nào, chỉ là giá bằng `None` ⇒ `est_max` = 0."""
    du_toan = estimate_from_tokens(_model(MODEL_KHONG_GIA), 5000)
    assert du_toan.est_max_usd == Decimal(0)
    assert du_toan.priced is False


def test_prompt_overhead_cong_vao_est_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """~2000 token 9Router bơm vào mọi request (B-65) phải vào dự toán."""
    model = _model(MODEL_CO_GIA)
    khong_phu_phi = estimate_from_tokens(model, 1000)
    monkeypatch.setattr(catalog.Catalog, "prompt_overhead_tokens", lambda self, mid: 2000)
    co_phu_phi = estimate_from_tokens(model, 1000)

    assert co_phu_phi.est_in_tokens == khong_phu_phi.est_in_tokens + 2000
    assert co_phu_phi.est_max_usd > khong_phu_phi.est_max_usd


def test_estimate_dem_ca_system_prompt_va_khung_message() -> None:
    model = _model(MODEL_CO_GIA)
    du_toan = estimate(model, [{"role": "user", "content": "xin chao"}])
    assert du_toan.est_in_tokens > 0
    assert du_toan.model_id == model.id


# ═════════════════════ cửa chặn: 429, retry_after, cảnh báo ═════════════════


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
            model_id=MODEL_CO_GIA,
        )
        await session.commit()
        return tra_loi.id


@pytest.fixture
def _quota_redis(monkeypatch: pytest.MonkeyPatch, quota_redis_fake: Any) -> Any:
    """Cùng bản vá mà `tests/api/conftest.py` gắn autouse, nhưng cho bộ test này."""
    monkeypatch.setattr("app.quota.estimator.get_redis", lambda: quota_redis_fake)
    monkeypatch.setattr("app.quota.tiers.get_redis", lambda: quota_redis_fake)
    return quota_redis_fake


@pytest.fixture
def _db_cua_test(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


def _nap_chi_tieu(redis: Any, user_id: uuid.UUID, *muc: tuple[float, str]) -> None:
    for window in (Window(LimitType.SHORT, settings.QUOTA_WINDOW_SHORT_S),):
        redis.zset[window.key(user_id)] = {
            encode_member(uuid.uuid4(), Decimal(cost)): score for score, cost in muc
        }


async def test_chua_tieu_gi_thi_di_qua_va_khong_canh_bao(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_cua_test: None,
) -> None:
    leaf = await _cay_mot_luot(session_factory, user_a)
    async with session_factory() as session:
        canh_bao = await check_quota(
            session, user_id=user_a, leaf_id=leaf, model=_model(MODEL_CO_GIA)
        )
    assert canh_bao is None


async def test_han_muc_5h_het_thi_429_kem_limit_type_va_retry_after(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_cua_test: None,
) -> None:
    """UC-07 dòng 3 + DoD dòng 2 và 3."""
    leaf = await _cay_mot_luot(session_factory, user_a)
    # Tier `free` có `limit_5h_usd = 0.50`; nạp 0.50 là đã chạm trần.
    now = time.time()
    _nap_chi_tieu(_quota_redis, user_a, (now - 17000, "0.50"))

    async with session_factory() as session:
        with pytest.raises(ApiError) as exc:
            await check_quota(session, user_id=user_a, leaf_id=leaf, model=_model(MODEL_CO_GIA))

    loi = exc.value
    assert loi.status_code == 429
    assert loi.code is ApiErrorCode.QUOTA_EXCEEDED
    assert loi.details["limit_type"] == "5h"
    # Phần tử duy nhất rơi khỏi cửa sổ 18000 s sau 1000 s nữa (±1 s làm tròn).
    assert 999 <= loi.details["retry_after"] <= 1001
    assert loi.headers is not None and loi.headers["Retry-After"] == str(loi.details["retry_after"])


async def test_han_muc_tuan_het_thi_limit_type_la_weekly(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_cua_test: None,
) -> None:
    """DoD dòng 3: body phân biệt được `5h` với `weekly`."""
    leaf = await _cay_mot_luot(session_factory, user_a)
    now = time.time()
    # Cửa sổ 5 giờ rỗng, cửa sổ tuần đã tiêu hết 3.00 USD của tier `free`.
    window = Window(LimitType.LONG, settings.QUOTA_WINDOW_LONG_S)
    _quota_redis.zset[window.key(user_a)] = {
        encode_member(uuid.uuid4(), Decimal("3.00")): now - 600000
    }

    async with session_factory() as session:
        with pytest.raises(ApiError) as exc:
            await check_quota(session, user_id=user_a, leaf_id=leaf, model=_model(MODEL_CO_GIA))
    assert exc.value.details["limit_type"] == "weekly"


async def test_mot_luot_don_le_vuot_tran_thi_retry_after_la_none(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_cua_test: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ca của DoD dòng 1 (`limit_5h_usd = 0.001`): nhả cả cửa sổ cũng không đủ."""
    leaf = await _cay_mot_luot(session_factory, user_a)
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
            await check_quota(session, user_id=user_a, leaf_id=leaf, model=_model(MODEL_CO_GIA))

    assert exc.value.details["retry_after"] is None
    # KHÔNG đặt `Retry-After`: không có con số thật nào để đặt.
    assert not (exc.value.headers or {}).get("Retry-After")


async def test_model_khong_co_gia_di_qua_ca_khi_han_muc_bang_0(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_cua_test: None,
) -> None:
    """B-65/NQ-52 nhìn từ phía cửa chặn: không có giá ⇒ không có gì để trừ."""
    leaf = await _cay_mot_luot(session_factory, user_a)
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
        canh_bao = await check_quota(
            session, user_id=user_a, leaf_id=leaf, model=_model(MODEL_KHONG_GIA)
        )
    assert canh_bao is None


async def test_con_15_phan_tram_thi_di_qua_kem_canh_bao(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_cua_test: None,
) -> None:
    """DoD dòng 4 + UC-07 dòng 1. Tier `free`: 0.50 USD/5 h ⇒ tiêu 0.425 là còn 15%."""
    leaf = await _cay_mot_luot(session_factory, user_a)
    _nap_chi_tieu(_quota_redis, user_a, (time.time() - 60, "0.425"))

    async with session_factory() as session:
        canh_bao = await check_quota(
            session, user_id=user_a, leaf_id=leaf, model=_model(MODEL_KHONG_GIA)
        )

    assert canh_bao is not None
    assert canh_bao.limit_type is LimitType.SHORT
    assert canh_bao.remaining_pct == 15
    assert canh_bao.spent_usd == Decimal("0.425")
    assert canh_bao.remaining_usd == Decimal("0.075")


async def test_nguong_canh_bao_doc_tu_settings(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_cua_test: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A3: 20% là cấu hình, không phải một số ma trong `estimator.py`."""
    leaf = await _cay_mot_luot(session_factory, user_a)
    _nap_chi_tieu(_quota_redis, user_a, (time.time() - 60, "0.425"))
    monkeypatch.setattr(settings, "QUOTA_WARN_REMAINING_PCT", 10)

    async with session_factory() as session:
        canh_bao = await check_quota(
            session, user_id=user_a, leaf_id=leaf, model=_model(MODEL_KHONG_GIA)
        )
    assert canh_bao is None


async def test_redis_chet_thi_503_chu_khong_cho_qua(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_cua_test: None,
) -> None:
    """Không hỏi được Redis = không biết còn bao nhiêu tiền. Cho qua là gỡ P2."""
    leaf = await _cay_mot_luot(session_factory, user_a)
    _quota_redis.fail = True

    async with session_factory() as session:
        with pytest.raises(ApiError) as exc:
            await check_quota(session, user_id=user_a, leaf_id=leaf, model=_model(MODEL_CO_GIA))
    assert exc.value.status_code == 503


async def test_ngu_canh_dung_khong_noi_thi_du_toan_theo_tran_ngan_sach(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_cua_test: None,
) -> None:
    """Không ước tính được **không** được đọc thành "không tốn gì".

    Đo bằng hai chiều dưới **cùng một** hạn mức, vì một chiều không chứng minh
    được gì: hạn mức 0.015 USD nằm giữa dự toán của một câu hỏi thật (~0.005–
    0.010 USD tuỳ khung giờ của `deepseek-flash`) và dự toán theo trần ngân
    sách §9.6 (118 808 token ⇒ ~0.023–0.045 USD). Lá có thật đi qua; lá không
    tồn tại — tức `context.build()` ném và đường lùi chạy — bị chặn.
    """
    leaf = await _cay_mot_luot(session_factory, user_a)
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
            await check_quota(session, user_id=user_a, leaf_id=leaf, model=_model(MODEL_CO_GIA))
            is None
        )

    async with session_factory() as session:
        with pytest.raises(ApiError) as exc:
            await check_quota(
                session, user_id=user_a, leaf_id=uuid.uuid4(), model=_model(MODEL_CO_GIA)
            )
    assert exc.value.code is ApiErrorCode.QUOTA_EXCEEDED
