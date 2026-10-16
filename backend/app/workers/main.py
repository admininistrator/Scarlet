"""Điểm vào của tiến trình worker: `arq app.workers.main.WorkerSettings`.

KH tham chiếu: ADR-02, §5.2, §7.2, §7.6, Phụ lục C · CLAUDE.md A1, A3, A4.

Module này chỉ làm bốn việc: khai nơi tìm Redis, khai danh sách job, khai lịch
cron (§7.6), và khai hai cái móc `on_startup`/`on_shutdown`. Không có logic
nghiệp vụ nào ở đây — mỗi job sống trong file riêng của nó (§23).

**Ba tham số của `generate` đều có lý do, không cái nào là mặc định của arq:**

1. `name=GENERATE_JOB_NAME` — §7.2 bước ① viết `arq.enqueue('generate', ...)`,
   tức tên job là một *giao kèo* giữa `api` và `worker`. arq mặc định lấy
   `__qualname__`, nghĩa là đổi tên hàm Python cũng đổi tên job, và bên gọi
   sẽ enqueue vào một tên không ai đăng ký: job nằm mãi trong hàng đợi, không
   lỗi, không log. Hằng này — cùng với `redis_settings()` — **chuyển sang
   `app/core/queue.py` ở T-1.8**: chúng là hợp đồng giữa hai tiến trình, nên
   phải nằm ở chỗ cả `api` lẫn `worker` import được. Đường ngược lại (`api`
   import chính file này) sẽ kéo `SystemAdapter` và cả SDK `openai` vào tiến
   trình `api` — đúng thứ §5.3 chặn.
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
dòng `logger.info` của worker rơi vào hư không. `setup_logging()`
(`app/core/log_setup.py` — dùng chung với `api` và `cli` từ T-9.5a) chạy sau
`dictConfig` của arq nên không bị ghi đè.

**Vì sao `LLMClient` sống trong `ctx`, không phải biến toàn cục (T-1.6).**
`AsyncOpenAI` mang theo một connection pool **gắn với event loop**, nên một
instance ở tầng module sẽ được tạo trước khi arq dựng loop của nó. Dựng ở
`on_startup` và đóng ở `on_shutdown` cho pool đúng một vòng đời bằng vòng đời
tiến trình — xem docstring `adapters/system.py`. Cùng lý do với engine Postgres
(`app/db/session.py` dựng lười, `dispose_engine()` gọi ở `on_shutdown`).
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from arq import cron, func
from arq.cron import CronJob
from arq.typing import WorkerCoroutine
from arq.worker import Function

from app.config.settings import settings
from app.core.log_setup import log_context, setup_logging
from app.core.queue import EXTRACT_JOB_NAME, GENERATE_JOB_NAME, TITLE_JOB_NAME, redis_settings
from app.db.session import dispose_engine
from app.llm.adapters.system import SystemAdapter
from app.workers.extract import extract
from app.workers.generate import CTX_LLM_CLIENT, generate
from app.workers.reaper import REAPER_JOB_NAME, REAPER_SECONDS_IN_MINUTE, reaper
from app.workers.spend_alert import (
    SPEND_ALERT_JOB_NAME,
    SPEND_ALERT_MINUTES_IN_HOUR,
    spend_alert,
)
from app.workers.title import generate_title

logger = logging.getLogger(__name__)

#: KHÔNG thử lại. Xem điểm 2 ở docstring module và docstring `generate.py`.
GENERATE_MAX_TRIES = 1

#: Job đặt tên hội thoại (T-S.7) cũng KHÔNG thử lại — §24.2b·S6: "Không thử lại
#: vô hạn". Hỏng một lần là tiêu đề ở lại `NULL` và sidebar hiện "Hội thoại chưa
#: đặt tên"; thử lại là trả tiền lần hai cho thứ người dùng tự gõ được.
TITLE_MAX_TRIES = 1


def with_request_id(job: Callable[..., Awaitable[Any]]) -> WorkerCoroutine:
    """Đặt lại ngữ cảnh log từ tham số `request_id` ở đầu mỗi job (§21.1, T-9.5b).

    contextvar không đi qua Redis: `api` gửi id làm tham số job
    (`enqueue_job(…, request_id=…)`), job chạy ở tiến trình khác phải tự đặt lại.
    Dict MỚI mỗi job — không để id của job trước sót lại.
    """

    @functools.wraps(job)
    async def run(ctx: dict[Any, Any], *args: Any, **kwargs: Any) -> Any:
        request_id = kwargs.pop("request_id", None)
        log_context.set({"request_id": request_id} if request_id else {})
        return await job(ctx, *args, **kwargs)

    return run


FUNCTIONS: list[Function] = [
    func(
        with_request_id(generate),
        name=GENERATE_JOB_NAME,
        timeout=settings.GENERATE_TIMEOUT_S,
        max_tries=GENERATE_MAX_TRIES,
    ),
    # Cùng trần thời gian với `generate` và cùng lý do (điểm 3 docstring
    # module): timeout HTTP của `SystemAdapter` phải nổ trước arq để `_close`
    # còn ghi được event kết thúc.
    func(
        with_request_id(generate_title),
        name=TITLE_JOB_NAME,
        timeout=settings.GENERATE_TIMEOUT_S,
        max_tries=TITLE_MAX_TRIES,
    ),
    # T-4.6a — trích chữ PDF/DOCX. KHÔNG `max_tries=1` (Cạm bẫy ⑤): luật "không
    # thử lại" của hai job trên sinh ra vì tiền, job này không gọi model. Job
    # tự nuốt lỗi của byte người dùng, nên arq chỉ thử lại khi worker chết giữa chừng.
    func(with_request_id(extract), name=EXTRACT_JOB_NAME),
]

#: §7.6 — lưới cuối cho ca "worker chết giữa lúc sinh" (tiêu chí S4).
#:
#: `run_at_startup=False`: ngưỡng là `heartbeat_at` chứ không phải "worker vừa
#: bật", nên chạy ngay lúc khởi động không dọn sớm được một dòng nào — nó chỉ
#: thêm một lượt quét vào đúng lúc tiến trình đang bận dựng pool.
#:
#: `unique=True` (mặc định) giữ nguyên: nó là thứ khiến hai worker không cùng
#: quét một tick. Hôm nay chỉ có một replica, nhưng đây là loại giả định rẻ
#: khi giữ và đắt khi phát hiện ra đã mất.
#:
#: `spend_alert` (T-2.17, RR-1) chạy **hằng giờ**, tức `minute={0}` — arq mặc
#: định `second=0` nên nó nổ đúng một lần ở phút 0 của mỗi giờ. Cũng
#: `run_at_startup=False`: ngưỡng là chi tiêu tích luỹ của cả ngày, không phải
#: một sự kiện lúc khởi động, và một lần `docker compose up -d` lúc 23 giờ
#: không nên tiêu mất lá thư duy nhất của ngày hôm đó.
CRON_JOBS: list[CronJob] = [
    cron(reaper, name=REAPER_JOB_NAME, second=set(REAPER_SECONDS_IN_MINUTE), run_at_startup=False),
    cron(
        spend_alert,
        name=SPEND_ALERT_JOB_NAME,
        minute=set(SPEND_ALERT_MINUTES_IN_HOUR),
        run_at_startup=False,
    ),
]


async def on_startup(ctx: dict[str, Any]) -> None:
    """`PING` Redis, dựng `LLMClient` dùng chung, rồi in log DoD của T-1.5."""
    setup_logging()
    await ctx["redis"].ping()
    ctx[CTX_LLM_CLIENT] = SystemAdapter.from_settings()
    conn = redis_settings()
    # KHÔNG in `REDIS_URL` nguyên văn: DSN có chỗ chứa mật khẩu (§15 DoD chung
    # — "không log secret"). Host/port/db là đủ để biết mình nối vào đâu.
    logger.info(
        "worker: da noi Redis %s:%s/%s · job dang ky: %s · cron: %s",
        conn.host,
        conn.port,
        conn.database,
        # `None` = mặc định của arq (job `extract`, T-4.6a) — in chữ, không "Nones".
        ", ".join(
            f"{f.name}(timeout={f'{f.timeout_s}s' if f.timeout_s else 'mac-dinh-arq'}, "
            f"max_tries={f.max_tries or 'mac-dinh-arq'})"
            for f in FUNCTIONS
        ),
        # In cả `minute` lẫn `second`: từ T-2.17 có hai cron với hai độ phân
        # giải khác nhau (`reaper` ghim giây, `spend_alert` ghim phút), nên một
        # dòng chỉ in `second=` sẽ nói `spend_alert(second={0})` — đọc ra là
        # "mỗi phút một lần", sai đúng 60 lần.
        ", ".join(
            f"{c.name}(minute={c.minute}, second={c.second}, max_tries={c.max_tries})"
            for c in CRON_JOBS
        ),
    )


async def on_shutdown(ctx: dict[str, Any]) -> None:
    """Đóng hai pool worker tự mở: HTTP tới LiteLLM và kết nối Postgres.

    Không đóng thì tiến trình vẫn thoát, nhưng asyncio in một loạt cảnh báo
    "Unclosed client session" che mất dòng log cuối cùng — đúng lúc người ta
    đang đọc log để hiểu vì sao worker dừng.
    """
    client = ctx.pop(CTX_LLM_CLIENT, None)
    if client is not None:
        await client.close()
    await dispose_engine()
    logger.info("worker: dung, khong nhan job moi")


class WorkerSettings:
    """Đối tượng mà lệnh `arq` đọc (Phụ lục C: `arq app.workers.main.WorkerSettings`)."""

    functions = FUNCTIONS
    cron_jobs = CRON_JOBS
    redis_settings = redis_settings()
    on_startup = on_startup
    on_shutdown = on_shutdown

    #: Nhịp worker ghi khoá `arq:queue:health-check` vào Redis, cũng là thứ
    #: `arq --check` (healthcheck của container) đọc. Mặc định của arq là
    #: **3600 s**: worker chết lúc 00:01 thì tới 01:00 `docker compose ps` vẫn
    #: báo `healthy`; khoá có TTL = nhịp + 1 s nên mất khoá nghĩa là vòng lặp
    #: chính của worker đã đứng.
    #:
    #: **Biến riêng `WORKER_HEALTHCHECK_S`, KHÔNG dùng lại `WORKER_HEARTBEAT_S`
    #: nữa (B-74 → NQ-27).** T-1.5 dùng chung một biến vì cả hai trả lời "bao
    #: lâu thì worker phải chứng minh nó còn sống"; T-1.10 làm câu đó tách đôi:
    #: `WORKER_HEARTBEAT_S` nay là một vế của tỉ lệ `REAPER_STALE_S /
    #: WORKER_HEARTBEAT_S` (số nhịp được phép lỡ trước khi reaper §7.6 đánh
    #: `WORKER_LOST`), nên vặn nó sẽ đồng thời đổi ba thứ ở ba tầng.
    health_check_interval = settings.WORKER_HEALTHCHECK_S

    #: Nhịp hỏi Redis "có job mới không". Mặc định của arq là 0.5 s và T-1.12
    #: đo được đúng con số đó nằm trong TTFT của mọi model (B-104): chặng
    #: `202` → `start` có trần bằng đúng `poll_delay` ở cả bốn model. Xem
    #: `Settings.ARQ_POLL_DELAY_S` cho phần còn lại của lý lẽ, gồm cả vì sao
    #: hạ xuống dưới 0.5 s không phá lịch cron của reaper.
    poll_delay = settings.ARQ_POLL_DELAY_S
