"""`app/core/provider_health.py` — nguồn của `available` trong `GET /models`.

KH tham chiếu: §9.3, §9.5, §18.3, RR-5, UC-05 · tasks.md T-3.6, B-192.

Không một ca nào ở đây chạm mạng thật: `probe_provider` là hàm **duy nhất**
gọi ra ngoài, nên mọi ca thay chính nó. Nhờ vậy bộ test đo đúng phần logic
(ai được đo, nhớ bao lâu, hỏng thì nói gì) chứ không đo xem 9Router trên máy
này có đang bật hay không — thứ đổi theo từng lần chạy.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.config import catalog
from app.config.catalog import Provider
from app.core import provider_health
from app.core.provider_health import HOST_DEPENDENT

#: Khoá provider `host-dependent` duy nhất của catalog thật (§9.2).
NINEROUTER = "ninerouter"


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:
    """Bộ nhớ của module là state toàn cục — dọn trước VÀ sau mỗi ca.

    Trước, vì một ca chạy trước có thể để lại kết quả còn hạn `TTL_S` (30 s)
    và ca sau sẽ xanh mà không đo gì. Sau, vì cùng lý do theo chiều ngược lại.
    """
    provider_health.forget_all()
    yield
    provider_health.forget_all()
    catalog.reload(path=catalog.CATALOG_PATH)


def _write_catalog(tmp_path: Path, raw: dict[str, object]) -> Path:
    fixture = tmp_path / "model_catalog.json"
    fixture.write_text(json.dumps(raw), encoding="utf-8")
    return fixture


def _catalog_without_health_path(tmp_path: Path) -> Path:
    """Bản catalog y hệt, trừ việc 9Router mất `health_path`."""
    raw = json.loads(catalog.CATALOG_PATH.read_text(encoding="utf-8"))
    del raw["providers"][NINEROUTER]["health_path"]
    return _write_catalog(tmp_path, raw)


def _catalog_always_with_health_path(tmp_path: Path) -> tuple[Path, str]:
    """Bản catalog trong đó một provider `always` **có** `health_path`.

    Cần một bản riêng vì catalog thật che mất phép đo: bốn provider của nó
    chỉ có 9Router khai `health_path`, nên bỏ hẳn phép lọc `availability` đi
    thì ba provider kia vẫn không bị gọi — chúng dừng ở nhánh "thiếu
    health_path" của `_probe_one`. Một phép kiểm xanh vì lý do đó là phép kiểm
    đang đo chỗ khác (đo được bằng phép kiểm ngược, xem báo cáo T-3.6).
    """
    raw = json.loads(catalog.CATALOG_PATH.read_text(encoding="utf-8"))
    key = next(k for k, p in raw["providers"].items() if p["availability"] != HOST_DEPENDENT)
    raw["providers"][key]["health_path"] = "/models"
    return _write_catalog(tmp_path, raw), key


async def test_always_provider_not_probed_even_with_health_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A3 + §9.2: ai được đo là **dữ liệu** (`availability`), không phải một
    danh sách tên provider trong `.py`.

    Provider `always` ở đây được cho hẳn một `health_path` để phép kiểm đo
    đúng phép lọc `availability` chứ không đo nhánh "thiếu health_path" —
    xem `_catalog_always_with_health_path`.
    """
    fixture, always_key = _catalog_always_with_health_path(tmp_path)
    catalog.reload(path=fixture)
    probed: list[str] = []

    async def failing_probe(provider: Provider) -> None:
        probed.append(provider.label)
        raise ConnectionError("khong ket noi duoc")

    monkeypatch.setattr(provider_health, "probe_provider", failing_probe)

    status = await provider_health.provider_statuses()

    cat = catalog.get_catalog()
    assert cat.providers[always_key].health_path is not None
    assert status[always_key].available is True
    assert status[always_key].reason is None
    assert probed == [cat.providers[NINEROUTER].label]


async def test_failing_host_dependent_is_unavailable_with_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_probe(provider: Provider) -> None:
        raise ConnectionError("Connection refused")

    monkeypatch.setattr(provider_health, "probe_provider", failing_probe)

    status = await provider_health.provider_statuses()

    nr = status[NINEROUTER]
    assert nr.available is False
    assert nr.reason is not None
    # Câu lấy tên provider từ CATALOG, không từ một literal trong `.py`.
    assert catalog.get_catalog().providers[NINEROUTER].label in nr.reason


async def test_live_host_dependent_has_no_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def probe_ok(provider: Provider) -> None:
        return None

    monkeypatch.setattr(provider_health, "probe_provider", probe_ok)

    status = await provider_health.provider_statuses()

    assert status[NINEROUTER].available is True
    assert status[NINEROUTER].reason is None


async def test_past_wait_time_counts_as_no_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Host im lặng (gói tin rơi) khác host từ chối — cả hai phải ra cùng một
    câu trả lời, và cái đầu chỉ lộ ra qua `asyncio.wait_for`."""

    async def hanging_probe(provider: Provider) -> None:
        await asyncio.sleep(10)

    monkeypatch.setattr(provider_health, "probe_provider", hanging_probe)
    monkeypatch.setattr(provider_health, "PROBE_TIMEOUT_S", 0.05)

    status = await provider_health.provider_statuses()

    assert status[NINEROUTER].available is False


async def test_missing_health_path_still_counts_as_available(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Không đo được ≠ đã tắt. Xám một model vì cấu hình thiếu một trường là
    đổ lỗi cho người dùng về việc của người vận hành."""
    catalog.reload(path=_catalog_without_health_path(tmp_path))

    async def flaky_probe(provider: Provider) -> None:
        raise AssertionError("khong duoc goi khi thieu health_path")

    monkeypatch.setattr(provider_health, "probe_provider", flaky_probe)

    status = await provider_health.provider_statuses()

    assert status[NINEROUTER].available is True
    assert status[NINEROUTER].reason is None


async def test_two_back_to_back_calls_probe_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cạm bẫy ② của T-3.6 / B-192: 854 ms mỗi lượt đo, picker mở rất nhiều."""
    count = 0

    async def counting_probe(provider: Provider) -> None:
        nonlocal count
        count += 1

    monkeypatch.setattr(provider_health, "probe_provider", counting_probe)

    await provider_health.provider_statuses()
    await provider_health.provider_statuses()
    await provider_health.provider_statuses()

    assert count == 1


async def test_many_parallel_calls_still_probe_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mở app trong bốn tab cùng lúc là bốn `GET /models` gần như đồng thời.
    Không có `_khoa` thì cả bốn đều thấy bộ nhớ hết hạn và cùng đi đo."""
    count = 0

    async def slow_probe(provider: Provider) -> None:
        nonlocal count
        count += 1
        await asyncio.sleep(0.05)

    monkeypatch.setattr(provider_health, "probe_provider", slow_probe)

    await asyncio.gather(*(provider_health.provider_statuses() for _ in range(4)))

    assert count == 1


async def test_expiry_reprobes(monkeypatch: pytest.MonkeyPatch) -> None:
    count = 0

    async def counting_probe(provider: Provider) -> None:
        nonlocal count
        count += 1

    monkeypatch.setattr(provider_health, "probe_provider", counting_probe)
    monkeypatch.setattr(provider_health, "TTL_S", 0.0)

    await provider_health.provider_statuses()
    await provider_health.provider_statuses()

    assert count == 2


async def test_catalog_reload_invalidates_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """S7/§19.1 — `POST /admin/catalog/reload` có hiệu lực NGAY. Không ai phải
    nhớ gọi `forget_all()`: `catalog.reload()` thay cả object nên phép so `is`
    trong `provider_statuses()` tự thấy."""
    count = 0

    async def counting_probe(provider: Provider) -> None:
        nonlocal count
        count += 1

    monkeypatch.setattr(provider_health, "probe_provider", counting_probe)

    await provider_health.provider_statuses()
    assert count == 1

    catalog.reload(path=catalog.CATALOG_PATH)
    await provider_health.provider_statuses()

    assert count == 2
