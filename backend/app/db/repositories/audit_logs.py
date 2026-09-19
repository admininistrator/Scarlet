"""Repository của sổ `audit_logs` (§20 hàng "Audit", §16.3) — T-2.16.

**Một hàm ghi, không có hàm nào khác.** Cố ý, và cùng lý lẽ đã ghi cho
`usage_events`: bảng này là append-only, nên không có `update_*`/`delete_*` và
sẽ không bao giờ có. Đường **đọc** (`GET /admin/audit-logs` của §18.5) chưa có
task nào nhận — không dựng sẵn một hàm chết.

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
from ipaddress import IPv4Address, IPv6Address
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditAction, AuditLog


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
