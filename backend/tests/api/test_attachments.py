"""`POST /attachments` + `GET /attachments/{id}` — T-4.2 (§15.1, §15.2, §18.3, §20).

MinIO giả ở **một** chỗ nối: `storage.put` (T-4.1, Cạm bẫy ⑤). `presign_get` là
phép tính thuần nên chạy thật. Byte thử dựng tại chỗ bằng Pillow / `zipfile` —
không tệp nhị phân nào trong repo.
"""

from __future__ import annotations

import codecs
import io
import struct
import subprocess
import sys
import uuid
import zipfile
import zlib
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from ooxml_bytes import pptx, xlsx
from PIL import Image
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.v1.attachments import decode_text
from app.config.settings import settings
from app.core import storage
from app.core.access_token import encode_access_token
from app.core.deps import SESSION_COOKIE_NAME
from app.core.errors import ApiError
from app.core.idempotency import HEADER_IDEMPOTENCY
from app.db.models import Attachment, User, UserRole, UserStatus
from app.db.models.attachment import DOCX_MIME, PPTX_MIME, XLSX_MIME
from app.main import app

URL = "/api/v1/attachments"
MB = 1024 * 1024


@pytest.fixture(autouse=True)
def _db_for_tests(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


@pytest.fixture(autouse=True)
def bucket(monkeypatch: pytest.MonkeyPatch) -> dict[str, tuple[bytes, str]]:
    """MinIO giả: khoá → (byte, content-type)."""
    objects: dict[str, tuple[bytes, str]] = {}

    async def _put(key: str, data: bytes, content_type: str) -> None:
        objects[key] = (data, content_type)

    monkeypatch.setattr(storage, "put", _put)
    return objects


class _FakeArq:
    """Hàng đợi giả cho job `extract` (T-4.6a): ghi `(tên, args, _job_id)`."""

    def __init__(self) -> None:
        self.pushed: list[tuple[str, tuple[Any, ...], str | None]] = []
        self.broken = False

    async def enqueue_job(self, name: str, *args: Any, _job_id: str | None = None) -> object:
        if self.broken:
            raise ConnectionError("redis:6379")
        self.pushed.append((name, args, _job_id))
        return object()


@pytest.fixture(autouse=True)
def arq(monkeypatch: pytest.MonkeyPatch) -> _FakeArq:
    fake = _FakeArq()

    async def _pool() -> _FakeArq:
        return fake

    monkeypatch.setattr("app.api.v1.attachments.get_arq_pool", _pool)
    return fake


@pytest_asyncio.fixture
async def client(event_hooks: dict[str, Any]) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://localhost", event_hooks=event_hooks
    ) as http:
        yield http


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    token = encode_access_token(
        user_id=user_id, role=UserRole.USER, tier="free", status=UserStatus.ACTIVE, ttl_minutes=15
    )
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


async def _upload(
    client: AsyncClient,
    user_id: uuid.UUID,
    data: bytes,
    name: str = "tep.bin",
    content_type: str = "application/octet-stream",
    headers: dict[str, str] | None = None,
) -> Any:
    return await client.post(
        URL,
        headers={**_auth(user_id), **(headers or {})},
        files={"file": (name, data, content_type)},
    )


# ─────────────────────────── byte thử ───────────────────────────


def _image(fmt: str, size: tuple[int, int] = (40, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buf, fmt)
    return buf.getvalue()


def _png_chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def _png_bomb() -> bytes:
    """PNG ~48 KB khai 20000×20000 — Pillow ném ngay ở `Image.open` (Cạm bẫy ②)."""
    ihdr = struct.pack(">IIBBBBB", 20000, 20000, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(b"\0" * 4_000_000, 9) + b"\0" * 44_000)
        + _png_chunk(b"IEND", b"")
    )


_PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
_DOCX_PARTS = {
    "[Content_Types].xml": "<Types/>",
    "_rels/.rels": "<Relationships/>",
    "word/document.xml": "<w:document/>",
}


def _zip(parts: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, body in parts.items():
            archive.writestr(name, body)
    return buf.getvalue()


# ─────────────────────── hợp lệ ⇒ 201 ───────────────────────


@pytest.mark.parametrize(
    ("fmt", "mime"), [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")]
)
async def test_valid_image_201(
    client: AsyncClient,
    user_a: uuid.UUID,
    bucket: dict[str, tuple[bytes, str]],
    session: AsyncSession,
    fmt: str,
    mime: str,
) -> None:
    data = _image(fmt)
    resp = await _upload(client, user_a, data, name="anh goc cua toi.bin")

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["kind"] == "image"
    assert body["mime_type"] == mime
    assert (body["width"], body["height"]) == (40, 30)
    assert body["bytes"] == len(data)
    assert body["name"] == "anh goc cua toi.bin"
    assert body["extract_status"] == "none"
    assert body["url"].startswith(settings.PUBLIC_BASE_URL)

    stmt = select(Attachment).where(Attachment.id == body["id"])
    row = (await session.execute(stmt)).scalar_one()
    assert row.user_id == user_a
    assert "anh goc" not in row.storage_key
    assert row.storage_key.startswith(f"{user_a}/")
    assert bucket[row.storage_key] == (data, mime)


async def test_pdf_201_is_file_without_url(
    client: AsyncClient, user_a: uuid.UUID, arq: _FakeArq
) -> None:
    resp = await _upload(client, user_a, _PDF, name="x.png", content_type="image/png")

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert (body["kind"], body["mime_type"], body["url"]) == ("file", "application/pdf", None)
    assert (body["width"], body["height"]) == (None, None)
    # T-4.6a: PDF chờ job `extract`, tên ghim, một tệp một `_job_id`.
    assert body["extract_status"] == "pending"
    assert arq.pushed == [("extract", (body["id"],), f"extract:{body['id']}")]


async def test_markdown_is_text_plain(client: AsyncClient, user_a: uuid.UUID) -> None:
    resp = await _upload(
        client, user_a, b"# Tieu de\n\n- mot\n- hai\n", "ghi-chu.md", "text/markdown"
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["mime_type"] == "text/plain"


@pytest.mark.parametrize("first", [True, False], ids=["content-types-dau", "content-types-cuoi"])
async def test_docx_by_zip_listing(client: AsyncClient, user_a: uuid.UUID, first: bool) -> None:
    """NQ-138 ②: cùng kết quả dù libmagic trả zip, octet-stream hay MIME DOCX."""
    parts = dict(_DOCX_PARTS)
    if not first:
        parts = {k: v for k, v in parts.items() if k != "[Content_Types].xml"}
        parts["[Content_Types].xml"] = "<Types/>"
    resp = await _upload(client, user_a, _zip(parts), "bao-cao.docx")

    assert resp.status_code == 201, resp.text
    assert resp.json()["mime_type"] == DOCX_MIME
    assert resp.json()["extract_status"] == "pending"


@pytest.mark.parametrize(
    ("data", "mime"),
    [
        (xlsx([("S", '<row r="1"><c r="A1"><v>1</v></c></row>')]), XLSX_MIME),
        (pptx([("slide1.xml", ["Một"], [])]), PPTX_MIME),
        (_zip({"xl/workbook.xml": "<workbook/>"}), XLSX_MIME),
        (_zip({"ppt/presentation.xml": "<p/>"}), PPTX_MIME),
    ],
    ids=["xlsx", "pptx", "xlsx-chi-workbook", "pptx-chi-presentation"],
)
async def test_xlsx_pptx_by_zip_listing_pending(
    client: AsyncClient, user_a: uuid.UUID, arq: _FakeArq, data: bytes, mime: str
) -> None:
    """**DoD** T-7.8b: loại OOXML quyết bằng danh mục zip (Cạm bẫy ②), không đuôi tệp."""
    resp = await _upload(client, user_a, data, "bang.docx")

    assert resp.status_code == 201, resp.text
    assert (resp.json()["mime_type"], resp.json()["extract_status"]) == (mime, "pending")
    assert len(arq.pushed) == 1


# ─────────────────────── TXT giải mã ngay ở `api` (T-4.6a) ───────────────────────

_VI = "Tiếng Việt có dấu: Đường phố Hà Nội, nữ hoàng, chuyện ấy."


@pytest.mark.parametrize(
    "data",
    [
        _VI.encode("utf-8"),
        codecs.BOM_UTF8 + _VI.encode("utf-8"),
        codecs.BOM_UTF16_LE + _VI.encode("utf-16-le"),
    ],
    ids=["utf8", "utf8-bom", "utf16le-bom"],
)
async def test_txt_is_done_at_upload_same_text(
    client: AsyncClient, user_a: uuid.UUID, session: AsyncSession, arq: _FakeArq, data: bytes
) -> None:
    """**DoD** NQ-138 ⑦: ba cách mã hoá hợp lệ ⇒ `done` ngay, cùng chuỗi, 0 `�`, không job."""
    resp = await _upload(client, user_a, data, "ghi-chu.txt", "text/plain")

    assert resp.status_code == 201, resp.text
    assert resp.json()["extract_status"] == "done"
    row = await session.execute(select(Attachment).where(Attachment.id == resp.json()["id"]))
    text = row.scalar_one().extracted_text
    assert text == _VI and "\ufffd" not in text
    assert arq.pushed == []


@pytest.mark.parametrize(
    "data",
    ["Xin chào".encode("cp1258"), _VI.encode("utf-16-le"), "abc".encode("utf-16-le")],
    ids=["cp1258", "utf16le-khong-bom", "utf16le-khong-bom-ascii"],
)
async def test_txt_bad_encoding_415(
    client: AsyncClient, user_a: uuid.UUID, session: AsyncSession, data: bytes
) -> None:
    """**DoD** NQ-138 ⑦ Cạm bẫy ④: không đoán bảng mã ⇒ `415`, không hàng nào."""
    resp = await _upload(client, user_a, data, "ghi-chu.txt", "text/plain")

    assert resp.status_code == 415, resp.text
    assert resp.json()["error"]["code"] in {
        "ATTACHMENT_TEXT_ENCODING",
        "ATTACHMENT_TYPE_UNSUPPORTED",  # libmagic không gọi nó là `text/plain`
    }
    count = select(func.count()).select_from(Attachment).where(Attachment.user_id == user_a)
    assert (await session.execute(count)).scalar_one() == 0


def test_decode_text_rejects_cp1258_by_its_own_code() -> None:
    """Ca `cp1258` phải đỏ ở CHÍNH luật giải mã, không nhờ libmagic từ chối hộ."""
    with pytest.raises(ApiError) as caught:
        decode_text("Xin chào".encode("cp1258"))
    assert caught.value.code == "ATTACHMENT_TEXT_ENCODING"


async def test_enqueue_failure_marks_failed_and_503(
    client: AsyncClient, user_a: uuid.UUID, session: AsyncSession, arq: _FakeArq
) -> None:
    """Redis chết sau `commit` ⇒ hàng `failed` (không `pending` mãi) + `503`."""
    arq.broken = True
    resp = await _upload(client, user_a, _PDF)

    assert resp.status_code == 503, resp.text
    assert resp.json()["error"]["code"] == "ENQUEUE_FAILED"
    row = await session.execute(select(Attachment).where(Attachment.user_id == user_a))
    assert row.scalar_one().extract_status == "failed"


# ─────────────────────── sai loại ⇒ 415 ───────────────────────


@pytest.mark.parametrize(
    "data",
    [
        b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg"><script>1</script></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        b'  \n<svg onload="alert(1)"></svg>',
        b'\xef\xbb\xbf<svg onload="alert(1)"></svg>',
        b"<!DOCTYPE html><html><body><script>alert(1)</script></body></html>",
        b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00" + b"\x00" * 200,
        _zip({"a.txt": "khong phai docx"}),
        _zip({"[Content_Types].xml": "<Types/>", "xl/worksheets/sheet1.xml": "<x/>"}),
        b"\x00\x01\x02\x03" * 64,
        b"",
    ],
    ids=[
        "svg-co-xml",
        "svg-khong-xml",
        "svg-khoang-trang-dau",
        "svg-bom",
        "html",
        "exe",
        "zip-khong-docx",
        "zip-khong-phan-ooxml",
        "rac",
        "rong",
    ],
)
async def test_wrong_type_415_even_named_png(
    client: AsyncClient,
    user_a: uuid.UUID,
    bucket: dict[str, tuple[bytes, str]],
    data: bytes,
) -> None:
    resp = await _upload(client, user_a, data, name="anh.png", content_type="image/png")

    assert resp.status_code == 415, resp.text
    assert resp.json()["error"]["code"] == "ATTACHMENT_TYPE_UNSUPPORTED"
    assert bucket == {}


# ─────────────────────── ảnh hỏng ⇒ 422, không 500 ───────────────────────


@pytest.mark.parametrize(
    "data",
    [_image("PNG", (200, 200))[: len(_image("PNG", (200, 200))) // 2], _png_bomb()],
    ids=["png-cat-nua", "png-bom-20000x20000"],
)
async def test_broken_image_422(
    client: AsyncClient,
    user_a: uuid.UUID,
    bucket: dict[str, tuple[bytes, str]],
    data: bytes,
) -> None:
    resp = await _upload(client, user_a, data, name="anh.png", content_type="image/png")

    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "ATTACHMENT_IMAGE_INVALID"
    assert bucket == {}


def test_bomb_fixture_is_48kb_png() -> None:
    data = _png_bomb()
    assert 40_000 < len(data) < 60_000
    assert data.startswith(b"\x89PNG")


# ─────────────────────── trần theo tier ───────────────────────


@pytest.mark.parametrize(("extra", "status"), [(0, 201), (1, 413)], ids=["dung-tran", "vuot-1"])
async def test_tier_limit_read_at_call_time(
    client: AsyncClient,
    user_a: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
    extra: int,
    status: int,
) -> None:
    """Trần là hạn mức đã gộp ghi đè (§10.4), đọc lúc gọi — không phải hằng."""
    async with session_factory() as s:
        await s.execute(
            update(User).where(User.id == user_a).values(limit_override_json={"max_upload_mb": 1})
        )
        await s.commit()

    resp = await _upload(client, user_a, b"a" * (MB + extra), "to.txt", "text/plain")

    assert resp.status_code == status, resp.text
    if status == 413:
        assert resp.json()["error"]["code"] == "ATTACHMENT_TOO_LARGE"
        assert resp.json()["error"]["details"] == {"max_upload_mb": 1}

    me = (await client.get("/api/v1/auth/me", headers=_auth(user_a))).json()
    assert me["max_upload_mb"] == 1
    assert me["max_attachments"] > 0
    assert me["allowed_upload_mime"] == list(settings.allowed_upload_mime)
    assert "text/markdown" not in me["allowed_upload_mime"]


# ─────────────────────── GET + IDOR + idempotency ───────────────────────


async def test_get_signs_fresh_url_and_hides_others(
    client: AsyncClient, user_a: uuid.UUID, user_b: uuid.UUID
) -> None:
    created = (await _upload(client, user_a, _image("PNG"))).json()

    own = await client.get(f"{URL}/{created['id']}", headers=_auth(user_a))
    assert own.status_code == 200
    assert {k: v for k, v in own.json().items() if k != "url"} == {
        k: v for k, v in created.items() if k != "url"
    }
    assert own.json()["url"].startswith(settings.PUBLIC_BASE_URL)

    of_a = await client.get(f"{URL}/{created['id']}", headers=_auth(user_b))
    made_up = await client.get(f"{URL}/{uuid.uuid4()}", headers=_auth(user_b))
    assert of_a.status_code == made_up.status_code == 404
    assert of_a.json() == made_up.json()
    assert of_a.json()["error"]["code"] == "ATTACHMENT_NOT_FOUND"


async def test_idempotency_key_replays_same_file(client: AsyncClient, user_a: uuid.UUID) -> None:
    key = {HEADER_IDEMPOTENCY: uuid.uuid4().hex}
    first = await _upload(client, user_a, _PDF, headers=key)
    again = await _upload(client, user_a, _PDF, headers=key)

    assert first.status_code == 201, first.text
    assert again.json()["id"] == first.json()["id"]


def test_image_check_in_fresh_process() -> None:
    """`Image.MIME` rỗng tới khi Pillow nạp plugin. Trong pytest, `_image()` đã
    nạp trước nên mọi ca trên xanh cả khi `api` vừa khởi động từ chối mọi ảnh
    (đo trên stack, T-4.2) — ca này chạy `image_size` ở tiến trình chưa nạp gì."""
    code = (
        "import sys; from app.api.v1.attachments import image_size; "
        "print(image_size(sys.stdin.buffer.read(), 'image/jpeg'))"
    )
    done = subprocess.run(
        [sys.executable, "-c", code], input=_image("JPEG"), capture_output=True, timeout=60
    )

    assert done.returncode == 0, done.stderr.decode()[-500:]
    assert done.stdout.strip() == b"(40, 30)"
