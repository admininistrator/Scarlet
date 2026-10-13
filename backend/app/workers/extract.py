"""Job `extract` — trích chữ PDF / DOCX / XLSX / PPTX một lần, cache vào `attachments`.

KH tham chiếu: §15.1, §15.3 (khối "PDF"), §17.2, ADR-02 · tasks.md T-4.6a, T-7.8b ·
NQ-138 ⑤, NQ-148.

`POST /attachments` đẩy job này cho PDF/DOCX/XLSX/PPTX (hàng ra đời `pending`); TXT giải
mã ngay ở `api`, không qua đây. Job khép hàng thành `done` | `needs_vision` |
`too_many_pages` | `failed` và **không bao giờ ném** ra khỏi job: parser chạy
trên byte người dùng trong tiến trình giữ mọi lượt sinh (Rủi ro của task).

* **PDF bằng `pypdfium2`, không `pymupdf`** (NQ-138 ⑤ — AGPL). Đếm trang trước
  mọi việc khác; đọc chữ từng trang, dừng khi đã quá `ATTACHMENT_TEXT_MAX_CHARS`
  — phần thừa vẫn lưu để `POST …/messages` trả `422` có mã, không âm thầm cắt.
  Không lớp chữ ⇒ `needs_vision`, hoặc `too_many_pages` khi quá
  `MAX_PDF_PAGES_VISION`. Số trang vào `page_count` (NQ-141).
* **PDF quét → ảnh** (T-4.6b): `render_pdf_page` — worker `generate` gọi cho
  từng tham chiếu trang, một trang một lần (Cạm bẫy ② T-4.6b).
* **DOCX bằng stdlib** `zipfile` + `xml.etree`: đọc tối đa `DOCX_XML_MAX_BYTES`
  + 1 byte giải nén **trước** khi parse (Cạm bẫy ⑥); vượt ⇒ `failed`. Thực thể
  XML lồng nhau (billion laughs) do expat ≥ 2.4 của 3.12 tự chặn.
* **XLSX / PPTX** (T-7.8b) cùng lối DOCX, trần `DOCX_XML_MAX_BYTES` cho **tổng**
  mọi phần đọc của một tệp (`_Package`). XLSX: giá trị **đã lưu** (`<v>`), không
  tính lại công thức; ô ngày ⇒ `YYYY-MM-DD`. PPTX: thứ tự theo `p:sldIdLst`, không
  theo tên tệp. Vượt `ATTACHMENT_TEXT_MAX_CHARS` ⇒ **cắt** ở ranh giới hàng/slide
  + một dòng báo (NQ-148 ③) — khác PDF/DOCX (giữ phần thừa để `422`).
* Việc CPU trong `asyncio.to_thread` — cùng lý do `_inline_images` (T-4.4b ⑤).
* Không thừa hưởng `max_tries=1` của `generate` (Cạm bẫy ⑤): job này không
  tiêu tiền.
"""

from __future__ import annotations

import asyncio
import io
import logging
import math
import posixpath
import re
import threading
import uuid
import zipfile
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any
from xml.etree import ElementTree

import pypdfium2 as pdfium
from sqlalchemy import select

from app.config.settings import settings
from app.core import storage
from app.db.models import Attachment, ExtractStatus
from app.db.models.attachment import (
    DOCX_MIME,
    DOCX_PART,
    PDF_MIME,
    PPTX_MIME,
    PPTX_PART,
    XLSX_MIME,
    XLSX_PART,
)
from app.db.repositories import AttachmentRepository
from app.db.session import session_scope

logger = logging.getLogger(__name__)

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_X = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
_R_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"

#: Dòng báo cuối chữ XLSX/PPTX đã cắt (NQ-148 ③), cùng họ `SEARCH_UNAVAILABLE`.
TRUNCATED_ROWS = (
    "[… còn {n} hàng chưa đưa vào vì tệp quá dài — nói rõ với người dùng là chỉ đọc "
    "được một phần tệp.]"
)
TRUNCATED_SLIDES = (
    "[… còn {n} slide chưa đưa vào vì tệp quá dài — nói rõ với người dùng là chỉ đọc "
    "được một phần tệp.]"
)
#: Dòng mở ghi chú người nói của một slide.
NOTES_LABEL = "Ghi chú:"
HIDDEN_SHEET = " (ẩn)"

#: numFmt dựng sẵn của Excel mang NGÀY (ECMA-376 §18.8.30): 14–17 ngày, 22 ngày
#: giờ. 18–21 là giờ thuần (`h:mm`…) — không có ngày để in, giữ số.
_BUILTIN_DATE_FMTS = frozenset({14, 15, 16, 17, 22})
#: Phần của chuỗi định dạng KHÔNG nói gì về ngày (Cạm bẫy ③): chữ trong ngoặc
#: kép, ký tự thoát `\x`, phút cạnh giờ/giây (`h:mm`, `[h]:mm` thời lượng,
#: `mm:ss`), `AM/PM`, rồi mọi `[…]` còn lại (màu, locale).
_FMT_NOISE = re.compile(
    r'"[^"]*"|\\.|\[?h+\]?:?m+|\[?m+\]?:?s+|AM/PM|A/P|\[[^\]]*\]', re.IGNORECASE
)
_FMT_DATE = re.compile(r"[dmy]", re.IGNORECASE)
#: Mốc số serial (đã gồm lỗi năm nhuận 1900 cho ngày sau 1900-03-01, Cạm bẫy ③).
_EXCEL_EPOCH = date(1899, 12, 30)
_EXCEL_EPOCH_1904 = date(1904, 1, 1)
_COLUMN = re.compile(r"[A-Z]+")

#: PDFium không an toàn đa luồng — hai job `extract` cùng lúc trong
#: `to_thread` là hai luồng gọi vào một thư viện C trong tiến trình worker.
# ponytail: khoá toàn cục, PDF trích tuần tự; tách tiến trình nếu hàng đợi dài.
_PDFIUM_LOCK = threading.Lock()

#: Định dạng của trang PDF đã render (`render_pdf_page`).
PAGE_MIME = "image/png"

#: `(trạng thái, chữ, số trang PDF)`.
Result = tuple[ExtractStatus, str | None, int | None]


def extract_pdf(data: bytes) -> Result:
    """Raise khi PDF hỏng — job đổi thành `failed`."""
    with _PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(data)
        try:
            pages = len(pdf)
            texts: list[str] = []
            size = 0
            for index in range(pages):
                page = pdf[index]
                textpage = page.get_textpage()
                text = textpage.get_text_range().replace("\r\n", "\n")
                textpage.close()
                page.close()
                texts.append(text)
                size += len(text)
                if size > settings.ATTACHMENT_TEXT_MAX_CHARS:
                    break
        finally:
            pdf.close()
    text = "\n".join(texts).strip()
    if text:
        return ExtractStatus.DONE, text, pages
    if pages > settings.MAX_PDF_PAGES_VISION:
        return ExtractStatus.TOO_MANY_PAGES, None, pages
    return ExtractStatus.NEEDS_VISION, None, pages


def render_pdf_page(data: bytes, index: int) -> bytes:
    """Trang `index` thành `PAGE_MIME`, cạnh dài đúng `VISION_MAX_EDGE_PX` (T-4.6b).

    Render thẳng ở cỡ T-4.3 sẽ giữ — không render 300 dpi rồi mới thu (Cạm bẫy
    ②: A4 300 dpi ≈ 26 MB RGB). Trần đọc lúc gọi. Việc CPU — người gọi bọc
    `asyncio.to_thread`.
    """
    with _PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(data)
        try:
            page = pdf[index]
            scale = settings.VISION_MAX_EDGE_PX / max(page.get_size())
            image = page.render(scale=scale).to_pil()
            page.close()
        finally:
            pdf.close()
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def extract_docx(data: bytes) -> Result:
    """Mỗi `w:p` một dòng. Raise khi zip/XML hỏng — job đổi thành `failed`."""
    cap = settings.DOCX_XML_MAX_BYTES
    with zipfile.ZipFile(io.BytesIO(data)) as archive, archive.open(DOCX_PART) as part:
        xml = part.read(cap + 1)
    if len(xml) > cap:
        return ExtractStatus.FAILED, None, None
    root = ElementTree.fromstring(xml)
    paragraphs = ["".join(t.text or "" for t in p.iter(f"{_W}t")) for p in root.iter(f"{_W}p")]
    return ExtractStatus.DONE, "\n".join(paragraphs).strip(), None


class _OverCap(Exception):
    """Tổng byte giải nén của các phần đã đọc vượt `DOCX_XML_MAX_BYTES`."""


class _Package:
    """Phần XML của một zip OOXML — trần `DOCX_XML_MAX_BYTES` cho TỔNG mọi phần đọc.

    Mỗi phần đọc tối đa phần trần còn lại + 1 byte rồi mới parse (Cạm bẫy ⑥ T-4.6a).
    """

    def __init__(self, archive: zipfile.ZipFile) -> None:
        self._archive = archive
        self._names = set(archive.namelist())
        self._left = settings.DOCX_XML_MAX_BYTES

    def xml(self, name: str) -> ElementTree.Element | None:
        """`None` khi zip không có phần ấy."""
        if name not in self._names:
            return None
        with self._archive.open(name) as part:
            data = part.read(self._left + 1)
        if len(data) > self._left:
            raise _OverCap
        self._left -= len(data)
        return ElementTree.fromstring(data)

    def rels(self, name: str) -> dict[str, tuple[str, str]]:
        """`Id → (Type, đường dẫn trong zip)` của `_rels/<tên>.rels` cạnh `name`."""
        folder, _, base = name.rpartition("/")
        root = self.xml(f"{folder}/_rels/{base}.rels")
        if root is None:
            return {}
        out: dict[str, tuple[str, str]] = {}
        for rel in root.iter(_PKG_REL):
            target = rel.get("Target") or ""
            if rel.get("TargetMode") == "External" or not target:
                continue
            path = target[1:] if target.startswith("/") else posixpath.join(folder, target)
            out[rel.get("Id") or ""] = (rel.get("Type") or "", posixpath.normpath(path))
        return out


def _ooxml(extract: Callable[[_Package], Result]) -> Callable[[bytes], Result]:
    """Mở zip cho `extract`; vượt trần giải nén ⇒ `failed`. Lỗi khác raise (job ⇒ `failed`)."""

    def run(data: bytes) -> Result:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            try:
                return extract(_Package(archive))
            except _OverCap:
                return ExtractStatus.FAILED, None, None

    return run


def _fit(lines: list[tuple[str, bool]], notice: str) -> str:
    """Nối `lines`; dài hơn `ATTACHMENT_TEXT_MAX_CHARS` ⇒ cắt ở ranh giới một dòng + `notice`.

    `(chữ, là đơn vị)` — đơn vị (hàng / slide) là thứ `notice` đếm; tiêu đề sheet
    thì không. Kết quả luôn ≤ trần: một bảng tính dài một mình không còn `422`.
    """
    cap = settings.ATTACHMENT_TEXT_MAX_CHARS
    full = "\n".join(text for text, _ in lines)
    if len(full) <= cap:
        return full
    reserve = len(notice.format(n=len(lines)))
    kept: list[str] = []
    size = 0
    for index, (text, _) in enumerate(lines):
        size += len(text) + 1
        if size + reserve > cap:
            rest = sum(unit for _, unit in lines[index:])
            return "\n".join([*kept, notice.format(n=rest)])
        kept.append(text)
    raise AssertionError("unreachable: full > cap")


def _paragraphs(root: ElementTree.Element) -> list[str]:
    """Chữ `a:t` theo từng `a:p` (DrawingML), bỏ đoạn rỗng."""
    texts = ("".join(t.text or "" for t in p.iter(f"{_A}t")) for p in root.iter(f"{_A}p"))
    return [text for text in texts if text.strip()]


def _is_date_format(code: str) -> bool:
    return bool(_FMT_DATE.search(_FMT_NOISE.sub("", code)))


def _date_styles(styles: ElementTree.Element | None) -> set[int]:
    """Chỉ số `cellXfs` mang định dạng ngày (dựng sẵn, hoặc tự đặt có d/m/y)."""
    if styles is None:
        return set()
    custom = {
        fmt.get("numFmtId")
        for fmt in styles.iter(f"{_X}numFmt")
        if _is_date_format(fmt.get("formatCode") or "")
    }
    xfs = styles.find(f"{_X}cellXfs")
    return {
        index
        for index, xf in enumerate(xfs if xfs is not None else ())
        if (fmt := xf.get("numFmtId") or "0") in custom
        or (fmt.isdigit() and int(fmt) in _BUILTIN_DATE_FMTS)
    }


def _string_item(node: ElementTree.Element) -> str:
    """`<si>` / `<is>`: `<t>` thẳng hoặc `<r><t>` — không `<rPh>` (phiên âm)."""
    parts = [node.findtext(f"{_X}t") or ""]
    parts += [run.findtext(f"{_X}t") or "" for run in node.iter(f"{_X}r")]
    return "".join(parts)


def _serial_date(value: str, epoch: date) -> str:
    """Số serial → `YYYY-MM-DD`; không đổi được thì giữ nguyên chữ."""
    try:
        return (epoch + timedelta(days=math.floor(float(value)))).isoformat()
    except (ValueError, OverflowError):
        return value


def _column(ref: str) -> int | None:
    """`"C7"` → 2. Không có `r` ⇒ `None` (ô đứng ngay sau ô trước)."""
    match = _COLUMN.match(ref)
    if match is None:
        return None
    index = 0
    for char in match.group():
        index = index * 26 + ord(char) - ord("A") + 1
    return index - 1


def _cell(cell: ElementTree.Element, shared: list[str], dates: set[int], epoch: date) -> str:
    kind = cell.get("t")
    if kind == "inlineStr":
        inline = cell.find(f"{_X}is")
        return _string_item(inline) if inline is not None else ""
    # Ô công thức: chỉ `<v>` (giá trị Excel đã lưu) — `<f>` không bao giờ ra chữ.
    raw = cell.findtext(f"{_X}v")
    if raw is None:
        return ""
    if kind == "s":
        return shared[int(raw)] if raw.isdigit() and int(raw) < len(shared) else ""
    if kind == "b":
        return "TRUE" if raw == "1" else "FALSE"
    style = cell.get("s") or "0"
    if kind in (None, "n") and style.isdigit() and int(style) in dates:
        return _serial_date(raw, epoch)
    return raw


def _xlsx(package: _Package) -> Result:
    """Mỗi sheet `## <tên>`, rồi mỗi hàng một dòng, ô ngăn `\\t` — giá trị ĐÃ LƯU."""
    workbook = package.xml(XLSX_PART)
    if workbook is None:
        raise ValueError("thieu workbook")
    rels = package.rels(XLSX_PART)
    by_type = {kind.rsplit("/", 1)[-1]: path for kind, path in rels.values()}
    shared_root = package.xml(by_type.get("sharedStrings", ""))
    shared = [] if shared_root is None else [_string_item(si) for si in shared_root.iter(f"{_X}si")]
    dates = _date_styles(package.xml(by_type.get("styles", "")))
    props = workbook.find(f"{_X}workbookPr")
    date1904 = props is not None and props.get("date1904") in ("1", "true")
    epoch = _EXCEL_EPOCH_1904 if date1904 else _EXCEL_EPOCH

    lines: list[tuple[str, bool]] = []
    for sheet in workbook.iter(f"{_X}sheet"):
        target = rels.get(sheet.get(_R_ID) or "")
        root = package.xml(target[1]) if target else None
        if root is None:
            continue
        hidden = HIDDEN_SHEET if sheet.get("state") in ("hidden", "veryHidden") else ""
        lines.append((f"## {sheet.get('name') or ''}{hidden}", False))
        for row in root.iter(f"{_X}row"):
            cells: list[str] = []
            for cell in row.iter(f"{_X}c"):
                column = _column(cell.get("r") or "")
                if column is not None and column > len(cells):
                    cells += [""] * (column - len(cells))
                cells.append(_cell(cell, shared, dates, epoch))
            text = "\t".join(cells).rstrip("\t")
            if text.strip():
                lines.append((text, True))
    return ExtractStatus.DONE, _fit(lines, TRUNCATED_ROWS), None


def _pptx(package: _Package) -> Result:
    """Mỗi slide `## Slide <n>` + đoạn chữ, rồi `Ghi chú:` + ghi chú người nói."""
    presentation = package.xml(PPTX_PART)
    if presentation is None:
        raise ValueError("thieu presentation")
    rels = package.rels(PPTX_PART)
    blocks: list[tuple[str, bool]] = []
    # Thứ tự trình chiếu là `p:sldIdLst` → rels — không phải tên tệp `slideN.xml`.
    for number, slide_id in enumerate(presentation.iter(f"{_P}sldId"), 1):
        target = rels.get(slide_id.get(_R_ID) or "")
        slide = package.xml(target[1]) if target else None
        if target is None or slide is None:
            continue
        lines = [f"## Slide {number}", *_paragraphs(slide)]
        slide_rels = package.rels(target[1]).values()
        notes_path = next((p for kind, p in slide_rels if kind.endswith("/notesSlide")), "")
        notes = package.xml(notes_path)
        if notes is not None:
            # Chỉ placeholder `body` — bỏ số trang (`sldNum`) và ảnh slide.
            body = [
                text
                for shape in notes.iter(f"{_P}sp")
                if (ph := shape.find(f"{_P}nvSpPr/{_P}nvPr/{_P}ph")) is not None
                and ph.get("type") == "body"
                for text in _paragraphs(shape)
            ]
            if body:
                lines += [NOTES_LABEL, *body]
        blocks.append(("\n".join(lines), True))
    return ExtractStatus.DONE, _fit(blocks, TRUNCATED_SLIDES), None


extract_xlsx = _ooxml(_xlsx)
extract_pptx = _ooxml(_pptx)


EXTRACTORS: dict[str, Callable[[bytes], Result]] = {
    PDF_MIME: extract_pdf,
    DOCX_MIME: extract_docx,
    XLSX_MIME: extract_xlsx,
    PPTX_MIME: extract_pptx,
}


async def extract(ctx: dict[str, Any], attachment_id: str) -> None:
    """Khép một hàng `pending`. Id lạ / hàng không còn `pending` ⇒ một dòng log, thoát."""
    try:
        aid = uuid.UUID(attachment_id)
    except ValueError:
        logger.warning("extract: id khong hop le %r", attachment_id)
        return
    # Không lọc `user_id`: id do chính `api` đẩy vào, không đến từ request nào.
    async with session_scope() as session:
        row = (
            await session.execute(
                select(Attachment.storage_key, Attachment.mime_type).where(
                    Attachment.id == aid, Attachment.extract_status == ExtractStatus.PENDING
                )
            )
        ).one_or_none()
    if row is None:
        logger.warning("extract: %s khong ton tai hoac khong con pending", aid)
        return

    status: ExtractStatus
    text: str | None
    pages: int | None
    try:
        data = await storage.get(row.storage_key)
        status, text, pages = await asyncio.to_thread(EXTRACTORS[row.mime_type], data)
    except Exception as exc:  # byte người dùng: mọi đường hỏng là `failed`, không traceback
        logger.warning("extract: %s that bai (%s)", aid, type(exc).__name__)
        status, text, pages = ExtractStatus.FAILED, None, None

    async with session_scope() as session:
        await AttachmentRepository(session).set_extracted(
            aid, status=status, text=text, pages=pages
        )
        await session.commit()
    logger.info("extract: %s -> %s (%d ky tu)", aid, status, len(text or ""))
