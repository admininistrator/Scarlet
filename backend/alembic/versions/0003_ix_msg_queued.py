"""Partial index cho nhánh `queued` của reaper §7.6 (B-123).

Từ B-123, reaper quét **hai** tập chứ không một: message mất nhịp tim
(`status='streaming'`, đã có `ix_msg_streaming` từ 0001) và message mồ côi
trong hàng đợi (`status='queued'`, chưa có index nào).

Cạm bẫy của T-1.10 áp nguyên cho nhánh mới: một câu quét toàn bảng `messages`
mỗi 30 giây sẽ thành truy vấn nặng nhất hệ thống sau vài tháng. Index này là
**partial** đúng như `ix_msg_streaming`, và cùng lý do — số dòng `queued` tại
một thời điểm bất kỳ là vài cái, trong khi `messages` lớn không giới hạn.

Đánh trên `created_at` chứ không `heartbeat_at`: một message `queued` **chưa
bao giờ** có nhịp tim (`mark_streaming` mới là chỗ đặt `heartbeat_at`, và nó
chính là bước chưa chạy), nên ngưỡng của nhánh này đo trên tuổi của message.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-16
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE INDEX ix_msg_queued ON messages (created_at) WHERE status = 'queued'")


def downgrade() -> None:
    op.execute("DROP INDEX ix_msg_queued")
