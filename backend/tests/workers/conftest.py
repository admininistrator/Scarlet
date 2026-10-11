"""Vá `get_redis` của `app.quota.tiers` cho mọi test worker (lối `tests/api/conftest.py`).

T-7.7a: `generate._prepare` đọc `can_execute_skills` qua `get_effective_limits`
mỗi lượt có model `tools` — không vá thì mỗi test hỏi DNS `redis` thật (~20 s
từ WSL) rồi mới lùi về Postgres.
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _tier_cache_redis(monkeypatch: pytest.MonkeyPatch, quota_redis_fake: Any) -> None:
    monkeypatch.setattr("app.quota.tiers.get_redis", lambda: quota_redis_fake)
