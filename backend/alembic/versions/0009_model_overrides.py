"""model_overrides — admin ghi đè cờ `vision` của một model catalog (T-4.5)

KH tham chiếu: §9.2, §9.4, S9 · tasks.md T-4.5, B-258 · NQ-139.

Catalog vẫn là file (§9.2) và vẫn là giá trị mặc định; một hàng ở đây thắng
file cho đúng một cờ. Xoá hàng ⇒ về lại giá trị của file. Không khoá ngoại tới
catalog — catalog không phải bảng; hàng của một model đã biến khỏi file chỉ
nằm im, không ai đọc tới.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE model_overrides (
            model_id    TEXT PRIMARY KEY,
            vision      BOOLEAN NOT NULL,
            updated_by  UUID REFERENCES users(id) ON DELETE SET NULL,
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS model_overrides")
