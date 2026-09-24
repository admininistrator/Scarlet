"""usage_events.purpose — tách lượt đặt tên hội thoại khỏi lượt chat (§24.2b·S6, S14)

KH tham chiếu: §24.2b·S6, S14, §10.2, §10.3 · tasks.md T-S.7 · NQ-110.

S6 chốt: lượt đặt tên tự động tiêu **tiền của người vận hành** (system key) và
vẫn ghi sổ như mọi lượt gọi model (A7), nhưng **không** trừ vào hai cửa sổ quota
của người dùng. Hai chỗ phải biết một dòng sổ thuộc loại nào:

* `quota/meter.py::record_usage` — không `ZADD` cho dòng `title`;
* ba câu dựng lại quota của `UsageEventRepository` (`list_since`,
  `has_events_since`, `user_ids_since`) — chỉ đọc `purpose = 'chat'`. Thiếu vế
  này thì lần dựng lại đầu tiên sau khi Redis mất dữ liệu (§10.3, RR-7) trừ oan
  mọi lượt đặt tên — Cạm bẫy ① của T-S.7.

**`TEXT NOT NULL DEFAULT 'chat'` + `CHECK`, không ENUM** — chữ của S14, và cùng
khuôn hai cột anh em `key_source`/`cost_confidence` của Phụ lục A. `DEFAULT
'chat'` đúng cho 100% số hàng đã có: trước T-S.7 không có đường ghi sổ nào khác
ngoài lượt chat. Postgres ≥ 11 thêm cột có `DEFAULT` hằng mà không viết lại bảng.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

#: Bản sao ĐÔNG CỨNG của `UsagePurpose` tại ngày 2026-09-24 — cùng lý lẽ
#: `_LEVELS` của 0006: migration đã chạy phải mô tả đúng thứ nó đã làm với
#: database. `tests/db/test_usage_purpose_column.py` canh hai chỗ không lệch nhau.
_PURPOSES = ("chat", "title")

_CK_PURPOSE = "ck_usage_purpose"


def upgrade() -> None:
    op.add_column(
        "usage_events",
        sa.Column("purpose", sa.Text(), nullable=False, server_default=sa.text("'chat'")),
    )
    allowed = ", ".join(f"'{purpose}'" for purpose in _PURPOSES)
    op.create_check_constraint(_CK_PURPOSE, "usage_events", f"purpose IN ({allowed})")


def downgrade() -> None:
    op.drop_constraint(_CK_PURPOSE, "usage_events", type_="check")
    op.drop_column("usage_events", "purpose")
