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

**Hai loại stream, một consumer (T-S.7).** `stream:{message_id}` của lượt sinh
và `stream:title:{conversation_id}` của lượt đặt tên hội thoại (§24.2b·S6) đi
qua **đúng** các bước dưới đây — §24.2b·S6 đòi dùng lại consumer §7.3, không
viết bản thứ hai. Chỗ duy nhất hai loại khác nhau là đường thứ hai (dựng lại
từ Postgres): consumer nhận một `ReplaySource` — `MessageSnapshot` hoặc
`TitleSnapshot` — biết tên khoá, biết "đã khép chưa", và biết phát lại những
event nào.

**Đường thứ ba: cursor đứng sau event kết thúc (B-84).** Một client đã nhận
`done` mà vẫn quay lại — trái §7.4, nhưng có thật — không được treo. Consumer hỏi
`XREVRANGE COUNT 1` xem bản ghi cuối của stream có phải event kết thúc không, rồi
**phát lại đúng event đó** và đóng. Hỏi chính stream chứ không hỏi
`messages.status` là có chủ ý — xem khối ②bis trong `frames()`.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from app.db.models import Message, MessageStatus
from app.llm.client import Usage
from app.streaming.events import (
    DeltaEvent,
    DoneEvent,
    ErrorCode,
    ErrorEvent,
    Event,
    StartEvent,
    TitleDoneEvent,
)
from app.streaming.producer import (
    FIELD_DATA,
    FIELD_TYPE,
    encode_event,
    stream_key,
    title_stream_key,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

#: Cursor mặc định của §7.2 ②. `0` với `XRANGE (0 +` nghĩa là "từ đầu, tất cả":
#: Redis hiểu `0` là `0-0`, và dấu `(` đẩy nó thành `0-1` — không bản ghi thật
#: nào có ID nhỏ hơn thế.
CURSOR_START = "0"

#: Redis Stream ID: `<ms>` hoặc `<ms>-<seq>`. Cursor tới từ người dùng (header
#: `Last-Event-ID` hoặc `?cursor=`) nên nó phải được KIỂM trước khi ghép vào
#: `(...`: một chuỗi lạ làm Redis trả lỗi giữa chừng, tức là một `500` xảy ra
#: sau khi header `200 text/event-stream` đã ra dây — lỗi mà client không đọc
#: nổi, vì với nó kết nối đã thành công rồi.
_CURSOR_FORMAT = re.compile(r"\A\d{1,20}(-\d{1,20})?\Z")

#: SSE tách trường bằng CRLF, CR hoặc LF (WHATWG). Xem `sse_frame`.
_NEWLINE = re.compile(r"\r\n|\r|\n")

#: Hai loại event đóng stream (§7.4). FE **không được** suy ra "đã xong" từ
#: việc stream im lặng, nên đây là danh sách đầy đủ và duy nhất.
TERMINAL_EVENTS = frozenset({"done", "error"})

#: Trạng thái message mà lượt sinh đã khép — điều kiện để đi đường Postgres.
#: `queued`/`streaming` KHÔNG nằm ở đây: chúng nghĩa là "vẫn còn chữ sẽ tới",
#: và trả về một câu trả lời rỗng lúc đó là nói dối.
TERMINAL_STATUSES = frozenset(
    {MessageStatus.COMPLETED, MessageStatus.FAILED, MessageStatus.CANCELLED}
)

#: Số bản ghi lấy mỗi lệnh. Một lượt sinh dài đo được ở T-1.6 là ~4300 bản ghi,
#: nên lấy từng cái một là ~4300 vòng round-trip chỉ để đuổi kịp một client vừa
#: reconnect. Cũng không lấy tất cả trong một lệnh: bộ nhớ của tiến trình `api`
#: sẽ tăng theo độ dài câu trả lời nhân số client.
ENTRIES_PER_READ = 500

#: Comment SSE. Dòng mở đầu bằng dấu hai chấm bị client bỏ qua — nó không phải
#: event, nên nó không đụng tới `Last-Event-ID` và FE không phải xử lý gì.
PING_FRAME = ": ping\n\n"

#: `X-Accel-Buffering: no` là lớp thứ hai của C1: kể cả khi ai đó lỡ tay xoá
#: `proxy_buffering off` khỏi `config/nginx/nginx.conf`, header này vẫn bảo
#: Nginx đừng gom. Hai lớp, vì mất streaming là loại lỗi im lặng.
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


class InvalidCursor(ValueError):
    """`Last-Event-ID` hoặc `?cursor=` không phải một Redis Stream ID."""

    def __init__(self, value: str) -> None:
        super().__init__(f"cursor khong phai Redis Stream ID: {value!r}")
        self.value = value


def parse_cursor(last_event_id: str | None, cursor: str | None) -> str:
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
    for source in (last_event_id, cursor):
        if source is None:
            continue
        value = source.strip()
        if not value:
            continue
        if not _CURSOR_FORMAT.match(value):
            raise InvalidCursor(value)
        return value
    return CURSOR_START


def _id_order(raw: str) -> tuple[int, int]:
    """`"1725984000123-4"` → `(1725984000123, 4)`; `"7"` → `(7, 0)`.

    Redis Stream ID so sánh theo **số**, không theo chuỗi: `"100-0" < "99-0"`
    đúng với `str` và sai với Redis. Phần `-seq` vắng mặt được Redis hiểu là
    `-0`, và `parse_cursor` cho phép cursor chỉ có mili-giây — nên hai dạng phải
    quy về cùng một khóa trước khi so.
    """
    ms, _, seq = raw.partition("-")
    return int(ms), int(seq or 0)


def _single_line(value: str) -> str:
    """Bỏ mọi ký tự xuống dòng khỏi một trường SSE một-dòng (`id:`, `event:`)."""
    return _NEWLINE.sub(" ", value)


def sse_frame(kind: str, data: str, *, event_id: str | None = None) -> str:
    """Một khung SSE hoàn chỉnh, kể cả dòng trống kết thúc.

    `data` được tách theo ký tự xuống dòng thành **nhiều** dòng `data:` đúng
    như WHATWG quy định, thay vì nhét cả cục vào một dòng. `json.dumps` của
    producer đã escape ký tự xuống dòng rồi (C10) nên đường chạy thật luôn ra
    đúng một dòng; phép tách này là lớp thứ hai, cho trường hợp một bản ghi lọt
    vào stream mà không qua `encode_event()` — khi đó khung vẫn hợp lệ thay vì
    cắt đôi và làm hỏng mọi event phía sau nó.

    `event_id` là Redis Stream ID và là thứ trình duyệt gửi lại trong
    `Last-Event-ID` (§7.4). `None` dành cho những event **không có chỗ trên
    stream** — xem `StreamConsumer._from_postgres`.
    """
    lines: list[str] = []
    if event_id is not None:
        lines.append(f"id: {_single_line(event_id)}")
    lines.append(f"event: {_single_line(kind)}")
    lines.extend(f"data: {part}" for part in _NEWLINE.split(data))
    return "\n".join(lines) + "\n\n"


def _error_code(raw: str | None) -> ErrorCode:
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


class ReplaySource(Protocol):
    """Những gì consumer cần từ Postgres cho MỘT stream, đọc một lần trước khi mở.

    Ba câu hỏi, đúng ba chỗ consumer phải hỏi Postgres thay vì Redis:

    * `stream_key` — đọc khoá nào;
    * `closed` — stream vắng mặt có nghĩa là "đã khép, dựng lại được" (đường
      thứ hai), hay "chưa có gì, chờ tiếp" (bước ③);
    * `replay()` — những event nào phát lại khi đi đường thứ hai.
    """

    @property
    def stream_key(self) -> str: ...

    @property
    def closed(self) -> bool: ...

    def replay(self) -> Iterator[Event]: ...


@dataclass(frozen=True, slots=True)
class MessageSnapshot:
    """Những gì consumer cần từ Postgres, đọc MỘT LẦN trước khi stream mở.

    Cố ý **không** giữ `Message` của ORM: một lượt sinh kéo mười phút, và một
    object còn gắn với session nghĩa là một kết nối Postgres nằm không suốt
    thời gian đó — cách nhanh nhất làm cạn pool khi vài người cùng chat. Cùng
    lý lẽ với `_prepare` trong `workers/generate.py`.
    """

    message_id: uuid.UUID
    status: MessageStatus
    content: str
    model_id: str | None
    reasoning_effort: str | None
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
            reasoning_effort=message.reasoning_effort,
            finish_reason=message.finish_reason,
            error_code=message.error_code,
            prompt_tokens=message.prompt_tokens,
            completion_tokens=message.completion_tokens,
        )

    @property
    def stream_key(self) -> str:
        return stream_key(self.message_id)

    @property
    def closed(self) -> bool:
        """Lượt sinh đã khép — `queued`/`streaming` nghĩa là còn chữ sẽ tới."""
        return self.status in TERMINAL_STATUSES

    def replay(self) -> Iterator[Event]:
        """Câu trả lời đã khép, dựng lại từ `messages` — xem `StreamConsumer._from_postgres`.

        `start` đi trước không phải để cho đủ bộ: nó báo FE "đây là một câu trả
        lời bắt đầu từ đầu", nên một client reconnect với cursor ở giữa cũng
        hiển thị đúng thay vì nối chồng lên phần nó đã có. Vắng `model_id` thì
        bỏ hẳn event này — một message chết trước khi kịp chọn model không có
        gì để khai báo, và chuỗi rỗng sẽ là một `model_id` sai.
        """
        if self.model_id is not None:
            yield StartEvent(
                message_id=str(self.message_id),
                model_id=self.model_id,
                # Cùng hình dạng `start` của đường Redis (T-S.6): mở lại sau một
                # giờ vẫn phải ra đúng chip "model · mức".
                reasoning_effort=self.reasoning_effort,
            )
        if self.content:
            yield DeltaEvent(text=self.content)
        if self.status is MessageStatus.FAILED:
            # Phần chữ đã sinh được vẫn gửi ở trên: `finish_generation` giữ nó
            # lại cho cả đường lỗi, và người dùng đã nhìn thấy nó trên màn hình.
            yield ErrorEvent(code=_error_code(self.error_code))
        else:
            yield DoneEvent(finish_reason=self.finish_reason, usage=self.usage())

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


@dataclass(frozen=True, slots=True)
class TitleSnapshot:
    """Nguồn dựng lại của `stream:title:{conversation_id}` (§24.2b·S6, T-S.7).

    Hai thứ đọc lúc mở kết nối: `conversations.title` (đã lọc `user_id` trong
    câu SQL ở route) và job `title` còn đang chờ/chạy hay không
    (`core/queue.py::title_job_pending` — route chỉ hỏi khi `title` còn `NULL`).

    Không có `start`/`delta` để phát lại: stream tiêu đề đã hết TTL thì thứ
    duy nhất còn đáng nói là tiêu đề cuối, và đó là đúng một event `done`.
    """

    conversation_id: uuid.UUID
    title: str | None
    job_pending: bool

    @property
    def stream_key(self) -> str:
        return title_stream_key(self.conversation_id)

    @property
    def closed(self) -> bool:
        """Không còn lượt đặt tên nào sẽ ghi vào stream này.

        `title` có giá trị ⇒ khép, bất kể job: nếu job còn chạy thì stream của
        nó đã tồn tại và bước ① đọc nó trước (đường thứ hai chỉ chạy khi khoá
        vắng mặt); nếu job chưa kịp `XADD start` mà người dùng đã đặt tên thì
        job cũng sẽ kết thúc bằng đúng tên ấy. `title` còn `NULL` ⇒ khép chỉ khi
        hàng đợi không còn job nào — ngược lại là job chưa kịp bắt đầu, chờ.
        """
        return self.title is not None or not self.job_pending

    def replay(self) -> Iterator[Event]:
        if self.title is not None:
            yield TitleDoneEvent(title=self.title)
            return
        # Không tiêu đề, không stream, không job: lượt đặt tên đã hỏng và đã
        # quá `STREAM_TTL_S`, hoặc chưa từng được đẩy vào hàng đợi. `JOB_LOST`
        # — "không có lượt nào đang chạy, chưa một chữ nào" — và FE hiện "Hội
        # thoại chưa đặt tên" như mọi ca `error` của §24.2b·S6.
        yield ErrorEvent(code=ErrorCode.JOB_LOST, message="khong co luot dat ten nao dang chay")


class StreamConsumer:
    """Đầu đọc của MỘT kết nối SSE tới MỘT stream (message hoặc tiêu đề).

    Một instance cho mỗi kết nối, không dùng lại: cursor là trạng thái của
    riêng client đó, và C7 sống hay chết ở đúng chỗ này.
    """

    __slots__ = ("_redis", "_key", "_block_ms", "_snapshot")

    def __init__(self, redis: Redis, snapshot: ReplaySource, *, heartbeat_s: int) -> None:
        self._redis = redis
        self._key = snapshot.stream_key
        self._block_ms = heartbeat_s * 1000
        self._snapshot = snapshot

    @property
    def key(self) -> str:
        return self._key

    async def frames(self, cursor: str) -> AsyncIterator[str]:
        """Khung SSE, từ `cursor` (loại trừ) tới hết — xem bốn luật ở đầu file."""
        last_id = cursor
        has_entries = False

        # ① Đuổi kịp: XRANGE (cursor, +]. Dấu mở ngoặc đơn là C3.
        while True:
            entries = await self._redis.xrange(
                self._key, f"({last_id}", "+", count=ENTRIES_PER_READ
            )
            if not entries:
                break
            has_entries = True
            for entry_id, fields in entries:
                frame = self._entry_frame(entry_id, fields)
                if frame is not None:
                    yield frame
                # Cursor tiến CẢ KHI bản ghi bị bỏ qua: một bản ghi hỏng không
                # đọc được thì cũng không gửi lại được, và giữ nguyên cursor ở
                # đó là một vòng lặp vô hạn.
                last_id = entry_id
                if fields.get(FIELD_TYPE) in TERMINAL_EVENTS:
                    return

        # ② Stream đã hết TTL nhưng lượt sinh đã khép → dựng lại từ Postgres.
        #    Kiểm SAU bước ① chứ không trước: nếu stream còn sống thì ① đã đọc
        #    hết nó rồi, và `EXISTS` ở đây trả lời đúng câu "có thật sự không
        #    còn gì trên Redis không", chứ không phải một phỏng đoán từ trước.
        #    Thứ tự ba điều kiện là thứ tự giá tiền: hai phép so trong RAM đứng
        #    trước vòng round-trip tới Redis, nên một message đang `streaming`
        #    không tốn thêm lệnh nào cho nhánh này.
        if not has_entries and self._snapshot.closed and not await self._redis.exists(self._key):
            for frame in self._from_postgres():
                yield frame
            return

        # ②bis (B-84) — CURSOR ĐỨNG SAU EVENT KẾT THÚC: phát lại event đó rồi đóng.
        #      Xảy ra khi một client đã nhận `done`/`error` mà vẫn quay lại với
        #      `Last-Event-ID` của chính nó. §7.4 dặn FE đóng `EventSource` khi
        #      thấy `done`, nhưng một client cũ hay một script viết vội thì không.
        #      Không có nhánh này thì `XRANGE` rỗng, stream vẫn còn (chưa hết TTL)
        #      nên ② không nhận, và ③ chờ một bản ghi KHÔNG BAO GIỜ tới — client
        #      treo tới lúc tự bỏ đi.
        #
        #      Phép kiểm là `XREVRANGE COUNT 1`, **không** phải `messages.status`:
        #      worker ghi Postgres TRƯỚC rồi `XADD done` SAU (luật 2 của
        #      `generate.py`), nên có một khe vài mili-giây mà message đã
        #      `completed` còn `done` chưa lên dây — đóng trong khe đó là cắt client
        #      ngay trước event cuối. Bản ghi cuối của chính stream thì không có
        #      khe nào: nó đã ở đó hoặc chưa.
        #
        #      **Phát LẠI chứ không đóng suông.** Đóng một `text/event-stream` mà
        #      không gửi gì là mời `EventSource` reconnect sau ~3 s, và nó quay lại
        #      với đúng cursor cũ: treo đổi thành vòng lặp nóng, tệ hơn. Một event
        #      kết thúc phát lại là thứ DUY NHẤT làm một client tuân §7.4 dừng
        #      hẳn, và nó không mang chữ nên không có gì để lặp (C3 yên).
        #
        #      Chỉ chạy khi ① không đọc được bản ghi nào: có đọc được nghĩa là
        #      bản ghi cuối nằm SAU cursor và không phải event kết thúc (nếu phải
        #      thì ① đã `return`), nên một vòng round-trip ở đây chắc chắn vô ích.
        #
        #      **`_thu_tu_id(...) <= last_id` là bắt buộc, không phải thận trọng
        #      thừa.** Giữa lúc `XRANGE` trả rỗng và lúc `XREVRANGE` chạy có đúng
        #      cái khe của C4: worker kịp ghi `delta` RỒI `done`. `XREVRANGE COUNT 1`
        #      chỉ thấy `done`, và phát nó rồi đóng là **nuốt mất `delta` ở giữa** —
        #      đúng loại mất chữ mà cả §7.3 dựng ra để chống. Bản ghi cuối mới hơn
        #      cursor nghĩa là có thứ client chưa thấy ⇒ không đi đường này, để ③
        #      đọc từ `last_id` và lấy đủ cả hai bản ghi.
        if not has_entries:
            last = await self._redis.xrevrange(self._key, "+", "-", count=1)
            if (
                last
                and last[0][1].get(FIELD_TYPE) in TERMINAL_EVENTS
                and _id_order(last[0][0]) <= _id_order(last_id)
            ):
                entry_id, fields = last[0]
                logger.info(
                    "consumer: %s cursor dung sau event %s — phat lai roi dong (B-84)",
                    self._key,
                    fields.get(FIELD_TYPE),
                )
                frame = self._entry_frame(entry_id, fields)
                if frame is not None:
                    yield frame
                return

        # ③ XREAD BLOCK từ ID CUỐI CÙNG ĐÃ GỬI — không phải `$` (C4).
        while True:
            batch = await self._redis.xread(
                {self._key: last_id}, block=self._block_ms, count=ENTRIES_PER_READ
            )
            if not batch:
                # Hết BLOCK mà chưa có gì: im lặng là ĐANG CHỜ, không phải xong.
                yield PING_FRAME
                continue
            for _, entries in batch:
                for entry_id, fields in entries:
                    frame = self._entry_frame(entry_id, fields)
                    if frame is not None:
                        yield frame
                    last_id = entry_id
                    if fields.get(FIELD_TYPE) in TERMINAL_EVENTS:
                        return

    def _entry_frame(self, entry_id: str, fields: dict[str, str]) -> str | None:
        """Một bản ghi Redis → một khung SSE. `None` khi bản ghi không đọc được.

        Chép thẳng `type` và `data`, **không** parse lại JSON: parse rồi dumps
        lại có thể đổi thứ tự khoá, và consumer không có việc gì phải hiểu nội
        dung payload (xem docstring `events.py`).
        """
        kind = fields.get(FIELD_TYPE)
        data = fields.get(FIELD_DATA)
        if kind is None or data is None:
            logger.warning(
                "consumer: %s bo qua ban ghi %s thieu truong %s/%s",
                self._key,
                entry_id,
                FIELD_TYPE,
                FIELD_DATA,
            )
            return None
        return sse_frame(kind, data, event_id=entry_id)

    def _from_postgres(self) -> Iterator[str]:
        """Dựng lại một stream đã khép từ Postgres, khi khoá đã hết TTL.

        Những event nào thì `ReplaySource.replay()` quyết (`MessageSnapshot` —
        câu trả lời; `TitleSnapshot` — tiêu đề); ở đây chỉ đóng khung. Phát đúng
        hình dạng event của §7.4 qua `encode_event()` — cùng hàm mà producer
        dùng — nên FE chỉ có MỘT bộ phân tích, không phải hai.

        **Không event nào ở đây mang `id:`**, và đó là chủ ý: `id:` là Redis
        Stream ID, mà ở đây không còn stream nào để trỏ tới. Bịa một ID nghĩa
        là phát cho client một cursor mà lần reconnect sau không ai hiểu. Theo
        đúng SSE, event không có `id:` thì `Last-Event-ID` của client giữ
        nguyên giá trị cũ — và vì đường này luôn phát **toàn bộ** phần còn đáng
        nói, không có gì để nối tiếp.

        Log chỉ còn tên khoá (T-S.7): trạng thái và độ dài của bản cũ là trường
        riêng của `MessageSnapshot`, và tên khoá đã nói stream nào — `stream:`
        hay `stream:title:` — đang được dựng lại.
        """
        logger.info("consumer: %s khong con tren Redis, dung lai tu Postgres", self._key)
        for event in self._snapshot.replay():
            yield self._event_frame(event)

    @staticmethod
    def _event_frame(event: Event) -> str:
        kind, data = encode_event(event)
        return sse_frame(kind, data)
