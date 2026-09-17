"""`app/config/catalog.py` — schema, validate, cache, reload (T-0.7 DoD).

KH tham chiếu: §9.2, §9.3, ADR-12. Các case lỗi dùng fixture JSON dựng tay
thay vì sửa `config/model_catalog.json` thật, để không phụ thuộc nội dung
catalog thật khi thêm/bớt model sau này.
"""

from __future__ import annotations

import json
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
    "version": 1,
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


def test_catalog_hop_le_load_duoc() -> None:
    cat = Catalog.model_validate(VALID)
    assert len(cat.models) == 2


def test_provider_khong_ton_tai_raise() -> None:
    bad = deepcopy(VALID)
    bad["models"][0]["provider"] = "khong-ton-tai"
    with pytest.raises(ValidationError) as exc:
        Catalog.model_validate(bad)
    message = str(exc.value)
    assert "khong-ton-tai" in message
    assert "deepseek-flash" in message


def test_hai_model_cung_default_raise() -> None:
    bad = deepcopy(VALID)
    bad["models"][1]["default"] = True
    with pytest.raises(ValidationError) as exc:
        Catalog.model_validate(bad)
    assert "default" in str(exc.value)


def test_khong_model_nao_default_raise() -> None:
    bad = deepcopy(VALID)
    bad["models"][0]["default"] = False
    with pytest.raises(ValidationError) as exc:
        Catalog.model_validate(bad)
    assert "default" in str(exc.value)


def test_metered_thieu_pricing_raise() -> None:
    bad = deepcopy(VALID)
    bad["models"][0]["pricing"] = None
    with pytest.raises(ValidationError) as exc:
        Catalog.model_validate(bad)
    message = str(exc.value)
    assert "pricing" in message
    assert "deepseek-flash" in message


def test_unmetered_khong_can_pricing() -> None:
    ok = deepcopy(VALID)
    ok["models"][1]["pricing_mode"] = "unmetered"
    ok["models"][1]["pricing"] = None
    cat = Catalog.model_validate(ok)
    assert cat.models[1].pricing is None


def test_base_url_co_dau_gach_cheo_cuoi_duoc_chuan_hoa() -> None:
    ok = deepcopy(VALID)
    ok["providers"]["deepseek"]["base_url"] = "https://api.deepseek.com/v1/"
    cat = Catalog.model_validate(ok)
    assert cat.providers["deepseek"].base_url == "https://api.deepseek.com/v1"


def test_base_url_thieu_phien_ban_bi_tu_choi() -> None:
    """C43 — `https://api.deepseek.com` (thiếu `/v1`) phải chết lúc nạp catalog."""
    bad = deepcopy(VALID)
    bad["providers"]["deepseek"]["base_url"] = "https://api.deepseek.com"
    with pytest.raises(ValidationError) as exc:
        Catalog.model_validate(bad)
    message = str(exc.value)
    assert "deepseek" in message
    assert "C43" in message


def test_base_url_ket_thuc_bang_duong_dan_khac_bi_tu_choi() -> None:
    """C43 — `/v1/chat/completions` cũng sai: base_url là GỐC API, không phải endpoint."""
    bad = deepcopy(VALID)
    bad["providers"]["deepseek"]["base_url"] = "https://api.deepseek.com/v1/chat/completions"
    with pytest.raises(ValidationError) as exc:
        Catalog.model_validate(bad)
    assert "C43" in str(exc.value)


@pytest.mark.parametrize("base_url", ["http://ollama:11434/v1", "https://x.test/api/v1beta"])
def test_base_url_co_phien_ban_duoc_chap_nhan(base_url: str) -> None:
    ok = deepcopy(VALID)
    ok["providers"]["deepseek"]["base_url"] = base_url
    assert Catalog.model_validate(ok).providers["deepseek"].base_url == base_url


def test_auth_style_thieu_mac_dinh_bearer() -> None:
    cat = Catalog.model_validate(VALID)
    assert cat.providers["anthropic"].auth_style == "bearer"


def test_verify_path_thieu_mac_dinh_none_va_canh_bao(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING", logger="app.config.catalog"):
        cat = Catalog.model_validate(VALID)
    assert cat.providers["anthropic"].verify_path is None
    assert "anthropic" in caplog.text
    assert "C42" in caplog.text


def test_file_catalog_that_hop_le_va_co_dung_mot_default() -> None:
    cat = catalog._read_and_validate(catalog.CATALOG_PATH)
    defaults = [m for m in cat.models if m.default]
    assert len(defaults) == 1
    assert defaults[0].id == "deepseek-flash"
    assert defaults[0].provider == "deepseek"


def test_reload_doc_lai_tu_dia_va_thay_cache(tmp_path: Path) -> None:
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


def test_get_catalog_khong_doc_dia(monkeypatch: pytest.MonkeyPatch) -> None:
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


def _voi_khung_gio() -> dict[str, Any]:
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


def _luc(iso: str) -> datetime:
    """Một thời điểm viết theo giờ Việt Nam — đúng cách bảng giá được phát biểu."""
    return datetime.fromisoformat(iso).replace(tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))


def test_catalog_khong_co_pricing_schedules_van_nap_duoc() -> None:
    cat = Catalog.model_validate(VALID)
    assert cat.pricing_schedules == {}


def test_schedule_khong_ton_tai_raise() -> None:
    bad = _voi_khung_gio()
    bad["models"][0]["pricing"]["off_peak"]["schedule"] = "khong-ton-tai"
    with pytest.raises(ValidationError) as exc:
        Catalog.model_validate(bad)
    message = str(exc.value)
    assert "khong-ton-tai" in message
    assert "deepseek-flash" in message


def test_timezone_sai_raise() -> None:
    bad = _voi_khung_gio()
    bad["pricing_schedules"]["peak-vn"]["timezone"] = "Asia/Khong_Co_That"
    with pytest.raises(ValidationError) as exc:
        Catalog.model_validate(bad)
    assert "Asia/Khong_Co_That" in str(exc.value)


def test_khung_gio_qua_nua_dem_bi_tu_choi() -> None:
    bad = _voi_khung_gio()
    bad["pricing_schedules"]["peak-vn"]["windows"] = [{"start": "22:00", "end": "02:00"}]
    with pytest.raises(ValidationError) as exc:
        Catalog.model_validate(bad)
    assert "start phải < end" in str(exc.value)


@pytest.mark.parametrize(
    ("moment", "mo_ta"),
    [
        ("2026-09-14T08:00:00", "thứ Hai, đúng lúc mở khung sáng"),
        ("2026-09-14T10:59:59", "thứ Hai, sát cuối khung sáng"),
        ("2026-09-18T13:00:00", "thứ Sáu, đúng lúc mở khung chiều"),
        ("2026-09-18T16:59:59", "thứ Sáu, sát cuối khung chiều"),
    ],
)
def test_trong_gio_cao_diem_tra_gia_dat(moment: str, mo_ta: str) -> None:
    cat = Catalog.model_validate(_voi_khung_gio())
    gia = cat.effective_pricing("deepseek-flash", _luc(moment))
    assert gia is not None
    assert gia.input_per_1m == 0.30, mo_ta
    assert gia.output_per_1m == 1.20
    assert gia.cached_input_per_1m == 0.006


@pytest.mark.parametrize(
    ("moment", "mo_ta"),
    [
        ("2026-09-14T07:59:59", "thứ Hai, trước giờ làm"),
        ("2026-09-14T11:00:00", "thứ Hai, đúng lúc nghỉ trưa — biên [start, end)"),
        ("2026-09-14T12:30:00", "thứ Hai, giữa trưa"),
        ("2026-09-18T17:00:00", "thứ Sáu, đúng lúc tan làm"),
        ("2026-09-19T09:00:00", "thứ Bảy, giờ hành chính nhưng cuối tuần"),
        ("2026-09-20T14:00:00", "Chủ nhật"),
    ],
)
def test_ngoai_gio_cao_diem_tra_gia_re(moment: str, mo_ta: str) -> None:
    cat = Catalog.model_validate(_voi_khung_gio())
    gia = cat.effective_pricing("deepseek-flash", _luc(moment))
    assert gia is not None
    assert gia.input_per_1m == 0.15, mo_ta
    assert gia.output_per_1m == 0.60
    assert gia.cached_input_per_1m == 0.003


def test_moc_gio_doi_theo_mui_gio_chu_khong_theo_gio_may_chu() -> None:
    """09:00 giờ Việt Nam = 02:00 UTC. Container chạy UTC, bảng giá viết giờ VN."""
    cat = Catalog.model_validate(_voi_khung_gio())
    sang_thu_hai_utc = datetime(2026, 9, 14, 2, 0, tzinfo=UTC)
    gia = cat.effective_pricing("deepseek-flash", sang_thu_hai_utc)
    assert gia is not None
    assert gia.input_per_1m == 0.30


def test_datetime_tran_bi_tu_choi() -> None:
    cat = Catalog.model_validate(_voi_khung_gio())
    with pytest.raises(ValueError, match="múi giờ"):
        cat.effective_pricing("deepseek-flash", datetime(2026, 9, 14, 9, 0))  # noqa: DTZ001


def test_model_khong_co_khung_gio_tra_dung_mot_gia() -> None:
    """`claude-haiku` không bán theo giờ — mọi thời điểm cho cùng một bảng giá."""
    data = _voi_khung_gio()
    data["models"][1]["pricing"] = {
        "input_per_1m": 1.00,
        "output_per_1m": 5.00,
        "cached_input_per_1m": 0.10,
        "cache_write_per_1m": 1.25,
    }
    cat = Catalog.model_validate(data)
    for moment in ("2026-09-14T09:00:00", "2026-09-20T03:00:00"):
        gia = cat.effective_pricing("claude-haiku", _luc(moment))
        assert gia is not None
        assert gia.input_per_1m == 1.00
        assert gia.cache_write_per_1m == 1.25


def test_model_unmetered_hoac_khong_ton_tai_khong_co_gia() -> None:
    data = _voi_khung_gio()
    data["models"][1]["pricing_mode"] = "unmetered"
    data["models"][1]["pricing"] = None
    cat = Catalog.model_validate(data)
    assert cat.effective_pricing("claude-haiku") is None
    assert cat.effective_pricing("model-khong-ton-tai") is None


def test_model_da_tat_van_con_gia() -> None:
    """A7: tắt một model không được xoá giá của những lượt sinh nó đã chạy."""
    data = _voi_khung_gio()
    data["models"][0]["enabled"] = False
    cat = Catalog.model_validate(data)
    assert cat.effective_pricing("deepseek-flash", _luc("2026-09-14T09:00:00")) is not None


def test_cache_write_thieu_la_none_chu_khong_phai_0() -> None:
    """DeepSeek không thu tiền ghi cache; Anthropic thu. Hai ca khác nhau."""
    cat = Catalog.model_validate(_voi_khung_gio())
    gia = cat.effective_pricing("deepseek-flash", _luc("2026-09-14T09:00:00"))
    assert gia is not None
    assert gia.cache_write_per_1m is None


# ─────────────── Catalog THẬT: giá do người dùng chốt (B-35) ───────────────


def test_catalog_that_deepseek_hai_khung_gia() -> None:
    cat = catalog.get_catalog()
    peak = cat.effective_pricing("deepseek-flash", _luc("2026-09-14T09:00:00"))
    off = cat.effective_pricing("deepseek-flash", _luc("2026-09-14T22:00:00"))
    assert peak is not None
    assert off is not None
    assert (peak.input_per_1m, peak.output_per_1m, peak.cached_input_per_1m) == (0.30, 1.20, 0.006)
    assert (off.input_per_1m, off.output_per_1m, off.cached_input_per_1m) == (0.15, 0.60, 0.003)


def test_catalog_that_claude_haiku_co_gia_ghi_cache() -> None:
    gia = catalog.get_catalog().effective_pricing("claude-haiku")
    assert gia is not None
    assert (gia.input_per_1m, gia.output_per_1m) == (1.00, 5.00)
    assert (gia.cached_input_per_1m, gia.cache_write_per_1m) == (0.10, 1.25)
