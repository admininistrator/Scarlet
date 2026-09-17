"""Repository của bảng `refresh_tokens` (§11.2, ADR-07) — T-2.3.

Hai thao tác:

- `issue_new_family`: đăng nhập thành công → token đầu tiên của một family
  MỚI (`family_id` tự sinh).
- `rotate`: `/auth/refresh` → tra token bằng hash, phân biệt ba kết cục
  (Việc cần làm + DoD T-2.3):

    - `raw_token` không khớp `token_hash` nào, hoặc đã `revoked_at`, hoặc đã
      `expires_at` → KHÔNG_HỢP_LỆ (401, không thu hồi gì thêm).
    - `used_at` đã có giá trị (token này đã được xoay vòng trước đó, mà giờ
      lại có người trình nó ra lần nữa) → TÁI_SỬ_DỤNG: thu hồi CẢ family
      (mọi hàng `family_id` này còn `revoked_at IS NULL`, kể cả hàng vừa
      xoay ra và còn hợp lệ) — dấu hiệu token đã bị đánh cắp.
    - Hợp lệ, chưa dùng, chưa hết hạn, chưa bị thu hồi → OK: đánh dấu
      `used_at`, phát hành token MỚI cùng `family_id`, trả về bản RÕ.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_refresh_token, hash_refresh_token
from app.db.models import RefreshToken


class RotateResult(StrEnum):
    OK = "ok"
    #: Token đã `used_at` bị trình ra lần nữa — cả family đã bị thu hồi.
    REUSED = "reused"
    #: Không tìm thấy / đã hết hạn / đã bị thu hồi từ trước (không phải do
    #: chính lần gọi này phát hiện tái sử dụng).
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class RotateOutcome:
    result: RotateResult
    #: Chỉ có giá trị khi `result is OK`.
    user_id: uuid.UUID | None = None
    raw_token: str | None = None


class RefreshTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def issue_new_family(
        self, *, user_id: uuid.UUID, ttl_days: int, user_agent: str | None
    ) -> tuple[str, uuid.UUID]:
        """Token đầu tiên của một family mới (đăng nhập). Trả `(raw_token, family_id)`."""
        family_id = uuid.uuid4()
        raw_token = await self._them_hang(
            user_id=user_id, family_id=family_id, ttl_days=ttl_days, user_agent=user_agent
        )
        return raw_token, family_id

    async def rotate(
        self, *, raw_token: str, ttl_days: int, user_agent: str | None
    ) -> RotateOutcome:
        token_hash = hash_refresh_token(raw_token)
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        row = (await self._session.execute(stmt)).scalar_one_or_none()

        if row is None or row.revoked_at is not None or row.expires_at < datetime.now(UTC):
            return RotateOutcome(RotateResult.INVALID)

        if row.used_at is not None:
            await self._thu_hoi_ca_family(row.family_id)
            return RotateOutcome(RotateResult.REUSED)

        row.used_at = datetime.now(UTC)
        await self._session.flush()

        new_raw_token = await self._them_hang(
            user_id=row.user_id, family_id=row.family_id, ttl_days=ttl_days, user_agent=user_agent
        )
        return RotateOutcome(RotateResult.OK, user_id=row.user_id, raw_token=new_raw_token)

    async def _them_hang(
        self, *, user_id: uuid.UUID, family_id: uuid.UUID, ttl_days: int, user_agent: str | None
    ) -> str:
        raw_token = generate_refresh_token()
        self._session.add(
            RefreshToken(
                user_id=user_id,
                family_id=family_id,
                token_hash=hash_refresh_token(raw_token),
                expires_at=datetime.now(UTC) + timedelta(days=ttl_days),
                user_agent=user_agent,
            )
        )
        await self._session.flush()
        return raw_token

    async def _thu_hoi_ca_family(self, family_id: uuid.UUID) -> None:
        stmt = (
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
            .execution_options(synchronize_session=False)
        )
        await self._session.execute(stmt)
        await self._session.flush()
