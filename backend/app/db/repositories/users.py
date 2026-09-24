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
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Numeric, bindparam, cast, func, select, text, update
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Conversation,
    KeySource,
    UsageEvent,
    User,
    UserRole,
    UserStatus,
)


@dataclass(frozen=True, slots=True)
class AdminUserRow:
    """Một hàng của bảng "Người dùng" (§16.3) — hàng `users` + hai cột NQ-66."""

    user: User
    #: Số hội thoại chưa xoá mềm. `0` khi chưa có — không bao giờ `None`.
    conversation_count: int
    #: `SUM(cost_usd)` của tiền hệ thống trong cửa sổ quota dài. `0.000000`
    #: khi chưa tiêu — không bao giờ `None`.
    spend_7d_usd: Decimal


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

    async def set_new_password(self, user_id: uuid.UUID, password_hash: str) -> bool:
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

    # ═════════════ cài đặt cá nhân (§18.4) — T-3.0 ═════════════

    async def set_profile(
        self, user_id: uuid.UUID, *, display_name: str | None, default_model: str | None
    ) -> bool:
        """Ghi hai cột cài đặt của `users` cho CHÍNH người gọi (§18.4) — T-3.0, T-S.5.

        `default_model` (B-206, T-3.0) và `display_name` (NQ-116, T-S.5) — hai
        trường của `PUT /settings` sống trên hàng `users`; phần còn lại ở
        `user_settings.prefs_json` (`UserSettingsRepository`).

        Nhận `None` và ghi `None` thật: "bỏ chọn, dùng lại mặc định của
        catalog" và "bỏ tên, hiện nguyên email" là những ý định có thật của
        người dùng, nên chúng phải đi được qua hàm này. Đó cũng là lý do tham số
        không có giá trị mặc định — bỏ quên một trường phải là lỗi cú pháp,
        không phải một lần xoá âm thầm.

        **Không** kiểm `default_model` có trong catalog, không cắt khoảng trắng
        của `display_name`: đó là việc của tầng router
        (`api/v1/settings.py::put_settings`), nơi có `ApiError` để nói với
        người dùng. Repository nói chuyện với Postgres, không với người.

        `deleted_at IS NULL` **trong câu SQL** (§20, cùng lối `get_by_id` và
        `set_new_password`): một access token còn hạn của tài khoản vừa xoá
        không được phép ghi tiếp vào hàng đó.

        Trả `False` khi không có hàng nào khớp — router quyết định câu trả lời,
        y như `mark_email_verified`.
        """
        stmt = (
            update(User)
            .where(User.id == user_id, User.deleted_at.is_(None))
            .values(display_name=display_name, default_model=default_model)
            .returning(User.id)
            .execution_options(synchronize_session=False)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    async def record_login(self, user_id: uuid.UUID) -> datetime | None:
        """Đóng dấu `users.last_login_at = now()` sau một lần đăng nhập thành công — T-S.5.

        Cột có từ Phụ lục A mà tới T-S.5 chưa ai ghi (admin đọc ra luôn
        `null`). S10/NQ-114 dùng nó để nhận ra "một lần đăng nhập": thanh
        quota chạy từ 0 khi giá trị này **đổi**. Vì vậy chỉ `POST /auth/login`
        gọi hàm này — `refresh` xoay token chứ không phải đăng nhập lại, và
        ghi ở đó thì F5 sau 15 phút cũng chạy lại hoạt ảnh.

        Đồng hồ của Postgres chứ không đồng hồ Python — cùng máy với
        `created_at` của chính hàng này. `clock_timestamp()` chứ không `now()`,
        cùng lý do migration 0002: `now()` là mốc **mở transaction**, nên hai
        lần đăng nhập trong cùng một transaction (đúng hình dạng của bộ test,
        NQ-17) mang cùng một giá trị và "đã đổi chưa" trả lời sai. Trả giá trị
        vừa ghi (`RETURNING`) để response của `login` mang đúng nó mà không
        phải đọc lại; `None` khi không hàng nào khớp.
        """
        stmt = (
            update(User)
            .where(User.id == user_id, User.deleted_at.is_(None))
            .values(last_login_at=func.clock_timestamp())
            .returning(User.last_login_at)
            .execution_options(synchronize_session=False)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    # ═════════════ ba câu của admin panel (§16.3, §18.5) — T-2.16 ═════════════

    async def list_for_admin(
        self, *, spend_since: datetime, status: UserStatus | None = None
    ) -> Sequence[AdminUserRow]:
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

        **Không phân trang** (B-175, chốt ở T-3.12): R1 chốt 15–20 người dùng,
        và một `LIMIT/OFFSET` mà không màn hình nào truyền vào là một nhánh
        không ai kiểm. `GET /admin/usage` thì khác — xem `admin_usage`.

        ╔══════════════════════════════════════════════════════════════════╗
        ║  NQ-66: HAI CỘT MỚI ĐI BẰNG **MỘT** CÂU, KHÔNG N+1                ║
        ╚══════════════════════════════════════════════════════════════════╝

        Bảng "Người dùng" có hai cột mà hàng `users` không có: *số hội thoại*
        và *chi tiêu 7 ngày*. Cả hai đến từ **hai subquery gom nhóm** được
        `LEFT JOIN` vào đúng câu `SELECT` này — Postgres nhận MỘT câu lệnh,
        dù có bao nhiêu người. Hai ngả đã loại (B-176): FE ghép hai response
        (và vẫn thiếu một câu đếm hội thoại), hoặc một vòng lặp gọi thêm hai
        câu cho mỗi người.

        `LEFT JOIN` + `COALESCE`: người chưa có hội thoại (hay chưa tiêu gì)
        vẫn ở trong danh sách và cột của họ là `0`, **không** `NULL` — một ô
        trống đọc như "không đo được", còn sự thật là "chưa dùng".

        *Chi tiêu 7 ngày* là `SUM(cost_usd)` của `key_source='system'` từ
        `spend_since` — **đúng tập** mà quota 7 ngày của người đó cộng
        (`UsageEventRepository.list_since`, §10.5): con số admin đọc ở đây là
        con số đang đẩy thanh quota của người ấy, không phải một con số thứ
        hai tính khác đi. `spend_since` do router truyền (A3: độ dài cửa sổ là
        `QUOTA_WINDOW_LONG_S`, không phải một hằng ở đây).

        `CAST(... AS NUMERIC(12,6))` cho ra đủ sáu chữ số thập phân kể cả khi
        tổng là `0` — cùng kiểu cột `cost_usd`, nên cột tiền trên màn hình
        thẳng hàng dấu chấm (T-HD7) mà FE không phải định dạng lại số tiền.

        Hội thoại đã xoá mềm **không** đếm: người dùng đã bỏ nó, và §8 coi nó
        như không còn trong mọi truy vấn mặc định.
        """
        conversation_counts = (
            select(Conversation.user_id, func.count().label("n"))
            .where(Conversation.deleted_at.is_(None))
            .group_by(Conversation.user_id)
            .subquery()
        )
        spend = (
            select(UsageEvent.user_id, func.sum(UsageEvent.cost_usd).label("usd"))
            .where(
                UsageEvent.created_at >= spend_since,
                UsageEvent.key_source == KeySource.SYSTEM,
            )
            .group_by(UsageEvent.user_id)
            .subquery()
        )
        stmt = (
            select(
                User,
                func.coalesce(conversation_counts.c.n, 0),
                cast(func.coalesce(spend.c.usd, 0), Numeric(12, 6)),
            )
            .outerjoin(conversation_counts, conversation_counts.c.user_id == User.id)
            .outerjoin(spend, spend.c.user_id == User.id)
            .where(User.deleted_at.is_(None))
        )
        if status is not None:
            stmt = stmt.where(User.status == status)
        rows = (await self._session.execute(stmt.order_by(User.created_at.desc()))).all()
        return [
            AdminUserRow(user=row[0], conversation_count=int(row[1]), spend_7d_usd=row[2])
            for row in rows
        ]

    async def set_status(
        self,
        user_id: uuid.UUID,
        *,
        from_status: UserStatus,
        to_status: UserStatus,
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
        lý do đã ghi ở `set_new_password`: không ai so cột này với thời gian
        thực để quyết định điều gì.
        """
        value: dict[str, Any] = {"status": to_status}
        if approved_by is not None:
            value["approved_at"] = func.now()
            value["approved_by"] = approved_by
        stmt = (
            update(User)
            .where(User.id == user_id, User.deleted_at.is_(None), User.status == from_status)
            .values(**value)
            .returning(User)
            .execution_options(synchronize_session="fetch")
        )
        return (await self._session.execute(stmt)).scalars().one_or_none()

    async def update_by_admin(self, user_id: uuid.UUID, *, changes: dict[str, Any]) -> User | None:
        """Đổi `tier_name` / `limit_override_json` cho một user — §10.4, §16.3.

        Hai cột, không hơn: §10.4 nói *"đổi tier"* là sửa `users.tier_name`, và
        *"ghi đè hạn mức"* là sửa `users.limit_override_json` — trong đó có cả
        `can_execute_skills` mà §16.3 gọi tên riêng. `status` **không** đi qua
        đây; nó có ba endpoint riêng vì mỗi lần đổi nó là một sự kiện phải ghi
        sổ với một cái tên (`set_status` ở trên).

        **Không có bước gỡ cache.** `app/quota/tiers.py` cố ý không có
        `invalidate()`: TTL 60 s là luật duy nhất và nó chạy kể cả khi không ai
        nhớ tới nó (§10.4 — "có hiệu lực ≤ 60 s", AC của UC-07).

        `changes` rỗng thì **không** chạy câu UPDATE nào — nhưng vẫn trả về
        hàng hiện tại, để `PATCH` với body rỗng cư xử như `GET` (cùng lối
        `update_conversation`).
        """
        if not changes:
            return await self.get_by_id(user_id)
        stmt = (
            update(User)
            .where(User.id == user_id, User.deleted_at.is_(None))
            .values(**changes)
            .returning(User)
            .execution_options(synchronize_session="fetch")
        )
        return (await self._session.execute(stmt)).scalars().one_or_none()

    # ═════════════ người nhận thư cảnh báo chi tiêu (RR-1) — T-2.17 ═════════════

    async def list_admins(self) -> Sequence[User]:
        """Những ai nhận thư cảnh báo chi tiêu — `role='admin'`, chưa xoá tài khoản.

        Đọc từ **bảng `users`** chứ không từ một biến `.env` kiểu `ALERT_TO`:
        R7 chốt *"một admin, không RBAC"*, và người ấy đã có một hàng trong
        bảng này với đúng một cột nói lên điều đó. Một biến môi trường song
        song là chỗ thứ hai để trả lời cùng một câu hỏi, và chỗ thứ hai luôn là
        chỗ lệch — admin đổi email trong app xong vẫn không nhận được thư.

        **Không** lọc `status`. Một admin đang `suspended` vẫn là người trả hoá
        đơn, và cảnh báo ngân sách là thứ cuối cùng nên im lặng vì một trạng
        thái tài khoản; `deleted_at IS NULL` thì có lọc, vì gửi thư cho một
        địa chỉ đã yêu cầu xoá là chuyện khác hẳn (§20 "Quyền riêng tư").

        `ORDER BY created_at` để thứ tự người nhận ổn định giữa hai lần chạy —
        thứ duy nhất đọc nó là log, và một danh sách đảo thứ tự mỗi giờ làm
        `diff` hai dòng log thành vô nghĩa.
        """
        stmt = (
            select(User)
            .where(User.role == UserRole.ADMIN, User.deleted_at.is_(None))
            .order_by(User.created_at)
        )
        return list((await self._session.execute(stmt)).scalars())
