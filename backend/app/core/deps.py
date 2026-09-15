"""Dependency dùng chung của tầng HTTP (§23 `core/deps.py`).

KH tham chiếu: §18.1, §20 · CLAUDE.md A10 · tasks.md T-2.3.

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
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Header, status

from app.config.settings import settings
from app.core.errors import ApiError, ApiErrorCode


async def get_current_user_id(
    x_user_id: Annotated[uuid.UUID | None, Header(alias="X-User-Id")] = None,
) -> uuid.UUID:
    """`user_id` của người gọi. **Chỗ tạm của Phase 1** — xem docstring module.

    Raise:
        ApiError 503 `AUTH_NOT_IMPLEMENTED`: `DEBUG=false`. Auth thật chưa tồn
            tại (T-2.3), và im lặng cho qua sẽ biến mọi endpoint thành công khai.
        ApiError 401 `UNAUTHENTICATED`: thiếu header `X-User-Id`.

    Hai mã đó là hợp đồng với FE (§18, B-86): T-2.3 thay thân hàm này bằng auth
    thật, và `UNAUTHENTICATED` vẫn là mã FE đọc để đẩy người dùng ra màn hình
    đăng nhập — đổi thân hàm không được đổi mã.
    """
    if not settings.DEBUG:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ApiErrorCode.AUTH_NOT_IMPLEMENTED,
            "auth chua duoc hien thuc (tasks.md T-2.3); Phase 1 chi chay voi DEBUG=true",
        )
    if x_user_id is None:
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            ApiErrorCode.UNAUTHENTICATED,
            "thieu header X-User-Id (cho tam cua Phase 1, xem app/core/deps.py)",
        )
    return x_user_id
