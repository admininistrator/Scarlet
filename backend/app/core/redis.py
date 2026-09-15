"""Kết nối Redis dùng chung cho tiến trình `api` (§7.3, §23).

KH tham chiếu: §7.2 ②, §7.3, C5 · CLAUDE.md A4.

Đối xứng với `app/db/session.py`: **dựng lười, dùng chung, đóng khi shutdown**.
Ba lý do cụ thể cho Redis, khác với lý do của Postgres:

1. **Một SSE đang `XREAD BLOCK` giữ một kết nối suốt thời gian chờ.** Mở một
   `Redis.from_url()` mới cho mỗi request — như `core/health_checks.py` đang
   làm, ở đó đúng vì nó gọi một lệnh rồi thôi — nghĩa là mỗi tab chat mở một
   kết nối TCP riêng và không ai đóng nó khi client biến mất giữa chừng.
2. **Pool gắn với event loop.** Dựng lúc import thì nó gắn vào loop nào đang
   chạy khi đó, chưa chắc là loop của uvicorn. Cùng cái bẫy đã ghi trong
   `db/session.py`.
3. **`decode_responses=True`.** Consumer ghép chuỗi SSE, nên nó muốn `str`.
   Producer (worker) thì ngược lại — nó nhận pool của arq, vốn trả `bytes`, và
   `emit()` tự `.decode()`. Hai tiến trình, hai cấu hình, và đó là lý do khoá
   này nằm ở `core/` chứ không nằm trong `streaming/producer.py`.

**`socket_timeout` cố ý KHÔNG đặt.** `XREAD BLOCK 15000` im lặng đúng 15 giây
theo thiết kế; một `socket_timeout` nhỏ hơn sẽ biến nhịp thở bình thường thành
`TimeoutError` mỗi 15 giây.
"""

from __future__ import annotations

from redis.asyncio import Redis

from app.config.settings import settings

_client: Redis | None = None


def get_redis() -> Redis:
    """Client dùng chung của tiến trình. Dựng ở lần gọi đầu tiên."""
    global _client
    if _client is None:
        _client = Redis.from_url(str(settings.REDIS_URL), decode_responses=True)
    return _client


async def dispose_redis() -> None:
    """Đóng pool. `main.py` gọi lúc shutdown; test gọi khi đổi client."""
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None
