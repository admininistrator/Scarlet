"""Gom router của `/api/v1` — và là nơi khai "router nào đòi tài khoản dùng
được" (§11.1, T-2.7).

`dependencies=[Depends(require_app_access)]` đặt ở **lời gọi `include_router`**
chứ không rải vào từng `@router.get/post`: cạm bẫy của T-2.7 ("mỗi endpoint sẽ
có một luật khác nhau") và của T-2.16 ("quên `require_admin` ở MỘT endpoint là
đủ") là cùng một cạm bẫy, và cách duy nhất đóng nó là để danh sách nằm ở một
chỗ đọc hết được trong một màn hình. Endpoint thứ mười một của
`conversations.py` sẽ được bảo vệ vì nó nằm trong router, không phải vì ai đó
nhớ chép thêm một dòng.

`settings` (T-2.14) gia nhập danh sách ấy với **cột "Xem UI"**, không phải
cột "Chat": §11.1 cho `pending_approval` chat bằng BYOK, và khoá BYOK vào được
DB qua đúng router này — gắn `require_chat_access` ở đây là khoá vòng (muốn có
khoá thì phải đã có khoá).

`admin` (T-2.16) có danh sách **riêng** (`_ADMIN`), không dùng
`_AUTHENTICATED`: nó cần thêm `require_admin` (§16.3) và **không** cần luật
§11.4 — mọi POST của nó nhắm vào một tài nguyên đã tồn tại (`{user_id}` trong
đường dẫn) chứ không tạo ra cái gì, nên bấm hai lần là hai lần đổi cùng một
hàng về cùng một trạng thái, không phải hai hàng mới. `change_user_status` tự
lo phần đó bằng nhánh "đích đã đạt ⇒ 200, không ghi sổ".

Ba router KHÔNG có mặt trong danh sách đó, mỗi cái một lý do:

* `models` — `GET /models` hôm nay công khai (T-0.7, chưa lọc theo user như
  ADR-12 hứa); §11.1 cũng cho `pending_approval` "chọn model được".
* `health` — phép kiểm hạ tầng, không có danh tính nào để hỏi.
* `auth` — phần lớn là route công khai (`register`, `login`, `verify-email`),
  và `logout` **phải** chạy được cả khi tài khoản vừa bị khoá (NQ-42: không
  đóng được phiên của chính mình là C21 ở dạng khác). Route duy nhất của nó
  đòi tài khoản dùng được là `GET /auth/me`, khai ngay tại chỗ trong
  `auth.py`.

**Và từ T-2.8, nơi khai "POST nào chịu luật idempotency của §11.4".** Cùng ba
router, cùng lý do đặt ở `include_router`: một POST thứ mười hai thêm vào
`conversations.py` phải chịu luật vì nó nằm trong router, không phải vì ai đó
nhớ chép thêm một dòng. `auth` **không** có mặt vì khoá §11.4 mở đầu bằng
`{user_id}` mà `register`/`login`/`refresh` chạy khi chưa có ai đăng nhập —
xem docstring `app/core/idempotency.py`.

`IDEMPOTENCY_REQUIRED_ROUTES` là danh sách route mà header là **bắt buộc**
(A8, thiếu ⇒ `400`); mọi POST còn lại của ba router là "tuỳ chọn": có header
thì áp luật, không có thì đi tiếp. Danh sách nằm ở đây — cạnh
`require_app_access` — chứ không trong `core/idempotency.py`, vì `core/`
không được biết tên route của `api/` (luật lớp §5.3).
"""

from fastapi import APIRouter, Depends

from app.api.v1 import admin, auth, conversations, health, messages, models, stream
from app.api.v1 import settings as settings_router
from app.config.settings import settings
from app.core.deps import require_admin, require_app_access
from app.core.idempotency import require_idempotency

#: A8: "Bắt buộc với POST /conversations/{id}/messages". Một tên route, không
#: phải một đường dẫn — xem `app/core/idempotency.py::build_key`.
#:
#: **Hai tên từ NQ-93 (B-231), không một.** `POST /messages/{id}/retry` cũng
#: *tạo tài nguyên* (một `assistant_message_id` mới ⇒ một hoá đơn mới), nên bắt
#: buộc nó là **áp** A8 chứ không lệch — A8 gọi đích danh một endpoint vì đó là
#: endpoint đắt nhất, không vì nó là endpoint duy nhất tạo ra một lượt sinh.
#: Hai nút Retry cạnh nhau của T-3.7 là chỗ hai lần bấm nhanh gặp nhau, và lớp
#: `_job_id` của B-92 không đỡ được (mỗi lần bấm một id khác).
#:
#: `PATCH /messages/{id}` **vẫn ngoài vùng phủ** (B-232): nó không phải POST, và
#: `GUARDED_METHOD` giữ nguyên `POST` theo đúng chữ §11.4/A8 — xem NQ-93.
IDEMPOTENCY_REQUIRED_ROUTES = frozenset(
    {messages.CREATE_MESSAGE_ROUTE_NAME, messages.RETRY_ROUTE_NAME}
)

_idempotency = require_idempotency(IDEMPOTENCY_REQUIRED_ROUTES)

#: Hai luật đi cùng nhau ở mọi router có danh tính. Thứ tự là chủ ý:
#: `require_app_access` chạy trước, nên một tài khoản `suspended` nhận `403`
#: mà **không** để lại khoá `idem:` nào trong Redis.
_AUTHENTICATED = [Depends(require_app_access), Depends(_idempotency)]

#: §16.3 + cạm bẫy T-2.16 ("quên `require_admin` ở MỘT endpoint là đủ"): cả hai
#: luật gắn ở ĐÂY, không rải vào `admin.py`. `require_app_access` đi trước —
#: một admin mà tài khoản vừa bị khoá không còn là một admin, và để `/admin/*`
#: không thành cánh cửa duy nhất của app không chịu bảng §11.1.
_ADMIN = [Depends(require_app_access), Depends(require_admin)]

router = APIRouter(prefix="/api/v1")
router.include_router(models.router)
router.include_router(admin.router, dependencies=_ADMIN)
router.include_router(health.router)
router.include_router(stream.router, dependencies=_AUTHENTICATED)
router.include_router(conversations.router, dependencies=_AUTHENTICATED)
router.include_router(messages.router, dependencies=_AUTHENTICATED)
router.include_router(settings_router.router, dependencies=_AUTHENTICATED)
router.include_router(auth.router)

# §18.6 — `/_debug/*` CHỈ tồn tại khi DEBUG=true. Gắn router có điều kiện thay
# vì kiểm `if settings.DEBUG` trong từng handler: đường dẫn không được đăng ký
# thì FastAPI trả 404 một cách tự nhiên, và không có nhánh nào để quên khi
# thêm endpoint debug thứ hai (§18.6 còn liệt `/_debug/stream/{message_id}`).
if settings.DEBUG:
    from app.api.v1 import debug

    router.include_router(debug.router)
