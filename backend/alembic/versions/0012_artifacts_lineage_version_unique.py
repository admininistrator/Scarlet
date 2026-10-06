"""Chỉ mục UNIQUE (dòng, version) trên artifacts (T-5.2a)

KH tham chiếu: §14.2, §17.4 · tasks.md T-5.2a, NQ-142 (Q-P5-2).

Dòng phiên bản = `COALESCE(parent_artifact_id, id)` (`parent_artifact_id` trỏ về
GỐC). Hai lượt ghi đua nhau trên một dòng tính cùng `max + 1` — chỉ mục này làm
một bên vi phạm, repository tính lại một lần. Kiêm chỉ mục tra "mọi phiên bản
của dòng" (`GET /artifacts/{id}/versions`).

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-06
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX uq_art_lineage_version "
        "ON artifacts ((COALESCE(parent_artifact_id, id)), version)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX uq_art_lineage_version")
