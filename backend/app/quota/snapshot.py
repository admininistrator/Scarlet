"""Bản chụp quota của MỘT người, để HIỂN THỊ — `GET /auth/me` (§18.1, §10.3).

KH tham chiếu: §18.1, §10.3, §10.4, UC-07 · CLAUDE.md A3, A7 · tasks.md T-3.0,
B-158, NQ-81.

§18.1 tả `/auth/me` là *"User + tier + quota còn lại + trạng thái"*, và UC-07
dòng 2 đòi FE **vô hiệu hoá nút gửi** khi hết quota 5 giờ cùng **thời điểm
chính xác** quota được hoàn lại. Cả hai mảnh cần thiết đã có từ T-2.11 —
`quota.tiers.get_effective_limits` (hạn mức đã gộp ghi đè) và
`quota.windows.read_window` (đã tiêu + `retry_after`) — nên file này là chỗ
**ghép** chúng lại, không phải chỗ dựng thêm gì.

╔══════════════════════════════════════════════════════════════════════════╗
║  ĐÂY LÀ MỘT Ô CỬA SỔ, KHÔNG PHẢI MỘT CÁNH CỬA                            ║
╚══════════════════════════════════════════════════════════════════════════╝

`quota/estimator.py::check_quota` và file này đọc **cùng** hai ZSET, nhưng
chúng trả lời hai câu khác nhau và vì thế hỏng theo hai kiểu khác nhau:

- `check_quota` đứng trước một lượt tiêu tiền. Không đọc được Redis ⇒ `503`:
  cho qua một lượt sinh mà không biết người ta còn bao nhiêu tiền là đúng thứ
  §10.2 dựng cửa ấy để chặn.
- File này chỉ vẽ một thanh trên màn hình. Không đọc được Redis ⇒ `None` và
  một dòng WARNING: `/auth/me` còn là endpoint mà FE dùng để **định tuyến**
  (§11.1, T-3.1b), nên một lần Redis chớp mắt không được phép khoá cả giao
  diện vì một thanh quota không vẽ được.

Hệ quả cho FE: `quota` là **nullable**. `null` nghĩa là "chưa đo được lúc
này", không phải "không có hạn mức" — ẩn thanh đi, đừng hiện 0.

╔══════════════════════════════════════════════════════════════════════════╗
║  `retry_after` Ở ĐÂY VÀ `Retry-After` CỦA `429` LÀ CÙNG MỘT PHÉP TÍNH     ║
╚══════════════════════════════════════════════════════════════════════════╝

Cả hai đi qua đúng `WindowState.retry_after_s` của §10.3, chỉ khác **lượng cần
nhả**:

    429 (estimator):  need_to_free = spent + est_max − limit
    /auth/me (đây):   need_to_free = spent − limit

Khác đúng một số hạng `est_max`, và nó vắng mặt ở đây vì có lý do: `/auth/me`
không biết người dùng sắp gõ gì bằng model nào, nên dự toán một lượt sinh chưa
tồn tại là bịa. Câu hỏi file này trả lời hẹp hơn và trả lời được: *"bao lâu
nữa thì phần đã tiêu tụt xuống dưới hạn mức"*.

`None` **chỉ** khi `spent ≤ limit` — chưa vượt thì không có gì để chờ. Ca `None`
thứ hai của `retry_after_s` ("nhả hết cả cửa sổ vẫn không đủ") không với tới
đường này: `need_to_free = spent − limit ≤ spent`, mà tổng của cả cửa sổ **bằng**
`spent`, nên phép cộng dồn luôn tới đích. Hễ `/auth/me` báo hết quota thì nó
luôn nói được lúc nào hết "hết" — khác `429`, nơi `est_max` có thể đẩy
`need_to_free` vượt quá cả cửa sổ và `Retry-After` cố ý vắng mặt.
"""

from __future__ import annotations

import logging
import time
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.quota.rebuild import refill_if_empty
from app.quota.tiers import get_effective_limits
from app.quota.windows import LimitType, read_window, windows

logger = logging.getLogger(__name__)


class WindowSnapshot(BaseModel):
    """Một cửa sổ trượt của §10.3 nhìn từ màn hình người dùng.

    Bốn con số tiền đều là `Decimal`, và pydantic serialise `Decimal` thành
    **chuỗi** JSON — cùng luật `cost_usd` đã đi từ Postgres tới FE từ T-2.16.
    Một `float` ở đây là `0.30000000000000004` trong một thanh quota, và tệ hơn
    là hai máy khác nhau làm tròn khác nhau trên cùng một con số.

    Hình dạng cố ý **trùng** `estimator.QuotaWarning` ở năm trường đầu: FE đã
    dựng một thanh cho `quota_warning` trong `202`, và bắt nó dựng thanh thứ
    hai bằng một bộ tên khác là mời hai thanh lệch nhau.
    """

    model_config = ConfigDict(extra="forbid")

    limit_type: LimitType
    limit_usd: Decimal
    spent_usd: Decimal
    #: `max(0, limit − spent)` — không bao giờ âm. Một số âm ở đây đúng về số
    #: học (vượt trần là tiêu quá) nhưng vô nghĩa với một thanh tiến trình, và
    #: FE sẽ phải tự kẹp lại — tức luật kẹp sống ở hai nơi.
    remaining_usd: Decimal
    #: Phần trăm còn lại, làm tròn **xuống**, đúng luật `QuotaWarning`: con số
    #: hiển thị không bao giờ được lạc quan hơn sự thật. `0` khi hạn mức là 0.
    remaining_pct: int
    #: Giây cho tới khi phần đã tiêu tụt xuống dưới hạn mức, hoặc `None` — xem
    #: docstring module. Cùng đơn vị và cùng phép tính với header `Retry-After`
    #: của `429 QUOTA_EXCEEDED`.
    retry_after: int | None


async def read_snapshot(
    session: AsyncSession, *, user_id: uuid.UUID
) -> list[WindowSnapshot] | None:
    """Hai cửa sổ của §10.3, theo đúng thứ tự `windows()` (5 giờ trước).

    `None` = không đọc được Redis. Đó là một câu trả lời, không phải một lỗi —
    xem docstring module.

    `refill_if_empty` chạy ở đây y như trong `check_quota` (RR-7): một cửa sổ
    rỗng có hai nghĩa ("chưa tiêu gì" và "Redis vừa mất dữ liệu") và chỉ
    Postgres phân biệt được. Bỏ bước ấy thì thanh quota hiện 0 cho tới khi
    người dùng bấm Gửi lần đầu, rồi nhảy vọt — hai endpoint đọc cùng một cửa
    sổ phải ra cùng một con số.
    """
    limits = await get_effective_limits(user_id)
    now = time.time()
    redis = get_redis()

    out: list[WindowSnapshot] = []
    for window in windows():
        try:
            state = await read_window(redis, window, user_id=user_id, now=now)
            state = await refill_if_empty(session, redis, state, user_id=user_id, now=now)
        except Exception:
            logger.warning(
                "khong doc duoc cua so quota %s cua user %s — /auth/me tra quota=null",
                window.limit_type.value,
                user_id,
                exc_info=True,
            )
            return None

        limit = limits.for_window(window)
        remaining = max(Decimal(0), limit - state.spent)
        out.append(
            WindowSnapshot(
                limit_type=window.limit_type,
                limit_usd=limit,
                spent_usd=state.spent,
                remaining_usd=remaining,
                remaining_pct=int(remaining * 100 / limit) if limit > 0 else 0,
                retry_after=state.retry_after_s(need_to_free=state.spent - limit, now=now),
            )
        )
    return out
