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
from app.streaming.events import DeltaEvent, DoneEvent, ErrorCode, ErrorEvent, StartEvent
from app.streaming.producer import FIELD_DATA, FIELD_TYPE, StreamProducer, stream_key


class RedisGia:
    """Chỉ đủ `xadd`/`expire` cho producer. ID tăng dần như Redis thật."""

    def __init__(self) -> None:
        self.ban_ghi: list[tuple[str, dict[str, str]]] = []
        self.expire_calls: list[tuple[str, int]] = []
        self._seq = 0

    async def xadd(self, name: str, fields: dict[str, Any]) -> bytes:
        self._seq += 1
        self.ban_ghi.append((name, dict(fields)))
        # Redis trả bytes khi `decode_responses=False` — đúng cấu hình pool mà
        # arq dựng (`create_pool` chỉ đặt `encoding='utf8'`).
        return f"172598400000{self._seq}-0".encode()

    async def expire(self, name: str, ttl: int) -> int:
        self.expire_calls.append((name, ttl))
        return 1


@pytest.fixture
def redis_gia() -> RedisGia:
    return RedisGia()


@pytest.fixture
def mid() -> uuid.UUID:
    return uuid.uuid4()


def _producer(redis_gia: RedisGia, mid: uuid.UUID, ttl_s: int = 3600) -> StreamProducer:
    return StreamProducer(redis_gia, mid, ttl_s=ttl_s)  # type: ignore[arg-type]


def test_ten_khoa_dung_dang_cua_ke_hoach(mid: uuid.UUID) -> None:
    """§7.2 viết `stream:{amid}` — T-1.7 và reaper dùng lại chính hàm này."""
    assert stream_key(mid) == f"stream:{mid}"
    assert stream_key(str(mid)) == stream_key(mid)


async def test_xadd_dung_khoa_va_dung_hai_truong(redis_gia: RedisGia, mid: uuid.UUID) -> None:
    await _producer(redis_gia, mid).emit(StartEvent(message_id=str(mid), model_id="mx"))

    ((name, fields),) = redis_gia.ban_ghi
    assert name == f"stream:{mid}"
    assert set(fields) == {FIELD_TYPE, FIELD_DATA}
    assert fields[FIELD_TYPE] == "start"
    assert json.loads(fields[FIELD_DATA]) == {"message_id": str(mid), "model_id": "mx"}


async def test_emit_tra_ve_id_that_cua_redis(redis_gia: RedisGia, mid: uuid.UUID) -> None:
    """ID này thành `id:` của SSE rồi thành `Last-Event-ID` — không được tự sinh."""
    sid = await _producer(redis_gia, mid).emit(DeltaEvent(text="a"))
    assert isinstance(sid, str)
    assert sid.endswith("-0")


async def test_payload_luon_la_json_ke_ca_khi_co_xuong_dong(
    redis_gia: RedisGia, mid: uuid.UUID
) -> None:
    """C10 — DoD dòng 6. Xuống dòng thật trong `data:` cắt đôi khung SSE."""
    chu = 'Một 🎉\nHai 😀\ndấu " và \\ và \t'
    await _producer(redis_gia, mid).emit(DeltaEvent(text=chu))

    _, fields = redis_gia.ban_ghi[0]
    assert "\n" not in fields[FIELD_DATA]
    assert json.loads(fields[FIELD_DATA])["t"] == chu


async def test_expire_dung_stream_ttl(redis_gia: RedisGia, mid: uuid.UUID) -> None:
    """C8 — quên `EXPIRE` thì Redis đầy dần trong vài tuần."""
    await _producer(redis_gia, mid, ttl_s=1234).expire()
    assert redis_gia.expire_calls == [(f"stream:{mid}", 1234)]


async def test_khong_dat_ttl_truoc_khi_ket_thuc(redis_gia: RedisGia, mid: uuid.UUID) -> None:
    """`emit` không được tự đặt TTL: lượt sinh dài hơn TTL sẽ mất stream giữa chừng."""
    producer = _producer(redis_gia, mid)
    for _ in range(5):
        await producer.emit(DeltaEvent(text="x"))
    assert redis_gia.expire_calls == []


async def test_ca_done_lan_error_deu_ra_duoc_day(redis_gia: RedisGia, mid: uuid.UUID) -> None:
    """C19: hai event kết thúc, cùng một đường ghi, không đường nào đặc biệt."""
    producer = _producer(redis_gia, mid)
    await producer.emit(
        DoneEvent(
            finish_reason="stop",
            usage=Usage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        )
    )
    await producer.emit(ErrorEvent(code=ErrorCode.UPSTREAM_ERROR, message="đứt"))

    loai = [fields[FIELD_TYPE] for _, fields in redis_gia.ban_ghi]
    assert loai == ["done", "error"]
    assert json.loads(redis_gia.ban_ghi[1][1][FIELD_DATA])["code"] == "UPSTREAM_ERROR"
