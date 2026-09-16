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
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

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
