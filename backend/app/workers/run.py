"""Điểm vào của tiến trình worker: `python -m app.workers.run` — B-196.

KH tham chiếu: ADR-02, §5.2, §7.2, Phụ lục C · CLAUDE.md A1, A3, A4 ·
tasks.md B-196, rà P2 2026-09-20.

╔══════════════════════════════════════════════════════════════════════════╗
║  VÌ SAO KHÔNG CÒN GỌI THẲNG `arq app.workers.main.WorkerSettings`        ║
╚══════════════════════════════════════════════════════════════════════════╝

Một lần Redis khởi động lại là đủ giết worker **vĩnh viễn**, và nó hỏng theo
kiểu tệ nhất có thể: im lặng. Đo được **ba lần** khi rà P2 (2026-09-20):

    worker-1 | redis.exceptions.ConnectionError:
    worker-1 |   Error while reading from redis:6379 : (104, 'Connection reset by peer')

    TTL arq:queue:health-check = -2        <- khoá không còn, vòng lặp đã chết
    docker health              = healthy   <- Docker vẫn báo khoẻ
    worker PID                 = 553223    <- KHÔNG đổi
    RestartCount               = 0
    /proc/1/stat               = 1 (arq) S     wchan = do_epoll_wait
    job thật đẩy vào           = queued ... +40 s vẫn queued

Ba điều rút ra, và cả ba đều cần thiết để hiểu file này:

1. **Tiến trình KHÔNG thoát.** `Worker.run()` của arq kết thúc bằng
   `finally: self.loop.run_until_complete(self.close())`, mà `close()` gọi
   `pool.delete(health_check_key)` — tức nói chuyện với đúng cái Redis vừa
   chết. Nó không thoát, nó **treo**. Vì thế `restart: unless-stopped` của
   Docker không bao giờ kích hoạt: chính sách restart chỉ nhìn **mã thoát**,
   không nhìn healthcheck.
2. **Healthcheck nói dối một khoảng.** Khoá `arq:queue:health-check` có
   TTL = `WORKER_HEALTHCHECK_S + 1`, nhưng Docker chỉ lật sang `unhealthy`
   sau `interval × retries`. Với 30 s × 3 thì có tới 90 giây `docker compose
   ps` khẳng định một tiến trình đã chết là khoẻ. Đã siết xuống 10 s × 3.
3. **Người dùng không thấy lỗi nào.** Message đứng ở `queued`; API vẫn `202`;
   không có dòng log nào ở phía họ. Đây là nửa sự cố đã ghi trong mục Ghi nhận
   của T-2.19, nay có cơ chế đầy đủ.

╔══════════════════════════════════════════════════════════════════════════╗
║  VÌ SAO `async_run()` CHỨ KHÔNG `run_worker()`                           ║
╚══════════════════════════════════════════════════════════════════════════╝

`run_worker()` bọc sẵn `run()`, tức bọc luôn cái `finally` có thể treo — một
`try/except` quanh nó **không cứu được gì**, vì quyền điều khiển không bao giờ
quay lại chỗ ta bắt. `async_run()` thì chỉ `await` vòng lặp chính và để phần
dọn dẹp cho người gọi, nên ở đây ta tự đóng, và đóng **có trần thời gian**
(`WORKER_SHUTDOWN_TIMEOUT_S`). Đó là toàn bộ khác biệt giữa "nối lại được" và
"treo ở chỗ khác".

`create_worker()` được gọi **bên trong** coroutine: `Worker.__init__` đọc
`asyncio.get_event_loop()` và cài signal handler ngay lúc dựng, nên nó phải
thấy đúng loop mà `asyncio.run()` vừa tạo.

╔══════════════════════════════════════════════════════════════════════════╗
║  TÍN HIỆU DỪNG KHÁC LỖI MẠNG, VÀ PHÂN BIỆT ĐƯỢC HAI CÁI LÀ VIỆC CHÍNH    ║
╚══════════════════════════════════════════════════════════════════════════╝

`docker compose stop` gửi SIGTERM; arq bắt nó trong `handle_sig` và **huỷ**
`main_task`, nên `async_run()` ném `CancelledError`. Nếu vòng lặp dưới đây coi
đó là một lỗi thì `docker compose stop` sẽ dựng lại worker đúng lúc người ta
muốn nó dừng — một worker không tắt được là một lỗi tệ hơn lỗi nó đang vá.
Vì vậy `CancelledError` ⇒ thoát 0, và **chỉ** lỗi mạng mới được dựng lại.

Mọi ngoại lệ khác (lỗi lập trình, `WorkerSettings` sai) cũng để nguyên cho nổi
ra ngoài: dựng lại một tiến trình hỏng vì bug là quay vòng vô tận mà không ai
đọc log, còn để nó chết thì `restart: unless-stopped` + `RestartCount` tăng
dần là thứ nhìn thấy được trong `docker compose ps`.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time

from arq.worker import Worker, create_worker
from redis.exceptions import RedisError

from app.config.settings import settings
from app.core.log_setup import setup_logging
from app.workers.main import WorkerSettings, on_shutdown

logger = logging.getLogger(__name__)

#: Những lỗi được coi là "Redis đi vắng, thử lại sau".
#:
#: `RedisError` phủ cả `ConnectionError` lẫn `TimeoutError` của redis-py.
#: `ConnectionError` **dựng sẵn của Python** đứng cạnh vì `ConnectionResetError`
#: (errno 104 — đúng lỗi đo được ở trên) là con của nó, và redis-py không phải
#: lúc nào cũng kịp bọc lại. Cố tình KHÔNG lấy cả `OSError`: một lỗi đọc file
#: cũng là `OSError`, mà dựng lại worker không sửa được một file hỏng.
NETWORK_ERRORS: tuple[type[BaseException], ...] = (RedisError, ConnectionError)


async def _close_with_timeout(worker: Worker) -> None:
    """Đóng worker cũ, nhưng không cho phép bước đóng treo mãi.

    `Worker.close()` đi qua Redis (xoá khoá healthcheck, chạy `on_shutdown`),
    tức đúng thứ vừa chết trong ca này. Nuốt lỗi ở đây là có chủ ý và hẹp:
    mục tiêu duy nhất của lời gọi này là **nhả tài nguyên rồi đi tiếp**, còn
    lý do phải đi tiếp thì dòng log ở vòng ngoài đã nói.
    """
    try:
        await asyncio.wait_for(worker.close(), timeout=settings.WORKER_SHUTDOWN_TIMEOUT_S)
    except TimeoutError:
        # Python 3.11+ gộp `asyncio.TimeoutError` vào `TimeoutError` dựng sẵn.
        logger.warning(
            "worker: dong khong xong trong %.1fs, bo qua de dung lai",
            settings.WORKER_SHUTDOWN_TIMEOUT_S,
        )
    except Exception as exc:  # noqa: BLE001 — xem docstring
        logger.warning(
            "worker: dong khong sach (%s: %s), bo qua de dung lai", type(exc).__name__, exc
        )


async def _release_loop_bound_resources(worker: Worker) -> None:
    """Dọn hai tài nguyên gắn với event loop, KHÔNG đi qua Redis.

    Đây là bản vá của một lỗi mà stack thật phát hiện còn test đơn thì không:

        RuntimeError: Task <coro=<reaper()>> got Future <Future pending>
                      attached to a different loop

    `Worker.close()` của arq gọi `pool.delete(health_check_key)` **trước**
    `on_shutdown`, nên trong đúng ca B-196 sinh ra để sửa — Redis đã chết —
    dòng ấy ném và `on_shutdown` **không bao giờ chạy**. Mà `on_shutdown` là
    chỗ duy nhất gọi `dispose_engine()` và đóng `LLMClient`. Vòng đời kế tiếp
    dựng một event loop mới (`asyncio.run`) trong khi engine SQLAlchemy toàn
    cục vẫn giữ kết nối asyncpg của loop **đã chết** — và worker sống lại
    trong một trạng thái hỏng theo kiểu mới.

    Gọi thẳng `on_shutdown` thay vì chép lại thân nó: nó đã là định nghĩa của
    "dọn sạch tiến trình này", và cả hai việc nó làm đều idempotent
    (`ctx.pop(..., None)`, `dispose_engine()` có cửa `if _engine is not None`),
    nên chạy hai lần — một lần trong `close()` khi Redis còn sống, một lần ở
    đây — không tốn gì.
    """
    try:
        await on_shutdown(worker.ctx)
    except Exception as exc:  # noqa: BLE001 — dọn dẹp không được chặn lần dựng lại
        logger.warning("worker: don tai nguyen khong sach (%s: %s)", type(exc).__name__, exc)


async def _run_one_lifecycle() -> None:
    """Dựng một worker, chạy tới khi nó dừng, rồi đóng nó.

    Một vòng đời = một `Worker` = một pool Redis = một event loop. Không dùng
    lại instance cũ sau lỗi: pool của nó gắn với event loop đã đóng và với
    những kết nối đã đứt, nên "dựng lại" phải nghĩa là dựng thật — và phải dọn
    thật, xem `_release_loop_bound_resources`.
    """
    worker = create_worker(WorkerSettings)  # type: ignore[arg-type]
    try:
        await worker.async_run()
    finally:
        await _close_with_timeout(worker)
        await _release_loop_bound_resources(worker)


def main() -> int:
    """Vòng nối lại. Trả mã thoát của tiến trình."""
    setup_logging()
    backoff_s = settings.WORKER_RECONNECT_BACKOFF_S
    attempt = 0

    while True:
        started_at = time.monotonic()
        try:
            asyncio.run(_run_one_lifecycle())
        except (asyncio.CancelledError, KeyboardInterrupt):
            # SIGTERM/SIGINT — xem docstring module. Đây là đường thoát DUY
            # NHẤT có chủ ý của vòng lặp này.
            logger.info("worker: nhan tin hieu dung, thoat")
            return 0
        except NETWORK_ERRORS as exc:
            # Một vòng đời chạy được lâu rồi mới đứt là một sự cố MỚI, không
            # phải lần thử lại thứ n của sự cố cũ — nên khoảng chờ quay về
            # mốc đầu. Thiếu dòng này thì sau vài lần Redis chớp trong nhiều
            # ngày, worker sẽ ngủ tối đa trước mỗi lần dựng lại, kể cả khi
            # Redis đã sống lại ngay tức thì.
            if time.monotonic() - started_at >= settings.WORKER_RECONNECT_BACKOFF_MAX_S:
                backoff_s = settings.WORKER_RECONNECT_BACKOFF_S
                attempt = 0
            attempt += 1
            logger.warning(
                "worker: mat Redis (%s: %s) — dung lai lan %d sau %.1fs",
                type(exc).__name__,
                exc,
                attempt,
                backoff_s,
            )
            time.sleep(backoff_s)
            backoff_s = min(backoff_s * 2, settings.WORKER_RECONNECT_BACKOFF_MAX_S)
        else:
            # `async_run()` trả về bình thường: arq chỉ làm thế ở chế độ burst,
            # thứ ta không bật. Tới được đây nghĩa là vòng lặp chính đã kết
            # thúc mà không ai huỷ nó — dừng sạch, không dựng lại.
            logger.info("worker: vong lap chinh ket thuc, thoat")
            return 0


if __name__ == "__main__":
    sys.exit(main())
