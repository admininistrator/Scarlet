"""T-5.1 — `app/llm/artifact_blocks.py`: khối code trong câu trả lời → artifact.

KH tham chiếu: §14.1 hàng 2 · NQ-142 (Q-P5-7) · tasks.md T-5.1 DoD dòng 1.

Thân khối phải là ĐÚNG `code.value` của mdast (FE khớp theo từng byte); phép
đối chiếu hai bộ phân tích trên cùng dữ liệu nằm trong báo cáo task (DoD dòng 2).
"""

from __future__ import annotations

import pytest

from app.config.settings import settings
from app.llm.artifact_blocks import artifact_blocks, fenced_blocks


def _body(n: int) -> str:
    return "\n".join(f"dong_{i} = {i}" for i in range(n))


def _reply(body: str, opener: str = "```python", closer: str = "```") -> str:
    return f"Đây là code:\n\n{opener}\n{body}\n{closer}\n\nHết."


@pytest.fixture(autouse=True)
def _defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ca nào cũng chạy trên số mặc định, bất kể `.env` của máy."""
    monkeypatch.setattr(settings, "ARTIFACT_MIN_CODE_LINES", 20)
    monkeypatch.setattr(settings, "ARTIFACT_TITLE_MAX_CHARS", 120)


# ───────────────────────────── ngưỡng số dòng ─────────────────────────────


def test_19_lines_without_title_is_not_artifact() -> None:
    assert artifact_blocks(_reply(_body(19))) == []


def test_20_lines_without_title_is_artifact_with_exact_body() -> None:
    [block] = artifact_blocks(_reply(_body(20)))
    assert block.content == _body(20)
    assert block.title == ""
    assert (block.kind, block.language) == ("code", "python")


def test_threshold_read_at_call_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """Đổi `.env` là đổi biên — không có hằng 20 nào trong code."""
    monkeypatch.setattr(settings, "ARTIFACT_MIN_CODE_LINES", 5)
    assert len(artifact_blocks(_reply(_body(5)))) == 1
    assert artifact_blocks(_reply(_body(4))) == []


def test_3_lines_with_title_is_artifact() -> None:
    [block] = artifact_blocks(_reply(_body(3), opener='```html title="Trang chào"'))
    assert (block.kind, block.title, block.content) == ("html", "Trang chào", _body(3))


def test_whitespace_only_body_with_title_is_not_artifact() -> None:
    assert artifact_blocks(_reply("  \n\t", opener='```html title="Rỗng"')) == []


# ─────────────────────────────── rào ───────────────────────────────


@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_backtick_and_tilde_fences(fence: str) -> None:
    [block] = artifact_blocks(_reply(_body(20), opener=f"{fence}js", closer=fence))
    assert block.content == _body(20)


def test_closing_fence_longer_than_opening_closes() -> None:
    [block] = fenced_blocks(_reply("x = 1", opener="```py", closer="`````"))
    assert block.body == "x = 1"


def test_closing_fence_shorter_than_opening_does_not_close() -> None:
    """Rào 4 dấu chứa được ```` ``` ```` trong thân — đúng ca tài liệu markdown lồng code."""
    text = "````md\n# Tựa\n```py\nx = 1\n```\n````\n"
    [block] = fenced_blocks(text)
    assert block.body == "# Tựa\n```py\nx = 1\n```"


def test_closing_fence_of_other_char_does_not_close() -> None:
    assert fenced_blocks(_reply("x = 1", opener="```py", closer="~~~")) == []


def test_unclosed_block_at_end_is_not_artifact() -> None:
    """Cạm bẫy ③: `length` / huỷ để lại khối dở — không bao giờ thành artifact."""
    text = f'Mở đầu\n\n```html title="Dở"\n{_body(30)}\n'
    assert fenced_blocks(text) == []
    assert artifact_blocks(text) == []


def test_indented_block_in_list_is_not_artifact() -> None:
    """Chỉ rào cột 0 — khối trong danh sách có thân khác mdast (Cạm bẫy ④)."""
    text = f"1. Bước một:\n   ```python\n{_indent(_body(25))}\n   ```\n2. Bước hai.\n"
    assert fenced_blocks(text) == []


def test_lines_inside_indented_block_are_not_read_as_col0_fence() -> None:
    """Rào thụt vẫn được theo dõi: rào cột 0 sau nó mới là khối mở mới."""
    text = '- a\n  ```\n  b\n  ```\n```html title="Thật"\n<p>x</p>\n```\n'
    [block] = artifact_blocks(text)
    assert (block.title, block.content) == ("Thật", "<p>x</p>")


def test_backtick_info_with_backtick_is_not_a_fence() -> None:
    assert fenced_blocks("```js`x\nkhong phai code\n```\n") == []


def test_two_blocks_in_order() -> None:
    text = '```html title="Một"\n<p>1</p>\n```\nỞ giữa.\n```svg title="Hai"\n<svg/>\n```\n'
    assert [(b.title, b.kind) for b in artifact_blocks(text)] == [("Một", "html"), ("Hai", "svg")]


def test_vietnamese_and_emoji_body_byte_exact() -> None:
    body = (
        "# Chào thế giới 🌏\nprint('Tiếng Việt có dấu: ắ ặ ỡ — 👨‍👩‍👧')\n\n  thụt lề giữ nguyên  "
    )
    [block] = artifact_blocks(_reply(body, opener='```python title="Chữ"'))
    assert block.content.encode("utf-8") == body.encode("utf-8")


def test_crlf_between_body_lines_kept_like_mdast() -> None:
    """mdast giữ dấu xuống dòng gốc giữa các dòng thân, bỏ cái đầu và cái cuối."""
    text = '```py title="CRLF"\r\na = 1\r\nb = 2\r\n```\r\n'
    [block] = artifact_blocks(text)
    assert block.content == "a = 1\r\nb = 2"


# ─────────────────────────────── kind ───────────────────────────────


@pytest.mark.parametrize(
    ("language", "kind"),
    [
        ("html", "html"),
        ("svg", "svg"),
        ("mermaid", "mermaid"),
        ("markdown", "markdown"),
        ("md", "markdown"),
        ("jsx", "react"),
        ("tsx", "react"),
        ("HTML", "html"),
        ("python", "code"),
        ("", "code"),
    ],
)
def test_kind_table(language: str, kind: str) -> None:
    [block] = artifact_blocks(_reply(_body(20), opener=f"```{language}"))
    assert block.kind == kind
    assert block.language == (language or None)


# ─────────────────────────────── tiêu đề ───────────────────────────────


def test_title_with_double_quote_kept() -> None:
    [block] = artifact_blocks(_reply("x", opener='```html title="Nút "Gửi" đẹp"'))
    assert block.title == 'Nút "Gửi" đẹp'


def test_title_control_chars_removed() -> None:
    [block] = artifact_blocks(_reply("x", opener='```html title="A\x00B\x1b[31mC\x7f"'))
    assert block.title == "AB[31mC"


def test_title_cut_at_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_TITLE_MAX_CHARS", 10)
    [block] = artifact_blocks(_reply("x", opener=f'```html title="{"ắ" * 50}"'))
    assert block.title == "ắ" * 10


def test_empty_title_falls_back_to_line_threshold() -> None:
    assert artifact_blocks(_reply(_body(3), opener='```html title=""')) == []


def _indent(text: str) -> str:
    return "\n".join("   " + line for line in text.split("\n"))
