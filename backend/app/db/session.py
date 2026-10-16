"""Engine + session dùng chung cho `api` và `worker` (B-54, §23, §19.3).

KH tham chiếu: §23, §5.2 · CLAUDE.md A4 · B-54.

T-1.1 cố ý chưa tạo file này: lúc đó chưa có ai gọi, và test tầng DB tự dựng
engine riêng trỏ vào `scarlet_test` (NQ-17). B-54 giao cho "task đầu tiên cần
một session trong code app" — đó là T-1.6, vì `generate` phải đọc cây message
và ghi kết quả.

**Engine dựng LƯỜI, không dựng lúc import.** Hai lý do, cả hai đều là lỗi
thật đã gặp ở dự án khác: (1) một engine tạo lúc import sẽ gắn vào event loop
nào đang chạy khi đó — với `arq` và `uvicorn` thì đó chưa chắc là loop sẽ dùng
nó; (2) bộ test import `app.*` ở mọi file mà `DATABASE_URL` trong test trỏ
tới `postgres:5432` (không tới được từ host), nên một engine háo hức là một
kết nối treo mỗi lần chạy pytest.

**`pool_pre_ping=True`.** Worker nằm không giữa các job, có khi hàng giờ.
Postgres restart (hoặc `docker compose restart postgres`) làm mọi kết nối
trong pool thành xác; không `pre_ping` thì job kế tiếp chết bằng
`ConnectionDoesNotExistError` — và với `max_tries=1` (T-1.5) thì nó chết hẳn,
không thử lại. Giá phải trả là một `SELECT 1` mỗi lần lấy kết nối.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config.settings import settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Engine dùng chung của tiến trình. Dựng ở lần gọi đầu tiên."""
    global _engine
    if _engine is None:
        # `hide_parameters` (T-9.5a, §20): `StatementError` in `[parameters: …]`
        # — tức nội dung message/artifact — vào traceback của mọi
        # `logger.exception` quanh một lần ghi Postgres hỏng.
        _engine = create_async_engine(
            str(settings.DATABASE_URL), pool_pre_ping=True, hide_parameters=True
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Nhà máy session dùng chung.

    `expire_on_commit=False` để object vừa ghi còn đọc được sau `commit()` —
    không có nó thì mỗi lần chạm thuộc tính sau commit là một `SELECT` mới, và
    trong worker thì "sau commit" thường là lúc session sắp đóng.
    """
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """Dependency của FastAPI (B-54) — `Depends(get_session)` ở T-1.8.

    **Không** `commit()` hộ người gọi: repository cũng không commit (§20, luật
    của `repositories/conversations.py`), nên ranh giới transaction nằm đúng ở
    tầng viết nghiệp vụ, nơi biết được "một đơn vị công việc" gồm những gì.
    §7.2 ① là ví dụ: hai `INSERT` + một `UPDATE` phải cùng một transaction.
    """
    async with get_sessionmaker()() as session:
        yield session


#: Cùng một thân hàm, dạng `async with` cho worker và script (không có FastAPI
#: để `Depends`). Viết lại bằng `asynccontextmanager` thay vì chép thân hàm:
#: hai bản chép tay là hai chỗ để quên `await session.close()`.
session_scope = asynccontextmanager(get_session)


async def dispose_engine() -> None:
    """Đóng pool. Worker gọi lúc shutdown; test gọi khi đổi engine."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
