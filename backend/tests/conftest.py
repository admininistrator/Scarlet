"""Đặt bộ biến môi trường tối thiểu để `app.config.settings` import được.

`app/config/settings.py` khởi tạo `settings` ngay lúc import (fail-fast, §19.2
L2), nên test phải có đủ biến bắt buộc **trước** khi import module đó.
Dùng `setdefault` để không đè lên biến thật nếu người chạy test đã export sẵn.

Đây là chỗ duy nhất ngoài config layer chạm vào `os.environ`, và nó nằm ngoài
`app/` nên không phá luật §19.2.
"""

from __future__ import annotations

import os

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
