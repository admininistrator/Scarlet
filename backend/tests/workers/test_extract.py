"""T-4.6a — job `extract`: PDF / DOCX → `attachments.extracted_text` (§15.1, §15.3, §17.2).

PDF có chữ tiếng Việt là fixture commit vào repo (`fixtures/vietnamese.pdf`, 2
trang, font DejaVu nhúng) — Pillow không dựng được lớp chữ. Mọi byte khác dựng
tại chỗ. MinIO giả ở `storage.get` (T-4.1); Postgres là transaction của test.
"""

from __future__ import annotations

import io
import logging
import uuid
import zipfile
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.db.session as db_session
from app.config.settings import settings
from app.core import storage
from app.db.models import Attachment, AttachmentKind, ExtractStatus
from app.db.models.attachment import DOCX_MIME, DOCX_PART, PDF_MIME
from app.db.repositories import AttachmentRepository
from app.workers.extract import extract, extract_docx, extract_pdf

FIXTURE_PDF = (Path(__file__).parent / "fixtures" / "vietnamese.pdf").read_bytes()
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_MB = 1024 * 1024


@pytest.fixture(autouse=True)
def _bind_session_to_test_db(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    monkeypatch.setattr(db_session, "get_sessionmaker", lambda: session_factory)


@pytest.fixture
def bucket(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    objects: dict[str, bytes] = {}

    async def _get(key: str) -> bytes:
        return objects[key]

    monkeypatch.setattr(storage, "get", _get)
    return objects


def _image_pdf(pages: int) -> bytes:
    """PDF chỉ có ảnh — không lớp chữ (Pillow `save(…, "PDF")`)."""
    frames = [Image.new("RGB", (200, 100), (255, 255, 255)) for _ in range(pages)]
    buf = io.BytesIO()
    frames[0].save(buf, "PDF", save_all=True, append_images=frames[1:])
    return buf.getvalue()


def _docx(*paragraphs: str) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    xml = f'<w:document xmlns:w="{_W_NS}"><w:body>{body}</w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(DOCX_PART, xml)
    return buf.getvalue()


def _docx_bomb(decompressed_mb: int) -> bytes:
    """`word/document.xml` giải nén `decompressed_mb` MB — zip chỉ vài trăm KB."""
    buf = io.BytesIO()
    chunk = b" " * _MB
    with (
        zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive,
        archive.open(DOCX_PART, "w") as part,
    ):
        for _ in range(decompressed_mb):
            part.write(chunk)
    return buf.getvalue()


async def _pending_row(
    session: AsyncSession, user_id: uuid.UUID, bucket: dict[str, bytes], data: bytes, mime: str
) -> uuid.UUID:
    key = f"{user_id}/2026/10/{uuid.uuid4()}"
    bucket[key] = data
    row = await AttachmentRepository(session).create(
        user_id=user_id,
        kind=AttachmentKind.FILE,
        mime_type=mime,
        original_name="tai-lieu",
        size_bytes=len(data),
        storage_key=key,
        extract_status=ExtractStatus.PENDING,
    )
    await session.commit()
    return row.id


async def _row(session: AsyncSession, attachment_id: uuid.UUID) -> Attachment:
    session.expire_all()
    stmt = select(Attachment).where(Attachment.id == attachment_id)
    return (await session.execute(stmt)).scalar_one()


# ─────────────────────────── PDF ───────────────────────────


def test_pdf_with_vietnamese_text_is_done_intact() -> None:
    """**DoD**: PDF có chữ tiếng Việt ⇒ `done`, dấu nguyên vẹn, 0 `�`, đủ hai trang."""
    status, text = extract_pdf(FIXTURE_PDF)

    assert status is ExtractStatus.DONE
    assert text is not None and "�" not in text
    assert "Tiếng Việt có dấu — Đường phố Hà Nội, ồ ạt, nữ hoàng, chuyện ấy." in text
    assert "Trang hai: Phở bò tái chín, bánh mì, cà phê sữa đá." in text


def test_image_only_pdf_needs_vision() -> None:
    """**DoD**: PDF chỉ ảnh (Pillow) ⇒ `needs_vision` (T-4.6b), không chữ."""
    assert extract_pdf(_image_pdf(2)) == (ExtractStatus.NEEDS_VISION, None)


def test_image_only_pdf_over_vision_pages_is_too_many_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`MAX_PDF_PAGES_VISION` đọc lúc gọi."""
    monkeypatch.setattr(settings, "MAX_PDF_PAGES_VISION", 1)
    assert extract_pdf(_image_pdf(2)) == (ExtractStatus.TOO_MANY_PAGES, None)


# ─────────────────────────── DOCX ───────────────────────────


def test_docx_two_paragraphs() -> None:
    """**DoD**: DOCX hai đoạn ⇒ đúng hai đoạn."""
    status, text = extract_docx(_docx("Đoạn một có dấu.", "Đoạn hai."))

    assert status is ExtractStatus.DONE
    assert text is not None and text.split("\n") == ["Đoạn một có dấu.", "Đoạn hai."]


def test_docx_bomb_200mb_fails_reading_at_most_cap_plus_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**DoD** Cạm bẫy ⑥: 200 MB giải nén ⇒ `failed`, byte đã đọc ≤ trần + 1 (stream bọc)."""
    data = _docx_bomb(200)
    read: list[int] = []
    original_open = zipfile.ZipFile.open

    class _Counting:
        def __init__(self, inner: Any) -> None:
            self._inner = inner

        def read(self, n: int = -1) -> bytes:
            chunk: bytes = self._inner.read(n)
            read.append(len(chunk))
            return chunk

        def __enter__(self) -> _Counting:
            return self

        def __exit__(self, *_: object) -> None:
            self._inner.close()

    def _open(self: zipfile.ZipFile, name: Any, *args: Any, **kwargs: Any) -> _Counting:
        return _Counting(original_open(self, name, *args, **kwargs))

    monkeypatch.setattr(zipfile.ZipFile, "open", _open)

    assert extract_docx(data) == (ExtractStatus.FAILED, None)
    assert 0 < sum(read) <= settings.DOCX_XML_MAX_BYTES + 1
    assert settings.DOCX_XML_MAX_BYTES < 200 * _MB


# ─────────────────────────── job ───────────────────────────


async def test_job_closes_pending_pdf_as_done(
    session: AsyncSession, user_a: uuid.UUID, bucket: dict[str, bytes]
) -> None:
    """Chữ vào `extracted_text` một lần (§17.2)."""
    aid = await _pending_row(session, user_a, bucket, FIXTURE_PDF, PDF_MIME)

    await extract({}, str(aid))

    row = await _row(session, aid)
    assert row.extract_status == ExtractStatus.DONE
    assert row.extracted_text is not None and "Hà Nội" in row.extracted_text


@pytest.mark.parametrize(
    ("data", "mime"),
    [(b"%PDF-1.4\nrac rac rac\n", PDF_MIME), (b"PK\x03\x04hong", DOCX_MIME)],
    ids=["pdf-hong", "docx-hong"],
)
async def test_broken_file_is_failed_without_raising(
    session: AsyncSession, user_a: uuid.UUID, bucket: dict[str, bytes], data: bytes, mime: str
) -> None:
    """**DoD**: PDF hỏng ⇒ `failed`, không ném ra khỏi job."""
    aid = await _pending_row(session, user_a, bucket, data, mime)

    await extract({}, str(aid))

    row = await _row(session, aid)
    assert (row.extract_status, row.extracted_text) == (ExtractStatus.FAILED, None)


async def test_unknown_id_ends_with_one_log_line(caplog: pytest.LogCaptureFixture) -> None:
    """**DoD**: id không tồn tại ⇒ job kết thúc, một dòng log, không traceback."""
    caplog.set_level(logging.INFO, logger="app.workers.extract")

    await extract({}, str(uuid.uuid4()))
    await extract({}, "khong-phai-uuid")

    records = [r for r in caplog.records if r.name == "app.workers.extract"]
    assert len(records) == 2
    assert all(r.exc_info is None for r in records)


async def test_done_row_is_not_extracted_again(
    session: AsyncSession, user_a: uuid.UUID, bucket: dict[str, bytes]
) -> None:
    """Trích một lần (§17.2): job lặp (arq thử lại) không ghi đè hàng đã khép."""
    aid = await _pending_row(session, user_a, bucket, FIXTURE_PDF, PDF_MIME)
    await extract({}, str(aid))
    bucket.clear()  # lần hai mà còn đọc object là `KeyError` ⇒ `failed`

    await extract({}, str(aid))

    assert (await _row(session, aid)).extract_status == ExtractStatus.DONE
