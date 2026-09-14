"""messages.created_at dùng clock_timestamp() thay cho now()

KH tham chiếu: §8.3, §17.2, Phụ lục A · tasks.md B-53, NQ-18.

`now()` của Postgres là bí danh của `transaction_timestamp()`: một hằng số
suốt cả giao dịch. Mọi message ghi trong CÙNG một transaction vì thế mang
`created_at` **bằng nhau**, và `ORDER BY created_at` của §8.3 — dùng cho cả
đường đi lẫn `sibling_index`/`sibling_count` — không sắp được chúng. Đó đúng
là chỗ C13 nói tới: FE hiện sai số nhánh `‹ n/m ›`.

Đo trên chính Postgres 17 của dự án, trong một transaction:

    now()             · 3 INSERT rời rạc → 1 giá trị khác nhau
    clock_timestamp() · 3 INSERT rời rạc → 3 giá trị khác nhau

`clock_timestamp()` đọc đồng hồ tại thời điểm chạy, nên nó chính là thứ tên
cột `created_at` vẫn tự nhận. Đổi DEFAULT là thao tác **metadata**, không viết
lại bảng và không đụng dòng dữ liệu nào đã có.

Chỉ đổi cho `messages`: đây là bảng duy nhất ở v1 mà thứ tự giữa các dòng sinh
trong cùng một giao dịch mang ý nghĩa nghiệp vụ (cây hội thoại, §8). Các bảng
khác giữ `now()` — xem B-57 nếu về sau có bảng thứ hai cần tính chất này.

Vẫn còn một khe hở đã biết, KHÔNG đóng ở đây: `clock_timestamp()` có độ phân
giải micro-giây, nên một câu `INSERT ... SELECT generate_series(...)` ghi hàng
trăm dòng một lúc vẫn tạo ra giá trị trùng (đo được: 500 dòng → 88 giá trị).
Vì vậy mọi truy vấn cây phải sắp `ORDER BY created_at, id` — khoá phụ `id`
không cho biết thứ tự tạo, nhưng làm kết quả **xác định**. Ứng dụng không bao
giờ ghi message bằng bulk insert: mỗi message là một INSERT trong request của
chính nó.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-14
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE messages ALTER COLUMN created_at SET DEFAULT clock_timestamp()")


def downgrade() -> None:
    op.execute("ALTER TABLE messages ALTER COLUMN created_at SET DEFAULT now()")
