"""Hàng đợi arq — phía **đẩy job vào** (§7.2 bước ①), dùng bởi tiến trình `api`.

KH tham chiếu: §7.2 ①, §5.2, ADR-02 · CLAUDE.md A1, A4 · tasks.md T-1.8.

A1 nói handler HTTP chỉ được "tạo record + enqueue job". File này là nửa
"enqueue job" của câu đó, và nó cố tình mỏng: một `RedisSettings`, một tên
job, một pool dựng lười.

**Vì sao `redis_settings()` và `GENERATE_JOB_NAME` chuyển từ
`app/workers/main.py` về đây.** Cả hai là **hợp đồng giữa hai tiến trình**,
không phải chi tiết của worker: `api` enqueue vào tên nào và Redis nào thì
`worker` phải đọc đúng tên ấy, đúng Redis ấy. Docstring gốc của chúng ở T-1.5
đã viết thẳng "cả worker lẫn bên enqueue (T-1.8) phải gọi hàm này" — nay bên
enqueue có thật, và cách rẻ nhất để hai bên không lệch là để hợp đồng ở chỗ cả
hai cùng import được. Đường còn lại — `api` import `app.workers.main` — kéo cả
`SystemAdapter` (tức SDK `openai`) và `generate` vào tiến trình `api`, đúng
thứ §5.3 và `scripts/check_hardcode.sh` lệnh 1 dựng ra để chặn.

`app/workers/main.py` vẫn import lại hai tên này nên bộ test của T-1.5 (đọc
chúng từ `app.workers.main`) không đổi một dòng.

**Pool dựng LƯỜI và có KHOÁ.** Lười vì cùng lý do với `db/session.py` và
`core/redis.py`: một pool tạo lúc import sẽ gắn vào event loop nào đang chạy
lúc đó, chưa chắc là loop của uvicorn. Khoá thì hai file kia không cần còn ở
đây thì cần — `create_pool` là hàm **async**, nên hai request đầu tiên tới
cùng lúc có thể cùng thấy `_pool is None`, cùng `await`, và một trong hai pool
sẽ không có ai đóng.

**Vì sao pool RIÊNG, không dùng lại `core/redis.py`.** `ArqRedis` không phải
một `Redis` có thêm phương thức: nó mang `job_serializer`/`job_deserializer`
và cách đặt khoá của arq. Và `core/redis.py` mở với `decode_responses=True`
cho consumer SSE ghép chuỗi, ngược hẳn với thứ arq cần (`bytes`, vì payload
job là pickle). Hai mục đích, hai kết nối — cùng lý lẽ đã ghi ở
`core/redis.py` cho cặp producer/consumer.
"""

from __future__ import annotations

import asyncio

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from arq.constants import default_queue_name

from app.config.settings import settings

#: Tên job trên dây — §7.2 bước ① viết `arq.enqueue('generate', ...)`.
#:
#: arq mặc định lấy `__qualname__` của hàm làm tên job, nghĩa là đổi tên hàm
#: Python cũng đổi tên job; bên enqueue khi đó đẩy vào một tên không ai đăng
#: ký và job nằm mãi trong hàng đợi — **không lỗi, không log**. Ghim tên vào
#: một hằng mà cả hai bên import làm chỗ đó đứt ngay lúc đọc code.
GENERATE_JOB_NAME = "generate"

_pool: ArqRedis | None = None
_khoa = asyncio.Lock()


def redis_settings() -> RedisSettings:
    """`REDIS_URL` của §19.1 đổi sang dạng arq hiểu.

    Cả worker lẫn bên enqueue phải gọi hàm này thay vì tự dựng
    `RedisSettings()`: mặc định của arq là `localhost:6379/0`, mà trong compose
    host là `redis` — sai lặng lẽ thành "job biến mất", không thành lỗi.
    """
    return RedisSettings.from_dsn(str(settings.REDIS_URL))


async def get_arq_pool() -> ArqRedis:
    """Pool dùng chung của tiến trình. Dựng ở lần gọi đầu tiên."""
    global _pool
    if _pool is None:
        async with _khoa:
            if _pool is None:
                _pool = await create_pool(redis_settings())
    return _pool


async def dispose_arq_pool() -> None:
    """Đóng pool. `main.py` gọi lúc shutdown; test gọi khi đổi pool."""
    global _pool
    if _pool is not None:
        await _pool.aclose()
    _pool = None


async def queue_depth() -> int:
    """Bao nhiêu job đang nằm trong hàng đợi — §21.2, §16.3 màn "Hệ thống".

    Chỉ số §21.2 gọi tên là *"độ dài hàng đợi arq"*, và nó trả lời đúng một câu:
    worker có theo kịp không.

    `ZCARD` chứ không `queued_jobs()`: hàm kia đọc **và giải mã** payload của
    từng job chỉ để rồi đếm chúng — tức unpickle cả hàng đợi mỗi lần admin mở
    một màn hình. Tên hàng đợi lấy từ chính `arq.constants`, không gõ lại chuỗi
    `"arq:queue"` ở đây (A3): bên đẩy job (`enqueue_job` trong
    `api/v1/messages.py`) cũng dùng mặc định ấy, nên hai bên chỉ đúng khi cùng
    đọc một hằng.

    Đếm cả job **hoãn** (`_defer_by`) vì chúng cùng nằm trong ZSET ấy — hôm nay
    không có chỗ nào hoãn job, và ngày có thì một job đã hứa vẫn là việc chưa
    làm xong.

    Người gọi phải tự lo ca Redis chết: hàm này để nguyên lỗi cho nổi lên, vì
    chỗ duy nhất biết "không đọc được thì hiển thị gì" là màn hình
    (`GET /admin/system` trả `null` và để `health` nói vì sao).
    """
    pool = await get_arq_pool()
    return await pool.zcard(default_queue_name)
