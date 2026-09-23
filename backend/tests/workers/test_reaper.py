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
from app.workers.reaper import REAPER_JOB_NAME, REAPER_SECONDS_IN_MINUTE, reaper

MODEL_ID = "deepseek-flash"


class FakeRedis:
    """Đủ `xadd`/`expire`. `key_no` làm hỏng đúng một khoá để kiểm cách ly."""

    def __init__(self) -> None:
        self.records: list[dict[str, str]] = []
        self.expire_calls: list[tuple[str, int]] = []
        self.key_no: str | None = None
        self._seq = 0

    async def xadd(self, name: str, fields: dict[str, Any]) -> bytes:
        if name == self.key_no:
            raise ConnectionError("redis chet giua chung (gia lap)")
        self._seq += 1
        self.records.append({"__key__": name, **fields})
        return f"1725984000{self._seq:03d}-0".encode()

    async def expire(self, name: str, ttl: int) -> int:
        self.expire_calls.append((name, ttl))
        return 1

    def entries_of(self, mid: uuid.UUID) -> list[dict[str, str]]:
        return [b for b in self.records if b["__key__"] == stream_key(mid)]


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture(autouse=True)
def _bind_session_to_test_db(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """`session_scope()` của reaper trỏ vào transaction của test — như T-1.6."""
    monkeypatch.setattr(db_session, "get_sessionmaker", lambda: session_factory)


def _ctx(fake_redis: FakeRedis) -> dict[str, Any]:
    return {"redis": fake_redis, "job_id": "test-cron"}


async def _message(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    status: MessageStatus,
    heartbeat_age_s: float | None,
    created_age_s: float | None = None,
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
    question_msg = await repo.create_message(
        conversation_id=conversation.id,
        user_id=user_id,
        role=MessageRole.USER,
        content="Mùa thu Hà Nội thế nào?",
        status=MessageStatus.COMPLETED,
    )
    answer = await repo.create_message(
        conversation_id=conversation.id,
        user_id=user_id,
        role=MessageRole.ASSISTANT,
        parent_id=question_msg.id,
        status=status,
        model_id=MODEL_ID,
    )
    if heartbeat_age_s is not None:
        await session.execute(
            update(Message)
            .where(Message.id == answer.id)
            .values(heartbeat_at=datetime.now(UTC) - timedelta(seconds=heartbeat_age_s))
        )
    if created_age_s is not None:
        # Nhánh `queued` của §7.6 đo trên `created_at` chứ không `heartbeat_at`
        # (B-123), nên test của nó phải dời được đúng cột ấy.
        await session.execute(
            update(Message)
            .where(Message.id == answer.id)
            .values(created_at=datetime.now(UTC) - timedelta(seconds=created_age_s))
        )
    await session.commit()
    return answer


async def _reload(session_factory: async_sessionmaker[AsyncSession], mid: uuid.UUID) -> Message:
    async with session_factory() as s:
        return (await s.execute(select(Message).where(Message.id == mid))).scalar_one()


def _overdue() -> float:
    return settings.REAPER_STALE_S + 10


def _still_fresh() -> float:
    return settings.REAPER_STALE_S / 2


def _queued_overdue() -> float:
    return settings.REAPER_QUEUED_STALE_S + 10


# ────────────────────── nhánh `queued` của §7.6 (B-123) ──────────────────────


async def test_overdue_queued_becomes_failed_job_lost(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
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
            heartbeat_age_s=None,
            created_age_s=_queued_overdue(),
        )
    ).id

    await reaper(_ctx(fake_redis))

    after = await _reload(session_factory, mid)
    assert after.status is MessageStatus.FAILED
    assert after.error_code == "JOB_LOST"

    # `stream:{id}` CHƯA hề tồn tại trước lượt quét này — `generate` chưa chạy
    # tới `XADD start` bao giờ. `XADD` tự tạo khoá, nên client đang mở SSE vẫn
    # nhận được `error` thay vì chờ mãi.
    records = fake_redis.entries_of(mid)
    assert len(records) == 1
    assert records[0][FIELD_TYPE] == "error"
    assert json.loads(records[0][FIELD_DATA])["code"] == "JOB_LOST"


async def test_fresh_queued_not_swept(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """Đường chạy thường ngày: mọi message vừa gửi đều `queued` trong ~0.1 s."""
    mid = (
        await _message(
            session, user_a, status=MessageStatus.QUEUED, heartbeat_age_s=None, created_age_s=None
        )
    ).id

    await reaper(_ctx(fake_redis))

    after = await _reload(session_factory, mid)
    assert after.status is MessageStatus.QUEUED
    assert fake_redis.records == []


async def test_two_branches_use_TWO_separate_thresholds(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
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
            heartbeat_age_s=None,
            created_age_s=settings.REAPER_STALE_S + 10,
        )
    ).id

    await reaper(_ctx(fake_redis))

    after = await _reload(session_factory, mid)
    assert after.status is MessageStatus.QUEUED, (
        "message queued bị dọn theo ngưỡng của nhánh streaming — hai nhánh đang "
        "dùng chung một biến (B-123)"
    )
    assert fake_redis.records == []


async def test_sweeps_both_branches_in_one_pass(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """Một tick phải dọn cả hai tập, và mỗi tập mang MÃ của chính nó."""
    stale = (
        await _message(session, user_a, status=MessageStatus.STREAMING, heartbeat_age_s=_overdue())
    ).id
    orphan = (
        await _message(
            session,
            user_a,
            status=MessageStatus.QUEUED,
            heartbeat_age_s=None,
            created_age_s=_queued_overdue(),
        )
    ).id

    await reaper(_ctx(fake_redis))

    assert (await _reload(session_factory, stale)).error_code == "WORKER_LOST"
    assert (await _reload(session_factory, orphan)).error_code == "JOB_LOST"

    # Mỗi message nhận ĐÚNG mã của nhánh mình, không phải mã của lượt quét.
    assert json.loads(fake_redis.entries_of(stale)[0][FIELD_DATA])["code"] == "WORKER_LOST"
    assert json.loads(fake_redis.entries_of(orphan)[0][FIELD_DATA])["code"] == "JOB_LOST"


# ─────────────────────────── DoD 1 và DoD 2 ───────────────────────────


async def test_overdue_message_becomes_failed_worker_lost(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """§7.6: `status='failed'`, `error_code='WORKER_LOST'`. DoD dòng 1."""
    mid = (
        await _message(session, user_a, status=MessageStatus.STREAMING, heartbeat_age_s=_overdue())
    ).id

    await reaper(_ctx(fake_redis))

    after = await _reload(session_factory, mid)
    assert after.status is MessageStatus.FAILED
    assert after.error_code == ErrorCode.WORKER_LOST.value


async def test_emits_worker_lost_error_event_on_right_stream(
    session: AsyncSession,
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """DoD dòng 2 — client đang mở SSE thấy `error`, không treo vô hạn.

    `error` là một trong hai loại kết thúc mà `streaming/consumer.py` nhận ra
    (`TERMINAL_EVENTS`), nên phát đúng loại này là điều kiện để SSE đóng.
    """
    mid = (
        await _message(session, user_a, status=MessageStatus.STREAMING, heartbeat_age_s=_overdue())
    ).id

    await reaper(_ctx(fake_redis))

    records = fake_redis.entries_of(mid)
    assert len(records) == 1, "đúng một event kết thúc cho một message"
    assert records[0][FIELD_TYPE] == "error"
    assert json.loads(records[0][FIELD_DATA])["code"] == "WORKER_LOST"


async def test_xadd_with_expire_since_no_one_else_can_set_ttl(
    session: AsyncSession,
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """C8: `_close_ledger` của worker là chỗ đặt TTL, mà nó đã không chạy."""
    mid = (
        await _message(session, user_a, status=MessageStatus.STREAMING, heartbeat_age_s=_overdue())
    ).id

    await reaper(_ctx(fake_redis))

    assert fake_redis.expire_calls == [(stream_key(mid), settings.STREAM_TTL_S)]


# ─────────────────────────── ai KHÔNG bị dọn ───────────────────────────


async def test_nothing_overdue_changes_nothing_no_error(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """DoD dòng 4 — đường chạy thường ngày, 2880 lần mỗi ngày."""
    mid = (
        await _message(
            session, user_a, status=MessageStatus.STREAMING, heartbeat_age_s=_still_fresh()
        )
    ).id

    await reaper(_ctx(fake_redis))

    after = await _reload(session_factory, mid)
    assert after.status is MessageStatus.STREAMING
    assert after.error_code is None
    assert fake_redis.records == []
    assert fake_redis.expire_calls == []


async def test_reaper_on_empty_table_does_not_raise(fake_redis: FakeRedis) -> None:
    """DoD dòng 4, ca không có message nào — `RETURNING` trả danh sách rỗng."""
    await reaper(_ctx(fake_redis))

    assert fake_redis.records == []


@pytest.mark.parametrize(
    "status",
    [
        MessageStatus.QUEUED,
        MessageStatus.COMPLETED,
        MessageStatus.FAILED,
        MessageStatus.CANCELLED,
    ],
)
async def test_only_touches_streaming_even_with_hours_old_heartbeat(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    status: MessageStatus,
) -> None:
    """§17.2: `heartbeat_at` chỉ có nghĩa khi `status='streaming'`.

    `finish_generation` cố ý **không** xoá `heartbeat_at` (nó là dấu vết "chết
    lúc nào"), nên mọi message đã khép đều mang một nhịp tim cũ. Bỏ vế
    `status` khỏi câu UPDATE là đánh `failed` toàn bộ lịch sử hội thoại.
    """
    mid = (await _message(session, user_a, status=status, heartbeat_age_s=3600)).id

    await reaper(_ctx(fake_redis))

    after = await _reload(session_factory, mid)
    assert after.status is status
    assert fake_redis.records == []


async def test_null_heartbeat_not_swept(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """`NULL < now() - interval` ra `NULL`, tức không khớp — và đó là lý do
    `mark_streaming` đặt `heartbeat_at` ngay lúc đổi trạng thái chứ không đợi
    nhịp đầu tiên. Test này canh chiều còn lại của giao kèo đó."""
    mid = (await _message(session, user_a, status=MessageStatus.STREAMING, heartbeat_age_s=None)).id

    await reaper(_ctx(fake_redis))

    after = await _reload(session_factory, mid)
    assert after.heartbeat_at is None
    assert after.status is MessageStatus.STREAMING


# ─────────────────────────── cách ly và thứ tự ───────────────────────────


async def test_one_message_redis_failure_does_not_block_others(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """Hai message cùng mồ côi; `XADD` của cái đầu nổ."""
    first = await _message(
        session, user_a, status=MessageStatus.STREAMING, heartbeat_age_s=_overdue()
    )
    second = await _message(
        session, user_a, status=MessageStatus.STREAMING, heartbeat_age_s=_overdue()
    )
    fake_redis.key_no = stream_key(first.id)

    await reaper(_ctx(fake_redis))

    # Postgres ghi TRƯỚC Redis, nên cả hai đều đã `failed` dù một cái không
    # ra được dây — đảo thứ tự là để FE hiện Retry trong khi DB nói "đang sinh".
    for mid in (first.id, second.id):
        assert (await _reload(session_factory, mid)).status is MessageStatus.FAILED
    assert fake_redis.entries_of(first.id) == []
    assert len(fake_redis.entries_of(second.id)) == 1


async def test_does_not_touch_running_generation_message(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
) -> None:
    """Một lượt mồ côi và một lượt còn nhịp, cùng một lượt quét."""
    dead = await _message(
        session, user_a, status=MessageStatus.STREAMING, heartbeat_age_s=_overdue()
    )
    alive_msg = await _message(
        session, user_a, status=MessageStatus.STREAMING, heartbeat_age_s=_still_fresh()
    )

    await reaper(_ctx(fake_redis))

    assert (await _reload(session_factory, dead.id)).status is MessageStatus.FAILED
    assert (await _reload(session_factory, alive_msg.id)).status is MessageStatus.STREAMING
    assert [b["__key__"] for b in fake_redis.records] == [stream_key(dead.id)]


# ─────────────────────── partial index và lịch cron ───────────────────────


async def test_update_inlines_streaming_as_CONSTANT_not_param(
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
    statements: list[str] = []

    def record(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        statements.append(statement)

    event.listen(connection.sync_engine, "before_cursor_execute", record)
    try:
        await MessageRepository(session).reap_stale_streaming(
            stale_after_s=90, error_code=ErrorCode.WORKER_LOST.value
        )
    finally:
        event.remove(connection.sync_engine, "before_cursor_execute", record)

    sql = next(c for c in statements if "RETURNING" in c and "UPDATE messages" in c)
    assert "messages.status = 'streaming'" in sql, sql
    assert "make_interval(secs=>90" in sql, sql


async def test_partial_index_matches_update_predicate(session: AsyncSession) -> None:
    """Vị từ của `ix_msg_streaming` phải đúng chữ mà câu UPDATE viết ra.

    Đọc từ `pg_indexes` của database test (schema do migration 0001 dựng), nên
    đổi migration mà quên câu UPDATE — hoặc ngược lại — thì test này đỏ.
    """
    definition = await session.scalar(
        text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_msg_streaming'")
    )
    assert definition is not None, "migration 0001 phải tạo ix_msg_streaming (§17.4)"
    assert "heartbeat_at" in definition
    assert "WHERE (status = 'streaming'::message_status)" in definition


def test_cron_registered_every_30_seconds() -> None:
    """§7.6 viết "Cron arq mỗi 30 s". arq nhận tập giây trong phút."""
    assert set(REAPER_SECONDS_IN_MINUTE) == {0, 30}

    schedule = [c for c in CRON_JOBS if c.name == REAPER_JOB_NAME]
    assert len(schedule) == 1, "đúng một cron reaper"
    assert schedule[0].second == {0, 30}
    assert schedule[0].minute is None, "mỗi phút, không phải mỗi giờ"


def test_cron_no_retry_and_no_two_concurrent_runs() -> None:
    """`max_tries=1`: tick sau vẫn thấy đúng những dòng ấy, thử lại vô nghĩa.
    `unique=True`: hai replica worker không cùng quét một tick."""
    schedule = next(c for c in CRON_JOBS if c.name == REAPER_JOB_NAME)

    assert schedule.max_tries == 1
    assert schedule.unique is True
    assert schedule.run_at_startup is False
