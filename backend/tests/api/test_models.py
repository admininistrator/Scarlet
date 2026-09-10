"""`GET /api/v1/models` và `POST /api/v1/admin/catalog/reload` (T-0.7 DoD).

KH tham chiếu: §9.3, ADR-12, S7.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import catalog
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _khoi_phuc_catalog_that() -> None:
    """Mỗi test tự dọn cache về catalog thật, tránh rò rỉ giữa các test."""
    yield
    catalog.reload(path=catalog.CATALOG_PATH)


def test_get_models_khong_lo_base_url_hay_pricing() -> None:
    resp = client.get("/api/v1/models")
    assert resp.status_code == 200
    body = resp.json()
    assert body
    first = body[0]
    assert "id" in first
    assert "display_name" in first
    assert "capabilities" in first
    assert "base_url" not in first
    assert "pricing" not in first


def test_get_models_co_dung_mot_default_deepseek_flash() -> None:
    resp = client.get("/api/v1/models")
    body = resp.json()
    defaults = [m for m in body if m["default"]]
    assert len(defaults) == 1
    assert defaults[0]["id"] == "deepseek-flash"


def test_reload_phan_anh_ngay_khong_can_restart(tmp_path: Path) -> None:
    raw = json.loads(catalog.CATALOG_PATH.read_text(encoding="utf-8"))
    raw["models"][0]["display_name"] = "DeepSeek Flash (test reload)"
    fixture = tmp_path / "model_catalog.json"
    fixture.write_text(json.dumps(raw), encoding="utf-8")

    catalog.reload(path=fixture)

    resp = client.get("/api/v1/models")
    names = {m["display_name"] for m in resp.json()}
    assert "DeepSeek Flash (test reload)" in names


def test_reload_endpoint_tra_ve_so_luong_model() -> None:
    resp = client.post("/api/v1/admin/catalog/reload")
    assert resp.status_code == 200
    assert resp.json()["models"] == len(catalog.get_catalog().models)
