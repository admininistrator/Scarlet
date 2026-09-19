"""Repository của sổ `audit_logs` (§20 hàng "Audit", §16.3) — T-2.16.

**Một hàm ghi, một hàm đọc, không có hàm nào khác.** Cố ý, và cùng lý lẽ đã
ghi cho `usage_events`: bảng này là append-only, nên không có
`update_*`/`delete_*` và sẽ không bao giờ có. T-2.20 thêm đúng nửa **đọc**
(`list_page`, cho `GET /admin/audit-logs` của §18.5) — trước đó muốn xem sổ
phải mở `psql`, tức một sổ đầy đủ mà không ai đọc.

**Lọc và phân trang nằm TRONG câu SQL**, không ở tầng Python (§20, và luật
"lọc trong câu SQL" của CLAUDE.md). Ở đây nó còn là một tính chất về quy mô
chứ không chỉ một quy ước: sổ audit là bảng duy nhất của schema chỉ lớn lên,
không bao giờ nhỏ đi, nên một `?action=` sàng sau khi `SELECT` đã đọc cả bảng
sẽ chạy đúng một năm rồi mới bắt đầu chậm.

**`flush()` chứ không `commit()`**, đúng lối mọi repository khác của thư mục
này: quyết định chốt giao dịch thuộc về chỗ gọi. Ở đây nó còn là một tính chất
chứ không chỉ một quy ước — `app/api/v1/admin.py` ghi dòng audit **trong cùng
transaction** với chính thay đổi mà nó mô tả, nên hai thứ cùng sống hoặc cùng
chết. Ngả ngược lại có hai khe, cả hai đều tệ theo cách riêng: audit commit
trước ⇒ sổ ghi một việc chưa từng xảy ra; audit commit sau ⇒ một tài khoản bị
khoá mà không ai biết ai khoá.
"""

from __future__ import annotations

import ipaddress
import uuid
from collections.abc import Sequence
from datetime import datetime
from ipaddress import IPv4Address, IPv6Address
from typing import Any, NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditAction, AuditLog, User


class AuditLogRow(NamedTuple):
    """Một dòng sổ kèm email của người đã làm việc ấy.

    §16.3 đòi màn hình trả lời được *"ai, lúc nào, làm gì, với ai"*, và cột
    `actor_id` một mình chỉ trả lời được ba phần tư: một UUID không nói ai là
    ai. Email đến từ **một câu JOIN**, không phải một vòng lặp tra từng id ở
    tầng trên — cùng quyết định NQ-66 đã chốt cho cột "số hội thoại" của bảng
    Người dùng, và cùng lý do: một trang 50 dòng không được biến thành 51 lượt
    đi Postgres.

    `email` là `None` khi `actor_id` là `None` (hành động của cron, xem
    `record`) **hoặc** khi tài khoản ấy đã bị xoá — `ON DELETE SET NULL` giữ
    dòng sổ ở lại và chỉ bỏ con trỏ về người, nên hai ca ấy trông giống nhau
    từ đây và cả hai đều là câu trả lời đúng: *"không còn biết là ai"*.
    """

    log: AuditLog
    email: str | None


def _ip_hop_le(ip: str | None) -> IPv4Address | IPv6Address | None:
    """Địa chỉ dùng được cho cột `INET`, hoặc `None`.

    `core/ratelimit.py::dia_chi_ip` trả về `"unknown"` khi không đọc được IP
    nào — một giá trị hoàn toàn hợp lý cho một khoá Redis và hoàn toàn sai cho
    một cột `INET`: Postgres từ chối nó, và một `INSERT` audit hỏng sẽ kéo theo
    cả hành động admin mà nó đang ghi (xem docstring module). Lọc ở đây chứ
    không ở router vì đây là chỗ biết cột có kiểu gì.

    Trả về **object đã phân tích** chứ không phải chuỗi gốc: đó đúng là thứ
    asyncpg trả về khi đọc lại cột này, nên ghi và đọc cùng một kiểu — không có
    chỗ nào cho một `str` đi vào rồi một `IPv4Address` đi ra mà không ai khai.
    """
    if not ip:
        return None
    try:
        return ipaddress.ip_address(ip)
    except ValueError:
        return None


class AuditLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        actor_id: uuid.UUID | None,
        action: AuditAction,
        target_type: str | None = None,
        target_id: str | None = None,
        details: dict[str, Any] | None = None,
        ip: str | None = None,
    ) -> AuditLog:
        """Ghi MỘT dòng sổ và trả về nó (đã có `id`/`created_at` do Postgres sinh).

        `actor_id` khai `| None` dù mọi chỗ gọi hôm nay đều có một admin thật:
        cột là nullable (`ON DELETE SET NULL`, Phụ lục A), và ngày có một hành
        động do cron sinh ra (§11.1 "quá hạn 7 ngày, cron dọn") thì nó không có
        người nào để ghi tên.
        """
        row = AuditLog(
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details,
            ip=_ip_hop_le(ip),
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_page(
        self,
        *,
        limit: int,
        before_id: int | None = None,
        actor_id: uuid.UUID | None = None,
        action: AuditAction | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> Sequence[AuditLogRow]:
        """Một trang của sổ, mới nhất trước — `GET /admin/audit-logs` (§16.3).

        **Con trỏ là `id`, không phải `created_at`.** `GET /conversations` phân
        trang bằng thời gian vì thứ tự của nó do người dùng làm đổi (mỗi lượt
        chat đẩy một hội thoại lên đầu) và vì `updated_at` ở đó là cột được
        `ORDER BY`. Ở đây thì khác hẳn: `id` là `BIGSERIAL`, tức đã là thứ tự
        ghi, **duy nhất**, và không bao giờ đổi. Dùng `created_at` thay vào sẽ
        mở đúng cái khe mà một khoá không duy nhất luôn mở: hai dòng ghi trong
        cùng một transaction mang **cùng một** `now()`, nên `< cursor` bỏ mất
        dòng thứ hai còn `<= cursor` lặp lại dòng thứ nhất.

        `limit` **không có giá trị mặc định** — hạn mức là cấu hình, không phải
        hằng số trong `.py` (A3). Cùng luật `list_conversations`.

        `[since, until)` nửa mở: hai trang liền nhau chia theo ngày không đếm
        hai lần dòng nằm đúng ở mốc giao.
        """
        stmt = (
            select(AuditLog, User.email)
            .select_from(AuditLog)
            .outerjoin(User, User.id == AuditLog.actor_id)
            .order_by(AuditLog.id.desc())
            .limit(limit)
        )
        if before_id is not None:
            stmt = stmt.where(AuditLog.id < before_id)
        if actor_id is not None:
            stmt = stmt.where(AuditLog.actor_id == actor_id)
        if action is not None:
            stmt = stmt.where(AuditLog.action == action)
        if since is not None:
            stmt = stmt.where(AuditLog.created_at >= since)
        if until is not None:
            stmt = stmt.where(AuditLog.created_at < until)

        rows = (await self._session.execute(stmt)).all()
        return [AuditLogRow(log=row[0], email=row[1]) for row in rows]
