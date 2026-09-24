"""Cửa SAU của §10.2 — ghi thực khi đã biết một lượt sinh tốn bao nhiêu.

KH tham chiếu: §10.2, §10.3, §9.5, §17.2, A7, ADR-08, C16, C40 · CLAUDE.md A3,
A7 · tasks.md T-2.12, B-32, B-67, B-78, B-94, B-156 · NQ-20, NQ-23, NQ-26.

§10.2 viết ra đúng bốn dòng cho vế SAU, và cả file này là chúng:

    SAU (trong worker, khi có usage thật):
      cost = in*in_price + out*out_price + cached*cached_price
      INSERT usage_events (... , price_snapshot = {…}, cost_confidence)
      ZADD quota:5h:{uid}  <ts> <cost>   ;  ZADD quota:7d:{uid} <ts> <cost>

Đối xứng với `estimator.py`: ở đó là **dự toán trường hợp xấu nhất** để quyết
định cho qua hay `429`; ở đây là **số thật** để ghi sổ. Hai con số cố tình khác
nhau, và §10.2 đã nói cách bù khác biệt ấy cho người dùng (thanh quota hiển thị
theo `spent` thật, không theo dự toán).

╔══════════════════════════════════════════════════════════════════════════╗
║  `cached_tokens` LÀ TẬP CON CỦA `prompt_tokens`, KHÔNG PHẢI KHOẢN CỘNG   ║
╚══════════════════════════════════════════════════════════════════════════╝

§10.2 viết công thức là `in*in_price + out*out_price + cached*cached_price`.
Đọc thẳng chữ ấy thì phần token trúng cache bị tính **hai lần**: một lần theo
giá cache-miss trong `in`, một lần nữa theo giá cache-hit. Cả OpenAI, DeepSeek
lẫn Anthropic (qua LiteLLM) đều báo `prompt_tokens` **đã bao gồm**
`prompt_tokens_details.cached_tokens`, nên `in` không phải "phần không trúng
cache".

`PricingRates` của `config/catalog.py` đã chốt nghĩa của hai mức giá từ B-35:
*"`input_per_1m` là giá của token **không** trúng cache (DeepSeek gọi là 'cache
miss'), và `cached_input_per_1m` là giá token **trúng** cache"*. Công thức duy
nhất đứng được cùng câu đó là:

    cost = (in − cached)*input + cached*cached_input + out*output

Với `deepseek-flash` giờ cao điểm (0.30 miss / 0.006 hit) thì chênh lệch giữa
hai cách đọc là **50×** trên phần trúng cache — đúng loại sai mà một hoá đơn
cuối tháng mới khai ra. Đây là một lệch so với chữ của §10.2, đã ghi vào báo
cáo T-2.12 phần "Lệch kế hoạch".

`cache_write_per_1m` (Anthropic thu riêng tiền **ghi** cache) nằm trong
`price_snapshot` nhưng **không** vào công thức: `Usage` của §9.1 không có
trường nào đếm token ghi cache, và `usage_events` cũng không có cột cho nó.
Snapshot giữ con số lại để một phép đối chiếu sau này biết hôm ấy provider bán
cache thế nào — xem Backlog.

╔══════════════════════════════════════════════════════════════════════════╗
║  `cost_confidence` — HAI ĐIỀU KIỆN, THIẾU MỘT LÀ `low` (§9.5, C16)       ║
╚══════════════════════════════════════════════════════════════════════════╝

`exact` đòi **cả hai**:

1. `model.is_metered` — provider báo chi phí đáng tin (§9.5). Model qua 9Router
   thì không: nó tự fallback sang tier khác nên model trả lời có thể không
   phải model đã yêu cầu, và token báo về có thể đã bị RTK nén.
2. `Spent.measured` — số token là số **provider gửi về**, không phải số
   `tiktoken` tự đếm. Hai đường rơi vào nhánh tự đếm, khác nguyên nhân nhưng
   cùng hệ quả: provider không bao giờ báo `usage` (C40, **B-67**), hoặc mình
   bỏ stream trước khi họ kịp báo — tức huỷ giữa chừng (**B-94**, NQ-26), nơi
   `done.usage` là `None` **luôn luôn** vì cả bốn provider đang bật chỉ gửi
   `usage` ở chunk cuối cùng.

C16 nói phép tách này phải làm **từ đây**, không phải sửa ở tầng hiển thị — nên
nó là một cột trong sổ, quyết ngay lúc ghi, không phải một phép suy luận mà
admin panel tự làm lại sau.

**Số tự đếm vào `usage_events`, KHÔNG vào `messages`.** NQ-26 chốt rằng hai cột
`messages.prompt_tokens`/`completion_tokens` chỉ chứa số **thật của provider**,
để NULL khi không có. Ở đây thì khác: `usage_events` có `cost_confidence` để
đánh dấu, tức là nơi **duy nhất** đếm được mà không nói dối (NQ-23). Ranh giới
ấy là toàn bộ nội dung của NQ-20 ② và NQ-26.

╔══════════════════════════════════════════════════════════════════════════╗
║  `upstream_model_reported` HÔM NAY LUÔN NULL — ĐÃ ĐO, ĐÃ CHỐT (B-32)     ║
╚══════════════════════════════════════════════════════════════════════════╝

§9.5 hàng "Ghi nhận" viết: *"Nếu 9Router trả header cho biết upstream thật,
worker ghi vào `usage_events.upstream_model_reported`"*. Đo trên 9Router thật ở
T-2.12:

* 9Router **không** trả header riêng nào — không `x-9router-*`, không gì khác.
* Nó **có** khai model thật, nhưng trong **body**: xin alias tier `-low` thì
  mọi chunk trả về một trường `model` mang tên model gốc, đã rụng hậu tố tier.
* LiteLLM **ghi đè** trường đó bằng alias của chính nó (tên trong
  `config/litellm.config.yaml`) trước khi backend nhìn thấy. Backend chỉ nói
  chuyện với model qua LiteLLM (A9, ADR-03), nên tên thật không tới được đây.
  *(Số đo nguyên văn của cả hai vế nằm trong báo cáo T-2.12; chép tên model
  vào đây sẽ làm `make check-hardcode` báo động giả mỗi lần chạy — và một
  phép kiểm hay báo động giả là một phép kiểm sắp bị tắt.)*
* LiteLLM **có** forward header của provider dưới tiền tố `llm_provider-*` —
  tức kênh §9.5 mong đợi tồn tại, 9Router không dùng. Header
  `x-litellm-model-name` là model **được yêu cầu**, không đổi khi 9Router
  fallback, nên nó không trả lời được câu hỏi của §9.5.

Vì vậy cột để **NULL**, và §9.5 hạ yêu cầu xuống "không lấy được" (ghi trong
Backlog + Nhật ký quyết định vì agent không sửa `docs/KE-HOACH.md`). Điền
`x-litellm-model-name` vào đó sẽ biến "không đo được" thành "đo được" cho đúng
cột sinh ra để phát hiện fallback — thứ NQ-23 cấm.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import catalog
from app.config.catalog import TOKENS_PER_PRICE_UNIT
from app.db.models import CostConfidence, KeySource, MessageRole, UsagePurpose
from app.db.repositories import UsageEventRepository
from app.llm.client import Usage
from app.llm.tokens import count_message, count_messages, count_text
from app.quota.windows import add_to_windows, quantize_cost

if TYPE_CHECKING:  # pragma: no cover - chỉ dùng cho kiểu
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Spent:
    """Token đã tiêu **thật** cho một lượt sinh đã khép.

    Khác `Estimate` của `estimator.py` ở đúng một chữ: cái kia là dự toán trước
    khi gọi, cái này là số sau khi gọi xong. Tách thành một kiểu riêng (thay vì
    dùng lại `Usage` của §9.1) vì nó mang thêm `measured` — thứ `Usage` không
    diễn đạt được: một `Usage` do `tiktoken` dựng ra trông y hệt một `Usage`
    provider gửi về, và trộn hai cái đó là mất luôn `cost_confidence`.
    """

    prompt_tokens: int
    completion_tokens: int
    #: Tập **con** của `prompt_tokens` — xem docstring module.
    cached_tokens: int
    #: `True` = số của provider; `False` = `tiktoken` tự đếm (B-67, B-94).
    measured: bool


@dataclass(frozen=True, slots=True)
class UsageRecord:
    """Dòng sổ vừa ghi, rút gọn còn những gì chỗ gọi cần đọc lại."""

    id: uuid.UUID
    cost_usd: Decimal
    confidence: CostConfidence
    spent: Spent


def measure(
    model: catalog.ModelEntry,
    *,
    usage: Usage | None,
    sent: list[dict[str, Any]],
    content: str,
    reasoning: str,
    tool_calls: list[dict[str, Any]] | None,
) -> Spent:
    """Số token thật của lượt sinh — của provider nếu có, tự đếm nếu không.

    Nhánh tự đếm là đường lùi C40 mà NQ-20 ② giao cho task này, và cũng là
    đường B-94 cần cho ca huỷ giữa chừng. Hai đường, một chỗ cắm.

    **Phần prompt cộng `prompt_overhead_tokens`** (B-65) — đúng như
    `estimator.py` làm cho `est_in`. Nếu không thì với một model 9Router, dự
    toán tính ~2000 token provider tự bơm còn sổ sách thì không, và hai cửa của
    cùng §10.2 sẽ nói hai chuyện khác nhau về cùng một lượt chat.

    **Phần output đếm cả `reasoning`.** `deepseek-flash` tiêu `max_tokens` cho
    reasoning **trước** khi sinh `content` (B-33), và provider tính nó vào
    `completion_tokens` (nó nằm trong `completion_tokens_details`). Bỏ ra là
    ghi 0 đồng cho một lượt sinh 112 chunk reasoning rồi bị huỷ — đúng ca đã
    quan sát được ở DoD T-1.9.

    `count_message` (chứ không `count_text` cho từng mảnh) để khối `tool_calls`
    đi qua **đúng** quy ước `json.dumps` của `llm/tokens.py` thay vì một quy
    ước thứ hai viết ở đây (A3). Cái giá: thừa `TOKENS_PER_MESSAGE` + vài token
    khung của vai `assistant`, tức ~4 token ≈ 5e-6 USD ở giá đắt nhất trong
    catalog. Thừa chứ không thiếu — cùng chiều an toàn §10.2 đã chọn.
    """
    if usage is not None:
        return Spent(
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            # `None` = provider KHÔNG báo trường này (NQ-23), khác hẳn báo và
            # bằng 0. Không báo ⇒ không có token nào trúng cache mà mình biết,
            # nên tính cả `prompt_tokens` theo giá cache-miss: đoán ngược lại
            # là tự giảm hoá đơn của mình bằng một con số không ai gửi.
            cached_tokens=usage.cached_prompt_tokens or 0,
            measured=True,
        )

    cat = catalog.get_catalog()
    prompt = _count_prompt(model, sent) + cat.prompt_overhead_tokens(model.id)
    output = count_message(
        {"role": MessageRole.ASSISTANT.value, "content": content, "tool_calls": tool_calls},
        model_id=model.id,
    ) + count_text(reasoning, model_id=model.id)
    return Spent(prompt_tokens=prompt, completion_tokens=output, cached_tokens=0, measured=False)


def cost_of(rates: catalog.PricingRates | None, spent: Spent) -> Decimal:
    """`cost_usd` của một lượt sinh, đã ép về đúng `NUMERIC(12,6)`.

    Thuần tính toán: không Redis, không Postgres, không catalog. Nhờ vậy phép
    nhân tiền — thứ A7 đòi đúng tới 1e-6 — kiểm được mà không phải dựng một
    lượt sinh giả. Cùng lý lẽ đã tách `estimate()` khỏi `check_quota()`.

    `rates is None` ⇒ **0 USD**, không phải một ngoại lệ: model chưa ai điền
    giá (`manual_pricing` còn trống, B-65) vẫn chạy được và vẫn sinh ra một
    dòng sổ, chỉ là dòng ấy ghi 0. `_warn_model_without_price` của catalog
    là chỗ gọi tên những model như vậy lúc nạp.

    `cached_input_per_1m is None` ⇒ tính phần trúng cache theo **giá thường**:
    `None` nghĩa là "provider không bán cache" (`PricingRates`), nên nếu họ vẫn
    báo `cached_tokens` thì những token ấy vẫn là token input tính tiền đầy đủ.
    """
    if rates is None:
        return quantize_cost(Decimal(0))

    # Kẹp vào `prompt_tokens`: một provider báo `cached > prompt` là dữ liệu
    # hỏng, và để nó chạy tiếp sẽ cho ra `uncached` âm, tức một khoản TRỪ tiền.
    cached = min(max(spent.cached_tokens, 0), max(spent.prompt_tokens, 0))
    uncached = max(spent.prompt_tokens, 0) - cached
    cached_rate = (
        rates.input_per_1m if rates.cached_input_per_1m is None else rates.cached_input_per_1m
    )

    total = (
        Decimal(uncached) * Decimal(str(rates.input_per_1m))
        + Decimal(cached) * Decimal(str(cached_rate))
        + Decimal(max(spent.completion_tokens, 0)) * Decimal(str(rates.output_per_1m))
    ) / TOKENS_PER_PRICE_UNIT
    return quantize_cost(total)


def confidence_of(model: catalog.ModelEntry, spent: Spent) -> CostConfidence:
    """`exact` chỉ khi provider vừa báo giá đáng tin vừa báo token — xem docstring module."""
    if model.is_metered and spent.measured:
        return CostConfidence.EXACT
    return CostConfidence.LOW


def snapshot_of(
    model: catalog.ModelEntry, rates: catalog.PricingRates | None, at: datetime
) -> dict[str, Any]:
    """Bảng giá đóng băng vào hàng — A7, ADR-08, §17.2.

    A7: *"Chi phí snapshot vào `usage_events` tại thời điểm gọi. Đổi giá trong
    catalog KHÔNG được làm đổi lịch sử."* Cách duy nhất giữ được lời hứa ấy là
    chép **con số**, không chép một con trỏ tới catalog.

    Bốn khoá đầu là bốn mức giá của `PricingRates`. Ba khoá còn lại là phần trả
    lời câu "vì sao lại là những con số này", và mỗi khoá đóng một lỗ hổng
    thật:

    * `at` — `deepseek-flash` bán theo **khung giờ** (B-35): 0.30 USD/1M lúc
      09:00 và 0.15 lúc 22:00. Không ghi thời điểm thì sáu tháng sau không ai
      nói được dòng này đã rơi vào khung nào, và phép đối chiếu hoá đơn của
      B-151 không có gì để bám.
    * `source` — giá **niêm yết** hay giá người vận hành **tự đoán** (B-65,
      §9.5). C16 bắt admin panel tách hai cột; cột `cost_confidence` trả lời
      "đáng tin tới đâu", khoá này trả lời "con số đến từ đâu".
    * `catalog_version` — `config/model_catalog.json` đã lên `version: 3` qua
      hai lần đổi hình dạng (B-35, B-65). Một dòng sổ đọc lại mà không biết nó
      được ghi dưới schema nào là một dòng không tự giải thích được.

    `cache_write_per_1m` được chép dù công thức chưa dùng tới — xem docstring
    module.
    """
    return {
        "input_per_1m": None if rates is None else rates.input_per_1m,
        "output_per_1m": None if rates is None else rates.output_per_1m,
        "cached_input_per_1m": None if rates is None else rates.cached_input_per_1m,
        "cache_write_per_1m": None if rates is None else rates.cache_write_per_1m,
        "pricing_mode": model.pricing_mode,
        "source": catalog.get_catalog().pricing_source(model.id),
        "catalog_version": catalog.get_catalog().version,
        "at": at.isoformat(),
    }


async def record_usage(
    session: AsyncSession,
    redis: Redis,
    *,
    user_id: uuid.UUID,
    message_id: uuid.UUID,
    model: catalog.ModelEntry,
    at: datetime,
    now: float,
    usage: Usage | None,
    sent: list[dict[str, Any]],
    content: str,
    reasoning: str,
    tool_calls: list[dict[str, Any]] | None,
    key_source: KeySource = KeySource.SYSTEM,
    purpose: UsagePurpose = UsagePurpose.CHAT,
) -> UsageRecord:
    """Ghi sổ một lượt sinh đã khép: `INSERT usage_events` rồi `ZADD` hai cửa sổ.

    Đây là hàm mà `workers/generate.py` gọi ở bước ⑥.5, giữa lúc ghi
    `messages` và lúc `XADD done`.

    **Postgres TRƯỚC, Redis SAU, và thứ tự ấy là hợp đồng.** §10.3 nói *"Redis
    là cache, Postgres là sự thật"*. Ghi Redis trước rồi Postgres hỏng sẽ để
    lại một khoản tiền trong ZSET mà không dòng sổ nào giải thích được — và
    `rebuild_quota` của T-2.13, thứ dựng lại ZSET **từ** `usage_events`, sẽ âm
    thầm xoá nó đi ở lần chạy đầu tiên. Ngược lại thì hỏng theo chiều lành: dòng
    sổ có, ZSET thiếu, và `rebuild_quota` vá được.

    **`at` và `now` là hai tham số riêng, không phải một.** `at` là thời điểm
    **gọi model** (dùng để tra bảng giá theo khung giờ — A7); `now` là thời
    điểm **ghi sổ** (dùng làm `score` của ZSET, tức mốc mà cửa sổ trượt so
    sánh). Một lượt sinh dài mười phút có thể bắt đầu lúc 16:58 giờ cao điểm
    và kết thúc lúc 17:08 giờ thường: giá phải là giá 16:58, còn cửa sổ 5 giờ
    phải đếm từ 17:08. Gộp hai cái thành một tham số là chọn sai một trong hai.

    **`purpose` là vế thứ hai của "có `ZADD` hay không" (T-S.7, §24.2b·S6).**
    Lượt đặt tên hội thoại (`title`) đi bằng system key mà vẫn **không** trừ
    quota. Mặc định `chat` là mặc định chặt hơn: một đường ghi sổ mới quên
    khai `purpose` thì trừ quota thừa, không chạy miễn phí — cùng chiều với
    `key_source`. Nửa đọc của luật này ở `UsageEventRepository` (ba câu dựng
    lại quota lọc `purpose=chat`); hai nửa phải đi cùng nhau, nếu không lần
    `rebuild_quota` đầu tiên trả lại đúng khoản vừa được tha.

    Raise:
        Ngoại lệ của Postgres hoặc Redis đi thẳng ra ngoài. Chỗ gọi mới biết
        một lượt sinh đã xong có được phép chết vì lỗi ghi sổ hay không — cùng
        lối `read_window`/`add_to_windows`.
    """
    rates = catalog.get_catalog().effective_pricing(model.id, at)
    spent = measure(
        model, usage=usage, sent=sent, content=content, reasoning=reasoning, tool_calls=tool_calls
    )
    cost = cost_of(rates, spent)
    confidence = confidence_of(model, spent)

    event = await UsageEventRepository(session).record(
        user_id=user_id,
        message_id=message_id,
        model_id=model.id,
        provider=model.provider,
        key_source=key_source,
        prompt_tokens=spent.prompt_tokens,
        completion_tokens=spent.completion_tokens,
        cached_tokens=spent.cached_tokens,
        cost_usd=cost,
        cost_confidence=confidence,
        price_snapshot=snapshot_of(model, rates, at),
        purpose=purpose,
        # B-32 — đã đo, không lấy được. Xem docstring module.
        upstream_model_reported=None,
    )

    # §10.5: request BYOK **không** trừ quota, nhưng vẫn có dòng sổ ở trên để
    # người dùng tự xem chi tiêu. Từ T-2.15 nhánh này chạy thật:
    # `workers/generate.py` chở `key_source` xuống từ `llm/credentials.py`.
    # Luật vẫn ở đây — chỗ duy nhất biết cả hai vế — chứ không ở chỗ gọi, nên
    # một đường ghi sổ thứ hai sinh ra sau này không thể quên nó (B-157).
    # T-S.7 thêm vế thứ hai theo đúng lối ấy: lượt đặt tên không trừ quota.
    if key_source is KeySource.SYSTEM and purpose is UsagePurpose.CHAT:
        await add_to_windows(redis, user_id=user_id, usage_id=event.id, cost_usd=cost, now=now)

    return UsageRecord(id=event.id, cost_usd=cost, confidence=confidence, spent=spent)


# ─────────────────────────── phần trong của file ───────────────────────────


def _count_prompt(model: catalog.ModelEntry, sent: list[dict[str, Any]]) -> int:
    """Token của ngữ cảnh đã gửi lên, theo đúng phép đếm của `llm/tokens.py`.

    Tách ra một hàm vì `sent` rỗng là một ca có thật — lượt sinh chết trước khi
    `_prepare` kịp dựng ngữ cảnh — và `count_messages` trên danh sách rỗng vẫn
    trả `TOKENS_REPLY_PRIMING`, tức một con số khác 0 cho một request chưa từng
    được gửi.
    """
    if not sent:
        return 0
    return count_messages(sent, model_id=model.id)
