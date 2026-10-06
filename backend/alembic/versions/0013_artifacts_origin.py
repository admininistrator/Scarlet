"""artifacts.origin — phiên bản do model hay do người dùng sửa (T-5.2b)

KH tham chiếu: §14.1 (hàng 4), §14.2 · tasks.md T-5.2b · NQ-142 (Q-P5-3, Q-P5-5).

Tập cố định `model | user` (lối `ExtractStatus` của T-4.6a): `TEXT` + `CHECK`,
không ENUM. Hàng có sẵn đều do worker sinh ⇒ `DEFAULT 'model'` đúng cho chúng.
`build()` chỉ đưa bản `user` vào ngữ cảnh lượt kế tiếp.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-07
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE artifacts ADD COLUMN origin TEXT NOT NULL DEFAULT 'model' "
        "CONSTRAINT ck_art_origin CHECK (origin IN ('model', 'user'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE artifacts DROP COLUMN IF EXISTS origin")
