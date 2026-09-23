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
from app.core import provider_health
from app.core.access_token import encode_access_token
from app.core.deps import SESSION_COOKIE_NAME
from app.db.models import UserRole, UserStatus
from app.main import app

client = TestClient(app)


class _FakeSession:
    """Session không ghi gì — `AuditLogRepository.record` gọi đúng hai lệnh này."""

    def add(self, _row: Any) -> None:
        return None

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None


@asynccontextmanager
async def _no_ledger_writes() -> AsyncIterator[_FakeSession]:
    """Thay `session_scope()` của `admin.py` — xem `test_reload_endpoint_...`."""
    yield _FakeSession()


async def _probe_ok(_provider: object) -> None:
    """Provider trả lời được — xem `_no_real_network_probe`."""
    return None


class _FakeRedis:
    """Blacklist rỗng — `get_access_claims` hỏi Redis ở MỌI request có cookie."""

    async def mget(self, keys: list[str]) -> list[str | None]:
        return [None for _ in keys]


@pytest.fixture
def admin_session(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Cookie phiên `role=admin` trên `client` cho ca `reload` — T-2.16.

    Không cần hàng `users` nào trong Postgres: `require_admin` đọc `role` từ
    **claim** (§11.2), và ca này đo catalog chứ không đo audit.

    Dọn cookie ở cuối vì `client` là của cả module: một phiên admin còn sót lại
    sẽ đi theo mọi ca chạy sau, và khi ấy một test "gọi không đăng nhập" sẽ
    xanh vì lý do hoàn toàn khác với lý do nó tưởng.
    """
    monkeypatch.setattr("app.core.deps.get_redis", lambda: _FakeRedis())
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
def _restore_real_catalog() -> None:
    """Mỗi test tự dọn cache về catalog thật, tránh rò rỉ giữa các test."""
    yield
    catalog.reload(path=catalog.CATALOG_PATH)
    provider_health.forget_all()


@pytest.fixture(autouse=True)
def _no_real_network_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """T-3.6 — `GET /models` nay hỏi `provider_health`, thứ gọi ra ngoài.

    Thay đúng **một** hàm (`probe_provider`, lời gọi mạng duy nhất) chứ không
    thay cả `provider_statuses`: phần ánh xạ provider → model vẫn phải chạy
    thật ở mỗi ca, nếu không thì hai trường mới của §18.3 không ai đo.

    Mặc định là "mọi provider trả lời được", nên các ca cũ của T-0.7 giữ
    nguyên ý nghĩa. Ca nào cần chiều ngược lại thì tự `monkeypatch` lại.
    """
    monkeypatch.setattr(provider_health, "probe_provider", _probe_ok)
    provider_health.forget_all()


def test_get_models_does_not_leak_base_url_or_pricing() -> None:
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


def test_get_models_has_exactly_one_default_deepseek_flash() -> None:
    resp = client.get("/api/v1/models")
    body = resp.json()
    defaults = [m for m in body if m["default"]]
    assert len(defaults) == 1
    assert defaults[0]["id"] == "deepseek-flash"


def test_reload_takes_effect_without_restart(tmp_path: Path) -> None:
    raw = json.loads(catalog.CATALOG_PATH.read_text(encoding="utf-8"))
    raw["models"][0]["display_name"] = "DeepSeek Flash (test reload)"
    fixture = tmp_path / "model_catalog.json"
    fixture.write_text(json.dumps(raw), encoding="utf-8")

    catalog.reload(path=fixture)

    resp = client.get("/api/v1/models")
    names = {m["display_name"] for m in resp.json()}
    assert "DeepSeek Flash (test reload)" in names


@pytest.mark.usefixtures("admin_session")
def test_reload_endpoint_returns_model_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """Từ T-2.16, endpoint này ghi một dòng `audit_logs` — xem docstring module.

    Ca này đo **catalog**, không đo sổ, nên nó thay `session_scope` bằng một
    stub thay vì kéo cả Postgres vào một file test của T-0.7.
    """
    monkeypatch.setattr("app.api.v1.admin.session_scope", _no_ledger_writes)

    resp = client.post("/api/v1/admin/catalog/reload")

    assert resp.status_code == 200
    assert resp.json()["models"] == len(catalog.get_catalog().models)


# ═════════════════ T-3.6 — `available` + `unavailable_reason` (§18.3) ════════


def test_get_models_has_the_two_availability_fields_of_18_3() -> None:
    """§18.3: *"có `available: bool` và `unavailable_reason`"*. T-0.7 dựng
    `GET /models` **tối thiểu** và bỏ hai trường này lại; T-3.6 đặt chúng vào."""
    body = client.get("/api/v1/models").json()

    assert body
    for m in body:
        assert isinstance(m["available"], bool)
        assert "unavailable_reason" in m


def test_live_provider_makes_every_model_available_without_reason() -> None:
    body = client.get("/api/v1/models").json()

    assert all(m["available"] for m in body)
    assert all(m["unavailable_reason"] is None for m in body)


def test_host_dependent_provider_down_greys_out_its_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RR-5 / UC-05 dòng 2 — 9Router tắt là ca THƯỜNG. Chỉ model của provider
    ấy mất `available`; DeepSeek và Anthropic không liên quan."""

    async def failing_probe(_provider: object) -> None:
        raise ConnectionError("Connection refused")

    monkeypatch.setattr(provider_health, "probe_provider", failing_probe)
    provider_health.forget_all()

    body = client.get("/api/v1/models").json()

    cat = catalog.get_catalog()
    disabled = {
        m.id
        for m in cat.models
        if m.enabled and cat.providers[m.provider].availability == "host-dependent"
    }
    assert disabled, "catalog thật phải còn ít nhất một model `host-dependent`"
    for m in body:
        if m["id"] in disabled:
            assert m["available"] is False
            assert m["unavailable_reason"]
        else:
            assert m["available"] is True
            assert m["unavailable_reason"] is None


def test_unavailable_model_STILL_in_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UC-05 dòng 2 đòi *hiện xám*, không đòi biến mất. Lọc nó đi thì
    `conversations.default_model` của một hội thoại cũ trỏ vào một model
    không còn trong danh sách nào — Cạm bẫy ① của T-3.6 ở một dạng khác."""

    async def failing_probe(_provider: object) -> None:
        raise ConnectionError("Connection refused")

    monkeypatch.setattr(provider_health, "probe_provider", failing_probe)
    provider_health.forget_all()

    count_when_off = len(client.get("/api/v1/models").json())

    monkeypatch.setattr(provider_health, "probe_provider", _probe_ok)
    provider_health.forget_all()
    count_when_alive = len(client.get("/api/v1/models").json())

    assert count_when_off == count_when_alive


def test_reason_takes_provider_name_from_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """A3 — câu hiện lên màn hình không được ghim tên một provider cụ thể."""

    async def failing_probe(_provider: object) -> None:
        raise TimeoutError("het gio cho")

    monkeypatch.setattr(provider_health, "probe_provider", failing_probe)
    provider_health.forget_all()

    body = client.get("/api/v1/models").json()
    cat = catalog.get_catalog()
    label = {
        cat.providers[m.provider].label
        for m in cat.models
        if m.enabled and cat.providers[m.provider].availability == "host-dependent"
    }

    reason = [m["unavailable_reason"] for m in body if not m["available"]]
    assert reason
    assert all(any(n in r for n in label) for r in reason)


def test_get_models_does_not_leak_base_url_when_provider_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Câu lý do đi ra ngoài cho MỌI người dùng. `str(exc)` của httpx mang
    nguyên URL nội bộ (`http://host.docker.internal:20128/v1/models`), nên nó
    phải ở lại trong log — ADR-12, §9.3 hàng đầu tiên."""

    async def failing_probe(_provider: object) -> None:
        raise ConnectionError("All connection attempts failed: http://host.docker.internal:20128")

    monkeypatch.setattr(provider_health, "probe_provider", failing_probe)
    provider_health.forget_all()

    body = client.get("/api/v1/models").json()

    for m in body:
        assert "host.docker.internal" not in (m["unavailable_reason"] or "")
        assert "20128" not in (m["unavailable_reason"] or "")


# ═══════════════ B-257 — `provider_id`: khoá để so, tách khỏi nhãn để hiện ══════


def test_provider_id_is_catalog_key_not_label() -> None:
    """B-257 — `provider` là NHÃN (`DeepSeek AI`), `provider_id` là KHOÁ
    (`deepseek`). FE so khoá BYOK của người dùng với `provider_id`; so với
    nhãn thì không bao giờ khớp.

    Ca này chỉ có nghĩa khi catalog thật có ít nhất một provider mà nhãn khác
    khoá — nếu mọi nhãn trùng khoá thì một FE so nhầm trường vẫn chạy đúng, và
    ca này phải nói ra điều đó thay vì xanh vô nghĩa.
    """
    cat = catalog.get_catalog()
    body = client.get("/api/v1/models").json()

    assert body
    for m in body:
        entry = next(e for e in cat.models if e.id == m["id"])
        assert m["provider_id"] == entry.provider
        assert m["provider"] == cat.providers[entry.provider].label
    assert any(m["provider"] != m["provider_id"] for m in body), (
        "catalog thật không có provider nào có nhãn khác khoá — ca B-257 mất ý nghĩa"
    )


def test_provider_id_matches_key_accepted_by_settings_keys() -> None:
    """B-257 — `provider_id` phải là chuỗi mà `PUT /settings/keys/{provider}`
    tra trong `providers` của catalog: đó là hai đầu của cùng một phép so."""
    cat = catalog.get_catalog()
    body = client.get("/api/v1/models").json()

    assert {m["provider_id"] for m in body} <= set(cat.providers)
