"""Cửa chặn TRƯỚC của §10.2 — ước tính trường hợp xấu nhất rồi cho qua hay `429`.

KH tham chiếu: §10.2, §10.3, §9.5, §9.6, ADR-08, UC-07, S6 · CLAUDE.md A1, A3,
A7 · tasks.md T-2.11, B-65.

§10.2 viết ra đúng năm dòng cho vế TRƯỚC, và cả file này là chúng:

    TRƯỚC (trong api, đồng bộ, < 5 ms):
      est_in   = đếm token của context đã dựng (tiktoken, xấp xỉ là đủ)
      est_max  = est_in * in_price + max_output * out_price   ← xấu nhất
      spent_5h, spent_7d = đọc từ Redis
      nếu spent_5h + est_max > limit_5h  → 429 {limit_type:"5h", retry_after}
      nếu spent_7d + est_max > limit_7d  → 429 {limit_type:"weekly", ...}

╔══════════════════════════════════════════════════════════════════════════╗
║  VÌ SAO "XẤU NHẤT" LÀ `max_output`, KHÔNG PHẢI MỘT CON SỐ TRUNG BÌNH     ║
╚══════════════════════════════════════════════════════════════════════════╝

Cạm bẫy của T-2.11 nói thẳng: *"ước tính lạc quan (chỉ tính prompt token)
khiến một câu hỏi sinh 8000 token vượt hạn mức hàng chục lần"*. Lúc chặn thì
chưa ai biết model sẽ sinh bao nhiêu — nên đại lượng duy nhất **biết chắc**
là trần: `max_output` của chính model đó trong catalog. Với `deepseek-flash`
(8192 token, 1.20 USD/1M output) thì mỗi lượt được tính trước **0.0098 USD**
cho phần output, dù câu trả lời thật có thể chỉ tốn một phần trăm chừng ấy.

Cái giá của lựa chọn này là người dùng thấy quota "chặt hơn thực tế", và §10.2
đã nhận cái giá đó bằng chữ, kèm cách bù: hiển thị "còn lại ~X USD" theo **chi
tiêu thật** (`spent`), không theo dự toán. Đó chính là lý do `QuotaWarning`
dưới đây mang `spent_usd`/`remaining_usd` chứ không mang `est_max`.

╔══════════════════════════════════════════════════════════════════════════╗
║  MODEL KHÔNG CÓ GIÁ ⇒ `est_max = 0` ⇒ ĐI QUA, KHÔNG PHẢI ĐƯỢC MIỄN       ║
╚══════════════════════════════════════════════════════════════════════════╝

B-65 hỏi "model `unmetered` có được miễn luôn cửa này không"; NQ-52 trả lời
**không** — không có ngoại lệ nào trong dòng code dưới đây. Model đi qua cửa
này như mọi model khác, chỉ là giá của nó bằng `None` nên `est_max` ra 0 và
phép so sánh luôn đúng. Khác biệt nghe nhỏ nhưng nó quyết định chỗ sửa: điền
giá vào `manual_pricing` là đủ để một model bắt đầu bị trừ quota, **không cần
sửa một dòng nào ở đây** (§9.5, A3).

Phần ~2000 token 9Router bơm vào mọi request cộng vào `est_in` qua
`catalog.prompt_overhead_tokens()` — cũng là dữ liệu, cũng không có `if
provider == ...` nào ở đây.

╔══════════════════════════════════════════════════════════════════════════╗
║  DỰNG LẠI NGỮ CẢNH TRONG `api` — MỘT LẦN NỮA, CÓ CHỦ Ý                   ║
╚══════════════════════════════════════════════════════════════════════════╝

`est_in` phải là số token của **đúng** thứ worker sắp gửi lên, nên hàm này gọi
`llm.context.build()` — cùng hàm worker gọi, trên cùng `leaf_id`. Hệ quả: một
lượt chat dựng ngữ cảnh **hai** lần (một ở `api` để ước tính, một ở `worker`
để gửi).

Ngả rẻ hơn — chỉ đếm message mới rồi đoán phần còn lại — là chép luật cắt
ngữ cảnh của §9.6 ra khỏi `context.py` (A3), và nó sẽ lệch đúng vào hội thoại
dài, tức hội thoại đắt. Cái giá thật: một `get_path` (recursive CTE, đo 10.0 ms
ở T-1.2 trên cây 500 message) cộng một lượt `tiktoken`. Với 15–20 người dùng
(R1) thì đó là cái giá rẻ hơn nhiều so với một dự toán sai.

**A1 không bị vi phạm.** A1 cấm *generation* chạy trong HTTP handler — không
có `await` nào tới model ở đây, và `check_quota` không gọi `llm/client.py`.
Đếm token là một phép tính cục bộ, và §10.2 nói thẳng nó chạy "trong api".

╔══════════════════════════════════════════════════════════════════════════╗
║  REDIS CHẾT ⇒ 503, KHÁC `quota/tiers.py` — VÀ KHÁC CÓ CHỦ Ý              ║
╚══════════════════════════════════════════════════════════════════════════╝

`quota/tiers.py` đi tiếp bằng Postgres khi Redis chết, vì ở đó Redis chỉ là
một lối tắt. Ở đây thì không: ZSET vẫn là nơi cửa chặn này **đọc** số tiền đã
tiêu. Không hỏi được Redis nghĩa là **không biết** người này còn bao nhiêu
tiền — và cho qua lúc đó là gỡ đúng lớp phòng thủ P2 vào lúc hệ thống đang
hỏng. Cùng câu trả lời với năm chỗ đã chốt trước (`core/deps.py`,
`core/blacklist.py`, `core/idempotency.py`, và cả hai lớp của
`core/ratelimit.py`).

**Redis CHẾT và Redis RỖNG là hai ca khác nhau, và T-2.13 chỉ đóng ca thứ
hai.** Một `FLUSHDB` hay một `docker compose down -v` để lại một Redis **sống**
với hai cửa sổ trống, và ca đó `read_window` trả về bình thường — nên nó đi
qua `refill_if_empty` (`quota/rebuild.py`, RR-7) và được nạp lại từ
`usage_events` trước khi cửa chặn so sánh. Ca Redis **chết** thì vẫn `503`
đúng như đoạn trên: đường lùi "tính hạn mức thẳng từ Postgres khi Redis không
trả lời" là **B-155**, và nó vẫn đang mở.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from fastapi import status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import catalog
from app.config.catalog import TOKENS_PER_PRICE_UNIT
from app.config.settings import settings
from app.core.errors import ApiError, ApiErrorCode
from app.core.redis import get_redis
from app.db.repositories import SkillRepository
from app.llm import context
from app.llm.tokens import count_messages
from app.quota.rebuild import refill_if_empty
from app.quota.tiers import EffectiveLimits, get_effective_limits
from app.quota.windows import LimitType, WindowState, read_window, windows

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Estimate:
    """Dự toán **trường hợp xấu nhất** của một lượt sinh chưa chạy."""

    model_id: str
    #: Token đầu vào: ngữ cảnh đã dựng **cộng** phần provider tự bơm (B-65).
    est_in_tokens: int
    #: Trần token đầu ra của model — xem docstring module.
    max_output_tokens: int
    est_max_usd: Decimal
    #: `False` khi model không có giá ở cả hai nguồn của catalog. Không phải
    #: "miễn phí đã xác nhận", mà là "chưa ai điền giá" — `est_max_usd` khi đó
    #: bằng 0 và quota không trừ. Xem `_warn_model_without_price`.
    priced: bool


class QuotaWarning(BaseModel):
    """Cảnh báo sắp hết quota — UC-07 dòng 1: *"Còn ≤ 20% quota → hiện thanh cảnh báo"*.

    Đi trong **body** của `202`, không phải một header. Khác `X-RateLimit-*`
    của §10.6 có chủ ý: ba header kia là ba số nguyên không đơn vị mà FE chỉ
    hiển thị, còn khối này là bốn số **tiền** mà UC-07 bắt FE dựng thành một
    thanh cảnh báo có chữ — và một hợp đồng có kiểu, nằm trong OpenAPI, là thứ
    FE dựng được mà không phải đoán đơn vị của một chuỗi header.

    `spent_usd` là **chi tiêu thật**, không phải dự toán: §10.2 chốt rằng cửa
    chặn tính theo trường hợp xấu nhất còn con số hiển thị cho người dùng thì
    theo tiền đã tiêu — hai đại lượng khác nhau, và trộn chúng làm thanh cảnh
    báo nhảy lùi mỗi khi một lượt sinh kết thúc rẻ hơn dự toán.
    """

    model_config = ConfigDict(extra="forbid")

    limit_type: LimitType
    limit_usd: Decimal
    spent_usd: Decimal
    remaining_usd: Decimal
    #: Phần trăm còn lại, làm tròn **xuống**: 19.7% hiện ra là 19, không phải
    #: 20 — con số hiển thị không bao giờ được lạc quan hơn sự thật.
    remaining_pct: int


def estimate(
    model: catalog.ModelEntry, messages: list[dict[str, Any]], *, web_tools: bool = False
) -> Estimate:
    """`est_max` của §10.2 cho một ngữ cảnh đã dựng.

    Tách khỏi `check_quota` vì nó là phần **thuần tính toán**: không Redis,
    không Postgres, không `ApiError`. Nhờ vậy phép nhân tiền — thứ A7 đòi đúng
    tới 1e-6 — kiểm được mà không phải dựng một request giả.
    """
    return estimate_from_tokens(
        model, count_messages(messages, model_id=model.id), web_tools=web_tools
    )


def estimate_from_tokens(
    model: catalog.ModelEntry, context_tokens: int, *, web_tools: bool = False
) -> Estimate:
    """`est_max` khi đã có sẵn số token của ngữ cảnh.

    Là hàm mà `estimate` gọi, và cũng là đường đi của ca lùi trong
    `_estimate` — nơi ngữ cảnh dựng không nổi nên con số duy nhất dùng được là
    trần ngân sách §9.6. Hai đường vào, **một** phép nhân tiền.

    Giá lấy qua `catalog.effective_pricing()`, hàm duy nhất trả lời câu "model
    này giá bao nhiêu" (A3, B-35, B-65). **Không** truyền `at`: dự toán là dự
    toán cho **bây giờ**, và giờ này là giờ model sẽ chạy. Giá chốt vào lịch
    sử là việc của T-2.12, với `at` của chính lượt sinh ấy.

    **Lượt bật web (Q-P6-6, T-6.7a):** `est_max × (MAX_TOOL_ROUNDS + 1)` — mỗi
    vòng tool là một lần gọi nữa, gửi lại cả ngữ cảnh. Trần đọc LÚC GỌI.
    """
    cat = catalog.get_catalog()
    est_in = context_tokens + cat.prompt_overhead_tokens(model.id)
    pricing = cat.effective_pricing(model.id)

    if pricing is None:
        return Estimate(
            model_id=model.id,
            est_in_tokens=est_in,
            max_output_tokens=model.max_output,
            est_max_usd=Decimal(0),
            priced=False,
        )

    est_max = (
        Decimal(est_in) * Decimal(str(pricing.input_per_1m))
        + Decimal(model.max_output) * Decimal(str(pricing.output_per_1m))
    ) / TOKENS_PER_PRICE_UNIT
    if web_tools:
        est_max *= settings.MAX_TOOL_ROUNDS + 1

    return Estimate(
        model_id=model.id,
        est_in_tokens=est_in,
        max_output_tokens=model.max_output,
        est_max_usd=est_max,
        priced=True,
    )


async def check_quota(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    leaf_id: uuid.UUID,
    model: catalog.ModelEntry,
    web_tools: bool = False,
) -> QuotaWarning | None:
    """Cửa chặn TRƯỚC của §10.2. Trả cảnh báo (hoặc `None`) khi cho qua.

    Gọi từ `app/api/v1/messages.py::_mo_luot_sinh`, tức **trước** khi job vào
    hàng đợi và bên trong transaction của caller — ném từ đây làm cả
    transaction rollback, nên một lượt bị chặn không để lại hàng `messages`
    nào. Đó là điều S6 đo: `0 USD phát sinh`, và cũng không có rác.

    Raise:
        ApiError 429 `QUOTA_EXCEEDED`: `spent + est_max` vượt hạn mức của một
            trong hai cửa sổ. `details` mang `limit_type`, `retry_after`
            (có thể `null`), `limit`, `spent`, `estimate`.
        ApiError 503 `SERVICE_UNAVAILABLE`: không hỏi được Redis — xem
            docstring module.
    """
    estimate = await _estimate(
        session, leaf_id=leaf_id, model=model, user_id=user_id, web_tools=web_tools
    )
    limits = await get_effective_limits(user_id)

    now = time.time()
    redis = get_redis()
    states: list[WindowState] = []

    for window in windows():
        try:
            state = await read_window(redis, window, user_id=user_id, now=now)
            # RR-7 (T-2.13): cửa sổ rỗng có HAI nghĩa — "chưa tiêu gì" và
            # "Redis vừa mất dữ liệu" — và chúng trông giống hệt nhau từ đây.
            # `refill_if_empty` hỏi Postgres để phân biệt, rồi nạp lại nếu
            # cần. Nằm TRONG `try` cùng `read_window` có chủ ý: không hỏi
            # được Postgres nghĩa là vẫn không biết người này còn bao nhiêu
            # tiền, tức cùng một câu trả lời `503`.
            state = await refill_if_empty(session, redis, state, user_id=user_id, now=now)
        except Exception as exc:
            logger.exception(
                "khong doc duoc cua so quota %s cua user %s", window.limit_type, user_id
            )
            raise ApiError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                ApiErrorCode.SERVICE_UNAVAILABLE,
                "khong kiem duoc han muc chi tieu, hay thu lai",
            ) from exc

        limit_usd = limits.for_window(window)
        if state.spent + estimate.est_max_usd > limit_usd:
            raise _over_limit(state, estimate, limit_usd=limit_usd, now=now)
        states.append(state)

    return _warning(states, limits)


# ─────────────────────────── phần trong của file ───────────────────────────


async def _estimate(
    session: AsyncSession,
    *,
    leaf_id: uuid.UUID,
    model: catalog.ModelEntry,
    user_id: uuid.UUID,
    web_tools: bool,
) -> Estimate:
    """Dự toán theo ngữ cảnh thật; ngữ cảnh dựng không nổi thì theo **cả ngân sách**.

    `context.build()` có hai đường ném (`EmptyPathError`, `BudgetTooSmallError`)
    và cả hai đều **không** phải việc của cửa chặn này: nhiệm vụ của nó là ước
    tính, không phải xác nhận một lượt sinh hợp lệ — worker sẽ gặp lại đúng
    ngoại lệ ấy và báo lỗi bằng đường của §7.4.

    Nhưng "không ước tính được" thì không được đọc thành "không tốn gì": rơi
    về **trần ngân sách** (§9.6) là con số lớn nhất mà một lượt sinh có thể
    gửi lên, tức đúng chiều an toàn mà §10.2 đã chọn cho cả cửa này.

    Lượt có skill bật trên model `tools` cũng là lượt tool (`load_skill`, T-7.6)
    ⇒ cùng hệ số `MAX_TOOL_ROUNDS + 1` như lượt bật web. Cùng thế: user có
    `can_execute_skills` (`run_code`, T-7.7a) — cùng điều kiện worker mời tool.
    """
    if not web_tools and catalog.TOOLS_CAPABILITY in model.capabilities:
        web_tools = (
            bool(await SkillRepository(session).enabled_for_user(user_id))
            or (await get_effective_limits(user_id)).can_execute_skills
        )
    try:
        messages = await context.build(session, leaf_id, model, user_id=user_id)
    except context.ContextError:
        cap = context.token_budget(model)
        logger.warning(
            "khong dung duoc ngu canh cua leaf %s de uoc tinh — dung tran ngan sach "
            "%d token (§9.6) cho du toan",
            leaf_id,
            cap,
        )
        return estimate_from_tokens(model, cap, web_tools=web_tools)
    return estimate(model, messages, web_tools=web_tools)


def _over_limit(
    state: WindowState, estimate: Estimate, *, limit_usd: Decimal, now: float
) -> ApiError:
    """`429` của UC-07 dòng 3, kèm `retry_after` tính theo §10.3."""
    to_release = state.spent + estimate.est_max_usd - limit_usd
    retry_after = state.retry_after_s(need_to_free=to_release, now=now)

    logger.warning(
        "quota %s cua user het: da tieu %s + du toan %s > han muc %s (retry_after=%s)",
        state.window.limit_type.value,
        state.spent,
        estimate.est_max_usd,
        limit_usd,
        retry_after,
    )
    return ApiError(
        status.HTTP_429_TOO_MANY_REQUESTS,
        ApiErrorCode.QUOTA_EXCEEDED,
        "het han muc chi tieu, hay thu lai sau",
        details={
            "limit_type": state.window.limit_type.value,
            "retry_after": retry_after,
            "limit_usd": str(limit_usd),
            "spent_usd": str(state.spent),
            "estimate_usd": str(estimate.est_max_usd),
        },
        # `Retry-After` chỉ đặt khi có một con số THẬT — xem
        # `WindowState.retry_after_s`.
        headers={"Retry-After": str(retry_after)} if retry_after is not None else None,
    )


def _warning(states: list[WindowState], limits: EffectiveLimits) -> QuotaWarning | None:
    """Cửa sổ **chặt nhất** còn dưới ngưỡng cảnh báo, hoặc `None`.

    Một cảnh báo chứ không phải hai: người dùng cần biết "sắp hết" và cần một
    con số, không cần một bảng. Chọn cửa sổ còn **ít phần trăm nhất** vì đó là
    cửa sổ sẽ chặn họ trước.

    Tier có hạn mức `0` thì bỏ qua — không có phép chia nào, và người đó vốn
    đã bị chặn ở vòng trên trừ khi model không có giá.
    """
    candidates: list[QuotaWarning] = []
    for state in states:
        limit_usd = limits.for_window(state.window)
        if limit_usd <= 0:
            continue
        remaining = max(Decimal(0), limit_usd - state.spent)
        percent = int(remaining * 100 / limit_usd)
        if percent > settings.QUOTA_WARN_REMAINING_PCT:
            continue
        candidates.append(
            QuotaWarning(
                limit_type=state.window.limit_type,
                limit_usd=limit_usd,
                spent_usd=state.spent,
                remaining_usd=remaining,
                remaining_pct=percent,
            )
        )
    if not candidates:
        return None
    return min(candidates, key=lambda w: w.remaining_pct)
