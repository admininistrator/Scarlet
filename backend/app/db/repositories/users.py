"""Repository của bảng `users` (KH §11.1, §11.5, §20) — T-2.1.

Một luật riêng so với `conversations.py`/`messages.py`: hàm tạo user ở đây
**nuốt** xung đột UNIQUE trên `email` thay vì để nó nổ ra thành exception.
Lý do là §11.5 — "chống dò": đăng ký với email đã tồn tại phải cho ra đúng
đường đi (và đúng response) với đăng ký thành công, nên tầng gọi (router)
không được thấy hai nhánh khác nhau ở đây.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, UserStatus


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

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        """Tra một user theo id — dùng bởi `GET /auth/me` và `/auth/refresh` (T-2.3).

        `deleted_at IS NULL` trong SQL (§20): một user vừa xoá tài khoản không
        được phép tiếp tục đọc chính thông tin của mình qua một token còn hạn.
        """
        stmt = select(User).where(User.id == user_id, User.deleted_at.is_(None))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        """Tra một user theo email (CITEXT — so sánh không phân biệt hoa/thường).

        Dùng bởi `resend-verification` (T-2.2): router giữ nguyên §11.5 —
        không rẽ nhánh theo kết quả hàm này ra ngoài response, chỉ dùng nó để
        biết có phát hành token mới hay không (tác dụng phụ nội bộ, không lộ
        ra ngoài).
        """
        stmt = select(User).where(User.email == email, User.deleted_at.is_(None))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def dat_mat_khau_moi(self, user_id: uuid.UUID, password_hash: str) -> bool:
        """Ghi hash mật khẩu mới + `password_changed_at` (§11.3, T-2.5).

        `deleted_at IS NULL` **trong câu SQL** (§20, cùng lối `get_by_id`): một
        token reset còn hạn của tài khoản vừa xoá không được phép hồi sinh nó.

        `password_changed_at` cập nhật **cùng một câu UPDATE**, không phải một
        lượt ghi thứ hai: hai câu lệnh là hai cơ hội để một trong hai trượt, và
        một mật khẩu đã đổi mà cột mốc thì chưa là thứ không ai phát hiện được
        cho tới lúc cần điều tra.

        `func.now()` (mốc mở transaction) chứ không `clock_timestamp()`: khác
        `heartbeat_at` của NQ-18, không ai so cột này với thời gian thực để
        quyết định điều gì, và đây cũng chính là hàm mà `server_default` của
        cột đang dùng — hai nguồn ghi vào một cột nên đi cùng một đồng hồ.

        Trả `False` khi không có hàng nào khớp (user đã xoá) — không raise:
        router quyết định câu trả lời, y như `mark_email_verified`.
        """
        stmt = (
            update(User)
            .where(User.id == user_id, User.deleted_at.is_(None))
            .values(password_hash=password_hash, password_changed_at=func.now())
            .returning(User.id)
            .execution_options(synchronize_session=False)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    async def mark_email_verified(self, user_id: uuid.UUID) -> bool:
        """`pending_email` → `pending_approval` (§11.1, UC-01), T-2.2.

        `WHERE status = 'pending_email'` cùng lý lẽ với `mark_streaming` của
        `repositories/messages.py`: một token verify dùng ĐÚNG một lần cho một
        đổi trạng thái, nên chuyển có điều kiện ngay trong câu UPDATE thay vì
        đọc rồi ghi — hai request `verify-email` chạy đua (link bấm hai tab)
        thì chỉ một cái thắng, cái kia trả `False` chứ không ghi đè lần hai.
        Trả `False` không phải lỗi: `EmailTokenRepository.consume` đã tự lo
        idempotent ở lớp trên, hàm này chỉ là "đổi status nếu còn đúng chỗ".
        """
        stmt = (
            update(User)
            .where(User.id == user_id, User.status == UserStatus.PENDING_EMAIL)
            .values(status=UserStatus.PENDING_APPROVAL, email_verified_at=func.now())
            .returning(User.id)
            .execution_options(synchronize_session=False)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None
