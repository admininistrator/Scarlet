"""`app/config/catalog.py` — schema, validate, cache, reload (T-0.7 DoD).

KH tham chiếu: §9.2, §9.3, ADR-12. Các case lỗi dùng fixture JSON dựng tay
thay vì sửa `config/model_catalog.json` thật, để không phụ thuộc nội dung
catalog thật khi thêm/bớt model sau này.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.config import catalog
from app.config.catalog import Catalog

VALID: dict[str, Any] = {
    "version": catalog.CATALOG_VERSION,
    "title_model": {"model": "deepseek-flash", "max_output": 64},
    "providers": {
        "deepseek": {
            "label": "DeepSeek AI",
            "base_url": "https://api.deepseek.com/v1",
            "availability": "always",
            "byok_supported": True,
            "cost_reporting": "exact",
            "auth_style": "bearer",
            "verify_path": "/models",
        },
        "anthropic": {
            "label": "Anthropic",
            "base_url": "https://api.anthropic.com/v1",
            "availability": "always",
            "byok_supported": True,
            "cost_reporting": "exact",
        },
    },
    "models": [
        {
            "id": "deepseek-flash",
            "display_name": "DeepSeek Flash",
            "provider": "deepseek",
            "upstream_model": "deepseek/deepseek-flash",
            "capabilities": ["tools"],
            "context_window": 128000,
            "max_output": 8192,
            "pricing": {"input_per_1m": 0.27, "output_per_1m": 1.10},
            "pricing_mode": "metered",
            "enabled": True,
            "default": True,
            "order": 10,
        },
        {
            "id": "claude-haiku",
            "display_name": "Claude Haiku 4.5",
            "provider": "anthropic",
            "upstream_model": "anthropic/claude-haiku-4-5-20251001",
            "capabilities": ["tools", "vision"],
            "context_window": 200000,
            "max_output": 8192,
            "pricing": {"input_per_1m": 1.00, "output_per_1m": 5.00},
            "pricing_mode": "metered",
            "enabled": True,
            "default": False,
            "order": 20,
        },
    ],
}


def test_valid_catalog_loads() -> None:
    cat = Catalog.model_validate(VALID)
    assert len(cat.models) == 2


def test_missing_provider_raises() -> None:
    bad = deepcopy(VALID)
    bad["models"][0]["provider"] = "khong-ton-tai"
    with pytest.raises(ValidationError) as exc:
        Catalog.model_validate(bad)
    message = str(exc.value)
    assert "khong-ton-tai" in message
    assert "deepseek-flash" in message


def test_two_default_models_raise() -> None:
    bad = deepcopy(VALID)
    bad["models"][1]["default"] = True
    with pytest.raises(ValidationError) as exc:
        Catalog.model_validate(bad)
    assert "default" in str(exc.value)


def test_no_default_model_raises() -> None:
    bad = deepcopy(VALID)
    bad["models"][0]["default"] = False
    with pytest.raises(ValidationError) as exc:
        Catalog.model_validate(bad)
    assert "default" in str(exc.value)


def test_metered_without_pricing_raises() -> None:
    bad = deepcopy(VALID)
    bad["models"][0]["pricing"] = None
    with pytest.raises(ValidationError) as exc:
        Catalog.model_validate(bad)
    message = str(exc.value)
    assert "pricing" in message
    assert "deepseek-flash" in message


def test_unmetered_needs_no_pricing() -> None:
    ok = deepcopy(VALID)
    ok["models"][1]["pricing_mode"] = "unmetered"
    ok["models"][1]["pricing"] = None
    cat = Catalog.model_validate(ok)
    assert cat.models[1].pricing is None


def test_base_url_trailing_slash_is_normalized() -> None:
    ok = deepcopy(VALID)
    ok["providers"]["deepseek"]["base_url"] = "https://api.deepseek.com/v1/"
    cat = Catalog.model_validate(ok)
    assert cat.providers["deepseek"].base_url == "https://api.deepseek.com/v1"


def test_base_url_without_version_is_rejected() -> None:
    """C43 — `https://api.deepseek.com` (thiếu `/v1`) phải chết lúc nạp catalog."""
    bad = deepcopy(VALID)
    bad["providers"]["deepseek"]["base_url"] = "https://api.deepseek.com"
    with pytest.raises(ValidationError) as exc:
        Catalog.model_validate(bad)
    message = str(exc.value)
    assert "deepseek" in message
    assert "C43" in message


def test_base_url_ending_in_other_path_is_rejected() -> None:
    """C43 — `/v1/chat/completions` cũng sai: base_url là GỐC API, không phải endpoint."""
    bad = deepcopy(VALID)
    bad["providers"]["deepseek"]["base_url"] = "https://api.deepseek.com/v1/chat/completions"
    with pytest.raises(ValidationError) as exc:
        Catalog.model_validate(bad)
    assert "C43" in str(exc.value)


@pytest.mark.parametrize("base_url", ["http://ollama:11434/v1", "https://x.test/api/v1beta"])
def test_base_url_with_version_is_accepted(base_url: str) -> None:
    ok = deepcopy(VALID)
    ok["providers"]["deepseek"]["base_url"] = base_url
    assert Catalog.model_validate(ok).providers["deepseek"].base_url == base_url


def test_missing_auth_style_defaults_to_bearer() -> None:
    cat = Catalog.model_validate(VALID)
    assert cat.providers["anthropic"].auth_style == "bearer"


def test_missing_verify_path_defaults_to_none_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING", logger="app.config.catalog"):
        cat = Catalog.model_validate(VALID)
    assert cat.providers["anthropic"].verify_path is None
    assert "anthropic" in caplog.text
    assert "C42" in caplog.text


def test_real_catalog_file_valid_with_exactly_one_default() -> None:
    cat = catalog._read_and_validate(catalog.CATALOG_PATH)
    defaults = [m for m in cat.models if m.default]
    assert len(defaults) == 1
    assert defaults[0].id == "deepseek-flash"
    assert defaults[0].provider == "deepseek"


def test_reload_rereads_disk_and_replaces_cache(tmp_path: Path) -> None:
    fixture = tmp_path / "model_catalog.json"
    fixture.write_text(json.dumps(VALID), encoding="utf-8")

    original = catalog.get_catalog()
    try:
        cat = catalog.reload(path=fixture)
        assert cat is catalog.get_catalog()
        assert len(catalog.get_catalog().models) == 2

        changed = deepcopy(VALID)
        changed["models"][0]["display_name"] = "DeepSeek Flash (đổi tên)"
        fixture.write_text(json.dumps(changed), encoding="utf-8")
        catalog.reload(path=fixture)
        assert catalog.get_catalog().models[0].display_name == "DeepSeek Flash (đổi tên)"
    finally:
        catalog.reload(path=catalog.CATALOG_PATH)
        assert catalog.get_catalog() is not None
        # khôi phục cache về catalog thật cho test khác trong cùng tiến trình
        assert original.version == catalog.get_catalog().version


def test_get_catalog_does_not_read_disk(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(path: Path) -> Catalog:
        raise AssertionError("get_catalog() không được đọc đĩa")

    monkeypatch.setattr(catalog, "_read_and_validate", _boom)
    # Không raise nghĩa là không gọi lại _read_and_validate.
    catalog.get_catalog()


# ═══════════════════════ B-35 — giá thật, hai khung giờ ═══════════════════════
#
# `VALID` ở trên cố ý KHÔNG có `pricing_schedules`: nó chứng minh rằng một
# catalog không bán theo khung giờ vẫn nạp được sau B-35 (trường mới có default
# rỗng). Các test dưới đây dựng bản có khung giờ từ chính nó.

PEAK_SCHEDULE: dict[str, Any] = {
    "label": "Giờ cao điểm (giờ Việt Nam)",
    "timezone": "Asia/Ho_Chi_Minh",
    "weekdays": ["mon", "tue", "wed", "thu", "fri"],
    "windows": [
        {"start": "08:00", "end": "11:00"},
        {"start": "13:00", "end": "17:00"},
    ],
}


def _with_time_windows() -> dict[str, Any]:
    """`VALID` + một model bán theo hai khung giờ (giống `deepseek-flash` thật)."""
    data = deepcopy(VALID)
    data["pricing_schedules"] = {"peak-vn": deepcopy(PEAK_SCHEDULE)}
    data["models"][0]["pricing"] = {
        "input_per_1m": 0.30,
        "output_per_1m": 1.20,
        "cached_input_per_1m": 0.006,
        "off_peak": {
            "schedule": "peak-vn",
            "input_per_1m": 0.15,
            "output_per_1m": 0.60,
            "cached_input_per_1m": 0.003,
        },
    }
    return data


def _at(iso: str) -> datetime:
    """Một thời điểm viết theo giờ Việt Nam — đúng cách bảng giá được phát biểu."""
    return datetime.fromisoformat(iso).replace(tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))


def test_catalog_without_pricing_schedules_still_loads() -> None:
    cat = Catalog.model_validate(VALID)
    assert cat.pricing_schedules == {}


def test_missing_schedule_raises() -> None:
    bad = _with_time_windows()
    bad["models"][0]["pricing"]["off_peak"]["schedule"] = "khong-ton-tai"
    with pytest.raises(ValidationError) as exc:
        Catalog.model_validate(bad)
    message = str(exc.value)
    assert "khong-ton-tai" in message
    assert "deepseek-flash" in message


def test_bad_timezone_raises() -> None:
    bad = _with_time_windows()
    bad["pricing_schedules"]["peak-vn"]["timezone"] = "Asia/Khong_Co_That"
    with pytest.raises(ValidationError) as exc:
        Catalog.model_validate(bad)
    assert "Asia/Khong_Co_That" in str(exc.value)


def test_window_crossing_midnight_is_rejected() -> None:
    bad = _with_time_windows()
    bad["pricing_schedules"]["peak-vn"]["windows"] = [{"start": "22:00", "end": "02:00"}]
    with pytest.raises(ValidationError) as exc:
        Catalog.model_validate(bad)
    assert "start phải < end" in str(exc.value)


@pytest.mark.parametrize(
    ("moment", "description"),
    [
        ("2026-09-14T08:00:00", "thứ Hai, đúng lúc mở khung sáng"),
        ("2026-09-14T10:59:59", "thứ Hai, sát cuối khung sáng"),
        ("2026-09-18T13:00:00", "thứ Sáu, đúng lúc mở khung chiều"),
        ("2026-09-18T16:59:59", "thứ Sáu, sát cuối khung chiều"),
    ],
)
def test_peak_returns_expensive_price(moment: str, description: str) -> None:
    cat = Catalog.model_validate(_with_time_windows())
    pricing = cat.effective_pricing("deepseek-flash", _at(moment))
    assert pricing is not None
    assert pricing.input_per_1m == 0.30, description
    assert pricing.output_per_1m == 1.20
    assert pricing.cached_input_per_1m == 0.006


@pytest.mark.parametrize(
    ("moment", "description"),
    [
        ("2026-09-14T07:59:59", "thứ Hai, trước giờ làm"),
        ("2026-09-14T11:00:00", "thứ Hai, đúng lúc nghỉ trưa — biên [start, end)"),
        ("2026-09-14T12:30:00", "thứ Hai, giữa trưa"),
        ("2026-09-18T17:00:00", "thứ Sáu, đúng lúc tan làm"),
        ("2026-09-19T09:00:00", "thứ Bảy, giờ hành chính nhưng cuối tuần"),
        ("2026-09-20T14:00:00", "Chủ nhật"),
    ],
)
def test_off_peak_returns_cheap_price(moment: str, description: str) -> None:
    cat = Catalog.model_validate(_with_time_windows())
    pricing = cat.effective_pricing("deepseek-flash", _at(moment))
    assert pricing is not None
    assert pricing.input_per_1m == 0.15, description
    assert pricing.output_per_1m == 0.60
    assert pricing.cached_input_per_1m == 0.003


def test_hour_boundary_follows_timezone_not_server_clock() -> None:
    """09:00 giờ Việt Nam = 02:00 UTC. Container chạy UTC, bảng giá viết giờ VN."""
    cat = Catalog.model_validate(_with_time_windows())
    monday_morning_utc = datetime(2026, 9, 14, 2, 0, tzinfo=UTC)
    pricing = cat.effective_pricing("deepseek-flash", monday_morning_utc)
    assert pricing is not None
    assert pricing.input_per_1m == 0.30


def test_naive_datetime_is_rejected() -> None:
    cat = Catalog.model_validate(_with_time_windows())
    with pytest.raises(ValueError, match="múi giờ"):
        cat.effective_pricing("deepseek-flash", datetime(2026, 9, 14, 9, 0))  # noqa: DTZ001


def test_model_without_windows_returns_single_price() -> None:
    """`claude-haiku` không bán theo giờ — mọi thời điểm cho cùng một bảng giá."""
    data = _with_time_windows()
    data["models"][1]["pricing"] = {
        "input_per_1m": 1.00,
        "output_per_1m": 5.00,
        "cached_input_per_1m": 0.10,
        "cache_write_per_1m": 1.25,
    }
    cat = Catalog.model_validate(data)
    for moment in ("2026-09-14T09:00:00", "2026-09-20T03:00:00"):
        pricing = cat.effective_pricing("claude-haiku", _at(moment))
        assert pricing is not None
        assert pricing.input_per_1m == 1.00
        assert pricing.cache_write_per_1m == 1.25


def test_unmetered_or_missing_model_has_no_price() -> None:
    data = _with_time_windows()
    data["models"][1]["pricing_mode"] = "unmetered"
    data["models"][1]["pricing"] = None
    cat = Catalog.model_validate(data)
    assert cat.effective_pricing("claude-haiku") is None
    assert cat.effective_pricing("model-khong-ton-tai") is None


def test_disabled_model_still_has_price() -> None:
    """A7: tắt một model không được xoá giá của những lượt sinh nó đã chạy."""
    data = _with_time_windows()
    data["models"][0]["enabled"] = False
    # `title_model` phải trỏ vào một model đang bật (T-S.3) — dời nó đi để ca
    # này vẫn đo đúng một điều: tắt model không xoá giá.
    data["title_model"]["model"] = "claude-haiku"
    cat = Catalog.model_validate(data)
    assert cat.effective_pricing("deepseek-flash", _at("2026-09-14T09:00:00")) is not None


def test_missing_cache_write_is_none_not_0() -> None:
    """DeepSeek không thu tiền ghi cache; Anthropic thu. Hai ca khác nhau."""
    cat = Catalog.model_validate(_with_time_windows())
    pricing = cat.effective_pricing("deepseek-flash", _at("2026-09-14T09:00:00"))
    assert pricing is not None
    assert pricing.cache_write_per_1m is None


# ─────────────── Catalog THẬT: giá do người dùng chốt (B-35) ───────────────


def test_real_catalog_deepseek_two_price_windows() -> None:
    cat = catalog.get_catalog()
    peak = cat.effective_pricing("deepseek-flash", _at("2026-09-14T09:00:00"))
    off = cat.effective_pricing("deepseek-flash", _at("2026-09-14T22:00:00"))
    assert peak is not None
    assert off is not None
    assert (peak.input_per_1m, peak.output_per_1m, peak.cached_input_per_1m) == (0.30, 1.20, 0.006)
    assert (off.input_per_1m, off.output_per_1m, off.cached_input_per_1m) == (0.15, 0.60, 0.003)


def test_real_catalog_claude_haiku_has_cache_write_price() -> None:
    pricing = catalog.get_catalog().effective_pricing("claude-haiku")
    assert pricing is not None
    assert (pricing.input_per_1m, pricing.output_per_1m) == (1.00, 5.00)
    assert (pricing.cached_input_per_1m, pricing.cache_write_per_1m) == (0.10, 1.25)


# ─────────────── Giá tự điền cho provider không báo giá (B-65) ───────────────


def _with_manual_pricing(entry: dict[str, Any] | None = None) -> dict[str, Any]:
    """`VALID` cộng một model `unmetered` (`nr-gemini-flash`) và khối giá tự điền."""
    data = deepcopy(VALID)
    data["providers"]["ninerouter"] = {
        "label": "9Router (local)",
        "base_url": "http://host.docker.internal:20128/v1",
        "availability": "host-dependent",
        "byok_supported": False,
        "cost_reporting": "unreliable",
        "health_path": "/models",
    }
    data["models"].append(
        {
            "id": "nr-gemini-flash",
            "display_name": "Gemini Flash (qua 9Router)",
            "provider": "ninerouter",
            "upstream_model": "openai/ag/gemini-3.8-flash-low",
            "capabilities": [],
            "context_window": 128000,
            "max_output": 8192,
            "pricing": None,
            "pricing_mode": "unmetered",
            "enabled": True,
            "default": False,
            "order": 30,
        }
    )
    if entry is not None:
        data["manual_pricing"] = {"nr-gemini-flash": entry}
    return data


def test_missing_manual_pricing_still_loads() -> None:
    cat = Catalog.model_validate(_with_manual_pricing())
    assert cat.manual_pricing == {}
    assert cat.effective_pricing("nr-gemini-flash") is None


def test_filled_manual_pricing_becomes_model_price() -> None:
    cat = Catalog.model_validate(
        _with_manual_pricing({"input_per_1m": 0.10, "output_per_1m": 0.40})
    )
    pricing = cat.effective_pricing("nr-gemini-flash")
    assert pricing is not None
    assert (pricing.input_per_1m, pricing.output_per_1m) == (0.10, 0.40)


def test_blank_manual_pricing_still_means_no_price() -> None:
    """Ô còn `null` = chưa điền, KHÔNG phải 0 USD đã xác nhận."""
    cat = Catalog.model_validate(
        _with_manual_pricing({"input_per_1m": None, "output_per_1m": None})
    )
    assert cat.effective_pricing("nr-gemini-flash") is None


def test_half_filled_manual_pricing_is_rejected() -> None:
    """Nửa còn thiếu sẽ lặng lẽ thành 0 — đó là lý do nó phải nổ lúc nạp."""
    with pytest.raises(ValidationError) as exc:
        Catalog.model_validate(_with_manual_pricing({"input_per_1m": 0.10}))
    assert "CẢ HAI" in str(exc.value)


def test_manual_pricing_key_matching_no_model_is_rejected() -> None:
    data = _with_manual_pricing({"input_per_1m": 0.10, "output_per_1m": 0.40})
    data["manual_pricing"] = {"go-nham-ten": {"input_per_1m": 0.10, "output_per_1m": 0.40}}
    with pytest.raises(ValidationError) as exc:
        Catalog.model_validate(data)
    assert "go-nham-ten" in str(exc.value)


def test_model_cannot_have_two_price_sources() -> None:
    data = _with_manual_pricing({"input_per_1m": 0.10, "output_per_1m": 0.40})
    data["manual_pricing"] = {"deepseek-flash": {"input_per_1m": 9.0, "output_per_1m": 9.0}}
    with pytest.raises(ValidationError) as exc:
        Catalog.model_validate(data)
    assert "hai nguồn giá" in str(exc.value)


def test_keys_starting_with_underscore_are_comments() -> None:
    data = _with_manual_pricing({"input_per_1m": 0.10, "output_per_1m": 0.40})
    data["manual_pricing"]["_huong_dan"] = "day la chu thich, khong phai mot model"
    cat = Catalog.model_validate(data)
    assert list(cat.manual_pricing) == ["nr-gemini-flash"]


def test_prompt_overhead_parsed_and_defaults_to_0() -> None:
    cat = Catalog.model_validate(
        _with_manual_pricing(
            {"input_per_1m": 0.10, "output_per_1m": 0.40, "prompt_overhead_tokens": 2100}
        )
    )
    assert cat.prompt_overhead_tokens("nr-gemini-flash") == 2100
    assert cat.prompt_overhead_tokens("deepseek-flash") == 0
    assert cat.prompt_overhead_tokens("khong-ton-tai") == 0


def test_warns_when_model_has_no_price(caplog: pytest.LogCaptureFixture) -> None:
    """Lỗ hổng "quota không trừ" phải TỰ KHAI lúc nạp, không đợi cuối tháng."""
    with caplog.at_level("WARNING", logger="app.config.catalog"):
        Catalog.model_validate(_with_manual_pricing())
    assert "nr-gemini-flash" in caplog.text
    assert "cost_reporting=unreliable" in caplog.text


def test_warns_when_priced_but_pricing_mode_unchanged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING", logger="app.config.catalog"):
        Catalog.model_validate(_with_manual_pricing({"input_per_1m": 0.10, "output_per_1m": 0.40}))
    assert "flat" in caplog.text


def test_real_catalog_has_price_slot_for_9router() -> None:
    """File thật phải có sẵn ô trống cho 9Router — đó là sản phẩm của B-65."""
    cat = catalog.get_catalog()
    assert "nr-gemini-flash" in cat.manual_pricing


# ══════════ T-2.15 — `extra_headers` (B-166) và `provider_model` (§9.1) ══════════


def test_missing_extra_headers_is_empty_dict() -> None:
    """Trường mới không được bắt mọi provider cũ phải khai lại (§9.2)."""
    cat = Catalog.model_validate(VALID)
    assert cat.providers["deepseek"].extra_headers == {}


def test_extra_headers_read_from_json() -> None:
    raw = deepcopy(VALID)
    raw["providers"]["anthropic"]["extra_headers"] = {"anthropic-version": "2023-06-01"}
    cat = Catalog.model_validate(raw)
    assert cat.providers["anthropic"].extra_headers == {"anthropic-version": "2023-06-01"}


def test_extra_headers_wrong_type_app_does_not_boot() -> None:
    """Một header không phải chuỗi là một request hỏng lúc chạy — L2 bắt ở đây."""
    raw = deepcopy(VALID)
    raw["providers"]["anthropic"]["extra_headers"] = {"anthropic-version": 20230601}
    with pytest.raises(ValidationError):
        Catalog.model_validate(raw)


def test_real_catalog_anthropic_declares_enough_for_byok() -> None:
    """**B-166 đóng ở T-2.15.** Đo được, không phải một lời hứa trong docstring.

    `GET /v1/models` của Anthropic đòi `anthropic-version` và chỉ nhận
    `x-api-key`; thiếu một trong hai thì `PUT /settings/keys/anthropic` trả
    `503` và một trong hai provider `byok_supported` là không dùng được.
    """
    provider = catalog.get_catalog().providers["anthropic"]
    assert provider.byok_supported
    assert provider.auth_style == "x-api-key"
    assert "anthropic-version" in provider.extra_headers


@pytest.mark.parametrize(
    ("upstream", "expected"),
    [
        ("deepseek/deepseek-flash", "deepseek-flash"),
        ("anthropic/claude-haiku-4-5-20251001", "claude-haiku-4-5-20251001"),
        # 9Router: phần tên gốc TỰ NÓ có một dấu gạch chéo — cắt ở dấu cuối
        # sẽ vứt mất tiền tố `ag/` mà provider đòi.
        ("openai/ag/gemini-3.8-flash-low", "ag/gemini-3.8-flash-low"),
        # Không có tiền tố litellm nào ⇒ nguyên văn.
        ("qwen2.5:0.5b", "qwen2.5:0.5b"),
    ],
)
def test_provider_model_strips_litellm_prefix(upstream: str, expected: str) -> None:
    raw = deepcopy(VALID)
    raw["models"][0]["upstream_model"] = upstream
    cat = Catalog.model_validate(raw)
    assert cat.models[0].provider_model == expected


def test_provider_model_differs_from_id_for_at_least_one_real_model() -> None:
    """Hai tên trùng nhau ở MỌI model thì `Credential.model_name` không đo được."""
    cat = catalog.get_catalog()
    assert any(m.id != m.provider_model for m in cat.models)


# ══════════ T-S.3 — catalog v4: provider hiển thị, `reasoning`, `title_model` ══════════
#
# KH tham chiếu: §24.2b·S3, S14 · NQ-118, NQ-119, NQ-120, NQ-123.

#: Gốc repo — `config/` nằm ở đây, cùng lối `test_compose_calls_right_module`.
REPO_ROOT = Path(__file__).resolve().parents[3]
LITELLM_CONFIG_PATH = REPO_ROOT / "config" / "litellm.config.yaml"

#: `model_name:` của một entry trong `model_list` — đọc bằng chữ, không bằng
#: YAML: backend không phụ thuộc trực tiếp vào một bộ đọc YAML, và phép kiểm
#: này chỉ cần biết một cái tên có mặt hay không.
_MODEL_NAME = re.compile(r"^\s*-\s*model_name:\s*(\S+)\s*$", re.MULTILINE)


def _v4() -> dict[str, Any]:
    """`VALID` + một đường trung gian (`user_visible: false`) và khối `reasoning`."""
    data = deepcopy(VALID)
    data["providers"]["ninerouter"] = {
        "label": "Route trung gian (local)",
        "base_url": "http://host.docker.internal:20128/v1",
        "availability": "host-dependent",
        "byok_supported": False,
        "cost_reporting": "unreliable",
        "health_path": "/models",
        "user_visible": False,
    }
    data["models"].append(
        {
            "id": "nr-gemini-flash",
            "display_name": "Gemini Flash",
            "provider": "ninerouter",
            "display_provider": "Google AI",
            "upstream_model": "openai/ag/gemini-3.8-flash-low",
            "context_window": 128000,
            "max_output": 8192,
            "pricing_mode": "unmetered",
            "order": 30,
            "reasoning": {
                "default": "low",
                "options": [
                    {"id": "low", "params": {}},
                    {"id": "high", "params": {}, "alias": "nr-gemini-flash-high"},
                ],
            },
        }
    )
    data["models"][0]["reasoning"] = {
        "default": "high",
        "options": [
            {"id": "off", "params": {"thinking": {"type": "disabled"}}},
            {"id": "high", "params": {"thinking": {"type": "enabled"}, "reasoning_effort": "high"}},
        ],
    }
    data["title_model"] = {"model": "deepseek-flash", "reasoning": "off", "max_output": 64}
    return data


def _missing_aliases(raw_catalog: dict[str, Any], litellm_text: str) -> list[str]:
    """`model 'X': alias 'Y'` cho mọi `alias` không có `model_name` trong LiteLLM."""
    names = set(_MODEL_NAME.findall(litellm_text))
    return [
        f"model '{m['id']}': alias '{o['alias']}'"
        for m in raw_catalog["models"]
        for o in (m.get("reasoning") or {}).get("options", [])
        if o.get("alias") is not None and o["alias"] not in names
    ]


def test_v4_fixture_loads() -> None:
    cat = Catalog.model_validate(_v4())
    assert cat.version == catalog.CATALOG_VERSION == 4
    assert cat.providers["ninerouter"].user_visible is False
    assert cat.providers["deepseek"].user_visible is True  # vắng mặt ⇒ hiện


def test_older_catalog_version_says_backend_needs_v4() -> None:
    """Cạm bẫy ④ — lệch phiên bản phải là một câu đọc được, không phải lỗi `extra`."""
    bad = _v4()
    bad["version"] = 3
    with pytest.raises(ValidationError) as exc:
        Catalog.model_validate(bad)
    message = str(exc.value)
    assert "catalog v4" in message
    assert "T-S.3" in message


def test_newer_catalog_version_says_backend_is_too_old() -> None:
    bad = _v4()
    bad["version"] = 5
    with pytest.raises(ValidationError) as exc:
        Catalog.model_validate(bad)
    assert "cần backend mới hơn" in str(exc.value)


def test_hidden_provider_model_without_display_provider_does_not_boot() -> None:
    """NQ-119 — thiếu `display_provider` thì tên đường đi lọt ra giao diện."""
    bad = _v4()
    del bad["models"][2]["display_provider"]
    with pytest.raises(ValidationError) as exc:
        Catalog.model_validate(bad)
    message = str(exc.value)
    assert "nr-gemini-flash" in message
    assert "display_provider" in message


def test_visible_provider_falls_back_to_label() -> None:
    cat = Catalog.model_validate(_v4())
    haiku = next(m for m in cat.models if m.id == "claude-haiku")
    gemini = next(m for m in cat.models if m.id == "nr-gemini-flash")
    assert haiku.display_provider is None
    assert cat.display_provider(haiku) == "Anthropic"
    assert cat.display_provider(gemini) == "Google AI"


def test_empty_display_provider_is_rejected() -> None:
    bad = _v4()
    bad["models"][2]["display_provider"] = ""
    with pytest.raises(ValidationError):
        Catalog.model_validate(bad)


def test_reasoning_default_not_in_options_is_rejected() -> None:
    bad = _v4()
    bad["models"][0]["reasoning"]["default"] = "low"
    with pytest.raises(ValidationError) as exc:
        Catalog.model_validate(bad)
    message = str(exc.value)
    assert "deepseek-flash" in message
    assert "'low'" in message


def test_reasoning_id_outside_vocabulary_is_rejected() -> None:
    bad = _v4()
    bad["models"][0]["reasoning"]["options"].append({"id": "ultra", "params": {}})
    with pytest.raises(ValidationError) as exc:
        Catalog.model_validate(bad)
    message = str(exc.value)
    assert "deepseek-flash" in message
    assert "ultra" in message


def test_reasoning_duplicate_ids_rejected() -> None:
    bad = _v4()
    bad["models"][0]["reasoning"]["options"].append({"id": "high", "params": {}})
    with pytest.raises(ValidationError) as exc:
        Catalog.model_validate(bad)
    assert "trùng" in str(exc.value)


def test_reasoning_option_unknown_field_rejected() -> None:
    """`extra="forbid"` — `omit_temprature` gõ sai phải chết, không bị bỏ im lặng."""
    bad = _v4()
    bad["models"][0]["reasoning"]["options"][1]["omit_temprature"] = True
    with pytest.raises(ValidationError):
        Catalog.model_validate(bad)


def test_reasoning_option_fields_are_parsed() -> None:
    raw = _v4()
    raw["models"][1]["reasoning"] = {
        "default": "off",
        "options": [
            {"id": "off", "params": {"thinking": {"type": "disabled"}}},
            {
                "id": "low",
                "params": {"thinking": {"type": "enabled", "budget_tokens": 1024}},
                "byok_params": {"thinking": {"type": "enabled", "budget_tokens": 1024}},
                "omit_temperature": True,
            },
        ],
    }
    cat = Catalog.model_validate(raw)
    haiku = next(m for m in cat.models if m.id == "claude-haiku")
    assert haiku.reasoning is not None
    low = haiku.reasoning.option("low")
    off = haiku.reasoning.option("off")
    assert low is not None
    assert off is not None
    assert low.omit_temperature is True
    assert low.byok_params == {"thinking": {"type": "enabled", "budget_tokens": 1024}}
    assert off.omit_temperature is False
    assert off.byok_params is None
    assert haiku.reasoning.option("max") is None


def test_missing_title_model_does_not_boot() -> None:
    bad = _v4()
    del bad["title_model"]
    with pytest.raises(ValidationError) as exc:
        Catalog.model_validate(bad)
    assert "title_model" in str(exc.value)


def test_title_model_unknown_model_rejected() -> None:
    bad = _v4()
    bad["title_model"]["model"] = "khong-ton-tai"
    with pytest.raises(ValidationError) as exc:
        Catalog.model_validate(bad)
    assert "khong-ton-tai" in str(exc.value)


def test_title_model_disabled_model_rejected() -> None:
    bad = _v4()
    bad["models"][0]["enabled"] = False
    bad["models"][0]["default"] = False
    bad["models"][1]["default"] = True
    with pytest.raises(ValidationError) as exc:
        Catalog.model_validate(bad)
    message = str(exc.value)
    assert "title_model" in message
    assert "enabled=false" in message


def test_title_model_reasoning_not_in_options_rejected() -> None:
    bad = _v4()
    bad["title_model"]["reasoning"] = "max"
    with pytest.raises(ValidationError) as exc:
        Catalog.model_validate(bad)
    message = str(exc.value)
    assert "'max'" in message
    assert "deepseek-flash" in message


def test_title_model_reasoning_on_model_without_block_rejected() -> None:
    bad = _v4()
    bad["title_model"] = {"model": "claude-haiku", "reasoning": "off", "max_output": 64}
    with pytest.raises(ValidationError) as exc:
        Catalog.model_validate(bad)
    assert "claude-haiku" in str(exc.value)


# ─────────── `alias` phải có trong `config/litellm.config.yaml` (đọc cả hai file) ───────────


def test_real_catalog_every_alias_exists_in_litellm_config() -> None:
    """Cùng khuôn `test_compose_calls_right_module`: không phép kiểm nào khác nối
    hai file. Thiếu alias thì catalog vẫn nạp, picker vẫn hiện mức ấy — và lượt
    gọi đầu tiên ở mức ấy nhận `400` của LiteLLM (`drop_params` không cứu nổi
    một tên model không tồn tại)."""
    raw = json.loads(catalog.CATALOG_PATH.read_text(encoding="utf-8"))
    litellm_text = LITELLM_CONFIG_PATH.read_text(encoding="utf-8")

    aliases = [
        o["alias"]
        for m in raw["models"]
        for o in (m.get("reasoning") or {}).get("options", [])
        if o.get("alias") is not None
    ]
    assert aliases, "catalog thật phải có ít nhất một alias — nếu không ca này xanh vô nghĩa"
    assert _missing_aliases(raw, litellm_text) == []


def test_alias_missing_from_litellm_config_is_reported() -> None:
    """Ca âm — gỡ entry `nr-gemini-flash-high` khỏi bản chép của file LiteLLM thật."""
    raw = json.loads(catalog.CATALOG_PATH.read_text(encoding="utf-8"))
    litellm_text = LITELLM_CONFIG_PATH.read_text(encoding="utf-8")
    without_alias = litellm_text.replace(
        "model_name: nr-gemini-flash-high", "model_name: da-go-alias"
    )
    assert without_alias != litellm_text

    missing = _missing_aliases(raw, without_alias)

    assert missing == ["model 'nr-gemini-flash': alias 'nr-gemini-flash-high'"]


# ─────────────── Dữ liệu thật: đúng bảng T-S.2, không tên đường đi ───────────────


def test_real_catalog_reasoning_matches_t_s_2_table() -> None:
    """Khối `reasoning` chép nguyên từ "Ghi nhận" của T-S.2 — không mức nào chưa đo."""
    raw = json.loads(catalog.CATALOG_PATH.read_text(encoding="utf-8"))
    blocks = {m["id"]: m.get("reasoning") for m in raw["models"]}

    assert blocks["deepseek-flash"] == {
        "default": "high",
        "options": [
            {"id": "off", "params": {"thinking": {"type": "disabled"}}},
            {"id": "high", "params": {"thinking": {"type": "enabled"}, "reasoning_effort": "high"}},
        ],
    }
    assert blocks["claude-haiku"] == {
        "default": "off",
        "options": [
            {"id": "off", "params": {"thinking": {"type": "disabled"}}},
            {
                "id": "low",
                "params": {"thinking": {"type": "enabled", "budget_tokens": 1024}},
                "omit_temperature": True,
            },
            {
                "id": "high",
                "params": {"thinking": {"type": "enabled", "budget_tokens": 4096}},
                "omit_temperature": True,
            },
        ],
    }
    assert blocks["nr-gemini-flash"] == {
        "default": "low",
        "options": [
            {"id": "low", "params": {}},
            {"id": "high", "params": {}, "alias": "nr-gemini-flash-high"},
        ],
    }
    # T-S.2: Grok (Sub2API bỏ im lặng tham số) và Qwen (không có suy luận) KHÔNG khai.
    assert blocks["grok-4.6"] is None
    assert blocks["ol-qwen-small"] is None


def test_real_catalog_hides_intermediate_routes() -> None:
    """NQ-119 — tên đường trung gian không nằm trong chữ nào người dùng đọc được."""
    cat = catalog.get_catalog()
    hidden = {key: p for key, p in cat.providers.items() if not p.user_visible}
    assert set(hidden) == {"ninerouter", "sub2api"}

    names = {key.lower() for key in hidden} | {p.label.split()[0].lower() for p in hidden.values()}
    for m in cat.models:
        shown = " ".join([m.display_name, m.badge or "", cat.display_provider(m)]).lower()
        assert not any(n in shown for n in names), f"{m.id}: '{shown}'"
        if m.provider in hidden:
            assert m.display_provider is not None


def test_real_catalog_title_model_is_deepseek_flash_with_reasoning_off() -> None:
    title = catalog.get_catalog().title_model
    assert (title.model, title.reasoning) == ("deepseek-flash", "off")
    assert title.max_output > 0


# ─────────────── Giá dạng chuỗi và khung giá (§24.2b·S3c, NQ-120) ───────────────


def test_price_text_keeps_digits_written_in_file(tmp_path: Path) -> None:
    """Cạm bẫy ③ — `0.30` trong file ra `"0.30"`, không `"0.3"`, không `0.30000000000000004`."""
    raw = _with_time_windows()
    fixture = tmp_path / "model_catalog.json"
    fixture.write_text(json.dumps(raw).replace('"input_per_1m": 0.3,', '"input_per_1m": 0.30,'))
    assert '"input_per_1m": 0.30,' in fixture.read_text()

    cat = catalog._read_and_validate(fixture)
    peak = cat.effective_pricing("deepseek-flash", _at("2026-09-14T09:00:00"))

    assert peak is not None
    assert peak.usd("input_per_1m") == "0.30"
    assert peak.usd("output_per_1m") == "1.2"
    assert peak.usd("cache_write_per_1m") is None


def test_price_text_from_python_float_has_no_rounding() -> None:
    """Không nguồn chữ nào ⇒ dạng thập phân ngắn nhất của đúng số đã nhận."""
    rates = catalog.PricingRates(input_per_1m=0.1 + 0.2, output_per_1m=0.006)
    assert rates.usd("output_per_1m") == "0.006"
    assert rates.usd("input_per_1m") == "0.30000000000000004"


def test_real_catalog_price_text_matches_file_digit_for_digit() -> None:
    """DoD — giá `deepseek-flash` khớp `model_catalog.json` từng chữ số."""
    raw = json.loads(catalog.CATALOG_PATH.read_text(encoding="utf-8"), parse_float=str)
    written = next(m for m in raw["models"] if m["id"] == "deepseek-flash")["pricing"]
    windows = catalog.get_catalog().price_windows("deepseek-flash", _at("2026-09-14T09:00:00"))

    peak, off_peak = (w.rates for w in windows)
    for field in ("input_per_1m", "output_per_1m", "cached_input_per_1m"):
        assert peak.usd(field) == written[field]
        assert off_peak.usd(field) == written["off_peak"][field]


def test_manual_price_text_survives_as_rates(tmp_path: Path) -> None:
    raw = _with_manual_pricing({"input_per_1m": 0.1, "output_per_1m": 0.4})
    fixture = tmp_path / "model_catalog.json"
    text = json.dumps(raw).replace('"input_per_1m": 0.1,', '"input_per_1m": 0.10,')
    assert text != json.dumps(raw)
    fixture.write_text(text)

    rates = catalog._read_and_validate(fixture).effective_pricing("nr-gemini-flash")

    assert rates is not None
    assert rates.usd("input_per_1m") == "0.10"


def test_json_numbers_in_reasoning_params_stay_serializable(tmp_path: Path) -> None:
    """`_JsonFloat` là `float`: một `params` có số thực vẫn `json.dumps` được."""
    raw = _v4()
    raw["models"][0]["reasoning"]["options"][0]["params"] = {"top_p": 0.95}
    fixture = tmp_path / "model_catalog.json"
    fixture.write_text(json.dumps(raw))

    model = catalog._read_and_validate(fixture).models[0]

    assert model.reasoning is not None
    assert json.dumps(model.reasoning.options[0].params) == '{"top_p": 0.95}'


@pytest.mark.parametrize(
    ("moment", "current", "other"),
    [
        ("2026-09-14T09:00:00", "peak", "off_peak"),
        ("2026-09-14T22:00:00", "off_peak", "peak"),
        ("2026-09-19T09:00:00", "off_peak", "peak"),
    ],
)
def test_price_windows_put_active_window_first(moment: str, current: str, other: str) -> None:
    cat = Catalog.model_validate(_with_time_windows())
    windows = cat.price_windows("deepseek-flash", _at(moment))
    assert [w.window for w in windows] == [current, other]
    assert windows[0].rates is cat.effective_pricing("deepseek-flash", _at(moment))


def test_price_windows_single_price_and_no_price() -> None:
    cat = Catalog.model_validate(_with_manual_pricing())
    assert [w.window for w in cat.price_windows("claude-haiku")] == [None]
    assert cat.price_windows("nr-gemini-flash") == ()
    assert cat.price_windows("khong-ton-tai") == ()
