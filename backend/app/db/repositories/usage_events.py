"""Repository của sổ cái `usage_events` (§10.2 vế SAU, A7) — T-2.12.

Một hàm ghi, một hàm cộng. Cố ý ít: bảng này là **append-only** — không có
`update_*`, không có `delete_*`, và sẽ không bao giờ có. A7 nói lịch sử chi phí
không đổi, mà cách rẻ nhất để giữ lời hứa đó là không viết sẵn con dao.

`sum_since` chưa có người gọi trong T-2.12; nó là nửa đọc mà **T-2.13**
(`rebuild_quota`, §10.3) và **T-2.17** (cảnh báo chi tiêu, RR-1) cùng cần, và
nó nằm ở đây thay vì ở `quota/` vì §20 bắt mọi câu SQL sống trong tầng này —
nhất là câu có `WHERE user_id`, thứ phải đọc được bằng mắt trong vài phút.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CostConfidence, KeySource, UsageEvent


class UsageEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        user_id: uuid.UUID,
        message_id: uuid.UUID | None,
        model_id: str,
        provider: str,
        key_source: KeySource,
        prompt_tokens: int,
        completion_tokens: int,
        cached_tokens: int,
        cost_usd: Decimal,
        cost_confidence: CostConfidence,
        price_snapshot: dict[str, Any],
        upstream_model_reported: str | None = None,
    ) -> UsageEvent:
        """Ghi MỘT dòng sổ và trả về nó (đã có `id` do Postgres sinh).

        Trả về cả hàng chứ không chỉ `id` vì chỗ gọi cần hai thứ từ nó: `id` để
        làm member của ZSET (`quota/windows.py::encode_member`) và `created_at`
        để dòng log nói được lượt sinh này được ghi sổ lúc nào.

        `flush()` chứ không `commit()`: quyết định chốt giao dịch thuộc về chỗ
        gọi, đúng lối mọi repository khác của thư mục này. `Base` khai
        `eager_defaults=True` nên `flush` đã kéo về `id`/`created_at` bằng
        `RETURNING` — không có lazy-load nào rình `MissingGreenlet` phía sau.

        **Không có tham số `cost_usd` mặc định.** Mọi cột đều bắt buộc, kể cả
        những cột DDL có `DEFAULT`: một dòng sổ thiếu giá là một dòng sổ sai,
        và `DEFAULT 0` của Phụ lục A là lưới cho câu `INSERT` viết tay trong
        `psql`, không phải cho đường ghi của app.
        """
        event = UsageEvent(
            user_id=user_id,
            message_id=message_id,
            model_id=model_id,
            provider=provider,
            key_source=key_source,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            cost_usd=cost_usd,
            cost_confidence=cost_confidence,
            price_snapshot=price_snapshot,
            upstream_model_reported=upstream_model_reported,
        )
        self._session.add(event)
        await self._session.flush()
        return event

    async def sum_since(self, *, user_id: uuid.UUID, since: datetime) -> Decimal:
        """`SUM(cost_usd)` của một người kể từ `since` — §10.3 ("Postgres là sự thật").

        Lọc `user_id` **trong câu SQL**, không phải bằng một vòng `if` ở Python
        (§20). Đi đúng index `ix_usage_user_time` (`user_id, created_at DESC`)
        mà Phụ lục A dựng sẵn cho việc này.

        `COALESCE` vì `SUM` trên tập rỗng trả `NULL`, và một người chưa chat
        lần nào phải ra `0` chứ không phải `None` — chỗ gọi sẽ cộng con số này
        vào một `Decimal`, và `None` ở đó là một `TypeError` giữa đường tính
        hạn mức.
        """
        stmt = select(func.coalesce(func.sum(UsageEvent.cost_usd), 0)).where(
            UsageEvent.user_id == user_id,
            UsageEvent.created_at >= since,
        )
        return Decimal(str((await self._session.execute(stmt)).scalar_one()))
