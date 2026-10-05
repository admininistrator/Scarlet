"""attachments.page_count — số trang PDF, job `extract` ghi một lần (T-4.6b)

KH tham chiếu: §15.3 (nhánh "Không có text"), §17.2 · tasks.md T-4.6b · NQ-141.

`build()` chạy cả ở `api` (dự toán quota) mà không được mở PDF lần hai (Cạm bẫy
③): mỗi trang PDF quét là một phần `image_url`, cộng `VISION_TOKENS_PER_IMAGE`
(Cạm bẫy ①) — số trang phải nằm trong hàng. `NULL` cho mọi thứ không phải PDF.
Lệch DDL Phụ lục A — NQ-141.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-06
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE attachments ADD COLUMN page_count INT")


def downgrade() -> None:
    op.execute("ALTER TABLE attachments DROP COLUMN IF EXISTS page_count")
