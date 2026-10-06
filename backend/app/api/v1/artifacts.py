"""Hai endpoint đọc artifact của §18.3 — T-5.2a.

    GET /api/v1/artifacts/{id}            một phiên bản, đủ `content`
    GET /api/v1/artifacts/{id}/versions   mọi phiên bản của dòng, KHÔNG `content`

KH tham chiếu: §14.2, §18.3, §20 · NQ-142 (Q-P5-2).

Bảng `artifacts` không có `user_id` — sở hữu lọc trong SQL ở repository (JOIN
`messages → conversations`). Của người khác, không có, message / hội thoại đã
xoá mềm ⇒ cùng một `404 ARTIFACT_NOT_FOUND`, trùng từng byte (§20).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from app.core.deps import get_current_user_id
from app.core.errors import ApiError, ApiErrorCode, ErrorEnvelope
from app.db.models import Artifact
from app.db.repositories import ArtifactRepository
from app.db.session import session_scope

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


class PathArtifact(BaseModel):
    """Một artifact trên đường đi (`GET /conversations/{id}`, `/siblings`).

    `content` có mặt để FE khớp khối trong bong bóng theo từng byte (Q-P5-7).
    """

    id: uuid.UUID
    kind: str
    language: str | None
    title: str
    version: int
    # ponytail: gấp đôi băng thông cho tin có artifact (khối nằm cả trong
    # `messages.content`), đổi sang băm nếu đo thấy đường đi chậm.
    content: str | None


class ArtifactOut(BaseModel):
    id: uuid.UUID
    #: Id gốc của dòng phiên bản (`parent_artifact_id` hoặc chính `id` ở v1).
    lineage_id: uuid.UUID
    version: int
    kind: str
    language: str | None
    title: str
    content: str | None
    message_id: uuid.UUID
    conversation_id: uuid.UUID
    created_at: datetime


class ArtifactVersionOut(BaseModel):
    id: uuid.UUID
    version: int
    kind: str
    language: str | None
    title: str
    message_id: uuid.UUID
    created_at: datetime


class ArtifactVersionList(BaseModel):
    #: `ORDER BY version` — mọi nhánh; một nhánh có thể thấy "v1 v4" (Cạm bẫy ⑦).
    items: list[ArtifactVersionOut]


def path_artifact(row: Artifact) -> PathArtifact:
    return PathArtifact(
        id=row.id,
        kind=row.kind,
        language=row.language,
        title=row.title,
        version=row.version,
        content=row.content,
    )


def _not_found() -> ApiError:
    return ApiError(
        status.HTTP_404_NOT_FOUND, ApiErrorCode.ARTIFACT_NOT_FOUND, "khong tim thay artifact"
    )


_NOT_FOUND_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorEnvelope, "description": "ARTIFACT_NOT_FOUND"}
}


@router.get(
    "/{artifact_id}",
    status_code=status.HTTP_200_OK,
    response_model=ArtifactOut,
    responses=_NOT_FOUND_RESPONSES,
)
async def get_artifact(
    artifact_id: uuid.UUID,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
) -> ArtifactOut:
    async with session_scope() as session:
        found = await ArtifactRepository(session).get(user_id=user_id, artifact_id=artifact_id)
    if found is None:
        raise _not_found()
    row, conversation_id = found
    return ArtifactOut(
        id=row.id,
        lineage_id=row.parent_artifact_id or row.id,
        version=row.version,
        kind=row.kind,
        language=row.language,
        title=row.title,
        content=row.content,
        message_id=row.message_id,
        conversation_id=conversation_id,
        created_at=row.created_at,
    )


@router.get(
    "/{artifact_id}/versions",
    status_code=status.HTTP_200_OK,
    response_model=ArtifactVersionList,
    responses=_NOT_FOUND_RESPONSES,
)
async def list_artifact_versions(
    artifact_id: uuid.UUID,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
) -> ArtifactVersionList:
    async with session_scope() as session:
        rows = await ArtifactRepository(session).list_versions(
            user_id=user_id, artifact_id=artifact_id
        )
    if not rows:
        raise _not_found()
    return ArtifactVersionList(
        items=[ArtifactVersionOut.model_validate(dict(r._mapping)) for r in rows]
    )
