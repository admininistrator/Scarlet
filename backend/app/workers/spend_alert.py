"""Cron `spend_alert` — thư cảnh báo khi chi tiêu vượt ngưỡng (RR-1, §21.5).

KH tham chiếu: RR-1, RR-13, §21.5, §21.2, §10.5, §9.5/C16, S13, Q-05 ·
CLAUDE.md A1, A3, A4 · tasks.md T-2.17, B-172.

RR-1 xếp *"đăng ký mở → người lạ tiêu tiền của bạn"* ở mức **Cao** và liệt năm
lớp chặn; bốn lớp đầu (duyệt tài khoản, verify email, Turnstile, quota) đều
chặn **trước khi** tiền ra đi. Lớp thứ năm — file này — là lớp duy nhất chạy
**sau**: nó không chặn gì cả, nó chỉ bảo đảm rằng nếu bốn lớp kia bị lọt thì
người vận hành biết trong vòng một giờ chứ không phải cuối tháng. RR-13 nói
cùng điều ấy từ phía khác: chỉ có **một** người vận hành, nên thứ duy nhất
đáng tin là cái tự gõ cửa.

╔══════════════════════════════════════════════════════════════════════════╗
║  BỐN QUYẾT ĐỊNH CỦA TASK NÀY — NGƯỜI DÙNG CHỐT, GHI Ở NQ-62…NQ-65        ║
╚══════════════════════════════════════════════════════════════════════════╝

**① Đếm tiền của ai: chỉ `key_source='system'`** (NQ-62, đóng **B-172**).
RR-1 viết *"người lạ tiêu tiền CỦA BẠN"*, và §10.5 nói dòng sổ `byok` tồn tại
*"để user tự xem chi tiêu"* — tiền ấy không nằm trên hoá đơn của người vận
hành, nên gộp nó vào đây là thổi ngân sách 30 USD lên bằng tiền người khác đã
tự trả. Hệ quả: `UsageEventRepository.sum_since` nhận `key_source` làm tham số
**bắt buộc** (đúng như B-172 dự đoán), và `user_ids_since` — vốn đã ghim
`system` từ T-2.15 — là nguồn danh sách người dùng đúng cho vòng lặp dưới đây.

**② Đọc bằng `sum_since` + `user_ids_since`, không thêm câu SQL thứ năm**
(NQ-63). Một `GROUP BY user_id` mới sẽ nhanh hơn về lý thuyết, nhưng nó là câu
thứ năm đọc `usage_events` với một mệnh đề `WHERE` chép tay — và một bảng chi
phí trong đó cron nói khác `/admin/usage` là một bảng không ai còn tin (cùng
lý lẽ đã viết cho `_tong_hop` ở T-2.16). Vòng lặp ở đây là **1 + N** truy vấn
với N = số người có chi tiêu trong cửa sổ; R1 chốt 15–20 người dùng và job
chạy mỗi giờ một lần, nên cái giá là vài chục mili-giây. Đổi lại: tổng của cả
hệ thống và "ai tiêu nhiều nhất" ra từ **cùng một tập số**, nên chúng không
thể nói khác nhau trong cùng một lá thư.

**③ Cửa sổ của `MONTHLY_BUDGET_USD` là 30 ngày TRƯỢT** (NQ-64). S13 viết đúng
chữ *"chi phí thực tế **30 ngày**"*. Mốc "ngày 1 hằng tháng" sẽ reset ngân
sách một cách giả tạo: tiêu 29 USD ngày 30/9 rồi 29 USD ngày 1/10 là 58 USD
trong 48 giờ mà không chuông nào kêu.

**④ Dòng `cost_confidence='low'` CÓ tính vào ngưỡng, nhưng thư in tách hai
con số** (NQ-65). C16 cấm *một con số gộp đứng một mình*, không cấm phép cộng:
lá thư luôn in `exact` và `low` riêng, nên người đọc thấy ngay phần nào đối
chiếu được với hoá đơn provider (S13) và phần nào chỉ là ước lượng của §9.5.
Ngả kia — chỉ đếm `exact` — làm chuông câm đúng với kẻ lạm dụng chỉ dùng model
qua 9Router, tức hỏng về phía **lỏng** hơn. Phép cộng ấy sống ở đúng một hàm
có tên (`_combined`), để `grep` ra được chỗ duy nhất trong app làm việc đó.

╔══════════════════════════════════════════════════════════════════════════╗
║  CHỐNG LẶP: GIỮ CHỖ TRƯỚC, GỬI SAU, NHẢ RA NẾU KHÔNG GỬI ĐƯỢC LÁ NÀO     ║
╚══════════════════════════════════════════════════════════════════════════╝

Cạm bẫy của task viết thẳng: *"không chống lặp thì bạn nhận 24 thư mỗi ngày và
sẽ lọc chúng vào thùng rác — cảnh báo bị bỏ qua là cảnh báo không tồn tại."*

Cờ là một khoá Redis đặt tên theo **ngày** (`alert:daily:{YYYY-MM-DD}`), và
`SET NX` chính là phép kiểm chứ không phải một bước riêng sau `EXISTS`: hai
bước là một khe mà hai tick có thể cùng lọt qua. Tên khoá mang danh tính của
ngày nên TTL chỉ còn việc dọn rác — để nó **hai** ngày, không phải "tới nửa
đêm", vì một TTL tính theo thời gian còn lại sẽ tắt cảnh báo của ngày hôm sau
nếu lá thư đầu tiên rơi vào 23 giờ.

Thứ tự **giữ chỗ → gửi → nhả nếu hỏng** chọn *không gửi trùng* làm mặc định và
vẫn thử lại được ở giờ sau khi SMTP chết (ca hỏng thường gặp). Ca mất hẳn một
cảnh báo chỉ xảy ra khi tiến trình bị giết đúng giữa `SET NX` và `send` — và
ngày hôm sau vẫn có chuông.

**`MONTHLY_BUDGET_USD` cũng chống lặp theo NGÀY, không theo tháng.** "Việc cần
làm" chỉ viết `tối đa 1 lần/ngày` cho ngưỡng ngày, nhưng Cạm bẫy nói về cả hai
— mà một lần duy nhất cho cả cửa sổ 30 ngày thì ngân sách vượt 2× vẫn im. Một
thư mỗi ngày là nhắc mà không làm phiền.

**Dòng log `WARNING` thì KHÔNG chống lặp.** Nó ghi ở **mỗi** tick khi còn vượt
ngân sách, vì log không phải hộp thư: nó là thứ duy nhất còn lại khi SMTP chết
hoặc khi người ta đọc lại một ngày đã qua (§21.1).

╔══════════════════════════════════════════════════════════════════════════╗
║  VÌ SAO HAI CON SỐ Ở ĐÂY KHÔNG PHẢI BIẾN `Settings` (A3)                 ║
╚══════════════════════════════════════════════════════════════════════════╝

`DAILY_ALERT_USD` và `MONTHLY_BUDGET_USD` là *giới hạn*, và cả hai **đã** là
biến môi trường từ Q-05. `BUDGET_WINDOW_DAYS = 30` và nhịp chạy hằng giờ thì
không: chúng là **định nghĩa** của phép đo chứ không phải nút vặn — S13 viết
ra con số 30, và "cron hằng giờ" là chữ của chính task. Cùng lối với
`REAPER_MOI_N_GIAY` của §7.6, và cùng lý do phụ: `cron` của arq nhận một tập
**phút trong giờ**, nên một biến `.env` nhận `SPEND_ALERT_MOI_N_PHUT=7` sẽ tạo
một lịch lệch mà không ai báo.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from app.config.settings import settings
from app.core.mailer import mailer
from app.db.models import KeySource
from app.db.repositories import CostSplit, UsageEventRepository, UserRepository
from app.db.session import session_scope

logger = logging.getLogger(__name__)

#: Tên cron trên dây. Cùng lý do với `REAPER_JOB_NAME`: arq mặc định lấy
#: `__qualname__`, nên đổi tên hàm Python là làm chết một lệnh `grep` của
#: người vận hành mà không ai báo.
SPEND_ALERT_JOB_NAME = "spend_alert"

#: "Cron hằng giờ" của "Việc cần làm" — arq nhận một tập **phút trong giờ**,
#: nên "mỗi giờ" là `{0}` (arq mặc định `second=0`, xem `arq/cron.py`).
SPEND_ALERT_PHUT_TRONG_GIO = frozenset({0})

#: Cửa sổ của `MONTHLY_BUDGET_USD`: **30 ngày trượt**, đúng chữ của S13
#: (NQ-64). Xem khối cuối docstring module cho lý do đây không phải `Settings`.
BUDGET_WINDOW_DAYS = 30

#: TTL của cờ chống lặp. Tên khoá đã mang ngày nên TTL chỉ là phép dọn rác —
#: hai ngày cho rộng rãi. Xem khối "chống lặp" ở docstring module.
ALERT_FLAG_TTL_S = 2 * 24 * 3600

#: Tên template mail (`app/templates/email/{tên}.txt|.html`) — cũng là khoá
#: tra tiêu đề trong `core/mailer.py::_SUBJECTS`, và cũng là tiền tố khoá cờ.
TEMPLATE_DAILY = "spend_daily"
TEMPLATE_BUDGET = "spend_budget"

#: Bước nhỏ nhất của `usage_events.cost_usd` (`NUMERIC(12, 6)`). Đây là độ
#: phân giải của **cột**, không phải một con số tiền — in `{:.2f}` sẽ biến
#: ngưỡng 0.0001 USD của DoD thành "0.00" trong thư.
USD_QUANTUM = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class WindowSpend:
    """Chi tiêu của CẢ HỆ THỐNG trong một cửa sổ, kèm người tiêu nhiều nhất.

    `split` giữ nguyên hai cột của C16 tới tận lá thư; `top_email` có thể là
    `None` ở hai ca: không ai tiêu gì (khi ấy `top_usd` là 0), hoặc người tiêu
    nhiều nhất đã xoá tài khoản giữa lúc ấy và lúc job chạy — `get_by_id` lọc
    `deleted_at IS NULL`, và thư nói "(không rõ)" thay vì giấu cả dòng đi.
    """

    split: CostSplit
    top_email: str | None
    top_usd: Decimal


def _combined(split: CostSplit) -> Decimal:
    """Cộng hai cột của C16 thành MỘT con số — chỗ duy nhất trong app làm thế.

    Có tên riêng để `grep` ra được, vì đây đúng là thứ C16 cảnh báo. Nó hợp lệ
    ở **đây** và chỉ ở đây: NQ-65 chốt rằng ngưỡng so trên tổng (một kẻ lạm
    dụng chỉ dùng model `unmetered` vẫn phải làm chuông kêu), với điều kiện lá
    thư không bao giờ in con số này mà thiếu hai con số thành phần.
    """
    return split.exact + split.low


def _usd(value: Decimal) -> str:
    """Số tiền dưới dạng chuỗi, đủ sáu chữ số thập phân của cột `cost_usd`."""
    return str(value.quantize(USD_QUANTUM))


def day_start_utc(now: datetime) -> datetime:
    """Nửa đêm **UTC** của ngày chứa `now` — biên dưới của "chi tiêu ngày".

    Một hàm riêng chứ không một dòng `now.replace(...)` trong thân job, và lý
    do là **kiểm được**: ngả sai đáng sợ ở đây là `now - timedelta(days=1)`
    (một cửa sổ 24 giờ **trượt**, không phải "hôm nay"), và hai công thức ấy
    chỉ cho kết quả khác nhau tuỳ vào **giờ lúc chạy** — tức một phép kiểm
    đo qua job sẽ xanh hay đỏ theo đồng hồ của người chạy test. Tách ra thì
    nó nhận một `now` cố định và trả lời dứt khoát.

    UTC, cùng đồng hồ với `admin_by_day` (`AT TIME ZONE 'UTC'`) và với mọi chỗ
    ghi mốc trong app: một job đo "hôm nay" bằng múi giờ khác bảng chi phí là
    hai con số không bao giờ khớp mà không ai sai.
    """
    return now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


async def spend_alert(ctx: dict[str, Any]) -> None:
    """Một nhịp. Không ném ra ngoài — cùng luật với `reaper` (§7.6).

    `max_tries=1` của cron arq nghĩa là một lần ném là mất hẳn một tick, mà
    tick sau vẫn thấy đúng những con số ấy (sổ cái là append-only, A7) nên thử
    lại không mua thêm gì. Đổi lại, mọi ngả thoát đều để lại một dòng log.
    """
    now = datetime.now(UTC)
    day_start = day_start_utc(now)
    budget_start = now - timedelta(days=BUDGET_WINDOW_DAYS)
    hom_nay = now.date().isoformat()

    try:
        async with session_scope() as session:
            usage = UsageEventRepository(session)
            users = UserRepository(session)
            daily = await _window_spend(usage, users, since=day_start)
            budget = await _window_spend(usage, users, since=budget_start)
            recipients = [admin.email for admin in await users.list_admins()]
    except Exception:  # noqa: BLE001 — xem docstring
        logger.exception("spend_alert: khong doc duoc so cai, bo qua nhip nay")
        return

    await _alert_if_over(
        ctx["redis"],
        spend=daily,
        limit_usd=settings.DAILY_ALERT_USD,
        template=TEMPLATE_DAILY,
        flag=f"alert:{TEMPLATE_DAILY}:{hom_nay}",
        window_label="hom nay",
        window_text="hôm nay",
        recipients=recipients,
        urgent=False,
        now=now,
    )
    await _alert_if_over(
        ctx["redis"],
        spend=budget,
        limit_usd=settings.MONTHLY_BUDGET_USD,
        template=TEMPLATE_BUDGET,
        flag=f"alert:{TEMPLATE_BUDGET}:{hom_nay}",
        window_label=f"{BUDGET_WINDOW_DAYS} ngay qua",
        window_text=f"{BUDGET_WINDOW_DAYS} ngày qua",
        recipients=recipients,
        urgent=True,
        now=now,
    )


async def _window_spend(
    usage: UsageEventRepository,
    users: UserRepository,
    *,
    since: datetime,
) -> WindowSpend:
    """Tổng chi tiêu `system` của cả hệ thống trong `[since, ∞)` + người tiêu nhất.

    `user_ids_since` đã lọc `key_source='system'` từ T-2.15, nên tập người ở
    đây khớp đúng tập hàng mà `sum_since(key_source=SYSTEM)` sẽ cộng — một
    người chỉ tiêu bằng khoá của chính họ không xuất hiện ở cả hai chỗ.

    Một lời gọi `get_by_id` **duy nhất**, cho người đứng đầu: DoD đòi thư nói
    *"user nào tiêu nhiều nhất và bao nhiêu"*, không đòi một bảng xếp hạng, và
    tra email cho cả N người là N truy vấn để in ra thứ không ai đọc.
    """
    exact = Decimal(0)
    low = Decimal(0)
    top_id: uuid.UUID | None = None
    top_usd = Decimal(0)

    for user_id in await usage.user_ids_since(since=since):
        split = await usage.sum_since(user_id=user_id, since=since, key_source=KeySource.SYSTEM)
        exact += split.exact
        low += split.low
        cua_nguoi_nay = _combined(split)
        if top_id is None or cua_nguoi_nay > top_usd:
            top_id, top_usd = user_id, cua_nguoi_nay

    top_email: str | None = None
    if top_id is not None:
        nguoi = await users.get_by_id(top_id)
        top_email = nguoi.email if nguoi is not None else None

    return WindowSpend(split=CostSplit(exact=exact, low=low), top_email=top_email, top_usd=top_usd)


async def _alert_if_over(
    redis: Any,
    *,
    spend: WindowSpend,
    limit_usd: Decimal,
    template: str,
    flag: str,
    window_label: str,
    window_text: str,
    recipients: list[str],
    urgent: bool,
    now: datetime,
) -> None:
    """Một ngưỡng: so, ghi log, giữ chỗ, gửi. Hai lời gọi, không hai bản chép.

    `>` chứ không `>=`: "vượt" là vượt. Với `DAILY_ALERT_USD=0` (biến khai
    `ge=0`) thì một ngày không ai chat vẫn im lặng.
    """
    total = _combined(spend.split)
    if total <= limit_usd:
        # `debug` chứ không `info`: 24 dòng/ngày × 2 ngưỡng ở mức `info` sẽ dìm
        # log của `generate` — cùng lý lẽ với đường chạy thường ngày của reaper.
        logger.debug(
            "spend_alert: %s %s USD, duoi nguong %s USD",
            window_label,
            _usd(total),
            _usd(limit_usd),
        )
        return

    if urgent:
        # "ghi log mức WARNING" của "Việc cần làm". KHÔNG chống lặp — xem
        # docstring module: log không phải hộp thư.
        logger.warning(
            "spend_alert: VUOT NGAN SACH %s — %s USD (exact %s + low %s) > %s USD",
            window_label,
            _usd(total),
            _usd(spend.split.exact),
            _usd(spend.split.low),
            _usd(limit_usd),
        )

    if not recipients:
        # Không nhả cờ và cũng không giữ chỗ: không có ai để gửi thì mỗi tick
        # phải nói lại, vì đây là một sự cố cấu hình chứ không phải một lần
        # SMTP hỏng. Dòng này là thứ duy nhất chỉ ra "chưa có tài khoản admin".
        logger.warning(
            "spend_alert: vuot nguong %s nhung khong co user nao role='admin' de gui thu",
            window_label,
        )
        return

    if not await _reserve(redis, flag):
        logger.info("spend_alert: thu '%s' da gui hom nay, khong gui lai", template)
        return

    ctx = {
        "window": window_text,
        "total_usd": _usd(total),
        "exact_usd": _usd(spend.split.exact),
        "low_usd": _usd(spend.split.low),
        "limit_usd": _usd(limit_usd),
        "top_email": spend.top_email,
        "top_usd": _usd(spend.top_usd),
        "as_of": now.isoformat(timespec="seconds"),
    }
    sent = await _send(recipients, template, ctx)
    if sent == 0:
        # Không lá nào đi được ⇒ nhả chỗ đã giữ, để giờ sau còn thử lại.
        await _release(redis, flag)
        return
    logger.info(
        "spend_alert: da gui '%s' cho %d admin — %s %s USD > %s USD, cao nhat: %s (%s USD)",
        template,
        sent,
        window_label,
        _usd(total),
        _usd(limit_usd),
        spend.top_email or "(khong ro)",
        _usd(spend.top_usd),
    )


async def _reserve(redis: Any, flag: str) -> bool:
    """`SET NX EX` — vừa là phép kiểm vừa là phép đặt, trong một lệnh.

    Redis chết thì coi như **đã gửi** (trả `False`): ngả kia là gửi thư mà
    không ghi được cờ, tức đúng 24 lá một ngày mà Cạm bẫy của task nói tới.
    """
    try:
        return bool(await redis.set(flag, "1", ex=ALERT_FLAG_TTL_S, nx=True))
    except Exception:  # noqa: BLE001 — xem docstring
        logger.exception("spend_alert: khong dat duoc co chong lap %s, bo qua luot gui", flag)
        return False


async def _release(redis: Any, flag: str) -> None:
    """Nhả chỗ đã giữ khi không lá thư nào đi được — giờ sau thử lại."""
    try:
        await redis.delete(flag)
    except Exception:  # noqa: BLE001
        logger.exception("spend_alert: khong xoa duoc co %s sau khi gui that bai", flag)


async def _send(recipients: list[str], template: str, ctx: dict[str, Any]) -> int:
    """Gửi cho từng admin; một hộp thư hỏng KHÔNG chặn những hộp còn lại.

    Cùng hình dạng với `_bao_cho_client` của reaper, và cùng lý do: vòng lặp
    này chạy trong một job không có ai đứng chờ, nên một exception bay ra là
    mất nốt phần chưa làm mà không ai biết.
    """
    sent = 0
    for to in recipients:
        try:
            await mailer.send(template=template, to=to, ctx=ctx)
            sent += 1
        except Exception:  # noqa: BLE001 — xem docstring
            logger.exception("spend_alert: gui '%s' cho %s that bai", template, to)
    return sent
