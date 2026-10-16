"""`setup_logging()` — một hàm dựng logging cho `api`/`worker`/`cli` (T-9.5a, B-288)."""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest

from app.core.log_setup import setup_logging
from app.db import session as db_session


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    """`propagate=False` sống qua test này thì `caplog` của cả bộ mất record `app.*`."""
    app_logger = logging.getLogger("app")
    access = logging.getLogger("uvicorn.access")
    handlers, level, propagate = app_logger.handlers[:], app_logger.level, app_logger.propagate
    disabled = access.disabled
    app_logger.handlers.clear()
    # Test `cli` chạy trước đã `setup_logging()` ⇒ `propagate=False`; pytest
    # gắn `LogCaptureHandler` vào logger không propagate lúc vào pha call.
    app_logger.propagate = True
    yield
    app_logger.handlers[:] = handlers
    app_logger.setLevel(level)
    app_logger.propagate = propagate
    access.disabled = disabled


def test_handler_attached_once_after_two_setups() -> None:
    setup_logging()
    setup_logging()
    assert len(logging.getLogger("app").handlers) == 1
    assert logging.getLogger("app").propagate is False


def test_api_logger_info_reaches_handler(capsys: pytest.CaptureFixture[str]) -> None:
    """B-288: trước T-9.5a `logger.info` của tầng API không in (mức hiệu lực WARNING)."""
    setup_logging()  # handler dựng SAU capsys ⇒ ghi vào stderr đã bắt
    logging.getLogger("app.api.v1.messages").info("job title cho hoi thoai x — bo qua")
    assert "job title cho hoi thoai x — bo qua" in capsys.readouterr().err


def test_uvicorn_access_log_off() -> None:
    """Uvicorn ghi `GET /đường?query` nguyên văn — Nginx giữ access log (không query)."""
    setup_logging()
    assert logging.getLogger("uvicorn.access").disabled


def test_engine_hides_sql_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    """`StatementError` không mang `[parameters: …]` (nội dung message) vào traceback."""
    monkeypatch.setattr(db_session, "_engine", None)  # dựng mới, không nối — monkeypatch trả lại
    assert db_session.get_engine().sync_engine.hide_parameters is True
