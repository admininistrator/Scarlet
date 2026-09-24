"""T-1.6 — `app/streaming/producer.py`: XADD, tên khoá, TTL.

KH tham chiếu: §7.2 ③, ADR-01, C8, C10.

Chạy trên một `Redis` giả ghi lại lời gọi, **không** trên Redis thật: thứ cần
canh ở đây là *hình dạng lời gọi* (tên khoá, hai trường, chuỗi JSON), và một
Redis thật không làm phép kiểm đó chặt hơn — nó chỉ làm bộ test cần thêm một
container. Đường chạy thật đi qua DoD của task (XLEN/XRANGE/TTL bằng
`redis-cli`) và qua `tests/workers/test_generate.py`.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from app.llm.client import Usage
from app.streaming.events import (
    DeltaEvent,
    DoneEvent,
    ErrorCode,
    ErrorEvent,
    StartEvent,
    TitleDoneEvent,
)
from app.streaming.producer import (
    FIELD_DATA,
    FIELD_TYPE,
    StreamProducer,
    stream_key,
    title_stream_key,
)


class FakeRedis:
    """Chỉ đủ `xadd`/`expire` cho producer. ID tăng dần như Redis thật."""

    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, str]]] = []
        self.expire_calls: list[tuple[str, int]] = []
        self._seq = 0

    async def xadd(self, name: str, fields: dict[str, Any]) -> bytes:
        self._seq += 1
        self.records.append((name, dict(fields)))
        # Redis trả bytes khi `decode_responses=False` — đúng cấu hình pool mà
        # arq dựng (`create_pool` chỉ đặt `encoding='utf8'`).
        return f"172598400000{self._seq}-0".encode()

    async def expire(self, name: str, ttl: int) -> int:
        self.expire_calls.append((name, ttl))
        return 1


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def mid() -> uuid.UUID:
    return uuid.uuid4()


def _producer(fake_redis: FakeRedis, mid: uuid.UUID, ttl_s: int = 3600) -> StreamProducer:
    return StreamProducer(fake_redis, mid, ttl_s=ttl_s)  # type: ignore[arg-type]


def test_key_name_follows_the_plan(mid: uuid.UUID) -> None:
    """§7.2 viết `stream:{amid}` — T-1.7 và reaper dùng lại chính hàm này."""
    assert stream_key(mid) == f"stream:{mid}"
    assert stream_key(str(mid)) == stream_key(mid)


async def test_xadd_uses_right_key_and_two_fields(fake_redis: FakeRedis, mid: uuid.UUID) -> None:
    await _producer(fake_redis, mid).emit(StartEvent(message_id=str(mid), model_id="mx"))

    ((name, fields),) = fake_redis.records
    assert name == f"stream:{mid}"
    assert set(fields) == {FIELD_TYPE, FIELD_DATA}
    assert fields[FIELD_TYPE] == "start"
    assert json.loads(fields[FIELD_DATA]) == {
        "message_id": str(mid),
        "model_id": "mx",
        "reasoning_effort": None,
    }


async def test_emit_returns_real_redis_id(fake_redis: FakeRedis, mid: uuid.UUID) -> None:
    """ID này thành `id:` của SSE rồi thành `Last-Event-ID` — không được tự sinh."""
    sid = await _producer(fake_redis, mid).emit(DeltaEvent(text="a"))
    assert isinstance(sid, str)
    assert sid.endswith("-0")


async def test_payload_always_json_even_with_newlines(
    fake_redis: FakeRedis, mid: uuid.UUID
) -> None:
    """C10 — DoD dòng 6. Xuống dòng thật trong `data:` cắt đôi khung SSE."""
    text = 'Một 🎉\nHai 😀\ndấu " và \\ và \t'
    await _producer(fake_redis, mid).emit(DeltaEvent(text=text))

    _, fields = fake_redis.records[0]
    assert "\n" not in fields[FIELD_DATA]
    assert json.loads(fields[FIELD_DATA])["t"] == text


async def test_expire_uses_stream_ttl(fake_redis: FakeRedis, mid: uuid.UUID) -> None:
    """C8 — quên `EXPIRE` thì Redis đầy dần trong vài tuần."""
    await _producer(fake_redis, mid, ttl_s=1234).expire()
    assert fake_redis.expire_calls == [(f"stream:{mid}", 1234)]


async def test_no_ttl_before_finishing(fake_redis: FakeRedis, mid: uuid.UUID) -> None:
    """`emit` không được tự đặt TTL: lượt sinh dài hơn TTL sẽ mất stream giữa chừng."""
    producer = _producer(fake_redis, mid)
    for _ in range(5):
        await producer.emit(DeltaEvent(text="x"))
    assert fake_redis.expire_calls == []


async def test_both_done_and_error_reach_the_wire(fake_redis: FakeRedis, mid: uuid.UUID) -> None:
    """C19: hai event kết thúc, cùng một đường ghi, không đường nào đặc biệt."""
    producer = _producer(fake_redis, mid)
    await producer.emit(
        DoneEvent(
            finish_reason="stop",
            usage=Usage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        )
    )
    await producer.emit(ErrorEvent(code=ErrorCode.UPSTREAM_ERROR, message="đứt"))

    kind = [fields[FIELD_TYPE] for _, fields in fake_redis.records]
    assert kind == ["done", "error"]
    assert json.loads(fake_redis.records[1][1][FIELD_DATA])["code"] == "UPSTREAM_ERROR"


# ═════════════ T-S.7 — stream tiêu đề `stream:title:{conversation_id}` ═════════════


def test_title_stream_key_follows_S14(fake_redis: FakeRedis) -> None:
    """Khoá chốt ở T-S.7 (§24.2b·S14): cùng tiền tố `stream:` — C8 và phép đếm của nó."""
    cid = uuid.uuid4()
    producer = StreamProducer.for_title(fake_redis, cid, ttl_s=60)  # type: ignore[arg-type]
    assert producer.key == title_stream_key(cid) == f"stream:title:{cid}"
    assert producer.key != stream_key(cid), "khong dung khoa voi stream cua mot message"


async def test_title_done_carries_title_only(fake_redis: FakeRedis) -> None:
    """`done` của stream tiêu đề: `{"title": …}` — không `finish_reason`, không tiền (C10)."""
    cid = uuid.uuid4()
    producer = StreamProducer.for_title(fake_redis, cid, ttl_s=60)  # type: ignore[arg-type]
    await producer.emit(TitleDoneEvent(title='Nấu phở "bò"\nmới'))
    ((name, fields),) = fake_redis.records
    assert name == f"stream:title:{cid}"
    assert fields[FIELD_TYPE] == "done"
    assert json.loads(fields[FIELD_DATA]) == {"title": 'Nấu phở "bò"\nmới'}
