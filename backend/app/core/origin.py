"""Kiểm `Origin` cho mọi method đổi trạng thái (NQ-36, B-114) — T-2.3.

Từ T-2.3, `get_current_user_id` chấp nhận một cookie phiên (§20 CSRF).
`SameSite=Lax` đã chặn phần lớn CSRF (cookie không kèm request cross-site trừ
điều hướng GET top-level), nhưng không chặn được form POST cross-site cũ hay
trình duyệt không hỗ trợ `SameSite`. Lớp phòng thủ thứ hai: so `Origin` với
`settings.PUBLIC_BASE_URL` — kiến trúc một-origin-duy-nhất (Nginx phục vụ cả
FE lẫn `/api/v1` trên cùng host, T-0.10/T-0.11) nên đúng một giá trị là đủ,
không cần danh sách CORS.

**Vắng `Origin` thì CHO QUA, không chặn.** Trình duyệt không phải lúc nào
cũng gửi `Origin` (điều hướng same-site cũ, một số client không phải trình
duyệt), và mọi client hiện có của Phase 1 (`httpx`, `curl`, `test_resume.py`,
mọi test trong `tests/`) không gửi header này — chặn khi vắng mặt sẽ biến mọi
`POST`/`PATCH`/`DELETE` hiện có thành 403. Điều khoản chặn CHỈ áp dụng khi
`Origin` CÓ MẶT và KHÔNG khớp — đúng hình dạng của một request cross-site thật.

**Vì sao ASGI thuần, không `BaseHTTPMiddleware`.** `BaseHTTPMiddleware` bọc lại
toàn bộ response qua một `StreamingResponse` nội bộ của chính nó — với response
thường thì vô hại, nhưng đây là app có SSE (§7, A1), và lớp bọc thêm đó là
đúng loại rủi ro mà C1/C2 đã cảnh báo (đệm ngầm, mất khả năng phát hiện client
ngắt kết nối). Class ASGI thuần ở đây forward thẳng `(scope, receive, send)`
cho mọi request được cho qua — không có lớp bọc nào chèn vào giữa.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send

from app.config.settings import settings
from app.core.errors import ApiErrorCode, ErrorBody, ErrorEnvelope

#: §18.2/§7 dùng POST/PATCH/DELETE cho mọi thao tác đổi trạng thái; GET/HEAD/
#: OPTIONS không đổi gì nên không cần kiểm.
STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

_BODY_TU_CHOI = (
    ErrorEnvelope(error=ErrorBody(code=ApiErrorCode.FORBIDDEN, message="origin khong hop le"))
    .model_dump_json()
    .encode("utf-8")
)


class OriginCheckMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in STATE_CHANGING_METHODS:
            await self.app(scope, receive, send)
            return

        origin = dict(scope["headers"]).get(b"origin")
        if origin is not None and origin.decode("latin-1") != settings.PUBLIC_BASE_URL:
            await send(
                {
                    "type": "http.response.start",
                    "status": 403,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": _BODY_TU_CHOI})
            return

        await self.app(scope, receive, send)
