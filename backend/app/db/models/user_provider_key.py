"""Bảng `user_provider_keys` — BYOK (KH Phụ lục A, §10.5) — T-2.14.

Bảng đã có trong DB từ migration 0001, nhưng tới hôm nay mới có model: T-2.7
cố ý hỏi nó bằng một câu `text()` (`UserRepository.has_provider_key`) và ghi
rõ lý do — *"dựng model ở đây là làm trước một phần của T-2.14, nơi hình dạng
thật của bảng mới có người dùng"*. Đây là task đó.

Cũng như `tier.py` và `usage_event.py`, model này không có một dòng logic nào.
Phần "mã hoá/giải mã" sống ở `app/core/crypto.py`, phần "kiểm khoá còn sống"
ở `app/llm/byok_verify.py`, phần "câu SQL" ở
`app/db/repositories/provider_keys.py`.

**Không có cột `deleted_at`, và đó là chữ của §10.5:** *"Xoá tài khoản: xoá
cứng bản ghi key, không soft-delete."* Một khoá API bị thu hồi phải biến mất
khỏi đĩa, không phải mang một cột đánh dấu mà một câu `SELECT` quên lọc là đọc
lại được.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, LargeBinary, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class UserProviderKey(Base):
    __tablename__ = "user_provider_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    #: `ON DELETE CASCADE` (Phụ lục A) — xoá tài khoản là xoá khoá, §10.5.
    #: Khác hẳn `messages.parent_id`, nơi CASCADE bị cấm (C12): ở đó cascade
    #: xoá mất một **nhánh hội thoại**, ở đây nó xoá đúng thứ phải xoá.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    #: Khoá trong `model_catalog.json::providers` (§9.2). TEXT chứ không ENUM:
    #: thêm một provider là sửa **một file JSON**, không phải một migration —
    #: đó là tiêu chí S15 ("thêm provider = 0 dòng code").
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    #: AES-256-GCM: bản mã **đã gồm tag 16 byte ở cuối** (`app/core/crypto.py`).
    key_cipher: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    #: Nonce RIÊNG của đúng hàng này — cạm bẫy của T-2.14. Cột riêng chính là
    #: cách DDL bắt buộc điều đó: không có chỗ nào để đặt một nonce dùng chung.
    key_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    #: DDL ghi "chỉ để hiển thị", và giá trị lưu ở đây là **nguyên chuỗi che**
    #: mà §10.5 cho phép UI hiện (`sk-...4f2a`), chứ không phải 4 ký tự rời.
    #: Xem `app/core/crypto.py::mask_secret`: nhờ vậy `GET /settings/keys` đọc
    #: xong là trả lời được, không phải giải mã gì — bản rõ chỉ đi qua tiến
    #: trình đúng một lần, lúc lưu.
    key_last4: Mapped[str] = mapped_column(Text, nullable=False)
    #: Thời điểm provider xác nhận khoá còn sống (§10.5 "Kiểm tra khi thêm").
    #: `NULL` = đã lưu mà **chưa** kiểm được — ca C42 (provider không khai
    #: `verify_path`, hoặc kiểu xác thực chưa kiểm được). Nullable chính là
    #: chỗ DDL chừa cho ca đó, nên nó không bị nhét thành một `False` giả.
    verified_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    #: `UNIQUE (user_id, provider)` của Phụ lục A. Khai lại ở đây không phải
    #: để tạo ràng buộc (migration 0001 đã tạo, xem `base.py` luật 1) mà để
    #: `ProviderKeyRepository.upsert` có một `ON CONFLICT` suy ra được từ
    #: model thay vì một tên ràng buộc gõ tay.
    __table_args__ = (UniqueConstraint("user_id", "provider"),)

    def __repr__(self) -> str:
        # KHÔNG có `key_cipher`/`key_nonce`: một `repr` là thứ đi thẳng vào log
        # và vào thông báo lỗi (C20), nên nó chỉ mang những gì UI được phép
        # thấy. `key_last4` đã là chuỗi che.
        return (
            f"UserProviderKey(user_id={self.user_id!r}, provider={self.provider!r}, "
            f"key_last4={self.key_last4!r})"
        )
