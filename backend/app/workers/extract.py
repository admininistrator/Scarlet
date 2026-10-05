"""Job `extract` — trích chữ PDF / DOCX một lần, cache vào `attachments` (§15.1, §17.2).

KH tham chiếu: §15.1, §15.3 (khối "PDF"), §17.2, ADR-02 · tasks.md T-4.6a · NQ-138 ⑤.

`POST /attachments` đẩy job này cho PDF/DOCX (hàng ra đời `pending`); TXT giải
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
* Việc CPU trong `asyncio.to_thread` — cùng lý do `_inline_images` (T-4.4b ⑤).
* Không thừa hưởng `max_tries=1` của `generate` (Cạm bẫy ⑤): job này không
  tiêu tiền.
"""

from __future__ import annotations

import asyncio
import io
import logging
import threading
import uuid
import zipfile
from collections.abc import Callable
from typing import Any
from xml.etree import ElementTree

import pypdfium2 as pdfium
from sqlalchemy import select

from app.config.settings import settings
from app.core import storage
from app.db.models import Attachment, ExtractStatus
from app.db.models.attachment import DOCX_MIME, DOCX_PART, PDF_MIME
from app.db.repositories import AttachmentRepository
from app.db.session import session_scope

logger = logging.getLogger(__name__)

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

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


EXTRACTORS: dict[str, Callable[[bytes], Result]] = {
    PDF_MIME: extract_pdf,
    DOCX_MIME: extract_docx,
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
