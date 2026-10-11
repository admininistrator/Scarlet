"""Scarlet skill `docx` — build a .docx from a list of blocks (python-docx only).

Usage inside `run_code` (skill="docx"):

    from make_docx import build_docx
    build_docx("report.docx", [{"type": "heading", "text": "Intro", "level": 1}, ...],
               title="Quarterly report")
"""

from docx import Document
from docx.shared import Inches


def build_docx(path, blocks, title=None):
    """Write `blocks` to `path`. Unknown block type ⇒ ValueError (fix the spec, rerun)."""
    document = Document()
    if title:
        document.core_properties.title = title
        document.add_heading(title, level=0)
    for block in blocks:
        kind = block.get("type")
        if kind == "heading":
            document.add_heading(block["text"], level=block.get("level", 1))
        elif kind == "paragraph":
            document.add_paragraph(block["text"])
        elif kind in ("bullets", "numbered"):
            style = "List Bullet" if kind == "bullets" else "List Number"
            for item in block["items"]:
                document.add_paragraph(item, style=style)
        elif kind == "table":
            rows = block["rows"]
            table = document.add_table(rows=len(rows), cols=max(len(r) for r in rows))
            table.style = "Table Grid"
            for r, row in enumerate(rows):
                for c, value in enumerate(row):
                    cell = table.cell(r, c)
                    cell.text = "" if value is None else str(value)
                    if r == 0:
                        for run in cell.paragraphs[0].runs:
                            run.bold = True
        elif kind == "image":
            document.add_picture(block["path"], width=Inches(block.get("width_in", 6)))
        elif kind == "page_break":
            document.add_page_break()
        else:
            raise ValueError(f"unknown block type: {kind!r}")
    document.save(path)
    return path
