from fastapi import APIRouter

from app.api.v1 import admin, health, models, stream
from app.config.settings import settings

router = APIRouter(prefix="/api/v1")
router.include_router(models.router)
router.include_router(admin.router)
router.include_router(health.router)
router.include_router(stream.router)

# §18.6 — `/_debug/*` CHỈ tồn tại khi DEBUG=true. Gắn router có điều kiện thay
# vì kiểm `if settings.DEBUG` trong từng handler: đường dẫn không được đăng ký
# thì FastAPI trả 404 một cách tự nhiên, và không có nhánh nào để quên khi
# thêm endpoint debug thứ hai (§18.6 còn liệt `/_debug/stream/{message_id}`).
if settings.DEBUG:
    from app.api.v1 import debug

    router.include_router(debug.router)
