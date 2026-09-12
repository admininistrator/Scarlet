"""Lớp khai báo gốc cho mọi ORM model.

KH tham chiếu: §17, Phụ lục A.

Hai luật của tầng này:

1. **Migration sinh bảng, model KHÔNG.** Không có `Base.metadata.create_all()`
   ở bất cứ đâu trong repo. Model chỉ mô tả lại DDL của Phụ lục A để Python
   đọc/ghi có kiểu; thêm cột ở đây mà không thêm migration là tạo ra một
   schema chỉ tồn tại trong trí tưởng tượng của ORM.
2. **Không chép default của DDL sang Python.** Cột nào có `DEFAULT` trong
   Phụ lục A thì khai `server_default` đúng giá trị đó và để Postgres điền.
   Hai nguồn default là hai nguồn sự thật, và chúng sẽ lệch nhau.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Gốc khai báo dùng chung.

    `eager_defaults=True` bắt SQLAlchemy dùng `RETURNING` để lấy luôn giá trị
    do Postgres sinh (`id`, `created_at`, default của `status`/`content`) ngay
    trong câu INSERT/UPDATE. Không có nó, lần đầu đọc `message.created_at` sau
    `flush()` sẽ là một lazy-load — mà lazy-load ngoài ngữ cảnh `await` trong
    asyncio không phải một query chậm, nó là `MissingGreenlet` lúc chạy.
    """

    __mapper_args__: dict[str, Any] = {"eager_defaults": True}
