from fastapi import APIRouter

from app.api.v1 import admin, models

router = APIRouter(prefix="/api/v1")
router.include_router(models.router)
router.include_router(admin.router)
