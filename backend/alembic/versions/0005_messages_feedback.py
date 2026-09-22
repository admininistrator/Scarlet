"""messages.feedback + messages.feedback_reason — Like/Dislike của §18.2

KH tham chiếu: §18.2, §20 · tasks.md T-3.7a, B-207, NQ-80.

§18.2 hứa `POST /messages/{id}/feedback` ("`like` / `dislike` + lý do tuỳ
chọn") và UC-02 dòng 5 liệt hai nút ấy trong hàng nút bắt buộc dưới mỗi câu trả
lời. Đo 2026-09-20 (B-207): `grep -rn feedback backend/app` ra **0 dòng** —
không route, không schema, không cột. Migration này mở đường dữ liệu cho chúng.

**Hai cột trên `messages`, KHÔNG phải một bảng `message_feedback` riêng** —
NQ-80. Lý do là phép kiểm quyền: message thuộc một hội thoại, hội thoại lọc
`user_id` **trong câu SQL** (§20), nên hai cột dùng lại nguyên vẹn
`MessageRepository` và không sinh ra đường tra quyền thứ hai nào phải viết rồi
tự canh cho khớp với đường thứ nhất. Cái giá đã nhìn thấy và chấp nhận: ngày P8
mở share/fork thì câu *"ai đánh giá"* không trả lời được, vì hai cột này không
mang `user_id`.

**`message_feedback` là ENUM chứ không `TEXT` + `CHECK`** (T-3.7a cho chọn một
trong hai). Chính bảng này đã có hai cột enum — `role`, `status` — cùng đi qua
`pg_enum()` của `db/models/base.py`; một cột thứ ba dùng cơ chế khác là một cơ
chế nữa phải nhớ khi đọc. Enum cũng rẻ hơn cho bảng nóng nhất của app: 4 byte
cố định thay vì một chuỗi có độ dài thay đổi.

**Hai CHECK, và cả hai là luật chứ không phải trang trí:**

* `ck_msg_feedback_reason_len` — trần độ dài của một trường **tự do** đi vào
  bảng mà **mọi** truy vấn đường đi (§8.3, recursive CTE) đều kéo về. Cạm bẫy ①
  của T-3.7a gọi đích danh nó. Con số sống ở
  `app/config/settings.py::FEEDBACK_REASON_MAX_CHARS` (A3) và DDL này là chỗ
  thứ hai nó xuất hiện — migration đã chạy thì không sửa lại được, nên nó phải
  là một literal ở đây. `tests/api/test_feedback.py` có một ca đâm **thẳng**
  vào DB với `max + 1` ký tự để hai chỗ ấy không lệch nhau trong im lặng: lệch
  theo chiều nới hằng số Python ra thì một `422` sẽ biến thành `500`.
* `ck_msg_feedback_reason_needs_value` — một lý do mà không có đánh giá là một
  hàng không đọc được: gỡ Like mà để lại câu "trả lời sai" thì lần đọc sau
  không biết nó nói về cái gì. Endpoint ghi **cả hai** cột trong một câu UPDATE
  nên nó không tạo ra hàng như vậy; CHECK này canh đúng những đường **không**
  đi qua endpoint (psql tay, một migration sau này, một worker tương lai).

Cả hai cột `nullable` và không `server_default`: `NULL` là "chưa ai bấm gì",
khác hẳn một giá trị mặc định nào đó — và 100% số hàng `messages` đã có sẽ ở
trạng thái ấy, nên `ALTER TABLE` này không viết lại bảng.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

#: Bản sao ĐÔNG CỨNG của `settings.FEEDBACK_REASON_MAX_CHARS` tại ngày
#: 2026-09-22. Không `import` từ `app.config`: một migration đã chạy phải mô tả
#: đúng thứ nó đã làm với database, còn hằng số trong app thì đổi được bất cứ
#: lúc nào — đọc nó từ đây sẽ khiến `downgrade` của hôm nay dựng lại một
#: constraint khác với constraint của hôm qua.
_REASON_MAX_CHARS = 2000

_CK_LEN = "ck_msg_feedback_reason_len"
_CK_NEEDS_VALUE = "ck_msg_feedback_reason_needs_value"


def upgrade() -> None:
    op.execute("CREATE TYPE message_feedback AS ENUM ('like','dislike')")
    op.add_column(
        "messages",
        sa.Column(
            "feedback",
            # `create_type=False`: kiểu vừa được tạo ngay ở trên bằng DDL
            # tường minh, đúng lối `0001_initial` đã dùng cho `message_role` và
            # `message_status`. Không có cờ này, SQLAlchemy phát thêm một
            # `CREATE TYPE` thứ hai và `ALTER TABLE` đổ vì "type already
            # exists".
            postgresql.ENUM(name="message_feedback", create_type=False),
            nullable=True,
        ),
    )
    op.add_column("messages", sa.Column("feedback_reason", sa.Text(), nullable=True))
    op.create_check_constraint(
        _CK_LEN,
        "messages",
        f"feedback_reason IS NULL OR char_length(feedback_reason) <= {_REASON_MAX_CHARS}",
    )
    op.create_check_constraint(
        _CK_NEEDS_VALUE,
        "messages",
        "feedback IS NOT NULL OR feedback_reason IS NULL",
    )


def downgrade() -> None:
    # Ngược đúng thứ tự upgrade. `DROP TYPE` phải đứng SAU `drop_column`:
    # Postgres từ chối xoá một kiểu còn cột nào dùng tới.
    op.drop_constraint(_CK_NEEDS_VALUE, "messages", type_="check")
    op.drop_constraint(_CK_LEN, "messages", type_="check")
    op.drop_column("messages", "feedback_reason")
    op.drop_column("messages", "feedback")
    op.execute("DROP TYPE message_feedback")
