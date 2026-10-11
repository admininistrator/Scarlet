"""Hai endpoint đọc artifact của §18.3 — T-5.2a.

    GET /api/v1/artifacts/{id}            một phiên bản, đủ `content`
    GET /api/v1/artifacts/{id}/versions   mọi phiên bản của dòng, KHÔNG `content`
    POST /api/v1/artifacts/{id}/versions  người dùng sửa ⇒ phiên bản mới (T-5.2b)

KH tham chiếu: §14.2, §18.3, §20 · NQ-142 (Q-P5-2).

Bảng `artifacts` không có `user_id` — sở hữu lọc trong SQL ở repository (JOIN
`messages → conversations`). Của người khác, không có, message / hội thoại đã
xoá mềm ⇒ cùng một `404 ARTIFACT_NOT_FOUND`, trùng từng byte (§20).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import PurePosixPath
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from app.config.settings import settings
from app.core import storage
from app.core.deps import get_current_user_id
from app.core.errors import ApiError, ApiErrorCode, ErrorEnvelope
from app.core.ratelimit import upload_limit
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
    #: `kind=file` (T-7.7a): URL ký của MinIO cho nút Tải — byte ở `storage_key`,
    #: `content` NULL (B-372). Khác `None` ⇔ có `storage_key`.
    download_url: str | None = None
    message_id: uuid.UUID
    conversation_id: uuid.UUID
    created_at: datetime


class ArtifactVersionOut(BaseModel):
    id: uuid.UUID
    version: int
    kind: str
    language: str | None
    title: str
    #: `model` | `user` — tab "bạn sửa" (T-5.9).
    origin: str
    message_id: uuid.UUID
    created_at: datetime


class ArtifactEditIn(BaseModel):
    #: Trần đọc lúc gọi ở handler (mã riêng), không ở `Field`.
    content: str = Field(min_length=1)


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
        download_url=(
            None
            if row.storage_key is None
            else storage.presign_get(row.storage_key, download_name=PurePosixPath(row.title).name)
        ),
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


@router.post(
    "/{artifact_id}/versions",
    status_code=status.HTTP_201_CREATED,
    response_model=ArtifactVersionOut,
    dependencies=[Depends(upload_limit())],
    responses={
        **_NOT_FOUND_RESPONSES,
        422: {"model": ErrorEnvelope, "description": "content rong, ARTIFACT_TOO_LONG"},
    },
)
async def create_artifact_version(
    artifact_id: uuid.UUID,
    body: ArtifactEditIn,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
) -> ArtifactVersionOut:
    """Người dùng sửa ⇒ hàng mới `origin = user` (Q-P5-3); `artifact_id` là phiên
    bản bất kỳ của dòng. `201` KHÔNG mang `content` — bản ghi `idem:` của
    `Idempotency-Key` (tuỳ chọn, gắn ở router) lưu nguyên response 24 h (B-145).
    """
    if len(body.content) > settings.ATTACHMENT_TEXT_MAX_CHARS:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ApiErrorCode.ARTIFACT_TOO_LONG,
            "ban sua vuot tran cho phep",
            details={"max_chars": settings.ATTACHMENT_TEXT_MAX_CHARS},
        )
    async with session_scope() as session:
        row = await ArtifactRepository(session).create_user_version(
            user_id=user_id, artifact_id=artifact_id, content=body.content
        )
        if row is None:
            raise _not_found()
        out = ArtifactVersionOut.model_validate(row, from_attributes=True)
        await session.commit()
    return out
