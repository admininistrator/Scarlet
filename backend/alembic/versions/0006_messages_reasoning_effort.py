"""messages.reasoning_effort — mức suy luận của một lượt sinh (§24.2b·S4, S14)

KH tham chiếu: §24.2b·S3b, S4, S14 · tasks.md T-S.6 · NQ-118.

S4 chốt ba chỗ mức suy luận đi qua: body của `POST …/messages`/`…/retry`,
event `start` của SSE, và **cột này** — để chip "model · mức" dưới bong bóng
(T-S.15) vẫn đúng sau F5, khi stream đã hết TTL từ lâu, và để "Thử lại" không
chọn gì thì sinh lại đúng mức cũ.

**Cùng khuôn hai cột của T-3.7a (migration 0005):** `nullable`, không
`server_default`, một CHECK giữ giá trị trong bộ từ vựng. `NULL` là "lượt này
không gửi tham số suy luận nào" — model không khai khối `reasoning`
(`ol-qwen-small`, `grok-4.6`), hoặc hàng có từ trước migration này. 100% số
hàng đã có ở trạng thái ấy, nên `ALTER TABLE` không viết lại bảng.

**`TEXT` + `CHECK`, không ENUM** — S14 ghi `TEXT`, và khác 0005 có lý do: bộ từ
vựng `off · low · medium · high · xhigh · max` là **dữ liệu của catalog**
(`app/config/catalog.py::REASONING_LEVELS`), còn ENUM thì mỗi lần thêm một giá
trị là một `ALTER TYPE` không chạy được trong transaction. CHECK thì bỏ-rồi-tạo
lại trong cùng một migration.

**CHECK là lớp thứ hai, không phải lớp chính.** Handler đã từ chối mức model
không khai (`400 REASONING_UNSUPPORTED`), worker đã rơi về mức mặc định nếu
catalog đổi giữa chừng. CHECK canh đúng những đường **không** đi qua hai chỗ ấy
(psql tay, một migration sau này): một chuỗi rác trong cột này sẽ thành một
chip rác trên màn hình của người dùng.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

#: Bản sao ĐÔNG CỨNG của `catalog.REASONING_LEVELS` tại ngày 2026-09-24 — cùng
#: lý lẽ `_REASON_MAX_CHARS` của 0005: migration đã chạy phải mô tả đúng thứ nó
#: đã làm với database. `tests/db/test_reasoning_effort_column.py` canh hai chỗ
#: không lệch nhau.
_LEVELS = ("off", "low", "medium", "high", "xhigh", "max")

_CK_LEVEL = "ck_msg_reasoning_effort_level"


def upgrade() -> None:
    op.add_column("messages", sa.Column("reasoning_effort", sa.Text(), nullable=True))
    allowed = ", ".join(f"'{level}'" for level in _LEVELS)
    op.create_check_constraint(
        _CK_LEVEL,
        "messages",
        f"reasoning_effort IS NULL OR reasoning_effort IN ({allowed})",
    )


def downgrade() -> None:
    op.drop_constraint(_CK_LEVEL, "messages", type_="check")
    op.drop_column("messages", "reasoning_effort")
