"""skills.default_enabled — skill dựng sẵn bật cho user chưa đặt công tắc (T-7.8b)

KH tham chiếu: §13.2 · tasks.md T-7.8b · NQ-148 ②.

Loader ghi từ `metadata.default_enabled: "true"` của frontmatter. Không hàng
`user_skills` ⇒ dùng cột này; có hàng ⇒ công tắc của user thắng.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-13
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE skills ADD COLUMN default_enabled BOOLEAN NOT NULL DEFAULT false")


def downgrade() -> None:
    op.execute("ALTER TABLE skills DROP COLUMN IF EXISTS default_enabled")
