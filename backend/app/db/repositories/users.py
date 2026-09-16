"""Repository của bảng `users` (KH §11.1, §11.5, §20) — T-2.1.

Một luật riêng so với `conversations.py`/`messages.py`: hàm tạo user ở đây
**nuốt** xung đột UNIQUE trên `email` thay vì để nó nổ ra thành exception.
Lý do là §11.5 — "chống dò": đăng ký với email đã tồn tại phải cho ra đúng
đường đi (và đúng response) với đăng ký thành công, nên tầng gọi (router)
không được thấy hai nhánh khác nhau ở đây.
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_pending_user(self, *, email: str, password_hash: str) -> User | None:
        """Tạo user mới: `status='pending_email'`, tier mặc định (`server_default`).

        Trả `None` khi email đã tồn tại (vi phạm UNIQUE của cột CITEXT) thay
        vì raise: router cần phản hồi GIỐNG HỆT trường hợp thành công (§11.5,
        UC-01), nên một exception có tên riêng ở đây chỉ mời router viết một
        nhánh `except` mà kết quả phải giống hệt nhánh `try` — thà trả thẳng
        `None` và để router xử lý bằng một `if` duy nhất.

        Sau một `flush()` thất bại, transaction của session ở trạng thái
        aborted — `rollback()` ở đây là bắt buộc để session còn dùng lại được
        cho phần còn lại của request (đọc lại KHÔNG cần, vì router không đọc
        gì thêm ở nhánh trùng email).
        """
        user = User(email=email, password_hash=password_hash)
        self._session.add(user)
        try:
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()
            return None
        return user
