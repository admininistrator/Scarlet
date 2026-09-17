"""Hạ tầng dùng chung cho test tầng API — luật §11.4 gắn ở ROUTER (T-2.8).

Từ T-2.8, `api/v1/__init__.py` gắn `require_idempotency(...)` vào lời gọi
`include_router` của `stream`/`conversations`/`messages`. Đó chính là tính chất
mà task muốn (không endpoint nào quên được), và cái giá của nó là: **mọi POST
đã xác thực trong ba router đó đều đi qua Redis**, kể cả những POST của các
test viết từ Phase 1 chẳng liên quan gì tới idempotency.

Hai mảnh ở đây trả giá đó một lần cho cả thư mục, thay vì bắt chín file test
tự lo:

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

import httpx
import pytest

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
