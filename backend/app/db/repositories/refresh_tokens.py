"""Repository của bảng `refresh_tokens` (§11.2, §11.3, ADR-07) — T-2.3, T-2.4.

Hai thao tác của T-2.3:

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

T-2.4 thêm hai thao tác thu hồi **chủ động** — khác `rotate`, chúng không tra
cứu để cho qua, chúng chỉ đóng cửa (§11.3):

- `revoke_family_by_token`: logout → thu hồi đúng family của phiên đang
  đăng xuất, không đụng phiên khác của cùng người dùng.
- `revoke_all_families`: đổi mật khẩu / admin suspend → thu hồi **mọi** family.

Cả hai đều trả về **số hàng đã đổi** thay vì `None`: đó là con số duy nhất cho
biết thao tác có chạm được vào cái gì hay không, và DoD của T-2.4 đọc đúng nó.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

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
        raw_token = await self._insert_row(
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
            await self._revoke_family(row.family_id)
            return RotateOutcome(RotateResult.REUSED)

        row.used_at = datetime.now(UTC)
        await self._session.flush()

        new_raw_token = await self._insert_row(
            user_id=row.user_id, family_id=row.family_id, ttl_days=ttl_days, user_agent=user_agent
        )
        return RotateOutcome(RotateResult.OK, user_id=row.user_id, raw_token=new_raw_token)

    async def revoke_family_by_token(self, raw_token: str) -> int:
        """Logout (§11.3): thu hồi family của **chính** token đang cầm.

        Trả số hàng đã thu hồi; `0` nghĩa là không tìm thấy token (đã bị thu
        hồi từ trước, hoặc bịa đặt). `0` **không** phải lỗi và chỗ gọi không
        được biến nó thành lỗi: logout phải chạy được với một cookie cũ, xem
        docstring của `logout` trong `api/v1/auth.py`.

        Cố ý KHÔNG kiểm `used_at`/`expires_at` như `rotate`: ở đây không có ai
        được cấp quyền gì, chỉ có quyền bị lấy đi. Một token đã hết hạn vẫn chỉ
        đúng family cần đóng.
        """
        stmt = select(RefreshToken.family_id).where(
            RefreshToken.token_hash == hash_refresh_token(raw_token)
        )
        family_id = (await self._session.execute(stmt)).scalar_one_or_none()
        if family_id is None:
            return 0
        return await self._revoke_family(family_id)

    async def revoke_all_families(self, user_id: uuid.UUID) -> int:
        """Đổi mật khẩu / admin suspend (§11.3): thu hồi MỌI family của user.

        Một câu `UPDATE` theo `user_id` chứ không phải vòng lặp theo từng
        `family_id`: §20 đòi lọc **trong** SQL, và một vòng lặp ở Python có
        thêm một cửa sổ để một lần đăng nhập mới chen vào giữa.
        """
        return await self._revoke_where(RefreshToken.user_id == user_id)

    async def _insert_row(
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

    async def _revoke_family(self, family_id: uuid.UUID) -> int:
        return await self._revoke_where(RefreshToken.family_id == family_id)

    async def _revoke_where(self, condition: ColumnElement[bool]) -> int:
        """`UPDATE ... revoked_at = now()` cho mọi hàng khớp mà CHƯA bị thu hồi.

        `revoked_at IS NULL` không phải để tiết kiệm: nó giữ **thời điểm thu
        hồi đầu tiên**. Ghi đè bằng `now()` mỗi lần gọi sẽ xoá mất dấu vết của
        lần phát hiện tái sử dụng (`rotate`) ngay khi người dùng bấm logout,
        đúng lúc dấu vết đó đáng giá nhất.
        """
        stmt = (
            update(RefreshToken)
            .where(condition, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
            .returning(RefreshToken.id)
            .execution_options(synchronize_session=False)
        )
        # `RETURNING` chứ không `rowcount`: cùng lối `mark_email_verified` của
        # `repositories/users.py`, và `Result.rowcount` không có trong kiểu tĩnh
        # mà SQLAlchemy khai cho `session.execute` (mypy đỏ).
        row_count = len((await self._session.execute(stmt)).scalars().all())
        await self._session.flush()
        return row_count
