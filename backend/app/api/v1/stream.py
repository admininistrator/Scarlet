"""Hai endpoint SSE: câu trả lời (§7.2 ②) và tiêu đề hội thoại (§24.2b·S6).

    GET /api/v1/messages/{id}/stream              §7.2 ②, §18.2 — T-1.7
    GET /api/v1/conversations/{id}/title/stream   §24.2b·S6, S14 — T-S.7

KH tham chiếu: §7.2 ②, §7.3, §7.4, §18.2, §20, §24.2b·S6, C1, C2 · CLAUDE.md
A1, A2.

**Cả hai dùng ĐÚNG một consumer** (`StreamConsumer`, §7.3) — S6 viết thẳng
"dùng lại đúng consumer của §7.3". Khác nhau ở khoá Redis và ở thứ Postgres biết
khi stream đã hết TTL (`MessageSnapshot` / `TitleSnapshot`), không ở cách đọc.

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
from app.core.queue import title_job_pending
from app.core.redis import get_redis
from app.db.repositories import ConversationRepository, MessageRepository
from app.db.session import session_scope
from app.streaming.consumer import (
    SSE_HEADERS,
    InvalidCursor,
    MessageSnapshot,
    StreamConsumer,
    TitleSnapshot,
    parse_cursor,
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

    Đường dẫn phải khớp location SSE `location ~ ^/api/v1/(messages/[^/]+/stream|…)$`
    trong `config/nginx/nginx.conf` — đó là location duy nhất có
    `proxy_buffering off` (C1) và `proxy_read_timeout 3600s` (C2). Đổi đường
    dẫn ở đây mà quên file kia thì stream **vẫn chạy**, chỉ là im lặng rồi trả
    một cục khi xong; triệu chứng đó rất dễ bị đọc nhầm thành "model chậm".
    """
    try:
        position = parse_cursor(last_event_id, cursor)
    except InvalidCursor as exc:
        raise ApiError(status.HTTP_400_BAD_REQUEST, ApiErrorCode.CURSOR_INVALID, str(exc)) from exc

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
        consumer.frames(position),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.get(
    "/conversations/{conversation_id}/title/stream",
    response_class=StreamingResponse,
    responses={
        200: {"content": {"text/event-stream": {}}, "description": "start/delta/done|error"},
        400: {"description": "Last-Event-ID / cursor khong phai Redis Stream ID"},
        404: {"description": "Hoi thoai khong ton tai, da xoa, hoac cua nguoi khac"},
    },
)
async def stream_title(
    conversation_id: uuid.UUID,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    cursor: Annotated[str | None, Query(description="Redis Stream ID, mac dinh 0")] = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    """Tiêu đề hội thoại chảy từng mảnh — `stream:title:{id}` (§24.2b·S6, T-S.7).

    Ba bước như `stream_message`, cộng một câu hỏi hàng đợi:

        ① kiểm quyền sở hữu TRONG câu SQL (§20) → 404, kể cả IDOR
        ② đọc `conversations.title` MỘT LẦN rồi đóng session
        ②bis tiêu đề còn `NULL` ⇒ hỏi job `title` còn chờ/chạy không
        ③ giao phần còn lại cho `StreamConsumer`

    Bước ②bis là thứ duy nhất stream này có mà stream câu trả lời không: một
    message luôn có `status` để nói "còn chữ sẽ tới", còn tiêu đề `NULL` thì
    không phân biệt được "job chưa kịp bắt đầu" với "không còn lượt nào" — xem
    `core/queue.py::title_job_pending`. Hỏi sau khi session đã đóng: nó là một
    vòng Redis, không cần giữ kết nối Postgres.

    FE mở đường này **sau** khi `POST …/messages` trả `202` (lúc ấy job đã nằm
    trong hàng đợi): mở trước đó thì tiêu đề `NULL` + không job ⇒ `error`
    `JOB_LOST` ngay.

    Đường dẫn phải khớp location SSE của `config/nginx/nginx.conf` — cùng lời
    dặn với `stream_message` (C1, Cạm bẫy ③ của T-S.7).
    """
    try:
        position = parse_cursor(last_event_id, cursor)
    except InvalidCursor as exc:
        raise ApiError(status.HTTP_400_BAD_REQUEST, ApiErrorCode.CURSOR_INVALID, str(exc)) from exc

    async with session_scope() as session:
        conversation = await ConversationRepository(session).get_conversation(
            conversation_id, user_id=user_id
        )
        if conversation is None:
            # §20: "không có", "đã xoá" và "của người khác" trả cùng một câu.
            raise ApiError(
                status.HTTP_404_NOT_FOUND,
                ApiErrorCode.CONVERSATION_NOT_FOUND,
                "khong tim thay hoi thoai",
            )
        title = conversation.title

    snapshot = TitleSnapshot(
        conversation_id=conversation_id,
        title=title,
        job_pending=title is None and await title_job_pending(conversation_id),
    )
    consumer = StreamConsumer(get_redis(), snapshot, heartbeat_s=settings.STREAM_HEARTBEAT_S)
    return StreamingResponse(
        consumer.frames(position),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
