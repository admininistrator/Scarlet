"""Phát một refresh token cho `make test-artifact-origin` (T-5.6, S12).

Chạy TRONG container `api` (`docker compose exec -T api python - < file`):
host `.venv` thiếu biến `.env` (A4). In một dòng JSON `{"refresh": ...}` ra
stdout — Makefile nối thẳng vào stdin của `scripts/test_artifact_origin.mjs`,
token không qua argv hay biến môi trường.

Không mật khẩu, không `POST /auth/login` ⇒ `last_login_at` không đổi (NQ-125).
Người dùng: chủ hội thoại cập nhật gần nhất (active, chưa xoá) — phép đối chứng
cần một danh sách hội thoại không rỗng. Script Node gọi `/auth/refresh` để có
cookie phiên, rồi `/auth/logout` ở cuối ⇒ cả family bị thu hồi.
"""

import asyncio
import json

from sqlalchemy import select

from app.config.settings import settings
from app.db.models import Conversation, User, UserStatus
from app.db.repositories.refresh_tokens import RefreshTokenRepository
from app.db.session import session_scope


async def main() -> None:
    async with session_scope() as session:
        user_id = (
            await session.execute(
                select(User.id)
                .join(Conversation, Conversation.user_id == User.id)
                .where(
                    User.status == UserStatus("active"),
                    User.deleted_at.is_(None),
                    Conversation.deleted_at.is_(None),
                )
                .order_by(Conversation.updated_at.desc())
                .limit(1)
            )
        ).scalar_one()
        refresh, _family_id = await RefreshTokenRepository(session).issue_new_family(
            user_id=user_id,
            ttl_days=settings.REFRESH_TOKEN_TTL_DAYS,
            user_agent="make test-artifact-origin",
        )
        await session.commit()
    print(json.dumps({"refresh": refresh}))


asyncio.run(main())
