"""Hạ tầng dùng chung cho cả bộ test: biến môi trường tối thiểu + Postgres thật.

Hai phần, hai lý do khác nhau — đọc riêng từng phần.

── Phần 1: biến môi trường ─────────────────────────────────────────────────

`app/config/settings.py` khởi tạo `settings` ngay lúc import (fail-fast, §19.2
L2), nên test phải có đủ biến bắt buộc **trước** khi import module đó. Dùng
`setdefault` để không đè lên biến thật nếu người chạy test đã export sẵn.

Đây là chỗ duy nhất ngoài config layer chạm vào `os.environ`, và nó nằm ngoài
`app/` nên không phá luật §19.2.

── Phần 2: Postgres thật cho test tầng DB (NQ-17) ──────────────────────────

Vì sao không mock và không SQLite: thứ cần kiểm ở T-1.1 chính là những thứ chỉ
Postgres có — kiểu ENUM `message_role`/`message_status`, FK tự trỏ của
`messages.parent_id`, `gen_random_uuid()`, và (từ T-1.2) `IS NOT DISTINCT FROM`
trong recursive CTE. Test chạy trên SQLite sẽ xanh trong khi production đỏ,
đúng dòng "test đang mock chính thứ cần kiểm" của HUONG-DAN-AGENT §11.

Cách nối (người dùng chốt ở T-1.1, ghi thành NQ-17):

- `docker-compose.override.yml` publish `postgres` ra **127.0.0.1:5432** (chỉ
  loopback) vì `make test` chạy pytest từ WSL host, ngoài network `internal`.
- Database **riêng** `scarlet_test` trên cùng instance, KHÔNG đụng `scarlet`
  của dev. Fixture tự tạo nếu chưa có rồi chạy `alembic upgrade head` thật —
  không `Base.metadata.create_all()`, vì như vậy sẽ kiểm một schema do ORM tự
  nghĩ ra thay vì schema mà migration sinh ra.
- Mỗi test chạy trong một transaction và bị **rollback** ở cuối, nên các test
  không thấy dữ liệu của nhau và DB không phình ra.

Biến `TEST_DATABASE_URL` đọc từ môi trường, không có thì đọc `.env` ở gốc repo
(`make test` không nạp `.env`). Thiếu hẳn thì **nổ ngay** kèm tên biến, không
`skip` — §15 cấm test skip không lý do, và một bộ test DB bị skip im lặng là
cách tự lừa mình rẻ nhất.

Phần 2 nằm ở conftest **gốc** chứ không ở `tests/db/` vì từ T-1.4 nó có người
dùng thứ hai: `tests/llm/test_context.py` dựng ngữ cảnh từ một cây message
thật, và cây đó phải là cây trong Postgres chứ không phải một danh sách chép
tay — nếu không thì C11 (đường đi lẫn nhánh) không có gì kiểm được. Fixture ở
conftest gốc là fixture lười: file test nào không xin thì không tốn gì.
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ─────────────────── Phần 1: biến môi trường tối thiểu ───────────────────

MINIMAL_ENV = {
    "DATABASE_URL": "postgresql+asyncpg://scarlet:test@postgres:5432/scarlet",
    "REDIS_URL": "redis://redis:6379/0",
    "JWT_SECRET": "j" * 32,
    "MASTER_ENCRYPTION_KEY": "m" * 32,
    "LITELLM_MASTER_KEY": "litellm-test-key",
    "LITELLM_BASE_URL": "http://litellm:4000/v1",
    "PUBLIC_BASE_URL": "https://localhost",
    "ARTIFACTS_BASE_URL": "https://artifacts.localhost",
    "MINIO_ENDPOINT": "http://minio:9000",
    "MINIO_ACCESS_KEY": "minio-test-access",
    "MINIO_SECRET_KEY": "minio-test-secret",
    "MINIO_BUCKET": "scarlet",
}

for _name, _value in MINIMAL_ENV.items():
    os.environ.setdefault(_name, _value)


# ────────────────────── Phần 2: Postgres thật (NQ-17) ─────────────────────

BACKEND_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = BACKEND_DIR.parent / ".env"
URL_VAR = "TEST_DATABASE_URL"
#: Database luôn tồn tại, dùng để chạy `CREATE DATABASE` cho database test.
MAINTENANCE_DB = "postgres"
_SAFE_DB_NAME = re.compile(r"^[A-Za-z0-9_]+$")


def _read_from_env_file(name: str) -> str | None:
    """Đọc một biến từ `.env` gốc repo.

    Cố tình thô sơ: chỉ cắt ở dấu `=` đầu tiên, KHÔNG cố hiểu chú thích cuối
    dòng. Dòng `TEST_DATABASE_URL=` trong `.env`/`.env.example` được viết với
    chú thích ở dòng RIÊNG — đúng bài học B-44, nơi một chú thích cuối dòng sau
    giá trị rỗng biến thành chính giá trị đó.
    """
    if not ENV_FILE.is_file():
        return None
    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip()
    return None


def _test_database_url() -> str:
    url = os.environ.get(URL_VAR) or _read_from_env_file(URL_VAR)
    if not url:
        raise RuntimeError(
            f"thiếu {URL_VAR}. Đặt nó trong môi trường hoặc trong {ENV_FILE} "
            f"(mẫu ở .env.example), và bảo đảm `docker compose up -d postgres` "
            f"đã publish cổng 127.0.0.1:5432"
        )
    return url


def _database_name(url: str) -> str:
    name = urlsplit(url).path.lstrip("/")
    if not _SAFE_DB_NAME.match(name):
        raise RuntimeError(f"tên database trong {URL_VAR} không hợp lệ: {name!r}")
    return name


def _with_database(url: str, name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{name}"))


async def _create_database_if_missing(url: str) -> None:
    name = _database_name(url)
    # CREATE DATABASE không chạy được trong transaction ⇒ AUTOCOMMIT.
    engine = create_async_engine(_with_database(url, MAINTENANCE_DB), isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}
            )
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        await engine.dispose()


def _alembic_upgrade_head(url: str) -> None:
    """Chạy migration THẬT vào database test.

    Qua subprocess vì `alembic/env.py` đọc `settings.DATABASE_URL` lúc import —
    cách sạch nhất để trỏ nó sang database khác là cho nó một môi trường khác.
    """
    result = subprocess.run(  # noqa: S603 - lệnh cố định, không có input từ ngoài
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic upgrade head thất bại (exit {result.returncode})\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


@pytest.fixture(scope="session")
def migrated_database_url() -> str:
    """Tạo database test (nếu chưa có) và đưa schema lên `head`. Chạy một lần.

    Fixture này **đồng bộ** có chủ ý: phần async duy nhất được gói gọn trong
    `asyncio.run()`, nên không có engine nào sống sót sang event loop của test.
    Một engine session-scope dùng lại giữa nhiều event loop là nguồn lỗi
    "attached to a different loop" kinh điển của pytest-asyncio.
    """
    url = _test_database_url()
    asyncio.run(_create_database_if_missing(url))
    _alembic_upgrade_head(url)
    return url


@pytest_asyncio.fixture
async def connection(migrated_database_url: str) -> AsyncIterator[AsyncConnection]:
    """Một kết nối, một transaction, rollback ở cuối mỗi test."""
    engine = create_async_engine(migrated_database_url)
    conn = await engine.connect()
    transaction = await conn.begin()
    try:
        yield conn
    finally:
        await transaction.rollback()
        await conn.close()
        await engine.dispose()


@pytest.fixture
def session_factory(connection: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    """Nhà máy session gắn vào ĐÚNG kết nối của test.

    `join_transaction_mode="create_savepoint"`: nếu có code nào gọi `commit()`,
    nó chỉ giải phóng savepoint chứ không commit transaction ngoài — rollback
    cuối test vẫn dọn sạch.

    Có `session_factory` (chứ không chỉ `session`) vì nhiều phép kiểm cần một
    session THỨ HAI: repository ghi bằng câu UPDATE thẳng, nên đọc lại bằng
    chính session đã ghi có thể thấy object cũ trong identity map. Session mới
    trên cùng transaction cho biết DB thực sự đang chứa gì.
    """
    return async_sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )


@pytest_asyncio.fixture
async def session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as db_session:
        yield db_session


class FakeQuotaRedis:
    """Redis giả cho `app/quota/` — sáu lệnh, cả sáu mô phỏng THẬT (T-2.11, T-2.12).

    Cùng lối `FakeIdempotencyRedis` chứ không phải `FakeRateLimitRedis`: ở đây
    không có script Lua nào, chỉ có `ZADD`/`ZREMRANGEBYSCORE`/`ZRANGEBYSCORE`,
    `EXPIRE` và cặp `get`/`set` của cache tier — sáu lệnh mà một bản mô phỏng
    bằng Python *đúng* được, nên mô phỏng đúng luôn. Nhờ vậy test kiểm được
    đúng thứ cần kiểm: phần quá hạn có bị dọn TRƯỚC khi đọc không, phần còn
    trong cửa sổ có được cộng đủ không, và (từ T-2.12) một lượt sinh vừa ghi sổ
    có rơi vào **cả hai** cửa sổ với **đúng** con số Postgres đang giữ không.

    `zadd` mô phỏng đúng ngữ nghĩa Redis ở chỗ quan trọng nhất: member trùng
    thì **ghi đè** score chứ không thêm một phần tử thứ hai. Đó là lý do
    `encode_member` phải mang `usage_id` (B-156) — bỏ nó đi thì hai lượt sinh
    cùng giá đè lên nhau và tiền của một lượt biến mất, và phép mô phỏng này là
    chỗ duy nhất trong bộ test nhìn thấy điều đó.

    Một `get_redis` cho cả `estimator` lẫn `tiers`, nên fixture dưới đây vá cả
    hai — một module thiếu là một test **treo** ở lần nối `redis:6379` chứ
    không đỏ (đúng bài học `idempotency_redis` của T-2.8 và `ratelimit_redis`
    của T-2.9).
    """

    def __init__(self) -> None:
        #: `{khoá: {member: score}}` — hai ZSET `quota:5h:*`/`quota:weekly:*`.
        self.zset: dict[str, dict[str, float]] = {}
        #: Cặp key/value của cache tier (`tier:limits:*`).
        self.store: dict[str, str] = {}
        #: Mỗi lời gọi `zremrangebyscore`, theo thứ tự — test đọc để chứng minh
        #: bước dọn chạy TRƯỚC bước đọc.
        self.da_don: list[tuple[str, object, object]] = []
        #: Mỗi lời gọi `expire`, theo thứ tự — T-2.12 đọc để chứng minh nửa (b)
        #: của B-156 (hai khoá quota có TTL) thật sự chạy ở **mỗi** lần ghi.
        self.da_dat_ttl: list[tuple[str, int]] = []
        #: Mỗi lời gọi `zadd` dưới dạng `(khoá, số member)` — T-2.13 đọc để
        #: chứng minh `rebuild_quota` gửi **theo lô** chứ không một lệnh mỗi
        #: dòng sổ. Đó là thứ đứng sau DoD dòng 3 (10k dòng dưới 2 giây), và
        #: một bản giả không đếm gì sẽ xanh y hệt với 20 000 vòng đi-về.
        self.da_ghi: list[tuple[str, int]] = []
        #: Bật lên để mô phỏng Redis chết giữa chừng.
        self.fail = False

    @staticmethod
    def _diem(bien: object) -> tuple[float, bool]:
        """Một biên của `ZRANGEBYSCORE`: `-inf`, `+inf`, `12.5`, hoặc `(12.5`."""
        raw = bien if isinstance(bien, str) else repr(bien)
        mo = raw.startswith("(")
        return float(raw[1:] if mo else raw), mo

    async def zremrangebyscore(self, name: str, min: object, max: object) -> int:
        if self.fail:
            raise ConnectionError("redis chet (gia lap)")
        self.da_don.append((name, min, max))
        can_duoi, mo_duoi = self._diem(min)
        can_tren, mo_tren = self._diem(max)
        ghe = self.zset.get(name, {})
        bo = [
            member
            for member, score in ghe.items()
            if (score > can_duoi if mo_duoi else score >= can_duoi)
            and (score < can_tren if mo_tren else score <= can_tren)
        ]
        for member in bo:
            del ghe[member]
        return len(bo)

    async def zrangebyscore(
        self, name: str, min: object, max: object, *, withscores: bool = False
    ) -> list[tuple[str, float]]:
        if self.fail:
            raise ConnectionError("redis chet (gia lap)")
        assert withscores, "`read_window` luon doc kem score — xem retry_after_s"
        can_duoi, mo_duoi = self._diem(min)
        can_tren, mo_tren = self._diem(max)
        trong = [
            (member, score)
            for member, score in self.zset.get(name, {}).items()
            if (score > can_duoi if mo_duoi else score >= can_duoi)
            and (score < can_tren if mo_tren else score <= can_tren)
        ]
        return sorted(trong, key=lambda muc: muc[1])

    async def zadd(self, name: str, mapping: dict[str, float]) -> int:
        if self.fail:
            raise ConnectionError("redis chet (gia lap)")
        self.da_ghi.append((name, len(mapping)))
        ghe = self.zset.setdefault(name, {})
        moi = sum(1 for member in mapping if member not in ghe)
        ghe.update(mapping)
        return moi

    async def expire(self, name: str, ttl: int) -> bool:
        if self.fail:
            raise ConnectionError("redis chet (gia lap)")
        self.da_dat_ttl.append((name, ttl))
        return name in self.zset or name in self.store

    # ── cache tier (T-2.10) — cùng client, nên cùng fake ──
    async def get(self, name: str) -> str | None:
        if self.fail:
            raise ConnectionError("redis chet (gia lap)")
        return self.store.get(name)

    async def set(self, name: str, value: str, *, ex: int | None = None) -> bool:
        if self.fail:
            raise ConnectionError("redis chet (gia lap)")
        self.store[name] = value
        return True


@pytest.fixture
def quota_redis_fake() -> FakeQuotaRedis:
    """Một `FakeQuotaRedis` rỗng. Vá nó vào module nào là việc của chỗ xin."""
    return FakeQuotaRedis()


# Đặt SAU khối MINIMAL_ENV (Phần 1) một cách cố ý: `app.db.repositories.users`
# kéo theo `app.config.settings`, thứ khởi tạo `Settings()` ngay lúc import
# (fail-fast, L2) — import này phải chạy SAU khi biến môi trường tối thiểu đã
# có mặt, không phải trước.
from app.db.repositories.users import UserRepository  # noqa: E402


async def _create_user(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    """Một user tối thiểu, qua ORM thật (T-2.1, B-55) — không còn SQL thô.

    Trước T-2.1, `users` chưa có model nên fixture này chèn bằng `text()`
    thô; giờ model đã ra đời, giữ nguyên đường chèn tay là có HAI cách tạo
    user trong cùng một bộ test (B-55) — repository là đường DUY NHẤT.

    `tier_name` không truyền ⇒ Postgres tự điền `server_default` 'free'
    (migration 0001 seed tier này; xem `db/models/base.py` rule 2).
    """
    async with session_factory() as session:
        user = await UserRepository(session).create_pending_user(
            # `.example` (RFC 2606), KHÔNG `.test`: `email-validator` (dùng bởi
            # `EmailStr` của T-2.1) coi TLD `test` là special-use và từ chối —
            # `_create_user` không đi qua `EmailStr` nên vẫn chạy được với
            # `.test`, nhưng cùng miền với `test_auth.py` cho khỏi hai chuẩn.
            email=f"{uuid.uuid4().hex}@scarlet.example",
            password_hash="khong-phai-hash-that",
        )
        assert user is not None
        await session.commit()
        return user.id


@pytest_asyncio.fixture
async def user_a(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    return await _create_user(session_factory)


@pytest_asyncio.fixture
async def user_b(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    """User thứ hai — dùng cho mọi phép kiểm IDOR (§20)."""
    return await _create_user(session_factory)


# ───── Phần 3: Redis giả dùng chung cho `tests/api/` và `tests/security/` ─────
#
# Hai lớp dưới đây SINH RA ở `tests/api/conftest.py` (T-2.8, T-2.9) và chuyển
# lên đây ở T-2.18, không đổi một dòng hành vi nào. Lý do là lý do đã viết cho
# `FakeQuotaRedis` ngay trên: `tests/` không phải package, nên một thư mục test
# thứ hai (`tests/security/`) không `import` được chúng từ conftest của thư mục
# đầu. Hai đường còn lại đều tệ hơn — một bản mô phỏng Redis THỨ BA để bộ test
# IDOR dùng riêng (đúng hình dạng B-102 đã cấm), hoặc bỏ ba route sinh chữ ra
# khỏi ma trận IDOR vì không dựng nổi hạ tầng cho chúng, tức bỏ đúng ba cánh
# cửa tốn tiền nhất.
#
# Cách chia y như `FakeQuotaRedis`: **lớp và fixture "cái fake" nằm ở đây,
# fixture autouse đi vá `get_redis` nằm ở conftest của từng thư mục.** Thư mục
# nào cần vá module nào là chuyện của thư mục ấy; ở đây không autouse gì cả,
# nên `tests/db/`, `tests/llm/`, `tests/core/`… không tốn gì.

from app.core import ratelimit  # noqa: E402
from app.core.idempotency import HEADER_IDEMPOTENCY  # noqa: E402


class FakeIdempotencyRedis:
    """Redis trong bộ nhớ — đúng ba lệnh mà `core/idempotency.py` dùng.

    `set(..., nx=True)` tôn trọng NX **thật sự** chứ không ghi bừa: đó chính là
    tính chất mà cả §11.4 dựa vào, nên một stub dễ tính hơn Redis thật sẽ làm
    phép kiểm mất nghĩa (bài học B-102, cùng lối `_RedisDem` của
    `tests/core/test_ratelimit.py`).

    `ttl` giữ lại giá trị `ex` đã truyền để DoD dòng 4 của T-2.8 ("`TTL
    idem:...` ≈ 86400") kiểm được mà không cần một Redis thật.
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


@pytest.fixture
def idempotency_redis_fake() -> FakeIdempotencyRedis:
    """Một `FakeIdempotencyRedis` rỗng. Vá nó vào module nào là việc của chỗ xin."""
    return FakeIdempotencyRedis()


@pytest.fixture
def ratelimit_redis_fake() -> FakeRateLimitRedis:
    """Một `FakeRateLimitRedis` rỗng. Vá nó vào module nào là việc của chỗ xin."""
    return FakeRateLimitRedis()


class FakeBlacklistRedis:
    """Blacklist §11.3 **rỗng** — đúng một lệnh mà `core/deps.py` dùng.

    Sinh ra ở T-3.1c, và lý do nó nằm ở đây chứ không trong từng file test là
    lý do đã viết cho ba lớp trên: mười file test của `tests/api/` vừa chuyển
    từ danh tính tạm của Phase 1 sang **cookie phiên thật**, mà mỗi cookie
    phiên là một lần `get_access_claims` hỏi Redis xem token đã bị thu hồi
    chưa. Mười bản sao của sáu dòng dưới đây là đúng hình dạng B-102 đã cấm —
    và bốn bản sao như thế đã tồn tại từ trước (`test_auth.py`,
    `test_admin.py`, `test_account_states.py`, `test_admin_authz.py`), mỗi bản
    vì một lý do riêng của file đó.

    "Rỗng" nghĩa là **không token nào bị coi là đã thu hồi**, nên mọi ca dừng
    lại đúng ở lớp nó muốn đo chứ không ở một `401 TOKEN_REVOKED`. File nào
    muốn đo chính §11.3 thì tự vá một Redis của riêng nó đè lên — đó là việc
    `test_auth.py` và `test_admin.py` vẫn đang làm.
    """

    async def mget(self, keys: list[str]) -> list[str | None]:
        return [None for _ in keys]


@pytest.fixture
def blacklist_redis_fake() -> FakeBlacklistRedis:
    """Một `FakeBlacklistRedis`. Vá nó vào module nào là việc của chỗ xin."""
    return FakeBlacklistRedis()


async def _attach_idempotency_key(request: httpx.Request) -> None:
    """Mỗi POST một key mới — client của test cư xử như FE của C22."""
    if request.method == "POST" and HEADER_IDEMPOTENCY not in request.headers:
        request.headers[HEADER_IDEMPOTENCY] = uuid.uuid4().hex


@pytest.fixture
def event_hooks() -> dict[str, list[Callable[[httpx.Request], Awaitable[None]]]]:
    """Truyền vào `AsyncClient(event_hooks=...)`.

    Client của test tự gắn một `Idempotency-Key` **mới cho mỗi POST**, đúng
    hành vi mà C22 đòi ở FE ("key gắn với lần soạn thảo, đổi sau khi gửi thành
    công"). Nhờ vậy 60+ lời gọi POST có sẵn không phải sửa, và quan trọng hơn:
    không lời gọi nào vô tình dùng lại key của lời gọi trước — nếu dùng lại,
    request thứ hai sẽ nhận **bản phát lại** của request thứ nhất và test sẽ đỏ
    theo một cách rất khó hiểu.

    Test nào muốn kiểm chính luật §11.4 thì đặt header tay (hook không đè lên
    header đã có) hoặc tự dựng `AsyncClient` không có hook — xem
    `tests/api/test_idempotency.py`.

    Là một **fixture** chứ không phải hằng số import được: `tests/` không phải
    package (không có `__init__.py`), nên `from tests.api.conftest import ...`
    không chạy. Fixture là đường pytest vốn dựng sẵn để chia sẻ thứ như thế —
    và từ T-2.18 nó có người dùng thứ hai ở `tests/security/`.
    """
    return {"request": [_attach_idempotency_key]}
