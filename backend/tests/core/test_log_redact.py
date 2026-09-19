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
KHOA_GIA = "sk-" + "abcdefghij" * 3


@pytest.fixture(autouse=True)
def _da_cai_dat() -> None:
    """Idempotent, nên gọi ở mỗi test là an toàn — và nó phải an toàn, vì thứ
    tự chạy của pytest không bảo đảm file nào cài trước."""
    install_log_redaction()


# ═══════════════════════ 1. `redact()` thuần ════════════════════════════════


def test_che_khoa_dang_sk() -> None:
    assert KHOA_GIA not in redact(f"loi khi goi provider voi {KHOA_GIA}")


def test_giu_lai_tien_to_sk_de_dong_log_con_noi_duoc_gi_da_bi_che() -> None:
    assert redact(KHOA_GIA) == f"sk-{REDACTED}"


def test_che_bearer_du_khoa_khong_bat_dau_bang_sk() -> None:
    """Mẫu quan trọng nhất: nó bắt theo **vị trí**, nên phủ được provider có
    định dạng khoá khác."""
    ra = redact("Authorization: Bearer gsk_KHONG-PHAI-DANG-SK-1234567890")
    assert "gsk_KHONG-PHAI-DANG-SK-1234567890" not in ra


def test_che_header_x_api_key() -> None:
    ra = redact("{'x-api-key': 'ANY-SHAPE-OF-KEY-1234', 'content-type': 'application/json'}")
    assert "ANY-SHAPE-OF-KEY-1234" not in ra
    # Chỉ mất đúng giá trị của trường ấy — phần còn lại của dict vẫn đọc được.
    assert "content-type" in ra


def test_che_api_key_dang_gan_bang() -> None:
    assert "RAC-1234567890" not in redact("api_key=RAC-1234567890&model=x")


def test_khong_dung_toi_chuoi_vo_hai() -> None:
    """UUID, Redis Stream ID, tên model — ba thứ đầy trong log của repo này."""
    lanh = "message_id=3fa85f64-5717-4562-b3fc-2c963f66afa6 cursor=1726740000000-0 model=x-1"
    assert redact(lanh) == lanh


# ═════════════════ 2. Qua `logging` thật (tính chất của C20) ════════════════


def test_moi_logger_deu_bi_che_du_khong_thuoc_cay_app(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`logging.Filter` gắn trên logger `app` sẽ **không** bắt được dòng này —
    đó là lý do bộ che nằm ở record factory."""
    with caplog.at_level(logging.INFO):
        logging.getLogger("httpx").info("HTTP Request: GET /models key=%s", KHOA_GIA)
    assert KHOA_GIA not in caplog.text


def test_che_ca_phan_args_chu_khong_chi_msg(caplog: pytest.LogCaptureFixture) -> None:
    """Đường rò thật: `logger.info("goi %s", key)` — chuỗi khoá nằm trong
    `args`, không trong `msg`."""
    with caplog.at_level(logging.INFO):
        logging.getLogger("bat-ky").info("goi provider voi %s", KHOA_GIA)
    assert KHOA_GIA not in caplog.text
    assert REDACTED in caplog.text


def test_che_khi_msg_la_mot_object(caplog: pytest.LogCaptureFixture) -> None:
    """C20 gọi tên đúng ca này: "log cả object request"."""
    with caplog.at_level(logging.INFO):
        logging.getLogger("bat-ky").info({"headers": {"authorization": f"Bearer {KHOA_GIA}"}})
    assert KHOA_GIA not in caplog.text


def test_dong_log_binh_thuong_khong_bi_doi(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        logging.getLogger("bat-ky").info("da xu ly %d hang trong %.2f s", 42, 1.5)
    assert "da xu ly 42 hang trong 1.50 s" in caplog.text


# ═══════════════════════════ 3. Traceback ═══════════════════════════════════


def test_che_trong_traceback_cua_exception(caplog: pytest.LogCaptureFixture) -> None:
    """Nửa thứ hai của C20. Chuỗi khoá chỉ có trong thông điệp exception."""
    with caplog.at_level(logging.ERROR):
        try:
            raise RuntimeError(f"upstream tu choi key {KHOA_GIA}")
        except RuntimeError:
            logging.getLogger("bat-ky").exception("goi provider that bai")
    assert KHOA_GIA not in caplog.text
    assert "goi provider that bai" in caplog.text
