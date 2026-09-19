"""Repository của sổ cái `usage_events` (§10.2 vế SAU, A7) — T-2.12.

Một hàm ghi, một hàm cộng. Cố ý ít: bảng này là **append-only** — không có
`update_*`, không có `delete_*`, và sẽ không bao giờ có. A7 nói lịch sử chi phí
không đổi, mà cách rẻ nhất để giữ lời hứa đó là không viết sẵn con dao.

`sum_since` chưa có người gọi trong T-2.12; nó là nửa đọc mà **T-2.13**
(`rebuild_quota`, §10.3) và **T-2.17** (cảnh báo chi tiêu, RR-1) cùng cần, và
nó nằm ở đây thay vì ở `quota/` vì §20 bắt mọi câu SQL sống trong tầng này —
nhất là câu có `WHERE user_id`, thứ phải đọc được bằng mắt trong vài phút.

**T-2.13 thêm ba câu đọc, và KHÔNG dùng `sum_since`.** Một tổng không dựng lại
được ZSET: §10.3 đặt `score` là epoch của **từng** dòng sổ, nên bản dựng lại
phải biết mỗi khoản tiền ra đời lúc nào — một con số gộp chỉ nói được "tổng
bằng nhau", mà bất biến T-2.12 đo là mạnh hơn thế (*số member bằng số dòng
sổ*). `sum_since` vì vậy vẫn chờ T-2.17; ba hàm mới ở dưới là phần T-2.13 cần:
`list_since` (dựng lại), `has_events_since` (phát hiện lệch, §10.3), và
`user_ids_since` (lệnh CLI `--all`).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CostConfidence, KeySource, UsageEvent


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """Ba cột của một dòng sổ mà `rebuild_quota` cần — không hơn (T-2.13).

    Ba, chứ không phải cả hàng `UsageEvent`: bản dựng lại đọc tới **10k dòng**
    (DoD dòng 3) và mỗi hàng ORM đầy đủ kéo theo `price_snapshot` — một JSONB
    vài trăm byte mà không ai ở đường này đọc. Ba cột là đúng ba thứ một member
    ZSET cần: `id` và `cost_usd` để `encode_member`, `created_at` để làm
    `score`.
    """

    id: uuid.UUID
    cost_usd: Decimal
    created_at: datetime


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

    async def list_since(self, *, user_id: uuid.UUID, since: datetime) -> Sequence[LedgerEntry]:
        """Mọi dòng sổ của một người kể từ `since`, cũ nhất trước — T-2.13, §10.3.

        Đây là vế "Postgres là sự thật" của §10.3 ở dạng đọc được: mỗi hàng trả
        về đây sẽ thành **đúng một** member trong ZSET, nên câu này và
        `read_window` phải lọc **cùng một biên**. `>=` chứ không `>`, khớp đúng
        `ZRANGEBYSCORE cutoff +inf` của `quota/windows.py` — lệch một dấu bằng
        ở đây là một khoản tiền biến mất mỗi lần dựng lại.

        `ORDER BY created_at` (cũ nhất trước) không phải để đẹp: chỗ gọi nạp
        theo lô, và một lô bị ngắt giữa chừng khi ấy để lại **phần cũ** trong
        Redis — tức phần sắp rơi khỏi cửa sổ, chỗ mất mát rẻ nhất.

        Lọc `user_id` **trong câu SQL** (§20), đi đúng index `ix_usage_user_time`.
        """
        stmt = (
            select(UsageEvent.id, UsageEvent.cost_usd, UsageEvent.created_at)
            .where(UsageEvent.user_id == user_id, UsageEvent.created_at >= since)
            .order_by(UsageEvent.created_at)
        )
        rows = (await self._session.execute(stmt)).all()
        return [LedgerEntry(id=r.id, cost_usd=r.cost_usd, created_at=r.created_at) for r in rows]

    async def has_events_since(self, *, user_id: uuid.UUID, since: datetime) -> bool:
        """Người này có dòng sổ nào trong cửa sổ không? — cửa vào của việc dựng lại.

        `LIMIT 1` chứ không `count(*)`: câu hỏi là "có hay không", và nó chạy
        trên **mỗi** request có cửa sổ rỗng — tức mọi request của một người vừa
        nghỉ hơn 5 giờ. Một `count(*)` ở đó đọc cả cửa sổ để trả lời một câu hỏi
        nhị phân.

        Tách khỏi `list_since` thay vì `len(await list_since(...)) > 0` vì hai
        câu có hai cái giá khác hẳn nhau, và chỗ gọi hỏi câu rẻ **trước** để
        không phải trả giá câu đắt trong ca thường (ZSET rỗng vì người ta thật
        sự chưa tiêu gì).
        """
        stmt = (
            select(UsageEvent.id)
            .where(UsageEvent.user_id == user_id, UsageEvent.created_at >= since)
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    async def user_ids_since(self, *, since: datetime) -> Sequence[uuid.UUID]:
        """Những ai có chi tiêu trong cửa sổ — tập người mà `--all` phải dựng lại.

        **Không** phải `SELECT id FROM users`: một người không có dòng sổ nào
        trong cửa sổ thì ZSET của họ đúng ra phải **rỗng**, nên dựng lại cho họ
        là hai câu truy vấn để không ghi gì. Tập đúng là tập người có tiền
        trong cửa sổ, và nó đọc thẳng từ chính bảng sẽ được dựng lại.
        """
        stmt = select(UsageEvent.user_id).where(UsageEvent.created_at >= since).distinct()
        return list((await self._session.execute(stmt)).scalars().all())
