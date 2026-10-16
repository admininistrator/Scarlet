"""Ứng dụng FastAPI của service `api`.

`lifespan` làm hai việc. **Chạy vòng đo provider nền** (T-S.4, NQ-113):
`provider_health.background()` chờ lượt đo đầu tối đa một trần đo rồi để vòng
lặp chạy suốt đời tiến trình — `GET /models` chỉ đọc kết quả, không bao giờ
chờ mạng. Gọi qua tên module (`provider_health.background`) chứ không import
thẳng hàm, để `tests/conftest.py` thay được nó (Cạm bẫy ③).

Và **đóng pool khi tiến trình dừng.** T-1.7 là task
đầu tiên mà tầng HTTP giữ tài nguyên sống lâu hơn một request —
`app/core/redis.py` (một `XREAD BLOCK` cho mỗi SSE đang mở) và
`app/db/session.py` (engine dùng chung với worker); T-1.8 thêm cái thứ ba,
`app/core/queue.py` (pool arq để đẩy job `generate`). Không có chỗ đóng thì
mỗi lần `uvicorn --reload` nạp lại code là một pool bị bỏ rơi, và trong
container là một đống kết nối Postgres/Redis mà `docker compose restart api`
mới dọn.

`errors.register(app)` gắn khung lỗi `{"error":{...}}` của §18 (B-86, NQ-25).
Nó phải chạy **trên `app`**, không phải trên router: 404-không-có-route và
405 do Starlette sinh ra trước khi bất kỳ router nào được hỏi tới.

`idempotency.register(app)` gắn handler phát lại response đã lưu của §11.4
(T-2.8) — cùng lý do phải ở mức `app`.

`install_log_redaction()` (T-2.14) cài bộ che secret vào record factory của
tiến trình — C20, xem `app/core/log_redact.py`.

**Thứ tự hai middleware là chủ ý.** `add_middleware` chèn vào đầu danh sách,
nên cái gọi **sau** nằm **ngoài**: `OriginCheckMiddleware` ở ngoài cùng, và
một POST cross-site bị chặn `403` trước khi `IdempotencyMiddleware` kịp làm
bất cứ việc gì. Đảo lại thì lớp idempotency vẫn chạy đúng (nó chỉ ghi khoá khi
dependency đã đặt, mà dependency không bao giờ chạy cho một request bị chặn),
nhưng nó sẽ bọc `send` cho cả những request đã biết chắc là bị từ chối.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.artifacts_render import router as artifacts_render_router
from app.api.v1 import router as api_v1_router
from app.core import errors, idempotency, provider_health
from app.core.idempotency import IdempotencyMiddleware
from app.core.log_redact import install_log_redaction
from app.core.log_setup import setup_logging
from app.core.origin import OriginCheckMiddleware
from app.core.queue import dispose_arq_pool
from app.core.redis import dispose_redis
from app.core.request_id import RequestIdMiddleware
from app.db.session import dispose_engine, session_scope
from app.skills.loader import sync_skills

# C20 (T-2.14) — phải chạy TRƯỚC khi có dòng log đầu tiên của tiến trình, nên
# nó ở mức module chứ không trong `lifespan`: uvicorn import file này rồi mới
# gọi lifespan, và giữa hai mốc đó `app/config/settings.py` đã kịp cảnh báo về
# `TURNSTILE_SECRET`. Xem `app/core/log_redact.py`.
install_log_redaction()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # B-288 / T-9.5a: handler cho `app.*` — sau `dictConfig` của uvicorn. Xem
    # `app/core/log_setup.py` vì sao không ở mức module như dòng C20 ở trên.
    setup_logging()
    # T-7.5: so skill doc tu `skills/` moi lan khoi dong — them/sua skill = restart api.
    async with session_scope() as session:
        await sync_skills(session)
        await session.commit()
    async with provider_health.background():
        yield
    await dispose_redis()
    await dispose_arq_pool()
    await dispose_engine()


app = FastAPI(title="Scarlet", lifespan=lifespan)
errors.register(app)
idempotency.register(app)
app.add_middleware(IdempotencyMiddleware)
app.add_middleware(OriginCheckMiddleware)
# T-9.5b — ngoài cùng: cả `403` của Origin cũng có `request_id` + dòng log.
app.add_middleware(RequestIdMiddleware)
app.include_router(api_v1_router)
app.include_router(artifacts_render_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
