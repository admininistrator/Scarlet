"""Phát một refresh token cho `make test-artifact-origin` (T-5.6, S12; T-5.5).

Chạy TRONG container `api` (`docker compose exec -T api python - < file`):
host `.venv` thiếu biến `.env` (A4). In một dòng JSON ra stdout — Makefile nối
thẳng vào stdin của `scripts/test_artifact_origin.mjs`, token không qua argv
hay biến môi trường.

Không mật khẩu, không `POST /auth/login` ⇒ `last_login_at` không đổi (NQ-125).
Script Node gọi `/auth/refresh` để có cookie phiên, rồi `/auth/logout` ở cuối
⇒ cả family bị thu hồi.

T-5.5: S12 thăm dò iframe DO PANEL DỰNG, nên cần một hội thoại có thẻ artifact
`html` để bấm "Mở". Chọn artifact `html` có tiêu đề, mới nhất, nằm trên ĐƯỜNG ĐI
đang mở (đi từ `active_leaf_id` ngược lên gốc — A2: thẻ chỉ hiện cho message
trên đường đi) của một hội thoại chưa xoá, chủ còn `active`. Người dùng là chủ
hội thoại ấy — phép đối chứng cũng cần danh sách hội thoại không rỗng.
"""

import asyncio
import json

from sqlalchemy import text

from app.config.settings import settings
from app.db.repositories.refresh_tokens import RefreshTokenRepository
from app.db.session import session_scope

_NEWEST_HTML_ON_PATH = text(
    """
    WITH RECURSIVE path AS (
        SELECT c.id AS conversation_id, m.id, m.parent_id
        FROM conversations c
        JOIN users u ON u.id = c.user_id
        JOIN messages m ON m.id = c.active_leaf_id
        WHERE c.deleted_at IS NULL AND u.deleted_at IS NULL AND u.status = 'active'
        UNION ALL
        SELECT p.conversation_id, m.id, m.parent_id
        FROM messages m
        JOIN path p ON m.id = p.parent_id
    )
    SELECT c.user_id, c.id AS conversation_id, a.title, a.version
    FROM path p
    JOIN messages m ON m.id = p.id AND m.deleted_at IS NULL
    JOIN artifacts a ON a.message_id = m.id
    JOIN conversations c ON c.id = p.conversation_id
    WHERE a.kind = 'html' AND btrim(a.title) <> ''
    ORDER BY a.created_at DESC
    LIMIT 1
    """
)


async def main() -> None:
    async with session_scope() as session:
        row = (await session.execute(_NEWEST_HTML_ON_PATH)).one()
        refresh, _family_id = await RefreshTokenRepository(session).issue_new_family(
            user_id=row.user_id,
            ttl_days=settings.REFRESH_TOKEN_TTL_DAYS,
            user_agent="make test-artifact-origin",
        )
        await session.commit()
    print(
        json.dumps(
            {
                "refresh": refresh,
                "conversation_id": str(row.conversation_id),
                "title": row.title,
                "version": row.version,
            }
        )
    )


asyncio.run(main())
