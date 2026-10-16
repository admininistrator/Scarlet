"""§21.1 — log JSON một dòng, `request_id` từ header tới job `worker` (T-9.5b)."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import uuid
from collections.abc import Iterator
from typing import Annotated, Any

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1 import attachments, messages
from app.core.access_token import encode_access_token
from app.core.deps import SESSION_COOKIE_NAME, get_current_user_id
from app.core.log_setup import JsonFormatter, log_context
from app.core.request_id import RequestIdMiddleware
from app.db.models import UserRole, UserStatus
from app.main import app as real_app
from app.workers.main import FUNCTIONS, with_request_id

HEX32 = re.compile(r"[0-9a-f]{32}")
NGINX_ID = "5f0c9a2e8b7d4c1fa3e6b9d0c2f4a817"  # hình dạng `$request_id` của Nginx


@pytest.fixture
def json_lines() -> Iterator[io.StringIO]:
    """Handler JSON thật trên `app` — `caplog` format muộn, lúc contextvar đã trả."""
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    app_logger = logging.getLogger("app")
    level = app_logger.level
    app_logger.addHandler(handler)
    app_logger.setLevel(logging.INFO)
    yield buf
    app_logger.removeHandler(handler)
    app_logger.setLevel(level)


def _parsed(buf: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in buf.getvalue().splitlines()]


def test_every_line_is_json_even_with_newline_and_traceback(json_lines: io.StringIO) -> None:
    log = logging.getLogger("app.test")
    token = log_context.set({"request_id": NGINX_ID})
    try:
        log.info('dong 1\ndong gia mao {"level": "ERROR"}')
        try:
            raise ValueError("no\nnua")
        except ValueError:
            log.exception("hong")
    finally:
        log_context.reset(token)
    log.warning("ngoai request")

    lines = json_lines.getvalue().splitlines()
    assert len(lines) == 3  # xuống dòng trong msg / traceback không bẻ dòng
    first, second, third = (json.loads(line) for line in lines)
    assert first["msg"].startswith("dong 1\n") and first["request_id"] == NGINX_ID
    assert {"ts", "level", "logger", "msg"} <= first.keys()
    assert "ValueError: no\nnua" in second["exc"]
    assert "request_id" not in third  # khoá vắng thì bỏ


def test_import_time_warnings_are_json_too() -> None:
    """Cảnh báo lúc nạp `settings` / catalog ra trước `setup_logging()` — qua `lastResort`."""
    assert logging.lastResort is not None
    assert isinstance(logging.lastResort.formatter, JsonFormatter)


async def _hello(scope: Any, receive: Any, send: Any) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


async def _call(headers: list[tuple[bytes, bytes]]) -> tuple[list[dict[str, Any]], str]:
    sent: list[dict[str, Any]] = []

    async def send(message: Any) -> None:
        sent.append(message)

    async def receive() -> Any:
        return {"type": "http.request"}

    scope = {"type": "http", "method": "GET", "path": "/", "headers": headers}
    await RequestIdMiddleware(_hello)(scope, receive, send)
    rid = dict(sent[0]["headers"])[b"x-request-id"].decode()
    return sent, rid


async def test_valid_nginx_request_id_is_kept(json_lines: io.StringIO) -> None:
    _, rid = await _call([(b"x-request-id", NGINX_ID.encode())])
    assert rid == NGINX_ID
    (line,) = _parsed(json_lines)
    assert line["request_id"] == NGINX_ID and line["status"] == 200


@pytest.mark.parametrize(
    "junk",
    [
        NGINX_ID[:16].encode() + b"\n" + NGINX_ID[16:].encode(),  # xuống dòng
        NGINX_ID.encode() + b"0",  # quá dài
        NGINX_ID.upper().encode(),  # không phải dạng Nginx
        b'0" injected="1' + b"0" * 18,  # ký tự lạ
        b"",
    ],
)
async def test_junk_request_id_is_replaced(junk: bytes, json_lines: io.StringIO) -> None:
    _, rid = await _call([(b"x-request-id", junk)])
    assert HEX32.fullmatch(rid) and rid.encode() != junk
    assert _parsed(json_lines)[0]["request_id"] == rid


async def test_response_carries_request_id_without_nginx() -> None:
    """Cạm bẫy ③ — `curl` thẳng `api:8000` không có header ⇒ sinh mới, vẫn trả về."""
    async with AsyncClient(transport=ASGITransport(app=real_app), base_url="http://api") as c:
        resp = await c.get("/health")
    assert HEX32.fullmatch(resp.headers["x-request-id"])


async def test_request_line_has_route_template_user_and_latency(
    monkeypatch: pytest.MonkeyPatch, blacklist_redis_fake: Any, json_lines: io.StringIO
) -> None:
    monkeypatch.setattr("app.core.deps.get_redis", lambda: blacklist_redis_fake)
    user_id = uuid.uuid4()
    mini = FastAPI()
    mini.add_middleware(RequestIdMiddleware)

    @mini.get("/things/{thing_id}")
    async def thing(thing_id: str, _: Annotated[uuid.UUID, Depends(get_current_user_id)]) -> str:
        return thing_id

    token = encode_access_token(
        user_id=user_id, role=UserRole.USER, tier="free", status=UserStatus.ACTIVE, ttl_minutes=15
    )
    async with AsyncClient(transport=ASGITransport(app=mini), base_url="http://api") as c:
        resp = await c.get(
            "/things/secret-token-in-path", headers={"Cookie": f"{SESSION_COOKIE_NAME}={token}"}
        )
    assert resp.status_code == 200
    (line,) = _parsed(json_lines)
    assert line["route"] == "/things/{thing_id}"  # mẫu, không đường thật
    assert "secret-token-in-path" not in json_lines.getvalue()
    assert line["user_id"] == str(user_id) and line["status"] == 200
    assert isinstance(line["latency_ms"], float)


class _Arq:
    def __init__(self) -> None:
        self.kwargs: dict[str, dict[str, Any]] = {}

    async def enqueue_job(self, name: str, *args: Any, **kwargs: Any) -> object:
        self.kwargs[name] = kwargs
        return object()


async def test_enqueued_jobs_carry_request_id(monkeypatch: pytest.MonkeyPatch) -> None:
    arq = _Arq()

    async def pool() -> _Arq:
        return arq

    monkeypatch.setattr(messages, "get_arq_pool", pool)
    monkeypatch.setattr(attachments, "get_arq_pool", pool)
    token = log_context.set({"request_id": NGINX_ID})
    try:
        await messages._day_job(uuid.uuid4())
        await messages._enqueue_title(uuid.uuid4(), uuid.uuid4())
        await attachments._enqueue_extract(uuid.uuid4())
    finally:
        log_context.reset(token)
    assert {name: kw["request_id"] for name, kw in arq.kwargs.items()} == {
        "generate": NGINX_ID,
        "title": NGINX_ID,
        "extract": NGINX_ID,
    }


async def test_job_log_lines_carry_request_id_from_job_arg(json_lines: io.StringIO) -> None:
    assert all(hasattr(f.coroutine, "__wrapped__") for f in FUNCTIONS)  # cả ba job bọc

    async def job(ctx: dict[str, Any], message_id: str) -> None:
        logging.getLogger("app.workers.generate").info("generate: xong %s", message_id)

    run = with_request_id(job)
    await run({}, "m1", request_id=NGINX_ID)
    await run({}, "m2")  # job không có id (enqueue cũ) ⇒ không mang id của job trước
    first, second = _parsed(json_lines)
    assert first["request_id"] == NGINX_ID
    assert "request_id" not in second


async def test_sse_chunks_pass_through_and_line_written_at_close(
    json_lines: io.StringIO,
) -> None:
    """C1 — middleware không đệm: chunk đầu tới `send` khi app còn đang sinh."""
    release = asyncio.Event()

    async def sse(scope: Any, receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"data: 1\n\n", "more_body": True})
        await release.wait()
        await send({"type": "http.response.body", "body": b"data: 2\n\n"})

    sent: list[Any] = []

    async def send(message: Any) -> None:
        sent.append(message)

    async def receive() -> Any:
        return {"type": "http.request"}

    scope = {"type": "http", "method": "GET", "path": "/s", "headers": []}
    task = asyncio.create_task(RequestIdMiddleware(sse)(scope, receive, send))
    for _ in range(10):
        await asyncio.sleep(0)
    assert [m.get("body") for m in sent[1:]] == [b"data: 1\n\n"]
    assert json_lines.getvalue() == ""  # chưa đóng ⇒ chưa có dòng log
    release.set()
    await task
    assert len(sent) == 3
    assert len(_parsed(json_lines)) == 1
