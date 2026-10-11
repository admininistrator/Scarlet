"""Scarlet skill `pptx` — build a .pptx from a list of slide dicts (python-pptx only).

Usage inside `run_code` (skill="pptx"):

    from make_pptx import build_pptx
    build_pptx("deck.pptx", [{"title": "Plan", "subtitle": "Q4"},
                             {"title": "Goals", "bullets": ["Ship", ["detail", 1]]}])
"""

from PIL import Image
from pptx import Presentation
from pptx.util import Inches

#: Layout indexes of the default template.
TITLE_LAYOUT, CONTENT_LAYOUT, TITLE_ONLY_LAYOUT = 0, 1, 5
#: Picture box under the title on a 10 x 7.5 in slide.
IMAGE_BOX_IN = (0.5, 1.6, 9.0, 5.5)  # left, top, width, height


def build_pptx(path, slides):
    """`bullets` ⇒ title + bullets; `image` ⇒ title + picture; else title slide.

    A bullet is a str or [text, level] (level 0–4). `notes` adds speaker notes.
    """
    prs = Presentation()
    for spec in slides:
        if "bullets" in spec:
            slide = prs.slides.add_slide(prs.slide_layouts[CONTENT_LAYOUT])
            body = slide.placeholders[1].text_frame
            for i, item in enumerate(spec["bullets"]):
                text, level = (item, 0) if isinstance(item, str) else item
                para = body.paragraphs[0] if i == 0 else body.add_paragraph()
                para.text, para.level = text, level
        elif "image" in spec:
            slide = prs.slides.add_slide(prs.slide_layouts[TITLE_ONLY_LAYOUT])
            left, top, box_w, box_h = IMAGE_BOX_IN
            with Image.open(spec["image"]) as img:
                scale = min(box_w / img.width, box_h / img.height)
                width, height = img.width * scale, img.height * scale
            slide.shapes.add_picture(
                spec["image"],
                Inches(left + (box_w - width) / 2),
                Inches(top),
                Inches(width),
                Inches(height),
            )
        else:
            slide = prs.slides.add_slide(prs.slide_layouts[TITLE_LAYOUT])
            slide.placeholders[1].text = spec.get("subtitle", "")
        slide.shapes.title.text = spec.get("title", "")
        if spec.get("notes"):
            slide.notes_slide.notes_text_frame.text = spec["notes"]
    prs.save(path)
    return path
