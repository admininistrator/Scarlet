"""Đọc `stream:{message_id}` và phát ra khung SSE (§7.3, §7.4, C3, C4, C7, C10).

KH tham chiếu: §7.2 ②, §7.3, §7.4, C3, C4, C7, C10 · CLAUDE.md A1 · ADR-01.

Đây là **nửa đọc** của cơ chế resume; nửa ghi là `producer.py` (T-1.6). Hai
nửa nói chuyện qua đúng ba thứ, và cả ba đều khai ở `producer.py` chứ không
đầu nào tự đoán: `stream_key()`, `FIELD_TYPE`/`FIELD_DATA`, `encode_event()`.

Module này **không dựng lại payload**: với mỗi bản ghi Redis nó chép `type`
sang `event:` và chuỗi JSON sang `data:`, nguyên văn. Nhờ vậy thêm một trường
vào một event là sửa một dòng ở `events.py`, không phải hai chỗ ở hai task.

┌──────────────────────────────────────────────────────────────────────────┐
│  BỐN LUẬT, MỖI LUẬT LÀ MỘT CẠM BẪY ĐÃ CÓ TÊN                             │
└──────────────────────────────────────────────────────────────────────────┘

**1. `XRANGE` TRƯỚC, `XREAD` SAU — và `XREAD` từ ID CUỐI CÙNG ĐÃ GỬI (§7.3).**
Chỉ `XREAD BLOCK` từ `$` là C4: client reconnect mất trắng phần sinh ra trong
lúc đứt. Chỉ `XRANGE` rồi thôi thì mất phần sinh tiếp. Và ID mồi cho `XREAD`
phải là ID của bản ghi **thực sự đã gửi cho client**, không phải ID đọc được
lúc bắt đầu — chênh nhau đúng những bản ghi rơi vào giữa hai lệnh. Đây là lỗi
chỉ hiện ra khi có độ trễ giữa hai lệnh, tức chỉ trên máy thật dưới tải.

**2. `(cursor` — LOẠI TRỪ, không phải `[cursor` (C3).** `XRANGE key [id +` trả
lại **cả** bản ghi client vừa nhận, nên reconnect thấy một đoạn chữ lặp. Dấu
ngoặc đơn là toàn bộ khác biệt giữa "đúng" và "lặp một đoạn".

**3. KHÔNG consumer group (C7).** Group giao mỗi bản ghi cho **một** consumer:
mở hai tab thì một tab đói. Ở đây mỗi kết nối `XREAD` độc lập với cursor
riêng, và Redis Stream không xoá gì khi đọc — nên hai, năm hay mười client
cùng đọc một stream đều nhận đủ. Không có `XGROUP` ở bất cứ đâu trong file này.

**4. Im lặng KHÔNG phải kết thúc (§7.4).** Chỉ `done` hoặc `error` mới đóng
stream. Hết `BLOCK` mà chưa có gì thì gửi comment `: ping` rồi chờ tiếp — nó
giữ kết nối qua `proxy_read_timeout` (C2) và cho client biết đường dây còn
sống. Một stream im lặng 60 giây vì model đang nghĩ là chuyện bình thường.

**Đường thứ hai: dựng lại từ Postgres.** `STREAM_TTL_S` mặc định một giờ (C8),
nên mở lại một message của hôm qua thì stream đã biến mất. Khi đó — và **chỉ**
khi đó — consumer đọc `messages.content` rồi phát ra đúng những event tương
ứng. Redis là bộ đệm, Postgres là sự thật (C5), nên đây không phải đường lùi
tạm bợ mà là đường đúng cho một câu trả lời đã khép.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.db.models import Message, MessageStatus
from app.llm.client import Usage
from app.streaming.events import (
    DeltaEvent,
    DoneEvent,
    ErrorCode,
    ErrorEvent,
    Event,
    StartEvent,
)
from app.streaming.producer import FIELD_DATA, FIELD_TYPE, encode_event, stream_key

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

#: Cursor mặc định của §7.2 ②. `0` với `XRANGE (0 +` nghĩa là "từ đầu, tất cả":
#: Redis hiểu `0` là `0-0`, và dấu `(` đẩy nó thành `0-1` — không bản ghi thật
#: nào có ID nhỏ hơn thế.
CURSOR_DAU = "0"

#: Redis Stream ID: `<ms>` hoặc `<ms>-<seq>`. Cursor tới từ người dùng (header
#: `Last-Event-ID` hoặc `?cursor=`) nên nó phải được KIỂM trước khi ghép vào
#: `(...`: một chuỗi lạ làm Redis trả lỗi giữa chừng, tức là một `500` xảy ra
#: sau khi header `200 text/event-stream` đã ra dây — lỗi mà client không đọc
#: nổi, vì với nó kết nối đã thành công rồi.
_DANG_CURSOR = re.compile(r"\A\d{1,20}(-\d{1,20})?\Z")

#: SSE tách trường bằng CRLF, CR hoặc LF (WHATWG). Xem `khung_sse`.
_XUONG_DONG = re.compile(r"\r\n|\r|\n")

#: Hai loại event đóng stream (§7.4). FE **không được** suy ra "đã xong" từ
#: việc stream im lặng, nên đây là danh sách đầy đủ và duy nhất.
LOAI_KET_THUC = frozenset({"done", "error"})

#: Trạng thái message mà lượt sinh đã khép — điều kiện để đi đường Postgres.
#: `queued`/`streaming` KHÔNG nằm ở đây: chúng nghĩa là "vẫn còn chữ sẽ tới",
#: và trả về một câu trả lời rỗng lúc đó là nói dối.
TRANG_THAI_KET_THUC = frozenset(
    {MessageStatus.COMPLETED, MessageStatus.FAILED, MessageStatus.CANCELLED}
)

#: Số bản ghi lấy mỗi lệnh. Một lượt sinh dài đo được ở T-1.6 là ~4300 bản ghi,
#: nên lấy từng cái một là ~4300 vòng round-trip chỉ để đuổi kịp một client vừa
#: reconnect. Cũng không lấy tất cả trong một lệnh: bộ nhớ của tiến trình `api`
#: sẽ tăng theo độ dài câu trả lời nhân số client.
SO_BAN_GHI_MOI_LAN = 500

#: Comment SSE. Dòng mở đầu bằng dấu hai chấm bị client bỏ qua — nó không phải
#: event, nên nó không đụng tới `Last-Event-ID` và FE không phải xử lý gì.
KHUNG_PING = ": ping\n\n"

#: `X-Accel-Buffering: no` là lớp thứ hai của C1: kể cả khi ai đó lỡ tay xoá
#: `proxy_buffering off` khỏi `config/nginx/nginx.conf`, header này vẫn bảo
#: Nginx đừng gom. Hai lớp, vì mất streaming là loại lỗi im lặng.
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


class CursorKhongHopLe(ValueError):
    """`Last-Event-ID` hoặc `?cursor=` không phải một Redis Stream ID."""

    def __init__(self, gia_tri: str) -> None:
        super().__init__(f"cursor khong phai Redis Stream ID: {gia_tri!r}")
        self.gia_tri = gia_tri


def doc_cursor(last_event_id: str | None, cursor: str | None) -> str:
    """§7.2 ②: `Last-Event-ID`, rồi `?cursor=`, mặc định `0`.

    Header đi TRƯỚC query có chủ ý: `EventSource` của trình duyệt tự gửi lại
    `Last-Event-ID` khi reconnect (§7.4) nhưng vẫn giữ nguyên URL nó được tạo
    ra cùng — nếu URL đó có `?cursor=0` thì để query thắng là biến mọi lần
    reconnect thành phát lại từ đầu.

    Chuỗi rỗng coi như vắng mặt: có proxy gửi `Last-Event-ID:` rỗng thay vì bỏ
    hẳn header, và trả `400` cho nó là chặn đúng những client đang cố quay lại.

    Raise:
        CursorKhongHopLe: có giá trị nhưng sai dạng. **Không** âm thầm lùi về
            `0` — phát lại từ đầu khi client xin phần giữa chính là triệu chứng
            của C3, và im lặng thì không ai lần ra nguyên nhân.
    """
    for nguon in (last_event_id, cursor):
        if nguon is None:
            continue
        gia_tri = nguon.strip()
        if not gia_tri:
            continue
        if not _DANG_CURSOR.match(gia_tri):
            raise CursorKhongHopLe(gia_tri)
        return gia_tri
    return CURSOR_DAU


def _mot_dong(gia_tri: str) -> str:
    """Bỏ mọi ký tự xuống dòng khỏi một trường SSE một-dòng (`id:`, `event:`)."""
    return _XUONG_DONG.sub(" ", gia_tri)


def khung_sse(loai: str, data: str, *, event_id: str | None = None) -> str:
    """Một khung SSE hoàn chỉnh, kể cả dòng trống kết thúc.

    `data` được tách theo ký tự xuống dòng thành **nhiều** dòng `data:` đúng
    như WHATWG quy định, thay vì nhét cả cục vào một dòng. `json.dumps` của
    producer đã escape ký tự xuống dòng rồi (C10) nên đường chạy thật luôn ra
    đúng một dòng; phép tách này là lớp thứ hai, cho trường hợp một bản ghi lọt
    vào stream mà không qua `encode_event()` — khi đó khung vẫn hợp lệ thay vì
    cắt đôi và làm hỏng mọi event phía sau nó.

    `event_id` là Redis Stream ID và là thứ trình duyệt gửi lại trong
    `Last-Event-ID` (§7.4). `None` dành cho những event **không có chỗ trên
    stream** — xem `StreamConsumer._tu_postgres`.
    """
    dong: list[str] = []
    if event_id is not None:
        dong.append(f"id: {_mot_dong(event_id)}")
    dong.append(f"event: {_mot_dong(loai)}")
    dong.extend(f"data: {phan}" for phan in _XUONG_DONG.split(data))
    return "\n".join(dong) + "\n\n"


def _ma_loi(raw: str | None) -> ErrorCode:
    """`messages.error_code` (TEXT) → `ErrorCode`. Mã lạ hoặc NULL → `INTERNAL_ERROR`.

    `NULL` cùng đường với "mã lạ" chứ không phải một ca riêng: một message
    `failed` mà không có `error_code` là một nhánh thoát chưa ai đặt tên, đúng
    nghĩa của `INTERNAL_ERROR` trong `events.py`.
    """
    if raw is None:
        return ErrorCode.INTERNAL_ERROR
    try:
        return ErrorCode(raw)
    except ValueError:
        return ErrorCode.INTERNAL_ERROR


@dataclass(frozen=True, slots=True)
class MessageSnapshot:
    """Những gì consumer cần từ Postgres, đọc MỘT LẦN trước khi stream mở.

    Cố ý **không** giữ `Message` của ORM: một lượt sinh kéo mười phút, và một
    object còn gắn với session nghĩa là một kết nối Postgres nằm không suốt
    thời gian đó — cách nhanh nhất làm cạn pool khi vài người cùng chat. Cùng
    lý lẽ với `_chuan_bi` trong `workers/generate.py`.
    """

    message_id: uuid.UUID
    status: MessageStatus
    content: str
    model_id: str | None
    finish_reason: str | None
    error_code: str | None
    prompt_tokens: int | None
    completion_tokens: int | None

    @classmethod
    def from_message(cls, message: Message) -> MessageSnapshot:
        return cls(
            message_id=message.id,
            status=message.status,
            content=message.content,
            model_id=message.model_id,
            finish_reason=message.finish_reason,
            error_code=message.error_code,
            prompt_tokens=message.prompt_tokens,
            completion_tokens=message.completion_tokens,
        )

    def usage(self) -> Usage | None:
        """`Usage` dựng lại từ hai cột, hoặc `None` khi không đủ số.

        Thiếu một trong hai cột thì trả `None` chứ **không** điền `0`: NQ-23 và
        C40 dựa vào chỗ khác nhau giữa "provider không báo" và "báo và bằng 0",
        và điền 0 vào chỗ vắng biến một lượt chat thành miễn phí trong sổ sách.

        `reasoning_tokens` và `cached_prompt_tokens` luôn `None` ở đây vì
        `messages` không có cột cho chúng (Phụ lục A) — chúng chỉ sống trên dây
        lúc sinh, và T-2.12 mới là task ghi chúng xuống `usage_events`.
        """
        if self.prompt_tokens is None or self.completion_tokens is None:
            return None
        return Usage(
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            total_tokens=self.prompt_tokens + self.completion_tokens,
        )


class StreamConsumer:
    """Đầu đọc của MỘT kết nối SSE tới MỘT message.

    Một instance cho mỗi kết nối, không dùng lại: cursor là trạng thái của
    riêng client đó, và C7 sống hay chết ở đúng chỗ này.
    """

    __slots__ = ("_redis", "_key", "_block_ms", "_snapshot")

    def __init__(self, redis: Redis, snapshot: MessageSnapshot, *, heartbeat_s: int) -> None:
        self._redis = redis
        self._key = stream_key(snapshot.message_id)
        self._block_ms = heartbeat_s * 1000
        self._snapshot = snapshot

    @property
    def key(self) -> str:
        return self._key

    async def frames(self, cursor: str) -> AsyncIterator[str]:
        """Khung SSE, từ `cursor` (loại trừ) tới hết — xem bốn luật ở đầu file."""
        last_id = cursor
        co_ban_ghi = False

        # ① Đuổi kịp: XRANGE (cursor, +]. Dấu mở ngoặc đơn là C3.
        while True:
            ban_ghi = await self._redis.xrange(
                self._key, f"({last_id}", "+", count=SO_BAN_GHI_MOI_LAN
            )
            if not ban_ghi:
                break
            co_ban_ghi = True
            for entry_id, fields in ban_ghi:
                khung = self._khung_ban_ghi(entry_id, fields)
                if khung is not None:
                    yield khung
                # Cursor tiến CẢ KHI bản ghi bị bỏ qua: một bản ghi hỏng không
                # đọc được thì cũng không gửi lại được, và giữ nguyên cursor ở
                # đó là một vòng lặp vô hạn.
                last_id = entry_id
                if fields.get(FIELD_TYPE) in LOAI_KET_THUC:
                    return

        # ② Stream đã hết TTL nhưng lượt sinh đã khép → dựng lại từ Postgres.
        #    Kiểm SAU bước ① chứ không trước: nếu stream còn sống thì ① đã đọc
        #    hết nó rồi, và `EXISTS` ở đây trả lời đúng câu "có thật sự không
        #    còn gì trên Redis không", chứ không phải một phỏng đoán từ trước.
        #    Thứ tự ba điều kiện là thứ tự giá tiền: hai phép so trong RAM đứng
        #    trước vòng round-trip tới Redis, nên một message đang `streaming`
        #    không tốn thêm lệnh nào cho nhánh này.
        if (
            not co_ban_ghi
            and self._snapshot.status in TRANG_THAI_KET_THUC
            and not await self._redis.exists(self._key)
        ):
            for khung in self._tu_postgres():
                yield khung
            return

        # ③ XREAD BLOCK từ ID CUỐI CÙNG ĐÃ GỬI — không phải `$` (C4).
        while True:
            goi = await self._redis.xread(
                {self._key: last_id}, block=self._block_ms, count=SO_BAN_GHI_MOI_LAN
            )
            if not goi:
                # Hết BLOCK mà chưa có gì: im lặng là ĐANG CHỜ, không phải xong.
                yield KHUNG_PING
                continue
            for _, ban_ghi in goi:
                for entry_id, fields in ban_ghi:
                    khung = self._khung_ban_ghi(entry_id, fields)
                    if khung is not None:
                        yield khung
                    last_id = entry_id
                    if fields.get(FIELD_TYPE) in LOAI_KET_THUC:
                        return

    def _khung_ban_ghi(self, entry_id: str, fields: dict[str, str]) -> str | None:
        """Một bản ghi Redis → một khung SSE. `None` khi bản ghi không đọc được.

        Chép thẳng `type` và `data`, **không** parse lại JSON: parse rồi dumps
        lại có thể đổi thứ tự khoá, và consumer không có việc gì phải hiểu nội
        dung payload (xem docstring `events.py`).
        """
        loai = fields.get(FIELD_TYPE)
        data = fields.get(FIELD_DATA)
        if loai is None or data is None:
            logger.warning(
                "consumer: %s bo qua ban ghi %s thieu truong %s/%s",
                self._key,
                entry_id,
                FIELD_TYPE,
                FIELD_DATA,
            )
            return None
        return khung_sse(loai, data, event_id=entry_id)

    def _tu_postgres(self) -> Iterator[str]:
        """Dựng lại câu trả lời đã khép từ `messages`, khi stream đã hết TTL.

        Phát đúng hình dạng event của §7.4 qua `encode_event()` — cùng hàm mà
        producer dùng — nên FE chỉ có MỘT bộ phân tích, không phải hai.

        **Không event nào ở đây mang `id:`**, và đó là chủ ý: `id:` là Redis
        Stream ID, mà ở đây không còn stream nào để trỏ tới. Bịa một ID nghĩa
        là phát cho client một cursor mà lần reconnect sau không ai hiểu. Theo
        đúng SSE, event không có `id:` thì `Last-Event-ID` của client giữ
        nguyên giá trị cũ — và vì đường này luôn phát **toàn bộ** câu trả lời,
        không có gì để nối tiếp.

        `start` đi trước không phải để cho đủ bộ: nó báo FE "đây là một câu trả
        lời bắt đầu từ đầu", nên một client reconnect với cursor ở giữa cũng
        hiển thị đúng thay vì nối chồng lên phần nó đã có. Vắng `model_id` thì
        bỏ hẳn event này — một message chết trước khi kịp chọn model không có
        gì để khai báo, và chuỗi rỗng sẽ là một `model_id` sai.
        """
        snap = self._snapshot
        logger.info(
            "consumer: %s khong con tren Redis, dung lai tu Postgres (status=%s, %d ky tu)",
            self._key,
            snap.status.value,
            len(snap.content),
        )
        if snap.model_id is not None:
            yield self._khung_su_kien(
                StartEvent(message_id=str(snap.message_id), model_id=snap.model_id)
            )
        if snap.content:
            yield self._khung_su_kien(DeltaEvent(text=snap.content))
        if snap.status is MessageStatus.FAILED:
            # Phần chữ đã sinh được vẫn gửi ở trên: `finish_generation` giữ nó
            # lại cho cả đường lỗi, và người dùng đã nhìn thấy nó trên màn hình.
            yield self._khung_su_kien(ErrorEvent(code=_ma_loi(snap.error_code)))
        else:
            yield self._khung_su_kien(
                DoneEvent(finish_reason=snap.finish_reason, usage=snap.usage())
            )

    @staticmethod
    def _khung_su_kien(event: Event) -> str:
        loai, data = encode_event(event)
        return khung_sse(loai, data)
