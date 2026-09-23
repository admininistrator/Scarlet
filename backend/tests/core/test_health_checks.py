"""`app/core/health_checks.py` — B-193 (lý do không rỗng) và B-192 (bộ nhớ).

KH tham chiếu: §18.6, §21.2, §16.3 · tasks.md T-2.20, T-3.12, B-192, B-193.

**B-193** đo được hai lần trong DoD của T-2.20: `{"ok": false, "latency_ms":
2000, "error": ""}` cho `redis` lúc container đã dừng — `asyncio.wait_for` hết
giờ ném `TimeoutError` với `str()` rỗng. Hai ca đầu của file này đi đúng
đường ấy (`_timed` với một coroutine không bao giờ xong), không gọi thẳng hàm
định dạng — vì chỗ hỏng là *đường* từ exception tới `CheckResult.error`.

**B-192** — `CachedChecks` nhớ một lượt đo `ttl_s` giây. Ba tính chất: lượt
hỏi thứ hai trong hạn **không** đo lại; các lượt hỏi TRÙNG LÚC khi bộ nhớ
rỗng chỉ đo **một** lần; hết hạn thì đo lại và mốc `checked_at` đổi theo.
"""

from __future__ import annotations

import asyncio

import pytest

from app.core import health_checks
from app.core.health_checks import CachedChecks, CheckResult, describe_error


async def _never_finishes() -> None:
    await asyncio.Event().wait()


async def test_timeout_leaves_no_empty_string(monkeypatch: pytest.MonkeyPatch) -> None:
    """B-193 — ca đã lọt: hết giờ ⇒ `error` phải nói được "hết giờ"."""
    monkeypatch.setattr(health_checks, "CHECK_TIMEOUT_S", 0.01)

    _, result = await health_checks._timed("redis", _never_finishes())

    assert result.ok is False
    assert result.error
    assert result.error.strip() != ""
    assert "TimeoutError" in result.error


async def test_exception_without_message_still_has_type_name() -> None:
    """Không chỉ timeout — mọi exception có `str()` rỗng (vài lỗi của redis-py)."""

    async def broken() -> None:
        raise ConnectionError()

    _, result = await health_checks._timed("redis", broken())

    assert result.error == "ConnectionError"


async def test_exception_with_message_keeps_both() -> None:
    async def broken() -> None:
        raise ConnectionError("Error 111 connecting to redis:6379.")

    _, result = await health_checks._timed("redis", broken())

    assert result.error == "ConnectionError: Error 111 connecting to redis:6379."


def test_whitespace_only_message_counts_as_empty() -> None:
    assert describe_error(ValueError("   ")) == "ValueError"


def test_reason_is_truncated_at_cap() -> None:
    assert len(describe_error(ValueError("x" * 1000))) == health_checks.ERROR_MAX_CHARS


# ═══════════════════════════ B-192 — CachedChecks ═══════════════════════════


class _ProbeCounter:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self) -> dict[str, CheckResult]:
        self.calls += 1
        # Nhường vòng lặp một nhịp: đủ để các lượt hỏi trùng lúc chen vào
        # giữa lúc "đang đo" — đúng khe mà khoá phải đóng.
        await asyncio.sleep(0)
        return {"redis": CheckResult(ok=True, latency_ms=self.calls)}


async def test_asking_again_within_ttl_does_not_reprobe() -> None:
    cache = CachedChecks()
    do = _ProbeCounter()

    first = await cache.get(do, ttl_s=60)
    again = await cache.get(do, ttl_s=60)

    assert do.calls == 1
    assert again.checked_at == first.checked_at
    assert again.checks == first.checks


async def test_concurrent_asks_on_empty_cache_probe_once() -> None:
    cache = CachedChecks()
    do = _ProbeCounter()

    result = await asyncio.gather(*(cache.get(do, ttl_s=60) for _ in range(5)))

    assert do.calls == 1
    assert len({r.checked_at for r in result}) == 1


async def test_expiry_reprobes_and_changes_probe_time(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = CachedChecks()
    do = _ProbeCounter()
    clock = [1000.0]
    monkeypatch.setattr(health_checks.time, "monotonic", lambda: clock[0])

    first = await cache.get(do, ttl_s=10)
    clock[0] += 9.9
    await cache.get(do, ttl_s=10)
    assert do.calls == 1

    clock[0] += 0.2
    after = await cache.get(do, ttl_s=10)

    assert do.calls == 2
    assert after.checked_at >= first.checked_at
    assert after.checks["redis"].latency_ms == 2


async def test_clear_forces_reprobe() -> None:
    cache = CachedChecks()
    do = _ProbeCounter()

    await cache.get(do, ttl_s=60)
    cache.clear()
    await cache.get(do, ttl_s=60)

    assert do.calls == 2
