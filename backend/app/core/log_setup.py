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

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from app.core.log_redact import install_log_redaction

#: Ngữ cảnh log của request / job đang chạy — `request_id`, `user_id` (§21.1,
#: T-9.5b). Đặt bởi `RequestIdMiddleware` (`api`) và `with_request_id` (`worker`).
#: Một dict **mutable** chứ không một biến mỗi khoá: dependency auth ghi
#: `user_id` vào chính dict của request, và dòng log cuối của middleware (nằm
#: ở context ngoài) thấy được — kể cả khi chỗ ghi chạy trong threadpool
#: (context chép, object dùng chung).
log_context: ContextVar[dict[str, Any] | None] = ContextVar("log_context", default=None)

#: Khoá lấy từ `extra=` của record (dòng "request xong" của middleware).
_EXTRA_KEYS = ("route", "status", "latency_ms")


def bind_log_context(**values: Any) -> None:
    """Thêm khoá vào ngữ cảnh đang có; ngoài request / job thì không làm gì."""
    ctx = log_context.get()
    if ctx is not None:
        ctx.update(values)


def current_request_id() -> str | None:
    ctx = log_context.get()
    return ctx.get("request_id") if ctx else None


class JsonFormatter(logging.Formatter):
    """Mỗi record một dòng JSON — §21.1. Khoá vắng thì bỏ.

    `json.dumps` escape `\\n` / ký tự điều khiển ⇒ chữ từ client (route, id)
    không bẻ được dòng (log injection — Cạm bẫy ④); traceback vào khoá `exc`.
    `ensure_ascii=False`: log đọc được chữ Việt.
    """

    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        line.update(log_context.get() or {})
        line.update({k: getattr(record, k) for k in _EXTRA_KEYS if hasattr(record, k)})
        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            line["exc"] = record.exc_text
        if record.stack_info:
            line["stack"] = record.stack_info
        return json.dumps(line, ensure_ascii=False, default=str)


def setup_logging() -> None:
    """Gắn đúng MỘT handler cho logger `app`, mức `LOG_LEVEL`. Idempotent."""
    # Import muộn: `app/__init__.py` import module này TRƯỚC `settings` để cảnh
    # báo lúc nạp `settings` / catalog cũng ra JSON.
    from app.config.settings import settings

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
    handler.setFormatter(JsonFormatter())
    app_logger.addHandler(handler)
    app_logger.setLevel(settings.LOG_LEVEL)
    app_logger.propagate = False
