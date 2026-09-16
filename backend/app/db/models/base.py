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

from enum import Enum
from typing import Any

from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import DeclarativeBase


def pg_enum(python_enum: type[Enum], name: str) -> ENUM:
    """Ánh xạ enum Python sang kiểu ENUM **đã có sẵn** trong Postgres.

    Dùng chung cho mọi model có cột kiểu ENUM (`message.py`, `user.py`, …) —
    một hàm, không phải mỗi model tự chép lại.

    `create_type=False`: kiểu do migration tạo, ORM không được tạo lại.
    `values_callable`: không có nó, SQLAlchemy gửi **tên** thành viên
    (`ASSISTANT`) xuống DB thay vì **giá trị** (`assistant`), và Postgres từ
    chối vì nhãn không tồn tại trong kiểu.
    """
    return ENUM(
        python_enum,
        name=name,
        create_type=False,
        values_callable=lambda enum_cls: [member.value for member in enum_cls],
    )


class Base(DeclarativeBase):
    """Gốc khai báo dùng chung.

    `eager_defaults=True` bắt SQLAlchemy dùng `RETURNING` để lấy luôn giá trị
    do Postgres sinh (`id`, `created_at`, default của `status`/`content`) ngay
    trong câu INSERT/UPDATE. Không có nó, lần đầu đọc `message.created_at` sau
    `flush()` sẽ là một lazy-load — mà lazy-load ngoài ngữ cảnh `await` trong
    asyncio không phải một query chậm, nó là `MissingGreenlet` lúc chạy.
    """

    __mapper_args__: dict[str, Any] = {"eager_defaults": True}
