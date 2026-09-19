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
from app.db.models import CostConfidence, KeySource, MessageRole
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
MODEL_CO_GIA = "deepseek-flash"

#: Vài mốc tuổi, tính bằng giây, đặt tên để mỗi test nói được nó đang kiểm ca
#: nào. `QUOTA_WINDOW_SHORT_S` mặc định 18000 (5 giờ), `LONG` 604800 (7 ngày).
TRONG_5H = 3600
NGOAI_5H_TRONG_TUAN = 6 * 3600
NGOAI_CA_HAI = 8 * 24 * 3600


def _model(model_id: str = MODEL_CO_GIA) -> catalog.ModelEntry:
    model = catalog.get_model(model_id)
    assert model is not None, model_id
    return model


async def _ghi_so(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    cost: str,
    tuoi_giay: float = 0.0,
    key_source: KeySource = KeySource.SYSTEM,
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
        model_id=MODEL_CO_GIA,
        provider="deepseek",
        key_source=key_source,
        prompt_tokens=100,
        completion_tokens=10,
        cached_tokens=0,
        cost_usd=Decimal(cost),
        cost_confidence=CostConfidence.EXACT,
        price_snapshot={"source": "catalog"},
    )
    if tuoi_giay:
        await session.execute(
            text(
                "UPDATE usage_events SET created_at = now() - make_interval(secs => :t) "
                "WHERE id = :id"
            ),
            {"t": tuoi_giay, "id": event.id},
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


def _tong(redis: Any, limit_type: LimitType, user_id: uuid.UUID) -> Decimal:
    return sum(
        (parse_member(m) or Decimal(0) for m in _zset(redis, limit_type, user_id)),
        Decimal(0),
    )


# ═══════════════════ rebuild_quota: trong và ngoài cửa sổ ═══════════════════


async def test_dung_lai_tu_redis_rong_ra_dung_so_tien_cua_postgres(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    """Ca chính của RR-7: Redis trắng, Postgres có sổ ⇒ ZSET quay lại như cũ."""
    await _ghi_so(session, user_a, cost="0.120000", tuoi_giay=TRONG_5H)
    await _ghi_so(session, user_a, cost="0.030000", tuoi_giay=TRONG_5H * 2)

    report = await rebuild_quota(session, quota_redis_fake, user_id=user_a, now=time.time())

    assert report.members == 4  # hai dòng × hai cửa sổ
    assert _tong(quota_redis_fake, LimitType.SHORT, user_a) == Decimal("0.150000")
    assert _tong(quota_redis_fake, LimitType.LONG, user_a) == Decimal("0.150000")


async def test_dong_ngoai_cua_so_5h_chi_vao_cua_so_tuan(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    """DoD dòng 2 — "dữ liệu nằm trong và ngoài cửa sổ", vế thứ nhất."""
    await _ghi_so(session, user_a, cost="0.100000", tuoi_giay=TRONG_5H)
    await _ghi_so(session, user_a, cost="0.200000", tuoi_giay=NGOAI_5H_TRONG_TUAN)

    await rebuild_quota(session, quota_redis_fake, user_id=user_a, now=time.time())

    assert len(_zset(quota_redis_fake, LimitType.SHORT, user_a)) == 1
    assert _tong(quota_redis_fake, LimitType.SHORT, user_a) == Decimal("0.100000")
    assert len(_zset(quota_redis_fake, LimitType.LONG, user_a)) == 2
    assert _tong(quota_redis_fake, LimitType.LONG, user_a) == Decimal("0.300000")


async def test_dong_ngoai_ca_hai_cua_so_khong_vao_dau_ca(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    """DoD dòng 2 — vế thứ hai. Tiền của tuần trước KHÔNG được sống lại."""
    await _ghi_so(session, user_a, cost="9.000000", tuoi_giay=NGOAI_CA_HAI)

    report = await rebuild_quota(session, quota_redis_fake, user_id=user_a, now=time.time())

    assert report.members == 0
    # Và không tạo khoá rỗng: một khoá rỗng khác một khoá không tồn tại ở đúng
    # phép đo `--scan --pattern 'quota:*'` của DoD T-2.12.
    assert quota_redis_fake.zset == {}
    assert quota_redis_fake.da_dat_ttl == []


async def test_score_la_created_at_chu_khong_phai_now(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    """Chỗ mà "một truy vấn `SUM`" của §10.3 không làm được.

    Nạp bằng `score = now` thì khoản tiêu 4 giờ trước được gia hạn thêm 5 giờ
    nữa — người dùng bị phạt hai lần cho cùng một khoản. Phép kiểm: dựng lại
    rồi đọc cửa sổ ở một `now` **tương lai**, chỗ mà dòng ấy phải đã rơi ra.
    """
    bon_gio = 4 * 3600
    await _ghi_so(session, user_a, cost="0.400000", tuoi_giay=bon_gio)
    now = time.time()
    await rebuild_quota(session, quota_redis_fake, user_id=user_a, now=now)

    ngan, _ = windows()
    ngay_bay_gio = await read_window(quota_redis_fake, ngan, user_id=user_a, now=now)
    assert ngay_bay_gio.spent == Decimal("0.400000")

    # 1 giờ 1 phút nữa là dòng ấy tròn 5 giờ 1 phút tuổi ⇒ ngoài cửa sổ.
    sau_nay = now + 3660
    da_roi = await read_window(quota_redis_fake, ngan, user_id=user_a, now=sau_nay)
    assert da_roi.spent == Decimal(0)


async def test_so_member_bang_so_dong_so_chu_khong_chi_bang_tong_tien(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    """Bất biến mà DoD T-2.12 dòng 5 đo, giữ nguyên sau khi dựng lại.

    Ba dòng **cùng giá** là ca duy nhất phân biệt được hai cách đọc §10.3:
    member mang `usage_id` thì ra ba, member chỉ mang `<cost>` (chữ của §10.2)
    thì ba dòng đè lên nhau còn một, và tổng tiền tụt xuống một phần ba.
    """
    for _ in range(3):
        await _ghi_so(session, user_a, cost="0.010000", tuoi_giay=TRONG_5H)

    await rebuild_quota(session, quota_redis_fake, user_id=user_a, now=time.time())

    assert len(_zset(quota_redis_fake, LimitType.SHORT, user_a)) == 3
    assert _tong(quota_redis_fake, LimitType.SHORT, user_a) == Decimal("0.030000")


async def test_dung_lai_hai_lan_cho_ra_dung_mot_ket_qua(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    """Không `DEL` thì phép này phải không đổi — nếu không, mỗi lần chạy là một
    lần nhân đôi hoá đơn."""
    await _ghi_so(session, user_a, cost="0.070000", tuoi_giay=TRONG_5H)
    now = time.time()

    await rebuild_quota(session, quota_redis_fake, user_id=user_a, now=now)
    lan_dau = dict(_zset(quota_redis_fake, LimitType.SHORT, user_a))
    await rebuild_quota(session, quota_redis_fake, user_id=user_a, now=now)

    assert _zset(quota_redis_fake, LimitType.SHORT, user_a) == lan_dau
    assert _tong(quota_redis_fake, LimitType.SHORT, user_a) == Decimal("0.070000")


async def test_khong_xoa_member_cua_luot_sinh_vua_ghi_so_song_song(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    """Vì sao hàm này HỢP chứ không THAY — xem docstring `quota/rebuild.py`.

    Mô phỏng khe giữa "chụp ảnh Postgres" và "ghi vào Redis": worker khép sổ
    một lượt sinh mà ảnh chụp chưa thấy. Một bản `DEL` + `ZADD` sẽ nuốt mất
    khoản ấy, và dòng `usage_events` của nó thì vẫn nằm trong Postgres.
    """
    await _ghi_so(session, user_a, cost="0.050000", tuoi_giay=TRONG_5H)
    now = time.time()
    ngan, _ = windows()
    ma_worker_vua_ghi = encode_member(uuid.uuid4(), Decimal("0.020000"))
    quota_redis_fake.zset[ngan.key(user_a)] = {ma_worker_vua_ghi: now}

    await rebuild_quota(session, quota_redis_fake, user_id=user_a, now=now)

    assert ma_worker_vua_ghi in _zset(quota_redis_fake, LimitType.SHORT, user_a)
    assert _tong(quota_redis_fake, LimitType.SHORT, user_a) == Decimal("0.070000")


async def test_moi_cua_so_duoc_dat_ttl_bang_do_dai_cua_chinh_no(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    """Cùng luật với `add_to_windows` (nửa (b) của B-156).

    Không có nó thì một khoá dựng lại cho người đã ngừng chat nằm lại vô thời
    hạn — đúng thứ B-156 mở ra để sửa.
    """
    await _ghi_so(session, user_a, cost="0.010000", tuoi_giay=TRONG_5H)
    await rebuild_quota(session, quota_redis_fake, user_id=user_a, now=time.time())

    ngan, dai = windows()
    assert quota_redis_fake.da_dat_ttl == [
        (ngan.key(user_a), settings.QUOTA_WINDOW_SHORT_S),
        (dai.key(user_a), settings.QUOTA_WINDOW_LONG_S),
    ]


async def test_nap_theo_lo_chu_khong_mot_lenh_moi_dong(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    """Thứ đứng sau DoD dòng 3 (10k dòng < 2 s), đo được mà không cần 10k dòng.

    `ZADD_BATCH + 1` dòng là con số nhỏ nhất chứng minh được phép chia lô: một
    lệnh đầy và một lệnh lẻ cho mỗi cửa sổ. Một bản hiện thực "một `ZADD` mỗi
    dòng" sẽ cho `2 × (ZADD_BATCH + 1)` lệnh và vẫn **đúng** — nó chỉ chậm,
    tức đúng loại hỏng mà không phép kiểm nào khác nhìn thấy.
    """
    so_dong = ZADD_BATCH + 1
    repo = UsageEventRepository(session)
    for _ in range(so_dong):
        await repo.record(
            user_id=user_a,
            message_id=None,
            model_id=MODEL_CO_GIA,
            provider="deepseek",
            key_source=KeySource.SYSTEM,
            prompt_tokens=1,
            completion_tokens=1,
            cached_tokens=0,
            cost_usd=Decimal("0.000001"),
            cost_confidence=CostConfidence.EXACT,
            price_snapshot={"source": "catalog"},
        )
    await session.flush()

    await rebuild_quota(session, quota_redis_fake, user_id=user_a, now=time.time())

    lenh = [so for _, so in quota_redis_fake.da_ghi]
    assert lenh == [ZADD_BATCH, 1, ZADD_BATCH, 1]
    assert len(_zset(quota_redis_fake, LimitType.SHORT, user_a)) == so_dong


async def test_chi_dung_lai_cho_dung_nguoi(
    session: AsyncSession, user_a: uuid.UUID, user_b: uuid.UUID, quota_redis_fake: Any
) -> None:
    """§20 — phép lọc `user_id` nằm trong câu SQL, và đây là chỗ nó được đo."""
    await _ghi_so(session, user_a, cost="0.100000", tuoi_giay=TRONG_5H)
    await _ghi_so(session, user_b, cost="0.900000", tuoi_giay=TRONG_5H)

    await rebuild_quota(session, quota_redis_fake, user_id=user_a, now=time.time())

    assert _tong(quota_redis_fake, LimitType.SHORT, user_a) == Decimal("0.100000")
    assert _zset(quota_redis_fake, LimitType.SHORT, user_b) == {}


def test_bien_cua_so_la_datetime_co_mui_gio() -> None:
    """NQ-50 ⑦ cùng bài học: một `datetime` trần đi vào `timestamptz` là một
    phép so sánh do driver đoán hộ."""
    ngan, _ = windows()
    bien = cutoff_at(ngan, time.time())
    assert bien.tzinfo is not None
    assert bien.utcoffset() == datetime.now(UTC).utcoffset()


# ═══════════════════ refill_if_empty: tự gọi khi phát hiện lệch ═════════════


async def test_cua_so_rong_ma_postgres_co_tien_thi_tu_dung_lai(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    await _ghi_so(session, user_a, cost="0.250000", tuoi_giay=TRONG_5H)
    now = time.time()
    ngan, _ = windows()

    truoc = await read_window(quota_redis_fake, ngan, user_id=user_a, now=now)
    assert truoc.spent == Decimal(0)

    sau = await refill_if_empty(session, quota_redis_fake, truoc, user_id=user_a, now=now)
    assert sau.spent == Decimal("0.250000")
    assert len(sau.entries) == 1


async def test_cua_so_rong_va_postgres_cung_rong_thi_khong_ghi_gi(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    """Ca thường của một người dùng mới — nó không được tốn một lệnh ghi nào."""
    now = time.time()
    ngan, _ = windows()
    truoc = await read_window(quota_redis_fake, ngan, user_id=user_a, now=now)

    sau = await refill_if_empty(session, quota_redis_fake, truoc, user_id=user_a, now=now)

    assert sau is truoc
    assert quota_redis_fake.da_ghi == []
    assert quota_redis_fake.zset == {}


async def test_cua_so_con_du_lieu_thi_khong_hoi_postgres(
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
    ngan, _ = windows()
    await _ghi_so(session, user_a, cost="0.050000", tuoi_giay=TRONG_5H)
    quota_redis_fake.zset[ngan.key(user_a)] = {
        encode_member(uuid.uuid4(), Decimal("0.300000")): now - 60
    }
    truoc = await read_window(quota_redis_fake, ngan, user_id=user_a, now=now)

    sau = await refill_if_empty(session, quota_redis_fake, truoc, user_id=user_a, now=now)

    assert sau is truoc
    assert sau.spent == Decimal("0.300000")
    assert quota_redis_fake.da_ghi == []


async def test_tien_ngoai_cua_so_khong_lam_no_tu_dung_lai(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    """Vế "trong cửa sổ" của điều kiện, đo riêng.

    Một người tiêu tiền 6 giờ trước có cửa sổ 5 giờ **đúng là** rỗng. Dựng lại
    ở đó là ghi đè một câu trả lời đúng bằng chính nó, mỗi request một lần.
    """
    await _ghi_so(session, user_a, cost="0.500000", tuoi_giay=NGOAI_5H_TRONG_TUAN)
    now = time.time()
    ngan, _ = windows()
    truoc = await read_window(quota_redis_fake, ngan, user_id=user_a, now=now)

    sau = await refill_if_empty(session, quota_redis_fake, truoc, user_id=user_a, now=now)

    assert sau is truoc
    assert quota_redis_fake.da_ghi == []


# ═════════════════ qua check_quota: bản pytest của DoD dòng 1 ═══════════════


@pytest.fixture
def _quota_redis(monkeypatch: pytest.MonkeyPatch, quota_redis_fake: Any) -> Any:
    monkeypatch.setattr("app.quota.estimator.get_redis", lambda: quota_redis_fake)
    monkeypatch.setattr("app.quota.tiers.get_redis", lambda: quota_redis_fake)
    return quota_redis_fake


@pytest.fixture
def _db_cua_test(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


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


async def test_redis_bi_xoa_sach_thi_cua_chan_van_thay_tien_da_tieu(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_cua_test: None,
) -> None:
    """DoD dòng 1 ở dạng tự động: `FLUSHDB` rồi gọi API ⇒ quota KHÔNG về 0.

    Tier `free` có `limit_5h_usd = 0.50`. Người này đã tiêu 0.50 theo sổ cái,
    nên cửa chặn phải trả `429` — mà nó chỉ làm được thế nếu đã tự dựng lại
    ZSET từ Postgres. Không có `refill_if_empty` thì request này đi qua, và đó
    đúng là câu "quota của mọi người reset" trong Cạm bẫy của T-2.13.
    """
    leaf = await _cay_mot_luot(session_factory, user_a)
    async with session_factory() as ghi:
        await _ghi_so(ghi, user_a, cost="0.500000", tuoi_giay=TRONG_5H)
        await ghi.commit()

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
    assert _tong(_quota_redis, LimitType.SHORT, user_a) == Decimal("0.500000")


async def test_postgres_chet_giua_luc_dung_lai_thi_503_chu_khong_cho_qua(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _quota_redis: Any,
    _db_cua_test: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Không hỏi được Postgres ⇒ vẫn "không biết còn bao nhiêu tiền" ⇒ `503`.

    Cùng câu trả lời với ca Redis chết (NQ-53). Cho qua ở đây là gỡ lớp phòng
    thủ P2 vào đúng lúc cả hai kho đều không trả lời được.
    """
    leaf = await _cay_mot_luot(session_factory, user_a)

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


async def test_rebuild_all_dung_lai_cho_moi_nguoi_co_chi_tieu(
    session: AsyncSession, user_a: uuid.UUID, user_b: uuid.UUID, quota_redis_fake: Any
) -> None:
    await _ghi_so(session, user_a, cost="0.110000", tuoi_giay=TRONG_5H)
    await _ghi_so(session, user_b, cost="0.220000", tuoi_giay=NGOAI_5H_TRONG_TUAN)

    reports = await rebuild_all(session, quota_redis_fake, now=time.time())

    theo_user = {r.user_id: r for r in reports}
    assert {user_a, user_b} <= set(theo_user)
    assert _tong(quota_redis_fake, LimitType.SHORT, user_a) == Decimal("0.110000")
    assert _tong(quota_redis_fake, LimitType.LONG, user_b) == Decimal("0.220000")
    # `user_b` tiêu tiền ngoài cửa sổ 5 giờ ⇒ cửa sổ ấy vẫn phải rỗng.
    assert _zset(quota_redis_fake, LimitType.SHORT, user_b) == {}


async def test_rebuild_all_bo_qua_nguoi_khong_co_dong_so_nao(
    session: AsyncSession, user_a: uuid.UUID, user_b: uuid.UUID, quota_redis_fake: Any
) -> None:
    """Tập người đọc từ `usage_events`, không từ `users`."""
    await _ghi_so(session, user_a, cost="0.010000", tuoi_giay=TRONG_5H)

    reports = await rebuild_all(session, quota_redis_fake, now=time.time())

    assert user_b not in {r.user_id for r in reports}


# ══════════════════════════ app/cli.py — vỏ lệnh ═══════════════════════════


def test_thieu_co_all_thi_argparse_bao_loi_chu_khong_chay(
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


def test_khong_co_lenh_nao_thi_cung_bao_loi() -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == 2


async def test_lenh_rebuild_quota_all_nap_lai_zset_va_tra_ma_thoat_0(
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
    async with session_factory() as ghi:
        await _ghi_so(ghi, user_a, cost="0.330000", tuoi_giay=TRONG_5H)
        await ghi.commit()

    ma_thoat = await cli._rebuild_quota_all()

    assert ma_thoat == 0
    assert _tong(quota_redis_fake, LimitType.SHORT, user_a) == Decimal("0.330000")
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


async def test_dong_BYOK_khong_vao_ZSET_khi_dung_lai(
    session: AsyncSession, user_a: uuid.UUID, quota_redis_fake: Any
) -> None:
    """`rebuild_quota` chỉ dựng lại phần tiền của NGƯỜI VẬN HÀNH."""
    await _ghi_so(session, user_a, cost="0.100000", tuoi_giay=TRONG_5H)
    await _ghi_so(session, user_a, cost="0.900000", tuoi_giay=TRONG_5H, key_source=KeySource.BYOK)
    await session.commit()

    await rebuild_quota(session, quota_redis_fake, user_id=user_a, now=time.time())

    assert _tong(quota_redis_fake, LimitType.SHORT, user_a) == Decimal("0.100000")
    assert len(_zset(quota_redis_fake, LimitType.SHORT, user_a)) == 1
    assert _tong(quota_redis_fake, LimitType.LONG, user_a) == Decimal("0.100000")


async def test_chi_co_dong_BYOK_thi_KHONG_HOI_postgres_lan_thu_hai(
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
    await _ghi_so(session, user_a, cost="0.900000", tuoi_giay=TRONG_5H, key_source=KeySource.BYOK)
    await session.commit()
    state = await read_window(quota_redis_fake, windows()[0], user_id=user_a, now=time.time())
    so_lan_doc_ca_cua_so = 0
    goc = UsageEventRepository.list_since

    async def dem(self: UsageEventRepository, **kwargs: Any) -> Any:
        nonlocal so_lan_doc_ca_cua_so
        so_lan_doc_ca_cua_so += 1
        return await goc(self, **kwargs)

    monkeypatch.setattr(UsageEventRepository, "list_since", dem)

    sau = await refill_if_empty(session, quota_redis_fake, state, user_id=user_a, now=time.time())

    assert sau.spent == Decimal(0)
    assert _zset(quota_redis_fake, LimitType.SHORT, user_a) == {}
    assert so_lan_doc_ca_cua_so == 0, (
        "chỉ có tiền BYOK thì `has_events_since` phải nói KHÔNG, và lượt đọc cả "
        "cửa sổ không được xảy ra"
    )


async def test_rebuild_all_bo_qua_nguoi_chi_tieu_bang_BYOK(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    quota_redis_fake: Any,
) -> None:
    """`user_ids_since` là vế thứ ba — bỏ sót nó thì `--all` vẫn nạp nhầm."""
    async with session_factory() as ghi:
        await _ghi_so(ghi, user_a, cost="0.200000", tuoi_giay=TRONG_5H)
        await _ghi_so(ghi, user_b, cost="0.700000", tuoi_giay=TRONG_5H, key_source=KeySource.BYOK)
        await ghi.commit()

    async with session_factory() as doc:
        da_dung = await rebuild_all(doc, quota_redis_fake, now=time.time())

    assert [bao_cao.user_id for bao_cao in da_dung] == [user_a]
    assert _zset(quota_redis_fake, LimitType.SHORT, user_b) == {}
