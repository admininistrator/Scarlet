"""Hạ tầng dùng chung cho test tầng API — luật §11.4 gắn ở ROUTER (T-2.8).

Từ T-2.8, `api/v1/__init__.py` gắn `require_idempotency(...)` vào lời gọi
`include_router` của `stream`/`conversations`/`messages`. Đó chính là tính chất
mà task muốn (không endpoint nào quên được), và cái giá của nó là: **mọi POST
đã xác thực trong ba router đó đều đi qua Redis**, kể cả những POST của các
test viết từ Phase 1 chẳng liên quan gì tới idempotency.

Ba mảnh ở đây trả giá đó một lần cho cả thư mục, thay vì bắt chín file test
tự lo (mảnh thứ ba, `ratelimit_redis`, đến từ T-2.9 vì cùng một lý do: ba route
sinh chữ nay đi qua token bucket và trần đồng thời của §10.6):

1. `idempotency_redis` — **autouse**. Redis thật nằm ở `redis:6379`, một host
   chỉ phân giải được bên trong network `internal` của compose, còn `make test`
   chạy từ WSL host (cùng lý do đã ghi ở `ArqGia` của `test_messages.py`).
   Autouse chứ không phải xin-thì-có: một file test quên xin sẽ không đỏ ngay
   mà **treo** ở lần kết nối Redis đầu tiên, và đó là kiểu hỏng khó truy nhất.
2. `event_hooks` — client của test tự gắn một `Idempotency-Key` **mới cho mỗi
   POST**, đúng hành vi mà C22 đòi ở FE ("key gắn với lần soạn thảo, đổi sau
   khi gửi thành công"). Nhờ vậy 60+ lời gọi POST có sẵn không phải sửa, và
   quan trọng hơn: không lời gọi nào vô tình dùng lại key của lời gọi trước —
   nếu dùng lại, request thứ hai sẽ nhận **bản phát lại** của request thứ nhất
   và test sẽ đỏ theo một cách rất khó hiểu.

Test nào muốn kiểm chính luật §11.4 thì đặt header tay (hook không đè lên
header đã có) hoặc tự dựng `AsyncClient` không có hook — xem
`tests/api/test_idempotency.py`.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest

from app.core import ratelimit
from app.core.idempotency import HEADER_IDEMPOTENCY


class FakeIdempotencyRedis:
    """Redis trong bộ nhớ — đúng ba lệnh mà `core/idempotency.py` dùng.

    `set(..., nx=True)` tôn trọng NX **thật sự** chứ không ghi bừa: đó chính là
    tính chất mà cả §11.4 dựa vào, nên một stub dễ tính hơn Redis thật sẽ làm
    phép kiểm mất nghĩa (bài học B-102, cùng lối `_RedisDem` của
    `tests/core/test_ratelimit.py`).

    `ttl` giữ lại giá trị `ex` đã truyền để DoD dòng 4 ("`TTL idem:...` ≈
    86400") kiểm được mà không cần một Redis thật.
    """

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttl: dict[str, int] = {}
        #: Bật lên để mô phỏng Redis chết giữa chừng.
        self.fail = False

    async def set(
        self, name: str, value: str, *, nx: bool = False, ex: int | None = None
    ) -> bool | None:
        if self.fail:
            raise ConnectionError("redis chet (gia lap)")
        if nx and name in self.store:
            return None
        self.store[name] = value
        if ex is not None:
            self.ttl[name] = ex
        return True

    async def get(self, name: str) -> str | None:
        if self.fail:
            raise ConnectionError("redis chet (gia lap)")
        return self.store.get(name)

    async def delete(self, *names: str) -> int:
        if self.fail:
            raise ConnectionError("redis chet (gia lap)")
        removed = 0
        for name in names:
            if self.store.pop(name, None) is not None:
                removed += 1
            self.ttl.pop(name, None)
        return removed


@pytest.fixture(autouse=True)
def idempotency_redis(monkeypatch: pytest.MonkeyPatch) -> FakeIdempotencyRedis:
    """Redis giả cho `core/idempotency.py`. Xem docstring module."""
    fake = FakeIdempotencyRedis()
    monkeypatch.setattr("app.core.idempotency.get_redis", lambda: fake)
    return fake


class FakeRateLimitRedis:
    """Stub Redis cho `core/ratelimit.py` — **không** mô phỏng Lua (T-2.9).

    Khác `FakeIdempotencyRedis` ở trên một chỗ căn bản, và chỗ đó là chủ ý.
    `SET NX` mô phỏng được bằng ba dòng Python và bản mô phỏng ấy *đúng*, nên
    fake kia tôn trọng NX thật sự. Hai script Lua của T-2.9 thì không: dịch
    chúng sang Python là dựng một **bản hiện thực thứ hai**, và khi ấy test sẽ
    xanh cả trong trường hợp bản Lua thật đã hỏng — tệ hơn không có test, đúng
    bài học B-102 đọc theo chiều ngược lại.

    Nên `eval` ở đây chỉ **trả lời theo kịch bản** (`bucket`, `slot`) và ghi
    lại ARGV nó nhận được. Nó kiểm được:

        * route nào có gọi hạn mức, route nào không
        * `429`/`503` đi ra đúng mã lỗi, đúng header
        * `_ghe_can_nha` chọn đúng ghế để nhả (phần này là Python thuần)

    Nó **không** kiểm được phép tính nạp lại và tính nguyên tử của script. Hai
    thứ đó chỉ chứng minh được trên Redis thật — `scripts/test_ratelimit.sh`,
    DoD T-2.9 dòng 1 và 2. Xem B-149.


    Nó phủ **cả ba** lớp của `core/ratelimit.py` chứ không riêng hai lớp mới:
    một module, một `get_redis`, nên một fake thiếu lệnh là một test treo.
    Phần theo IP (`incr`/`expire`/`ttl`) mô phỏng thật, đúng như `_RedisDem`
    của `tests/core/test_ratelimit.py` — ở đó bản mô phỏng *đúng* được.
    """

    def __init__(self) -> None:
        #: `[allowed, remaining, retry_after_ms, reset_ms]` cho LUA_TOKEN_BUCKET.
        self.bucket: list[int] = [1, 19, 0, 3000]
        #: `[cho_phep, dang_chay]` cho LUA_GIU_GHE.
        self.slot: list[int] = [1, 1]
        #: ZSET ghế bận, dùng cho `zrange`/`zrem`.
        self.zset: dict[str, dict[str, float]] = {}
        #: ARGV của mỗi lần `eval`, theo thứ tự — test đọc để biết script nào
        #: đã chạy và nó được truyền những ghế nào để nhả.
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        #: Mỗi lời gọi `zrem` — test đọc để biết ghế có được nhả hay không.
        self.da_nha: list[tuple[str, tuple[str, ...]]] = []
        #: Bộ đếm + TTL của lớp theo IP (T-2.5).
        self.dem: dict[str, int] = {}
        self.ttl_da_dat: dict[str, int] = {}
        #: Bật lên để mô phỏng Redis chết giữa chừng.
        self.fail = False

    async def eval(self, script: str, numkeys: int, *args: object) -> list[int]:
        if self.fail:
            raise ConnectionError("redis chet (gia lap)")
        if script is ratelimit.LUA_TOKEN_BUCKET:
            self.calls.append(("bucket", args))
            return list(self.bucket)
        if script is ratelimit.LUA_GIU_GHE:
            self.calls.append(("slot", args))
            return list(self.slot)
        raise AssertionError("script Lua khong biet — fake nay chi phuc vu T-2.9")

    async def zrange(
        self, name: str, start: int, end: int, *, withscores: bool = False
    ) -> list[tuple[str, float]]:
        if self.fail:
            raise ConnectionError("redis chet (gia lap)")
        assert withscores, "`nhan_ghe_sinh` luon doc kem score — xem PHANTOM_GRACE_S"
        return sorted(self.zset.get(name, {}).items(), key=lambda item: item[1])

    async def zrem(self, name: str, *members: str) -> int:
        if self.fail:
            raise ConnectionError("redis chet (gia lap)")
        self.da_nha.append((name, members))
        ghe = self.zset.get(name, {})
        return sum(1 for member in members if ghe.pop(member, None) is not None)

    # ── lớp theo IP (T-2.5): cửa sổ cố định, mô phỏng đầy đủ ──
    async def incr(self, name: str) -> int:
        if self.fail:
            raise ConnectionError("redis chet (gia lap)")
        self.dem[name] = self.dem.get(name, 0) + 1
        return self.dem[name]

    async def expire(self, name: str, time: int, *, nx: bool = False) -> bool:
        if self.fail:
            raise ConnectionError("redis chet (gia lap)")
        if nx and name in self.ttl_da_dat:
            return False
        self.ttl_da_dat[name] = time
        return True

    async def ttl(self, name: str) -> int:
        if name not in self.dem:
            return -2
        return self.ttl_da_dat.get(name, -1)


@pytest.fixture(autouse=True)
def ratelimit_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRateLimitRedis:
    """Redis giả cho `core/ratelimit.py`. **Autouse**, cùng lý do fixture trên.

    Từ T-2.9, ba route sinh chữ đi qua token bucket và trần đồng thời, và cả
    hai chạm Redis. Không có fixture này thì `tests/api/test_messages.py` treo
    ở lần nối `redis:6379` chứ không đỏ — đúng kiểu hỏng mà `idempotency_redis`
    đã phải trả giá một lần để học.

    Mặc định trả lời "cho qua" nên 60+ lời gọi POST có sẵn không phải sửa; test
    nào muốn kiểm chính hạn mức thì đặt `bucket`/`slot` theo kịch bản của mình.
    """
    fake = FakeRateLimitRedis()
    monkeypatch.setattr("app.core.ratelimit.get_redis", lambda: fake)
    return fake


@pytest.fixture(autouse=True)
def quota_redis(monkeypatch: pytest.MonkeyPatch, quota_redis_fake: Any) -> Any:
    """Redis giả cho `app/quota/`. **Autouse**, cùng lý do hai fixture trên.

    Từ T-2.11, ba route sinh chữ đi qua cửa chặn §10.2, thứ đọc hai ZSET quota
    **và** cache hạn mức tier. Mặc định cả hai đều rỗng nên đường đi thường là
    "chưa tiêu gì, hạn mức đọc từ Postgres" — 60+ lời gọi POST có sẵn không
    phải sửa. Test nào muốn kiểm chính cửa chặn thì tự nạp vào `zset`.

    Vá **cả hai** module vì `estimator` và `tiers` dùng chung một `get_redis`;
    một module bị bỏ sót là một test **treo** ở lần nối `redis:6379` chứ không
    đỏ (đúng bài học `idempotency_redis` của T-2.8).

    Lớp `FakeQuotaRedis` sống ở `tests/conftest.py` chứ không ở đây, và nó
    đi qua **fixture** chứ không qua `import`: `tests/` không phải package
    (không có `__init__.py`) nên `from tests.conftest import ...` không chạy —
    cùng lý do đã ghi ở `event_hooks` ngay dưới. Đó cũng là lý do kiểu ở đây
    là `Any`.
    """
    monkeypatch.setattr("app.quota.estimator.get_redis", lambda: quota_redis_fake)
    monkeypatch.setattr("app.quota.tiers.get_redis", lambda: quota_redis_fake)
    return quota_redis_fake


async def _attach_idempotency_key(request: httpx.Request) -> None:
    """Mỗi POST một key mới — client của test cư xử như FE của C22."""
    if request.method == "POST" and HEADER_IDEMPOTENCY not in request.headers:
        request.headers[HEADER_IDEMPOTENCY] = uuid.uuid4().hex


@pytest.fixture
def event_hooks() -> dict[str, list[Callable[[httpx.Request], Awaitable[None]]]]:
    """Truyền vào `AsyncClient(event_hooks=...)` — xem docstring module.

    Là một **fixture** chứ không phải hằng số import được: `tests/` không phải
    package (không có `__init__.py`), nên `from tests.api.conftest import ...`
    không chạy. Fixture là đường pytest vốn dựng sẵn để chia sẻ thứ như thế.
    """
    return {"request": [_attach_idempotency_key]}
