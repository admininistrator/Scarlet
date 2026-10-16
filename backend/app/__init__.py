"""§21.1 (T-9.5b): record phát ra lúc import — trước `setup_logging()`, vd. cảnh
báo của `settings` (`TURNSTILE_SECRET`) và catalog (B-65) — không có handler nào
nên đi qua `logging.lastResort`; nó cũng phải in một dòng JSON."""

import logging

from app.core.log_setup import JsonFormatter

if logging.lastResort is not None:
    logging.lastResort.setFormatter(JsonFormatter())
