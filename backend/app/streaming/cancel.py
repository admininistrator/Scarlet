"""Cờ huỷ `cancel:{message_id}` — §7.5, hợp đồng giữa `api` và `worker`.

KH tham chiếu: §7.5, §7.2 ③, §7.4 · CLAUDE.md A1, A3 · tasks.md T-1.9.

§7.5 viết ra toàn bộ cơ chế trong ba dòng:

    POST /messages/{amid}/cancel → SET cancel:{amid} 1 EX 300
    worker: mỗi 8 chunk kiểm EXISTS cancel:{amid}
            → có: dừng vòng lặp, UPDATE finish_reason='cancelled',
                   VẪN ghi usage_events cho phần đã sinh, XADD type=done

Hai tiến trình khác nhau đứng hai đầu: `api` **ghi** cờ (`api/v1/messages.py`),
`worker` **đọc** cờ (`workers/generate.py`). Cả hai import file này chứ không
tự nối chuỗi `"cancel:" + str(mid)` — cùng lý lẽ đã ghi cho `stream_key()` ở
`producer.py`: một chỗ gõ sai tiền tố là một nút Dừng không bao giờ dừng được
cái gì, và nó **không báo lỗi**, nó chỉ im lặng.

**Vì sao cờ nằm ở Redis chứ không phải một cột trong Postgres.** Worker phải
hỏi "đã bấm Dừng chưa" nhiều lần trong một lượt sinh (mỗi
`KIEM_HUY_MOI_N_CHUNK` chunk, xem `generate.py`); với một câu trả lời dài của
`deepseek-flash` (~533 chunk đo ở T-1.3) đó là ~66 lần hỏi. Hỏi Postgres từng
ấy lần cho mỗi lượt chat là đúng thứ ADR-01 đã loại khi chọn Redis làm nơi giữ
dữ liệu **đang bay**. Cờ này cũng đúng nghĩa dữ liệu đang bay: nó chỉ có ý
nghĩa trong lúc còn một lượt sinh để dừng, và sự thật lâu dài — message đã bị
huỷ hay chưa — nằm ở `messages.status`/`messages.finish_reason` (C5).

**Vì sao cờ có TTL.** Không có `EX` thì mỗi lần bấm Dừng để lại một khoá sống
mãi, y hệt C8 của stream key. Tệ hơn stream: `maxmemory-policy volatile-lru`
chỉ đụng được khoá **có** TTL. `CANCEL_TTL_S` là một *giới hạn* nên nó sống ở
`Settings` chứ không phải một số trong file này (A3, §19.2 L4) — cùng họ với
`STREAM_TTL_S`.

**Vì sao `SET` chứ không `SETEX`/`SETNX`.** Bấm Dừng hai lần phải vô hại và
phải **gia hạn** đồng hồ: lần bấm thứ hai nghĩa là người dùng vẫn đang chờ nó
dừng. `SETNX` giữ nguyên TTL cũ của lần bấm trước, tức cái cờ có thể hết hạn
trong lúc người ta vừa bấm lại.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis.asyncio import Redis

#: Tiền tố khoá của §7.5. Xem docstring module về việc không ai được tự nối.
CANCEL_KEY_PREFIX = "cancel:"

#: Giá trị của khoá — §7.5 viết `SET cancel:{amid} 1`. Không ai đọc nội dung
#: này; câu hỏi duy nhất là `EXISTS`. Vẫn ghi đúng `1` của kế hoạch để
#: `redis-cli GET` lúc debug cho ra thứ người đọc kế hoạch đang chờ thấy.
GIA_TRI_CO = "1"

#: `messages.finish_reason` và khoá `finish_reason` của event `done` (§7.4) khi
#: lượt sinh dừng vì người dùng bấm Dừng. Nằm ở đây chứ không ở `events.py`:
#: ba giá trị kia (`stop`, `length`, `tool_calls`) đến từ provider và
#: `llm/parser.py` là module duy nhất nhìn thấy chúng, còn giá trị này là của
#: **mình** và chỉ đường huỷ sinh ra nó. FE phân nhánh theo đúng chuỗi này nên
#: nó là hằng có tên, không phải chữ gõ rời ở hai file (§19.2 L4).
FINISH_REASON_CANCELLED = "cancelled"


def cancel_key(message_id: uuid.UUID | str) -> str:
    return f"{CANCEL_KEY_PREFIX}{message_id}"


async def dat_co_huy(redis: Redis, message_id: uuid.UUID | str, *, ttl_s: int) -> None:
    """`SET cancel:{message_id} 1 EX ttl_s` — nửa GHI của §7.5, do `api` gọi.

    Không trả về gì vì không có câu trả lời nào đáng hỏi: `SET` luôn thành
    công, và "worker có kịp thấy cờ không" thì Redis không biết. Câu trả lời
    thật cho người dùng nằm ở `messages.status` sau đó.
    """
    await redis.set(cancel_key(message_id), GIA_TRI_CO, ex=ttl_s)


async def da_yeu_cau_huy(redis: Redis, message_id: uuid.UUID | str) -> bool:
    """`EXISTS cancel:{message_id}` — nửa ĐỌC của §7.5, do `worker` gọi.

    Trả `bool` chứ không trả số của Redis: chỗ gọi nó là một câu `if`, và một
    số nguyên lọt vào đó là chỗ để sau này ai đó so `== 1` với một API mà
    phiên bản sau có thể trả số khác.
    """
    return bool(await redis.exists(cancel_key(message_id)))
