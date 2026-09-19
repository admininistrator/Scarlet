"""users.default_model — model mặc định theo NGƯỜI, không theo hội thoại

KH tham chiếu: §18.4, §9.2, UC-05 · tasks.md T-3.0, B-206, NQ-79.

§18.4 hứa `GET/PUT /settings` với "theme, model mặc định, bật/tắt tính năng",
và UC-05 đòi model mặc định **nhớ theo người dùng**. Hôm nay chỉ có
`conversations.default_model` (theo một hội thoại), nên mở một hội thoại mới là
quay về model `default: true` của catalog — đúng thứ UC-05 nói là không được.

**Một cột trên `users`, không phải một bảng `user_settings`.** NQ-79 chốt "tối
thiểu": theme đã sống được bằng `localStorage` từ T-0.10, và phần thiếu thật
chỉ còn đúng một trường. Dựng sẵn một bảng khoá-giá trị cho những tuỳ chọn chưa
ai viết ra là đúng thứ L3 cấm; khi tuỳ chọn thứ ba xuất hiện thì bảng ấy vẫn
mở được, còn hôm nay nó chỉ là một JOIN không ai cần.

**Nullable, không `server_default`.** `NULL` mang một nghĩa riêng — "người này
chưa chọn gì" — khác hẳn "người này chọn đúng model đang là mặc định của
catalog": model `default: true` đổi được bất cứ lúc nào, và một giá trị chép
cứng lúc tạo tài khoản sẽ đóng băng người dùng ở model của ngày họ đăng ký.

**Không `FOREIGN KEY`.** Catalog là file JSON sửa nóng (§19.1,
`POST /admin/catalog/reload`), không phải bảng — xem docstring của
`app/db/models/user.py::User.default_model` cho chỗ phép kiểm thật sự đứng.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("default_model", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "default_model")
