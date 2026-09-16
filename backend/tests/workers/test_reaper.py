"""T-1.10 — cron `reaper` (§7.6, tiêu chí S4).

KH tham chiếu: §7.6, §7.4, §17.4, C8 · CLAUDE.md A3 · S4.

Ba trong bốn dòng DoD của task được kiểm tự động ở đây; dòng còn lại (`EXPLAIN`
câu UPDATE trên một bảng đủ lớn) phải chạy trên Postgres thật có vài chục nghìn
dòng nên nó nằm trong báo cáo task — B-61 đã ghi đúng lý do: bảng test chỉ có
vài dòng, planner chọn `Seq Scan` vì nó **thật sự** rẻ hơn, nên một `EXPLAIN`
trong `pytest` sẽ khẳng định điều ngược với production.

- **DoD 1** — message kẹt `streaming` → `failed`: `test_message_qua_han…`
- **DoD 2** — client nhận `error` mã `WORKER_LOST`: `test_phat_event_error…`
- **DoD 4** — không có gì quá hạn → 0 dòng, không lỗi: `test_khong_co_gi…`

Postgres là **thật** (fixture của `tests/conftest.py`): thứ đáng kiểm nhất ở
task này là câu `UPDATE … RETURNING` có chọn đúng tập dòng hay không, mà đó là
ngữ nghĩa của Postgres chứ không phải của Python — kiểu ENUM `message_status`,
`now()` là `transaction_timestamp()`, và `NULL < …` ra `NULL`. Chỉ Redis là giả.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import event, select, text, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

import app.db.session as db_session
from app.config.settings import settings
from app.db.models import Conversation, Message, MessageRole, MessageStatus
from app.db.repositories import ConversationRepository, MessageRepository
from app.streaming.events import ErrorCode
from app.streaming.producer import FIELD_DATA, FIELD_TYPE, stream_key
from app.workers.main import CRON_JOBS
from app.workers.reaper import REAPER_GIAY_TRONG_PHUT, REAPER_JOB_NAME, reaper

MODEL_ID = "deepseek-flash"


class RedisGia:
    """Đủ `xadd`/`expire`. `key_no` làm hỏng đúng một khoá để kiểm cách ly."""

    def __init__(self) -> None:
        self.ban_ghi: list[dict[str, str]] = []
        self.expire_calls: list[tuple[str, int]] = []
        self.key_no: str | None = None
        self._seq = 0

    async def xadd(self, name: str, fields: dict[str, Any]) -> bytes:
        if name == self.key_no:
            raise ConnectionError("redis chet giua chung (gia lap)")
        self._seq += 1
        self.ban_ghi.append({"__key__": name, **fields})
        return f"1725984000{self._seq:03d}-0".encode()

    async def expire(self, name: str, ttl: int) -> int:
        self.expire_calls.append((name, ttl))
        return 1

    def ban_ghi_cua(self, mid: uuid.UUID) -> list[dict[str, str]]:
        return [b for b in self.ban_ghi if b["__key__"] == stream_key(mid)]


@pytest.fixture
def redis_gia() -> RedisGia:
    return RedisGia()


@pytest.fixture(autouse=True)
def _noi_session_vao_db_test(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """`session_scope()` của reaper trỏ vào transaction của test — như T-1.6."""
    monkeypatch.setattr(db_session, "get_sessionmaker", lambda: session_factory)


def _ctx(redis_gia: RedisGia) -> dict[str, Any]:
    return {"redis": redis_gia, "job_id": "test-cron"}


async def _message(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    status: MessageStatus,
    heartbeat_tuoi_s: float | None,
    created_tuoi_s: float | None = None,
) -> Message:
    """Một message assistant với `heartbeat_at` đặt tay ở quá khứ.

    Đặt thẳng bằng `UPDATE` thay vì đợi thời gian trôi: DoD đo bằng 90 giây
    thật trên hạ tầng thật (xem báo cáo task), còn ở đây thứ cần kiểm là **vị
    từ của câu SQL**, không phải đồng hồ.
    """
    repo = MessageRepository(session)
    conversation: Conversation = await ConversationRepository(session).create_conversation(
        user_id=user_id
    )
    hoi = await repo.create_message(
        conversation_id=conversation.id,
        user_id=user_id,
        role=MessageRole.USER,
        content="Mùa thu Hà Nội thế nào?",
        status=MessageStatus.COMPLETED,
    )
    tra_loi = await repo.create_message(
        conversation_id=conversation.id,
        user_id=user_id,
        role=MessageRole.ASSISTANT,
        parent_id=hoi.id,
        status=status,
        model_id=MODEL_ID,
    )
    if heartbeat_tuoi_s is not None:
        await session.execute(
            update(Message)
            .where(Message.id == tra_loi.id)
            .values(heartbeat_at=datetime.now(UTC) - timedelta(seconds=heartbeat_tuoi_s))
        )
    if created_tuoi_s is not None:
        # Nhánh `queued` của §7.6 đo trên `created_at` chứ không `heartbeat_at`
        # (B-123), nên test của nó phải dời được đúng cột ấy.
        await session.execute(
            update(Message)
            .where(Message.id == tra_loi.id)
            .values(created_at=datetime.now(UTC) - timedelta(seconds=created_tuoi_s))
        )
    await session.commit()
    return tra_loi


async def _doc_lai(session_factory: async_sessionmaker[AsyncSession], mid: uuid.UUID) -> Message:
    async with session_factory() as s:
        return (await s.execute(select(Message).where(Message.id == mid))).scalar_one()


def _qua_han() -> float:
    return settings.REAPER_STALE_S + 10


def _con_moi() -> float:
    return settings.REAPER_STALE_S / 2


def _queued_qua_han() -> float:
    return settings.REAPER_QUEUED_STALE_S + 10


# ────────────────────── nhánh `queued` của §7.6 (B-123) ──────────────────────


async def test_queued_qua_han_thanh_failed_voi_ma_job_lost(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    redis_gia: RedisGia,
) -> None:
    """B-123: worker chết TRƯỚC `mark_streaming` để lại một tập reaper cũ mù.

    `status='queued'` + `heartbeat_at=NULL` trượt cả hai vế của câu UPDATE
    nhánh `streaming`, còn job thì bị arq từ chối bằng `max retries 1 exceeded`
    — nên trước bản vá này message kẹt `queued` **vĩnh viễn**.
    """
    mid = (
        await _message(
            session,
            user_a,
            status=MessageStatus.QUEUED,
            heartbeat_tuoi_s=None,
            created_tuoi_s=_queued_qua_han(),
        )
    ).id

    await reaper(_ctx(redis_gia))

    sau = await _doc_lai(session_factory, mid)
    assert sau.status is MessageStatus.FAILED
    assert sau.error_code == "JOB_LOST"

    # `stream:{id}` CHƯA hề tồn tại trước lượt quét này — `generate` chưa chạy
    # tới `XADD start` bao giờ. `XADD` tự tạo khoá, nên client đang mở SSE vẫn
    # nhận được `error` thay vì chờ mãi.
    ban_ghi = redis_gia.ban_ghi_cua(mid)
    assert len(ban_ghi) == 1
    assert ban_ghi[0][FIELD_TYPE] == "error"
    assert json.loads(ban_ghi[0][FIELD_DATA])["code"] == "JOB_LOST"


async def test_queued_con_moi_khong_bi_don(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    redis_gia: RedisGia,
) -> None:
    """Đường chạy thường ngày: mọi message vừa gửi đều `queued` trong ~0.1 s."""
    mid = (
        await _message(
            session, user_a, status=MessageStatus.QUEUED, heartbeat_tuoi_s=None, created_tuoi_s=None
        )
    ).id

    await reaper(_ctx(redis_gia))

    sau = await _doc_lai(session_factory, mid)
    assert sau.status is MessageStatus.QUEUED
    assert redis_gia.ban_ghi == []


async def test_hai_nhanh_dung_HAI_nguong_rieng_khong_dung_chung(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    redis_gia: RedisGia,
) -> None:
    """Ngưỡng `queued` phải LỚN HƠN ngưỡng `streaming`, và là biến khác.

    Đây là test canh chỗ dễ sai nhất của B-123: dùng lại `REAPER_STALE_S` cho
    cả hai nhánh. Nếu ai đó làm thế, message dưới đây — già hơn ngưỡng
    `streaming` nhưng trẻ hơn ngưỡng `queued` — sẽ bị đánh `failed` oan, trong
    khi job của nó vẫn còn nằm trong hàng đợi arq và **sắp chạy**
    (khoá `arq:in-progress:` sống tới `GENERATE_TIMEOUT_S + 10` ≈ 910 s, B-72).
    """
    assert settings.REAPER_QUEUED_STALE_S > settings.GENERATE_TIMEOUT_S, (
        "ngưỡng queued phải lớn hơn timeout của job, nếu không reaper đua với arq"
    )

    mid = (
        await _message(
            session,
            user_a,
            status=MessageStatus.QUEUED,
            heartbeat_tuoi_s=None,
            created_tuoi_s=settings.REAPER_STALE_S + 10,
        )
    ).id

    await reaper(_ctx(redis_gia))

    sau = await _doc_lai(session_factory, mid)
    assert sau.status is MessageStatus.QUEUED, (
        "message queued bị dọn theo ngưỡng của nhánh streaming — hai nhánh đang "
        "dùng chung một biến (B-123)"
    )
    assert redis_gia.ban_ghi == []


async def test_don_ca_hai_nhanh_trong_mot_luot_quet(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    redis_gia: RedisGia,
) -> None:
    """Một tick phải dọn cả hai tập, và mỗi tập mang MÃ của chính nó."""
    mat_nhip = (
        await _message(session, user_a, status=MessageStatus.STREAMING, heartbeat_tuoi_s=_qua_han())
    ).id
    mo_coi = (
        await _message(
            session,
            user_a,
            status=MessageStatus.QUEUED,
            heartbeat_tuoi_s=None,
            created_tuoi_s=_queued_qua_han(),
        )
    ).id

    await reaper(_ctx(redis_gia))

    assert (await _doc_lai(session_factory, mat_nhip)).error_code == "WORKER_LOST"
    assert (await _doc_lai(session_factory, mo_coi)).error_code == "JOB_LOST"

    # Mỗi message nhận ĐÚNG mã của nhánh mình, không phải mã của lượt quét.
    assert json.loads(redis_gia.ban_ghi_cua(mat_nhip)[0][FIELD_DATA])["code"] == "WORKER_LOST"
    assert json.loads(redis_gia.ban_ghi_cua(mo_coi)[0][FIELD_DATA])["code"] == "JOB_LOST"


# ─────────────────────────── DoD 1 và DoD 2 ───────────────────────────


async def test_message_qua_han_thanh_failed_voi_ma_worker_lost(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    redis_gia: RedisGia,
) -> None:
    """§7.6: `status='failed'`, `error_code='WORKER_LOST'`. DoD dòng 1."""
    mid = (
        await _message(session, user_a, status=MessageStatus.STREAMING, heartbeat_tuoi_s=_qua_han())
    ).id

    await reaper(_ctx(redis_gia))

    sau = await _doc_lai(session_factory, mid)
    assert sau.status is MessageStatus.FAILED
    assert sau.error_code == ErrorCode.WORKER_LOST.value


async def test_phat_event_error_ma_worker_lost_len_dung_stream(
    session: AsyncSession,
    user_a: uuid.UUID,
    redis_gia: RedisGia,
) -> None:
    """DoD dòng 2 — client đang mở SSE thấy `error`, không treo vô hạn.

    `error` là một trong hai loại kết thúc mà `streaming/consumer.py` nhận ra
    (`LOAI_KET_THUC`), nên phát đúng loại này là điều kiện để SSE đóng.
    """
    mid = (
        await _message(session, user_a, status=MessageStatus.STREAMING, heartbeat_tuoi_s=_qua_han())
    ).id

    await reaper(_ctx(redis_gia))

    ban_ghi = redis_gia.ban_ghi_cua(mid)
    assert len(ban_ghi) == 1, "đúng một event kết thúc cho một message"
    assert ban_ghi[0][FIELD_TYPE] == "error"
    assert json.loads(ban_ghi[0][FIELD_DATA])["code"] == "WORKER_LOST"


async def test_xadd_kem_expire_vi_khong_ai_khac_dat_ttl_duoc(
    session: AsyncSession,
    user_a: uuid.UUID,
    redis_gia: RedisGia,
) -> None:
    """C8: `_dong_so` của worker là chỗ đặt TTL, mà nó đã không chạy."""
    mid = (
        await _message(session, user_a, status=MessageStatus.STREAMING, heartbeat_tuoi_s=_qua_han())
    ).id

    await reaper(_ctx(redis_gia))

    assert redis_gia.expire_calls == [(stream_key(mid), settings.STREAM_TTL_S)]


# ─────────────────────────── ai KHÔNG bị dọn ───────────────────────────


async def test_khong_co_gi_qua_han_thi_khong_doi_gi_va_khong_loi(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    redis_gia: RedisGia,
) -> None:
    """DoD dòng 4 — đường chạy thường ngày, 2880 lần mỗi ngày."""
    mid = (
        await _message(session, user_a, status=MessageStatus.STREAMING, heartbeat_tuoi_s=_con_moi())
    ).id

    await reaper(_ctx(redis_gia))

    sau = await _doc_lai(session_factory, mid)
    assert sau.status is MessageStatus.STREAMING
    assert sau.error_code is None
    assert redis_gia.ban_ghi == []
    assert redis_gia.expire_calls == []


async def test_reaper_chay_tren_bang_rong_khong_no(redis_gia: RedisGia) -> None:
    """DoD dòng 4, ca không có message nào — `RETURNING` trả danh sách rỗng."""
    await reaper(_ctx(redis_gia))

    assert redis_gia.ban_ghi == []


@pytest.mark.parametrize(
    "status",
    [
        MessageStatus.QUEUED,
        MessageStatus.COMPLETED,
        MessageStatus.FAILED,
        MessageStatus.CANCELLED,
    ],
)
async def test_chi_dung_toi_streaming_du_nhip_tim_cu_hang_gio(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    redis_gia: RedisGia,
    status: MessageStatus,
) -> None:
    """§17.2: `heartbeat_at` chỉ có nghĩa khi `status='streaming'`.

    `finish_generation` cố ý **không** xoá `heartbeat_at` (nó là dấu vết "chết
    lúc nào"), nên mọi message đã khép đều mang một nhịp tim cũ. Bỏ vế
    `status` khỏi câu UPDATE là đánh `failed` toàn bộ lịch sử hội thoại.
    """
    mid = (await _message(session, user_a, status=status, heartbeat_tuoi_s=3600)).id

    await reaper(_ctx(redis_gia))

    sau = await _doc_lai(session_factory, mid)
    assert sau.status is status
    assert redis_gia.ban_ghi == []


async def test_heartbeat_null_khong_bi_don(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    redis_gia: RedisGia,
) -> None:
    """`NULL < now() - interval` ra `NULL`, tức không khớp — và đó là lý do
    `mark_streaming` đặt `heartbeat_at` ngay lúc đổi trạng thái chứ không đợi
    nhịp đầu tiên. Test này canh chiều còn lại của giao kèo đó."""
    mid = (
        await _message(session, user_a, status=MessageStatus.STREAMING, heartbeat_tuoi_s=None)
    ).id

    await reaper(_ctx(redis_gia))

    sau = await _doc_lai(session_factory, mid)
    assert sau.heartbeat_at is None
    assert sau.status is MessageStatus.STREAMING


# ─────────────────────────── cách ly và thứ tự ───────────────────────────


async def test_mot_message_hong_redis_khong_chan_nhung_message_con_lai(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    redis_gia: RedisGia,
) -> None:
    """Hai message cùng mồ côi; `XADD` của cái đầu nổ."""
    mot = await _message(
        session, user_a, status=MessageStatus.STREAMING, heartbeat_tuoi_s=_qua_han()
    )
    hai = await _message(
        session, user_a, status=MessageStatus.STREAMING, heartbeat_tuoi_s=_qua_han()
    )
    redis_gia.key_no = stream_key(mot.id)

    await reaper(_ctx(redis_gia))

    # Postgres ghi TRƯỚC Redis, nên cả hai đều đã `failed` dù một cái không
    # ra được dây — đảo thứ tự là để FE hiện Retry trong khi DB nói "đang sinh".
    for mid in (mot.id, hai.id):
        assert (await _doc_lai(session_factory, mid)).status is MessageStatus.FAILED
    assert redis_gia.ban_ghi_cua(mot.id) == []
    assert len(redis_gia.ban_ghi_cua(hai.id)) == 1


async def test_khong_dung_toi_message_cua_luot_sinh_dang_chay(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    redis_gia: RedisGia,
) -> None:
    """Một lượt mồ côi và một lượt còn nhịp, cùng một lượt quét."""
    chet = await _message(
        session, user_a, status=MessageStatus.STREAMING, heartbeat_tuoi_s=_qua_han()
    )
    song = await _message(
        session, user_a, status=MessageStatus.STREAMING, heartbeat_tuoi_s=_con_moi()
    )

    await reaper(_ctx(redis_gia))

    assert (await _doc_lai(session_factory, chet.id)).status is MessageStatus.FAILED
    assert (await _doc_lai(session_factory, song.id)).status is MessageStatus.STREAMING
    assert [b["__key__"] for b in redis_gia.ban_ghi] == [stream_key(chet.id)]


# ─────────────────────── partial index và lịch cron ───────────────────────


async def test_cau_update_noi_suy_streaming_thanh_HANG_chu_khong_tham_so(
    session: AsyncSession,
    connection: AsyncConnection,
) -> None:
    """DoD dòng 3, nửa kiểm được bằng test: `status = 'streaming'` phải nằm
    **trong chuỗi SQL mà driver gửi đi**, không phải một tham số.

    `ix_msg_streaming` là partial index; Postgres chỉ dùng được nó khi vị từ
    của câu truy vấn kéo theo vị từ của index, mà với `status = $1` thì generic
    plan không chứng minh được — và generic plan là thứ Postgres tự chuyển sang
    sau năm lần thực thi. Bỏ `literal_execute=True` đi thì `EXPLAIN` của DoD
    vẫn xanh ở lần chạy đầu rồi hỏng **lặng lẽ** ở lần thứ sáu, nên chỗ chống
    lệch phải là một phép khẳng định trên chuỗi SQL, không phải trên kế hoạch.

    Bắt chuỗi ở `before_cursor_execute` chứ không `compile()` lại: cái sau kiểm
    ý định của mình, cái này kiểm thứ thật sự chạy.
    """
    cau_lenh: list[str] = []

    def ghi_lai(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        cau_lenh.append(statement)

    event.listen(connection.sync_engine, "before_cursor_execute", ghi_lai)
    try:
        await MessageRepository(session).reap_stale_streaming(
            stale_after_s=90, error_code=ErrorCode.WORKER_LOST.value
        )
    finally:
        event.remove(connection.sync_engine, "before_cursor_execute", ghi_lai)

    sql = next(c for c in cau_lenh if "RETURNING" in c and "UPDATE messages" in c)
    assert "messages.status = 'streaming'" in sql, sql
    assert "make_interval(secs=>90" in sql, sql


async def test_partial_index_khop_dung_vi_tu_cua_cau_update(session: AsyncSession) -> None:
    """Vị từ của `ix_msg_streaming` phải đúng chữ mà câu UPDATE viết ra.

    Đọc từ `pg_indexes` của database test (schema do migration 0001 dựng), nên
    đổi migration mà quên câu UPDATE — hoặc ngược lại — thì test này đỏ.
    """
    dinh_nghia = await session.scalar(
        text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_msg_streaming'")
    )
    assert dinh_nghia is not None, "migration 0001 phải tạo ix_msg_streaming (§17.4)"
    assert "heartbeat_at" in dinh_nghia
    assert "WHERE (status = 'streaming'::message_status)" in dinh_nghia


def test_cron_dang_ky_dung_nhip_30_giay() -> None:
    """§7.6 viết "Cron arq mỗi 30 s". arq nhận tập giây trong phút."""
    assert set(REAPER_GIAY_TRONG_PHUT) == {0, 30}

    lich = [c for c in CRON_JOBS if c.name == REAPER_JOB_NAME]
    assert len(lich) == 1, "đúng một cron reaper"
    assert lich[0].second == {0, 30}
    assert lich[0].minute is None, "mỗi phút, không phải mỗi giờ"


def test_cron_khong_thu_lai_va_khong_chay_hai_ban_cung_luc() -> None:
    """`max_tries=1`: tick sau vẫn thấy đúng những dòng ấy, thử lại vô nghĩa.
    `unique=True`: hai replica worker không cùng quét một tick."""
    lich = next(c for c in CRON_JOBS if c.name == REAPER_JOB_NAME)

    assert lich.max_tries == 1
    assert lich.unique is True
    assert lich.run_at_startup is False
