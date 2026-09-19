"""Bảng `audit_logs` (KH Phụ lục A, §16.3, §20) — T-2.16.

§20 hàng "Audit" viết đúng một câu: *"Mọi hành động admin ghi `audit_logs`"*,
và §16.3 nói màn hình đọc nó phải trả lời được bốn câu — *"ai, lúc nào, làm
gì, với ai"*. Bốn câu đó là bốn cột dưới đây (`actor_id`, `created_at`,
`action`, `target_type` + `target_id`); `details` giữ phần *"đổi từ gì sang
gì"*, thứ không câu nào trong bốn câu ấy hỏi nhưng mọi lần điều tra đều cần.

Cũng như `tier.py` và `usage_event.py`, model này không có một dòng logic nào.
Phần "hành động nào ghi ra dòng nào" sống ở `app/api/v1/admin.py`, phần câu
SQL ở `app/db/repositories/audit_logs.py`.

**Bảng này chỉ có INSERT.** Không `update_*`, không `delete_*`, và sẽ không bao
giờ có — cùng lý lẽ đã ghi cho `usage_events` (A7): một sổ mà người bị ghi sổ
sửa được thì không phải sổ. Cách rẻ nhất để giữ lời hứa đó là không viết sẵn
con dao.

**`actor_id` là `ON DELETE SET NULL`, không phải `CASCADE`** (Phụ lục A): xoá
tài khoản của một admin cũ **không** được xoá dấu vết những gì họ đã làm với
tài khoản người khác. Cùng hình dạng với `usage_events.message_id` — dòng sổ ở
lại, chỉ mất con trỏ về người.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from ipaddress import IPv4Address, IPv6Address
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import INET, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class AuditAction(StrEnum):
    """Giá trị của cột `action` — hợp đồng với màn hình "Audit log" của §16.3.

    Một `StrEnum` chứ không phải chuỗi tự do rải trong router, cùng lý lẽ với
    `ApiErrorCode`: một dòng audit chỉ có ích nếu người đọc lọc được nó, và lọc
    được nghĩa là tên của nó nằm trong một danh sách đọc hết trong một màn hình.

    Dạng `<đối tượng>.<việc>`: cột `target_type` nói đối tượng ấy là bảng nào,
    nên tiền tố ở đây trùng lặp một chút **có chủ ý** — một dòng log đọc bằng
    mắt trong `psql` (`SELECT action, target_id`) vẫn tự giải thích được mà
    không phải JOIN hay nhớ thứ tự cột.

    Ánh xạ sang `Text`, không qua `pg_enum()`: Phụ lục A khai cột này là `TEXT`
    (khác `users.status`), vì thêm một hành động admin là thêm một dòng ở đây
    chứ không phải một migration.
    """

    USER_APPROVE = "user.approve"
    USER_REJECT = "user.reject"
    USER_SUSPEND = "user.suspend"
    USER_UPDATE = "user.update"
    TIER_UPDATE = "tier.update"
    CATALOG_RELOAD = "catalog.reload"


#: Giá trị của `target_type` cho một hành động tác động lên một hàng `users`.
#: Là **tên bảng**, không phải một nhãn tự nghĩ ra: `target_id` không có khoá
#: ngoại nào (Phụ lục A khai nó là `TEXT`, vì nó phải trỏ được tới nhiều bảng),
#: nên chuỗi này là thứ duy nhất nói cho người điều tra biết phải `SELECT` ở
#: đâu với cái id ấy.
TARGET_USER = "users"

#: `target_type` cho một hành động tác động lên một hàng `tiers` (T-2.20).
#: `target_id` khi đó là **tên tier**, không phải một UUID — đúng lý do cột ấy
#: khai `TEXT` ngay từ đầu, và lý do đó nay có người dùng thật chứ không còn
#: là một dự phòng viết sẵn.
TARGET_TIER = "tiers"

#: `target_type` cho hành động không nhắm vào hàng nào — `catalog.reload` tác
#: động lên tiến trình, không lên dữ liệu. `target_id` khi đó để `NULL`.
TARGET_CATALOG = "catalog"


class AuditLog(Base):
    __tablename__ = "audit_logs"

    #: `BIGSERIAL` (Phụ lục A), khác mọi bảng khác của schema dùng
    #: `gen_random_uuid()`. Giữ nguyên chứ không "thống nhất" lại: thứ tự ghi
    #: chính là thứ tự đọc của một sổ, và một khoá tăng dần nói được điều đó
    #: mà một UUID v4 thì không.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[AuditAction] = mapped_column(Text, nullable=False)
    target_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: `TEXT` chứ không `UUID` (Phụ lục A): nó trỏ được tới hàng của nhiều bảng
    #: khác nhau, và ngày mai một trong số đó có khoá chính không phải UUID
    #: (`tiers.name` đã thế rồi) thì cột không phải đổi kiểu.
    target_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    #: `INET` — `NULL` khi không đọc được IP nào (gọi từ trong mạng nội bộ, hoặc
    #: `X-Real-IP` vắng mặt). NULL chứ không phải một chuỗi `"unknown"`: kiểu
    #: `INET` của Postgres không nhận chuỗi đó, và nhét một giá trị giả vào một
    #: cột có kiểu là cách nhanh nhất để mất luôn phép kiểm mà kiểu ấy đang làm.
    #:
    #: Kiểu Python là `IPv4Address`/`IPv6Address`, **không** phải `str`: đó là
    #: thứ asyncpg thật sự trả về khi đọc cột `INET`, và khai `str` ở đây sẽ là
    #: một lời nói dối mà mypy tin còn `assert row.ip == "1.2.3.4"` thì không.
    ip: Mapped[IPv4Address | IPv6Address | None] = mapped_column(INET, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"AuditLog(id={self.id!r}, action={self.action!r}, "
            f"actor_id={self.actor_id!r}, target_id={self.target_id!r})"
        )
