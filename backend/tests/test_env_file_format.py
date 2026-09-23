"""Hình dạng của `.env*` — chặn B-44/B-118 quay lại (NQ-45).

KH tham chiếu: §19.1, §19.2 L2 · CLAUDE.md A4 · tasks.md B-31, B-44, B-118.

**Điều đã đo được, không phải suy đoán** (docker compose v5.1.3, 2026-09-17):

    A_EMPTY_CMT=                 # chu thich   ->  '# chu thich'   ← BUG
    B_VALUE_CMT=gia-tri          # chu thich   ->  'gia-tri'
    F_EMPTY_NOSPACE=# chu thich                ->  '# chu thich'   ← BUG

Compose chỉ bóc chú thích khi phía trước `#` **đã có** một giá trị. Sau một
dấu `=` trống, cả dòng chú thích trở thành chính giá trị đó — và giá trị ấy là
**truthy**, dài 52 ký tự, nên mọi `if settings.X:` đều tin rằng biến đã được
cấu hình. Đó là toàn bộ nội dung B-118: `TURNSTILE_SECRET` trong container `api`
mang nguyên câu "# rỗng = bỏ qua (chỉ dev), log cảnh báo mỗi lần boot".

── Hai luật, không phải một ────────────────────────────────────────────────

**Luật 1 — áp cho CẢ `.env.example` lẫn `.env`.** Không phép gán nào được có
giá trị chỉ gồm khoảng trắng rồi `#`. Đây là hình dạng hỏng thật sự: giá trị
biến mất và bị thay bằng câu chú thích, im lặng.

**Luật 2 — chỉ áp cho `.env.example`.** Không chú thích cuối dòng, kể cả sau
một giá trị khác rỗng. Chặt hơn Luật 1 vì hai lý do:

- `.env.example` là file người ta **chép** thành `.env`. Một dòng hợp lệ hôm
  nay (`KEY=abc  # ghi chú`) thành dòng hỏng ngay khi ai đó xoá `abc` để điền
  giá trị của mình — đúng cách B-44 ra đời.
- Compose bóc đúng, nhưng người đọc thứ hai thì không: `grep '^KEY=' .env |
  cut -d= -f2-` lấy cả chú thích. B-31 mất 20 phút debug "No connected db" vì
  `LITELLM_MASTER_KEY` dài 86 thay vì 35 ký tự.

`.env` **không** chịu Luật 2 vì nó chứa giá trị thật: một mật khẩu có thể chứa
` #` một cách hoàn toàn hợp lệ, và một phép kiểm làm đỏ bộ test trên máy dev vì
mật khẩu của người ta là một phép kiểm sẽ bị tắt.

── Thông báo lỗi KHÔNG chứa giá trị ────────────────────────────────────────

Chỉ tên file, số dòng, tên biến. `.env` là file có secret thật, và một phép
kiểm in ra giá trị bị từ chối là B-18 ở một chỗ mới.

── Nửa thứ hai: lúc CHẠY, không chỉ lúc đọc file ───────────────────────────

Ba phép kiểm đầu canh hai file `.env*` **của repo này**. Phần cuối file canh
`Settings` — đường mà một `environment:` gõ tay trong compose, một `export`
trong shell, hay `.env` của một máy khác vẫn đi qua được.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.config.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = REPO_ROOT / ".env.example"
REAL_ENV = REPO_ROOT / ".env"

#: Luật 1 — giá trị chỉ gồm khoảng trắng rồi `#` (hoặc `#` ngay sau `=`).
ONLY_COMMENT = re.compile(r"^([A-Z][A-Z0-9_]*)=[ \t]*#")

#: Luật 2 — có chú thích ở cuối dòng, sau một giá trị khác rỗng.
TRAILING_COMMENT = re.compile(r"^([A-Z][A-Z0-9_]*)=[^#]*[ \t]+#")


def _violations(path: Path, pattern: re.Pattern[str]) -> list[str]:
    """Danh sách `tên file:dòng — TÊN_BIẾN`. Không bao giờ kèm giá trị."""
    violations = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        match = pattern.match(line.strip())
        if match is not None:
            violations.append(f"{path.name}:{line_no} — {match.group(1)}")
    return violations


def test_env_example_has_no_comment_only_assignment() -> None:
    """Luật 1 trên `.env.example` — hình dạng đã tạo ra B-44/B-118."""
    assert not _violations(ENV_EXAMPLE, ONLY_COMMENT), (
        "giá trị của biến sẽ là chính câu chú thích (đo được: docker compose "
        "chỉ bóc `#` khi phía trước đã có giá trị) — dời chú thích lên dòng riêng"
    )


def test_env_example_has_no_trailing_comments() -> None:
    """Luật 2 — xem docstring module cho lý do chặt hơn ở file mẫu."""
    assert not _violations(ENV_EXAMPLE, TRAILING_COMMENT), (
        "chú thích phải nằm ở dòng RIÊNG phía trên phép gán: dòng này thành "
        "dòng hỏng ngay khi ai đó xoá giá trị đi để điền giá trị của mình"
    )


def test_real_env_has_no_comment_only_assignment() -> None:
    """Luật 1 trên `.env` THẬT của máy này — file mà B-118 đã cắn.

    `.env` không được commit, nên trên một bản clone sạch nó không tồn tại và
    phép kiểm này không có gì để đo. `skip` kèm lý do (không phải `pass` im
    lặng): một phép kiểm luôn xanh vì không có dữ liệu là một phép kiểm nói dối.
    """
    if not REAL_ENV.is_file():
        pytest.skip(f"không có {REAL_ENV} trên máy này — chỉ .env.example được canh")
    assert not _violations(REAL_ENV, ONLY_COMMENT), (
        "biến này đang mang giá trị là một câu chú thích — app sẽ chạy với "
        "cấu hình rác mà không báo gì (B-118)"
    )


# ═══════════ Settings từ chối boot khi giá trị là một chú thích (A4) ═══════════

#: Hai chuỗi THẬT đã đo được trong container `api` ngày 2026-09-17, không phải
#: ví dụ bịa. Cái thứ hai dài 37 ký tự — **qua** ngưỡng `MIN_SECRET_CHARS = 32`
#: của `_long_enough`, tức nó đi lọt mọi phép kiểm đang có trước NQ-45.
TURNSTILE_COMMENT = "# rỗng = bỏ qua (chỉ dev), log cảnh báo mỗi lần boot"
MASTER_KEY_COMMENT = "# openssl rand -hex 32  — mã hoá BYOK"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("TURNSTILE_SECRET", TURNSTILE_COMMENT),
        ("MASTER_ENCRYPTION_KEY", MASTER_KEY_COMMENT),
        ("SMTP_HOST", "# mailpit khi dev"),
    ],
)
def test_comment_value_app_does_not_boot(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError) as exc:
        Settings()
    assert name in str(exc.value)


def test_message_does_not_print_rejected_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """B-18 ở một chỗ mới: `ValidationError` in kèm `input_value=`.

    Đây là lý do `_reject_comment_values` raise `RuntimeError` chứ
    không `ValueError` — pydantic chỉ bọc loại thứ hai, và bản bọc mang theo
    giá trị vào log đúng lúc app đang từ chối boot.
    """
    monkeypatch.setenv("MASTER_ENCRYPTION_KEY", MASTER_KEY_COMMENT)
    with pytest.raises(RuntimeError) as exc:
        Settings()
    assert MASTER_KEY_COMMENT not in str(exc.value)


def test_normal_value_still_boots(monkeypatch: pytest.MonkeyPatch) -> None:
    """Phép kiểm ngược của chính luật trên: không chặn nhầm giá trị hợp lệ."""
    monkeypatch.setenv("MASTER_ENCRYPTION_KEY", "m" * 32)
    monkeypatch.setenv("TURNSTILE_SECRET", "0xKHONG-PHAI-CHU-THICH")
    assert Settings().TURNSTILE_SECRET.get_secret_value() == "0xKHONG-PHAI-CHU-THICH"
