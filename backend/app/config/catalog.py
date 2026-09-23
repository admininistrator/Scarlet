"""Model catalog — nạp, validate, cache `config/model_catalog.json` (§9.2, §9.3, ADR-12).

KH tham chiếu: §9.2, §9.3, ADR-12 · CLAUDE.md A3.

File JSON là nguồn sự thật cho danh sách model/provider/giá (§19.1). Module này
là nơi DUY NHẤT app đọc file đó. `get_catalog()` chỉ trả về bản đã cache trong
bộ nhớ — không đọc đĩa mỗi lần gọi (Cạm bẫy của T-0.7: mỗi lần mở Model Picker
không phải là một lần đọc đĩa). Nạp lại tường minh qua `reload()`.

Catalog được nạp ngay lúc import (fail-fast, cùng tinh thần L2 với
`app/config/settings.py`): catalog sai schema → app không boot.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.config.settings import HttpUrlStr

logger = logging.getLogger(__name__)

#: `config/` nằm ở gốc repo, mounted riêng ngoài image (§23) — không phải biến
#: môi trường vì đây là một cấu trúc thư mục cố định, không phải giá trị hạ
#: tầng thay đổi theo triển khai.
CATALOG_PATH = Path(__file__).resolve().parents[3] / "config" / "model_catalog.json"

#: Mẫu số của mọi con số giá trong catalog (`*_per_1m`). Sống ở đây chứ không
#: ở `app/quota/`: đơn vị là một thuộc tính của **dữ liệu**, và hai chỗ tính
#: tiền (`quota/estimator.py` chặn trước, `quota/meter.py` ghi sau) phải chia
#: cho đúng một con số. `Decimal` chứ không `1e6` — trộn một `float` vào phép
#: nhân tiền là mời sai số nhị phân vào đúng chỗ A7 đòi chính xác.
TOKENS_PER_PRICE_UNIT = Decimal(1_000_000)

#: Giá trị `pricing_mode` nghĩa là "provider báo chi phí đáng tin" (§9.5). Có
#: tên vì `ModelEntry.is_metered` và `_pricing_required_when_metered` cùng hỏi
#: nó; chuỗi này KHÔNG được rời khỏi file catalog (xem `ModelEntry.is_metered`).
PRICING_MODE_METERED = "metered"

#: `pricing_mode` của một model đã điền giá ước lượng cố định (§9.5).
PRICING_MODE_FLAT = "flat"

AuthStyle = Literal["bearer", "x-api-key", "query"]
Availability = Literal["always", "host-dependent"]
CostReporting = Literal["exact", "unreliable"]
PricingMode = Literal["metered", "unmetered", "flat"]
#: Xuất xứ của con số giá — xem `Catalog.pricing_source`.
PricingSource = Literal["catalog", "manual", "none"]
Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

#: Tên thứ trong JSON, KHÔNG phải số: "0" là thứ Hai hay Chủ nhật thì tuỳ thư
#: viện, và một khung giờ lệch một ngày trong bảng giá không ai nhìn thấy cho
#: tới lúc đối chiếu hoá đơn. Giá trị khớp `datetime.weekday()` (thứ Hai = 0).
_WEEKDAY_INDEX: dict[str, int] = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}

#: Segment cuối của `base_url` phải là một phiên bản API (`/v1`, `/v2`,
#: `/v1beta`). Xem `_base_url_has_version` bên dưới cho lý do (C43).
_VERSION_SEGMENT = re.compile(r"^v\d+[a-z]*$")


class Provider(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    base_url: HttpUrlStr
    availability: Availability
    byok_supported: bool
    cost_reporting: CostReporting
    #: Thiếu → mặc định `bearer` (C44).
    auth_style: AuthStyle = "bearer"
    #: Thiếu → BYOK lưu key mà không kiểm được (C42); cảnh báo lúc nạp catalog.
    verify_path: str | None = None
    health_path: str | None = None
    #: Header BẮT BUỘC khác header xác thực, do provider đòi (B-166, T-2.15).
    #:
    #: Trường này ra đời vì một phép đo: `GET https://api.anthropic.com/v1/models`
    #: trả `400 "anthropic-version: header is required"` với **cả** hai
    #: `auth_style` đang có, nên `byok_supported: true` của provider ấy là một
    #: lời hứa không giữ được. Tên header và giá trị của nó là **dữ liệu của
    #: provider**, đúng loại thứ A3 bắt sống trong catalog — ghi một `if` cho
    #: một provider vào `byok_verify.py` là mở lại đúng cửa đó.
    #:
    #: Đi vào **cả hai** đường dùng khoá BYOK và phải đi cả hai: đường KIỂM
    #: (`llm/byok_verify.py`) và đường GỌI (`llm/adapters/byok.py`). Thiếu một
    #: vế thì lưu được khoá mà không chat được, hoặc ngược lại.
    #:
    #: **Không bao giờ mang credential.** Khoá đi qua `auth_style` — một
    #: đường, một chỗ để soi (C20). Header xác thực được gắn **sau** khối này
    #: nên một `Authorization` viết nhầm vào đây cũng không ghi đè được nó.
    extra_headers: dict[str, str] = Field(default_factory=dict)


class PricingWindow(BaseModel):
    """Một khung giờ trong ngày, theo giờ địa phương của `PricingSchedule`."""

    model_config = ConfigDict(extra="forbid")

    start: time
    end: time

    @model_validator(mode="after")
    def _start_before_end(self) -> PricingWindow:
        """Khung qua nửa đêm (`22:00`–`02:00`) bị từ chối, không bị hiểu sai.

        Bảng giá hôm nay không có khung nào như vậy. Chấp nhận nó nghĩa là
        `contains()` phải đổi sang phép so sánh vòng — mà một phép so sánh
        vòng viết đúng cho dữ liệu không tồn tại là một phép so sánh không ai
        kiểm được. Ngày cần tới, tách thành hai khung rồi mở luật này ra.
        """
        if self.start >= self.end:
            raise ValueError(
                f"khung giờ {self.start}–{self.end} không hợp lệ: start phải < end "
                f"(khung qua nửa đêm phải tách làm hai)"
            )
        return self

    def contains(self, at: time) -> bool:
        """Nửa khoảng `[start, end)`.

        Đúng 11:00 thuộc giờ nghỉ trưa chứ không thuộc khung sáng — nếu không,
        hai khung liền nhau sẽ chồng lên nhau đúng một thời điểm và thời điểm
        ấy có hai giá.
        """
        return self.start <= at < self.end


class PricingSchedule(BaseModel):
    """Tập khung giờ mà một bảng giá phụ thuộc vào (B-35).

    Sống ở mức catalog chứ không nằm trong từng model: hai model của cùng một
    provider dùng chung một khung giờ, và chép nó hai lần là hai chỗ để lệch.

    `timezone` là tên IANA, không phải một độ lệch số. Việt Nam không có DST
    nên hôm nay `+07:00` cũng cho cùng kết quả, nhưng một provider có DST thì
    độ lệch số sẽ sai đúng hai lần mỗi năm, mỗi lần một tiếng — và sai ở đây
    nghĩa là tính sai tiền, im lặng.
    """

    model_config = ConfigDict(extra="forbid")

    label: str
    timezone: str
    weekdays: list[Weekday] = Field(min_length=1)
    windows: list[PricingWindow] = Field(min_length=1)

    @model_validator(mode="after")
    def _timezone_must_exist(self) -> PricingSchedule:
        """Tên múi giờ sai → app KHÔNG boot (L2), không phải tính sai tiền lúc chạy."""
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"timezone '{self.timezone}' không phải tên IANA hợp lệ") from exc
        return self

    def contains(self, at: datetime) -> bool:
        """`at` có rơi vào khung giờ này không (sau khi đổi sang giờ địa phương).

        Raise:
            ValueError: `at` không mang múi giờ. Một `datetime` trần ở đây là
                giờ của *máy chủ* — mà container chạy UTC còn bảng giá viết
                theo giờ Việt Nam, nên nhận bừa nó là lệch đúng 7 tiếng và
                lệch im lặng. Nổ to rẻ hơn nhiều.
        """
        if at.tzinfo is None:
            raise ValueError("`at` phải mang múi giờ (aware datetime), không nhận datetime trần")
        local = at.astimezone(ZoneInfo(self.timezone))
        if local.weekday() not in {_WEEKDAY_INDEX[day] for day in self.weekdays}:
            return False
        return any(window.contains(local.time()) for window in self.windows)


class PricingRates(BaseModel):
    """Bốn mức giá của một model, USD trên **1 triệu token** (B-35).

    Ba mức đầu là ba khoản của công thức §10.2 (`in*in_price +
    out*out_price + cached*cached_price`). Khoản thứ tư,
    `cache_write_per_1m`, là thứ công thức đó chưa biết tới: Anthropic thu
    riêng tiền **ghi** cache ($1.25/MTok cho Haiku) bên cạnh tiền **đọc**
    ($0.10/MTok), còn DeepSeek thì không — giá "cache miss" của họ đã là giá
    input thường.

    Vì vậy `input_per_1m` là giá của token **không** trúng cache (DeepSeek gọi
    là "cache miss"), và `cached_input_per_1m` là giá token **trúng** cache
    ("cache hit" của DeepSeek, "cache read" của Anthropic).

    `None` nghĩa là "provider không thu khoản này", khác `0.0` nghĩa là
    "provider thu 0 USD cho khoản này". Giữ được khác biệt đó thì
    `usage_events.price_snapshot` (A7) đọc lại sau này còn biết hôm ấy provider
    có bán cache hay không, thay vì thấy một số 0 không giải thích được.
    """

    model_config = ConfigDict(extra="forbid")

    input_per_1m: float = Field(gt=0)
    output_per_1m: float = Field(gt=0)
    cached_input_per_1m: float | None = Field(default=None, ge=0)
    cache_write_per_1m: float | None = Field(default=None, ge=0)


class OffPeakPricing(PricingRates):
    """Bảng giá thứ hai, có hiệu lực **ngoài** khung giờ `schedule` (B-35).

    DeepSeek bán theo hai khung giờ: trong giờ cao điểm một giá, ngoài giờ cao
    điểm một giá rẻ hơn. Hai bảng giá viết **tường minh** chứ không phải một hệ
    số nhân, dù hôm nay off-peak đúng bằng một nửa peak: tỉ lệ ấy là một sự
    trùng hợp của bảng giá hiện tại, không phải một luật của provider, và ngày
    họ đổi một vế thì một hệ số nhân sẽ im lặng sai cả ba khoản.
    """

    model_config = ConfigDict(extra="forbid")

    #: Tên một mục trong `Catalog.pricing_schedules`.
    schedule: str


class Pricing(PricingRates):
    """Giá **cao điểm** của một model, cộng bảng giá ngoài giờ nếu có.

    **Giá ở mức trên cùng là mức ĐẮT nhất, có chủ ý.** Một chỗ nào đó đọc
    `model.pricing.input_per_1m` mà quên hỏi giờ giấc sẽ ước tính *thừa* chứ
    không *thiếu* — đúng chiều an toàn mà §10.2 đã chọn cho cửa chặn trước
    ("chặn theo tình huống xấu nhất"). Ngả ngược lại (mức trên cùng là giá rẻ,
    `peak` là khối phụ) cho ra một cửa chặn hở đúng vào giờ hành chính.
    """

    model_config = ConfigDict(extra="forbid")

    off_peak: OffPeakPricing | None = None


class ManualPricing(BaseModel):
    """Giá **ước lượng do người vận hành tự điền** cho một model (B-65, §9.5).

    Khác `Pricing` ở ngay chỗ quan trọng nhất: `Pricing` là giá **niêm yết**
    chép từ trang giá của provider, còn khối này là một **con số đoán** cho
    model mà provider không bán theo token hoặc không báo giá đáng tin.
    §9.5 gọi đúng tên ca này: 9Router tự fallback sang tier khác nên model trả
    lời có thể không phải model đã yêu cầu, và số token báo về có thể đã bị
    RTK nén — hai lý do khiến giá trong `models[].pricing` sẽ **sai**.

    **Vì sao là một khối RIÊNG chứ không điền thẳng vào `models[].pricing`.**
    Hai con số có cùng đơn vị nhưng khác hẳn về thẩm quyền: một cái đối chiếu
    được với hoá đơn (S13), một cái thì không. Trộn chúng vào cùng một trường
    là xoá mất khác biệt ấy ngay tại chỗ duy nhất còn đọc được nó — và C16 nói
    thẳng rằng phép tách `metered`/`unmetered` phải làm **từ đây**, không phải
    sửa ở tầng hiển thị.

    **Cả bốn mức giá đều `None` được, và `None` nghĩa là "chưa điền".** Model
    chưa điền giá thì `effective_pricing()` trả `None` ⇒ cửa chặn §10.2 coi nó
    là **0 USD** và quota không trừ. Đó là ca đúng cho model chạy tại chỗ
    (Ollama, 0 USD thật) và là một lỗ hổng tạm cho model 9Router — nên lúc nạp
    catalog app in một dòng WARNING gọi đúng tên từng model chưa có giá
    (`_warn_model_without_price`).

    **`input_per_1m` và `output_per_1m` phải điền CẢ HAI hoặc để trống cả
    hai.** Điền một nửa là một lỗi gõ, không phải một trạng thái: nửa còn
    thiếu sẽ lặng lẽ thành 0 và cho ra một dự toán mà không ai từng viết ra.
    Cùng chiều với `merge_override` của `app/quota/tiers.py` — bản ghi đè hỏng
    thì rơi **cả** bản, không rơi một nửa.
    """

    model_config = ConfigDict(extra="forbid")

    input_per_1m: float | None = Field(default=None, gt=0)
    output_per_1m: float | None = Field(default=None, gt=0)
    cached_input_per_1m: float | None = Field(default=None, ge=0)
    cache_write_per_1m: float | None = Field(default=None, ge=0)
    #: Số token provider tự bơm thêm vào **mọi** request, không nằm trong ngữ
    #: cảnh Scarlet gửi lên. 9Router đo được ~2000 (B-65: prompt 15 token cho
    #: `prompt_tokens` = 2015/2032/2089/2092 trong bốn lần gọi). Bộ ước tính
    #: của §10.2 cộng nó vào `est_in` **trước** khi nhân giá; để trống = 0.
    prompt_overhead_tokens: int | None = Field(default=None, ge=0)
    #: Chỗ ghi con số này đến từ đâu. Không ai đọc bằng code — và đó là điểm:
    #: một giá ước lượng không có xuất xứ thì sáu tháng sau không ai dám sửa.
    note: str | None = None

    @model_validator(mode="after")
    def _main_fields_together(self) -> ManualPricing:
        if (self.input_per_1m is None) != (self.output_per_1m is None):
            raise ValueError(
                "manual_pricing: input_per_1m và output_per_1m phải điền CẢ HAI "
                "hoặc để trống cả hai (điền một nửa là một lỗi gõ, không phải "
                "một trạng thái)"
            )
        return self

    def as_rates(self) -> PricingRates | None:
        """Bốn mức giá dưới hình dạng chung `PricingRates`, hoặc `None` nếu chưa điền.

        Trả về đúng kiểu mà `Pricing` trả về, để `effective_pricing()` chỉ có
        **một** kiểu đi ra và tầng gọi không phải hỏi "giá này đến từ đâu".
        Xuất xứ của con số là chuyện của `cost_confidence` ở T-2.12, không phải
        của phép nhân.
        """
        if self.input_per_1m is None or self.output_per_1m is None:
            return None
        return PricingRates(
            input_per_1m=self.input_per_1m,
            output_per_1m=self.output_per_1m,
            cached_input_per_1m=self.cached_input_per_1m,
            cache_write_per_1m=self.cache_write_per_1m,
        )


class ModelEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    display_name: str
    provider: str
    upstream_model: str
    capabilities: list[str] = Field(default_factory=list)
    context_window: int = Field(gt=0)
    max_output: int = Field(gt=0)
    pricing: Pricing | None = None
    pricing_mode: PricingMode
    enabled: bool = True
    default: bool = False
    order: int = 0
    badge: str | None = None

    @property
    def is_metered(self) -> bool:
        """Provider có báo chi phí **đáng tin** cho model này không (§9.5).

        Là một thuộc tính ở đây chứ không phải phép so sánh `pricing_mode ==
        "metered"` rải ở tầng app, vì đó đúng là chỗ C16 nói phải tách:
        *"trộn chung model `metered` và `unmetered` vào một con số làm bảng chi
        phí vô nghĩa — phải tách từ đây, không phải sửa ở tầng hiển thị"*.
        `app/quota/meter.py` dịch câu trả lời này thành `cost_confidence`, và
        nó làm được điều đó mà không cần biết chuỗi `"metered"` trông ra sao.
        """
        return self.pricing_mode == PRICING_MODE_METERED

    @property
    def provider_model(self) -> str:
        """Tên model mà **chính provider** hiểu — đường BYOK gọi thẳng (§9.1, T-2.15).

        Hai đường gọi, hai cái tên khác nhau, và đó không phải chuyện tuỳ chọn:

        * `SystemAdapter` đi qua LiteLLM, nên tên phải là **alias** trong
          `config/litellm.config.yaml` — chính là `id` ở trên.
        * `ByokAdapter` gọi thẳng `provider.base_url`, nơi LiteLLM không có
          mặt để dịch, nên tên phải là tên gốc của provider.

        `upstream_model` viết theo quy ước `<provider litellm>/<tên gốc>`
        (`deepseek/deepseek-flash`, `openai/ag/gemini-3.8-flash-low`) — đó là
        **định dạng của LiteLLM**, và thứ nó bỏ đi trước khi gửi đi cũng đúng
        là đoạn đầu ấy. Cắt ở dấu `/` **đầu tiên** chứ không phải dấu cuối:
        phần còn lại của 9Router (`ag/gemini-3.8-flash-low`) tự nó có một dấu
        gạch chéo, và cắt ở dấu cuối sẽ vứt mất tiền tố `ag/` mà provider đòi.

        Không có dấu `/` nào ⇒ trả nguyên văn: một provider OpenAI-compatible
        khai tên trần vẫn gọi được, không cần một trường thứ hai trong catalog.

        Đây là **suy ra**, không phải một cột dữ liệu mới, vì hai tên ấy hôm
        nay luôn là một chuỗi và một tiền tố của nó — thêm một trường là thêm
        một chỗ để hai giá trị lệch nhau trong im lặng. Ngày một provider phá
        quy ước đó thì mới đáng đổi (Backlog).
        """
        _, sep, after_prefix = self.upstream_model.partition("/")
        return after_prefix if sep else self.upstream_model

    @model_validator(mode="after")
    def _pricing_required_when_metered(self) -> ModelEntry:
        if self.is_metered and self.pricing is None:
            raise ValueError(
                f"model '{self.id}': pricing bắt buộc khi pricing_mode='{PRICING_MODE_METERED}'"
            )
        return self


class Catalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    providers: dict[str, Provider]
    models: list[ModelEntry]
    #: Vắng mặt = không model nào bán theo khung giờ (B-35).
    pricing_schedules: dict[str, PricingSchedule] = Field(default_factory=dict)
    #: Giá người vận hành tự điền, khoá theo `ModelEntry.id` (B-65). Vắng mặt =
    #: chưa model nào cần tới. Xem `ManualPricing`.
    manual_pricing: dict[str, ManualPricing] = Field(default_factory=dict)

    @field_validator("manual_pricing", mode="before")
    @classmethod
    def _drop_comment_keys(cls, raw: object) -> object:
        """Khoá bắt đầu bằng `_` là chú thích cho người đọc, không phải dữ liệu.

        JSON không có cú pháp chú thích, mà khối này là khối **người** sửa
        thường xuyên nhất trong cả file — hướng dẫn dùng nó phải nằm ngay cạnh
        nó, không phải trong một file `.md` mà người đang sửa giá không mở.
        Quy ước `_ten` là cách duy nhất viết được ghi chú vào JSON chuẩn, và
        nó bị bóc ở đây thay vì được khai thành trường: khai thành trường thì
        thêm một dòng hướng dẫn lại phải sửa cả code.
        """
        if isinstance(raw, dict):
            return {key: value for key, value in raw.items() if not str(key).startswith("_")}
        return raw

    @model_validator(mode="after")
    def _manual_pricing_targets_model(self) -> Catalog:
        """Cùng luật với `_provider_must_exist`: một tên gõ sai phải chết lúc nạp.

        Một khoá `manual_pricing` không khớp `id` nào là một bảng giá **không
        bao giờ được đọc** — nó không làm gì sai, nó chỉ không làm gì cả, và
        người điền sẽ tin là đã điền. Đây đúng là kiểu hỏng mà một con số tiền
        không được phép có.

        Và một model không được có **hai** nguồn giá: `models[].pricing` là giá
        niêm yết, `manual_pricing` là giá đoán; có cả hai thì câu "model này
        giá bao nhiêu" có hai câu trả lời, tức A3 bị vi phạm ngay trong file
        cấu hình.
        """
        by_id = {m.id: m for m in self.models}
        for model_id in self.manual_pricing:
            model = by_id.get(model_id)
            if model is None:
                raise ValueError(
                    f"manual_pricing: '{model_id}' không khớp model nào trong catalog "
                    f"({sorted(by_id)})"
                )
            if model.pricing is not None:
                raise ValueError(
                    f"model '{model_id}': vừa có `pricing` (giá niêm yết) vừa có "
                    f"`manual_pricing` (giá tự điền) — hai nguồn giá cho một model"
                )
        return self

    @model_validator(mode="after")
    def _provider_must_exist(self) -> Catalog:
        for m in self.models:
            if m.provider not in self.providers:
                raise ValueError(
                    f"model '{m.id}': provider '{m.provider}' không tồn tại trong "
                    f"providers ({sorted(self.providers)})"
                )
        return self

    @model_validator(mode="after")
    def _schedule_must_exist(self) -> Catalog:
        """Cùng luật với `_provider_must_exist`: một tên gõ sai phải chết lúc nạp.

        Không có phép kiểm này thì `effective_pricing` gặp `KeyError` giữa lúc
        đang tính tiền cho một lượt sinh — tức lỗi rơi vào đúng đường đi tốn
        tiền, và rơi vào đó *sau* khi model đã sinh xong.
        """
        for m in self.models:
            if m.pricing is None or m.pricing.off_peak is None:
                continue
            name = m.pricing.off_peak.schedule
            if name not in self.pricing_schedules:
                raise ValueError(
                    f"model '{m.id}': pricing.off_peak.schedule '{name}' không tồn tại trong "
                    f"pricing_schedules ({sorted(self.pricing_schedules)})"
                )
        return self

    @model_validator(mode="after")
    def _exactly_one_default(self) -> Catalog:
        defaults = [m.id for m in self.models if m.default]
        if len(defaults) != 1:
            raise ValueError(
                f"phải có đúng một model với default:true, tìm thấy {len(defaults)}: {defaults}"
            )
        return self

    @model_validator(mode="after")
    def _base_url_has_version(self) -> Catalog:
        """`base_url` phải là gốc API **đã bao gồm** phiên bản, ví dụ `/v1` (C43).

        SDK `openai` và LiteLLM đều nối thẳng `/chat/completions` vào
        `base_url`. Thiếu `/v1` thì upstream trả `404` dù dán URL vào trình
        duyệt vẫn ra JSON — triệu chứng đánh lạc hướng nhất của C43. Dấu `/`
        cuối đã bị `HttpUrlStr` cắt trước khi tới đây.

        Chấp nhận `v<số>` kèm hậu tố chữ (`v1`, `v2`, `v1beta`) chứ không chỉ
        đúng chuỗi `/v1`: KH C43 viết "đã bao gồm `/v1`" để nói *phải có phiên
        bản*, và ghim cứng `v1` sẽ tự tạo ra một chỗ cứng mới cho provider đặt
        API ở `/v1beta` — đúng loại chỗ cứng mà T-0.12 sinh ra để xoá.
        """
        for name, provider in self.providers.items():
            last = urlsplit(provider.base_url).path.rsplit("/", 1)[-1]
            if not _VERSION_SEGMENT.match(last):
                raise ValueError(
                    f"provider '{name}': base_url phải kết thúc bằng segment phiên bản "
                    f"(ví dụ '/v1'), nhận được '{provider.base_url}' — C43"
                )
        return self

    def effective_pricing(self, model_id: str, at: datetime | None = None) -> PricingRates | None:
        """Bảng giá **đang có hiệu lực** của một model tại thời điểm `at` (B-35).

        Đây là hàm duy nhất trả lời câu "một triệu token của model này giá bao
        nhiêu" — tầng app không tự đọc `model.pricing.input_per_1m` rồi tự hỏi
        giờ giấc, vì như vậy là chép luật khung giờ ra khỏi file này (A3).

        `at` mặc định là **bây giờ theo UTC**, không phải `datetime.now()` trần:
        xem `PricingSchedule.contains`. Truyền `at` tường minh khi tính lại chi
        phí của một lượt sinh trong quá khứ — A7 đòi chi phí được chốt tại thời
        điểm gọi, và một lượt sinh lúc 09:00 phải giữ giá 09:00 kể cả khi hàm
        này được gọi lại lúc nửa đêm.

        **Hai nguồn giá, một câu trả lời (B-65).** `models[].pricing` là giá
        **niêm yết** của provider; `manual_pricing[id]` là giá **ước lượng**
        người vận hành tự điền cho model mà provider không báo giá đáng tin
        (§9.5). `_manual_pricing_targets_model` đã cấm một model có cả hai,
        nên ở đây chúng không bao giờ tranh nhau — và tầng gọi không phải biết
        con số nó nhận được đến từ nguồn nào. Xuất xứ là chuyện của
        `cost_confidence` (T-2.12), không phải của phép nhân.

        Trả `None` khi model **không có giá ở cả hai nguồn**. Tầng gọi đọc nó
        là "0 USD, quota không trừ" — đúng cho model chạy tại chỗ, và là ca mà
        `_warn_model_without_price` gọi tên lúc nạp catalog.

        **KHÔNG lọc `enabled`**, khác `get_model` ngay dưới, và khác có chủ ý:
        `get_model` trả lời "có được *dùng* model này không", còn hàm này trả
        lời "model này giá bao nhiêu". Tắt một model đang hỏng không được phép
        làm mất giá của những lượt sinh nó đã chạy xong — A7 nói lịch sử chi
        phí không đổi theo catalog.
        """
        model = next((m for m in self.models if m.id == model_id), None)
        if model is None:
            return None
        if model.pricing is None:
            manual = self.manual_pricing.get(model_id)
            return manual.as_rates() if manual is not None else None
        off_peak = model.pricing.off_peak
        if off_peak is None:
            return model.pricing
        schedule = self.pricing_schedules[off_peak.schedule]
        moment = at if at is not None else datetime.now(UTC)
        return model.pricing if schedule.contains(moment) else off_peak

    def pricing_source(self, model_id: str) -> PricingSource:
        """Con số giá của model này **đến từ đâu** — giá niêm yết hay giá đoán.

        `effective_pricing()` cố ý không trả lời câu này: tầng nhân tiền không
        được phép rẽ nhánh theo xuất xứ, nếu không thì luật giá lại rải ra
        ngoài file này (A3). Nhưng `usage_events.price_snapshot` **phải** giữ
        nó: A7 nói dòng lịch sử đọc lại sau sáu tháng phải tự giải thích được,
        và "1.00 USD/1M" chép từ trang giá Anthropic khác hẳn "1.00 USD/1M" do
        người vận hành đoán cho một model 9Router (B-65, §9.5). Không giữ khác
        biệt ấy thì C16 không tách được hai cột ở admin panel.

        Ba giá trị, và `_manual_pricing_targets_model` đã cấm một model có cả
        hai nguồn nên chúng loại trừ nhau:

        * `catalog` — `models[].pricing`, giá niêm yết của provider.
        * `manual`  — `manual_pricing[id]`, giá người vận hành tự điền.
        * `none`    — chưa ai điền; `effective_pricing()` trả `None`, chi phí 0.
        """
        model = next((m for m in self.models if m.id == model_id), None)
        if model is None:
            return "none"
        if model.pricing is not None:
            return "catalog"
        manual = self.manual_pricing.get(model_id)
        return "manual" if manual is not None and manual.as_rates() is not None else "none"

    def prompt_overhead_tokens(self, model_id: str) -> int:
        """Token provider tự bơm vào mỗi request, ngoài ngữ cảnh Scarlet gửi (B-65).

        Trả `0` khi không ai điền — cùng lối `effective_pricing`: một ca rỗng,
        không phải hai. `0` là con số **đúng** cho mọi provider hôm nay trừ
        9Router, và con số của 9Router thì chỉ người vận hành đo được (nó đổi
        theo từng lượt: 2015/2032/2089/2092 trong bốn lần gọi).

        Là một hàm của `Catalog` chứ không phải một phép cộng nằm trong bộ ước
        tính, cùng lý do với `effective_pricing`: luật "model này tốn thêm bao
        nhiêu token" sống trong file catalog, không rải ra tầng app (A3).
        """
        manual = self.manual_pricing.get(model_id)
        if manual is None or manual.prompt_overhead_tokens is None:
            return 0
        return manual.prompt_overhead_tokens

    @model_validator(mode="after")
    def _warn_pricing_mode_unchanged(self) -> Catalog:
        """§9.5: điền một giá ước lượng cố định ⇒ `pricing_mode` là `"flat"`.

        WARNING chứ không lỗi, và khác biệt ấy có lý do: không chỗ nào **đọc**
        `pricing_mode` để quyết định giá — `effective_pricing()` là câu trả lời
        duy nhất cho câu hỏi đó, và nó không hỏi cờ này. Cờ chỉ mang nghĩa §9.5
        ("provider báo chi phí đáng tin tới đâu"), thứ T-2.12 dịch thành
        `cost_confidence`. Để app chết vì một cái nhãn lệch là chặn người vận
        hành ở đúng lúc họ vừa điền xong giá.
        """
        mismatched = [
            m.id
            for m in self.models
            if m.id in self.manual_pricing
            and self.manual_pricing[m.id].as_rates() is not None
            and m.pricing_mode != PRICING_MODE_FLAT
        ]
        if mismatched:
            logger.warning(
                "model %s đã có giá trong manual_pricing nhưng pricing_mode vẫn là "
                "'unmetered' — §9.5 gọi ca 'một giá ước lượng cố định' là 'flat'",
                ", ".join(sorted(mismatched)),
            )
        return self

    @model_validator(mode="after")
    def _warn_model_without_price(self) -> Catalog:
        """Gọi đúng tên mọi model đang bật mà **không** có giá nào (B-65).

        Không có giá ⇒ cửa chặn §10.2 tính `est_max = 0` ⇒ quota **không trừ**
        cho model đó. Với Ollama chạy tại chỗ thì đó là sự thật (0 USD). Với
        một model đi qua 9Router thì đó là một lỗ hổng, và lỗ hổng ấy **không
        tự khai** — nó chỉ hiện ra ở cuối tháng. Dòng log này là chỗ nó khai.

        In một dòng cho cả danh sách chứ không mỗi model một dòng: một dòng thì
        đọc được "hôm nay có hai model chưa có giá", n dòng thì thành nhiễu.
        """
        unpriced = [
            (m.id, m.provider, self.providers[m.provider].cost_reporting)
            for m in self.models
            if m.enabled and self.effective_pricing(m.id) is None
        ]
        if unpriced:
            logger.warning(
                "catalog: %d model đang bật KHÔNG có giá, quota sẽ không trừ cho "
                "chúng: %s — điền ở `manual_pricing` nếu muốn trừ quota (B-65)",
                len(unpriced),
                ", ".join(
                    f"{mid} (provider {prov}, cost_reporting={rep})" for mid, prov, rep in unpriced
                ),
            )
        return self

    @model_validator(mode="after")
    def _warn_verify_path_missing(self) -> Catalog:
        for name, provider in self.providers.items():
            if provider.byok_supported and provider.verify_path is None:
                logger.warning(
                    "provider '%s' hỗ trợ BYOK nhưng không có verify_path — "
                    "key BYOK sẽ được lưu mà không kiểm (C42)",
                    name,
                )
        return self


def _read_and_validate(path: Path) -> Catalog:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Catalog.model_validate(raw)


def reload(path: Path = CATALOG_PATH) -> Catalog:
    """Nạp lại catalog từ đĩa và thay bản cache trong bộ nhớ."""
    global _catalog
    _catalog = _read_and_validate(path)
    return _catalog


def get_catalog() -> Catalog:
    """Trả về catalog đã cache — không đọc đĩa."""
    return _catalog


def get_model(model_id: str) -> ModelEntry | None:
    """Model theo `id`, hoặc `None` nếu không có / đã `enabled: false`.

    Tắt một model trong catalog phải làm mọi lượt sinh dùng nó dừng lại có mã
    lỗi, chứ không phải vẫn chạy được vì code chỉ đọc `id`: `enabled` là cái
    công tắc §9.2 dành cho lúc một provider chết, và một công tắc chỉ ảnh hưởng
    Model Picker mà không ảnh hưởng đường gọi thì không phải công tắc.
    """
    return next((m for m in _catalog.models if m.id == model_id and m.enabled), None)


def get_default_model() -> ModelEntry | None:
    """Model dùng khi request không nói dùng model nào (§9.2 `default: true`).

    `Catalog._exactly_one_default` đã bắt phải có **đúng một** model `default`,
    nhưng nó **không** bắt model đó phải `enabled` — tắt một provider đang hỏng
    là chuyện của giờ phút, còn sửa cờ `default` là một quyết định khác. Vì
    vậy hàm vẫn lọc `enabled` và vẫn trả `None` được: ca "model mặc định vừa bị
    tắt" phải thành một mã lỗi mà người dùng đọc được (T-1.8 trả 503), chứ
    không phải một `StopIteration` giữa handler.

    Đây là hàm duy nhất ngoài `get_model` mà tầng app dùng để *chọn* model —
    tầng api không tự duyệt `get_catalog().models` đi tìm cờ `default`, vì như
    vậy là chép luật của §9.2 ra khỏi file này (A3).
    """
    return next((m for m in _catalog.models if m.default and m.enabled), None)


#: Nạp ngay lúc import — fail-fast (L2). Catalog sai schema → app không boot.
_catalog = _read_and_validate(CATALOG_PATH)
