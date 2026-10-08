"""Bộ đếm lượt `web_search` mỗi user — cửa sổ trượt 24 h (§12.4, lối §10.3) — T-6.8.

KH tham chiếu: §12.4 ("cộng một bộ đếm ngày"), §10.3, §10.4 · NQ-144 ①.

ZSET `web:{user_id}`, score = epoch lúc gọi, member ngẫu nhiên (hai lượt cùng
giây không đè nhau). Dọn phần quá hạn trước mỗi lần đọc, như `read_window`.
Trần (`web_searches_per_day`) do người gọi đưa vào — đọc qua
`get_effective_limits` lúc gọi (B-153), không đọc ở đây.

"Ngày" là 24 h trượt, không phải ngày lịch (NQ-144 ①: không cần chốt múi giờ),
nên độ dài cửa sổ là định nghĩa của chính tên trường, không phải cấu hình.
"""

from __future__ import annotations

import math
import uuid

from app.core.redis import get_redis

WEB_PREFIX = "web:"
DAY_S = 24 * 60 * 60


def _key(user_id: uuid.UUID) -> str:
    return f"{WEB_PREFIX}{user_id}"


async def searches_in_window(user_id: uuid.UUID, *, now: float) -> list[float]:
    """Score (epoch) các lượt còn trong 24 h, cũ trước. Ngoại lệ Redis không bị nuốt."""
    redis = get_redis()
    key = _key(user_id)
    cutoff = now - DAY_S
    await redis.zremrangebyscore(key, "-inf", f"({cutoff}")
    return [score for _, score in await redis.zrangebyscore(key, cutoff, "+inf", withscores=True)]


async def take_search(user_id: uuid.UUID, *, limit: int, now: float) -> float | None:
    """Còn lượt ⇒ ghi một lượt, trả `None`. Hết ⇒ không ghi, trả epoch có lại một lượt.

    `limit = 0` ⇒ `math.inf` (không bao giờ có lại).
    """
    # ponytail: đếm-rồi-ghi không nguyên tử — hai lời gọi song song có thể vượt
    # trần một lượt (cùng hình B-331); chấp nhận với 15–20 người, muốn chặt thì Lua.
    scores = await searches_in_window(user_id, now=now)
    if len(scores) >= limit:
        return scores[len(scores) - limit] + DAY_S if limit > 0 else math.inf
    redis = get_redis()
    key = _key(user_id)
    await redis.zadd(key, {uuid.uuid4().hex: now})
    await redis.expire(key, DAY_S)
    return None
