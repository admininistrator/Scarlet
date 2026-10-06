"""Trang khung của origin phụ `artifacts.<domain>` (ADR-10, §14.3) — T-5.6.

Nginx chuyển **mọi** đường của origin phụ về đây (`location /` ⇒
`proxy_pass http://api:8000/artifacts-render/`, Phụ lục D). Trang không tham
số, không id, không đọc DB, không đăng nhập: nội dung artifact tới sau bằng
`postMessage` từ trang cha đã xác thực (T-5.7) — ở đây không có gì để IDOR
(B-182). Đường con bất kỳ ⇒ cùng một trang.

**Vì sao router riêng ngoài `/api/v1`.** Origin chính chỉ chuyển `/api/` cho
`api`; `/artifacts-render/` ở đó rơi vào SPA — khung không tới được từ origin
chính, nên không thể vô tình chạy cùng gốc với cookie phiên. Nằm dưới
`/api/v1` thì `https://<domain>/api/v1/...` sẽ phục vụ khung ngay trên origin
chính, và các dependency xác thực của `app/api/v1/__init__.py` không áp cho nó.

CSP và `nosniff` do Nginx đặt (Phụ lục D), không phải ở đây: cùng một chỗ phủ
cả trang lỗi.

**Bắt tay `postMessage` (T-5.7, §14.3 đoạn cuối).** Script của khung gắn
listener rồi gửi `ready` cho `window.parent`; cha gửi `{type: "render", kind,
content}` **sau** `ready`; khung trả `rendered` hoặc `error {message}`. Khung
chỉ nhận message có `event.source === window.parent` **và** `event.origin` ==
`PUBLIC_BASE_URL` — chèn vào trang lúc phục vụ (A3), không literal. Thiếu kiểm
`source` thì một tab khác cùng origin chính `window.open` khung này rồi đẩy nội
dung vào được (DoD T-5.7). Nội dung không bao giờ đi qua URL: access log ghi
URL (T-4.1 ⑥).

Khung **dùng một lần**: `document.open()` xoá mọi listener của `window` (HTML
spec) và phía cha đổi nội dung bằng iframe MỚI (`ArtifactFrame.tsx`) — state
và timer của script cũ chết cùng iframe cũ.
"""

import json

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.config.settings import settings

router = APIRouter(prefix="/artifacts-render", include_in_schema=False)

# `__PARENT_ORIGIN__` thay lúc phục vụ. Tên các kiểu message ở MỘT chỗ phía
# khung (`MESSAGE`); phía cha là `ARTIFACT_MESSAGE` của `ArtifactFrame.tsx`.
_FRAME_HTML = """<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>artifact</title>
</head>
<body>
<script>
(() => {
  const PARENT_ORIGIN = __PARENT_ORIGIN__;
  const MESSAGE = { ready: "ready", render: "render", rendered: "rendered", error: "error" };
  const parent = window.parent;
  const reply = (data) => parent.postMessage(data, PARENT_ORIGIN);
  function onMessage(event) {
    if (event.source !== parent || event.origin !== PARENT_ORIGIN) return;
    const data = event.data;
    if (!data || data.type !== MESSAGE.render) return;
    if (data.kind !== "html" || typeof data.content !== "string") {
      reply({ type: MESSAGE.error, message: "kind chua ho tro: " + String(data.kind) });
      return;
    }
    removeEventListener("message", onMessage);
    try {
      document.open();
      document.write(data.content);
      document.close();
      reply({ type: MESSAGE.rendered });
    } catch (e) {
      reply({ type: MESSAGE.error, message: String(e) });
    }
  }
  addEventListener("message", onMessage);
  reply({ type: MESSAGE.ready });
})();
</script>
</body>
</html>
"""


@router.get("/{_rest:path}", response_class=HTMLResponse)
async def artifact_frame(_rest: str) -> HTMLResponse:
    # `<` thoát thành `\u003c`: giá trị nằm trong <script>, không được đóng thẻ.
    origin = json.dumps(settings.PUBLIC_BASE_URL).replace("<", "\\u003c")
    return HTMLResponse(_FRAME_HTML.replace("__PARENT_ORIGIN__", origin))
