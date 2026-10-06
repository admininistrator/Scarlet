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
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/artifacts-render", include_in_schema=False)

_FRAME_HTML = """<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>artifact</title>
</head>
<body></body>
</html>
"""


@router.get("/{_rest:path}", response_class=HTMLResponse)
async def artifact_frame(_rest: str) -> HTMLResponse:
    return HTMLResponse(_FRAME_HTML)
