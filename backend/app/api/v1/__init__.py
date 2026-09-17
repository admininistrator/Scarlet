"""Gom router của `/api/v1` — và là nơi khai "router nào đòi tài khoản dùng
được" (§11.1, T-2.7).

`dependencies=[Depends(require_app_access)]` đặt ở **lời gọi `include_router`**
chứ không rải vào từng `@router.get/post`: cạm bẫy của T-2.7 ("mỗi endpoint sẽ
có một luật khác nhau") và của T-2.16 ("quên `require_admin` ở MỘT endpoint là
đủ") là cùng một cạm bẫy, và cách duy nhất đóng nó là để danh sách nằm ở một
chỗ đọc hết được trong một màn hình. Endpoint thứ mười một của
`conversations.py` sẽ được bảo vệ vì nó nằm trong router, không phải vì ai đó
nhớ chép thêm một dòng.

Ba router KHÔNG có mặt trong danh sách đó, mỗi cái một lý do:

* `models` — `GET /models` hôm nay công khai (T-0.7, chưa lọc theo user như
  ADR-12 hứa); §11.1 cũng cho `pending_approval` "chọn model được".
* `health` — phép kiểm hạ tầng, không có danh tính nào để hỏi.
* `auth` — phần lớn là route công khai (`register`, `login`, `verify-email`),
  và `logout` **phải** chạy được cả khi tài khoản vừa bị khoá (NQ-42: không
  đóng được phiên của chính mình là C21 ở dạng khác). Route duy nhất của nó
  đòi tài khoản dùng được là `GET /auth/me`, khai ngay tại chỗ trong
  `auth.py`.
"""

from fastapi import APIRouter, Depends

from app.api.v1 import admin, auth, conversations, health, messages, models, stream
from app.config.settings import settings
from app.core.deps import require_app_access

router = APIRouter(prefix="/api/v1")
router.include_router(models.router)
router.include_router(admin.router)
router.include_router(health.router)
router.include_router(stream.router, dependencies=[Depends(require_app_access)])
router.include_router(conversations.router, dependencies=[Depends(require_app_access)])
router.include_router(messages.router, dependencies=[Depends(require_app_access)])
router.include_router(auth.router)

# §18.6 — `/_debug/*` CHỈ tồn tại khi DEBUG=true. Gắn router có điều kiện thay
# vì kiểm `if settings.DEBUG` trong từng handler: đường dẫn không được đăng ký
# thì FastAPI trả 404 một cách tự nhiên, và không có nhánh nào để quên khi
# thêm endpoint debug thứ hai (§18.6 còn liệt `/_debug/stream/{message_id}`).
if settings.DEBUG:
    from app.api.v1 import debug

    router.include_router(debug.router)
