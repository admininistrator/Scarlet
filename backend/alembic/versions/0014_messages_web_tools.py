"""messages.web_tools + messages.tool_rounds — lượt có tool trong MỘT message (T-6.7a)

KH tham chiếu: §7.2 ③, §13.5, §17.2 · tasks.md T-6.7a · NQ-144 (Q-P6-1, Q-P6-3).

`web_tools`: cờ công tắc "Tìm web" của lượt — API ghi lên hàng `queued`, worker
đọc (lối `reasoning_effort`, migration 0006). `tool_rounds`: mỗi vòng tool một
phần tử `{tool_calls, reasoning, finish_reason, results}`; role `tool` /
`tool_call_id` của DDL không dùng (Q-P6-1). NULL = lượt không gọi tool.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-09
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE messages "
        "ADD COLUMN web_tools BOOLEAN NOT NULL DEFAULT false, "
        "ADD COLUMN tool_rounds JSONB"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE messages DROP COLUMN IF EXISTS tool_rounds, DROP COLUMN IF EXISTS web_tools"
    )
