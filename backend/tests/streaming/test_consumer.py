"""T-1.7 — `app/streaming/consumer.py`: cursor, XRANGE → XREAD, `: ping`, fallback.

KH tham chiếu: §7.2 ②, §7.3, §7.4, C3, C4, C7, C10.

`RedisGia` ở đây **không phải** một stub ghi lại lời gọi như trong
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
    CURSOR_DAU,
    KHUNG_PING,
    CursorKhongHopLe,
    MessageSnapshot,
    StreamConsumer,
    doc_cursor,
    khung_sse,
)
from app.streaming.events import DeltaEvent, DoneEvent, ErrorCode
from app.streaming.producer import FIELD_DATA, FIELD_TYPE, encode_event

HEARTBEAT_S = 15


# ───────────────────────── Redis Stream giả, đúng ngữ nghĩa ─────────────────


def _khoa_id(raw: str) -> tuple[int, int]:
    """`"1725984000123-4"` → `(1725984000123, 4)`; `"7"` → `(7, 0)`."""
    if "-" in raw:
        ms, seq = raw.split("-", 1)
        return int(ms), int(seq)
    return int(raw), 0


def _can_duoi(start: str) -> tuple[int, int]:
    """Biên dưới của `XRANGE`. Dấu `(` đẩy nó lên đúng một nấc — đây là C3."""
    if start.startswith("("):
        ms, seq = _khoa_id(start[1:])
        return ms, seq + 1
    return _khoa_id(start)


class RedisGia:
    __slots__ = ("streams", "moc_sau_xrange_rong", "xread_da_goi_voi", "so_lan_xread")

    def __init__(self) -> None:
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        #: Hàm chạy NGAY SAU khi một `XRANGE` trả rỗng — dựng lại khoảnh khắc
        #: của C4. Xem docstring module.
        self.moc_sau_xrange_rong: Any = None
        self.xread_da_goi_voi: list[str] = []
        self.so_lan_xread = 0

    # ── công cụ của test, không phải API của Redis ──
    def them(self, key: str, loai: str, data: dict[str, Any]) -> str:
        ban_ghi = self.streams.setdefault(key, [])
        entry_id = f"172598400{len(ban_ghi):04d}-0"
        ban_ghi.append(
            (entry_id, {FIELD_TYPE: loai, FIELD_DATA: json.dumps(data, ensure_ascii=False)})
        )
        return entry_id

    def ids(self, key: str) -> list[str]:
        return [eid for eid, _ in self.streams.get(key, [])]

    # ── phần bắt chước Redis ──
    async def xrange(
        self, name: str, start: str, end: str, count: int | None = None
    ) -> list[tuple[str, dict[str, str]]]:
        assert end == "+", "consumer phai doc toi cuoi stream"
        lo = _can_duoi(start)
        ket_qua = [
            (eid, fields) for eid, fields in self.streams.get(name, []) if _khoa_id(eid) >= lo
        ]
        if count is not None:
            ket_qua = ket_qua[:count]
        if not ket_qua and self.moc_sau_xrange_rong is not None:
            moc, self.moc_sau_xrange_rong = self.moc_sau_xrange_rong, None
            moc()
        return ket_qua

    async def xread(
        self, streams: dict[str, str], block: int | None = None, count: int | None = None
    ) -> list[tuple[str, list[tuple[str, dict[str, str]]]]] | None:
        assert block == HEARTBEAT_S * 1000, "BLOCK phai bang STREAM_HEARTBEAT_S"
        self.so_lan_xread += 1
        ((name, moc),) = streams.items()
        self.xread_da_goi_voi.append(moc)
        ban_ghi = self.streams.get(name, [])
        # `$` giải ra ID lớn nhất TẠI THỜI ĐIỂM GỌI — đây là nửa còn lại của C4.
        lo = _khoa_id(ban_ghi[-1][0]) if (moc == "$" and ban_ghi) else _khoa_id(moc)
        moi = [(eid, f) for eid, f in ban_ghi if _khoa_id(eid) > lo]
        if count is not None:
            moi = moi[:count]
        return [(name, moi)] if moi else None

    async def xrevrange(
        self, name: str, max: str = "+", min: str = "-", count: int | None = None
    ) -> list[tuple[str, dict[str, str]]]:
        """B-84. Chỉ dựng đúng ca consumer cần: toàn stream, đảo ngược, cắt `count`."""
        assert (max, min) == ("+", "-"), "consumer chi hoi ban ghi CUOI cua ca stream"
        nguoc = list(reversed(self.streams.get(name, [])))
        return nguoc[:count] if count is not None else nguoc

    async def exists(self, name: str) -> int:
        return 1 if name in self.streams else 0

    def __getattr__(self, ten: str) -> Any:
        # C7: consumer group là lỗi thiết kế ở đây, không phải lựa chọn. Chạm
        # vào bất kỳ lệnh nào của group là đỏ ngay, kể cả khi test khác vẫn xanh.
        raise AssertionError(f"consumer khong duoc goi Redis.{ten} (C7: khong consumer group)")


# ──────────────────────────────── công cụ ──────────────────────────────────


def _snapshot(
    mid: uuid.UUID,
    *,
    status: MessageStatus = MessageStatus.STREAMING,
    content: str = "",
    model_id: str | None = "mx",
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
        finish_reason=finish_reason,
        error_code=error_code,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


def _consumer(redis: RedisGia, snapshot: MessageSnapshot) -> StreamConsumer:
    return StreamConsumer(redis, snapshot, heartbeat_s=HEARTBEAT_S)  # type: ignore[arg-type]


async def _thu(consumer: StreamConsumer, cursor: str, *, toi_da: int = 50) -> list[str]:
    """Đọc tối đa `toi_da` khung rồi dừng — stream chưa `done` thì chờ mãi."""
    khung: list[str] = []
    async for k in consumer.frames(cursor):
        khung.append(k)
        if len(khung) >= toi_da:
            break
    return khung


def _truong(khung: str, ten: str) -> list[str]:
    return [d[len(ten) + 2 :] for d in khung.split("\n") if d.startswith(f"{ten}: ")]


def _chuoi_chu(khung: list[str]) -> str:
    """Nối mọi `delta` — đúng việc mà `sse.ts` (T-1.14) sẽ làm."""
    ra = []
    for k in khung:
        if _truong(k, "event") == ["delta"]:
            ra.append(json.loads("\n".join(_truong(k, "data")))["t"])
    return "".join(ra)


def _stream_mau(redis: RedisGia, key: str, so_delta: int = 5, *, done: bool = True) -> None:
    redis.them(key, "start", {"message_id": "m", "model_id": "mx"})
    for i in range(so_delta):
        redis.them(key, "delta", {"t": f"chu{i}"})
    if done:
        redis.them(key, "done", {"finish_reason": "stop", "usage": None})


# ═══════════════════════════ cursor (§7.2 ②) ═══════════════════════════════


def test_mac_dinh_la_0_khi_khong_co_gi() -> None:
    assert doc_cursor(None, None) == CURSOR_DAU


def test_last_event_id_thang_query_cursor() -> None:
    """EventSource giữ nguyên URL cũ khi reconnect — để query thắng là phát lại từ đầu."""
    assert doc_cursor("1725984000123-0", "0") == "1725984000123-0"


def test_dung_query_cursor_khi_khong_co_header() -> None:
    assert doc_cursor(None, "1725984000123-4") == "1725984000123-4"


@pytest.mark.parametrize("rong", ["", "   "])
def test_header_rong_coi_nhu_vang_mat(rong: str) -> None:
    """Có proxy gửi `Last-Event-ID:` rỗng — 400 ở đây là chặn client đang quay lại."""
    assert doc_cursor(rong, "77-0") == "77-0"


@pytest.mark.parametrize("xau", ["abc", "$", "-", "1-2-3", "1725984000123-", "(77", "1e5"])
def test_cursor_sai_dang_thi_raise_chu_khong_lui_ve_0(xau: str) -> None:
    """Âm thầm lùi về 0 là phát lại từ đầu — đúng triệu chứng C3, mà không ai thấy."""
    with pytest.raises(CursorKhongHopLe):
        doc_cursor(xau, None)


def test_cursor_chi_co_mili_giay_van_hop_le() -> None:
    assert doc_cursor(None, "1725984000123") == "1725984000123"


# ═════════════════════════ khung SSE (§7.4, C10) ═══════════════════════════


def test_khung_du_ba_truong_va_dong_trong_ket_thuc() -> None:
    assert (
        khung_sse("delta", '{"t":"a"}', event_id="7-0")
        == 'id: 7-0\nevent: delta\ndata: {"t":"a"}\n\n'
    )


def test_khung_khong_co_id_thi_bo_han_dong_id() -> None:
    assert khung_sse("done", "{}") == "event: done\ndata: {}\n\n"


def test_data_nhieu_dong_thanh_nhieu_dong_data() -> None:
    """Lớp thứ hai của C10: một payload lọt vào stream mà không qua `encode_event`."""
    khung = khung_sse("delta", "a\nb\r\nc")
    assert _truong(khung, "data") == ["a", "b", "c"]
    assert khung.endswith("\n\n")


def test_xuong_dong_trong_ten_event_bi_lam_phang() -> None:
    """`event:` là trường MỘT dòng — một `\\n` ở đây cắt đôi mọi khung phía sau."""
    assert _truong(khung_sse("de\nlta", "{}"), "event") == ["de lta"]


# ═══════════════ ① XRANGE (cursor, +] — đuổi kịp, không lặp (C3) ═══════════


async def test_cursor_0_nhan_lai_tu_dau_du_so_ban_ghi() -> None:
    """DoD: chạy lại với `cursor=0` → nhận lại từ đầu, đủ số bản ghi bằng XLEN."""
    redis = RedisGia()
    mid = uuid.uuid4()
    consumer = _consumer(redis, _snapshot(mid))
    _stream_mau(redis, consumer.key)

    khung = await _thu(consumer, CURSOR_DAU)

    assert len(khung) == len(redis.ids(consumer.key)) == 7
    assert _chuoi_chu(khung) == "chu0chu1chu2chu3chu4"


async def test_xrange_loai_tru_cursor_khong_gui_lai_ban_ghi_da_nhan() -> None:
    """C3 — `[cursor` thay vì `(cursor` làm reconnect thấy một đoạn chữ LẶP."""
    redis = RedisGia()
    mid = uuid.uuid4()
    consumer = _consumer(redis, _snapshot(mid))
    _stream_mau(redis, consumer.key)
    ids = redis.ids(consumer.key)

    khung = await _thu(consumer, ids[2])  # đã nhận tới delta thứ hai

    assert _truong(khung[0], "id") == [ids[3]], "ban ghi tai cursor KHONG duoc gui lai"
    assert _chuoi_chu(khung) == "chu2chu3chu4"


async def test_noi_hai_nua_bang_dung_chuoi_goc_khong_thua_khong_thieu() -> None:
    """Phép đo của S3/T-1.11 thu nhỏ: ngắt ở giữa rồi nối `A + B`."""
    redis = RedisGia()
    mid = uuid.uuid4()
    day_du = _consumer(redis, _snapshot(mid))
    _stream_mau(redis, day_du.key, so_delta=9)
    ids = redis.ids(day_du.key)

    nua_a = await _thu(day_du, CURSOR_DAU, toi_da=5)
    id_cuoi = _truong(nua_a[-1], "id")[0]
    nua_b = await _thu(_consumer(redis, _snapshot(mid)), id_cuoi)

    assert _chuoi_chu(nua_a + nua_b) == "".join(f"chu{i}" for i in range(9))
    assert [i for k in nua_a + nua_b for i in _truong(k, "id")] == ids


# ═════════ ② XREAD BLOCK từ ID CUỐI CÙNG ĐÃ GỬI — không phải `$` (C4) ══════


async def test_xread_moi_bang_id_cuoi_cung_da_gui() -> None:
    redis = RedisGia()
    mid = uuid.uuid4()
    consumer = _consumer(redis, _snapshot(mid))
    _stream_mau(redis, consumer.key, done=False)
    ids = redis.ids(consumer.key)

    await _thu(consumer, CURSOR_DAU, toi_da=len(ids) + 1)

    assert redis.xread_da_goi_voi == [ids[-1]], "XREAD phai moi bang ID cuoi, khong phai `$`"


async def test_khong_mat_ban_ghi_sinh_ra_giua_xrange_va_xread() -> None:
    """C4 — cạm bẫy tinh vi nhất: chỉ sai khi có độ trễ giữa hai lệnh.

    `moc_sau_xrange_rong` ghi thêm chữ đúng vào khe đó. Với `XREAD` từ `$`,
    `$` giải ra ID của chính bản ghi vừa thêm nên nó bị bỏ qua vĩnh viễn.
    """
    redis = RedisGia()
    mid = uuid.uuid4()
    consumer = _consumer(redis, _snapshot(mid))
    _stream_mau(redis, consumer.key, so_delta=3, done=False)

    def sinh_tiep() -> None:
        redis.them(consumer.key, "delta", {"t": "-trong-khe"})
        redis.them(consumer.key, "done", {"finish_reason": "stop", "usage": None})

    redis.moc_sau_xrange_rong = sinh_tiep

    khung = await _thu(consumer, CURSOR_DAU)

    assert _chuoi_chu(khung) == "chu0chu1chu2-trong-khe"
    assert _truong(khung[-1], "event") == ["done"]


async def test_ping_khi_het_block_va_van_cho_tiep() -> None:
    """DoD: không có event mới trong 20 s → thấy `: ping`, kết nối chưa đứt."""
    redis = RedisGia()
    mid = uuid.uuid4()
    consumer = _consumer(redis, _snapshot(mid))
    _stream_mau(redis, consumer.key, so_delta=1, done=False)

    khung: list[str] = []
    async for k in consumer.frames(CURSOR_DAU):
        khung.append(k)
        if khung.count(KHUNG_PING) == 3:
            # Chữ tới SAU ba nhịp im lặng — đúng hình dạng của một model nghĩ lâu.
            redis.them(consumer.key, "done", {"finish_reason": "stop", "usage": None})

    assert khung.count(KHUNG_PING) == 3
    assert _truong(khung[-1], "event") == ["done"]
    assert KHUNG_PING.startswith(":"), "ping phai la COMMENT, khong phai event"


@pytest.mark.parametrize("loai_ket_thuc", ["done", "error"])
async def test_dung_ngay_sau_event_ket_thuc(loai_ket_thuc: str) -> None:
    """§7.4: chỉ `done` hoặc `error` mới đóng stream — và chúng đóng THẬT."""
    redis = RedisGia()
    mid = uuid.uuid4()
    consumer = _consumer(redis, _snapshot(mid))
    redis.them(consumer.key, "delta", {"t": "a"})
    redis.them(consumer.key, loai_ket_thuc, {"code": "UPSTREAM_ERROR"})
    redis.them(consumer.key, "delta", {"t": "khong-duoc-gui"})

    khung = await _thu(consumer, CURSOR_DAU)

    assert [_truong(k, "event")[0] for k in khung] == ["delta", loai_ket_thuc]
    assert redis.so_lan_xread == 0, "da co event ket thuc thi khong duoc BLOCK them"


# ═════════ ②bis — cursor đứng sau event kết thúc (B-84) ══════════


@pytest.mark.parametrize("loai_ket_thuc", ["done", "error"])
async def test_cursor_dung_sau_event_ket_thuc_thi_phat_lai_roi_dong(loai_ket_thuc: str) -> None:
    """B-84: client đã nhận `done` mà vẫn quay lại — **không được** treo.

    Không có khối ②bis thì `XRANGE (cursor +` rỗng, stream vẫn còn nên đường
    Postgres không nhận, và `XREAD BLOCK` chờ một bản ghi không bao giờ tới.
    """
    redis = RedisGia()
    mid = uuid.uuid4()
    consumer = _consumer(redis, _snapshot(mid, status=MessageStatus.COMPLETED, content="a"))
    redis.them(consumer.key, "delta", {"t": "a"})
    id_cuoi = redis.them(consumer.key, loai_ket_thuc, {"code": "UPSTREAM_ERROR"})

    khung = await _thu(consumer, id_cuoi)

    assert [_truong(k, "event")[0] for k in khung] == [loai_ket_thuc]
    assert _truong(khung[0], "id") == [id_cuoi], "phat lai dung ban ghi cu, khong bia ID"
    assert redis.so_lan_xread == 0, "khong duoc BLOCK cho mot ban ghi khong bao gio toi"


async def test_phat_lai_event_ket_thuc_khong_them_mot_ky_tu_nao() -> None:
    """C3 vẫn yên: thứ được phát lại là `done`, mà `done` không mang chữ."""
    redis = RedisGia()
    mid = uuid.uuid4()
    consumer = _consumer(redis, _snapshot(mid, status=MessageStatus.COMPLETED, content="chu0"))
    redis.them(consumer.key, "delta", {"t": "chu0"})
    id_done = redis.them(consumer.key, "done", {"finish_reason": "stop", "usage": None})

    assert _chuoi_chu(await _thu(consumer, id_done)) == ""


async def test_cursor_dung_sau_ban_ghi_cuoi_MA_CHUA_KET_THUC_thi_van_cho() -> None:
    """Nửa còn lại của B-84: bản ghi cuối là `delta` thì đóng là cắt giữa chừng.

    Đây là khe vài mili-giây mà B-84 cảnh báo: worker ghi Postgres TRƯỚC rồi
    `XADD done` SAU, nên `status` đã `completed` trong khi `done` chưa lên dây.
    ②bis hỏi `messages.status` thay vì hỏi chính stream thì test này đỏ.
    """
    redis = RedisGia()
    mid = uuid.uuid4()
    consumer = _consumer(redis, _snapshot(mid, status=MessageStatus.COMPLETED, content="a"))
    id_delta = redis.them(consumer.key, "delta", {"t": "a"})

    def worker_ghi_not() -> None:
        redis.them(consumer.key, "done", {"finish_reason": "stop", "usage": None})

    redis.moc_sau_xrange_rong = worker_ghi_not
    khung = await _thu(consumer, id_delta)

    assert [_truong(k, "event")[0] for k in khung] == ["done"]
    assert redis.so_lan_xread == 1, "phai di tiep sang XREAD chu khong duoc dong"


async def test_ban_ghi_moi_hon_cursor_khong_bi_nuot_boi_nhanh_phat_lai() -> None:
    """Khe C4 bên trong chính ②bis: worker kịp ghi `delta` RỒI `done`.

    `XREVRANGE COUNT 1` chỉ thấy `done`; phát nó rồi đóng là nuốt mất `delta` ở
    giữa. Bỏ phép so `_thu_tu_id(...) <= last_id` thì test này đỏ đúng chỗ đó.
    """
    redis = RedisGia()
    mid = uuid.uuid4()
    consumer = _consumer(redis, _snapshot(mid, status=MessageStatus.COMPLETED, content="ab"))
    id_delta = redis.them(consumer.key, "delta", {"t": "a"})

    def worker_ghi_not() -> None:
        redis.them(consumer.key, "delta", {"t": "b"})
        redis.them(consumer.key, "done", {"finish_reason": "stop", "usage": None})

    redis.moc_sau_xrange_rong = worker_ghi_not
    khung = await _thu(consumer, id_delta)

    assert _chuoi_chu(khung) == "b", "phan sinh ra trong khe KHONG duoc mat"
    assert [_truong(k, "event")[0] for k in khung] == ["delta", "done"]


async def test_cursor_chi_co_mili_giay_van_nhan_ra_da_qua_event_ket_thuc() -> None:
    """`?cursor=1725984000005` (không có `-seq`) vẫn phải bằng `1725984000005-0`.

    So hai ID bằng chuỗi thì `"...005-0" <= "...005"` là `False` và client treo
    đúng ca B-84 mô tả. `doc_cursor` cho phép dạng chỉ-mili-giây này (xem
    `test_cursor_chi_co_mili_giay_van_hop_le`) nên nó không phải ca giả định.
    """
    redis = RedisGia()
    mid = uuid.uuid4()
    consumer = _consumer(redis, _snapshot(mid, status=MessageStatus.COMPLETED, content=""))
    redis.streams[consumer.key] = [
        (
            "1725984000005-0",
            {FIELD_TYPE: "done", FIELD_DATA: json.dumps({"finish_reason": "stop"})},
        )
    ]

    khung = await _thu(consumer, "1725984000005")

    assert [_truong(k, "event")[0] for k in khung] == ["done"]
    assert redis.so_lan_xread == 0


# ════════════════════════ ③ hai client song song (C7) ══════════════════════


async def test_hai_client_cung_luc_deu_nhan_du_moi_event() -> None:
    """DoD: hai `curl -N` song song cùng một message → cả hai nhận đủ.

    `RedisGia.__getattr__` đã chặn mọi lệnh consumer group; test này kiểm nửa
    còn lại của C7 — đọc không làm bản ghi biến mất với người đọc kia.
    """
    redis = RedisGia()
    mid = uuid.uuid4()
    tab_a = _consumer(redis, _snapshot(mid))
    tab_b = _consumer(redis, _snapshot(mid))
    _stream_mau(redis, tab_a.key)

    khung_a = await _thu(tab_a, CURSOR_DAU)
    khung_b = await _thu(tab_b, CURSOR_DAU)

    assert _chuoi_chu(khung_a) == _chuoi_chu(khung_b) == "chu0chu1chu2chu3chu4"
    assert khung_a == khung_b


# ═══════════════════ mỗi event mang `id:` là Redis Stream ID ═══════════════


async def test_moi_event_mang_dung_id_cua_redis() -> None:
    redis = RedisGia()
    mid = uuid.uuid4()
    consumer = _consumer(redis, _snapshot(mid))
    _stream_mau(redis, consumer.key)

    khung = await _thu(consumer, CURSOR_DAU)

    assert [_truong(k, "id")[0] for k in khung] == redis.ids(consumer.key)


async def test_chep_nguyen_van_data_khong_parse_lai() -> None:
    """Parse rồi dumps lại có thể đổi thứ tự khoá — consumer không đụng payload."""
    redis = RedisGia()
    mid = uuid.uuid4()
    consumer = _consumer(redis, _snapshot(mid))
    tho = '{"z":1,"a":2}'
    redis.streams[consumer.key] = [("1-0", {FIELD_TYPE: "delta", FIELD_DATA: tho})]
    redis.them(consumer.key, "done", {"finish_reason": "stop", "usage": None})

    khung = await _thu(consumer, CURSOR_DAU)

    assert _truong(khung[0], "data") == [tho]


async def test_tieng_viet_va_emoji_di_qua_nguyen_ven() -> None:
    """C9/C10 — nối lại phải bằng chuỗi gốc, kể cả emoji và dấu xuống dòng."""
    redis = RedisGia()
    mid = uuid.uuid4()
    consumer = _consumer(redis, _snapshot(mid))
    chu = "Mùa thu 🍂\nlá rụng ☕"
    redis.them(consumer.key, "delta", {"t": chu})
    redis.them(consumer.key, "done", {"finish_reason": "stop", "usage": None})

    khung = await _thu(consumer, CURSOR_DAU)

    assert _chuoi_chu(khung) == chu
    assert len(_truong(khung[0], "data")) == 1, "json.dumps phai escape xuong dong (C10)"


async def test_ban_ghi_thieu_truong_bi_bo_qua_chu_khong_lam_hong_khung() -> None:
    redis = RedisGia()
    mid = uuid.uuid4()
    consumer = _consumer(redis, _snapshot(mid))
    redis.streams[consumer.key] = [("1-0", {FIELD_TYPE: "delta"})]
    redis.them(consumer.key, "done", {"finish_reason": "stop", "usage": None})

    khung = await _thu(consumer, CURSOR_DAU)

    assert [_truong(k, "event")[0] for k in khung] == ["done"]


# ══════════ stream hết TTL, message đã khép → dựng lại từ Postgres ═════════


async def test_stream_het_ttl_message_completed_tra_content_roi_done() -> None:
    """DoD: message `completed` từ 2 giờ trước → vẫn trả content đầy đủ + `done`."""
    redis = RedisGia()
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

    khung = await _thu(consumer, CURSOR_DAU)

    assert [_truong(k, "event")[0] for k in khung] == ["start", "delta", "done"]
    assert _chuoi_chu(khung) == "câu trả lời của hôm qua"
    cuoi = json.loads(_truong(khung[-1], "data")[0])
    assert cuoi == {"finish_reason": "stop", "usage": {"in": 297, "out": 298}}
    assert redis.so_lan_xread == 0, "khong duoc BLOCK khi da tra loi xong tu Postgres"


async def test_duong_postgres_khong_mang_id() -> None:
    """Không còn stream nào để trỏ tới — bịa một ID là phát ra cursor vô nghĩa."""
    redis = RedisGia()
    consumer = _consumer(
        redis, _snapshot(uuid.uuid4(), status=MessageStatus.COMPLETED, content="x")
    )

    khung = await _thu(consumer, CURSOR_DAU)

    assert all(_truong(k, "id") == [] for k in khung)


async def test_duong_postgres_dung_chung_encode_event_voi_producer() -> None:
    """Hai đường phải ra cùng một chuỗi `data:`, nếu không FE cần hai parser."""
    redis = RedisGia()
    consumer = _consumer(
        redis, _snapshot(uuid.uuid4(), status=MessageStatus.COMPLETED, content="xin chào")
    )

    khung = await _thu(consumer, CURSOR_DAU)

    assert _truong(khung[1], "data") == [encode_event(DeltaEvent(text="xin chào"))[1]]
    assert _truong(khung[2], "data") == [encode_event(DoneEvent(finish_reason=None, usage=None))[1]]


async def test_stream_het_ttl_message_failed_tra_error_co_ma() -> None:
    redis = RedisGia()
    consumer = _consumer(
        redis,
        _snapshot(
            uuid.uuid4(),
            status=MessageStatus.FAILED,
            content="phần đã sinh được",
            error_code=ErrorCode.UPSTREAM_ERROR.value,
        ),
    )

    khung = await _thu(consumer, CURSOR_DAU)

    assert [_truong(k, "event")[0] for k in khung] == ["start", "delta", "error"]
    # Phần chữ đã sinh vẫn tới người dùng: `finish_generation` giữ nó cho cả đường lỗi.
    assert _chuoi_chu(khung) == "phần đã sinh được"
    assert json.loads(_truong(khung[-1], "data")[0])["code"] == "UPSTREAM_ERROR"


@pytest.mark.parametrize("ma", [None, "MA_KHONG_CO_THAT"])
async def test_error_code_la_null_hoac_ma_la_thi_thanh_internal_error(ma: str | None) -> None:
    redis = RedisGia()
    consumer = _consumer(redis, _snapshot(uuid.uuid4(), status=MessageStatus.FAILED, error_code=ma))

    khung = await _thu(consumer, CURSOR_DAU)

    assert json.loads(_truong(khung[-1], "data")[0])["code"] == "INTERNAL_ERROR"


async def test_message_cancelled_di_duong_done_chu_khong_phai_error() -> None:
    """§7.5: huỷ vẫn là một lượt sinh khép lại bình thường, chỉ khác `finish_reason`."""
    redis = RedisGia()
    consumer = _consumer(
        redis,
        _snapshot(
            uuid.uuid4(),
            status=MessageStatus.CANCELLED,
            content="một nửa",
            finish_reason="cancelled",
        ),
    )

    khung = await _thu(consumer, CURSOR_DAU)

    assert _truong(khung[-1], "event") == ["done"]
    assert json.loads(_truong(khung[-1], "data")[0])["finish_reason"] == "cancelled"


async def test_khong_co_model_id_thi_bo_han_event_start() -> None:
    """Chết trước khi kịp chọn model thì không có gì để khai báo — `""` là sai."""
    redis = RedisGia()
    consumer = _consumer(redis, _snapshot(uuid.uuid4(), status=MessageStatus.FAILED, model_id=None))

    khung = await _thu(consumer, CURSOR_DAU)

    assert [_truong(k, "event")[0] for k in khung] == ["error"]


async def test_content_rong_thi_khong_co_delta_rong() -> None:
    redis = RedisGia()
    consumer = _consumer(redis, _snapshot(uuid.uuid4(), status=MessageStatus.COMPLETED, content=""))

    khung = await _thu(consumer, CURSOR_DAU)

    assert [_truong(k, "event")[0] for k in khung] == ["start", "done"]


@pytest.mark.parametrize("chua_xong", [MessageStatus.QUEUED, MessageStatus.STREAMING])
async def test_message_chua_khep_thi_KHONG_di_duong_postgres(chua_xong: MessageStatus) -> None:
    """`queued`/`streaming` nghĩa là chữ vẫn sẽ tới — trả câu rỗng lúc đó là nói dối."""
    redis = RedisGia()
    consumer = _consumer(redis, _snapshot(uuid.uuid4(), status=chua_xong, content=""))

    khung = await _thu(consumer, CURSOR_DAU, toi_da=2)

    assert khung == [KHUNG_PING, KHUNG_PING]


async def test_stream_con_song_thi_doc_redis_chu_khong_doc_postgres() -> None:
    """Redis là nguồn của phần đang bay; Postgres chỉ vào cuộc khi stream đã mất."""
    redis = RedisGia()
    mid = uuid.uuid4()
    consumer = _consumer(
        redis, _snapshot(mid, status=MessageStatus.COMPLETED, content="BAN-CUA-POSTGRES")
    )
    _stream_mau(redis, consumer.key, so_delta=2)

    khung = await _thu(consumer, CURSOR_DAU)

    assert _chuoi_chu(khung) == "chu0chu1"


# ═══════════════════════════ MessageSnapshot.usage ═════════════════════════


def test_usage_dung_khi_co_ca_hai_cot() -> None:
    usage = _snapshot(uuid.uuid4(), prompt_tokens=10, completion_tokens=4).usage()
    assert usage is not None
    assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (10, 4, 14)
    # NQ-23: hai cột này không có chỗ trong `messages`, nên chúng phải VẮNG MẶT.
    assert usage.reasoning_tokens is None
    assert usage.cached_prompt_tokens is None


@pytest.mark.parametrize(("vao", "ra"), [(None, 4), (10, None), (None, None)])
def test_thieu_mot_cot_thi_usage_la_None_chu_khong_phai_0(vao: int | None, ra: int | None) -> None:
    """Điền 0 vào chỗ vắng biến một lượt chat thành miễn phí trong sổ sách (C40)."""
    assert _snapshot(uuid.uuid4(), prompt_tokens=vao, completion_tokens=ra).usage() is None
