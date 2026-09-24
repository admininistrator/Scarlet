"""T-1.7 — `app/streaming/consumer.py`: cursor, XRANGE → XREAD, `: ping`, fallback.

KH tham chiếu: §7.2 ②, §7.3, §7.4, C3, C4, C7, C10.

`FakeRedis` ở đây **không phải** một stub ghi lại lời gọi như trong
`test_producer.py`. Nó hiện thực đúng ngữ nghĩa của `XRANGE`/`XREAD`/`EXISTS`
trên Redis Stream, kể cả ba chi tiết mà cả ba cạm bẫy của task này sống nhờ:

- `(id` là **loại trừ**, `[id` (hoặc `id` trần) là bao gồm — C3;
- `XREAD` từ `$` giải ra ID lớn nhất **tại thời điểm gọi lệnh**, nên bản ghi
  sinh ra giữa `XRANGE` và `XREAD` bị bỏ qua — C4;
- đọc **không** xoá gì, nên hai client cùng đọc đều nhận đủ — C7.

Một stub chỉ ghi lại lời gọi sẽ xanh với cả `(cursor` lẫn `[cursor`, tức là nó
không kiểm được đúng thứ task này tồn tại để làm đúng. `moc_sau_xrange_rong`
dựng lại khoảnh khắc nguy hiểm của C4: worker ghi thêm chữ **sau** khi
`XRANGE` cuối cùng trả rỗng nhưng **trước** khi `XREAD` kịp chạy.

DoD chạy trên Redis thật (`curl -kN` qua Nginx) nằm trong báo cáo của task.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from app.db.models import MessageStatus
from app.streaming.consumer import (
    CURSOR_START,
    PING_FRAME,
    InvalidCursor,
    MessageSnapshot,
    StreamConsumer,
    parse_cursor,
    sse_frame,
)
from app.streaming.events import DeltaEvent, DoneEvent, ErrorCode
from app.streaming.producer import FIELD_DATA, FIELD_TYPE, encode_event

HEARTBEAT_S = 15


# ───────────────────────── Redis Stream giả, đúng ngữ nghĩa ─────────────────


def _id_key(raw: str) -> tuple[int, int]:
    """`"1725984000123-4"` → `(1725984000123, 4)`; `"7"` → `(7, 0)`."""
    if "-" in raw:
        ms, seq = raw.split("-", 1)
        return int(ms), int(seq)
    return int(raw), 0


def _lower_bound(start: str) -> tuple[int, int]:
    """Biên dưới của `XRANGE`. Dấu `(` đẩy nó lên đúng một nấc — đây là C3."""
    if start.startswith("("):
        ms, seq = _id_key(start[1:])
        return ms, seq + 1
    return _id_key(start)


class FakeRedis:
    __slots__ = ("streams", "after_empty_xrange", "xread_called_with", "xread_calls")

    def __init__(self) -> None:
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        #: Hàm chạy NGAY SAU khi một `XRANGE` trả rỗng — dựng lại khoảnh khắc
        #: của C4. Xem docstring module.
        self.after_empty_xrange: Any = None
        self.xread_called_with: list[str] = []
        self.xread_calls = 0

    # ── công cụ của test, không phải API của Redis ──
    def add(self, key: str, kind: str, data: dict[str, Any]) -> str:
        entries = self.streams.setdefault(key, [])
        entry_id = f"172598400{len(entries):04d}-0"
        entries.append(
            (entry_id, {FIELD_TYPE: kind, FIELD_DATA: json.dumps(data, ensure_ascii=False)})
        )
        return entry_id

    def ids(self, key: str) -> list[str]:
        return [eid for eid, _ in self.streams.get(key, [])]

    # ── phần bắt chước Redis ──
    async def xrange(
        self, name: str, start: str, end: str, count: int | None = None
    ) -> list[tuple[str, dict[str, str]]]:
        assert end == "+", "consumer phai doc toi cuoi stream"
        low = _lower_bound(start)
        result = [
            (eid, fields) for eid, fields in self.streams.get(name, []) if _id_key(eid) >= low
        ]
        if count is not None:
            result = result[:count]
        if not result and self.after_empty_xrange is not None:
            hook, self.after_empty_xrange = self.after_empty_xrange, None
            hook()
        return result

    async def xread(
        self, streams: dict[str, str], block: int | None = None, count: int | None = None
    ) -> list[tuple[str, list[tuple[str, dict[str, str]]]]] | None:
        assert block == HEARTBEAT_S * 1000, "BLOCK phai bang STREAM_HEARTBEAT_S"
        self.xread_calls += 1
        ((name, hook),) = streams.items()
        self.xread_called_with.append(hook)
        entries = self.streams.get(name, [])
        # `$` giải ra ID lớn nhất TẠI THỜI ĐIỂM GỌI — đây là nửa còn lại của C4.
        low = _id_key(entries[-1][0]) if (hook == "$" and entries) else _id_key(hook)
        newer = [(eid, f) for eid, f in entries if _id_key(eid) > low]
        if count is not None:
            newer = newer[:count]
        return [(name, newer)] if newer else None

    async def xrevrange(
        self, name: str, max: str = "+", min: str = "-", count: int | None = None
    ) -> list[tuple[str, dict[str, str]]]:
        """B-84. Chỉ dựng đúng ca consumer cần: toàn stream, đảo ngược, cắt `count`."""
        assert (max, min) == ("+", "-"), "consumer chi hoi ban ghi CUOI cua ca stream"
        reversed_entries = list(reversed(self.streams.get(name, [])))
        return reversed_entries[:count] if count is not None else reversed_entries

    async def exists(self, name: str) -> int:
        return 1 if name in self.streams else 0

    def __getattr__(self, name: str) -> Any:
        # C7: consumer group là lỗi thiết kế ở đây, không phải lựa chọn. Chạm
        # vào bất kỳ lệnh nào của group là đỏ ngay, kể cả khi test khác vẫn xanh.
        raise AssertionError(f"consumer khong duoc goi Redis.{name} (C7: khong consumer group)")


# ──────────────────────────────── công cụ ──────────────────────────────────


def _snapshot(
    mid: uuid.UUID,
    *,
    status: MessageStatus = MessageStatus.STREAMING,
    content: str = "",
    model_id: str | None = "mx",
    reasoning_effort: str | None = None,
    finish_reason: str | None = None,
    error_code: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
) -> MessageSnapshot:
    return MessageSnapshot(
        message_id=mid,
        status=status,
        content=content,
        model_id=model_id,
        reasoning_effort=reasoning_effort,
        finish_reason=finish_reason,
        error_code=error_code,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


def _consumer(redis: FakeRedis, snapshot: MessageSnapshot) -> StreamConsumer:
    return StreamConsumer(redis, snapshot, heartbeat_s=HEARTBEAT_S)  # type: ignore[arg-type]


async def _collect(consumer: StreamConsumer, cursor: str, *, max_frames: int = 50) -> list[str]:
    """Đọc tối đa `max_frames` khung rồi dừng — stream chưa `done` thì chờ mãi."""
    frame: list[str] = []
    async for k in consumer.frames(cursor):
        frame.append(k)
        if len(frame) >= max_frames:
            break
    return frame


def _field(frame: str, name: str) -> list[str]:
    return [d[len(name) + 2 :] for d in frame.split("\n") if d.startswith(f"{name}: ")]


def _joined_text(frame: list[str]) -> str:
    """Nối mọi `delta` — đúng việc mà `sse.ts` (T-1.14) sẽ làm."""
    out = []
    for k in frame:
        if _field(k, "event") == ["delta"]:
            out.append(json.loads("\n".join(_field(k, "data")))["t"])
    return "".join(out)


def _sample_stream(redis: FakeRedis, key: str, so_delta: int = 5, *, done: bool = True) -> None:
    redis.add(key, "start", {"message_id": "m", "model_id": "mx"})
    for i in range(so_delta):
        redis.add(key, "delta", {"t": f"chu{i}"})
    if done:
        redis.add(key, "done", {"finish_reason": "stop", "usage": None})


# ═══════════════════════════ cursor (§7.2 ②) ═══════════════════════════════


def test_defaults_to_0_when_nothing_given() -> None:
    assert parse_cursor(None, None) == CURSOR_START


def test_last_event_id_beats_query_cursor() -> None:
    """EventSource giữ nguyên URL cũ khi reconnect — để query thắng là phát lại từ đầu."""
    assert parse_cursor("1725984000123-0", "0") == "1725984000123-0"


def test_uses_query_cursor_without_header() -> None:
    assert parse_cursor(None, "1725984000123-4") == "1725984000123-4"


@pytest.mark.parametrize("blank", ["", "   "])
def test_empty_header_treated_as_missing(blank: str) -> None:
    """Có proxy gửi `Last-Event-ID:` rỗng — 400 ở đây là chặn client đang quay lại."""
    assert parse_cursor(blank, "77-0") == "77-0"


@pytest.mark.parametrize("bad", ["abc", "$", "-", "1-2-3", "1725984000123-", "(77", "1e5"])
def test_malformed_cursor_raises_not_rewinds_to_0(bad: str) -> None:
    """Âm thầm lùi về 0 là phát lại từ đầu — đúng triệu chứng C3, mà không ai thấy."""
    with pytest.raises(InvalidCursor):
        parse_cursor(bad, None)


def test_millisecond_only_cursor_is_valid() -> None:
    assert parse_cursor(None, "1725984000123") == "1725984000123"


# ═════════════════════════ khung SSE (§7.4, C10) ═══════════════════════════


def test_frame_has_three_fields_and_blank_line_terminator() -> None:
    assert (
        sse_frame("delta", '{"t":"a"}', event_id="7-0")
        == 'id: 7-0\nevent: delta\ndata: {"t":"a"}\n\n'
    )


def test_frame_without_id_drops_id_line() -> None:
    assert sse_frame("done", "{}") == "event: done\ndata: {}\n\n"


def test_multiline_data_becomes_multiple_data_lines() -> None:
    """Lớp thứ hai của C10: một payload lọt vào stream mà không qua `encode_event`."""
    frame = sse_frame("delta", "a\nb\r\nc")
    assert _field(frame, "data") == ["a", "b", "c"]
    assert frame.endswith("\n\n")


def test_newline_in_event_name_is_flattened() -> None:
    """`event:` là trường MỘT dòng — một `\\n` ở đây cắt đôi mọi khung phía sau."""
    assert _field(sse_frame("de\nlta", "{}"), "event") == ["de lta"]


# ═══════════════ ① XRANGE (cursor, +] — đuổi kịp, không lặp (C3) ═══════════


async def test_cursor_0_replays_from_start_all_entries() -> None:
    """DoD: chạy lại với `cursor=0` → nhận lại từ đầu, đủ số bản ghi bằng XLEN."""
    redis = FakeRedis()
    mid = uuid.uuid4()
    consumer = _consumer(redis, _snapshot(mid))
    _sample_stream(redis, consumer.key)

    frame = await _collect(consumer, CURSOR_START)

    assert len(frame) == len(redis.ids(consumer.key)) == 7
    assert _joined_text(frame) == "chu0chu1chu2chu3chu4"


async def test_xrange_excludes_cursor_no_resend_of_received_entry() -> None:
    """C3 — `[cursor` thay vì `(cursor` làm reconnect thấy một đoạn chữ LẶP."""
    redis = FakeRedis()
    mid = uuid.uuid4()
    consumer = _consumer(redis, _snapshot(mid))
    _sample_stream(redis, consumer.key)
    ids = redis.ids(consumer.key)

    frame = await _collect(consumer, ids[2])  # đã nhận tới delta thứ hai

    assert _field(frame[0], "id") == [ids[3]], "ban ghi tai cursor KHONG duoc gui lai"
    assert _joined_text(frame) == "chu2chu3chu4"


async def test_joining_two_halves_equals_original_no_more_no_less() -> None:
    """Phép đo của S3/T-1.11 thu nhỏ: ngắt ở giữa rồi nối `A + B`."""
    redis = FakeRedis()
    mid = uuid.uuid4()
    full = _consumer(redis, _snapshot(mid))
    _sample_stream(redis, full.key, so_delta=9)
    ids = redis.ids(full.key)

    half_a = await _collect(full, CURSOR_START, max_frames=5)
    last_id = _field(half_a[-1], "id")[0]
    half_b = await _collect(_consumer(redis, _snapshot(mid)), last_id)

    assert _joined_text(half_a + half_b) == "".join(f"chu{i}" for i in range(9))
    assert [i for k in half_a + half_b for i in _field(k, "id")] == ids


# ═════════ ② XREAD BLOCK từ ID CUỐI CÙNG ĐÃ GỬI — không phải `$` (C4) ══════


async def test_xread_waits_from_last_sent_id() -> None:
    redis = FakeRedis()
    mid = uuid.uuid4()
    consumer = _consumer(redis, _snapshot(mid))
    _sample_stream(redis, consumer.key, done=False)
    ids = redis.ids(consumer.key)

    await _collect(consumer, CURSOR_START, max_frames=len(ids) + 1)

    assert redis.xread_called_with == [ids[-1]], "XREAD phai moi bang ID cuoi, khong phai `$`"


async def test_no_entry_lost_between_xrange_and_xread() -> None:
    """C4 — cạm bẫy tinh vi nhất: chỉ sai khi có độ trễ giữa hai lệnh.

    `moc_sau_xrange_rong` ghi thêm chữ đúng vào khe đó. Với `XREAD` từ `$`,
    `$` giải ra ID của chính bản ghi vừa thêm nên nó bị bỏ qua vĩnh viễn.
    """
    redis = FakeRedis()
    mid = uuid.uuid4()
    consumer = _consumer(redis, _snapshot(mid))
    _sample_stream(redis, consumer.key, so_delta=3, done=False)

    def keep_generating() -> None:
        redis.add(consumer.key, "delta", {"t": "-trong-khe"})
        redis.add(consumer.key, "done", {"finish_reason": "stop", "usage": None})

    redis.after_empty_xrange = keep_generating

    frame = await _collect(consumer, CURSOR_START)

    assert _joined_text(frame) == "chu0chu1chu2-trong-khe"
    assert _field(frame[-1], "event") == ["done"]


async def test_pings_when_block_expires_and_keeps_waiting() -> None:
    """DoD: không có event mới trong 20 s → thấy `: ping`, kết nối chưa đứt."""
    redis = FakeRedis()
    mid = uuid.uuid4()
    consumer = _consumer(redis, _snapshot(mid))
    _sample_stream(redis, consumer.key, so_delta=1, done=False)

    frame: list[str] = []
    async for k in consumer.frames(CURSOR_START):
        frame.append(k)
        if frame.count(PING_FRAME) == 3:
            # Chữ tới SAU ba nhịp im lặng — đúng hình dạng của một model nghĩ lâu.
            redis.add(consumer.key, "done", {"finish_reason": "stop", "usage": None})

    assert frame.count(PING_FRAME) == 3
    assert _field(frame[-1], "event") == ["done"]
    assert PING_FRAME.startswith(":"), "ping phai la COMMENT, khong phai event"


@pytest.mark.parametrize("terminal_event", ["done", "error"])
async def test_stops_right_after_terminal_event(terminal_event: str) -> None:
    """§7.4: chỉ `done` hoặc `error` mới đóng stream — và chúng đóng THẬT."""
    redis = FakeRedis()
    mid = uuid.uuid4()
    consumer = _consumer(redis, _snapshot(mid))
    redis.add(consumer.key, "delta", {"t": "a"})
    redis.add(consumer.key, terminal_event, {"code": "UPSTREAM_ERROR"})
    redis.add(consumer.key, "delta", {"t": "khong-duoc-gui"})

    frame = await _collect(consumer, CURSOR_START)

    assert [_field(k, "event")[0] for k in frame] == ["delta", terminal_event]
    assert redis.xread_calls == 0, "da co event ket thuc thi khong duoc BLOCK them"


# ═════════ ②bis — cursor đứng sau event kết thúc (B-84) ══════════


@pytest.mark.parametrize("terminal_event", ["done", "error"])
async def test_cursor_after_terminal_event_replays_then_closes(terminal_event: str) -> None:
    """B-84: client đã nhận `done` mà vẫn quay lại — **không được** treo.

    Không có khối ②bis thì `XRANGE (cursor +` rỗng, stream vẫn còn nên đường
    Postgres không nhận, và `XREAD BLOCK` chờ một bản ghi không bao giờ tới.
    """
    redis = FakeRedis()
    mid = uuid.uuid4()
    consumer = _consumer(redis, _snapshot(mid, status=MessageStatus.COMPLETED, content="a"))
    redis.add(consumer.key, "delta", {"t": "a"})
    last_id = redis.add(consumer.key, terminal_event, {"code": "UPSTREAM_ERROR"})

    frame = await _collect(consumer, last_id)

    assert [_field(k, "event")[0] for k in frame] == [terminal_event]
    assert _field(frame[0], "id") == [last_id], "phat lai dung ban ghi cu, khong bia ID"
    assert redis.xread_calls == 0, "khong duoc BLOCK cho mot ban ghi khong bao gio toi"


async def test_replaying_terminal_event_adds_no_characters() -> None:
    """C3 vẫn yên: thứ được phát lại là `done`, mà `done` không mang chữ."""
    redis = FakeRedis()
    mid = uuid.uuid4()
    consumer = _consumer(redis, _snapshot(mid, status=MessageStatus.COMPLETED, content="chu0"))
    redis.add(consumer.key, "delta", {"t": "chu0"})
    id_done = redis.add(consumer.key, "done", {"finish_reason": "stop", "usage": None})

    assert _joined_text(await _collect(consumer, id_done)) == ""


async def test_cursor_after_last_entry_NOT_FINISHED_keeps_waiting() -> None:
    """Nửa còn lại của B-84: bản ghi cuối là `delta` thì đóng là cắt giữa chừng.

    Đây là khe vài mili-giây mà B-84 cảnh báo: worker ghi Postgres TRƯỚC rồi
    `XADD done` SAU, nên `status` đã `completed` trong khi `done` chưa lên dây.
    ②bis hỏi `messages.status` thay vì hỏi chính stream thì test này đỏ.
    """
    redis = FakeRedis()
    mid = uuid.uuid4()
    consumer = _consumer(redis, _snapshot(mid, status=MessageStatus.COMPLETED, content="a"))
    id_delta = redis.add(consumer.key, "delta", {"t": "a"})

    def worker_writes_rest() -> None:
        redis.add(consumer.key, "done", {"finish_reason": "stop", "usage": None})

    redis.after_empty_xrange = worker_writes_rest
    frame = await _collect(consumer, id_delta)

    assert [_field(k, "event")[0] for k in frame] == ["done"]
    assert redis.xread_calls == 1, "phai di tiep sang XREAD chu khong duoc dong"


async def test_entry_newer_than_cursor_not_swallowed_by_replay_branch() -> None:
    """Khe C4 bên trong chính ②bis: worker kịp ghi `delta` RỒI `done`.

    `XREVRANGE COUNT 1` chỉ thấy `done`; phát nó rồi đóng là nuốt mất `delta` ở
    giữa. Bỏ phép so `_thu_tu_id(...) <= last_id` thì test này đỏ đúng chỗ đó.
    """
    redis = FakeRedis()
    mid = uuid.uuid4()
    consumer = _consumer(redis, _snapshot(mid, status=MessageStatus.COMPLETED, content="ab"))
    id_delta = redis.add(consumer.key, "delta", {"t": "a"})

    def worker_writes_rest() -> None:
        redis.add(consumer.key, "delta", {"t": "b"})
        redis.add(consumer.key, "done", {"finish_reason": "stop", "usage": None})

    redis.after_empty_xrange = worker_writes_rest
    frame = await _collect(consumer, id_delta)

    assert _joined_text(frame) == "b", "phan sinh ra trong khe KHONG duoc mat"
    assert [_field(k, "event")[0] for k in frame] == ["delta", "done"]


async def test_millisecond_only_cursor_still_detects_passed_terminal_event() -> None:
    """`?cursor=1725984000005` (không có `-seq`) vẫn phải bằng `1725984000005-0`.

    So hai ID bằng chuỗi thì `"...005-0" <= "...005"` là `False` và client treo
    đúng ca B-84 mô tả. `parse_cursor` cho phép dạng chỉ-mili-giây này (xem
    `test_millisecond_only_cursor_is_valid`) nên nó không phải ca giả định.
    """
    redis = FakeRedis()
    mid = uuid.uuid4()
    consumer = _consumer(redis, _snapshot(mid, status=MessageStatus.COMPLETED, content=""))
    redis.streams[consumer.key] = [
        (
            "1725984000005-0",
            {FIELD_TYPE: "done", FIELD_DATA: json.dumps({"finish_reason": "stop"})},
        )
    ]

    frame = await _collect(consumer, "1725984000005")

    assert [_field(k, "event")[0] for k in frame] == ["done"]
    assert redis.xread_calls == 0


# ════════════════════════ ③ hai client song song (C7) ══════════════════════


async def test_two_concurrent_clients_both_get_every_event() -> None:
    """DoD: hai `curl -N` song song cùng một message → cả hai nhận đủ.

    `FakeRedis.__getattr__` đã chặn mọi lệnh consumer group; test này kiểm nửa
    còn lại của C7 — đọc không làm bản ghi biến mất với người đọc kia.
    """
    redis = FakeRedis()
    mid = uuid.uuid4()
    tab_a = _consumer(redis, _snapshot(mid))
    tab_b = _consumer(redis, _snapshot(mid))
    _sample_stream(redis, tab_a.key)

    frames_a = await _collect(tab_a, CURSOR_START)
    frames_b = await _collect(tab_b, CURSOR_START)

    assert _joined_text(frames_a) == _joined_text(frames_b) == "chu0chu1chu2chu3chu4"
    assert frames_a == frames_b


# ═══════════════════ mỗi event mang `id:` là Redis Stream ID ═══════════════


async def test_every_event_carries_its_redis_id() -> None:
    redis = FakeRedis()
    mid = uuid.uuid4()
    consumer = _consumer(redis, _snapshot(mid))
    _sample_stream(redis, consumer.key)

    frame = await _collect(consumer, CURSOR_START)

    assert [_field(k, "id")[0] for k in frame] == redis.ids(consumer.key)


async def test_copies_data_verbatim_without_reparsing() -> None:
    """Parse rồi dumps lại có thể đổi thứ tự khoá — consumer không đụng payload."""
    redis = FakeRedis()
    mid = uuid.uuid4()
    consumer = _consumer(redis, _snapshot(mid))
    raw = '{"z":1,"a":2}'
    redis.streams[consumer.key] = [("1-0", {FIELD_TYPE: "delta", FIELD_DATA: raw})]
    redis.add(consumer.key, "done", {"finish_reason": "stop", "usage": None})

    frame = await _collect(consumer, CURSOR_START)

    assert _field(frame[0], "data") == [raw]


async def test_vietnamese_and_emoji_pass_through_intact() -> None:
    """C9/C10 — nối lại phải bằng chuỗi gốc, kể cả emoji và dấu xuống dòng."""
    redis = FakeRedis()
    mid = uuid.uuid4()
    consumer = _consumer(redis, _snapshot(mid))
    text = "Mùa thu 🍂\nlá rụng ☕"
    redis.add(consumer.key, "delta", {"t": text})
    redis.add(consumer.key, "done", {"finish_reason": "stop", "usage": None})

    frame = await _collect(consumer, CURSOR_START)

    assert _joined_text(frame) == text
    assert len(_field(frame[0], "data")) == 1, "json.dumps phai escape xuong dong (C10)"


async def test_entry_missing_fields_skipped_not_breaking_frame() -> None:
    redis = FakeRedis()
    mid = uuid.uuid4()
    consumer = _consumer(redis, _snapshot(mid))
    redis.streams[consumer.key] = [("1-0", {FIELD_TYPE: "delta"})]
    redis.add(consumer.key, "done", {"finish_reason": "stop", "usage": None})

    frame = await _collect(consumer, CURSOR_START)

    assert [_field(k, "event")[0] for k in frame] == ["done"]


# ══════════ stream hết TTL, message đã khép → dựng lại từ Postgres ═════════


async def test_expired_stream_completed_message_sends_content_then_done() -> None:
    """DoD: message `completed` từ 2 giờ trước → vẫn trả content đầy đủ + `done`."""
    redis = FakeRedis()
    mid = uuid.uuid4()
    consumer = _consumer(
        redis,
        _snapshot(
            mid,
            status=MessageStatus.COMPLETED,
            content="câu trả lời của hôm qua",
            finish_reason="stop",
            prompt_tokens=297,
            completion_tokens=298,
        ),
    )

    frame = await _collect(consumer, CURSOR_START)

    assert [_field(k, "event")[0] for k in frame] == ["start", "delta", "done"]
    assert _joined_text(frame) == "câu trả lời của hôm qua"
    last = json.loads(_field(frame[-1], "data")[0])
    assert last == {"finish_reason": "stop", "usage": {"in": 297, "out": 298}}
    assert redis.xread_calls == 0, "khong duoc BLOCK khi da tra loi xong tu Postgres"


@pytest.mark.parametrize("level", ["low", None])
async def test_postgres_path_start_carries_reasoning_effort(level: str | None) -> None:
    """T-S.6: mở lại sau khi stream hết TTL vẫn ra đúng chip "model · mức".

    Cùng một `start` với đường Redis — kể cả khoá `reasoning_effort: null` của
    model không khai mức — để FE chỉ có một cách đọc event này.
    """
    mid = uuid.uuid4()
    consumer = _consumer(
        FakeRedis(),
        _snapshot(mid, status=MessageStatus.COMPLETED, content="x", reasoning_effort=level),
    )

    frame = await _collect(consumer, CURSOR_START)

    start = json.loads(_field(frame[0], "data")[0])
    assert start == {"message_id": str(mid), "model_id": "mx", "reasoning_effort": level}


async def test_postgres_path_carries_no_id() -> None:
    """Không còn stream nào để trỏ tới — bịa một ID là phát ra cursor vô nghĩa."""
    redis = FakeRedis()
    consumer = _consumer(
        redis, _snapshot(uuid.uuid4(), status=MessageStatus.COMPLETED, content="x")
    )

    frame = await _collect(consumer, CURSOR_START)

    assert all(_field(k, "id") == [] for k in frame)


async def test_postgres_path_shares_encode_event_with_producer() -> None:
    """Hai đường phải ra cùng một chuỗi `data:`, nếu không FE cần hai parser."""
    redis = FakeRedis()
    consumer = _consumer(
        redis, _snapshot(uuid.uuid4(), status=MessageStatus.COMPLETED, content="xin chào")
    )

    frame = await _collect(consumer, CURSOR_START)

    assert _field(frame[1], "data") == [encode_event(DeltaEvent(text="xin chào"))[1]]
    assert _field(frame[2], "data") == [encode_event(DoneEvent(finish_reason=None, usage=None))[1]]


async def test_expired_stream_failed_message_sends_error_with_code() -> None:
    redis = FakeRedis()
    consumer = _consumer(
        redis,
        _snapshot(
            uuid.uuid4(),
            status=MessageStatus.FAILED,
            content="phần đã sinh được",
            error_code=ErrorCode.UPSTREAM_ERROR.value,
        ),
    )

    frame = await _collect(consumer, CURSOR_START)

    assert [_field(k, "event")[0] for k in frame] == ["start", "delta", "error"]
    # Phần chữ đã sinh vẫn tới người dùng: `finish_generation` giữ nó cho cả đường lỗi.
    assert _joined_text(frame) == "phần đã sinh được"
    assert json.loads(_field(frame[-1], "data")[0])["code"] == "UPSTREAM_ERROR"


@pytest.mark.parametrize("code", [None, "MA_KHONG_CO_THAT"])
async def test_null_or_unknown_error_code_becomes_internal_error(code: str | None) -> None:
    redis = FakeRedis()
    consumer = _consumer(
        redis, _snapshot(uuid.uuid4(), status=MessageStatus.FAILED, error_code=code)
    )

    frame = await _collect(consumer, CURSOR_START)

    assert json.loads(_field(frame[-1], "data")[0])["code"] == "INTERNAL_ERROR"


async def test_cancelled_message_takes_done_path_not_error() -> None:
    """§7.5: huỷ vẫn là một lượt sinh khép lại bình thường, chỉ khác `finish_reason`."""
    redis = FakeRedis()
    consumer = _consumer(
        redis,
        _snapshot(
            uuid.uuid4(),
            status=MessageStatus.CANCELLED,
            content="một nửa",
            finish_reason="cancelled",
        ),
    )

    frame = await _collect(consumer, CURSOR_START)

    assert _field(frame[-1], "event") == ["done"]
    assert json.loads(_field(frame[-1], "data")[0])["finish_reason"] == "cancelled"


async def test_without_model_id_start_event_is_dropped() -> None:
    """Chết trước khi kịp chọn model thì không có gì để khai báo — `""` là sai."""
    redis = FakeRedis()
    consumer = _consumer(redis, _snapshot(uuid.uuid4(), status=MessageStatus.FAILED, model_id=None))

    frame = await _collect(consumer, CURSOR_START)

    assert [_field(k, "event")[0] for k in frame] == ["error"]


async def test_empty_content_yields_no_empty_delta() -> None:
    redis = FakeRedis()
    consumer = _consumer(redis, _snapshot(uuid.uuid4(), status=MessageStatus.COMPLETED, content=""))

    frame = await _collect(consumer, CURSOR_START)

    assert [_field(k, "event")[0] for k in frame] == ["start", "done"]


@pytest.mark.parametrize("unfinished", [MessageStatus.QUEUED, MessageStatus.STREAMING])
async def test_open_message_does_NOT_take_postgres_path(unfinished: MessageStatus) -> None:
    """`queued`/`streaming` nghĩa là chữ vẫn sẽ tới — trả câu rỗng lúc đó là nói dối."""
    redis = FakeRedis()
    consumer = _consumer(redis, _snapshot(uuid.uuid4(), status=unfinished, content=""))

    frame = await _collect(consumer, CURSOR_START, max_frames=2)

    assert frame == [PING_FRAME, PING_FRAME]


async def test_live_stream_reads_redis_not_postgres() -> None:
    """Redis là nguồn của phần đang bay; Postgres chỉ vào cuộc khi stream đã mất."""
    redis = FakeRedis()
    mid = uuid.uuid4()
    consumer = _consumer(
        redis, _snapshot(mid, status=MessageStatus.COMPLETED, content="BAN-CUA-POSTGRES")
    )
    _sample_stream(redis, consumer.key, so_delta=2)

    frame = await _collect(consumer, CURSOR_START)

    assert _joined_text(frame) == "chu0chu1"


# ═══════════════════════════ MessageSnapshot.usage ═════════════════════════


def test_usage_correct_when_both_columns_present() -> None:
    usage = _snapshot(uuid.uuid4(), prompt_tokens=10, completion_tokens=4).usage()
    assert usage is not None
    assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (10, 4, 14)
    # NQ-23: hai cột này không có chỗ trong `messages`, nên chúng phải VẮNG MẶT.
    assert usage.reasoning_tokens is None
    assert usage.cached_prompt_tokens is None


@pytest.mark.parametrize(("entry", "out"), [(None, 4), (10, None), (None, None)])
def test_missing_one_column_usage_is_None_not_0(entry: int | None, out: int | None) -> None:
    """Điền 0 vào chỗ vắng biến một lượt chat thành miễn phí trong sổ sách (C40)."""
    assert _snapshot(uuid.uuid4(), prompt_tokens=entry, completion_tokens=out).usage() is None
