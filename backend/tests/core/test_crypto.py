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
SAMPLE_KEY = "sk-khong-phai-khoa-that-cua-ai-4f2a"


@pytest.fixture(autouse=True)
def master_key_for_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MASTER_ENCRYPTION_KEY", SecretStr(MASTER_A))


def _swap_master_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MASTER_ENCRYPTION_KEY", SecretStr(MASTER_B))


# ═════════════════════════════ 1. Nonce ═════════════════════════════════════


def test_each_seal_uses_different_nonce() -> None:
    """Cạm bẫy T-2.14. Mười lần seal ⇒ mười nonce khác nhau."""
    nonces = {seal(SAMPLE_KEY).nonce for _ in range(10)}
    assert len(nonces) == 10


def test_same_plaintext_gives_two_different_ciphertexts() -> None:
    """DoD dòng 2: hai user lưu **cùng** một key ⇒ hai `key_cipher` khác nhau.

    Đây là tính chất mà nonce riêng sinh ra để có. Dùng chung nonce thì hai
    bản mã sẽ khớp nhau từng byte và phép kiểm này đỏ.
    """
    a, b = seal(SAMPLE_KEY), seal(SAMPLE_KEY)
    assert a.cipher != b.cipher
    assert a.nonce != b.nonce


def test_nonce_is_exactly_12_bytes() -> None:
    """96 bit — kích thước GCM được thiết kế quanh nó."""
    assert len(seal(SAMPLE_KEY).nonce) == NONCE_BYTES == 12


def test_ciphertext_longer_than_plaintext_by_16_byte_tag() -> None:
    """GCM nối tag 16 byte vào cuối — đó là hình dạng `key_cipher` trong DB."""
    assert len(seal(SAMPLE_KEY).cipher) == len(SAMPLE_KEY.encode()) + 16


# ═══════════════════════════ 2. Vòng đời ════════════════════════════════════


def test_seal_then_unseal_yields_plaintext() -> None:
    assert unseal(seal(SAMPLE_KEY)) == SAMPLE_KEY


def test_ciphertext_has_no_plaintext() -> None:
    """DoD dòng 1, đo ở tầng thấp nhất: bản mã không mang lại chuỗi gốc."""
    assert SAMPLE_KEY.encode() not in seal(SAMPLE_KEY).cipher


def test_non_ascii_chars_round_trip_intact() -> None:
    """Khoá là do provider sinh, nhưng `seal` không được phép giả định ASCII:
    một lần ai đó dán nhầm vào ô nhập cũng không được thành `UnicodeDecodeError`
    ở đường giải mã."""
    plaintext = "khoa-có-dấu-và-emoji-🔑"
    assert unseal(seal(plaintext)) == plaintext


def test_master_key_over_32_bytes_still_yields_32_byte_key() -> None:
    """`openssl rand -hex 32` cho 64 ký tự; AES-256 đòi đúng 32 byte.

    Đo gián tiếp qua HKDF: seal/unseal chạy được nghĩa là `_data_key()` đã trả
    đúng độ dài — `AESGCM` từ chối mọi độ dài khác.
    """
    assert len(settings.MASTER_ENCRYPTION_KEY.get_secret_value()) > KEY_BYTES
    assert unseal(seal(SAMPLE_KEY)) == SAMPLE_KEY


# ═══════════════════ 3. Hỏng CÓ KIỂM SOÁT (DoD dòng 6) ══════════════════════


def test_master_key_change_gives_DecryptionError_not_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DoD dòng 6 — và `DecryptionError` là kiểu của **mình**, để tầng HTTP
    bắt được mà không phải import `cryptography`."""
    sealed = seal(SAMPLE_KEY)
    _swap_master_key(monkeypatch)
    with pytest.raises(DecryptionError):
        unseal(sealed)


def test_error_message_has_no_plaintext(monkeypatch: pytest.MonkeyPatch) -> None:
    """C20: một exception là thứ đi thẳng vào log."""
    sealed = seal(SAMPLE_KEY)
    _swap_master_key(monkeypatch)
    with pytest.raises(DecryptionError) as error:
        unseal(sealed)
    assert SAMPLE_KEY not in str(error.value)


def test_flipping_one_ciphertext_byte_gives_DecryptionError() -> None:
    """GCM xác thực cả bản mã: một hàng DB bị sửa tay không ra chuỗi rác."""
    original = seal(SAMPLE_KEY)
    broken = Sealed(
        cipher=bytes([original.cipher[0] ^ 0x01]) + original.cipher[1:], nonce=original.nonce
    )
    with pytest.raises(DecryptionError):
        unseal(broken)


def test_wrong_nonce_length_gives_DecryptionError() -> None:
    """`AESGCM` ném `ValueError` chứ không `InvalidTag` cho ca này — nếu
    `unseal` chỉ bắt `InvalidTag` thì một hàng hỏng thành `500`."""
    original = seal(SAMPLE_KEY)
    with pytest.raises(DecryptionError):
        unseal(Sealed(cipher=original.cipher, nonce=b"ngan"))


def test_other_nonce_gives_DecryptionError() -> None:
    """Ghi đè `key_cipher` mà quên `key_nonce` (hoặc ngược lại) phải hỏng
    to chứ không im lặng — đó là lý do `upsert` ghi cả hai cột cùng lúc."""
    a, b = seal(SAMPLE_KEY), seal(SAMPLE_KEY)
    with pytest.raises(DecryptionError):
        unseal(Sealed(cipher=a.cipher, nonce=b.nonce))


# ═════════════════════════ 4. Chuỗi che (§10.5) ═════════════════════════════


def test_mask_keeps_first_three_and_last_four_chars() -> None:
    """§10.5 viết thẳng hình dạng này: `sk-...4f2a`."""
    assert mask_secret(SAMPLE_KEY) == "sk-...4f2a"


def test_mask_has_no_plaintext() -> None:
    assert SAMPLE_KEY not in mask_secret(SAMPLE_KEY)


def test_mask_of_short_key_drops_prefix() -> None:
    """Với chuỗi ngắn, giữ cả tiền tố lẫn hậu tố là lộ gần hết."""
    assert mask_secret("abcdefgh") == "...efgh"
