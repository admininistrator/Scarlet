"""Bảng `attachments` — tệp người dùng tải lên (§15.1, Phụ lục A) — T-4.2.

Byte nằm trên MinIO dưới `storage_key` (`app/core/storage.py`); hàng này chỉ
là con trỏ. `original_name` chỉ để hiển thị, không bao giờ vào khoá (§15.2).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, ForeignKey, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class AttachmentKind(StrEnum):
    IMAGE = "image"
    FILE = "file"


#: MIME của hai loại tệp đi qua job `extract` (T-4.6a). Sống ở đây — `api` và
#: `worker` cùng import — chứ không ở `api/v1/attachments.py`.
PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
#: Mục của zip làm nên một DOCX (NQ-138 ②) — cũng là mục duy nhất job đọc.
DOCX_PART = "word/document.xml"
#: T-7.8b (NQ-148 ①) — XLSX / PPTX đi cùng đường DOCX.
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
XLSX_PART = "xl/workbook.xml"
PPTX_PART = "ppt/presentation.xml"
#: Mục danh mục zip → loại OOXML (`sniff_mime`, Cạm bẫy ② T-7.8b).
OOXML_PARTS = {DOCX_PART: DOCX_MIME, XLSX_PART: XLSX_MIME, PPTX_PART: PPTX_MIME}
#: Loại tệp ra đời `pending` và đi qua job `extract`.
EXTRACTED_MIMES = frozenset({PDF_MIME, *OOXML_PARTS.values()})


class ExtractStatus(StrEnum):
    """`attachments.extract_status` — tập cố định (T-4.6a, lối `ErrorCode` của T-1.6).

    `none` = ảnh, không có gì để trích. TXT giải mã ngay ở `api` ⇒ `done` luôn;
    PDF/DOCX/XLSX/PPTX ra đời `pending`, job `extract` khép thành một trong bốn trạng thái
    còn lại. `needs_vision` / `too_many_pages`: PDF không lớp chữ — trang render
    thành ảnh, đi luật ảnh (T-4.6b).
    """

    NONE = "none"
    PENDING = "pending"
    DONE = "done"
    NEEDS_VISION = "needs_vision"
    TOO_MANY_PAGES = "too_many_pages"
    FAILED = "failed"


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    #: `NULL` tới khi tệp được gửi kèm một message (T-4.4a).
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    #: MIME **đã nhận dạng** từ byte — không phải `Content-Type` client khai.
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    original_name: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Số trang PDF, job `extract` ghi cùng lúc khép hàng (T-4.6b, NQ-141) —
    #: `build()` phát mỗi trang PDF quét một phần ảnh mà không mở lại PDF.
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Cache của lần trích DUY NHẤT (§17.2) — không trích lại mỗi lượt.
    #: Một trong `ExtractStatus`.
    extract_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'none'"))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
