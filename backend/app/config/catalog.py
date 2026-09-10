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
from pathlib import Path
from typing import Literal

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


class Pricing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_per_1m: float = Field(gt=0)
    output_per_1m: float = Field(gt=0)
    cached_input_per_1m: float | None = Field(default=None, ge=0)


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
            raise ValueError(
                f"model '{self.id}': pricing bắt buộc khi pricing_mode='metered'"
            )
        return self


class Catalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    providers: dict[str, Provider]
    models: list[ModelEntry]

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
    def _dung_mot_default(self) -> Catalog:
        defaults = [m.id for m in self.models if m.default]
        if len(defaults) != 1:
            raise ValueError(
                f"phải có đúng một model với default:true, tìm thấy {len(defaults)}: {defaults}"
            )
        return self

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


#: Nạp ngay lúc import — fail-fast (L2). Catalog sai schema → app không boot.
_catalog = _read_and_validate(CATALOG_PATH)
