"""Phiên + token chia sẻ cho `make s8` (T-9.4a, S8 — NQ-77).

Chạy TRONG `api` (`docker compose exec -T api python - < file`), lối
`artifact_origin_session.py`: in một dòng JSON ra stdout, Makefile nối thẳng vào
stdin của `scripts/s8_lighthouse.mjs` — token không qua argv / env.

Chọn snapshot chia sẻ mới nhất có khối mã **và** bảng (`/s/<token>` của T-8.2
— trang nặng nhất ở ngoài cửa); phiên là của chủ snapshot ấy (còn `active`).
Script Node gọi `/auth/refresh` rồi `/auth/logout` ở cuối ⇒ cả family thu hồi.
"""

import asyncio
import json

from sqlalchemy import text

from app.config.settings import settings
from app.db.repositories.refresh_tokens import RefreshTokenRepository
from app.db.session import session_scope

_NEWEST_SHARE_WITH_CODE_AND_TABLE = text(
    """
    SELECT s.token, s.owner_id
    FROM shared_conversations s
    JOIN users u ON u.id = s.owner_id
    WHERE s.revoked_at IS NULL AND u.deleted_at IS NULL AND u.status = 'active'
      AND s.snapshot_json::text LIKE '%```%' AND s.snapshot_json::text LIKE '%|---%'
    ORDER BY s.created_at DESC
    LIMIT 1
    """
)


async def main() -> None:
    async with session_scope() as session:
        row = (await session.execute(_NEWEST_SHARE_WITH_CODE_AND_TABLE)).one()
        refresh, _family_id = await RefreshTokenRepository(session).issue_new_family(
            user_id=row.owner_id,
            ttl_days=settings.REFRESH_TOKEN_TTL_DAYS,
            user_agent="make s8",
        )
        await session.commit()
    print(json.dumps({"refresh": refresh, "share": row.token}))


asyncio.run(main())
