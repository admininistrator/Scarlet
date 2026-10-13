"""Chia sẻ hội thoại — snapshot bất biến (ADR-14, §16.1, UC-11) — T-8.1.

    POST /api/v1/conversations/{id}/share   chủ ⇒ 201 {token, url}   (`router`)
    GET  /api/v1/s/{token}                  CÔNG KHAI, không cookie    (`public_router`)

KH tham chiếu: ADR-14, §16.1, §17.2, §18.5, §20, Phụ lục A · NQ-149 (Q-P8-4, Q-P8-5).

**Hai router, cố ý (Cạm bẫy ⑦).** `router` gắn ở `include_router` cùng
`_AUTHENTICATED` (danh tính + §11.4); `public_router` gắn trần. POST nằm ở
router công khai là mất lọc chủ; GET nằm ở router có danh tính là `401` cho
người lạ.

**Ranh giới "không lộ" là DANH SÁCH TRẮNG** (luật ① của P8): `build_snapshot`
dựng từng khoá bằng tay, không bao giờ "chép rồi lọc bỏ"; `SNAPSHOT_KEYS` là
tập mọi khoá được phép ở MỌI tầng — test duyệt đệ quy. Snapshot ghi một lần,
không bản vá nào sửa được link đã gửi đi: một trường thừa là lộ vĩnh viễn.

**Dữ liệu đi ra là bản chép** (luật ②): ảnh + artifact `kind=file` chép phía
MinIO sang `share/<token>/<uuid><đuôi>` TRƯỚC `INSERT`; snapshot chỉ mang khoá
chép. URL ký lúc `GET` (TTL `PRESIGN_TTL_S`) — không bao giờ lưu vào snapshot
(B-406 ②). Tài liệu của user chỉ mang tên + MIME, không khoá, không chữ trích.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel

from app.config.catalog import get_catalog
from app.config.settings import settings
from app.core import storage
from app.core.deps import get_current_user_id
from app.core.errors import ApiError, ApiErrorCode, ErrorEnvelope
from app.db.models import (
    Artifact,
    Attachment,
    AttachmentKind,
    Message,
    MessageRole,
    MessageStatus,
)
from app.db.repositories import (
    ArtifactRepository,
    AttachmentRepository,
    ConversationRepository,
    MessageRepository,
    SharedConversationRepository,
)
from app.db.repositories.messages import IN_FLIGHT_STATUSES
from app.db.session import session_scope

logger = logging.getLogger(__name__)

#: `secrets.token_urlsafe(16)` = 128 bit (Phụ lục A: "≥ 128 bit, url-safe").
SHARE_TOKEN_BYTES = 16
#: `version` của hình dạng snapshot — đổi hình dạng thì tăng, bản cũ vẫn đọc được.
SNAPSHOT_VERSION = 1
#: Tên route cho `IDEMPOTENCY_REQUIRED_ROUTES` (A8) — tên hàm handler.
SHARE_ROUTE_NAME = "share_conversation"

#: MỌI khoá được phép xuất hiện trong `snapshot_json`, ở mọi tầng. Thêm khoá
#: ở `build_snapshot` mà không thêm ở đây ⇒ test danh sách trắng đỏ.
SNAPSHOT_KEYS = frozenset(
    {
        # gốc
        "version",
        "title",
        "shared_at",
        "messages",
        # message
        "role",
        "content",
        "model_display_name",
        "created_at",
        "attachments",
        "artifacts",
        # tệp + artifact (`title`, `content` dùng chung tên ở trên)
        "kind",
        "name",
        "key",
        "width",
        "height",
        "mime_type",
        "language",
    }
)

_SHARED_ROLES = (MessageRole.USER, MessageRole.ASSISTANT)
_PUBLIC_HEADERS = {"X-Robots-Tag": "noindex, nofollow", "Cache-Control": "no-store"}

router = APIRouter(tags=["share"])
public_router = APIRouter(tags=["share"])


class ShareOut(BaseModel):
    """Thân nhỏ — bản ghi `idem:` lưu nguyên response 24 h (B-145)."""

    token: str
    url: str


def build_snapshot(
    *,
    token: str,
    title: str | None,
    messages: Sequence[Message],
    attachments: Sequence[Attachment],
    artifacts: Sequence[Artifact],
) -> tuple[dict[str, Any], dict[str, str]]:
    """`(snapshot, {khoá gốc: khoá chép})` — danh sách TRẮNG, từng khoá viết tay.

    `messages` theo thứ tự `get_path` (độ sâu, NQ-18). Artifact = bản mới nhất
    mỗi dòng (`version`) trong số artifact trên đường đi, gắn vào message của
    chính bản ấy. `kind=file` chép theo `storage_key` — `content` là NULL (B-372).
    """
    copies: dict[str, str] = {}

    def copied(source_key: str) -> str:
        if source_key not in copies:
            copies[source_key] = f"share/{token}/{uuid.uuid4()}{PurePosixPath(source_key).suffix}"
        return copies[source_key]

    def attachment_entry(row: Attachment) -> dict[str, Any]:
        if row.kind == AttachmentKind.IMAGE:
            return {
                "kind": "image",
                "name": row.original_name,
                "key": copied(row.storage_key),
                "width": row.width,
                "height": row.height,
            }
        return {"kind": "document", "name": row.original_name, "mime_type": row.mime_type}

    def artifact_entry(row: Artifact) -> dict[str, Any]:
        if row.storage_key is not None:
            return {"kind": "file", "title": row.title, "key": copied(row.storage_key)}
        return {
            "kind": row.kind,
            "language": row.language,
            "title": row.title,
            "content": row.content,
        }

    latest: dict[uuid.UUID, Artifact] = {}
    for art in artifacts:
        lineage = art.parent_artifact_id or art.id
        if lineage not in latest or art.version > latest[lineage].version:
            latest[lineage] = art
    shown = {art.id for art in latest.values()}

    display_names = {m.id: m.display_name for m in get_catalog().models}
    snapshot = {
        "version": SNAPSHOT_VERSION,
        "title": title,
        "shared_at": datetime.now(UTC).isoformat(),
        "messages": [
            {
                "role": str(m.role),
                "content": m.content,
                "model_display_name": display_names.get(m.model_id or ""),
                "created_at": m.created_at.isoformat(),
                "attachments": [attachment_entry(a) for a in attachments if a.message_id == m.id],
                "artifacts": [
                    artifact_entry(a) for a in artifacts if a.message_id == m.id and a.id in shown
                ],
            }
            for m in messages
        ],
    }
    return snapshot, copies


@router.post(
    "/conversations/{conversation_id}/share",
    status_code=status.HTTP_201_CREATED,
    response_model=ShareOut,
    responses={
        404: {"model": ErrorEnvelope, "description": "CONVERSATION_NOT_FOUND (§20 gop ba ca)"},
        409: {"model": ErrorEnvelope, "description": "GENERATION_IN_PROGRESS"},
        422: {"model": ErrorEnvelope, "description": "CONVERSATION_EMPTY"},
        503: {"model": ErrorEnvelope, "description": "SHARE_STORAGE_UNAVAILABLE"},
    },
)
async def share_conversation(
    conversation_id: uuid.UUID,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
) -> ShareOut:
    """Snapshot đường đi hiện tại (§8.3) ⇒ token MỚI mỗi lần (ADR-14: link cũ giữ nội dung cũ).

    Đọc trong một session, chép object NGOÀI session (không giữ kết nối pool
    qua N lượt mạng), ghi trong session thứ hai. Chép hỏng ⇒ `503`, không hàng.
    """
    token = secrets.token_urlsafe(SHARE_TOKEN_BYTES)
    async with session_scope() as session:
        conversation = await ConversationRepository(session).get_conversation(
            conversation_id, user_id=user_id
        )
        if conversation is None:
            raise ApiError(
                status.HTTP_404_NOT_FOUND,
                ApiErrorCode.CONVERSATION_NOT_FOUND,
                "khong tim thay hoi thoai",
            )
        nodes = (
            []
            if conversation.active_leaf_id is None
            else await MessageRepository(session).get_path(
                conversation.active_leaf_id, user_id=user_id
            )
        )
        if any(node.message.status in IN_FLIGHT_STATUSES for node in nodes):
            raise ApiError(
                status.HTTP_409_CONFLICT,
                ApiErrorCode.GENERATION_IN_PROGRESS,
                "luot sinh tren duong di chua xong; chia se sau khi no khep",
            )
        messages = [
            node.message
            for node in nodes
            if node.message.role in _SHARED_ROLES
            and not (node.message.status == MessageStatus.FAILED and not node.message.content)
        ]
        if not messages:
            raise ApiError(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                ApiErrorCode.CONVERSATION_EMPTY,
                "hoi thoai chua co tin nhan nao de chia se",
            )
        ids = [m.id for m in messages]
        snapshot, copies = build_snapshot(
            token=token,
            title=conversation.title,
            messages=messages,
            attachments=await AttachmentRepository(session).list_for_messages(
                user_id=user_id, message_ids=ids
            ),
            artifacts=await ArtifactRepository(session).list_for_messages(
                user_id=user_id, message_ids=ids
            ),
        )

    await _copy_all(copies)
    try:
        async with session_scope() as session:
            await SharedConversationRepository(session).create(
                token=token, owner_id=user_id, conversation_id=conversation_id, snapshot=snapshot
            )
            await session.commit()
    except Exception:
        await _remove_best_effort(copies.values())
        raise
    return ShareOut(token=token, url=f"{settings.PUBLIC_BASE_URL.rstrip('/')}/s/{token}")


async def _copy_all(copies: dict[str, str]) -> None:
    """Chép lần lượt; hỏng ở object nào ⇒ gỡ những bản đã chép rồi `503`."""
    done: list[str] = []
    for source, target in copies.items():
        try:
            await storage.copy(source, target)
        except Exception as exc:
            logger.warning("share: chep %s that bai (%s)", target, type(exc).__name__)
            await _remove_best_effort(done)
            raise ApiError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                ApiErrorCode.SHARE_STORAGE_UNAVAILABLE,
                "khong chep duoc anh/tep sang ban chia se, thu lai sau",
            ) from exc
        done.append(target)


async def _remove_best_effort(keys: Iterable[str]) -> None:
    for key in keys:
        try:
            await storage.remove(key)
        except Exception as exc:
            logger.warning("share: khong go duoc ban chep do %s (%s)", key, type(exc).__name__)


@public_router.get(
    "/s/{token}",
    responses={404: {"model": ErrorEnvelope, "description": "SHARE_NOT_FOUND"}},
)
async def read_share(token: str, response: Response) -> dict[str, Any]:
    """Snapshot nguyên văn + `url` ký MỚI cho mỗi `key` — chỉ đọc `snapshot_json` (ADR-14).

    Token lạ và token đã thu hồi trả cùng một `404` (không phân biệt hai ca).
    """
    async with session_scope() as session:
        snapshot = await SharedConversationRepository(session).read_public(token)
        await session.commit()
    if snapshot is None:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            ApiErrorCode.SHARE_NOT_FOUND,
            "link chia se khong ton tai",
            headers=_PUBLIC_HEADERS,
        )
    response.headers.update(_PUBLIC_HEADERS)
    for message in snapshot["messages"]:
        for item in message["attachments"]:
            if "key" in item:
                item["url"] = storage.presign_get(item["key"])
        for item in message["artifacts"]:
            if "key" in item:
                item["url"] = storage.presign_get(
                    item["key"], download_name=PurePosixPath(item["title"]).name
                )
    return snapshot
