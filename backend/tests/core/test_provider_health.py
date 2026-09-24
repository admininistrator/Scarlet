"""`app/core/provider_health.py` — nguồn của `available` trong `GET /models`.

KH tham chiếu: §9.3, §9.5, §18.3, RR-5, UC-05, §24.2b·S5 · tasks.md T-3.6,
T-S.4, B-192 · NQ-113.

Không một ca nào ở đây chạm mạng thật: `probe_provider` là hàm **duy nhất**
gọi ra ngoài, nên mọi ca thay chính nó. Nhờ vậy bộ test đo đúng phần logic
(ai được đo, hỏng thì nói gì, vòng nền sống sót ra sao) chứ không đo xem
9Router trên máy này có đang bật hay không — thứ đổi theo từng lần chạy.

T-S.4: nửa đầu file đo **một lượt** (`refresh()`), nửa sau đo **vòng nền**
(`run_forever()`, `background()`) bằng đồng hồ giả — không ca nào mở một vòng
lặp vô hạn thật (Cạm bẫy ③). `_Stop` là `BaseException` để dừng vòng lặp từ
trong `sleep` giả: `except Exception` của vòng lặp không được nuốt nó, đúng
như nó không được nuốt `CancelledError`.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.config import catalog
from app.config.catalog import Catalog, Provider
from app.config.settings import settings
from app.core import provider_health
from app.core.provider_health import HOST_DEPENDENT, ProviderStatus

#: `background()` THẬT — lấy lúc import, trước khi fixture autouse của
#: `tests/conftest.py` (Phần 4) thay nó bằng bản không làm gì.
_REAL_BACKGROUND = provider_health.background

#: Khoá provider `host-dependent` duy nhất của catalog thật (§9.2).
NINEROUTER = "ninerouter"


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:
    """Bộ nhớ của module là state toàn cục — dọn trước VÀ sau mỗi ca.

    Trước, vì một ca chạy trước có thể để lại một lượt đo và ca sau sẽ xanh
    mà không đo gì. Sau, vì cùng lý do theo chiều ngược lại.
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

    status = (await provider_health.refresh()).statuses

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

    status = (await provider_health.refresh()).statuses

    nr = status[NINEROUTER]
    assert nr.available is False
    assert nr.reason is not None
    # T-S.3 / NQ-119: 9Router là đường trung gian (`user_visible: false`) ⇒ câu
    # chung, KHÔNG chèn tên đường đi.
    assert catalog.get_catalog().providers[NINEROUTER].user_visible is False
    assert nr.reason == provider_health.HIDDEN_NO_RESPONSE_REASON
    assert catalog.get_catalog().providers[NINEROUTER].label not in nr.reason


async def test_visible_host_dependent_reason_takes_label_from_catalog(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Provider `user_visible` thì câu vẫn chèn tên — lấy từ CATALOG, không literal."""
    raw = json.loads(catalog.CATALOG_PATH.read_text(encoding="utf-8"))
    raw["providers"][NINEROUTER]["user_visible"] = True
    catalog.reload(path=_write_catalog(tmp_path, raw))

    async def failing_probe(provider: Provider) -> None:
        raise ConnectionError("Connection refused")

    monkeypatch.setattr(provider_health, "probe_provider", failing_probe)

    status = (await provider_health.refresh()).statuses

    reason = status[NINEROUTER].reason
    assert reason is not None
    assert catalog.get_catalog().providers[NINEROUTER].label in reason


async def test_live_host_dependent_has_no_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def probe_ok(provider: Provider) -> None:
        return None

    monkeypatch.setattr(provider_health, "probe_provider", probe_ok)

    status = (await provider_health.refresh()).statuses

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
    monkeypatch.setattr(settings, "PROVIDER_PROBE_TIMEOUT_S", 0.05)

    status = (await provider_health.refresh()).statuses

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

    status = (await provider_health.refresh()).statuses

    assert status[NINEROUTER].available is True
    assert status[NINEROUTER].reason is None


# ═══════════════ T-S.4 — đọc không bao giờ đo; vòng nền với đồng hồ giả ══════


async def _probe_ok(provider: Provider) -> None:
    return None


class _Stop(BaseException):
    """Dừng `run_forever()` từ trong `sleep` giả — xem docstring module."""


class _FakeClock:
    """`clock` + `sleep` cho `run_forever()`. Không một giây thật nào trôi.

    `sleep` ghi lại từng khoảng ngủ, cộng nó vào đồng hồ, ném `_Stop` sau
    `rounds` vòng, còn không thì gọi `between(n)` (n = số vòng đã xong) để ca
    test chen việc vào giữa hai vòng.
    """

    def __init__(self, rounds: int, between: Callable[[int], None] | None = None) -> None:
        self.t = 1000.0
        self.sleeps: list[float] = []
        self.rounds = rounds
        self.between = between

    def now(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds
        if len(self.sleeps) >= self.rounds:
            raise _Stop
        if self.between is not None:
            self.between(len(self.sleeps))


async def _run_rounds(clock: _FakeClock) -> None:
    with pytest.raises(_Stop):
        await provider_health.run_forever(sleep=clock.sleep, clock=clock.now)


def test_provider_statuses_is_sync_so_no_request_can_await_a_probe() -> None:
    """NQ-113 bằng cấu trúc: hàm request gọi không phải coroutine."""
    assert not inspect.iscoroutinefunction(provider_health.provider_statuses)


def test_reading_never_probes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bộ nhớ trống (`checked_at` null) cũng KHÔNG kéo một lượt đo theo yêu cầu —
    đúng chỗ T-3.6 đã chờ 5 s (5.09 / 5.06 s, 2026-09-23)."""
    probed = 0

    async def counting_probe(provider: Provider) -> None:
        nonlocal probed
        probed += 1

    monkeypatch.setattr(provider_health, "probe_provider", counting_probe)

    for _ in range(5):
        snapshot = provider_health.provider_statuses()

    assert probed == 0
    assert snapshot.checked_at is None
    assert snapshot.statuses == {}


async def test_refresh_stamps_start_time_and_reading_returns_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`checked_at` = lúc lượt đo BẮT ĐẦU, lấy từ `_now()` (đồng hồ giả)."""
    at = datetime(2026, 9, 24, 6, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(provider_health, "_now", lambda: at)
    monkeypatch.setattr(provider_health, "probe_provider", _probe_ok)

    await provider_health.refresh()

    snapshot = provider_health.provider_statuses()
    assert snapshot.checked_at == at
    assert snapshot.statuses[NINEROUTER].available is True


async def test_loop_survives_a_round_that_raises(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """DoD T-S.4 dòng 4 + Cạm bẫy ①: vòng 1 ném ⇒ vòng 2 VẪN chạy và ghi bộ nhớ.

    Ném ở `_probe_all` chứ không ở `probe_provider`: lỗi của một provider đã bị
    `_probe_one` nuốt thành "không phản hồi"; thứ giết được một vòng là lỗi
    ngoài chỗ ấy (catalog hỏng, một bug) — đúng loại lỗi không ai lường trước.
    """
    rounds = 0

    async def flaky_probe_all(cat: Catalog) -> dict[str, ProviderStatus]:
        nonlocal rounds
        rounds += 1
        if rounds == 1:
            raise RuntimeError("vong dau hong")
        return {key: ProviderStatus(available=True, reason=None) for key in cat.providers}

    monkeypatch.setattr(provider_health, "_probe_all", flaky_probe_all)
    clock = _FakeClock(rounds=3)

    with caplog.at_level(logging.ERROR, logger=provider_health.logger.name):
        await _run_rounds(clock)

    assert rounds == 3
    assert provider_health.provider_statuses().checked_at is not None
    assert any("vong dau hong" in (r.exc_text or "") for r in caplog.records)


async def test_loop_keeps_a_fixed_rate_from_round_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Một lượt chạm trần không đẩy lượt sau lùi thêm một trần: nhịp tính từ
    lúc BẮT ĐẦU, nên bật lại 9Router thì ≤ một nhịp + một lượt là sáng."""
    clock = _FakeClock(rounds=2)

    async def slow_probe_all(cat: Catalog) -> dict[str, ProviderStatus]:
        clock.t += settings.PROVIDER_PROBE_TIMEOUT_S
        return {}

    monkeypatch.setattr(provider_health, "_probe_all", slow_probe_all)

    await _run_rounds(clock)

    expected = settings.PROVIDER_HEALTH_TTL_S - settings.PROVIDER_PROBE_TIMEOUT_S
    assert clock.sleeps == [expected, expected]


async def test_loop_never_sleeps_negative_when_a_round_outlasts_the_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FakeClock(rounds=1)

    async def very_slow_probe_all(cat: Catalog) -> dict[str, ProviderStatus]:
        clock.t += settings.PROVIDER_HEALTH_TTL_S * 3
        return {}

    monkeypatch.setattr(provider_health, "_probe_all", very_slow_probe_all)

    await _run_rounds(clock)

    assert clock.sleeps == [0.0]


async def test_catalog_reload_is_used_by_the_next_round(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """DoD T-S.4 dòng 4: `POST /admin/catalog/reload` ⇒ lượt đo KẾ dùng catalog
    mới. Giữa vòng 1 và vòng 2, một provider `always` thành `host-dependent`
    (có `health_path`) — vòng 2 phải đo nó, vòng 1 thì không."""
    raw = json.loads(catalog.CATALOG_PATH.read_text(encoding="utf-8"))
    new_key = next(k for k, p in raw["providers"].items() if p["availability"] != HOST_DEPENDENT)
    raw["providers"][new_key]["availability"] = HOST_DEPENDENT
    raw["providers"][new_key]["health_path"] = "/models"
    fixture = _write_catalog(tmp_path, raw)

    probed: list[list[str]] = [[]]

    async def recording_probe(provider: Provider) -> None:
        probed[-1].append(provider.label)

    def reload_between(done_rounds: int) -> None:
        probed.append([])
        catalog.reload(path=fixture)

    monkeypatch.setattr(provider_health, "probe_provider", recording_probe)
    clock = _FakeClock(rounds=2, between=reload_between)

    await _run_rounds(clock)

    new_label = catalog.get_catalog().providers[new_key].label
    assert len(probed) == 2
    assert new_label not in probed[0]
    assert new_label in probed[1]


async def test_background_waits_for_first_round_then_stops_the_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Việc ① T-S.4: request đầu sau khi `api` lên đã có `checked_at`; tắt
    tiến trình thì vòng nền dừng (không một task nào sót lại)."""
    monkeypatch.setattr(provider_health, "probe_provider", _probe_ok)

    def loop_tasks() -> list[asyncio.Task[object]]:
        return [t for t in asyncio.all_tasks() if t.get_name() == "provider-health"]

    async with _REAL_BACKGROUND():
        assert provider_health.provider_statuses().checked_at is not None
        assert loop_tasks()

    assert not loop_tasks()


async def test_background_waits_at_most_one_probe_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cạm bẫy ④: một lượt đầu treo không giữ `api` lâu hơn một trần đo, và
    không bị huỷ — nó vẫn chạy trong nền và ghi bộ nhớ khi xong."""
    monkeypatch.setattr(settings, "PROVIDER_PROBE_TIMEOUT_S", 0.05)
    release = asyncio.Event()

    async def hanging_probe_all(cat: Catalog) -> dict[str, ProviderStatus]:
        await release.wait()
        return {}

    monkeypatch.setattr(provider_health, "_probe_all", hanging_probe_all)
    loop = asyncio.get_running_loop()
    started = loop.time()

    async with _REAL_BACKGROUND():
        waited = loop.time() - started
        assert provider_health.provider_statuses().checked_at is None
        release.set()
        for _ in range(10):
            await asyncio.sleep(0)
        assert provider_health.provider_statuses().checked_at is not None

    assert waited < 1.0


def test_dead_loop_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    """Lưới cuối của Cạm bẫy ①: vòng lặp thoát không vì bị huỷ ⇒ `ERROR`."""

    async def dies() -> None:
        raise RuntimeError("chet")

    async def run() -> None:
        task = asyncio.create_task(dies())
        with pytest.raises(RuntimeError):
            await task
        provider_health._log_if_died(task)

    with caplog.at_level(logging.ERROR, logger=provider_health.logger.name):
        asyncio.run(run())

    assert any(r.levelno == logging.ERROR for r in caplog.records)
