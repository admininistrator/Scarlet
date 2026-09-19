"""AES-256-GCM cho khoá BYOK (§10.5) — T-2.14.

Bốn nhóm, tách theo bốn kiểu hỏng khác nhau:

1. **Nonce** — cạm bẫy của chính task ("dùng chung một nonce phá vỡ hoàn toàn
   GCM"). Đây là nhóm quan trọng nhất, và nó kiểm bằng cách **đo tính chất**
   (hai lần seal cùng bản rõ cho hai bản mã khác nhau), không phải bằng cách
   đọc code.
2. **Vòng đời** — seal rồi unseal phải ra đúng chuỗi ban đầu, kể cả với ký tự
   ngoài ASCII.
3. **Hỏng có kiểm soát** — DoD dòng 6. Đổi `MASTER_ENCRYPTION_KEY`, sửa một
   byte bản mã, sửa nonce: cả ba phải là `DecryptionError`, không phải
   `InvalidTag` của `cryptography` và không phải một chuỗi rác.
4. **Chuỗi che** — `sk-...4f2a` của §10.5, và ca khoá ngắn.

`MASTER_ENCRYPTION_KEY` gán thẳng vào `settings` (đúng lối `test_turnstile.py`)
vì `_data_key()` đọc `settings` lúc **gọi** — xem docstring
`app/core/crypto.py`.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from app.config.settings import settings
from app.core.crypto import (
    KEY_BYTES,
    NONCE_BYTES,
    DecryptionError,
    Sealed,
    mask_secret,
    seal,
    unseal,
)

#: Không phải một khoá thật của ai cả — hai chuỗi 64 ký tự như `openssl rand
#: -hex 32` sinh ra, chỉ khác nhau ở ký tự cuối để phép kiểm "đổi master key"
#: đo đúng cái nó nói.
MASTER_A = "a" * 63 + "1"
MASTER_B = "a" * 63 + "2"

#: Bản rõ mẫu — cố ý mang tiền tố `sk-` và đủ dài để `mask_secret` giữ tiền tố.
KHOA_MAU = "sk-khong-phai-khoa-that-cua-ai-4f2a"


@pytest.fixture(autouse=True)
def master_key_cua_test(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MASTER_ENCRYPTION_KEY", SecretStr(MASTER_A))


def _doi_master_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MASTER_ENCRYPTION_KEY", SecretStr(MASTER_B))


# ═════════════════════════════ 1. Nonce ═════════════════════════════════════


def test_moi_lan_seal_mot_nonce_khac() -> None:
    """Cạm bẫy T-2.14. Mười lần seal ⇒ mười nonce khác nhau."""
    nonces = {seal(KHOA_MAU).nonce for _ in range(10)}
    assert len(nonces) == 10


def test_cung_ban_ro_cho_hai_ban_ma_khac_nhau() -> None:
    """DoD dòng 2: hai user lưu **cùng** một key ⇒ hai `key_cipher` khác nhau.

    Đây là tính chất mà nonce riêng sinh ra để có. Dùng chung nonce thì hai
    bản mã sẽ khớp nhau từng byte và phép kiểm này đỏ.
    """
    a, b = seal(KHOA_MAU), seal(KHOA_MAU)
    assert a.cipher != b.cipher
    assert a.nonce != b.nonce


def test_nonce_dai_dung_12_byte() -> None:
    """96 bit — kích thước GCM được thiết kế quanh nó."""
    assert len(seal(KHOA_MAU).nonce) == NONCE_BYTES == 12


def test_ban_ma_dai_hon_ban_ro_dung_16_byte_tag() -> None:
    """GCM nối tag 16 byte vào cuối — đó là hình dạng `key_cipher` trong DB."""
    assert len(seal(KHOA_MAU).cipher) == len(KHOA_MAU.encode()) + 16


# ═══════════════════════════ 2. Vòng đời ════════════════════════════════════


def test_seal_roi_unseal_ra_dung_ban_ro() -> None:
    assert unseal(seal(KHOA_MAU)) == KHOA_MAU


def test_ban_ma_khong_chua_ban_ro() -> None:
    """DoD dòng 1, đo ở tầng thấp nhất: bản mã không mang lại chuỗi gốc."""
    assert KHOA_MAU.encode() not in seal(KHOA_MAU).cipher


def test_ky_tu_ngoai_ascii_di_ve_nguyen_ven() -> None:
    """Khoá là do provider sinh, nhưng `seal` không được phép giả định ASCII:
    một lần ai đó dán nhầm vào ô nhập cũng không được thành `UnicodeDecodeError`
    ở đường giải mã."""
    ban_ro = "khoa-có-dấu-và-emoji-🔑"
    assert unseal(seal(ban_ro)) == ban_ro


def test_master_key_dai_hon_32_byte_van_ra_khoa_32_byte() -> None:
    """`openssl rand -hex 32` cho 64 ký tự; AES-256 đòi đúng 32 byte.

    Đo gián tiếp qua HKDF: seal/unseal chạy được nghĩa là `_data_key()` đã trả
    đúng độ dài — `AESGCM` từ chối mọi độ dài khác.
    """
    assert len(settings.MASTER_ENCRYPTION_KEY.get_secret_value()) > KEY_BYTES
    assert unseal(seal(KHOA_MAU)) == KHOA_MAU


# ═══════════════════ 3. Hỏng CÓ KIỂM SOÁT (DoD dòng 6) ══════════════════════


def test_doi_master_key_thi_DecryptionError_chu_khong_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DoD dòng 6 — và `DecryptionError` là kiểu của **mình**, để tầng HTTP
    bắt được mà không phải import `cryptography`."""
    da_seal = seal(KHOA_MAU)
    _doi_master_key(monkeypatch)
    with pytest.raises(DecryptionError):
        unseal(da_seal)


def test_thong_diep_loi_khong_chua_ban_ro(monkeypatch: pytest.MonkeyPatch) -> None:
    """C20: một exception là thứ đi thẳng vào log."""
    da_seal = seal(KHOA_MAU)
    _doi_master_key(monkeypatch)
    with pytest.raises(DecryptionError) as loi:
        unseal(da_seal)
    assert KHOA_MAU not in str(loi.value)


def test_sua_mot_byte_ban_ma_thi_DecryptionError() -> None:
    """GCM xác thực cả bản mã: một hàng DB bị sửa tay không ra chuỗi rác."""
    goc = seal(KHOA_MAU)
    hong = Sealed(cipher=bytes([goc.cipher[0] ^ 0x01]) + goc.cipher[1:], nonce=goc.nonce)
    with pytest.raises(DecryptionError):
        unseal(hong)


def test_nonce_sai_do_dai_thi_DecryptionError() -> None:
    """`AESGCM` ném `ValueError` chứ không `InvalidTag` cho ca này — nếu
    `unseal` chỉ bắt `InvalidTag` thì một hàng hỏng thành `500`."""
    goc = seal(KHOA_MAU)
    with pytest.raises(DecryptionError):
        unseal(Sealed(cipher=goc.cipher, nonce=b"ngan"))


def test_nonce_khac_thi_DecryptionError() -> None:
    """Ghi đè `key_cipher` mà quên `key_nonce` (hoặc ngược lại) phải hỏng
    to chứ không im lặng — đó là lý do `upsert` ghi cả hai cột cùng lúc."""
    a, b = seal(KHOA_MAU), seal(KHOA_MAU)
    with pytest.raises(DecryptionError):
        unseal(Sealed(cipher=a.cipher, nonce=b.nonce))


# ═════════════════════════ 4. Chuỗi che (§10.5) ═════════════════════════════


def test_mask_giu_ba_ky_tu_dau_va_bon_ky_tu_cuoi() -> None:
    """§10.5 viết thẳng hình dạng này: `sk-...4f2a`."""
    assert mask_secret(KHOA_MAU) == "sk-...4f2a"


def test_mask_khong_chua_ban_ro() -> None:
    assert KHOA_MAU not in mask_secret(KHOA_MAU)


def test_mask_khoa_ngan_thi_bo_tien_to() -> None:
    """Với chuỗi ngắn, giữ cả tiền tố lẫn hậu tố là lộ gần hết."""
    assert mask_secret("abcdefgh") == "...efgh"
