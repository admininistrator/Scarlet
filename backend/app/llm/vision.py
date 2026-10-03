"""Ảnh cho vision (§15.3, khối "Ảnh") — T-4.3.

Hàm thuần, không I/O: byte ảnh đã qua cửa T-4.2 vào, `(MIME, base64)` ra —
đúng thứ đi vào `data:<mime>;base64,…` của content block `image_url`.

Thứ tự là luật (C34): `exif_transpose` **trước**, thu nhỏ **sau** — ảnh mới mà
hàm thu nhỏ trả về không mang Orientation theo, xoay sau là xoay mù.
"""

from __future__ import annotations

import base64
import io

from PIL import ExifTags, Image, ImageOps

from app.config.settings import settings

_JPEG = "JPEG"
_JPEG_MIME = "image/jpeg"
_JPEG_QUALITY = 85  # §15.3


def _encode(img: Image.Image, fmt: str) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt, quality=_JPEG_QUALITY)
    return buf.getvalue()


def prepare_image(data: bytes, mime: str) -> tuple[str, str]:
    """`(mime, base64)` sẵn cho provider.

    * cạnh dài > `VISION_MAX_EDGE_PX` ⇒ thu theo tỉ lệ;
    * sau đó byte ≤ `VISION_MAX_BYTES` ⇒ giữ định dạng, vượt ⇒ JPEG q85 (chuyển
      `RGB` trước: `RGBA`/`P` ghi JPEG là `OSError`). So trên byte **trước**
      base64 (base64 nở ~4/3);
    * GIF động ⇒ khung đầu;
    * không gì phải đổi và dưới trần ⇒ trả nguyên byte gốc.

    Hai ngưỡng đọc **lúc gọi**. Việc CPU tới vài trăm ms trên ảnh điện thoại —
    người gọi async bọc `asyncio.to_thread` (worker ở T-4.4b).
    """
    edge = settings.VISION_MAX_EDGE_PX
    max_bytes = settings.VISION_MAX_BYTES
    # `Image.MIME` rỗng tới khi plugin được nạp (đo ở T-4.2).
    Image.init()
    fmt = next(f for f, m in Image.MIME.items() if m == mime)

    with Image.open(io.BytesIO(data), formats=[fmt]) as src:
        edited = (
            src.getexif().get(ExifTags.Base.Orientation, 1) != 1
            or getattr(src, "n_frames", 1) > 1
            or max(src.size) > edge
        )
        img: Image.Image = src
        body = data
        if edited:
            # Bản sao của khung đang mở — khung đầu với GIF động.
            img = ImageOps.exif_transpose(img)
            img.thumbnail((edge, edge), Image.Resampling.LANCZOS)
            body = _encode(img, fmt)
        if len(body) > max_bytes:
            body = _encode(img.convert("RGB"), _JPEG)
            mime = _JPEG_MIME
    return mime, base64.b64encode(body).decode("ascii")
