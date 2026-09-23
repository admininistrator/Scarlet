"""Mã hoá khoá BYOK — AES-256-GCM, nonce riêng mỗi bản ghi (§10.5) — T-2.14.

KH tham chiếu: §10.5, §14 (bảng "BYOK"), §23 `core/crypto.py` · Cạm bẫy C20 ·
CLAUDE.md A3, A4 · tasks.md T-2.14, NQ-45.

┌──────────────────────────────────────────────────────────────────────────┐
│  CẠM BẪY CỦA T-2.14: DÙNG CHUNG MỘT NONCE                                │
└──────────────────────────────────────────────────────────────────────────┘

*"Dùng chung một nonce cho mọi bản ghi phá vỡ hoàn toàn GCM. Sinh nonce ngẫu
nhiên mỗi lần mã hoá."*

GCM là một stream cipher: bản mã = bản rõ XOR với dòng khoá sinh từ
`(khoá, nonce)`. Hai bản ghi cùng `(khoá, nonce)` cho **cùng** dòng khoá, nên
XOR hai bản mã với nhau là xoá sạch dòng khoá và để lại `plaintext₁ XOR
plaintext₂` — hai khoá API của hai người dùng, khớp nhau từng byte. Tệ hơn:
lặp nonce trong GCM còn làm lộ khoá xác thực `H`, tức kẻ tấn công **giả được
tag**, và từ đó bản mã trong DB không còn là thứ chỉ đọc được nữa.

Vì vậy `seal()` gọi `os.urandom(NONCE_BYTES)` mỗi lần, không có đường nào
truyền nonce vào từ ngoài, và không có bộ đếm nào để ai đó "tối ưu". DDL Phụ
lục A cho `key_nonce` một cột riêng chính là vì mỗi hàng mang nonce của nó.

┌──────────────────────────────────────────────────────────────────────────┐
│  KHOÁ DẪN XUẤT, KHÔNG PHẢI `MASTER_ENCRYPTION_KEY` THÔ                   │
└──────────────────────────────────────────────────────────────────────────┘

§10.5 viết "khoá **dẫn xuất** từ `MASTER_ENCRYPTION_KEY`", và chữ đó là bắt
buộc chứ không phải trang trí: `MASTER_ENCRYPTION_KEY` là một chuỗi do người
vận hành dán vào `.env` (`openssl rand -hex 32` ⇒ **64** ký tự ASCII), còn
AES-256 đòi đúng **32 byte**. Cắt bừa 32 ký tự đầu là vứt một nửa entropy và
biến một chuỗi hex thành một khoá chỉ có 16 giá trị cho mỗi byte.

HKDF-SHA256 (`info=SCARLET_BYOK_INFO`) nhận chuỗi dài bao nhiêu cũng được, trả
đúng 32 byte, và trường `info` khoanh vùng: ngày nào một tính năng khác cũng
cần mã hoá bằng cùng master key, nó lấy một `info` khác và hai kho không dùng
chung dòng khoá. `salt=None` (HKDF quy về salt toàn 0) là chủ ý — salt của
HKDF phải được **lưu** để dẫn xuất lại, mà chỗ duy nhất lưu được là chính bảng
này, tức thêm một cột cho một giá trị công khai; với master key đã là 32+ byte
ngẫu nhiên thì salt không thêm gì.

**`settings` đọc lúc GỌI, không lúc import.** Cùng lý do với `is_enabled()` của
`core/turnstile.py`: một phép kiểm đổi `MASTER_ENCRYPTION_KEY` rồi gọi lại phải
thấy hiệu lực mà không cần nạp lại module — và đó chính là DoD dòng 6 của task
này. HKDF là hai lần HMAC-SHA256, tính lại mỗi lần gọi là chi phí không đo được
ở quy mô 15–20 người dùng.

┌──────────────────────────────────────────────────────────────────────────┐
│  ĐỔI MASTER KEY ⇒ HỎNG CÓ KIỂM SOÁT, KHÔNG PHẢI CRASH                    │
└──────────────────────────────────────────────────────────────────────────┘

DoD dòng 6. `AESGCM.decrypt` ném `cryptography.exceptions.InvalidTag` — một
kiểu của thư viện, và để nó nổi lên tầng HTTP nghĩa là `500 INTERNAL_ERROR`
cho một tình huống hoàn toàn dự đoán được (người vận hành xoay khoá, hoặc khôi
phục một bản dump DB sang máy có `.env` khác). `unseal()` vì vậy đổi nó thành
`DecryptionError` — một kiểu của **mình**, để tầng gọi bắt được mà không phải
import `cryptography`, và để câu trả lời cho người dùng là "hãy nhập lại khoá"
chứ không phải một trang lỗi.

`InvalidTag` cũng là cái lưới bắt bản mã bị sửa: GCM xác thực cả bản mã lẫn
tag, nên một byte đổi trong `key_cipher` cho ra đúng lỗi ấy, không phải một
chuỗi rác.

┌──────────────────────────────────────────────────────────────────────────┐
│  `mask_secret` — THỨ DUY NHẤT ĐƯỢC PHÉP ĐI RA NGOÀI                      │
└──────────────────────────────────────────────────────────────────────────┘

§10.5: *"Hiển thị lại: **không bao giờ.** UI chỉ hiện `sk-...4f2a` (4 ký tự
cuối) + thời điểm thêm."* Hàm ở đây dựng đúng chuỗi đó, và nó sống cạnh phần
mã hoá chứ không ở tầng API vì đây là cùng một luật: bản rõ chỉ rời khỏi
module này dưới dạng đã che.

Giữ `_PREFIX_CHARS` ký tự đầu chứ không che sạch: đó là thứ làm `sk-...4f2a`
đọc được đúng như §10.5 viết, và ba ký tự đầu của một khoá là phần **công
khai** của mọi định dạng khoá API (tiền tố định danh nhà cung cấp). Không gõ
`"sk-"` vào code — một tiền tố cứng ở đây là literal của một provider cụ thể,
đúng thứ A3 cấm; hàm chỉ cắt theo vị trí và bất kỳ provider nào cũng đi qua.

Khoá quá ngắn thì **không** giữ tiền tố: với một chuỗi 8 ký tự,
`3 + 4 = 7/8` là gần như lộ hết. Ngưỡng nằm ở `_MIN_CHARS_KEEP_PREFIX`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config.settings import settings

#: 96 bit — kích thước nonce mà GCM được thiết kế quanh nó. Khác 12 byte thì
#: GCM phải băm nonce qua GHASH trước, một đường ít được kiểm hơn và không
#: nhanh hơn. Là một hằng **mật mã** (một thuộc tính của thuật toán), không
#: phải một giới hạn vận hành, nên nó ở đây chứ không ở `settings` (A3).
NONCE_BYTES = 12

#: AES-256 ⇒ khoá 32 byte. Cùng loại hằng với `NONCE_BYTES`.
KEY_BYTES = 32

#: Trường `info` của HKDF — khoanh vùng khoá dẫn xuất cho đúng một mục đích
#: (xem docstring module). Đổi chuỗi này là làm **mọi** bản ghi đang có không
#: giải mã được nữa, y hệt đổi `MASTER_ENCRYPTION_KEY`.
SCARLET_BYOK_INFO = b"scarlet:user_provider_keys:aes-256-gcm:v1"

#: Số ký tự đầu giữ lại trong chuỗi che (`sk-` của `sk-...4f2a`).
_PREFIX_CHARS = 3

#: Số ký tự cuối giữ lại — §10.5 viết thẳng "4 ký tự cuối".
_SUFFIX_CHARS = 4

#: Dưới ngưỡng này thì bỏ tiền tố đi, chỉ giữ 4 ký tự cuối. 12 = 3 lần phần
#: lộ ra, tức chuỗi che vẫn giấu ít nhất 2/3 số ký tự.
_MIN_CHARS_KEEP_PREFIX = 12

#: Phần thay cho khúc giữa.
_ELLIPSIS = "..."


class DecryptionError(Exception):
    """Không giải mã được `key_cipher` bằng `MASTER_ENCRYPTION_KEY` hiện tại.

    Hai nguyên nhân có thật, cả hai đều **không** phải lỗi lập trình: master
    key đã đổi (xoay khoá, hoặc `.env` của một máy khác), hoặc bản mã/nonce
    trong DB đã bị sửa. Xem docstring module.
    """


@dataclass(frozen=True, slots=True)
class Sealed:
    """Đúng hai cột mà Phụ lục A dành cho một khoá đã mã hoá.

    `cipher` đã bao gồm tag xác thực 16 byte ở cuối — đó là hình dạng
    `AESGCM.encrypt` trả về, và tách tag ra một cột thứ ba chỉ tạo thêm một
    chỗ để ghép sai.
    """

    cipher: bytes
    nonce: bytes


def _data_key() -> bytes:
    """32 byte khoá AES, dẫn xuất từ `MASTER_ENCRYPTION_KEY` (xem docstring module)."""
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=KEY_BYTES,
        salt=None,
        info=SCARLET_BYOK_INFO,
    )
    return hkdf.derive(settings.MASTER_ENCRYPTION_KEY.get_secret_value().encode("utf-8"))


def seal(plaintext: str) -> Sealed:
    """Mã hoá một khoá BYOK. Nonce MỚI mỗi lần gọi — xem docstring module.

    Hai lần gọi với **cùng** một bản rõ cho hai `Sealed` khác nhau; đó là DoD
    dòng 2 của T-2.14 ("hai user lưu cùng một key → hai `key_cipher` khác
    nhau") và là tính chất mà cạm bẫy của task nói tới.
    """
    nonce = os.urandom(NONCE_BYTES)
    cipher = AESGCM(_data_key()).encrypt(nonce, plaintext.encode("utf-8"), None)
    return Sealed(cipher=cipher, nonce=nonce)


def unseal(sealed: Sealed) -> str:
    """Giải mã, hoặc `DecryptionError` — KHÔNG bao giờ để `InvalidTag` nổi lên.

    Raises:
        DecryptionError: master key đã đổi, hoặc bản mã/nonce đã bị sửa.
    """
    try:
        plaintext = AESGCM(_data_key()).decrypt(sealed.nonce, sealed.cipher, None)
    except InvalidTag as exc:
        # KHÔNG kèm `sealed` vào thông điệp: bản mã không phải bí mật, nhưng
        # một exception có dữ liệu đi kèm là một exception sẽ vào log (C20).
        raise DecryptionError(
            "khong giai ma duoc khoa BYOK bang MASTER_ENCRYPTION_KEY hien tai"
        ) from exc
    except ValueError as exc:
        # Nonce sai độ dài — một hàng hỏng trong DB, không phải một tag sai.
        raise DecryptionError("ban ghi khoa BYOK khong dung dinh dang") from exc
    return plaintext.decode("utf-8")


def mask_secret(plaintext: str) -> str:
    """Chuỗi che mà UI được phép hiện — `sk-...4f2a` (§10.5).

    Đây là giá trị đi vào cột `user_provider_keys.key_last4` (DDL ghi "chỉ để
    hiển thị"): lưu **chuỗi đã che** chứ không phải 4 ký tự rời nghĩa là đường
    đọc của `GET /settings/keys` không phải giải mã gì cả — bản rõ chỉ đi qua
    tiến trình đúng một lần, lúc lưu.
    """
    if len(plaintext) >= _MIN_CHARS_KEEP_PREFIX:
        return f"{plaintext[:_PREFIX_CHARS]}{_ELLIPSIS}{plaintext[-_SUFFIX_CHARS:]}"
    return f"{_ELLIPSIS}{plaintext[-_SUFFIX_CHARS:]}"
