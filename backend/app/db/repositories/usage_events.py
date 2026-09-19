"""Repository của sổ cái `usage_events` (§10.2 vế SAU, A7) — T-2.12.

Một hàm ghi, một hàm cộng. Cố ý ít: bảng này là **append-only** — không có
`update_*`, không có `delete_*`, và sẽ không bao giờ có. A7 nói lịch sử chi phí
không đổi, mà cách rẻ nhất để giữ lời hứa đó là không viết sẵn con dao.

`sum_since` chưa có người gọi trong T-2.12; nó là nửa đọc mà **T-2.13**
(`rebuild_quota`, §10.3) và **T-2.17** (cảnh báo chi tiêu, RR-1) cùng cần, và
nó nằm ở đây thay vì ở `quota/` vì §20 bắt mọi câu SQL sống trong tầng này —
nhất là câu có `WHERE user_id`, thứ phải đọc được bằng mắt trong vài phút.

╔══════════════════════════════════════════════════════════════════════════╗
║  BA CÂU DỰNG LẠI QUOTA CHỈ ĐỌC `key_source='system'` (§10.5, T-2.15)     ║
╚══════════════════════════════════════════════════════════════════════════╝

Bảng này chứa **cả hai** loại chi tiêu: tiền của người vận hành (`system`) và
tiền của chính người dùng (`byok`, §10.5). Hai câu hỏi khác nhau đọc nó, và
chúng cần hai tập hàng khác nhau:

* *"người này đã tiêu bao nhiêu **của mình**"* — cả hai loại. Đó là lý do
  §10.5 bắt ghi dòng sổ cho BYOK ngay cả khi không trừ quota.
* *"hạn mức 5 giờ của người này còn bao nhiêu"* — **chỉ** `system`.

`list_since`/`has_events_since`/`user_ids_since` trả lời câu **thứ hai**, nên
cả ba lọc `key_source='system'` trong câu SQL. Thiếu bộ lọc ấy thì mọi khoản
BYOK quay lại ZSET ở lần `refill_if_empty` đầu tiên (RR-7) — tức §10.5 bị phá
**một nhịp sau**, không phải lúc ghi sổ: `docker compose down -v` hay một
`FLUSHDB` là đủ. Đo được ở DoD T-2.15 dòng 3 trước khi có bộ lọc: sau khi xoá
khoá và xoá hai khoá quota, ZSET dựng lại ra **2** member trong đó có đúng
khoản BYOK 0.000068 USD vừa tiêu.

`sum_since` **không** lọc, vì nó trả lời câu thứ nhất và người gọi của nó
(T-2.17, cảnh báo chi tiêu) chưa tồn tại để nói nó muốn tập nào — xem Backlog.

**T-2.13 thêm ba câu đọc, và KHÔNG dùng `sum_since`.** Một tổng không dựng lại
được ZSET: §10.3 đặt `score` là epoch của **từng** dòng sổ, nên bản dựng lại
phải biết mỗi khoản tiền ra đời lúc nào — một con số gộp chỉ nói được "tổng
bằng nhau", mà bất biến T-2.12 đo là mạnh hơn thế (*số member bằng số dòng
sổ*). `sum_since` vì vậy vẫn chờ T-2.17; ba hàm mới ở dưới là phần T-2.13 cần:
`list_since` (dựng lại), `has_events_since` (phát hiện lệch, §10.3), và
`user_ids_since` (lệnh CLI `--all`).

**T-2.16 thêm bốn câu TỔNG HỢP cho `GET /admin/usage`** (§16.3, §18.5). Chúng
đứng riêng ở cuối file và là nhóm duy nhất **không** có `WHERE user_id` — xem
khối chú thích ngay trên chúng cho lý do, và `UsageBucket` ngay dưới đây cho
hình dạng một ô của bảng chi phí.
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

from app.db.models import CostConfidence, KeySource, UsageEvent, User


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


@dataclass(frozen=True, slots=True)
class UsageBucket:
    """MỘT ô của bảng chi phí admin: một khoá × một mức `cost_confidence` (T-2.16).

    Không phải một hàng — một **ô**. Câu SQL trả về hai dòng cho mỗi khoá có cả
    hai loại chi phí, và việc gộp chúng thành một hàng hai cột là việc của tầng
    hiển thị (`app/api/v1/admin.py`). Tách ở đây giữ cho repository trả về đúng
    thứ Postgres trả về, không phải một hình dạng đã diễn giải: C16 nói bảng
    phải có hai cột riêng, và cách chắc nhất để hai cột không bao giờ bị cộng
    lại là chúng chưa từng đi qua một biến chung nào.
    """

    #: Khoá của trục: ngày ISO, `user_id`, `model_id`, hoặc `key_source`.
    key: str
    #: Nhãn đọc được của khoá khi có (email của user); `None` ở ba trục kia.
    label: str | None
    confidence: CostConfidence
    cost_usd: Decimal
    prompt_tokens: int
    completion_tokens: int
    events: int


def _khoa(gia_tri: Any) -> str:
    """Khoá của một ô, dưới dạng chuỗi FE dùng thẳng được.

    `date_trunc` trả về một `datetime` lúc 00:00, và `str()` của nó là
    `"2026-09-19 00:00:00"` — một chuỗi mà mọi chỗ hiển thị sẽ phải cắt lại,
    và cắt bằng `[:10]` ở ba chỗ khác nhau là ba chỗ để cắt sai. Trục "theo
    ngày" trả về một **ngày**, nên khoá của nó là `"2026-09-19"`.
    """
    if isinstance(gia_tri, datetime):
        return gia_tri.date().isoformat()
    return "" if gia_tri is None else str(gia_tri)


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

        **KHÔNG lọc `key_source`, khác ba câu dưới** — có chủ ý, xem docstring
        module: đây là "người này đã tiêu bao nhiêu", một câu gồm cả BYOK.
        Người gọi duy nhất của nó (T-2.17) chưa tồn tại, nên chọn hộ nó một
        tập hàng hôm nay là đoán; ngày nó ra đời, nó nói ra tập nó muốn.
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
        Lọc `key_source='system'` ở cùng chỗ — xem docstring module (§10.5).
        """
        stmt = (
            select(UsageEvent.id, UsageEvent.cost_usd, UsageEvent.created_at)
            .where(
                UsageEvent.user_id == user_id,
                UsageEvent.created_at >= since,
                UsageEvent.key_source == KeySource.SYSTEM,
            )
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
            .where(
                UsageEvent.user_id == user_id,
                UsageEvent.created_at >= since,
                UsageEvent.key_source == KeySource.SYSTEM,
            )
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
        stmt = (
            select(UsageEvent.user_id)
            .where(
                UsageEvent.created_at >= since,
                UsageEvent.key_source == KeySource.SYSTEM,
            )
            .distinct()
        )
        return list((await self._session.execute(stmt)).scalars().all())

    # ═══════════ tổng hợp cho `GET /admin/usage` (§16.3, §18.5, C16) ═══════════
    #
    # Bốn hàm dưới đây là **một** câu hỏi hỏi theo bốn trục, nên chúng là bốn
    # lời gọi của cùng một hàm dựng câu (`_tong_hop`) chứ không phải bốn câu
    # SQL chép tay: bốn bản sao là bốn chỗ để `WHERE` lệch nhau, và một bảng
    # chi phí trong đó "theo ngày" cộng ra khác "theo model" là một bảng không
    # ai tin được nữa.
    #
    # KHÔNG lọc `user_id` — và đó là khác biệt duy nhất so với mọi câu khác của
    # file này. Người gọi là admin, câu hỏi là "cả hệ thống tiêu bao nhiêu";
    # cánh cửa canh chuyện đó là `require_admin` ở tầng router (§16.3: *"mọi
    # endpoint `/api/v1/admin/*` kiểm lại quyền phía server"*), không phải một
    # `WHERE` ở đây.

    async def _tong_hop(
        self,
        *,
        nhom: Any,
        nhan: Any | None,
        since: datetime,
        until: datetime,
    ) -> Sequence[UsageBucket]:
        """`GROUP BY (nhom, cost_confidence)` trong cửa sổ `[since, until)`.

        `cost_confidence` **luôn** nằm trong `GROUP BY`, ở mọi trục — đó chính
        là C16 viết thành SQL: *"trộn chung model `metered` và `unmetered` vào
        một con số làm bảng chi phí vô nghĩa — phải tách từ đây, không phải sửa
        ở tầng hiển thị"*. Một hàm `_tong_hop` không có cột ấy sẽ mời người gọi
        thứ hai quên nó đi.

        Biên `>= since` và `< until` (nửa mở), cùng luật với `list_since`: hai
        cửa sổ liền nhau không được đếm chung một dòng sổ hai lần.
        """
        cot = [nhom.label("khoa")]
        if nhan is not None:
            cot.append(nhan.label("nhan"))
        cot += [
            UsageEvent.cost_confidence.label("do_tin"),
            func.coalesce(func.sum(UsageEvent.cost_usd), 0).label("cost_usd"),
            func.coalesce(func.sum(UsageEvent.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(UsageEvent.completion_tokens), 0).label("completion_tokens"),
            func.count().label("events"),
        ]
        stmt = select(*cot).where(
            UsageEvent.created_at >= since,
            UsageEvent.created_at < until,
        )
        if nhan is not None:
            stmt = stmt.join(User, User.id == UsageEvent.user_id, isouter=True)
        stmt = stmt.group_by(*cot[: 2 if nhan is not None else 1], UsageEvent.cost_confidence)
        stmt = stmt.order_by(cot[0])
        rows = (await self._session.execute(stmt)).all()
        return [
            UsageBucket(
                key=_khoa(r.khoa),
                label=getattr(r, "nhan", None),
                confidence=CostConfidence(r.do_tin),
                cost_usd=Decimal(str(r.cost_usd)),
                prompt_tokens=int(r.prompt_tokens),
                completion_tokens=int(r.completion_tokens),
                events=int(r.events),
            )
            for r in rows
        ]

    async def admin_by_day(self, *, since: datetime, until: datetime) -> Sequence[UsageBucket]:
        """Chi phí theo NGÀY — §16.3 ("Biểu đồ theo ngày"), §18.5.

        `AT TIME ZONE 'UTC'` tường minh chứ không để `date_trunc` tự chọn: với
        `TIMESTAMPTZ` nó cắt theo `TimeZone` của **phiên** Postgres, tức cùng
        một dòng sổ rơi vào hai ngày khác nhau tuỳ ai đang hỏi. Cả app đã sống
        bằng UTC (`datetime.now(UTC)` ở mọi chỗ ghi mốc), nên chọn UTC ở đây là
        giữ đúng một đồng hồ chứ không phải thêm một quy ước.
        """
        ngay = func.date_trunc("day", func.timezone("UTC", UsageEvent.created_at))
        return await self._tong_hop(nhom=ngay, nhan=None, since=since, until=until)

    async def admin_by_user(self, *, since: datetime, until: datetime) -> Sequence[UsageBucket]:
        """Chi phí theo NGƯỜI DÙNG, kèm email — §16.3 ("bảng theo user").

        `LEFT JOIN users`: `usage_events.user_id` là `ON DELETE CASCADE`
        (Phụ lục A) nên hàng mồ côi không tồn tại hôm nay, nhưng một
        `soft-delete` (§20 "Quyền riêng tư") thì có — và một bảng chi phí tụt
        mất vài dòng vì người ta vừa xoá tài khoản là một bảng nói dối.
        """
        return await self._tong_hop(
            nhom=UsageEvent.user_id, nhan=User.email, since=since, until=until
        )

    async def admin_by_model(self, *, since: datetime, until: datetime) -> Sequence[UsageBucket]:
        """Chi phí theo MODEL — §16.3 ("bảng theo model")."""
        return await self._tong_hop(nhom=UsageEvent.model_id, nhan=None, since=since, until=until)

    async def admin_by_key_source(
        self, *, since: datetime, until: datetime
    ) -> Sequence[UsageBucket]:
        """Chi phí theo **tiền của ai** (§10.5) — trục thứ tư, không có trong §16.3.

        Có mặt vì C16 đọc một lần nữa ở mức cao hơn: `metered`/`unmetered` tách
        *"con số này đáng tin tới đâu"*, còn cột này tách *"con số này là tiền
        của ai"* — và gộp hai thứ đó vào một tổng làm hoá đơn của người vận hành
        phình lên đúng bằng phần BYOK mà §10.5 nói họ **không** trả. Cùng hình
        dạng, cùng hàm dựng câu, nên nó không thêm một luật nào mới: chỉ thêm
        một trục cho câu hỏi đã có.
        """
        return await self._tong_hop(nhom=UsageEvent.key_source, nhan=None, since=since, until=until)
