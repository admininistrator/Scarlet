"""Khối code trong câu trả lời → artifact — hàm thuần, không I/O (T-5.1, §14.1 hàng 2).

KH tham chiếu: §14.1, §14.2 · NQ-142 (Q-P5-1, Q-P5-7) · tasks.md T-5.1 Cạm bẫy ③ ④ ⑤.

**Backend là nguồn duy nhất quyết khối nào là artifact; FE chỉ khớp** (Q-P5-7):
T-5.3 thay khối trong bong bóng bằng thẻ khi `code.value` của mdast bằng ĐÚNG
TỪNG BYTE `artifacts.content`. Vì thế thân khối ở đây phải là `code.value`:

* chỉ khối rào **đã đóng**, rào mở ở **cột 0** (```` ``` ```` / `~~~`, ≥ 3 ký
  tự; rào đóng cùng ký tự, dài ≥ rào mở, thụt ≤ 3 dấu cách — CommonMark);
* thân = các dòng giữa hai rào, giữ nguyên dấu xuống dòng gốc giữa chúng,
  không xuống dòng đầu / cuối (mdast bỏ đúng hai cái ấy).

Rào thụt 1–3 dấu cách (vd. trong mục danh sách) vẫn được **theo dõi** để thân
của nó không bị đọc nhầm thành rào cột 0 — chỉ là không bao giờ thành artifact.

Tách dòng bằng `\\r\\n | \\r | \\n` (dấu xuống dòng của CommonMark), **không**
`str.splitlines()`: hàm ấy còn cắt ở `\\x0b`, `\\x1c`, `\\u2028`… mà mdast thì không.

ponytail: không dựng khối chứa (danh sách, trích dẫn, khối HTML) của CommonMark —
markdown lồng sai (thân khối trong danh sách tụt về cột 0, rào trong `<div>`
không dòng trống) có thể làm hai bên lệch. Nâng cấp khi đối chiếu trên câu trả
lời thật thấy lệch: chạy phép đo mdast của T-5.1 DoD dòng 2 trên `messages`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.config.settings import settings

#: Ngôn ngữ của dòng mở ⇒ `artifacts.kind` (Phụ lục A). Vắng ⇒ `code`.
KIND_BY_LANGUAGE = {
    "html": "html",
    "svg": "svg",
    "mermaid": "mermaid",
    "markdown": "markdown",
    "md": "markdown",
    "jsx": "react",
    "tsx": "react",
}
DEFAULT_KIND = "code"
#: File do `run_code` sinh (T-7.7a, §14.1 hàng 3): `content` NULL, byte ở `storage_key`.
FILE_KIND = "file"

_LINE_BREAK = re.compile(r"(\r\n|\r|\n)")
# Info của rào backtick không được chứa backtick (CommonMark) — nếu có thì dòng
# ấy là code inline, không phải rào.
_OPEN = re.compile(r"^( {0,3})(`{3,}(?!.*`)|~{3,})(.*)$")
_CLOSE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")
# Tham lam tới dấu `"` CUỐI dòng: tiêu đề chứa `"` vẫn nguyên. Quy ước dạy ở
# `system.jinja` đặt `title` cuối dòng mở.
_TITLE = re.compile(r'(?:^|\s)title="(.*)"')


@dataclass(frozen=True, slots=True)
class FencedBlock:
    """Một khối rào đã đóng, rào mở ở cột 0 — đúng một nút `code` của mdast."""

    language: str
    meta: str
    body: str
    line_count: int


@dataclass(frozen=True, slots=True)
class ArtifactBlock:
    kind: str
    language: str | None
    #: `""` = không có tiêu đề (FE hiện nhãn suy ra; T-5.2a không đưa vào dòng phiên bản).
    title: str
    #: `None` ⇔ `kind=file` — Tải lấy từ `storage_key` (B-372), không từ đây.
    content: str | None
    storage_key: str | None = None


def fenced_blocks(content: str) -> list[FencedBlock]:
    """Mọi khối rào đã đóng có rào mở ở cột 0, đúng thứ tự xuất hiện."""
    parts = _LINE_BREAK.split(content)
    lines, breaks = parts[0::2], parts[1::2]
    blocks: list[FencedBlock] = []
    open_at = -1
    fence = ""
    indent = ""
    info = ""
    for index, line in enumerate(lines):
        if open_at < 0:
            opened = _OPEN.match(line)
            if opened:
                open_at, (indent, fence, info) = index, opened.groups()
            continue
        closed = _CLOSE.match(line)
        if not closed or closed[1][0] != fence[0] or len(closed[1]) < len(fence):
            continue
        if not indent:
            body = "".join(lines[k] + breaks[k] for k in range(open_at + 1, index - 1))
            if index - 1 > open_at:
                body += lines[index - 1]
            language, _, meta = info.strip().replace("\t", " ").partition(" ")
            blocks.append(FencedBlock(language, meta.strip(), body, index - open_at - 1))
        open_at = -1
    return blocks


def _clean_title(meta: str) -> str:
    found = _TITLE.search(meta)
    return "" if found is None else clean_title(found[1])


def clean_title(raw: str) -> str:
    """Bỏ ký tự điều khiển, cắt `ARTIFACT_TITLE_MAX_CHARS` — chung cho tên file `run_code`."""
    title = "".join(ch for ch in raw if unicodedata.category(ch) != "Cc").strip()
    return title[: settings.ARTIFACT_TITLE_MAX_CHARS].strip()


def artifact_blocks(content: str) -> list[ArtifactBlock]:
    """Khối thành artifact: có tiêu đề **hoặc** thân ≥ `ARTIFACT_MIN_CODE_LINES` dòng.

    Hai trần đọc **lúc gọi** (sửa `.env` không cần sửa code). Nhánh "theo số
    dòng" phải tự đứng được — lời dặn trong system prompt không phải hợp đồng
    (Cạm bẫy ⑤). Thân chỉ toàn khoảng trắng không bao giờ là artifact.
    """
    found: list[ArtifactBlock] = []
    for block in fenced_blocks(content):
        title = _clean_title(block.meta)
        if not block.body.strip():
            continue
        if not title and block.line_count < settings.ARTIFACT_MIN_CODE_LINES:
            continue
        language = block.language.lower()
        found.append(
            ArtifactBlock(
                kind=KIND_BY_LANGUAGE.get(language, DEFAULT_KIND),
                language=block.language or None,
                title=title,
                content=block.body,
            )
        )
    return found
