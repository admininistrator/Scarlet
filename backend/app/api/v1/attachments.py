"""Tệp đính kèm — `POST /attachments`, `GET /attachments/{id}` (§15.1, §15.2, §18.3) — T-4.2.

Biên tin cậy đầu tiên nhận **byte** của người dùng: Pillow ở `api`, worker,
provider, trình duyệt đều đọc lại đúng những byte này, nên mọi phép kiểm sống ở
đây, theo thứ tự rẻ → đắt:

1. **Kích thước** — `max_upload_mb` đọc qua `get_effective_limits` **lúc gọi**
   (B-153, Cạm bẫy ③), không bao giờ một hằng hay một `Field(le=...)`.
2. **Loại** — libmagic trên byte, không tin tên tệp, không tin `Content-Type`.
   Hai chỗ libmagic không tự trả lời đủ:
   * DOCX: libmagic trả `zip`, `octet-stream` hoặc MIME DOCX tuỳ bản (545 vs
     546) và tuỳ thứ tự mục trong zip (Cạm bẫy ①) ⇒ cửa nhận là **danh mục**
     zip có `word/document.xml`, không phải chuỗi libmagic trả về (NQ-138 ②).
   * `text/plain`: SVG có khoảng trắng / BOM ở đầu ⇒ libmagic `text/plain` ở
     cả hai bản (đo 2026-10-03). Bỏ phần ấy rồi hỏi lại; ra loại khác ⇒ `415`.
3. **Ảnh** — magic bytes chỉ đọc đầu tệp (Cạm bẫy ②), nên ảnh phải qua Pillow:
   mở đúng định dạng libmagic nói, trần điểm ảnh, `verify()`.

Lưu: object lên MinIO **trước**, hàng Postgres **sau** — hỏng giữa chừng để lại
object mồ côi (B-338), không bao giờ một hàng trỏ vào hư không.

`Idempotency-Key` tuỳ chọn (A8) — router nằm trong `_AUTHENTICATED`. Khoá theo
**tệp**, không theo lần soạn (Cạm bẫy ⑥): `core/idempotency.py` không băm thân
request, nên hai tệp cùng một khoá thì tệp thứ hai nhận lại tệp thứ nhất.
"""

from __future__ import annotations

import asyncio
import codecs
import io
import uuid
import zipfile
from typing import Annotated

import magic
from fastapi import APIRouter, Depends, UploadFile, status
from PIL import Image
from pydantic import BaseModel

from app.config.settings import settings
from app.core import storage
from app.core.deps import get_current_user_id
from app.core.errors import ApiError, ApiErrorCode, ErrorEnvelope
from app.core.ratelimit import upload_limit
from app.db.models import Attachment, AttachmentKind
from app.db.repositories import AttachmentRepository
from app.db.session import session_scope
from app.quota.tiers import get_effective_limits

router = APIRouter(prefix="/attachments", tags=["attachments"])

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
#: Ba câu trả lời libmagic có thể cho một DOCX (Cạm bẫy ①).
_ZIP_ANSWERS = frozenset({"application/zip", "application/octet-stream", DOCX_MIME})
_DOCX_PART = "word/document.xml"
_TEXT = "text/plain"
_BYTES_PER_MB = 1024 * 1024


class AttachmentOut(BaseModel):
    id: uuid.UUID
    kind: str
    #: Tên gốc — chỉ để hiển thị, FE escape khi render (§15.2).
    name: str
    bytes: int
    mime_type: str
    width: int | None
    height: int | None
    extract_status: str
    #: Presigned URL qua Nginx (T-4.1), ký mới mỗi lần. Chỉ ảnh có.
    url: str | None


def _out(row: Attachment) -> AttachmentOut:
    return AttachmentOut(
        id=row.id,
        kind=row.kind,
        name=row.original_name,
        bytes=row.size_bytes,
        mime_type=row.mime_type,
        width=row.width,
        height=row.height,
        extract_status=row.extract_status,
        url=storage.presign_get(row.storage_key) if row.kind == AttachmentKind.IMAGE else None,
    )


def _unsupported(mime: str) -> ApiError:
    return ApiError(
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        ApiErrorCode.ATTACHMENT_TYPE_UNSUPPORTED,
        "loai tep khong duoc phep",
        details={"mime_type": mime},
    )


def _is_docx(data: bytes) -> bool:
    """Chỉ đọc danh mục — giải nén là việc của T-4.6a, có trần."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return _DOCX_PART in archive.namelist()
    except Exception:  # byte của người dùng: không phải zip đọc được là "không"
        return False


def sniff_mime(data: bytes) -> str:
    """MIME từ byte, đã qua allowlist. Raise `415`."""
    mime = magic.from_buffer(data, mime=True)
    if mime in _ZIP_ANSWERS:
        if not _is_docx(data):
            raise _unsupported(mime)
        mime = DOCX_MIME
    elif mime == _TEXT:
        bare = magic.from_buffer(data.removeprefix(codecs.BOM_UTF8).lstrip(), mime=True)
        if bare != _TEXT:
            raise _unsupported(bare)
    if mime not in settings.allowed_upload_mime:
        raise _unsupported(mime)
    return mime


def image_size(data: bytes, mime: str) -> tuple[int, int]:
    """`(width, height)` của một ảnh Pillow đọc trọn được. Raise `422`.

    `except Exception` có chủ ý: `DecompressionBombError` không phải `OSError`
    (Cạm bẫy ②), `verify()` ném `SyntaxError` — byte của người dùng không được
    có đường nào thành `500`.
    """
    # `Image.MIME` rỗng tới khi plugin được nạp — thiếu dòng này thì tiến trình
    # vừa khởi động từ chối MỌI ảnh (đo trên stack). Gọi lại là không làm gì.
    Image.init()
    formats = [f for f, m in Image.MIME.items() if m == mime]
    try:
        with Image.open(io.BytesIO(data), formats=formats) as img:
            width, height = img.size
            # Giữa 1× và 2× trần Pillow chỉ cảnh báo — chặn luôn.
            if width * height > (Image.MAX_IMAGE_PIXELS or 0):
                raise Image.DecompressionBombError(f"{width}x{height}")
            img.verify()
    except Exception as exc:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ApiErrorCode.ATTACHMENT_IMAGE_INVALID,
            "anh hong hoac khong doc duoc",
        ) from exc
    return width, height


def _inspect(data: bytes) -> tuple[str, int | None, int | None]:
    mime = sniff_mime(data)
    if mime.startswith("image/"):
        return (mime, *image_size(data, mime))
    return mime, None, None


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=AttachmentOut,
    dependencies=[Depends(upload_limit())],
    responses={
        413: {"model": ErrorEnvelope, "description": "vuot max_upload_mb (ATTACHMENT_TOO_LARGE)"},
        415: {"model": ErrorEnvelope, "description": "ATTACHMENT_TYPE_UNSUPPORTED"},
        422: {"model": ErrorEnvelope, "description": "ATTACHMENT_IMAGE_INVALID"},
    },
)
async def upload_attachment(
    file: UploadFile,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
) -> AttachmentOut:
    """Một tệp mỗi lượt (multipart, trường `file`)."""
    limits = await get_effective_limits(user_id)
    max_bytes = limits.max_upload_mb * _BYTES_PER_MB
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ApiError(
            status.HTTP_413_CONTENT_TOO_LARGE,
            ApiErrorCode.ATTACHMENT_TOO_LARGE,
            "tep vuot dung luong cho phep",
            details={"max_upload_mb": limits.max_upload_mb},
        )

    # libmagic + Pillow là việc CPU trên tới vài MB — không giữ event loop.
    mime, width, height = await asyncio.to_thread(_inspect, data)
    key = storage.object_key(user_id, mime)
    await storage.put(key, data, mime)

    async with session_scope() as session:
        row = await AttachmentRepository(session).create(
            user_id=user_id,
            kind=AttachmentKind.IMAGE if width is not None else AttachmentKind.FILE,
            mime_type=mime,
            original_name=file.filename or "",
            size_bytes=len(data),
            storage_key=key,
            width=width,
            height=height,
        )
        out = _out(row)
        await session.commit()
    return out


@router.get(
    "/{attachment_id}",
    status_code=status.HTTP_200_OK,
    response_model=AttachmentOut,
    responses={404: {"model": ErrorEnvelope, "description": "ATTACHMENT_NOT_FOUND"}},
)
async def get_attachment(
    attachment_id: uuid.UUID,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
) -> AttachmentOut:
    """Cùng hình dạng với `POST`, `url` ký mới. Của người khác ⇒ `404` như không có."""
    async with session_scope() as session:
        row = await AttachmentRepository(session).get(user_id=user_id, attachment_id=attachment_id)
    if row is None:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            ApiErrorCode.ATTACHMENT_NOT_FOUND,
            "khong tim thay tep",
        )
    return _out(row)
