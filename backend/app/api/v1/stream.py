"""`GET /api/v1/messages/{id}/stream` — SSE của §7.2 ② (§18.2, §23 `stream.py`).

KH tham chiếu: §7.2 ②, §7.3, §7.4, §18.2, §20, C1, C2 · CLAUDE.md A1, A2.

Router mỏng có chủ ý. Toàn bộ phần khó — thứ tự `XRANGE` rồi `XREAD`, cursor,
nhịp `: ping`, đường dựng lại từ Postgres — nằm ở `app/streaming/consumer.py`,
nơi nó kiểm được mà không cần dựng một HTTP client. Ở đây chỉ có ba việc:

    ① kiểm quyền sở hữu (§20) → 404
    ② đọc MỘT LẦN những gì Postgres biết, rồi ĐÓNG session
    ③ giao phần còn lại cho `StreamConsumer`, chỉ còn chạm Redis

**A1 sống ở đây.** Handler này không gọi model, không enqueue gì, không ghi gì.
Nó đọc một hàng của bảng `messages` rồi chuyển tiếp những byte mà worker đã
ghi vào Redis. Sinh chữ là việc của `app/workers/generate.py`.

**Vì sao KHÔNG dùng `Depends(get_session)`.** Dependency kiểu `yield` của
FastAPI chỉ được đóng **sau khi response đã gửi xong**, mà với
`StreamingResponse` thì "xong" nghĩa là sau khi model ngừng sinh — có thể mười
phút. Một kết nối Postgres nằm không suốt một lượt chat là cách nhanh nhất làm
cạn pool khi vài người cùng dùng. `session_scope()` mở và đóng ngay trong
handler; generator phía sau chỉ còn giữ Redis.

**404 chứ không 403 (§20).** "Không tồn tại", "đã xoá mềm" và "của người khác"
trả về cùng một câu — 403 cho ca thứ ba là xác nhận với người hỏi rằng
`message_id` đó có thật.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status
from fastapi.responses import StreamingResponse

from app.config.settings import settings
from app.core.deps import get_current_user_id
from app.core.errors import ApiError, ApiErrorCode
from app.core.redis import get_redis
from app.db.repositories import MessageRepository
from app.db.session import session_scope
from app.streaming.consumer import (
    SSE_HEADERS,
    CursorKhongHopLe,
    MessageSnapshot,
    StreamConsumer,
    doc_cursor,
)

router = APIRouter(tags=["stream"])


@router.get(
    "/messages/{message_id}/stream",
    response_class=StreamingResponse,
    responses={
        200: {"content": {"text/event-stream": {}}, "description": "Dong event SSE cua §7.4"},
        400: {"description": "Last-Event-ID / cursor khong phai Redis Stream ID"},
        404: {"description": "Message khong ton tai, da xoa, hoac cua nguoi khac"},
    },
)
async def stream_message(
    message_id: uuid.UUID,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    cursor: Annotated[str | None, Query(description="Redis Stream ID, mac dinh 0")] = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    """Phát lại phần đã sinh rồi nối tiếp phần đang sinh, từ `cursor` trở đi.

    Đường dẫn phải khớp `location ~ ^/api/v1/(messages/[^/]+/stream|_debug/sse)$`
    trong `config/nginx/nginx.conf` — đó là location duy nhất có
    `proxy_buffering off` (C1) và `proxy_read_timeout 3600s` (C2). Đổi đường
    dẫn ở đây mà quên file kia thì stream **vẫn chạy**, chỉ là im lặng rồi trả
    một cục khi xong; triệu chứng đó rất dễ bị đọc nhầm thành "model chậm".
    """
    try:
        vi_tri = doc_cursor(last_event_id, cursor)
    except CursorKhongHopLe as loi:
        raise ApiError(status.HTTP_400_BAD_REQUEST, ApiErrorCode.CURSOR_INVALID, str(loi)) from loi

    async with session_scope() as session:
        message = await MessageRepository(session).get_message(message_id, user_id=user_id)
        if message is None:
            raise ApiError(
                status.HTTP_404_NOT_FOUND,
                ApiErrorCode.MESSAGE_NOT_FOUND,
                "khong tim thay message",
            )
        snapshot = MessageSnapshot.from_message(message)

    consumer = StreamConsumer(get_redis(), snapshot, heartbeat_s=settings.STREAM_HEARTBEAT_S)
    return StreamingResponse(
        consumer.frames(vi_tri),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
