"""Ghi event vào Redis Stream `stream:{message_id}` (§7.2 ③, ADR-01, C8, C10).

KH tham chiếu: §7.2, §7.4, ADR-01, C5, C8, C10 · CLAUDE.md A1.

Đây là **nửa ghi** của cơ chế resume; nửa đọc là `consumer.py` (T-1.7). Cả hai
nói chuyện qua đúng ba thứ, và cả ba đều khai ở file này để không đầu nào tự
đoán: tên khoá (`stream_key`), hai tên trường của bản ghi (`FIELD_TYPE`,
`FIELD_DATA`), và cách serialize (`json.dumps`).

**Vì sao XADD chứ không Pub/Sub (ADR-01).** Pub/Sub không có lịch sử: client
đứt mạng 2 giây là mất hẳn 2 giây chữ, và không có cursor nào để xin lại.
Redis Stream cho mỗi bản ghi một ID tăng dần — chính là `Last-Event-ID` của
SSE. **Và KHÔNG dùng consumer group** (C7): group giao mỗi bản ghi cho **một**
consumer, nên mở hai tab thì một tab đói. Producer không cần biết điều đó,
nhưng nó là lý do file này không gọi `XGROUP CREATE` bao giờ.

**Vì sao payload luôn `json.dumps` (C10).** SSE dùng `\\n` làm dấu phân cách
trường, nên một câu trả lời có xuống dòng — tức gần như mọi câu trả lời — sẽ
cắt đôi khung `data:` nếu ghi chuỗi thô. `json.dumps` escape `\\n` thành `\\\\n`
và không có đường nào đi vòng qua: `emit()` là hàm DUY NHẤT ghi vào stream.

**Vì sao phải `EXPIRE` (C8).** Redis ở đây là bộ đệm, không phải nơi lưu trữ
(C5) — nguồn sự thật là `messages.content` trong Postgres. Quên `EXPIRE` thì
mỗi lượt chat để lại một khoá sống mãi, RAM Redis tăng đơn điệu trong vài
tuần, và không ai nghĩ tới nguyên nhân này. `maxmemory-policy volatile-lru`
trong compose chỉ cứu được các khoá **có TTL**, nên khoá quên TTL còn là khoá
mà chính sách đó không đụng tới được.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import TYPE_CHECKING

from app.streaming.events import Event

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

#: Tiền tố khoá của §7.2. Consumer (T-1.7) và reaper (T-1.10) dùng lại
#: `stream_key()` chứ không tự nối chuỗi — một chỗ gõ sai tiền tố là một
#: stream không ai đọc, và nó không báo lỗi, nó chỉ im lặng.
STREAM_KEY_PREFIX = "stream:"

#: Hai trường của mỗi bản ghi. `type` → `event:` của SSE, `data` → `data:`.
FIELD_TYPE = "type"
FIELD_DATA = "data"


#: Đoạn giữa của khoá stream tiêu đề: `stream:title:{conversation_id}`
#: (§24.2b·S6, S14 — T-S.7). Cùng tiền tố `stream:` nên cùng hưởng mọi thứ đã
#: dựng cho nó (C8, `maxmemory-policy volatile-lru`, phép đếm `--scan` của C8).
#: Tên chốt sau khi rà mọi chỗ quét `stream:*` (Cạm bẫy ② của T-S.7): con số
#: `streams_dang_chay` của `/admin/system` đếm `messages.status` trong
#: Postgres, reaper đi từ `message_id` — không chỗ nào suy `message_id` ngược
#: từ tên khoá, nên một khoá `stream:title:` không lọt vào con số nào.
TITLE_STREAM_SEGMENT = "title:"


def stream_key(message_id: uuid.UUID | str) -> str:
    return f"{STREAM_KEY_PREFIX}{message_id}"


def title_stream_key(conversation_id: uuid.UUID | str) -> str:
    """`stream:title:{conversation_id}` — stream riêng của lượt đặt tên (T-S.7)."""
    return stream_key(f"{TITLE_STREAM_SEGMENT}{conversation_id}")


def encode_event(event: Event) -> tuple[str, str]:
    """`Event` -> hai gia tri cua mot ban ghi stream: `(type, data)`.

    Tach khoi `emit()` vi T-1.7 co **mot** duong khong di qua Redis: khi stream
    da het TTL ma message da `completed`, consumer dung lai cau tra loi tu
    Postgres va phai phat ra dung hinh dang `data:` nhu luc no con tren day.
    Neu hai duong tu `json.dumps` lay thi chung lech nhau duoc — va lech o day
    nghia la cau tra loi doc sau mot gio khac cau tra loi doc ngay luc sinh.

    `ensure_ascii=False`: tieng Viet co dau va emoji di thang duoi dang UTF-8
    thay vi bi thoat thanh ma unicode. `json.loads` doc lai duoc ca hai dang,
    nhung dang nay ngan hon ~3 lan cho tieng Viet va doc duoc bang mat khi
    debug bang `redis-cli XRANGE`.
    """
    return event.TYPE, json.dumps(event.data(), ensure_ascii=False)


class StreamProducer:
    """Đầu ghi của MỘT message. Không dùng lại cho message khác.

    Nhận sẵn một `Redis` thay vì tự mở kết nối: worker đã có `ctx["redis"]` của
    arq (chính là `redis.asyncio.Redis`), và mở pool thứ hai cho mỗi lượt chat
    là vứt đi một pool mỗi lượt. Cùng lý do với `SystemAdapter` (§9.1).
    """

    __slots__ = ("_redis", "_key", "_ttl_s")

    def __init__(self, redis: Redis, message_id: uuid.UUID | str, *, ttl_s: int) -> None:
        self._redis = redis
        self._key = stream_key(message_id)
        self._ttl_s = ttl_s

    @classmethod
    def for_title(
        cls, redis: Redis, conversation_id: uuid.UUID | str, *, ttl_s: int
    ) -> StreamProducer:
        """Đầu ghi của `stream:title:{conversation_id}` — job `title` (T-S.7).

        Cùng lớp, cùng `emit`/`expire`: chỉ khác khoá. Khoá ra đúng
        `title_stream_key(conversation_id)` — cùng `TITLE_STREAM_SEGMENT`, cùng
        `stream_key` — nên consumer của `GET …/title/stream` đọc đúng khoá job
        ghi (`tests/streaming/test_producer.py` canh).
        """
        return cls(redis, f"{TITLE_STREAM_SEGMENT}{conversation_id}", ttl_s=ttl_s)

    @property
    def key(self) -> str:
        return self._key

    async def emit(self, event: Event) -> str:
        """`XADD` một event, trả về Redis Stream ID của bản ghi vừa ghi.

        ID trả về là thứ T-1.7 gửi làm `id:` của SSE, và là thứ client gửi lại
        trong `Last-Event-ID` khi reconnect — nên nó phải là ID **thật** Redis
        cấp, không phải một số đếm tự sinh.

        Hinh dang hai truong do `encode_event()` quyet dinh chu khong phai o
        day: consumer cua T-1.7 co mot duong dung lai event tu Postgres va
        phai ra dung chuoi ay.
        """
        kind, data = encode_event(event)
        raw = await self._redis.xadd(self._key, {FIELD_TYPE: kind, FIELD_DATA: data})
        return raw.decode() if isinstance(raw, bytes) else str(raw)

    async def expire(self) -> bool:
        """Đặt TTL cho stream — gọi NGAY sau event kết thúc (C8).

        Đặt TTL ở đây chứ không đặt lúc `XADD` đầu tiên: stream phải sống đủ
        lâu cho một lượt sinh dài (có thể hơn `STREAM_TTL_S` nếu model chậm),
        và đồng hồ chỉ nên bắt đầu chạy khi đã có gì đó hoàn chỉnh để đọc lại.
        """
        return bool(await self._redis.expire(self._key, self._ttl_s))
