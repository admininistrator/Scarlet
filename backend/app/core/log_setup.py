"""Dựng logging cho cây logger `app.*` — MỘT hàm cho cả ba tiến trình (T-9.5a, B-288).

KH tham chiếu: §20 (Log), §21.1, C20 · tasks.md T-9.5a.

Trước T-9.5a, `worker` và `cli` mỗi nơi một bản `_setup_logging`, còn `api`
không có bản nào: logger `app` ở mức hiệu lực `WARNING`, không handler, nên mọi
`logger.info` của tầng API rơi vào hư không (B-288). Gọi hàm này ở:

* `api` — trong `lifespan` (`app/main.py`), tức **sau** `dictConfig` của
  uvicorn. Không ở mức module: test import `app.main` mà không chạy lifespan,
  và `propagate = False` ở mức module sẽ cắt `caplog` (handler ở root) khỏi mọi
  record `app.*` của cả bộ test.
* `worker` — trong `on_startup` (sau `dictConfig` của arq) và đầu
  `app/workers/run.py::main`.
* `cli` — đầu `main()`.

`propagate = False`: handler gắn ở `app`, record không đi tiếp lên root — root
có handler nào (một `dictConfig` sau này) thì một dòng sẽ in hai lần.
"""

from __future__ import annotations

import logging

from app.config.settings import settings
from app.core.log_redact import install_log_redaction


def setup_logging() -> None:
    """Gắn đúng MỘT handler cho logger `app`, mức `LOG_LEVEL`. Idempotent."""
    # C20 (T-2.14) — trước cả `return` sớm: bộ che là của TIẾN TRÌNH,
    # không của handler, nên nó phải được cài kể cả khi handler đã có.
    install_log_redaction()
    # Access log của uvicorn ghi `GET /đường?query` nguyên văn — `?token=` của
    # link thư, `/api/v1/s/<token>`. Nginx đã có access log, không query, che
    # token chia sẻ (T-9.5a); ở `worker`/`cli` logger này không ai dùng.
    logging.getLogger("uvicorn.access").disabled = True
    app_logger = logging.getLogger("app")
    if app_logger.handlers:
        return
    handler = logging.StreamHandler()
    # Cùng `datefmt` với formatter của arq để hai nguồn log đọc chung được.
    handler.setFormatter(logging.Formatter("%(asctime)s: %(message)s", datefmt="%H:%M:%S"))
    app_logger.addHandler(handler)
    app_logger.setLevel(settings.LOG_LEVEL)
    app_logger.propagate = False
