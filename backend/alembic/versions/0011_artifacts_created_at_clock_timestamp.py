"""artifacts.created_at dùng clock_timestamp() thay cho now() (T-5.1)

KH tham chiếu: §14.2, §17.2, Phụ lục A · tasks.md B-57, NQ-18 · migration 0002.

Đúng cách sửa của `0002` cho `messages`: worker ghi MỌI artifact của một câu
trả lời trong **một** transaction, và `now()` là hằng của transaction — các
hàng sẽ mang cùng `created_at`. Thứ tự phiên bản vẫn theo cột `version`
(T-5.2a), không theo cột này; nhưng một cột tên `created_at` trả về cùng một
giá trị cho hai hàng ghi lần lượt là nói dối. Đổi DEFAULT là thao tác metadata.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-06
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE artifacts ALTER COLUMN created_at SET DEFAULT clock_timestamp()")


def downgrade() -> None:
    op.execute("ALTER TABLE artifacts ALTER COLUMN created_at SET DEFAULT now()")
