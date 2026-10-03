"""T-4.3 — `app/llm/vision.py`: `exif_transpose` → resize → nén → base64.

KH tham chiếu: §15.3 (khối "Ảnh"), C34. Ảnh dựng bằng Pillow ngay trong test.
"""

from __future__ import annotations

import base64
import io
import os

import pytest
from PIL import ExifTags, Image

from app.config.settings import settings
from app.llm.vision import prepare_image


def _encode(img: Image.Image, fmt: str, **params: object) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt, **params)
    return buf.getvalue()


def _noise(mode: str, size: tuple[int, int]) -> Image.Image:
    return Image.frombytes(mode, size, os.urandom(size[0] * size[1] * len(mode)))


def _run(data: bytes, mime: str) -> tuple[str, bytes, Image.Image]:
    out_mime, b64 = prepare_image(data, mime)
    body = base64.b64decode(b64)
    return out_mime, body, Image.open(io.BytesIO(body))


def test_exif_orientation_6_rotates_before_resize() -> None:
    exif = Image.Exif()
    exif[ExifTags.Base.Orientation] = 6
    data = _encode(Image.new("RGB", (40, 20), "red"), "JPEG", exif=exif)

    mime, _, img = _run(data, "image/jpeg")

    assert mime == "image/jpeg"
    assert img.size == (20, 40)


def test_phone_photo_long_edge_is_1568_ratio_kept() -> None:
    data = _encode(Image.new("RGB", (3024, 4032), "gray"), "JPEG")

    _, _, img = _run(data, "image/jpeg")

    width, height = img.size
    assert height == settings.VISION_MAX_EDGE_PX
    assert abs(width - round(3024 * height / 4032)) <= 1


@pytest.mark.parametrize(
    ("fmt", "mime"), [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")]
)
def test_under_limits_kept_byte_for_byte(fmt: str, mime: str) -> None:
    data = _encode(Image.new("RGB", (40, 30), "blue"), fmt)

    out_mime, body, img = _run(data, mime)

    assert out_mime == mime
    assert body == data  # base64 giải ngược ra đúng byte
    assert img.size == (40, 30)
    assert img.format == fmt


def test_resized_png_under_bytes_keeps_format() -> None:
    data = _encode(Image.new("RGB", (2000, 1000), "green"), "PNG")

    mime, _, img = _run(data, "image/png")

    assert mime == "image/png"
    assert img.format == "PNG"
    assert img.size == (settings.VISION_MAX_EDGE_PX, settings.VISION_MAX_EDGE_PX // 2)


def test_rgba_png_over_bytes_becomes_jpeg() -> None:
    edge = settings.VISION_MAX_EDGE_PX
    data = _encode(_noise("RGBA", (edge, edge)), "PNG")
    assert len(data) > settings.VISION_MAX_BYTES

    mime, _, img = _run(data, "image/png")

    assert mime == "image/jpeg"
    assert img.mode == "RGB"


def test_palette_gif_over_bytes_becomes_jpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    data = _encode(_noise("RGB", (600, 600)).convert("P"), "GIF")
    # GIF nhiễu cỡ 1568² vẫn dưới 3.5 MB — hạ trần, và trần phải đọc lúc gọi.
    monkeypatch.setattr(settings, "VISION_MAX_BYTES", len(data) - 1)

    mime, _, img = _run(data, "image/gif")

    assert mime == "image/jpeg"
    assert img.mode == "RGB"


def test_animated_gif_first_frame() -> None:
    frames = [Image.new("P", (20, 20), color) for color in (1, 2)]
    for frame in frames:
        frame.putpalette([0, 0, 0, 255, 0, 0, 0, 0, 255] + [0] * (256 * 3 - 9))
    data = _encode(frames[0], "GIF", save_all=True, append_images=frames[1:], duration=100)
    assert Image.open(io.BytesIO(data)).n_frames == 2

    mime, _, img = _run(data, "image/gif")

    assert mime == "image/gif"
    assert getattr(img, "n_frames", 1) == 1
    assert img.convert("RGB").getpixel((0, 0)) == (255, 0, 0)


def test_noise_png_compressed_to_jpeg_under_limit() -> None:
    edge = settings.VISION_MAX_EDGE_PX
    data = _encode(_noise("RGB", (edge, edge)), "PNG")
    print(
        f"PNG nhieu {edge}x{edge}: {len(data)} byte truoc khi nen, tran {settings.VISION_MAX_BYTES}"
    )
    assert len(data) > settings.VISION_MAX_BYTES  # ca chạm nhánh nén thật (Cạm bẫy ②)

    mime, body, img = _run(data, "image/png")

    print(f"sau khi nen: {len(body)} byte {mime}")
    assert mime == "image/jpeg"
    assert len(body) <= settings.VISION_MAX_BYTES
    assert img.size == (edge, edge)


def test_edge_read_at_call_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "VISION_MAX_EDGE_PX", 512)
    data = _encode(Image.new("RGB", (3024, 4032), "gray"), "JPEG")

    _, _, img = _run(data, "image/jpeg")

    assert max(img.size) == 512
