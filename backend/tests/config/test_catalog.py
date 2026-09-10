"""`app/config/catalog.py` — schema, validate, cache, reload (T-0.7 DoD).

KH tham chiếu: §9.2, §9.3, ADR-12. Các case lỗi dùng fixture JSON dựng tay
thay vì sửa `config/model_catalog.json` thật, để không phụ thuộc nội dung
catalog thật khi thêm/bớt model sau này.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

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
