"""Phát một refresh token cho `make test-voice` (T-8.4) — lối `artifact_origin_session.py`.

Chạy TRONG container `api` (`docker compose exec -T api python - < file`): host
`.venv` thiếu biến `.env` (A4). In một dòng JSON ra stdout, Makefile nối thẳng
vào stdin của `scripts/test_voice.mjs` — token không qua argv hay biến môi trường.
Script Node gọi `/auth/logout` ở cuối ⇒ cả family bị thu hồi.

Cần một hội thoại mà message lá (`active_leaf_id`) là câu trả lời `completed`
có khối mã ("```") — Đọc to phải BỎ khối ấy — và có nhánh anh em (hàng nút có
`‹ n/m ›` ⇒ dưới 640 px Đọc to gập vào menu "…", §7b.2 hàng thứ hai).
"""

import asyncio
import json

from sqlalchemy import text

from app.config.settings import settings
from app.db.repositories.refresh_tokens import RefreshTokenRepository
from app.db.session import session_scope

_ANSWER_WITH_CODE_AND_BRANCHES = text(
    """
    SELECT c.user_id, c.id AS conversation_id
    FROM conversations c
    JOIN users u ON u.id = c.user_id
    JOIN messages m ON m.id = c.active_leaf_id
    WHERE c.deleted_at IS NULL AND u.deleted_at IS NULL AND u.status = 'active'
      AND m.role = 'assistant' AND m.status = 'completed' AND m.deleted_at IS NULL
      AND position(repeat(chr(96), 3) IN m.content) > 0
      AND (
        SELECT count(*) FROM messages s
        WHERE s.conversation_id = m.conversation_id AND s.parent_id = m.parent_id
          AND s.deleted_at IS NULL
      ) > 1
    ORDER BY c.updated_at DESC
    LIMIT 1
    """
)


async def main() -> None:
    async with session_scope() as session:
        row = (await session.execute(_ANSWER_WITH_CODE_AND_BRANCHES)).one()
        refresh, _family_id = await RefreshTokenRepository(session).issue_new_family(
            user_id=row.user_id,
            ttl_days=settings.REFRESH_TOKEN_TTL_DAYS,
            user_agent="make test-voice",
        )
        await session.commit()
    print(json.dumps({"refresh": refresh, "conversation_id": str(row.conversation_id)}))


asyncio.run(main())
