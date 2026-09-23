"""`/api/v1/_debug/*` chỉ tồn tại khi `DEBUG=true` (T-0.8 DoD, §18.6).

Bộ test chạy với `DEBUG` không đặt → `Settings.DEBUG` là `False` (conftest chỉ
đặt các biến BẮT BUỘC), nên đây là canh gác cho chiều nguy hiểm: một sửa đổi
tương lai vô tình gắn router debug vô điều kiện sẽ mở endpoint này trên production.
Chiều còn lại (`DEBUG=true` → stream chảy) chỉ chứng minh được qua Nginx thật,
nên nó nằm ở DoD dạng `curl -kN`, không ở đây.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config.settings import settings
from app.main import app

client = TestClient(app)


def test_debug_sse_is_404_when_debug_off() -> None:
    assert settings.DEBUG is False
    assert client.get("/api/v1/_debug/sse").status_code == 404
