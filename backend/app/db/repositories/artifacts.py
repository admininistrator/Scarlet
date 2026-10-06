"""Repository của bảng `artifacts` — T-5.1 (§14.2).

T-5.1 chỉ ghi **v1** (`parent_artifact_id NULL`, `version 1`); dòng phiên bản
theo tiêu đề trên đường đi là T-5.2a. Bảng không có `user_id` — mọi câu ĐỌC sau
này phải JOIN `messages → conversations` và lọc `user_id` trong SQL (§20).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import TYPE_CHECKING

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Artifact

if TYPE_CHECKING:
    from app.llm.artifact_blocks import ArtifactBlock


class ArtifactRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_initial(
        self, *, message_id: uuid.UUID, blocks: Sequence[ArtifactBlock]
    ) -> list[Artifact]:
        """Mỗi khối một hàng v1, đúng thứ tự khối trong câu trả lời.

        Mỗi hàng một `INSERT` riêng chứ không một câu nhiều `VALUES`: trong
        cùng một câu, `clock_timestamp()` trùng nhau ở độ phân giải micro-giây
        (đo ở 0002: 500 dòng → 88 giá trị).
        """
        rows: list[Artifact] = []
        for block in blocks:
            stmt = (
                insert(Artifact)
                .values(
                    message_id=message_id,
                    kind=block.kind,
                    language=block.language,
                    title=block.title,
                    content=block.content,
                )
                .returning(Artifact)
            )
            rows.append((await self._session.execute(stmt)).scalar_one())
        return rows
