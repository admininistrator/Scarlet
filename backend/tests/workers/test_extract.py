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
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from ooxml_bytes import pptx, xlsx, xlsx_parts, zip_parts
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.db.session as db_session
from app.config.settings import settings
from app.core import storage
from app.db.models import Attachment, AttachmentKind, ExtractStatus
from app.db.models.attachment import DOCX_MIME, DOCX_PART, PDF_MIME, PPTX_MIME, XLSX_MIME
from app.db.repositories import AttachmentRepository
from app.workers.extract import (
    TRUNCATED_ROWS,
    _is_date_format,
    extract,
    extract_docx,
    extract_pdf,
    extract_pptx,
    extract_xlsx,
    render_pdf_page,
)

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
    status, text, pages = extract_pdf(FIXTURE_PDF)

    assert status is ExtractStatus.DONE
    assert text is not None and "�" not in text
    assert "Tiếng Việt có dấu — Đường phố Hà Nội, ồ ạt, nữ hoàng, chuyện ấy." in text
    assert "Trang hai: Phở bò tái chín, bánh mì, cà phê sữa đá." in text
    assert pages == 2


def test_image_only_pdf_needs_vision() -> None:
    """**DoD**: PDF chỉ ảnh (Pillow) ⇒ `needs_vision` (T-4.6b), không chữ."""
    assert extract_pdf(_image_pdf(2)) == (ExtractStatus.NEEDS_VISION, None, 2)


def test_image_only_pdf_over_vision_pages_is_too_many_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`MAX_PDF_PAGES_VISION` đọc lúc gọi."""
    monkeypatch.setattr(settings, "MAX_PDF_PAGES_VISION", 1)
    assert extract_pdf(_image_pdf(2)) == (ExtractStatus.TOO_MANY_PAGES, None, 2)


def test_render_page_long_edge_is_vision_max(monkeypatch: pytest.MonkeyPatch) -> None:
    """T-4.6b Cạm bẫy ②: render thẳng ở cạnh dài `VISION_MAX_EDGE_PX` (đọc lúc gọi)."""
    monkeypatch.setattr(settings, "VISION_MAX_EDGE_PX", 800)
    png = render_pdf_page(_image_pdf(2), 1)

    with Image.open(io.BytesIO(png)) as page:
        assert page.format == "PNG"
        assert page.size == (800, 400)  # trang 200×100 pt, giữ tỉ lệ


# ─────────────────────────── DOCX ───────────────────────────


def test_docx_two_paragraphs() -> None:
    """**DoD**: DOCX hai đoạn ⇒ đúng hai đoạn."""
    status, text, pages = extract_docx(_docx("Đoạn một có dấu.", "Đoạn hai."))

    assert status is ExtractStatus.DONE
    assert text is not None and text.split("\n") == ["Đoạn một có dấu.", "Đoạn hai."]
    assert pages is None


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

    assert extract_docx(data) == (ExtractStatus.FAILED, None, None)
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


async def test_job_records_page_count_of_scanned_pdf(
    session: AsyncSession, user_a: uuid.UUID, bucket: dict[str, bytes]
) -> None:
    """NQ-141: số trang ghi cùng lúc khép hàng — `build()` không mở lại PDF."""
    aid = await _pending_row(session, user_a, bucket, _image_pdf(3), PDF_MIME)

    await extract({}, str(aid))

    row = await _row(session, aid)
    assert (row.extract_status, row.page_count) == (ExtractStatus.NEEDS_VISION, 3)


@pytest.mark.parametrize(
    ("data", "mime"),
    [
        (b"%PDF-1.4\nrac rac rac\n", PDF_MIME),
        (b"PK\x03\x04hong", DOCX_MIME),
        (zip_parts({"xl/workbook.xml": "<workbook><khong-dong"}), XLSX_MIME),
        (zip_parts({"[Content_Types].xml": "<Types/>"}), PPTX_MIME),
    ],
    ids=["pdf-hong", "docx-hong", "xlsx-xml-hong", "pptx-thieu-presentation"],
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


# ─────────────────────────── XLSX / PPTX (T-7.8b) ───────────────────────────

#: cellXfs: 0 General · 1 ngày dựng sẵn (14) · 2 ngày tự đặt · 3 thời lượng `[h]:mm`
#: · 4 số có chữ "dmy" trong ngoặc kép — chỉ 1 và 2 là ngày (Cạm bẫy ③).
_NUMBER_FORMATS = {164: "dd/mm/yyyy", 165: "[h]:mm", 166: '0.00" dmy"'}
_XFS = (0, 14, 164, 165, 166)


def test_xlsx_shared_number_formula_date_hidden_sheet() -> None:
    """**DoD**: shared string + số + ô công thức (giá trị ĐÃ LƯU) + ô ngày ⇒ `YYYY-MM-DD`."""
    sheet1 = (
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
        '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>12.5</v></c>'
        '<c r="C2"><f>B2*2</f><v>25</v></c><c r="D2" s="1"><v>45210</v></c>'
        '<c r="E2" s="2"><v>45211.75</v></c><c r="F2" s="3"><v>1.5</v></c>'
        '<c r="G2" s="4"><v>3</v></c><c r="I2" t="inlineStr"><is><t>cách cột</t></is></c></row>'
        '<row r="3"><c r="A3" t="b"><v>1</v></c><c r="B3"><f>SUM(B2:B2)</f></c></row>'
    )
    sheet2 = '<row r="1"><c r="B1"><v>7</v></c></row>'
    data = xlsx(
        [("Doanh thu", sheet1), ("Nháp", sheet2)],
        shared=["Tên", "Số", "Cà phê"],
        number_formats=_NUMBER_FORMATS,
        xfs=_XFS,
        hidden=["Nháp"],
    )

    status, text, pages = extract_xlsx(data)

    assert (status, pages) == (ExtractStatus.DONE, None)
    assert text is not None
    assert text.split("\n") == [
        "## Doanh thu",
        "Tên\tSố",
        "Cà phê\t12.5\t25\t2023-10-11\t2023-10-12\t1.5\t3\t\tcách cột",
        "TRUE",  # công thức không có `<v>` ⇒ ô rỗng, không phải "SUM(B2:B2)"
        "## Nháp (ẩn)",
        "\t7",
    ]
    assert "B2*2" not in text and "SUM" not in text


@pytest.mark.parametrize(
    ("code", "is_date"),
    [
        ("dd/mm/yyyy", True),
        ("mmm-yy", True),
        ("[$-409]mmmm d, yyyy", True),
        ("dd/mm/yyyy hh:mm", True),
        ("[h]:mm", False),
        ("h:mm AM/PM", False),
        ("mm:ss.0", False),
        ('0.00" dmy"', False),
        ("#,##0;[Red]-#,##0", False),
        ("General", False),
    ],
)
def test_custom_date_format_detection(code: str, is_date: bool) -> None:
    """Cạm bẫy ③: d/m/y ngoài ngoặc kép và `[…]`; phút cạnh giờ/giây không phải tháng."""
    assert _is_date_format(code) is is_date


def test_pptx_order_follows_sldidlst_not_file_names_with_notes() -> None:
    """**DoD**: thứ tự theo `sldIdLst` — `slide10.xml` đứng trước `slide2.xml` trong zip."""
    data = pptx(
        [
            ("slide2.xml", ["Mở đầu", "Mục tiêu quý"], ["Nhắc số liệu tháng 9"]),
            ("slide10.xml", ["Kết quả"], []),
            ("slide3.xml", ["Kế hoạch"], ["Hỏi ý kiến"]),
        ],
        zip_order=["slide10.xml", "slide2.xml", "slide3.xml"],
    )

    status, text, _ = extract_pptx(data)

    assert status is ExtractStatus.DONE
    assert text == (
        "## Slide 1\nMở đầu\nMục tiêu quý\nGhi chú:\nNhắc số liệu tháng 9\n"
        "## Slide 2\nKết quả\n"
        "## Slide 3\nKế hoạch\nGhi chú:\nHỏi ý kiến"
    )
    assert "99" not in text  # số trang của trang ghi chú không lọt ra


_ROWS = '<row r="1"><c r="A1"><v>1</v></c></row>' * 30


@pytest.mark.parametrize(
    ("data", "extractor"),
    [
        (xlsx([(f"S{i}", _ROWS) for i in range(6)]), extract_xlsx),
        (pptx([(f"slide{i}.xml", ["chữ " * 100], []) for i in range(6)]), extract_pptx),
    ],
    ids=["xlsx", "pptx"],
)
def test_ooxml_parts_over_total_cap_fail(
    data: bytes, extractor: Callable[[bytes], Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """**DoD**: trần `DOCX_XML_MAX_BYTES` là TỔNG các phần — từng phần vừa, cộng lại vượt."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        sizes = [info.file_size for info in archive.infolist()]
    half = sum(sizes) // 2
    assert max(sizes) < half  # không phần nào một mình vượt
    monkeypatch.setattr(settings, "DOCX_XML_MAX_BYTES", half)

    assert extractor(data) == (ExtractStatus.FAILED, None, None)

    monkeypatch.setattr(settings, "DOCX_XML_MAX_BYTES", sum(sizes))
    assert extractor(data)[0] is ExtractStatus.DONE


def test_xlsx_bomb_reads_at_most_cap_plus_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cạm bẫy ①: một sheet giải nén 50 MB ⇒ `failed`, không đọc quá trần + 1."""
    parts = xlsx_parts([("S", "")])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in parts.items():
            if name != "xl/worksheets/sheet1.xml":
                archive.writestr(name, body)
        with archive.open("xl/worksheets/sheet1.xml", "w") as part:
            for _ in range(50):
                part.write(b" " * _MB)
    monkeypatch.setattr(settings, "DOCX_XML_MAX_BYTES", 4 * _MB)

    assert extract_xlsx(buf.getvalue()) == (ExtractStatus.FAILED, None, None)


def test_long_xlsx_cut_at_row_boundary_with_notice(monkeypatch: pytest.MonkeyPatch) -> None:
    """**DoD** NQ-148 ③: vượt `ATTACHMENT_TEXT_MAX_CHARS` ⇒ phần đầu, cắt ở ranh giới hàng
    + dòng báo đếm đúng số hàng còn lại; kết quả ≤ trần."""
    monkeypatch.setattr(settings, "ATTACHMENT_TEXT_MAX_CHARS", 400)
    rows = "".join(
        f'<row r="{i}"><c r="A{i}" t="inlineStr"><is><t>hàng {i:03d}</t></is></c>'
        f'<c r="B{i}"><v>{i}</v></c></row>'
        for i in range(1, 101)
    )

    status, text, _ = extract_xlsx(xlsx([("Dài", rows)]))

    assert status is ExtractStatus.DONE and text is not None
    assert len(text) <= 400
    *kept, notice = text.split("\n")
    assert kept[0] == "## Dài"
    assert kept[1:] == [f"hàng {i:03d}\t{i}" for i in range(1, len(kept))]
    assert notice == TRUNCATED_ROWS.format(n=100 - (len(kept) - 1))


def test_short_pptx_is_not_cut(monkeypatch: pytest.MonkeyPatch) -> None:
    """Đối chứng: vừa trần ⇒ không dòng báo."""
    monkeypatch.setattr(settings, "ATTACHMENT_TEXT_MAX_CHARS", 400)
    _, text, _ = extract_pptx(pptx([("slide1.xml", ["Một"], [])]))
    assert text == "## Slide 1\nMột"


@pytest.mark.parametrize(
    ("make", "mime"),
    [
        (lambda: xlsx([("S", '<row r="1"><c r="A1"><v>5</v></c></row>')]), XLSX_MIME),
        (lambda: pptx([("slide1.xml", ["Xin chào"], [])]), PPTX_MIME),
    ],
    ids=["xlsx", "pptx"],
)
async def test_job_closes_pending_xlsx_pptx_as_done(
    session: AsyncSession,
    user_a: uuid.UUID,
    bucket: dict[str, bytes],
    make: Callable[[], bytes],
    mime: str,
) -> None:
    aid = await _pending_row(session, user_a, bucket, make(), mime)

    await extract({}, str(aid))

    row = await _row(session, aid)
    assert row.extract_status == ExtractStatus.DONE
    assert row.extracted_text in ("## S\n5", "## Slide 1\nXin chào")
