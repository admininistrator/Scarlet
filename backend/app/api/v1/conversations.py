"""Bốn endpoint hội thoại của §18.2 — trước B-93 không task nào nhận chúng.

    GET    /api/v1/conversations          sidebar, phân trang bằng con trỏ
    POST   /api/v1/conversations          tạo rỗng
    GET    /api/v1/conversations/{id}     metadata + ĐƯỜNG ĐI hiện tại
    DELETE /api/v1/conversations/{id}     xoá mềm

KH tham chiếu: §8.2, §8.3, §17.4, §18.2, §20 · CLAUDE.md A2, A3 · B-93, NQ-31.

**Vì sao file này ra đời ngoài hàng đợi task.** `tasks.md` giao `PATCH
/conversations/{id}` cho T-1.13 và không giao bốn đường dẫn trên cho ai, nên
tới T-1.8 vẫn **không có cách nào tạo một hội thoại qua HTTP** — DoD phải
`INSERT` bằng `psql`. Bốn endpoint này chặn T-1.14 và mốc M3: màn chat thô cần
`POST /conversations` để bắt đầu một cuộc, `GET /conversations/{id}` để dựng
lại màn hình sau khi đóng tab, `GET /conversations` cho sidebar. Repository đã
có đủ bốn hàm từ T-1.1, nên phần việc ở đây là router + schema.

**`PATCH /conversations/{id}` KHÔNG nằm ở đây** — nó thuộc T-1.13, cùng lượt
với `active_leaf_id` và điều hướng nhánh. Thêm nó bây giờ là lấn sang task khác.

┌──────────────────────────────────────────────────────────────────────────┐
│  BA LUẬT                                                                 │
└──────────────────────────────────────────────────────────────────────────┘

**1. A2 — `GET /conversations/{id}` trả ĐƯỜNG ĐI, không trả "mọi message".**
Nó gọi `get_path(active_leaf_id)`, tức đi từ lá đang xem ngược lên gốc (§8.3).
Một câu `WHERE conversation_id = ... ORDER BY created_at` sẽ gom cả những nhánh
người dùng đã bỏ — đó là C11, và bạn trả tiền cho chúng ở mọi lượt sau.
`active_leaf_id` là NULL (hội thoại vừa tạo) ⇒ đường đi rỗng, không phải lỗi.

**2. §20 — 404 gộp ba ca.** "Không tồn tại", "đã xoá mềm" và "của người khác"
trả về cùng một câu. Repository đã lọc `user_id` **trong SQL**, nên tầng này
không bao giờ nhìn thấy hàng của người khác để mà lọc lại.

**3. A3 — kích thước trang là cấu hình.** `list_conversations` của repository
cố ý **không** có `limit` mặc định (docstring của nó nói thẳng lý do); con số
sống ở `settings.CONVERSATION_PAGE_SIZE` và dùng cho **cả** giá trị mặc định
lẫn trần của tham số `limit`. Một trần riêng lớn hơn mặc định chỉ thêm một nút
vặn thứ hai mà chưa màn hình nào cần.

**Con trỏ phân trang là `updated_at`, không phải offset.** Sidebar sắp theo
`updated_at DESC` (§17.4, `ix_conv_user`), và OFFSET trên một danh sách mà
chính người dùng đang làm đổi thứ tự sẽ nhảy cóc hoặc lặp dòng: mỗi lượt chat
đẩy một hội thoại lên đầu. Client gửi lại `next_cursor` của trang trước; hết
dữ liệu thì `next_cursor` là `null`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import catalog
from app.config.settings import settings
from app.core.deps import get_current_user_id
from app.core.errors import ApiError, ApiErrorCode, ErrorEnvelope
from app.db.models import Conversation, MessageRole, MessageStatus
from app.db.repositories import ConversationRepository, MessageRepository
from app.db.repositories.messages import PathNode
from app.db.session import session_scope

router = APIRouter(tags=["conversations"])


class TaoHoiThoaiRequest(BaseModel):
    """Body của `POST /conversations`. Cả ba trường đều tuỳ chọn.

    Không có `content` ở đây: §18.2 ghi "Tạo rỗng", và lượt chat đầu tiên đi
    qua `POST /conversations/{id}/messages` như mọi lượt sau — một đường ghi
    message duy nhất, nên A1/A2/C14 chỉ có một chỗ để đúng.
    """

    title: str | None = Field(default=None, max_length=200)
    #: Model mặc định của riêng hội thoại này (§9.2). Kiểm ngay tại đây chứ
    #: không đợi lượt chat đầu tiên: một hội thoại mang tên model không tồn tại
    #: là quả mìn hẹn giờ mà người dùng chỉ thấy khi đã gõ xong câu hỏi.
    default_model: str | None = None
    system_prompt_override: str | None = None


class HoiThoaiRa(BaseModel):
    """Metadata một hội thoại — dùng cho cả danh sách lẫn chi tiết."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    default_model: str | None
    system_prompt_override: str | None
    active_leaf_id: uuid.UUID | None
    pinned: bool
    created_at: datetime
    updated_at: datetime


class MessageTrenDuongDi(BaseModel):
    """Một message trên đường đi hiện tại, kèm vị trí giữa các anh em (C13).

    `sibling_index` đếm từ **0** (B-60): giao diện `‹ 2/3 ›` của §8.2 hiển thị
    `sibling_index + 1`. Hai số do SQL tính, FE không tự đếm.

    Không có `raw_response`, `tool_calls`, `prompt_tokens`, `heartbeat_at`:
    chúng là dữ liệu vận hành chứ không phải thứ màn chat cần, và thêm vào đây
    là mở một đường rò dữ liệu mà không ai xin.
    """

    id: uuid.UUID
    parent_id: uuid.UUID | None
    role: MessageRole
    status: MessageStatus
    content: str
    reasoning: str | None
    model_id: str | None
    finish_reason: str | None
    error_code: str | None
    created_at: datetime
    sibling_index: int
    sibling_count: int

    @classmethod
    def from_path_node(cls, node: PathNode) -> MessageTrenDuongDi:
        """Liệt từng trường bằng tay, **không** `from_attributes`.

        `Message` có 20 cột và ba trong số đó (`raw_response`, `tool_calls`,
        `heartbeat_at`) không được ra khỏi server. Một model đọc thuộc tính tự
        động sẽ lặng lẽ nhận thêm cột mới ở migration sau; danh sách viết tay
        thì không đổi cho tới khi có người cố ý sửa nó.
        """
        m = node.message
        return cls(
            id=m.id,
            parent_id=m.parent_id,
            role=m.role,
            status=m.status,
            content=m.content,
            reasoning=m.reasoning,
            model_id=m.model_id,
            finish_reason=m.finish_reason,
            error_code=m.error_code,
            created_at=m.created_at,
            sibling_index=node.sibling_index,
            sibling_count=node.sibling_count,
        )


class HoiThoaiChiTiet(HoiThoaiRa):
    """`GET /conversations/{id}` — metadata + đường đi hiện tại (§18.2)."""

    #: Gốc trước, lá sau. Rỗng khi `active_leaf_id` là NULL.
    path: list[MessageTrenDuongDi]


class DanhSachHoiThoai(BaseModel):
    """`GET /conversations` — một trang, kèm con trỏ sang trang kế."""

    items: list[HoiThoaiRa]
    #: `updated_at` của dòng cuối trang này; gửi lại vào `?updated_before=` để
    #: lấy trang kế. `null` = hết. **Không** trả tổng số dòng: đếm cả bảng mỗi
    #: lần mở sidebar là một câu quét mà không màn hình nào hiển thị kết quả.
    next_cursor: datetime | None


@router.get(
    "/conversations",
    response_model=DanhSachHoiThoai,
    responses={422: {"model": ErrorEnvelope, "description": "limit ngoai khoang cho phep"}},
)
async def list_conversations(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    limit: Annotated[
        int,
        Query(ge=1, le=settings.CONVERSATION_PAGE_SIZE, description="so hoi thoai toi da"),
    ] = settings.CONVERSATION_PAGE_SIZE,
    updated_before: Annotated[
        datetime | None,
        Query(description="next_cursor cua trang truoc"),
    ] = None,
) -> DanhSachHoiThoai:
    """Sidebar: mới nhất trước, phân trang bằng con trỏ `updated_at` (§17.4)."""
    async with session_scope() as session:
        rows = await ConversationRepository(session).list_conversations(
            user_id=user_id, limit=limit, updated_before=updated_before
        )
        items = [HoiThoaiRa.model_validate(row) for row in rows]

    # Trang chưa đầy ⇒ chắc chắn hết dữ liệu, khỏi mời client hỏi thêm một vòng
    # nữa chỉ để nhận về danh sách rỗng.
    con_nua = len(items) == limit
    return DanhSachHoiThoai(
        items=items,
        next_cursor=items[-1].updated_at if (items and con_nua) else None,
    )


@router.post(
    "/conversations",
    status_code=status.HTTP_201_CREATED,
    response_model=HoiThoaiRa,
    responses={
        400: {"model": ErrorEnvelope, "description": "default_model khong co trong catalog"}
    },
)
async def create_conversation(
    body: TaoHoiThoaiRequest,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
) -> HoiThoaiRa:
    """Tạo hội thoại RỖNG: `active_leaf_id` NULL, chưa có message nào (§18.2).

    `201` chứ không `202`: ở đây không có job nào được đẩy đi, tài nguyên tồn
    tại đầy đủ ngay khi response về. `202` của `POST .../messages` mang nghĩa
    khác hẳn — "đã nhận, câu trả lời còn đang sinh".
    """
    if body.default_model is not None and catalog.get_model(body.default_model) is None:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            ApiErrorCode.MODEL_UNKNOWN,
            f"model khong co trong catalog hoac da tat: {body.default_model}",
            details={"model_id": body.default_model},
        )

    async with session_scope() as session:
        conversation = await ConversationRepository(session).create_conversation(
            user_id=user_id,
            title=body.title,
            default_model=body.default_model,
            system_prompt_override=body.system_prompt_override,
        )
        # Đọc ra schema TRƯỚC khi session đóng — sau `commit()` object là
        # detached, cùng lý do với `uid, amid` của `messages.py`.
        ra = HoiThoaiRa.model_validate(conversation)
        await session.commit()
    return ra


@router.get(
    "/conversations/{conversation_id}",
    response_model=HoiThoaiChiTiet,
    responses={404: {"model": ErrorEnvelope, "description": "Khong thay (§20 gop ba ca)"}},
)
async def get_conversation(
    conversation_id: uuid.UUID,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
) -> HoiThoaiChiTiet:
    """Metadata + đường đi từ gốc xuống `active_leaf_id` (§8.3, A2).

    Đây là thứ T-1.14 gọi khi mở lại một tab đã đóng: nó dựng lại đúng màn hình
    người dùng đang nhìn, kể cả khi lượt sinh cuối vẫn đang chảy — message
    `streaming` nằm trong `path` với phần `content` đã ghi xuống Postgres, còn
    phần đang bay thì FE lấy tiếp qua `GET /messages/{id}/stream`.
    """
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
        path = await _duong_di(session, conversation, user_id=user_id)
        meta = HoiThoaiRa.model_validate(conversation)

    return HoiThoaiChiTiet(**meta.model_dump(), path=path)


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorEnvelope, "description": "Khong thay (§20 gop ba ca)"}},
)
async def delete_conversation(
    conversation_id: uuid.UUID,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
) -> Response:
    """Xoá **mềm** (C12). Cây message bên dưới không bị đụng tới.

    Xoá lần thứ hai trả `404` chứ không phải `204`: `soft_delete_conversation`
    chỉ nhận hàng còn `deleted_at IS NULL`, nên một hàng đã xoá đi cùng đường
    với "không tồn tại" — đúng §20, và đúng thứ `GET` cùng id trả về ngay sau
    đó. Một `204` ở lần thứ hai sẽ nói với client rằng nó vừa xoá được cái gì.
    """
    async with session_scope() as session:
        xoa_duoc = await ConversationRepository(session).soft_delete_conversation(
            conversation_id, user_id=user_id
        )
        if not xoa_duoc:
            raise ApiError(
                status.HTTP_404_NOT_FOUND,
                ApiErrorCode.CONVERSATION_NOT_FOUND,
                "khong tim thay hoi thoai",
            )
        await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _duong_di(
    session: AsyncSession, conversation: Conversation, *, user_id: uuid.UUID
) -> list[MessageTrenDuongDi]:
    """`get_path(active_leaf_id)` → schema. `active_leaf_id` NULL ⇒ rỗng."""
    if conversation.active_leaf_id is None:
        return []
    nodes = await MessageRepository(session).get_path(conversation.active_leaf_id, user_id=user_id)
    return [MessageTrenDuongDi.from_path_node(node) for node in nodes]
