"""T-1.9 — `app/streaming/cancel.py`: hợp đồng cờ huỷ giữa `api` và `worker` (§7.5).

File này kiểm đúng ba thứ mà hai tiến trình phải hiểu giống nhau: hình dạng
khoá, việc `SET` có kèm TTL, và việc `EXISTS` ra một `bool`.

Vì sao đáng một file riêng: khoá là thứ DUY NHẤT nối `POST /messages/{id}/cancel`
với vòng lặp trong `workers/generate.py`, và nếu hai đầu gõ lệch tiền tố thì
**không có gì báo lỗi** — nút Dừng chỉ đơn giản không bao giờ dừng được gì.
Cùng lý do `tests/streaming/test_producer.py` khoá `stream_key()` lại.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.streaming.cancel import (
    CANCEL_KEY_PREFIX,
    FINISH_REASON_CANCELLED,
    FLAG_VALUE,
    cancel_key,
    is_cancel_requested,
    set_cancel_flag,
)


class FakeRedis:
    """Chỉ đủ `set`/`exists`, và ghi lại mọi tham số để khẳng định được."""

    def __init__(self) -> None:
        self.set_calls: list[tuple[str, str, Any]] = []
        self.flags: set[str] = set()

    async def set(self, name: str, value: str, *, ex: int | None = None) -> bool:
        self.set_calls.append((name, value, ex))
        self.flags.add(name)
        return True

    async def exists(self, name: str) -> int:
        return 1 if name in self.flags else 0


def test_key_uses_planned_prefix() -> None:
    """§7.5 viết `cancel:{amid}`. UUID và chuỗi phải ra cùng một khoá."""
    mid = uuid.uuid4()

    assert cancel_key(mid) == f"cancel:{mid}"
    assert cancel_key(str(mid)) == cancel_key(mid)
    assert CANCEL_KEY_PREFIX == "cancel:"


async def test_setting_flag_carries_ttl() -> None:
    """`SET cancel:{id} 1 EX <ttl>` — thiếu `EX` là C8 ở dạng thứ hai."""
    redis = FakeRedis()
    mid = uuid.uuid4()

    await set_cancel_flag(redis, mid, ttl_s=300)

    assert redis.set_calls == [(f"cancel:{mid}", FLAG_VALUE, 300)]


async def test_setting_flag_twice_extends_clock() -> None:
    """Bấm Dừng lần hai phải đặt lại TTL, không giữ đồng hồ của lần đầu.

    Đây là lý do `cancel.py` dùng `SET` chứ không `SETNX`: lần bấm thứ hai
    nghĩa là người dùng **vẫn** đang chờ nó dừng.
    """
    redis = FakeRedis()
    mid = uuid.uuid4()

    await set_cancel_flag(redis, mid, ttl_s=300)
    await set_cancel_flag(redis, mid, ttl_s=300)

    assert len(redis.set_calls) == 2
    assert {ex for _, _, ex in redis.set_calls} == {300}


@pytest.mark.parametrize("preset", [True, False])
async def test_reading_flag_returns_bool(preset: bool) -> None:
    redis = FakeRedis()
    mid = uuid.uuid4()
    if preset:
        await set_cancel_flag(redis, mid, ttl_s=300)

    result = await is_cancel_requested(redis, mid)

    assert result is preset
    assert isinstance(result, bool), "chỗ gọi là một câu `if`, không phải một phép so số"


async def test_flag_of_one_message_does_not_affect_another() -> None:
    """Một khoá cho mỗi message — huỷ lượt này không dừng lượt đang chạy song song."""
    redis = FakeRedis()
    first, second = uuid.uuid4(), uuid.uuid4()

    await set_cancel_flag(redis, first, ttl_s=300)

    assert await is_cancel_requested(redis, first) is True
    assert await is_cancel_requested(redis, second) is False


def test_finish_reason_is_the_planned_string() -> None:
    """§7.5: `UPDATE finish_reason='cancelled'`. FE phân nhánh theo đúng chuỗi này."""
    assert FINISH_REASON_CANCELLED == "cancelled"
