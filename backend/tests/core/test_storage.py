"""`app/core/storage.py` — khoá object, presigned URL, chỗ nối MinIO (T-4.1).

KH tham chiếu: §15.1, §15.2 · tasks.md T-4.1 (Cạm bẫy ②, ⑤).

Không chạm MinIO thật. `presign_get` không cần giả: có `region` thì ký là
phép tính thuần — và ca cuối khoá đúng điều đó bằng cách cấm mọi lượt mạng
của `urllib3`. Thiếu `region` thì ca ấy đỏ ngay, không treo 6 s (Cạm bẫy ⑤).
Chữ ký đúng / `403` là việc của DoD trên stack thật, không phải của test này.
"""

from __future__ import annotations

import re
import uuid
from urllib.parse import parse_qs, urlsplit

import pytest
import urllib3

from app.config.settings import settings
from app.core import storage

USER_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.mark.parametrize(
    ("mime_type", "ext"),
    [("image/png", ".png"), ("image/jpeg", ".jpg"), ("image/webp", ".webp"), (DOCX, ".docx")],
)
def test_object_key_shape(mime_type: str, ext: str) -> None:
    key = storage.object_key(USER_ID, mime_type)
    assert re.fullmatch(rf"{USER_ID}/\d{{4}}/\d{{2}}/[0-9a-f-]{{36}}{re.escape(ext)}", key), key


def test_object_key_unknown_mime_has_no_ext() -> None:
    assert storage.object_key(USER_ID, "application/x-scarlet").count(".") == 0


def test_object_key_unique() -> None:
    assert storage.object_key(USER_ID, "image/png") != storage.object_key(USER_ID, "image/png")


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_: object, **__: object) -> None:
        raise AssertionError("presign_get không được có lượt mạng (Cạm bẫy ②)")

    monkeypatch.setattr(urllib3.PoolManager, "urlopen", refuse)


@pytest.mark.usefixtures("no_network")
def test_presign_url_on_public_origin() -> None:
    url = storage.presign_get("u/2026/10/x.png")

    assert url.startswith(f"{settings.PUBLIC_BASE_URL}/{settings.MINIO_BUCKET}/u/2026/10/x.png?")
    assert "minio:9000" not in url
    assert "X-Amz-Signature=" in url


@pytest.mark.usefixtures("no_network")
def test_presign_ttl_read_at_call(monkeypatch: pytest.MonkeyPatch) -> None:
    def expires() -> list[str]:
        return parse_qs(urlsplit(storage.presign_get("k.png")).query)["X-Amz-Expires"]

    monkeypatch.setattr(settings, "PRESIGN_TTL_S", 5)
    assert expires() == ["5"]
    monkeypatch.setattr(settings, "PRESIGN_TTL_S", 77)
    assert expires() == ["77"]


class FakeMinio:
    """Thay `_client()` — chỉ ghi lại lời gọi."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, str]] = {}
        self.released = False

    def put_object(self, bucket: str, key: str, data, length: int, content_type: str) -> None:  # type: ignore[no-untyped-def]
        body = data.read()
        assert len(body) == length
        self.objects[(bucket, key)] = (body, content_type)

    def get_object(self, bucket: str, key: str) -> FakeMinio:
        self._body = self.objects[(bucket, key)][0]
        return self

    def read(self) -> bytes:
        return self._body

    def close(self) -> None:
        pass

    def release_conn(self) -> None:
        self.released = True


async def test_put_then_get_through_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeMinio()
    monkeypatch.setattr(storage, "_client", lambda: fake)

    await storage.put("a/b.png", b"\x89PNG", "image/png")

    assert fake.objects[(settings.MINIO_BUCKET, "a/b.png")] == (b"\x89PNG", "image/png")
    assert await storage.get("a/b.png") == b"\x89PNG"
    assert fake.released
