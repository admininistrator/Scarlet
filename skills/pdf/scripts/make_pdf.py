"""Scarlet skill `pdf` — text/chart PDFs with matplotlib, page work with pypdf.

pypdf cannot lay out new text, and no reportlab/LibreOffice is installed, so
new pages are drawn by matplotlib (DejaVu Sans: Vietnamese works).

Usage inside `run_code` (skill="pdf"):

    from make_pdf import text_pdf, merge_pdfs
    text_pdf("report.pdf", "Title", ["First paragraph.", "Second paragraph."], figures=[fig])
"""

import textwrap

import matplotlib

matplotlib.use("Agg")
matplotlib.rcParams["pdf.fonttype"] = 42  # embed TrueType ⇒ text stays selectable/searchable

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from pypdf import PdfWriter  # noqa: E402

PAGE_IN = (8.27, 11.69)  # A4 portrait
MARGIN_IN = 0.8
FONT_PT = 11
LINE_SPACING = 1.5
#: ~characters of DejaVu Sans 11 pt across A4 minus margins.
WRAP_CHARS = 85


def _new_page():
    return plt.figure(figsize=PAGE_IN)


def text_pdf(path, title, paragraphs, figures=()):
    """Title + wrapped paragraphs (auto page breaks), then one page per figure."""
    width, height = PAGE_IN
    x = MARGIN_IN / width
    top, bottom = 1 - MARGIN_IN / height, MARGIN_IN / height
    step = FONT_PT * LINE_SPACING / 72 / height
    lines = []
    for para in paragraphs:
        lines += textwrap.wrap(para, WRAP_CHARS) or [""]
        lines.append("")
    with PdfPages(path, metadata={"Title": title}) as pdf:
        page, y = _new_page(), top
        page.text(x, y, title, fontsize=FONT_PT * 1.6, weight="bold", va="top")
        y -= step * 2.5
        for line in lines:
            if y < bottom:
                pdf.savefig(page)
                plt.close(page)
                page, y = _new_page(), top
            page.text(x, y, line, fontsize=FONT_PT, va="top")
            y -= step
        pdf.savefig(page)
        plt.close(page)
        for fig in figures:
            pdf.savefig(fig)
    return path


def merge_pdfs(path, inputs):
    """Concatenate PDFs (written earlier in the same run) into `path`."""
    writer = PdfWriter()
    for name in inputs:
        writer.append(name)
    with open(path, "wb") as out:
        writer.write(out)
    return path
