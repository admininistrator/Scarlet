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
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config.settings import HttpUrlStr

logger = logging.getLogger(__name__)

#: `config/` nằm ở gốc repo, mounted riêng ngoài image (§23) — không phải biến
#: môi trường vì đây là một cấu trúc thư mục cố định, không phải giá trị hạ
#: tầng thay đổi theo triển khai.
CATALOG_PATH = Path(__file__).resolve().parents[3] / "config" / "model_catalog.json"

AuthStyle = Literal["bearer", "x-api-key", "query"]
Availability = Literal["always", "host-dependent"]
CostReporting = Literal["exact", "unreliable"]
PricingMode = Literal["metered", "unmetered", "flat"]
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
#: `/v1beta`). Xem `_base_url_co_phien_ban` bên dưới cho lý do (C43).
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


class PricingWindow(BaseModel):
    """Một khung giờ trong ngày, theo giờ địa phương của `PricingSchedule`."""

    model_config = ConfigDict(extra="forbid")

    start: time
    end: time

    @model_validator(mode="after")
    def _start_truoc_end(self) -> PricingWindow:
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
    def _timezone_ton_tai(self) -> PricingSchedule:
        """Tên múi giờ sai → app KHÔNG boot (L2), không phải tính sai tiền lúc chạy."""
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as loi:
            raise ValueError(f"timezone '{self.timezone}' không phải tên IANA hợp lệ") from loi
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

    @model_validator(mode="after")
    def _pricing_bat_buoc_khi_metered(self) -> ModelEntry:
        if self.pricing_mode == "metered" and self.pricing is None:
            raise ValueError(f"model '{self.id}': pricing bắt buộc khi pricing_mode='metered'")
        return self


class Catalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    providers: dict[str, Provider]
    models: list[ModelEntry]
    #: Vắng mặt = không model nào bán theo khung giờ (B-35).
    pricing_schedules: dict[str, PricingSchedule] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _provider_phai_ton_tai(self) -> Catalog:
        for m in self.models:
            if m.provider not in self.providers:
                raise ValueError(
                    f"model '{m.id}': provider '{m.provider}' không tồn tại trong "
                    f"providers ({sorted(self.providers)})"
                )
        return self

    @model_validator(mode="after")
    def _schedule_phai_ton_tai(self) -> Catalog:
        """Cùng luật với `_provider_phai_ton_tai`: một tên gõ sai phải chết lúc nạp.

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
    def _dung_mot_default(self) -> Catalog:
        defaults = [m.id for m in self.models if m.default]
        if len(defaults) != 1:
            raise ValueError(
                f"phải có đúng một model với default:true, tìm thấy {len(defaults)}: {defaults}"
            )
        return self

    @model_validator(mode="after")
    def _base_url_co_phien_ban(self) -> Catalog:
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

        Trả `None` khi model không có giá (`pricing_mode` `unmetered`/`flat`) —
        cùng câu trả lời với `model.pricing is None`, để tầng gọi chỉ phải xử
        lý một ca rỗng chứ không hai.

        **KHÔNG lọc `enabled`**, khác `get_model` ngay dưới, và khác có chủ ý:
        `get_model` trả lời "có được *dùng* model này không", còn hàm này trả
        lời "model này giá bao nhiêu". Tắt một model đang hỏng không được phép
        làm mất giá của những lượt sinh nó đã chạy xong — A7 nói lịch sử chi
        phí không đổi theo catalog.
        """
        model = next((m for m in self.models if m.id == model_id), None)
        if model is None or model.pricing is None:
            return None
        off_peak = model.pricing.off_peak
        if off_peak is None:
            return model.pricing
        schedule = self.pricing_schedules[off_peak.schedule]
        moment = at if at is not None else datetime.now(UTC)
        return model.pricing if schedule.contains(moment) else off_peak

    @model_validator(mode="after")
    def _canh_bao_verify_path_thieu(self) -> Catalog:
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

    `Catalog._dung_mot_default` đã bắt phải có **đúng một** model `default`,
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
