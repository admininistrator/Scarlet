"""Repository của bảng `users` (KH §11.1, §11.5, §20) — T-2.1.

Một luật riêng so với `conversations.py`/`messages.py`: hàm tạo user ở đây
**nuốt** xung đột UNIQUE trên `email` thay vì để nó nổ ra thành exception.
Lý do là §11.5 — "chống dò": đăng ký với email đã tồn tại phải cho ra đúng
đường đi (và đúng response) với đăng ký thành công, nên tầng gọi (router)
không được thấy hai nhánh khác nhau ở đây.

**T-2.16 thêm ba câu của admin panel** ở cuối file (`list_for_admin`,
`set_status`, `update_by_admin`). Chúng là nhóm duy nhất ở đây không lọc theo
danh tính người gọi — §16.3 cho admin nhìn mọi tài khoản, và cánh cửa canh
chuyện đó là `require_admin` ở tầng router, không phải một `WHERE` ở đây.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import bindparam, func, select, text, update
from sqlalchemy.dialects.postgresql import UUID as PgUUID
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

    async def has_provider_key(self, user_id: uuid.UUID) -> bool:
        """Người này đã cấu hình BYOK chưa (§10.5, §11.1) — T-2.7.

        Câu hỏi duy nhất mà `require_status` cần hỏi Postgres: bảng §11.1 cho
        `pending_approval` chat **nếu** có BYOK, và không claim nào của access
        token trả lời được điều đó (khoá có thể được thêm/xoá giữa hai lần
        phát hành token).

        **Vì sao `text()` chứ không phải một model ORM.** `user_provider_keys`
        đã có trong DB từ migration 0001 nhưng chưa có model — và dựng model ở
        đây là làm trước một phần của T-2.14 (BYOK: mã hoá và CRUD), nơi hình
        dạng thật của bảng (`key_cipher`/`key_nonce` BYTEA, `key_last4`,
        `verified_at`) mới có người dùng. Một model nửa vời hôm nay là một
        model phải viết lại ngày mai, ở đúng task sở hữu nó.

        `EXISTS` chứ không `COUNT`: câu hỏi là "có hay không", và Postgres
        dừng ngay ở hàng đầu tiên. Lọc `user_id` **trong câu SQL** (§20).

        `bindparam(..., type_=PgUUID)` chứ không để SQLAlchemy đoán: với
        `text()` nó không biết kiểu của cột, còn asyncpg thì cần biết để gửi
        `uuid` chứ không phải chuỗi.
        """
        stmt = text(
            "SELECT EXISTS (SELECT 1 FROM user_provider_keys WHERE user_id = :user_id)"
        ).bindparams(bindparam("user_id", type_=PgUUID(as_uuid=True)))
        return bool((await self._session.execute(stmt, {"user_id": user_id})).scalar_one())

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

    # ═════════════ ba câu của admin panel (§16.3, §18.5) — T-2.16 ═════════════

    async def list_for_admin(self, *, trang_thai: UserStatus | None = None) -> Sequence[User]:
        """Danh sách user cho `GET /admin/users`, mới nhất trước — §16.3.

        **Câu duy nhất của file này KHÔNG có `WHERE user_id`**, vì câu hỏi ở
        đây là "ai đang chờ duyệt" chứ không phải "của tôi có gì". Cánh cửa canh
        nó là `require_admin` ở tầng router (§16.3: *"mọi endpoint
        `/api/v1/admin/*` kiểm lại quyền phía server"*).

        `deleted_at IS NULL` **trong SQL**, cùng lối `get_by_id`: một người đã
        xoá tài khoản không quay lại màn hình duyệt để admin bấm Duyệt cho một
        tài khoản không còn tồn tại.

        Lọc `status` cũng trong SQL chứ không `[u for u in ... if ...]` ở
        Python — §20 viết luật đó cho `user_id`, nhưng lý do của nó (dữ liệu
        không rời khỏi DB nhiều hơn mức cần) không đổi khi cột đổi tên.

        **Không phân trang.** R1 chốt 15–20 người dùng; một `LIMIT/OFFSET` ở
        đây là một tham số mà không màn hình nào của §16.3 truyền vào, và mỗi
        tham số không ai dùng là một nhánh không ai kiểm. Xem Backlog cho ngày
        con số R1 đổi.
        """
        stmt = select(User).where(User.deleted_at.is_(None))
        if trang_thai is not None:
            stmt = stmt.where(User.status == trang_thai)
        return list((await self._session.execute(stmt.order_by(User.created_at.desc()))).scalars())

    async def set_status(
        self,
        user_id: uuid.UUID,
        *,
        tu: UserStatus,
        sang: UserStatus,
        approved_by: uuid.UUID | None = None,
    ) -> User | None:
        """Đổi trạng thái tài khoản, **có điều kiện trên trạng thái cũ** — §11.1.

        `WHERE status = :tu` cùng lý lẽ với `mark_email_verified` ngay trên:
        phép chuyển trạng thái nằm **trong** câu UPDATE chứ không phải một
        `if` chạy trước nó. Hai admin cùng mở màn duyệt, một người bấm Duyệt và
        một người bấm Từ chối trong cùng một giây thì chỉ một câu thắng — câu
        kia trả `None` và router nói "trạng thái đã đổi, tải lại đi" thay vì
        ghi đè kết quả của đồng nghiệp mà không ai biết.

        `approved_at`/`approved_by` chỉ ghi khi chỗ gọi truyền `approved_by`,
        tức chỉ ở nhánh duyệt: hai cột ấy trả lời *"ai đã nhận người này vào"*,
        và ghi chúng cho một lần từ chối là làm hỏng câu trả lời đó.

        `func.now()` (mốc mở transaction) chứ không `clock_timestamp()`, cùng
        lý do đã ghi ở `dat_mat_khau_moi`: không ai so cột này với thời gian
        thực để quyết định điều gì.
        """
        gia_tri: dict[str, Any] = {"status": sang}
        if approved_by is not None:
            gia_tri["approved_at"] = func.now()
            gia_tri["approved_by"] = approved_by
        stmt = (
            update(User)
            .where(User.id == user_id, User.deleted_at.is_(None), User.status == tu)
            .values(**gia_tri)
            .returning(User)
            .execution_options(synchronize_session="fetch")
        )
        return (await self._session.execute(stmt)).scalars().one_or_none()

    async def update_by_admin(self, user_id: uuid.UUID, *, thay_doi: dict[str, Any]) -> User | None:
        """Đổi `tier_name` / `limit_override_json` cho một user — §10.4, §16.3.

        Hai cột, không hơn: §10.4 nói *"đổi tier"* là sửa `users.tier_name`, và
        *"ghi đè hạn mức"* là sửa `users.limit_override_json` — trong đó có cả
        `can_execute_skills` mà §16.3 gọi tên riêng. `status` **không** đi qua
        đây; nó có ba endpoint riêng vì mỗi lần đổi nó là một sự kiện phải ghi
        sổ với một cái tên (`set_status` ở trên).

        **Không có bước gỡ cache.** `app/quota/tiers.py` cố ý không có
        `invalidate()`: TTL 60 s là luật duy nhất và nó chạy kể cả khi không ai
        nhớ tới nó (§10.4 — "có hiệu lực ≤ 60 s", AC của UC-07).

        `thay_doi` rỗng thì **không** chạy câu UPDATE nào — nhưng vẫn trả về
        hàng hiện tại, để `PATCH` với body rỗng cư xử như `GET` (cùng lối
        `update_conversation`).
        """
        if not thay_doi:
            return await self.get_by_id(user_id)
        stmt = (
            update(User)
            .where(User.id == user_id, User.deleted_at.is_(None))
            .values(**thay_doi)
            .returning(User)
            .execution_options(synchronize_session="fetch")
        )
        return (await self._session.execute(stmt)).scalars().one_or_none()
