"""Lưu trữ object trên MinIO — chỗ nối DUY NHẤT giữa app và bucket (T-4.1).

KH tham chiếu: §15.1, §15.2 (dòng "Tên file", "Phục vụ lại") · NQ-138 ①.

**Hai client, hai việc.** `_client()` nối `MINIO_ENDPOINT` (`minio:9000`, tên
trong network `internal`) cho `put`/`get`/tạo bucket. `_signer()` chỉ để KÝ:
endpoint của nó là `PUBLIC_BASE_URL`, vì SigV4 ký cả `Host` — URL trình duyệt
nhận phải mang đúng host trình duyệt gọi (`https://localhost/<bucket>/<khoá>`),
và Nginx chuyển đường path-style ấy về `minio:9000` mà giữ nguyên `Host`.

**`region` ghim tường minh trên cả hai.** Thiếu nó, `presigned_get_object` gọi
`GET /<bucket>?location=` để hỏi region trước khi ký — với `_signer()` là gọi
`localhost:443` của chính container: 6 s rồi `MaxRetryError` (Cạm bẫy ② của
T-4.1). Có `region` thì ký là phép tính thuần, nên `presign_get` là hàm đồng
bộ; `put`/`get` có lượt mạng thật nên đi qua `asyncio.to_thread` (SDK `minio`
chỉ có API đồng bộ — cùng lối `_check_minio` của T-0.11).

**`make test` không chạm MinIO.** Test thay `put`/`get` ở module này; riêng
`presign_get` không cần giả — không có lượt mạng nào để giả.
"""

from __future__ import annotations

import asyncio
import io
import mimetypes
import uuid
from datetime import UTC, datetime, timedelta
from functools import cache
from urllib.parse import quote, urlsplit

from minio import Minio

from app.config.settings import settings

#: Đuôi tệp theo MIME **đã nhận dạng** — không bao giờ theo tên gốc (§15.2).
#: Bảng mặc định của stdlib, KHÔNG đọc `/etc/mime.types`: tệp ấy có ở WSL mà
#: không có trong image slim, tức `.venv` và container sẽ ra hai đuôi khác
#: nhau. Bảng mặc định của 3.12 thiếu hai loại của `ALLOWED_UPLOAD_MIME`.
_mime_types = mimetypes.MimeTypes(filenames=())
_mime_types.add_type("image/webp", ".webp")
_mime_types.add_type(
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"
)


def _minio(base_url: str) -> Minio:
    parsed = urlsplit(base_url)
    return Minio(
        parsed.netloc,
        access_key=settings.MINIO_ACCESS_KEY.get_secret_value(),
        secret_key=settings.MINIO_SECRET_KEY.get_secret_value(),
        secure=parsed.scheme == "https",
        region=settings.MINIO_REGION,
    )


@cache
def _client() -> Minio:
    return _minio(settings.MINIO_ENDPOINT)


@cache
def _signer() -> Minio:
    return _minio(settings.PUBLIC_BASE_URL)


def object_key(user_id: uuid.UUID, mime_type: str) -> str:
    """`{user_id}/{yyyy}/{mm}/{uuid}{ext}` — §15.1. MIME lạ ⇒ không đuôi."""
    now = datetime.now(UTC)
    ext = _mime_types.guess_extension(mime_type) or ""
    return f"{user_id}/{now:%Y}/{now:%m}/{uuid.uuid4()}{ext}"


def ensure_bucket() -> bool:
    """Tạo `MINIO_BUCKET` nếu chưa có, KHÔNG gắn policy nào. True = vừa tạo."""
    client = _client()
    if client.bucket_exists(settings.MINIO_BUCKET):
        return False
    client.make_bucket(settings.MINIO_BUCKET)
    return True


async def put(key: str, data: bytes, content_type: str) -> None:
    await asyncio.to_thread(
        _client().put_object,
        settings.MINIO_BUCKET,
        key,
        io.BytesIO(data),
        len(data),
        content_type=content_type,
    )


def _read(key: str) -> bytes:
    response = _client().get_object(settings.MINIO_BUCKET, key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


async def get(key: str) -> bytes:
    """Object mất ⇒ `minio.error.S3Error` (`code == "NoSuchKey"`) bay ra."""
    return await asyncio.to_thread(_read, key)


def content_type_for(name: str) -> str:
    """MIME theo đuôi tên file — chỉ loại trong allowlist §15.2, còn lại `octet-stream`.

    File `run_code` (T-7.7a) mang tên do model đặt và được phục vụ từ origin
    chính: `.html` / `.svg` / `.js` không bao giờ lên MinIO với loại chạy được.
    """
    guessed = _mime_types.guess_type(name)[0]
    return guessed if guessed in settings.allowed_upload_mime else "application/octet-stream"


def presign_get(key: str, *, download_name: str | None = None) -> str:
    """URL GET đã ký cho origin công khai. TTL đọc LÚC GỌI, không lúc import.

    `download_name` ⇒ `Content-Disposition: attachment` (MinIO ghi đè header theo
    tham số đã ký): trình duyệt tải về, không bao giờ hiển thị tại chỗ (B-372).
    """
    headers: dict[str, str | list[str] | tuple[str]] | None = None
    if download_name is not None:
        disposition = f"attachment; filename*=UTF-8''{quote(download_name, safe='')}"
        headers = {"response-content-disposition": disposition}
    return _signer().presigned_get_object(
        settings.MINIO_BUCKET,
        key,
        expires=timedelta(seconds=settings.PRESIGN_TTL_S),
        response_headers=headers,
    )
