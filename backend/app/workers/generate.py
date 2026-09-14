"""Job `generate` — KHUNG của T-1.5. Chưa sinh chữ; T-1.6 làm phần đó.

KH tham chiếu: §7.2 bước ③, §5.2 (hàng `worker`), ADR-02 · CLAUDE.md A1.

Đây là chỗ mà A1 chỉ tới: HTTP handler của §7.2 bước ① chỉ `INSERT` hai
message rồi `enqueue('generate', assistant_message_id)` và trả `202`; toàn bộ
phần đợi model nằm trong hàm dưới đây. Hôm nay hàm mới chỉ nhận `message_id`
và ghi log — T-1.6 thay thân hàm bằng đúng dãy bước của §7.2 ③ (dựng ngữ cảnh
bằng `app/llm/context.py` → `UPDATE status='streaming'` → `XADD` từng delta →
ghi Postgres → `XADD type=done` → `EXPIRE stream:{id}`).

**Vì sao job này không bao giờ được chạy lần thứ hai.** `max_tries=1` đặt ở
`main.py`, và nó là một quyết định về *tiền*, không phải về độ bền: một lượt
sinh đã chạm model là đã có hoá đơn. arq mặc định thử lại **5** lần, nên để
nguyên mặc định nghĩa là một job chết ở giây thứ 200 sẽ trả tiền thêm bốn lần
nữa cho cùng một câu hỏi, và người dùng nhận bốn câu trả lời khác nhau dán
chồng lên cùng một `message_id`. Job chết giữa chừng là việc của reaper §7.6
(đánh `status='failed'`, `error_code='WORKER_LOST'`), không phải việc của hàng
đợi.

**Hàm nhận `message_id` chứ không nhận nội dung câu hỏi.** §7.2 ① đã ghi cả
hai message xuống Postgres trước khi enqueue, nên payload của job chỉ cần một
khoá chính. Nhét nội dung vào payload sẽ tạo nguồn sự thật thứ hai nằm trong
Redis — đúng thứ C5 cấm — và làm hàng đợi phình theo độ dài hội thoại.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

#: Khoảng lặng giả, CHỈ để cái khung quan sát được: một job xong tức thì thì
#: không có "giữa job" nào để mà giết, tức DoD thứ ba của T-1.5 không chạy
#: được. **T-1.6 xoá dòng `asyncio.sleep` dùng hằng này** và thay bằng vòng
#: lặp stream thật. Không đưa vào `Settings` vì nó không phải một tham số vận
#: hành — nó là chỗ trống chờ code, và một biến môi trường cho chỗ trống thì
#: sẽ sống lâu hơn chỗ trống.
PLACEHOLDER_HOLD_S = 30


async def generate(ctx: dict[str, Any], message_id: str) -> None:
    """Khung của lượt sinh. Ghi log, giữ job đủ lâu để quan sát, rồi thoát.

    `ctx` là dict của arq: `ctx["redis"]` là `ArqRedis` dùng chung của worker,
    `ctx["job_id"]`/`ctx["job_try"]` là danh tính lượt thử này. `job_try` in ra
    đây là bằng chứng của `max_tries=1`: nó **không bao giờ** được lớn hơn 1
    trong log, vì lần thử thứ hai bị arq chặn trước khi gọi tới hàm này.
    """
    logger.info(
        "generate: nhận job %s cho message %s (job_try=%s) — T-1.5 mới là khung, chưa sinh chữ",
        ctx.get("job_id"),
        message_id,
        ctx.get("job_try"),
    )
    await asyncio.sleep(PLACEHOLDER_HOLD_S)
    logger.info("generate: kết thúc khung cho message %s", message_id)
