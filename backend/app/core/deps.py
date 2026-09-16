"""Dependency dùng chung của tầng HTTP (§23 `core/deps.py`).

KH tham chiếu: §18.1, §20, Phụ lục F · CLAUDE.md A10 · tasks.md T-2.3 · B-83.

Hiện chỉ có **một** thứ: "ai đang gọi". Nó ở đây vì T-1.7 là endpoint đầu tiên
cần trả lời câu hỏi đó, và vì T-1.8/T-1.9/T-1.13 sẽ hỏi lại đúng câu ấy.

╔══════════════════════════════════════════════════════════════════════════╗
║  ĐÂY LÀ CHỖ TẠM CỦA PHASE 1 — T-2.3 THAY THÂN HÀM `get_current_user_id`  ║
╚══════════════════════════════════════════════════════════════════════════╝

Kế hoạch đặt auth thật (đăng nhập, JWT, `get_current_user`) ở **T-2.3**, tức
Phase 2; nhưng T-1.7 đã phải kiểm quyền sở hữu ngay từ bây giờ ("message của
user khác → 404"), và cả Phase 1 — `scripts/test_resume.py`, `bench_ttft.py`,
màn chat thô của T-1.14 — cần một danh tính để gọi API. Người dùng chốt phương
án này trong phiên T-1.7 (xem Nhật ký quyết định NQ-24).

**Ba thứ giữ cho chỗ tạm này không sống sót sang production:**

1. `DEBUG=false` thì dependency **từ chối mọi request** bằng `503` — không có
   đường nào để một triển khai thật lỡ chạy với nó. `.env.example` để
   `DEBUG=false`, nên mặc định của một máy mới là "đóng".
2. Router **không** biết nó đang đọc header nào. Chúng chỉ viết
   `Depends(get_current_user_id)` và nhận một `UUID`. T-2.3 sửa đúng thân hàm
   dưới đây, không sửa một dòng nào trong `api/v1/*.py`.
3. Hàm **không** kiểm tra user có tồn tại trong bảng `users` hay không, và đó
   là chủ ý: nó không phải xác thực, nó là một chỗ giữ chân. Mọi truy vấn sau
   đó vẫn lọc `user_id` **trong câu SQL** (§20), nên một `X-User-Id` bịa ra chỉ
   thấy được đúng số hội thoại nó sở hữu — tức là không cái nào.

┌──────────────────────────────────────────────────────────────────────────┐
│  VÌ SAO CÓ ĐƯỜNG THỨ HAI: COOKIE  (T-1.14, NQ-33)                        │
└──────────────────────────────────────────────────────────────────────────┘

`EventSource` của trình duyệt **không đặt được header tuỳ chọn** — đó là chỗ
API dừng lại, không phải một thiếu sót của thư viện nào. Cả T-1.7 tới T-1.13
không chạm phải giới hạn đó vì mọi client của chúng là `curl` hoặc `httpx`;
T-1.14 là client đầu tiên **là một trình duyệt**, và §7.4 + Phụ lục F đòi đúng
`EventSource` native để `Last-Event-ID` do trình duyệt tự gửi khi reconnect.

Phụ lục F vốn đã viết sẵn `new EventSource(url, { withCredentials: true })` —
`withCredentials` nói về **cookie**, tức bản thân kế hoạch đã giả định đường
stream xác thực bằng cookie chứ không bằng header. Cookie ở đây là chỗ tạm đi
đúng hình dạng mà auth thật rồi cũng phải đi.

**Header vẫn thắng cookie, và thứ tự đó không phải tuỳ tiện.** Ba script của
Phase 1 (`test_resume.py`, `bench_ttft.py`, mọi `curl` trong DoD) gửi header;
nếu cookie thắng thì một cookie cũ còn sót trong `curl -b` hoặc trong jar của
ai đó sẽ **lặng lẽ** đổi danh tính của phép đo. Ngược lại thì không: header chỉ
có khi người gọi cố ý đặt nó.

**Cookie chỉ được đọc khi header VẮNG MẶT**, và đó là lý do nó khai kiểu `str`
chứ không `uuid.UUID`. Khai `uuid.UUID` thì FastAPI validate **cả hai** tham số
trước khi thân hàm chạy, nên một cookie hỏng (người dùng sửa tay, bản cũ của
một phiên trước) sẽ trả `422` cho cả những request mang header hoàn toàn hợp
lệ — tức làm hỏng `curl` vì một thứ `curl` không gửi.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Cookie, Header, status

from app.config.settings import settings
from app.core.errors import ApiError, ApiErrorCode

#: Tên cookie mang danh tính tạm của Phase 1. **Bản sao duy nhất của hằng này
#: nằm ở `frontend/src/lib/api.ts`** (`TEN_COOKIE_DEV`) — hai đầu của một sợi
#: dây, cùng loại với `stream:{id}` giữa producer và consumer. Đổi ở đây mà
#: quên bên kia thì FE im lặng trượt về `401`, nên cả hai chỗ đều trỏ về nhau
#: bằng chú thích.
DEV_USER_COOKIE = "scarlet_dev_user"


async def get_current_user_id(
    x_user_id: Annotated[uuid.UUID | None, Header(alias="X-User-Id")] = None,
    dev_user_cookie: Annotated[str | None, Cookie(alias=DEV_USER_COOKIE)] = None,
) -> uuid.UUID:
    """`user_id` của người gọi. **Chỗ tạm của Phase 1** — xem docstring module.

    Thứ tự: header `X-User-Id` → cookie `scarlet_dev_user`. Cookie chỉ được
    nhìn tới khi header vắng mặt.

    Raise:
        ApiError 503 `AUTH_NOT_IMPLEMENTED`: `DEBUG=false`. Auth thật chưa tồn
            tại (T-2.3), và im lặng cho qua sẽ biến mọi endpoint thành công khai.
        ApiError 401 `UNAUTHENTICATED`: không có đường nào mang danh tính tới.
        ApiError 422 `VALIDATION_ERROR`: có cookie nhưng nó không phải UUID.
            Không bỏ qua im lặng: một cookie hỏng mà bị làm ngơ sẽ hiện ra
            thành `401` ở tầng trên, và người sửa sẽ đi tìm ở nhầm chỗ.

    Ba mã đó là hợp đồng với FE (§18, B-86): T-2.3 thay thân hàm này bằng auth
    thật, và `UNAUTHENTICATED` vẫn là mã FE đọc để đẩy người dùng ra màn hình
    đăng nhập — đổi thân hàm không được đổi mã.
    """
    if not settings.DEBUG:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ApiErrorCode.AUTH_NOT_IMPLEMENTED,
            "auth chua duoc hien thuc (tasks.md T-2.3); Phase 1 chi chay voi DEBUG=true",
        )
    if x_user_id is not None:
        return x_user_id
    if dev_user_cookie is None:
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            ApiErrorCode.UNAUTHENTICATED,
            f"thieu header X-User-Id va cookie {DEV_USER_COOKIE} "
            f"(cho tam cua Phase 1, xem app/core/deps.py)",
        )
    try:
        return uuid.UUID(dev_user_cookie)
    except ValueError as loi:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ApiErrorCode.VALIDATION_ERROR,
            f"cookie {DEV_USER_COOKIE} khong phai UUID",
        ) from loi
