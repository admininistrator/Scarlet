"""Ứng dụng FastAPI của service `api`.

`lifespan` chỉ làm một việc: **đóng hai pool khi tiến trình dừng.** T-1.7 là
task đầu tiên mà tầng HTTP giữ tài nguyên sống lâu hơn một request —
`app/core/redis.py` (một `XREAD BLOCK` cho mỗi SSE đang mở) và
`app/db/session.py` (engine dùng chung với worker). Không có chỗ đóng thì mỗi
lần `uvicorn --reload` nạp lại code là một pool bị bỏ rơi, và trong container
là một đống kết nối Postgres/Redis mà `docker compose restart api` mới dọn.

`errors.register(app)` gắn khung lỗi `{"error":{...}}` của §18 (B-86, NQ-25).
Nó phải chạy **trên `app`**, không phải trên router: 404-không-có-route và
405 do Starlette sinh ra trước khi bất kỳ router nào được hỏi tới.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1 import router as api_v1_router
from app.core import errors
from app.core.redis import dispose_redis
from app.db.session import dispose_engine


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose_redis()
    await dispose_engine()


app = FastAPI(title="Scarlet", lifespan=lifespan)
errors.register(app)
app.include_router(api_v1_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
