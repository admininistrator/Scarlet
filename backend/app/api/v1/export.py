"""Xuất hội thoại — `GET /api/v1/conversations/{id}/export?format=md` (§18.2) — T-8.5.

KH tham chiếu: §18.2, §8.3, §20, §24.3 dòng P8 · NQ-02, NQ-149 ⑤ · A2, A3.

`.md` cho NGƯỜI đọc (NQ-149 ⑤): đường đi hiện tại (`active_leaf_id` → gốc, A2 /
C11), `content` nguyên văn, tệp đính kèm chỉ tên, phụ lục artifact bản mới nhất
mỗi dòng. Không reasoning, không chi phí, không URL ký (B-406 ②: tệp sống mãi,
URL thì hết hạn sau `PRESIGN_TTL_S`). `format` là `Literal` — T-8.6 thêm `json`.

**Stream thật, lối `stream.py`.** Handler đọc MỘT lần (hội thoại + id đường đi,
CTE không mang `content`) rồi đóng session — 404 phải ra trước byte đầu. Chữ
đọc theo lô `EXPORT_BATCH_SIZE` trong generator, mỗi lô một `session_scope()`
ngắn: không `Depends(get_session)` (giữ kết nối pool tới hết stream — Cạm bẫy ①),
không giữ kết nối trong lúc client chậm đọc.

**Header latin-1 (Cạm bẫy ⑤).** Starlette mã hoá header bằng latin-1 — tiêu đề
tiếng Việt chỉ đi trong `filename*=UTF-8''…`; `filename=` là bản ASCII.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse

from app.config.catalog import get_catalog
from app.config.settings import settings
from app.core.deps import get_current_user_id
from app.core.errors import ApiError, ApiErrorCode, ErrorEnvelope
from app.db.models import Artifact, MessageRole, MessageStatus
from app.db.repositories import ArtifactRepository, ConversationRepository, MessageRepository
from app.db.session import session_scope

#: Tiêu đề `null` (hoặc toàn ký hiệu) ⇒ tên này, cả trong tệp lẫn tên tệp.
DEFAULT_TITLE = "Hội thoại"
USER_LABEL = "Bạn"
#: Assistant không `model_id` (bản fork — T-8.3) hoặc model không còn trong catalog
#: mà id cũng rỗng.
ASSISTANT_LABEL = "Trợ lý"
_TIME_FORMAT = "%Y-%m-%d %H:%M UTC"
_BACKTICK_RUN = re.compile(r"`+")
_MIN_FENCE = 3

router = APIRouter(tags=["export"])


@router.get(
    "/conversations/{conversation_id}/export",
    response_class=StreamingResponse,
    responses={
        200: {"content": {"text/markdown": {}}, "description": "Duong di hien tai, markdown"},
        404: {"model": ErrorEnvelope, "description": "Khong thay (§20 gop ba ca)"},
    },
)
async def export_conversation(
    conversation_id: uuid.UUID,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    export_format: Annotated[Literal["md"], Query(alias="format")],
) -> StreamingResponse:
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
        ids = (
            []
            if conversation.active_leaf_id is None
            else await MessageRepository(session).path_ids(
                conversation.active_leaf_id, user_id=user_id
            )
        )
        title = conversation.title or DEFAULT_TITLE

    now = datetime.now(UTC)
    name = f"{_slug(title)}-{now:%Y-%m-%d}.md"
    disposition = (
        f'attachment; filename="{_ascii(_slug(title))}-{now:%Y-%m-%d}.md"; '
        f"filename*=UTF-8''{quote(name, safe='')}"
    )
    return StreamingResponse(
        _markdown(user_id, title, ids, now),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": disposition},
    )


async def _markdown(
    user_id: uuid.UUID, title: str, ids: list[uuid.UUID], now: datetime
) -> AsyncIterator[str]:
    yield f"# {title}\n\n_Xuất lúc {now:{_TIME_FORMAT}}_\n"
    display_names = {m.id: m.display_name for m in get_catalog().models}
    batch = settings.EXPORT_BATCH_SIZE
    for start in range(0, len(ids), batch):
        chunk = ids[start : start + batch]
        async with session_scope() as session:
            rows = await MessageRepository(session).export_rows(chunk, user_id=user_id)
        parts: list[str] = []
        for message_id in chunk:
            row = rows.get(message_id)
            if row is None or row.role not in (MessageRole.USER, MessageRole.ASSISTANT):
                continue
            if row.status == MessageStatus.FAILED and not row.content:
                continue
            label = (
                USER_LABEL
                if row.role == MessageRole.USER
                else display_names.get(row.model_id or "") or row.model_id or ASSISTANT_LABEL
            )
            parts.append(f"\n## {label} · {row.created_at.astimezone(UTC):{_TIME_FORMAT}}\n\n")
            parts.append(_block(row.content or ""))
            if row.attachment_names:
                parts.append(f"\nTệp đính kèm: {', '.join(row.attachment_names)}\n")
        if parts:
            yield "".join(parts)

    async with session_scope() as session:
        artifact_ids = await ArtifactRepository(session).latest_ids_for_messages(
            user_id=user_id, message_ids=ids
        )
    if artifact_ids:
        yield "\n## Artifact\n"
    for start in range(0, len(artifact_ids), batch):
        async with session_scope() as session:
            artifacts = await ArtifactRepository(session).list_by_ids(
                user_id=user_id, artifact_ids=artifact_ids[start : start + batch]
            )
        yield "".join(_artifact(a) for a in artifacts)


def _artifact(row: Artifact) -> str:
    """`kind=file` ⇒ chỉ tên (B-372: `content` NULL; không URL ký, không byte)."""
    if row.storage_key is not None:
        return f"\n### {row.title}\n\n_Tệp — không kèm trong bản xuất._\n"
    content = row.content or ""
    fence = "`" * max(_MIN_FENCE, _longest_backtick_run(content) + 1)
    heading = f"\n### {row.title or row.kind}\n\n"
    return f"{heading}{fence}{row.language or ''}\n{_block(content)}{fence}\n"


def _longest_backtick_run(text: str) -> int:
    """Fence phải DÀI HƠN mọi chuỗi backtick trong nội dung (CommonMark §4.5)."""
    return max((len(run) for run in _BACKTICK_RUN.findall(text)), default=0)


def _block(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"


def _slug(title: str) -> str:
    """Giữ chữ có dấu (đi trong `filename*`), gộp mọi thứ khác thành `-`."""
    return "-".join(re.findall(r"\w+", title.lower())) or _slug(DEFAULT_TITLE)


def _ascii(slug: str) -> str:
    """Bản latin-1-an-toàn cho `filename=`: bỏ dấu (NFKD), `đ` → `d`."""
    plain = unicodedata.normalize("NFKD", slug.replace("đ", "d")).encode("ascii", "ignore")
    return "-".join(re.findall(r"[a-z0-9]+", plain.decode())) or _ascii(_slug(DEFAULT_TITLE))
