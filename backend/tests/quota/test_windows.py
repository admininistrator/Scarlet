"""Hai cửa sổ trượt: khoá, member, dọn-trước-đọc, `retry_after` (§10.3) — T-2.11.

Redis GIẢ, và bản giả này mô phỏng **thật** hai lệnh ZSET — xem docstring
`FakeQuotaRedis` ở `tests/conftest.py` cho lý do (khác `FakeRateLimitRedis`
của T-2.9, nơi một bản mô phỏng Lua bằng Python sẽ là bản hiện thực thứ hai).
Nó đến qua **fixture** `quota_redis_fake` chứ không qua `import`: `tests/`
không phải package.

Phép tính `retry_after` là phần đắt nhất của file này và nó **không** cần
Redis: `WindowState` là một dataclass thuần, nên mọi ca biên đo được bằng số.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest

from app.config.settings import settings
from app.quota.windows import (
    LimitType,
    Window,
    WindowState,
    encode_member,
    parse_member,
    read_window,
    windows,
)

USER = uuid.UUID("11111111-1111-1111-1111-111111111111")
NOW = 1_800_000_000.0


def _window(seconds: int = 18000) -> Window:
    return Window(LimitType.SHORT, seconds)


def _state(*entries: tuple[float, str], seconds: int = 18000) -> WindowState:
    item = tuple((score, Decimal(cost)) for score, cost in entries)
    return WindowState(
        window=_window(seconds),
        spent=sum((cost for _, cost in item), Decimal(0)),
        entries=item,
    )


# ════════════════════════════ khoá và member ═══════════════════════════════


def test_key_carries_window_name_and_user_id() -> None:
    assert _window().key(USER) == f"quota:5h:{USER}"
    assert Window(LimitType.LONG, 604800).key(USER) == f"quota:weekly:{USER}"


def test_both_windows_read_length_from_settings_at_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """A3: hai con số là cấu hình, và `windows()` phải đọc chúng ở lúc GỌI."""
    monkeypatch.setattr(settings, "QUOTA_WINDOW_SHORT_S", 42)
    short_window, long_window = windows()
    assert (short_window.limit_type, short_window.seconds) == (LimitType.SHORT, 42)
    assert long_window.limit_type is LimitType.LONG


def test_member_round_trips_through_string_keeping_number() -> None:
    usage_id = uuid.uuid4()
    member = encode_member(usage_id, Decimal("0.001234"))
    assert member == f"{usage_id}:0.001234"
    assert parse_member(member) == Decimal("0.001234")


def test_member_keeps_all_six_decimals() -> None:
    """`NUMERIC(12,6)` của Phụ lục A — thiếu một chữ số là một phép đối chiếu tự sai."""
    assert parse_member(encode_member(uuid.uuid4(), Decimal("0.000001"))) == Decimal("0.000001")


def test_broken_member_returns_none_not_raise() -> None:
    assert parse_member("khong-co-dau-hai-cham") is None
    assert parse_member(f"{uuid.uuid4()}:khong-phai-so") is None


# ══════════════════════════ dọn trước, đọc sau ═════════════════════════════


async def test_cleanup_runs_before_read_with_right_bound(quota_redis_fake: Any) -> None:
    redis = quota_redis_fake
    window = _window(100)
    key = window.key(USER)
    redis.zset[key] = {
        encode_member(uuid.uuid4(), Decimal("1.5")): NOW - 150,  # quá hạn
        encode_member(uuid.uuid4(), Decimal("2.5")): NOW - 50,  # còn trong cửa sổ
    }

    state = await read_window(redis, window, user_id=USER, now=NOW)

    assert redis.cleaned == [(key, "-inf", f"({NOW - 100}")]
    assert state.spent == Decimal("2.5")
    assert len(redis.zset[key]) == 1


async def test_empty_window_yields_no_rows(quota_redis_fake: Any) -> None:
    state = await read_window(quota_redis_fake, _window(), user_id=USER, now=NOW)
    assert state.spent == Decimal(0)
    assert state.entries == ()


async def test_broken_member_skipped_not_failing_whole_read(
    caplog: pytest.LogCaptureFixture, quota_redis_fake: Any
) -> None:
    redis = quota_redis_fake
    window = _window(100)
    redis.zset[window.key(USER)] = {
        "rac-khong-doc-duoc": NOW - 10,
        encode_member(uuid.uuid4(), Decimal("0.5")): NOW - 10,
    }
    with caplog.at_level("WARNING", logger="app.quota.windows"):
        state = await read_window(redis, window, user_id=USER, now=NOW)
    assert state.spent == Decimal("0.5")
    assert "khong doc duoc" in caplog.text


async def test_dead_redis_raises_not_returns_empty_window(quota_redis_fake: Any) -> None:
    """Cửa sổ rỗng giả nghĩa là "chưa tiêu gì" — chỗ gọi mới được quyết định."""
    redis = quota_redis_fake
    redis.fail = True
    with pytest.raises(ConnectionError):
        await read_window(redis, _window(), user_id=USER, now=NOW)


# ═══════════════════════ retry_after theo §10.3 ════════════════════════════


def test_retry_after_is_when_oldest_item_leaves_window() -> None:
    """§10.3: `score` của phần tử cũ nhất cần rơi ra + độ dài cửa sổ − now."""
    state = _state((NOW - 17000, "1.0"), (NOW - 10000, "1.0"), seconds=18000)
    # Cần nhả 0.5 USD ⇒ chỉ phần tử cũ nhất là đủ ⇒ rơi sau 18000 − 17000 = 1000 s.
    assert state.retry_after_s(need_to_free=Decimal("0.5"), now=NOW) == 1000


def test_retry_after_moves_on_when_one_item_not_enough() -> None:
    state = _state((NOW - 17000, "1.0"), (NOW - 10000, "1.0"), seconds=18000)
    # Cần 1.5 ⇒ phải nhả cả hai ⇒ mốc là phần tử THỨ HAI: 18000 − 10000 = 8000 s.
    assert state.retry_after_s(need_to_free=Decimal("1.5"), now=NOW) == 8000


def test_retry_after_rounds_UP() -> None:
    """Làm tròn xuống là hẹn client quay lại lúc vẫn còn bị chặn (`_ceil_seconds`).

    Mốc rơi ra sau **3.2 s**: làm tròn lên ra 4, làm tròn xuống ra 3 — và 3 là
    một lời hẹn sai. Con số phải đủ xa 0 để phép so sánh không bị `max(1, …)`
    che mất: đó chính là chỗ bản đầu của test này trượt.
    """
    state = _state((NOW - 17996.8, "1.0"), seconds=18000)
    assert state.retry_after_s(need_to_free=Decimal("0.5"), now=NOW) == 4


def test_retry_after_at_least_1_second() -> None:
    """`0` nghĩa là "thử ngay đi", tức một vòng lặp bận."""
    state = _state((NOW - 17999.9, "1.0"), seconds=18000)
    assert state.retry_after_s(need_to_free=Decimal("0.5"), now=NOW) == 1


def test_retry_after_none_when_emptying_window_still_not_enough() -> None:
    """Ca của DoD dòng 1: một lượt sinh đơn lẻ đã vượt trần, không có gì để hẹn."""
    state = _state((NOW - 10000, "1.0"), seconds=18000)
    assert state.retry_after_s(need_to_free=Decimal("99"), now=NOW) is None


def test_retry_after_none_for_empty_window() -> None:
    assert _state().retry_after_s(need_to_free=Decimal("1"), now=NOW) is None


def test_retry_after_none_when_nothing_to_release() -> None:
    state = _state((NOW - 10, "1.0"))
    assert state.retry_after_s(need_to_free=Decimal(0), now=NOW) is None
