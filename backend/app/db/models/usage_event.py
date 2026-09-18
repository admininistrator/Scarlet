"""Bảng `usage_events` (KH Phụ lục A, §10.2, §17.2) — T-2.12.

Đây là **sổ cái**: mỗi lượt gọi model một dòng, và dòng đó không bao giờ được
sửa lại. A7 viết ra đúng điều đó — *"chi phí snapshot vào `usage_events` tại
thời điểm gọi; đổi giá trong catalog KHÔNG được làm đổi lịch sử"* — và cột
`price_snapshot` là cách bảng này giữ lời hứa ấy: giá của hôm nay nằm **trong
hàng**, không phải ở một chỗ mà ngày mai ai đó sửa.

Cũng như `tier.py`, model này cố ý không có một dòng logic nào. Phần "một lượt
sinh tốn bao nhiêu" sống ở `app/quota/meter.py`.

**Hai cột dưới đây là TEXT + CHECK chứ không phải kiểu ENUM của Postgres** (khác
`messages.status`), đúng theo Phụ lục A. Vì vậy hai `StrEnum` ở đây ánh xạ sang
`Text`, không qua `pg_enum()`: chúng là hợp đồng của **tầng app** với một ràng
buộc CHECK, không phải một kiểu do migration tạo.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import ForeignKey, Integer, Numeric, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class KeySource(StrEnum):
    """Credential nào đã trả tiền cho lượt gọi này — §10.5, §17.2.

    Quyết định **có trừ quota hay không**: `system` trừ, `byok` không trừ
    nhưng vẫn ghi một dòng ở đây để người dùng tự xem chi tiêu của mình.
    Phase 2 tới T-2.12 thì mọi request đều là `system` (đường BYOK ra đời ở
    T-2.14/T-2.15) — nhưng cột vẫn được ghi **tường minh** thay vì dựa vào
    `DEFAULT` của DDL, vì ngày BYOK bật lên thì chỗ quên điền sẽ là một dòng
    `system` sai, tức một lần trừ quota cho tiền của người khác.
    """

    SYSTEM = "system"
    BYOK = "byok"


class CostConfidence(StrEnum):
    """Con số `cost_usd` của dòng này đáng tin tới đâu — §9.5, §17.2, C16.

    `exact` chỉ khi **cả hai** điều kiện đúng: provider báo chi phí đáng tin
    (`pricing_mode='metered'`, §9.5) **và** số token là số provider gửi về.
    Thiếu một trong hai là `low`:

    * Model đi qua 9Router — nó tự fallback sang tier khác nên model trả lời có
      thể không phải model đã yêu cầu, và token báo về có thể đã bị RTK nén
      (§9.5). Giá trong catalog vì vậy **sai**, chỉ là ước lượng.
    * Provider **không** báo `usage` (C40, B-67), hoặc mình bỏ stream trước khi
      họ kịp báo (huỷ giữa chừng, B-94). Số token khi đó do `tiktoken` đếm —
      xấp xỉ, và xấp xỉ bằng bộ tách từ của một hãng khác.

    C16 nói thẳng vì sao cột này phải tồn tại ở **tầng dữ liệu**: *"trộn chung
    model `metered` và `unmetered` vào một con số làm bảng chi phí vô nghĩa —
    phải tách từ đây, không phải sửa ở tầng hiển thị"*. Tiêu chí S13 (đối chiếu
    với hoá đơn provider) chỉ áp cho những dòng `exact`.
    """

    EXACT = "exact"
    LOW = "low"


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    #: `ON DELETE SET NULL`, KHÔNG phải `CASCADE` (Phụ lục A): xoá một message
    #: là xoá một câu trả lời, không phải xoá một khoản tiền đã tiêu. Dòng sổ
    #: ở lại và chỉ mất con trỏ về message.
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    #: `id` trong catalog (§9.2), cùng giá trị với `messages.model_id`.
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    key_source: Mapped[KeySource] = mapped_column(Text, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    completion_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    #: Phần `prompt_tokens` trúng cache của provider. Là một **tập con** của
    #: `prompt_tokens`, không phải một khoản cộng thêm — xem `meter.cost_of`.
    cached_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    #: `NUMERIC(12,6)` ⇒ `Decimal`, cùng lý lẽ với `tiers.limit_5h_usd`: đây là
    #: tiền, và `float` cộng dồn qua vài nghìn dòng thì sai số nhị phân bò vào
    #: đúng con số A7 nói phải chốt được.
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, server_default=text("0")
    )
    cost_confidence: Mapped[CostConfidence] = mapped_column(
        Text, nullable=False, server_default=text("'exact'")
    )
    #: A7 — bảng giá đang có hiệu lực **tại thời điểm gọi**, đóng băng vào hàng.
    #: Hình dạng do `app/quota/meter.py::snapshot_of` quyết định.
    price_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    #: §9.5 — model **thật sự** đã trả lời, khi gateway báo. Hôm nay **luôn
    #: NULL**: 9Router không trả header nào, và tên thật nó ghi trong body bị
    #: LiteLLM ghi đè bằng alias trước khi backend nhìn thấy. Đo và chốt ở
    #: B-32; cột giữ lại vì ngày có gateway nào chịu khai thì đây là chỗ ghi.
    upstream_model_reported: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"UsageEvent(id={self.id!r}, model_id={self.model_id!r}, "
            f"cost_usd={self.cost_usd!r}, cost_confidence={self.cost_confidence!r})"
        )
