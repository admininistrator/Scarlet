"""Byte XLSX / PPTX tối thiểu dựng bằng `zipfile` cho test (T-7.8b) — không thêm gói.

`tests/` nằm trên `sys.path` (conftest gốc, chế độ `prepend`) ⇒ file test ở mọi
thư mục con `from ooxml_bytes import …` được.
"""

from __future__ import annotations

import html
import io
import zipfile
from collections.abc import Sequence

X = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
OFFICE = "application/vnd.openxmlformats-officedocument"


def _content_types(main: str, kind: str) -> str:
    return (
        f'<Types xmlns="{CT}">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package'
        '.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
        f'<Override PartName="/{main}" ContentType="{OFFICE}.{kind}"/></Types>'
    )


def _rels(items: Sequence[tuple[str, str, str]]) -> str:
    body = "".join(
        f'<Relationship Id="{rid}" Type="{R}/{kind}" Target="{target}"/>'
        for rid, kind, target in items
    )
    return f'<Relationships xmlns="{PKG}">{body}</Relationships>'


def zip_parts(parts: dict[str, str]) -> bytes:
    """Mục ghi đúng thứ tự của `parts`."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in parts.items():
            archive.writestr(name, body)
    return buf.getvalue()


def xlsx_parts(
    sheets: Sequence[tuple[str, str]],
    *,
    shared: Sequence[str] = (),
    number_formats: dict[int, str] | None = None,
    xfs: Sequence[int] = (0,),
    hidden: Sequence[str] = (),
) -> dict[str, str]:
    """`sheets` = `(tên, XML các <row> của sheetData)`; `xfs` = numFmtId từng `cellXfs`."""
    tags = "".join(
        f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}"'
        + (' state="hidden"' if name in hidden else "")
        + "/>"
        for i, (name, _) in enumerate(sheets, 1)
    )
    fmts = "".join(
        f'<numFmt numFmtId="{i}" formatCode="{html.escape(code)}"/>'
        for i, code in (number_formats or {}).items()
    )
    cell_xfs = "".join(f'<xf numFmtId="{fmt}"/>' for fmt in xfs)
    book = f'<workbook xmlns="{X}" xmlns:r="{R}"><sheets>{tags}</sheets></workbook>'
    parts = {
        "[Content_Types].xml": _content_types("xl/workbook.xml", "spreadsheetml.sheet.main+xml"),
        "_rels/.rels": _rels([("rId1", "officeDocument", "xl/workbook.xml")]),
        "xl/workbook.xml": book,
        "xl/_rels/workbook.xml.rels": _rels(
            [
                (f"rId{i}", "worksheet", f"worksheets/sheet{i}.xml")
                for i in range(1, len(sheets) + 1)
            ]
            + [("rIdS", "sharedStrings", "sharedStrings.xml"), ("rIdT", "styles", "styles.xml")]
        ),
        "xl/sharedStrings.xml": f'<sst xmlns="{X}">'
        + "".join(f"<si><t>{s}</t></si>" for s in shared)
        + "</sst>",
        "xl/styles.xml": f'<styleSheet xmlns="{X}"><numFmts>{fmts}</numFmts>'
        f"<cellXfs>{cell_xfs}</cellXfs></styleSheet>",
    }
    for i, (_, rows) in enumerate(sheets, 1):
        parts[f"xl/worksheets/sheet{i}.xml"] = (
            f'<worksheet xmlns="{X}"><sheetData>{rows}</sheetData></worksheet>'
        )
    return parts


def xlsx(sheets: Sequence[tuple[str, str]], **kwargs: object) -> bytes:
    return zip_parts(xlsx_parts(sheets, **kwargs))  # type: ignore[arg-type]


def _paras(texts: Sequence[str]) -> str:
    return "".join(f"<a:p><a:r><a:t>{t}</a:t></a:r></a:p>" for t in texts)


def _sp(texts: Sequence[str], placeholder: str | None = None) -> str:
    ph = (
        f'<p:nvSpPr><p:nvPr><p:ph type="{placeholder}"/></p:nvPr></p:nvSpPr>' if placeholder else ""
    )
    return f"<p:sp>{ph}<p:txBody>{_paras(texts)}</p:txBody></p:sp>"


def pptx(
    slides: Sequence[tuple[str, Sequence[str], Sequence[str]]],
    *,
    zip_order: Sequence[str] | None = None,
) -> bytes:
    """`slides` theo thứ tự TRÌNH CHIẾU: `(tên tệp, đoạn chữ, ghi chú)`.

    `zip_order` = tên tệp slide theo thứ tự mục trong zip (mặc định như `slides`).
    Ghi chú có thêm placeholder `sldNum` (chữ "99") — không được lọt ra.
    """
    ns = f'xmlns:p="{P}" xmlns:a="{A}" xmlns:r="{R}"'
    ids = "".join(f'<p:sldId id="{256 + i}" r:id="rId{i}"/>' for i in range(1, len(slides) + 1))
    parts = {
        "[Content_Types].xml": _content_types(
            "ppt/presentation.xml", "presentationml.presentation.main+xml"
        ),
        "_rels/.rels": _rels([("rId1", "officeDocument", "ppt/presentation.xml")]),
        "ppt/presentation.xml": f"<p:presentation {ns}><p:sldIdLst>{ids}</p:sldIdLst>"
        "</p:presentation>",
        "ppt/_rels/presentation.xml.rels": _rels(
            [(f"rId{i}", "slide", f"slides/{s[0]}") for i, s in enumerate(slides, 1)]
        ),
    }
    by_name = {name: (texts, notes) for name, texts, notes in slides}
    for name in zip_order or [s[0] for s in slides]:
        texts, notes = by_name[name]
        parts[f"ppt/slides/{name}"] = (
            f"<p:sld {ns}><p:cSld><p:spTree>{_sp(texts)}</p:spTree></p:cSld></p:sld>"
        )
        if notes:
            note = f"notes-{name}"
            parts[f"ppt/slides/_rels/{name}.rels"] = _rels(
                [("rId1", "notesSlide", f"../notesSlides/{note}")]
            )
            body = _sp([], "sldImg") + _sp(notes, "body") + _sp(["99"], "sldNum")
            parts[f"ppt/notesSlides/{note}"] = (
                f"<p:notes {ns}><p:cSld><p:spTree>{body}</p:spTree></p:cSld></p:notes>"
            )
    return zip_parts(parts)
