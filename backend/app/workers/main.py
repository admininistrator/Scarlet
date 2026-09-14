"""Điểm vào của tiến trình worker: `arq app.workers.main.WorkerSettings`.

KH tham chiếu: ADR-02, §5.2, §7.2, §7.6, Phụ lục C · CLAUDE.md A1, A3, A4.

Module này chỉ làm ba việc: khai nơi tìm Redis, khai danh sách job, và khai
hai cái móc `on_startup`/`on_shutdown`. Không có logic nghiệp vụ nào ở đây —
mỗi job sống trong file riêng của nó (§23).

**Ba tham số của `generate` đều có lý do, không cái nào là mặc định của arq:**

1. `name="generate"` — §7.2 bước ① viết `arq.enqueue('generate', ...)`, tức
   tên job là một *giao kèo* giữa `api` và `worker`. arq mặc định lấy
   `__qualname__`, nghĩa là đổi tên hàm Python cũng đổi tên job, và bên gọi
   sẽ enqueue vào một tên không ai đăng ký: job nằm mãi trong hàng đợi, không
   lỗi, không log. Ghim tên ra đây làm chỗ đó đứt ngay lúc đọc code.
2. `max_tries=GENERATE_MAX_TRIES` — xem docstring `generate.py`. Mặc định của
   arq là 5; với lượt sinh, thử lại lần hai là hoá đơn lần hai.
3. `timeout=GENERATE_TIMEOUT_S` — mặc định của arq là 300 s, ngắn hơn cả
   `LLM_REQUEST_TIMEOUT_S` (600 s) mà `SystemAdapter` đặt cho chặng backend →
   LiteLLM. Để nguyên thì arq huỷ job trong lúc model vẫn đang sinh: tiền vẫn
   mất, mà worker mất luôn quyền ghi `status`/`usage`/`XADD done` vì nó bị
   `CancelledError` ném vào giữa chừng. Thứ tự đúng là timeout của tầng HTTP
   nổ **trước**, để worker còn tự dọn được; timeout của arq chỉ là lưới cuối.

**Vì sao `on_startup` tự dựng logging.** `arq` CLI gọi `dictConfig` cho riêng
logger tên `arq`; logger `app.*` của chúng ta không có handler nào nên mọi
dòng `logger.info` của worker rơi vào hư không. Tiến trình `api` không gặp
chuyện này vì uvicorn dựng sẵn logging. Đây là chỗ duy nhất trong backend gọi
`addHandler`, và nó chạy sau `dictConfig` của arq nên không bị ghi đè.
"""

from __future__ import annotations

import logging
from typing import Any

from arq import func
from arq.connections import RedisSettings
from arq.worker import Function

from app.config.settings import settings
from app.workers.generate import generate

logger = logging.getLogger(__name__)

#: Tên job trên dây — giao kèo với §7.2 bước ①. Xem điểm 1 ở docstring module.
GENERATE_JOB_NAME = "generate"

#: KHÔNG thử lại. Xem điểm 2 ở docstring module và docstring `generate.py`.
GENERATE_MAX_TRIES = 1

FUNCTIONS: list[Function] = [
    func(
        generate,
        name=GENERATE_JOB_NAME,
        timeout=settings.GENERATE_TIMEOUT_S,
        max_tries=GENERATE_MAX_TRIES,
    ),
]


def redis_settings() -> RedisSettings:
    """`REDIS_URL` của §19.1 đổi sang dạng arq hiểu.

    Cả worker lẫn bên enqueue (T-1.8) phải gọi hàm này thay vì tự dựng
    `RedisSettings()`: mặc định của arq là `localhost:6379/0`, và trong compose
    thì host là `redis` — sai lặng lẽ thành "job biến mất" chứ không thành lỗi.
    """
    return RedisSettings.from_dsn(str(settings.REDIS_URL))


def _dung_logging() -> None:
    """Gắn handler cho cây logger `app.*`. Xem docstring module."""
    app_logger = logging.getLogger("app")
    if app_logger.handlers:
        return
    handler = logging.StreamHandler()
    # Cùng `datefmt` với formatter của arq để hai nguồn log đọc chung được.
    handler.setFormatter(logging.Formatter("%(asctime)s: %(message)s", datefmt="%H:%M:%S"))
    app_logger.addHandler(handler)
    app_logger.setLevel(settings.LOG_LEVEL)
    app_logger.propagate = False


async def on_startup(ctx: dict[str, Any]) -> None:
    """`PING` Redis rồi in đúng hai thứ DoD của T-1.5 đòi thấy trong log."""
    _dung_logging()
    await ctx["redis"].ping()
    conn = redis_settings()
    # KHÔNG in `REDIS_URL` nguyên văn: DSN có chỗ chứa mật khẩu (§15 DoD chung
    # — "không log secret"). Host/port/db là đủ để biết mình nối vào đâu.
    logger.info(
        "worker: da noi Redis %s:%s/%s · job dang ky: %s",
        conn.host,
        conn.port,
        conn.database,
        ", ".join(f"{f.name}(timeout={f.timeout_s}s, max_tries={f.max_tries})" for f in FUNCTIONS),
    )


async def on_shutdown(ctx: dict[str, Any]) -> None:
    logger.info("worker: dung, khong nhan job moi")


class WorkerSettings:
    """Đối tượng mà lệnh `arq` đọc (Phụ lục C: `arq app.workers.main.WorkerSettings`)."""

    functions = FUNCTIONS
    redis_settings = redis_settings()
    on_startup = on_startup
    on_shutdown = on_shutdown

    #: Nhịp worker ghi khoá `arq:queue:health-check` vào Redis, cũng là thứ
    #: `arq --check` (healthcheck của container) đọc. Mặc định của arq là
    #: **3600 s**: worker chết lúc 00:01 thì tới 01:00 `docker compose ps` vẫn
    #: báo `healthy`. Dùng lại `WORKER_HEARTBEAT_S` của §7.6 vì đó đã là câu
    #: trả lời của kế hoạch cho "bao lâu thì worker phải chứng minh nó còn
    #: sống"; khoá có TTL = nhịp + 1 s nên mất khoá nghĩa là vòng lặp chính của
    #: worker đã đứng.
    health_check_interval = settings.WORKER_HEARTBEAT_S
