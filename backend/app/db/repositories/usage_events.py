"""Repository của sổ cái `usage_events` (§10.2 vế SAU, A7) — T-2.12.

Một hàm ghi, một hàm cộng. Cố ý ít: bảng này là **append-only** — không có
`update_*`, không có `delete_*`, và sẽ không bao giờ có. A7 nói lịch sử chi phí
không đổi, mà cách rẻ nhất để giữ lời hứa đó là không viết sẵn con dao.

`sum_since` chưa có người gọi trong T-2.12; nó là nửa đọc mà **T-2.13**
(`rebuild_quota`, §10.3) và **T-2.17** (cảnh báo chi tiêu, RR-1) cùng cần, và
nó nằm ở đây thay vì ở `quota/` vì §20 bắt mọi câu SQL sống trong tầng này —
nhất là câu có `WHERE user_id`, thứ phải đọc được bằng mắt trong vài phút.
(T-2.13 rồi cũng **không** dùng nó — xem dưới; người gọi thật ra đời ở T-2.17.)

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

**Và chỉ đọc `purpose='chat'` (T-S.7, §24.2b·S6).** Lượt đặt tên hội thoại đi
bằng system key nhưng **không** trừ quota — `quota/meter.py` bỏ `ZADD` cho nó.
Cùng hình dạng lỗi với B-168 ở trên: thiếu bộ lọc thứ hai này thì §24.2b·S6 bị
phá một nhịp sau, ở lần `refill_if_empty` đầu tiên (Cạm bẫy ① của T-S.7).

`sum_since` trả lời **cả hai** câu, và nó bắt người gọi nói ra mình hỏi câu
nào: tham số `key_source` **bắt buộc**, không có giá trị mặc định (T-2.17,
B-172). Một mặc định ở đây là chọn hộ người gọi tiếp theo — đúng hình dạng đã
sinh ra B-168, nơi ba câu dựng lại quota im lặng gom cả tiền BYOK vào hạn mức.
`None` nghĩa là *"cả hai loại"* và phải được gõ ra tường minh.

Nó cũng trả về **hai** con số chứ không một (`CostSplit`), vì C16 nói thẳng
`exact` và `low` phải tách **từ tầng dữ liệu**, không phải sửa ở tầng hiển thị.
Người gọi đầu tiên của nó — cron `spend_alert` (T-2.17) — cần cả hai: ngưỡng
so trên tổng, còn lá thư in riêng từng cột.

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

from app.db.models import CostConfidence, KeySource, UsageEvent, UsagePurpose, User


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
class CostSplit:
    """Chi tiêu của MỘT người trong MỘT cửa sổ, tách theo `cost_confidence` (T-2.17).

    Hai trường, và **không** có trường thứ ba tên `total` — cùng lý lẽ đã ghi
    cho `MeteredSplit` của T-2.16: C16 nói chính con số gộp ấy làm bảng chi phí vô
    nghĩa, và một trường tiện tay thì sẽ có người dùng. Nơi duy nhất trong app
    được phép cộng hai cột là `workers/spend_alert.py::_combined`, một hàm có
    tên để `grep` ra được, đứng ở đúng chỗ người dùng đã chốt là "ngưỡng so
    trên tổng, nhưng thư in tách hai con số".

    Vì sao `sum_since` trả về cái này chứ không một `Decimal`: người gọi của nó
    cần **cả hai** con số cho cùng một cửa sổ, và đường rẻ nhất để có chúng là
    một câu `GROUP BY cost_confidence` — hỏi hai lần với hai bộ lọc là hai lần
    quét cho một câu hỏi, và là hai chỗ để `WHERE` lệch nhau.
    """

    exact: Decimal
    low: Decimal


@dataclass(frozen=True, slots=True)
class UsageBucket:
    """MỘT ô của bảng chi phí admin: một khoá × một mức `cost_confidence` × một
    `purpose` (T-2.16, T-S.8).

    Không phải một hàng — một **ô**. Câu SQL trả về tới bốn dòng cho mỗi khoá
    (hai loại chi phí × hai việc), và việc gộp chúng thành một hàng hai cột là
    việc của tầng hiển thị (`app/api/v1/admin.py`). Tách ở đây giữ cho
    repository trả về đúng thứ Postgres trả về, không phải một hình dạng đã
    diễn giải: C16 nói bảng phải có hai cột riêng, và cách chắc nhất để hai cột
    không bao giờ bị cộng lại là chúng chưa từng đi qua một biến chung nào.
    """

    #: Khoá của trục: ngày ISO, `user_id`, `model_id`, hoặc `key_source`.
    key: str
    #: Nhãn đọc được của khoá khi có (email của user); `None` ở ba trục kia.
    label: str | None
    confidence: CostConfidence
    #: T-S.8 (§24.2b·S6): lượt chat hay lượt đặt tên hội thoại.
    purpose: UsagePurpose
    cost_usd: Decimal
    prompt_tokens: int
    completion_tokens: int
    events: int


def _bucket_key(value: Any) -> str:
    """Khoá của một ô, dưới dạng chuỗi FE dùng thẳng được.

    `date_trunc` trả về một `datetime` lúc 00:00, và `str()` của nó là
    `"2026-09-19 00:00:00"` — một chuỗi mà mọi chỗ hiển thị sẽ phải cắt lại,
    và cắt bằng `[:10]` ở ba chỗ khác nhau là ba chỗ để cắt sai. Trục "theo
    ngày" trả về một **ngày**, nên khoá của nó là `"2026-09-19"`.
    """
    if isinstance(value, datetime):
        return value.date().isoformat()
    return "" if value is None else str(value)


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
        purpose: UsagePurpose,
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
            purpose=purpose,
            upstream_model_reported=upstream_model_reported,
        )
        self._session.add(event)
        await self._session.flush()
        return event

    async def sum_since(
        self, *, user_id: uuid.UUID, since: datetime, key_source: KeySource | None
    ) -> CostSplit:
        """`SUM(cost_usd)` của một người kể từ `since`, tách theo `cost_confidence`.

        §10.3 ("Postgres là sự thật") · C16 · B-172 (chốt ở T-2.17).

        Lọc `user_id` **trong câu SQL**, không phải bằng một vòng `if` ở Python
        (§20). Đi đúng index `ix_usage_user_time` (`user_id, created_at DESC`)
        mà Phụ lục A dựng sẵn cho việc này.

        **`key_source` là tham số bắt buộc, không có mặc định** (B-172). Ba câu
        dưới đây ghim cứng `system` vì chúng trả lời *"hạn mức của người này
        còn bao nhiêu"*; câu này trả lời được **cả hai** câu hỏi của docstring
        module, nên nó bắt người gọi nói ra mình hỏi câu nào. `None` = cả hai
        loại (dành cho *"tôi đã tiêu bao nhiêu"* của §18.4, gồm cả tiền BYOK
        của chính họ); `KeySource.SYSTEM` = tiền của người vận hành, tập mà
        cron `spend_alert` (T-2.17, RR-1) đo.

        `COALESCE` vì `SUM` trên tập rỗng trả `NULL`, và một người chưa chat
        lần nào phải ra `0` chứ không phải `None` — chỗ gọi sẽ cộng con số này
        vào một `Decimal`, và `None` ở đó là một `TypeError` giữa đường tính
        tiền. Với `GROUP BY` thì tập rỗng không trả **dòng** nào, nên phép bù
        `0` nằm ở bước dựng `CostSplit` bên dưới chứ không ở `COALESCE`; giữ
        `COALESCE` vì nó vẫn đúng cho một nhóm có tổng `NULL`.
        """
        stmt = (
            select(
                UsageEvent.cost_confidence,
                func.coalesce(func.sum(UsageEvent.cost_usd), 0),
            )
            .where(
                UsageEvent.user_id == user_id,
                UsageEvent.created_at >= since,
            )
            .group_by(UsageEvent.cost_confidence)
        )
        if key_source is not None:
            stmt = stmt.where(UsageEvent.key_source == key_source)
        by_confidence = {
            CostConfidence(confidence): Decimal(str(total))
            for confidence, total in (await self._session.execute(stmt)).all()
        }
        return CostSplit(
            exact=by_confidence.get(CostConfidence.EXACT, Decimal(0)),
            low=by_confidence.get(CostConfidence.LOW, Decimal(0)),
        )

    async def byok_tokens_by_provider(self, user_id: uuid.UUID) -> dict[str, tuple[int, int]]:
        """`provider → (prompt_tokens, completion_tokens)` của mọi lượt BYOK của
        một người — tổng token ở tab BYOK (NQ-134 ③). Endpoint tự nhập có
        `provider = 'byok:<endpoint_id>'`.
        """
        stmt = (
            select(
                UsageEvent.provider,
                func.sum(UsageEvent.prompt_tokens),
                func.sum(UsageEvent.completion_tokens),
            )
            .where(UsageEvent.user_id == user_id, UsageEvent.key_source == KeySource.BYOK)
            .group_by(UsageEvent.provider)
        )
        rows = (await self._session.execute(stmt)).all()
        return {provider: (int(p), int(c)) for provider, p, c in rows}

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
        Lọc `key_source='system'` và `purpose='chat'` ở cùng chỗ — xem docstring
        module (§10.5, §24.2b·S6).
        """
        stmt = (
            select(UsageEvent.id, UsageEvent.cost_usd, UsageEvent.created_at)
            .where(
                UsageEvent.user_id == user_id,
                UsageEvent.created_at >= since,
                UsageEvent.key_source == KeySource.SYSTEM,
                UsageEvent.purpose == UsagePurpose.CHAT,
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
                UsageEvent.purpose == UsagePurpose.CHAT,
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
                UsageEvent.purpose == UsagePurpose.CHAT,
            )
            .distinct()
        )
        return list((await self._session.execute(stmt)).scalars().all())

    # ═══════════ tổng hợp cho `GET /admin/usage` (§16.3, §18.5, C16) ═══════════
    #
    # Bốn hàm dưới đây là **một** câu hỏi hỏi theo bốn trục, nên chúng là bốn
    # lời gọi của cùng một hàm dựng câu (`_aggregate`) chứ không phải bốn câu
    # SQL chép tay: bốn bản sao là bốn chỗ để `WHERE` lệch nhau, và một bảng
    # chi phí trong đó "theo ngày" cộng ra khác "theo model" là một bảng không
    # ai tin được nữa.
    #
    # KHÔNG lọc `user_id` — và đó là khác biệt duy nhất so với mọi câu khác của
    # file này. Người gọi là admin, câu hỏi là "cả hệ thống tiêu bao nhiêu";
    # cánh cửa canh chuyện đó là `require_admin` ở tầng router (§16.3: *"mọi
    # endpoint `/api/v1/admin/*` kiểm lại quyền phía server"*), không phải một
    # `WHERE` ở đây.

    async def _aggregate(
        self,
        *,
        group: Any,
        label: Any | None,
        since: datetime,
        until: datetime,
        key_source: KeySource | None = None,
    ) -> Sequence[UsageBucket]:
        """`GROUP BY (nhom, cost_confidence, purpose)` trong cửa sổ `[since, until)`.

        `cost_confidence` **luôn** nằm trong `GROUP BY`, ở mọi trục — đó chính
        là C16 viết thành SQL: *"trộn chung model `metered` và `unmetered` vào
        một con số làm bảng chi phí vô nghĩa — phải tách từ đây, không phải sửa
        ở tầng hiển thị"*. Một hàm `_aggregate` không có cột ấy sẽ mời người gọi
        thứ hai quên nó đi.

        `purpose` (T-S.8, §24.2b·S6) nằm trong `GROUP BY` vì cùng lý do: khoản
        "Đặt tên" của màn Chi phí đến từ **cùng** câu với hai cột, nên phần tách
        theo việc cộng lại luôn bằng đúng hai cột — không có câu thứ hai nào để
        `WHERE` lệch đi. Không lọc `purpose` ở đây: bảng chi phí là hoá đơn, và
        lượt đặt tên tốn tiền thật dù không trừ quota ai.

        Biên `>= since` và `< until` (nửa mở), cùng luật với `list_since`: hai
        cửa sổ liền nhau không được đếm chung một dòng sổ hai lần.

        `key_source` (T-2.19, B-178) lọc theo **tiền của ai** (§10.5): `None`
        giữ nguyên hành vi của T-2.16 (mọi nguồn). Nó nằm ở đây chứ không ở
        tầng hiển thị vì cùng lý do `cost_confidence` nằm trong `GROUP BY`:
        một tổng đã cộng xong rồi mới trừ đi phần BYOK là một phép trừ ai cũng
        có thể quên, còn một `WHERE` thì không quên được.
        """
        columns = [group.label("key")]
        if label is not None:
            columns.append(label.label("label"))
        columns += [
            UsageEvent.cost_confidence.label("confidence"),
            UsageEvent.purpose.label("purpose"),
            func.coalesce(func.sum(UsageEvent.cost_usd), 0).label("cost_usd"),
            func.coalesce(func.sum(UsageEvent.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(UsageEvent.completion_tokens), 0).label("completion_tokens"),
            func.count().label("events"),
        ]
        stmt = select(*columns).where(
            UsageEvent.created_at >= since,
            UsageEvent.created_at < until,
        )
        if key_source is not None:
            stmt = stmt.where(UsageEvent.key_source == key_source)
        if label is not None:
            stmt = stmt.join(User, User.id == UsageEvent.user_id, isouter=True)
        stmt = stmt.group_by(
            *columns[: 2 if label is not None else 1],
            UsageEvent.cost_confidence,
            UsageEvent.purpose,
        )
        stmt = stmt.order_by(columns[0])
        rows = (await self._session.execute(stmt)).all()
        return [
            UsageBucket(
                key=_bucket_key(r.key),
                label=getattr(r, "label", None),
                confidence=CostConfidence(r.confidence),
                purpose=UsagePurpose(r.purpose),
                cost_usd=Decimal(str(r.cost_usd)),
                prompt_tokens=int(r.prompt_tokens),
                completion_tokens=int(r.completion_tokens),
                events=int(r.events),
            )
            for r in rows
        ]

    async def admin_by_day(
        self, *, since: datetime, until: datetime, key_source: KeySource | None = None
    ) -> Sequence[UsageBucket]:
        """Chi phí theo NGÀY — §16.3 ("Biểu đồ theo ngày"), §18.5.

        `AT TIME ZONE 'UTC'` tường minh chứ không để `date_trunc` tự chọn: với
        `TIMESTAMPTZ` nó cắt theo `TimeZone` của **phiên** Postgres, tức cùng
        một dòng sổ rơi vào hai ngày khác nhau tuỳ ai đang hỏi. Cả app đã sống
        bằng UTC (`datetime.now(UTC)` ở mọi chỗ ghi mốc), nên chọn UTC ở đây là
        giữ đúng một đồng hồ chứ không phải thêm một quy ước.
        """
        day_col = func.date_trunc("day", func.timezone("UTC", UsageEvent.created_at))
        return await self._aggregate(
            group=day_col, label=None, since=since, until=until, key_source=key_source
        )

    async def admin_by_user(
        self, *, since: datetime, until: datetime, key_source: KeySource | None = None
    ) -> Sequence[UsageBucket]:
        """Chi phí theo NGƯỜI DÙNG, kèm email — §16.3 ("bảng theo user").

        `LEFT JOIN users`: `usage_events.user_id` là `ON DELETE CASCADE`
        (Phụ lục A) nên hàng mồ côi không tồn tại hôm nay, nhưng một
        `soft-delete` (§20 "Quyền riêng tư") thì có — và một bảng chi phí tụt
        mất vài dòng vì người ta vừa xoá tài khoản là một bảng nói dối.
        """
        return await self._aggregate(
            group=UsageEvent.user_id,
            label=User.email,
            since=since,
            until=until,
            key_source=key_source,
        )

    async def admin_by_model(
        self, *, since: datetime, until: datetime, key_source: KeySource | None = None
    ) -> Sequence[UsageBucket]:
        """Chi phí theo MODEL — §16.3 ("bảng theo model")."""
        return await self._aggregate(
            group=UsageEvent.model_id, label=None, since=since, until=until, key_source=key_source
        )

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

        **Cố ý KHÔNG nhận `key_source`** — ba trục kia nhận (T-2.19, B-178).
        Lọc trục này theo chính cột nó nhóm là xoá đúng thứ nó sinh ra để nói:
        màn "Chi phí" mặc định hiện `system` (hoá đơn thật), và cái giữ cho mặc
        định ấy không thành một lời nói dối là bảng này vẫn kể đủ cả hai nguồn
        ngay cạnh nó. Lọc nó đi thì người vận hành không còn đường nào biết là
        có tồn tại phần BYOK mình vừa loại ra.
        """
        return await self._aggregate(
            group=UsageEvent.key_source, label=None, since=since, until=until
        )
