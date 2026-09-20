"""Hạ tầng dùng chung cho test tầng API — luật §11.4 gắn ở ROUTER (T-2.8).

Từ T-2.8, `api/v1/__init__.py` gắn `require_idempotency(...)` vào lời gọi
`include_router` của `stream`/`conversations`/`messages`. Đó chính là tính chất
mà task muốn (không endpoint nào quên được), và cái giá của nó là: **mọi POST
đã xác thực trong ba router đó đều đi qua Redis**, kể cả những POST của các
test viết từ Phase 1 chẳng liên quan gì tới idempotency.

Bốn mảnh trả giá đó một lần cho cả thư mục, thay vì bắt chín file test tự lo
(mảnh thứ ba, `ratelimit_redis`, đến từ T-2.9 vì cùng một lý do: ba route sinh
chữ nay đi qua token bucket và trần đồng thời của §10.6; mảnh thứ tư,
`blacklist_redis`, đến từ T-3.1c vì **mọi** request mang cookie phiên đều hỏi
blacklist §11.3):

1. `idempotency_redis` — **autouse**. Redis thật nằm ở `redis:6379`, một host
   chỉ phân giải được bên trong network `internal` của compose, còn `make test`
   chạy từ WSL host (cùng lý do đã ghi ở `ArqGia` của `test_messages.py`).
   Autouse chứ không phải xin-thì-có: một file test quên xin sẽ không đỏ ngay
   mà **treo** ở lần kết nối Redis đầu tiên, và đó là kiểu hỏng khó truy nhất.
2. `ratelimit_redis` — **autouse**, cùng lý do.
3. `blacklist_redis` — **autouse**, cùng lý do. Từ T-3.1c, `core/deps.py`
   không còn nhánh danh tính tạm nào, nên mọi file test của thư mục này dựng
   danh tính bằng một cookie phiên thật — và `get_access_claims` hỏi Redis ở
   MỌI request có cookie. Lớp `FakeBlacklistRedis` nằm ở conftest gốc, xem
   docstring của nó.
4. `event_hooks` — client của test tự gắn một `Idempotency-Key` mới cho mỗi
   POST.

**Từ T-2.18, cả ba mảnh SỐNG Ở `tests/conftest.py`, không ở đây nữa.** Lớp
`FakeIdempotencyRedis`, lớp `FakeRateLimitRedis` và `event_hooks` chuyển lên
conftest gốc không đổi một dòng hành vi; chỗ này giữ lại đúng phần *dành riêng
cho thư mục `api/`*: ba fixture autouse đi **vá** `get_redis` của từng module.
Lý do chuyển nằm trong chính conftest gốc — `tests/` không phải package nên
`tests/security/` không import được chúng từ đây, và một bản mô phỏng Redis
thứ ba viết riêng cho bộ test IDOR là đúng hình dạng B-102 đã cấm.

Cách chia ấy không mới: `FakeQuotaRedis` đã nằm ở conftest gốc từ T-2.11 với
fixture autouse `quota_redis` ở đây. Nay cả ba theo cùng một khuôn.
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture(autouse=True)
def idempotency_redis(monkeypatch: pytest.MonkeyPatch, idempotency_redis_fake: Any) -> Any:
    """Redis giả cho `core/idempotency.py`. Xem docstring module."""
    monkeypatch.setattr("app.core.idempotency.get_redis", lambda: idempotency_redis_fake)
    return idempotency_redis_fake


@pytest.fixture(autouse=True)
def ratelimit_redis(monkeypatch: pytest.MonkeyPatch, ratelimit_redis_fake: Any) -> Any:
    """Redis giả cho `core/ratelimit.py`. **Autouse**, cùng lý do fixture trên.

    Từ T-2.9, ba route sinh chữ đi qua token bucket và trần đồng thời, và cả
    hai chạm Redis. Không có fixture này thì `tests/api/test_messages.py` treo
    ở lần nối `redis:6379` chứ không đỏ — đúng kiểu hỏng mà `idempotency_redis`
    đã phải trả giá một lần để học.

    Mặc định trả lời "cho qua" nên 60+ lời gọi POST có sẵn không phải sửa; test
    nào muốn kiểm chính hạn mức thì đặt `bucket`/`slot` theo kịch bản của mình.
    """
    monkeypatch.setattr("app.core.ratelimit.get_redis", lambda: ratelimit_redis_fake)
    return ratelimit_redis_fake


@pytest.fixture(autouse=True)
def blacklist_redis(monkeypatch: pytest.MonkeyPatch, blacklist_redis_fake: Any) -> Any:
    """Redis giả cho blacklist của `core/deps.py` (§11.3). Xem docstring module.

    File test nào cần quan sát chính blacklist (`test_auth.py`, `test_admin.py`)
    vá một Redis của riêng nó lên cùng mục tiêu; fixture của file chạy SAU
    fixture autouse của conftest, nên bản của file thắng.
    """
    monkeypatch.setattr("app.core.deps.get_redis", lambda: blacklist_redis_fake)
    return blacklist_redis_fake


@pytest.fixture(autouse=True)
def quota_redis(monkeypatch: pytest.MonkeyPatch, quota_redis_fake: Any) -> Any:
    """Redis giả cho `app/quota/`. **Autouse**, cùng lý do hai fixture trên.

    Từ T-2.11, ba route sinh chữ đi qua cửa chặn §10.2, thứ đọc hai ZSET quota
    **và** cache hạn mức tier. Mặc định cả hai đều rỗng nên đường đi thường là
    "chưa tiêu gì, hạn mức đọc từ Postgres" — 60+ lời gọi POST có sẵn không
    phải sửa. Test nào muốn kiểm chính cửa chặn thì tự nạp vào `zset`.

    Vá **cả ba** module vì `estimator`, `tiers` và (từ T-3.0) `snapshot` dùng
    chung một `get_redis`; một module bị bỏ sót là một test **treo** ở lần nối
    `redis:6379` chứ không đỏ (đúng bài học `idempotency_redis` của T-2.8).
    `snapshot` vào danh sách này từ lúc `GET /auth/me` đọc quota (B-158), tức
    từ lúc một endpoint **không** sinh chữ cũng chạm hai ZSET.

    Lớp `FakeQuotaRedis` sống ở `tests/conftest.py` chứ không ở đây, và nó
    đi qua **fixture** chứ không qua `import`: `tests/` không phải package
    (không có `__init__.py`) nên `from tests.conftest import ...` không chạy.
    Đó cũng là lý do kiểu ở đây là `Any`.
    """
    monkeypatch.setattr("app.quota.estimator.get_redis", lambda: quota_redis_fake)
    monkeypatch.setattr("app.quota.tiers.get_redis", lambda: quota_redis_fake)
    monkeypatch.setattr("app.quota.snapshot.get_redis", lambda: quota_redis_fake)
    return quota_redis_fake
