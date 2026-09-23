"""Bộ che secret trong log — cạm bẫy C20 — T-2.14.

Ba nhóm:

1. **`redact()` thuần** — ba mẫu của `app/core/log_redact.py`, và cả những
   chuỗi **không** được đụng tới (một bộ che ăn hết log là một bộ che sẽ bị
   tắt).
2. **Qua `logging` thật** — cài record factory rồi log qua một logger bất kỳ,
   đọc lại bằng `caplog`. Đây là nhóm chứng minh tính chất mà C20 đòi ("chạy
   trên **mọi** log record"): logger của test không phải `app.*`, không có
   handler riêng, và vẫn bị che.
3. **Traceback** — nửa thứ hai của C20 ("để exception của SDK nổi lên nguyên
   văn"). Chuỗi khoá nằm trong thông điệp của exception, không nằm trong
   `record.msg`.
"""

from __future__ import annotations

import logging

import pytest

from app.core.log_redact import REDACTED, install_log_redaction, redact

#: Không phải khoá của ai — đúng hình dạng mà grep của C20 bắt
#: (`sk-[a-zA-Z0-9]{20,}`).
#:
#: **Ghép lúc chạy chứ không viết liền một chuỗi**, và đó không phải trang trí:
#: `scripts/check_hardcode.sh` lệnh 4 (§19.4) quét mọi file git đang theo dõi
#: bằng đúng mẫu ấy. Một chuỗi khớp nằm trong repo sẽ làm lệnh kiểm secret của
#: cả dự án đỏ vĩnh viễn — và một lệnh kiểm kêu oan mỗi lần chạy là một lệnh
#: kiểm sẽ bị tắt. Giá trị **lúc chạy** vẫn khớp mẫu, tức phép kiểm ở dưới vẫn
#: đo đúng thứ C20 nói.
FAKE_KEY = "sk-" + "abcdefghij" * 3


@pytest.fixture(autouse=True)
def _installed() -> None:
    """Idempotent, nên gọi ở mỗi test là an toàn — và nó phải an toàn, vì thứ
    tự chạy của pytest không bảo đảm file nào cài trước."""
    install_log_redaction()


# ═══════════════════════ 1. `redact()` thuần ════════════════════════════════


def test_masks_sk_style_key() -> None:
    assert FAKE_KEY not in redact(f"loi khi goi provider voi {FAKE_KEY}")


def test_keeps_sk_prefix_so_log_still_says_what_was_masked() -> None:
    assert redact(FAKE_KEY) == f"sk-{REDACTED}"


def test_masks_bearer_even_if_key_lacks_sk_prefix() -> None:
    """Mẫu quan trọng nhất: nó bắt theo **vị trí**, nên phủ được provider có
    định dạng khoá khác."""
    out = redact("Authorization: Bearer gsk_KHONG-PHAI-DANG-SK-1234567890")
    assert "gsk_KHONG-PHAI-DANG-SK-1234567890" not in out


def test_masks_x_api_key_header() -> None:
    out = redact("{'x-api-key': 'ANY-SHAPE-OF-KEY-1234', 'content-type': 'application/json'}")
    assert "ANY-SHAPE-OF-KEY-1234" not in out
    # Chỉ mất đúng giá trị của trường ấy — phần còn lại của dict vẫn đọc được.
    assert "content-type" in out


def test_masks_api_key_in_assignment_form() -> None:
    assert "RAC-1234567890" not in redact("api_key=RAC-1234567890&model=x")


def test_leaves_harmless_strings_alone() -> None:
    """UUID, Redis Stream ID, tên model — ba thứ đầy trong log của repo này."""
    benign = "message_id=3fa85f64-5717-4562-b3fc-2c963f66afa6 cursor=1726740000000-0 model=x-1"
    assert redact(benign) == benign


# ═════════════════ 2. Qua `logging` thật (tính chất của C20) ════════════════


def test_every_logger_is_masked_even_outside_app_tree(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`logging.Filter` gắn trên logger `app` sẽ **không** bắt được dòng này —
    đó là lý do bộ che nằm ở record factory."""
    with caplog.at_level(logging.INFO):
        logging.getLogger("httpx").info("HTTP Request: GET /models key=%s", FAKE_KEY)
    assert FAKE_KEY not in caplog.text


def test_masks_args_too_not_just_msg(caplog: pytest.LogCaptureFixture) -> None:
    """Đường rò thật: `logger.info("goi %s", key)` — chuỗi khoá nằm trong
    `args`, không trong `msg`."""
    with caplog.at_level(logging.INFO):
        logging.getLogger("bat-ky").info("goi provider voi %s", FAKE_KEY)
    assert FAKE_KEY not in caplog.text
    assert REDACTED in caplog.text


def test_masks_when_msg_is_an_object(caplog: pytest.LogCaptureFixture) -> None:
    """C20 gọi tên đúng ca này: "log cả object request"."""
    with caplog.at_level(logging.INFO):
        logging.getLogger("bat-ky").info({"headers": {"authorization": f"Bearer {FAKE_KEY}"}})
    assert FAKE_KEY not in caplog.text


def test_normal_log_line_unchanged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        logging.getLogger("bat-ky").info("da xu ly %d hang trong %.2f s", 42, 1.5)
    assert "da xu ly 42 hang trong 1.50 s" in caplog.text


# ═══════════════════════════ 3. Traceback ═══════════════════════════════════


def test_masks_inside_exception_traceback(caplog: pytest.LogCaptureFixture) -> None:
    """Nửa thứ hai của C20. Chuỗi khoá chỉ có trong thông điệp exception."""
    with caplog.at_level(logging.ERROR):
        try:
            raise RuntimeError(f"upstream tu choi key {FAKE_KEY}")
        except RuntimeError:
            logging.getLogger("bat-ky").exception("goi provider that bai")
    assert FAKE_KEY not in caplog.text
    assert "goi provider that bai" in caplog.text
