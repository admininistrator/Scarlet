"""`GET /api/v1/models` và `POST /api/v1/admin/catalog/reload` (T-0.7 DoD).

KH tham chiếu: §9.3, ADR-12, S7 · §16.3 (T-2.16).

**T-2.16 đóng B-34**, và ca `reload` ở cuối file đổi theo: endpoint ấy nay đòi
`require_admin`, nên nó cần một cookie phiên mang `role=admin` để chạy tới chỗ
nó vốn đo (số model sau khi nạp lại). Phần *"user thường thì sao"* **không**
nằm ở đây — nó là `tests/api/test_admin_authz.py`, thứ phủ cả bảy endpoint
`/admin/*` một lượt thay vì một endpoint ở một file không nói về quyền.

Hai ca `GET /models` đầu file không đổi: §11.1 cho `pending_approval` "chọn
model được", nên router `models` cố ý đứng ngoài mọi danh sách phân quyền
(xem `app/api/v1/__init__.py`).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import catalog
from app.core.access_token import encode_access_token
from app.core.deps import SESSION_COOKIE_NAME
from app.db.models import UserRole, UserStatus
from app.main import app

client = TestClient(app)


class _SessionGia:
    """Session không ghi gì — `AuditLogRepository.record` gọi đúng hai lệnh này."""

    def add(self, _row: Any) -> None:
        return None

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None


@asynccontextmanager
async def _khong_ghi_so() -> AsyncIterator[_SessionGia]:
    """Thay `session_scope()` của `admin.py` — xem `test_reload_endpoint_...`."""
    yield _SessionGia()


class _RedisGia:
    """Blacklist rỗng — `get_access_claims` hỏi Redis ở MỌI request có cookie."""

    async def mget(self, keys: list[str]) -> list[str | None]:
        return [None for _ in keys]


@pytest.fixture
def phien_admin(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Cookie phiên `role=admin` trên `client` cho ca `reload` — T-2.16.

    Không cần hàng `users` nào trong Postgres: `require_admin` đọc `role` từ
    **claim** (§11.2), và ca này đo catalog chứ không đo audit.

    Dọn cookie ở cuối vì `client` là của cả module: một phiên admin còn sót lại
    sẽ đi theo mọi ca chạy sau, và khi ấy một test "gọi không đăng nhập" sẽ
    xanh vì lý do hoàn toàn khác với lý do nó tưởng.
    """
    monkeypatch.setattr("app.core.deps.get_redis", lambda: _RedisGia())
    client.cookies.set(
        SESSION_COOKIE_NAME,
        encode_access_token(
            user_id=uuid.uuid4(),
            role=UserRole.ADMIN,
            tier="free",
            status=UserStatus.ACTIVE,
            ttl_minutes=15,
        ),
    )
    yield
    client.cookies.clear()


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


@pytest.mark.usefixtures("phien_admin")
def test_reload_endpoint_tra_ve_so_luong_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Từ T-2.16, endpoint này ghi một dòng `audit_logs` — xem docstring module.

    Ca này đo **catalog**, không đo sổ, nên nó thay `session_scope` bằng một
    stub thay vì kéo cả Postgres vào một file test của T-0.7.
    """
    monkeypatch.setattr("app.api.v1.admin.session_scope", _khong_ghi_so)

    resp = client.post("/api/v1/admin/catalog/reload")

    assert resp.status_code == 200
    assert resp.json()["models"] == len(catalog.get_catalog().models)
