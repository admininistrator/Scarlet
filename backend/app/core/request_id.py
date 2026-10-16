"""`request_id` cho mọi request + một dòng log khi request xong — §21.1, T-9.5b.

Nginx đặt `X-Request-Id: $request_id` (32 hex). Header đúng hình dạng ấy thì
giữ — để một dòng access log của Nginx lần được tới dòng `api` và job `worker`
(id đi theo tham số job, `app/workers/main.py::with_request_id`); sai hình dạng
hoặc vắng (`curl` thẳng `api:8000`, test) ⇒ sinh mới, **không** tin chuỗi lạ.

ASGI thuần, không `BaseHTTPMiddleware` — cùng lý do `core/origin.py` (C1): lớp
bọc của nó đệm ngầm SSE. `send` ở đây chỉ chèn một header vào
`http.response.start` rồi chuyển tiếp từng message. Dòng log ghi khi `app`
trả về — với SSE là lúc stream đóng, không mỗi chunk. `route` là mẫu đường
dẫn (`/api/v1/messages/{message_id}/stream`), không đường thật: `/s/<token>`
mang thẻ vào cửa (T-9.5a).
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.log_setup import log_context

logger = logging.getLogger(__name__)

#: Đúng hình dạng `$request_id` của Nginx.
_VALID_ID = re.compile(r"[0-9a-f]{32}")


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        raw = dict(scope["headers"]).get(b"x-request-id", b"").decode("latin-1")
        request_id = raw if _VALID_ID.fullmatch(raw) else uuid.uuid4().hex
        token = log_context.set({"request_id": request_id})
        status = 500  # app ném trước khi trả lời ⇒ ServerErrorMiddleware trả 500
        started = time.perf_counter()

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = [*message.get("headers", ()), (b"x-request-id", request_id.encode())]
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            route = getattr(scope.get("route"), "path", None)
            extra: dict[str, Any] = {
                "status": status,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            }
            if route is not None:
                extra["route"] = route
            logger.info("%s %s %s", scope["method"], route or "-", status, extra=extra)
            log_context.reset(token)
