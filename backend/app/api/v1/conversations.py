"""Năm endpoint hội thoại của §18.2 — bốn cái đầu ra đời ở B-93, `PATCH` ở T-1.13.

    GET    /api/v1/conversations          sidebar, phân trang bằng con trỏ · ?pinned= (T-S.8)
    POST   /api/v1/conversations          tạo rỗng
    GET    /api/v1/conversations/{id}     metadata + ĐƯỜNG ĐI hiện tại
    PATCH  /api/v1/conversations/{id}     tiêu đề · model · ghim · CHUYỂN NHÁNH
    DELETE /api/v1/conversations/{id}     xoá mềm

KH tham chiếu: §8.2, §8.3, §17.4, §18.2, §20 · CLAUDE.md A2, A3 · B-93, NQ-31.

**Vì sao file này ra đời ngoài hàng đợi task.** `tasks.md` giao `PATCH
/conversations/{id}` cho T-1.13 và không giao bốn đường dẫn trên cho ai, nên
tới T-1.8 vẫn **không có cách nào tạo một hội thoại qua HTTP** — DoD phải
`INSERT` bằng `psql`. Bốn endpoint này chặn T-1.14 và mốc M3: màn chat thô cần
`POST /conversations` để bắt đầu một cuộc, `GET /conversations/{id}` để dựng
lại màn hình sau khi đóng tab, `GET /conversations` cho sidebar. Repository đã
có đủ bốn hàm từ T-1.1, nên phần việc ở đây là router + schema.

**`PATCH /conversations/{id}` tới sau, ở T-1.13** — cùng lượt với
`active_leaf_id` và điều hướng nhánh, đúng như NQ-31 đã giao. Nó dựng đủ **bốn**
trường mà §18.2 liệt (tiêu đề, model mặc định, ghim, `active_leaf_id`) chứ
không chỉ trường cuối: `tasks.md` chỉ nêu tên `active_leaf_id` vì đó là phần
thuộc về chủ đề của T-1.13, nhưng ba trường kia không có task nào khác nhận, và
để endpoint ra đời thiếu một nửa nghĩa là sẽ có người sửa lại đúng file này lần
nữa mà không có ai sở hữu lần sửa đó. Xem B-111.

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
from app.config.settings import CONVERSATION_TITLE_MAX_CHARS, settings
from app.core.deps import get_current_user_id
from app.core.errors import ApiError, ApiErrorCode, ErrorEnvelope
from app.db.models import Conversation, Message, MessageFeedback, MessageRole, MessageStatus
from app.db.repositories import (
    ConversationRepository,
    MessageNotInConversationError,
    MessageRepository,
)
from app.db.repositories.conversations import EDITABLE_FIELDS
from app.db.repositories.messages import PathNode
from app.db.session import session_scope

router = APIRouter(tags=["conversations"])


class CreateConversationRequest(BaseModel):
    """Body của `POST /conversations`. Cả ba trường đều tuỳ chọn.

    Không có `content` ở đây: §18.2 ghi "Tạo rỗng", và lượt chat đầu tiên đi
    qua `POST /conversations/{id}/messages` như mọi lượt sau — một đường ghi
    message duy nhất, nên A1/A2/C14 chỉ có một chỗ để đúng.
    """

    title: str | None = Field(default=None, max_length=CONVERSATION_TITLE_MAX_CHARS)
    #: Model mặc định của riêng hội thoại này (§9.2). Kiểm ngay tại đây chứ
    #: không đợi lượt chat đầu tiên: một hội thoại mang tên model không tồn tại
    #: là quả mìn hẹn giờ mà người dùng chỉ thấy khi đã gõ xong câu hỏi.
    default_model: str | None = None
    system_prompt_override: str | None = None


class UpdateConversationRequest(BaseModel):
    """Body của `PATCH /conversations/{id}` — bốn trường của §18.2.

    Cả bốn đều tuỳ chọn, và **vắng mặt khác `null`**: handler đọc
    `model_fields_set` chứ không so `is None`, đúng luật mà `parent_id` của
    `POST .../messages` đã đặt ra (C14). Không có trường nào gộp hai nghĩa vào
    một giá trị.

    `system_prompt_override` **không** có mặt dù `POST /conversations` nhận nó:
    §18.2 liệt đúng bốn thứ cho `PATCH` ("Đổi tiêu đề, model mặc định, ghim,
    `active_leaf_id`"), và allowlist `EDITABLE_FIELDS` của repository là bản thứ
    hai của cùng danh sách đó — hai chỗ phải cùng nói một chuyện.
    """

    title: str | None = Field(default=None, max_length=CONVERSATION_TITLE_MAX_CHARS)
    default_model: str | None = None
    #: `null` không có nghĩa (cột `NOT NULL`) → handler trả `400`. Khai
    #: `bool | None` chứ không `bool` để phân biệt được "vắng" với "gửi null":
    #: `bool` sẽ biến `pinned: null` thành `422` của pydantic, một câu trả lời
    #: đúng nhưng nói sai chuyện.
    pinned: bool | None = None
    #: §8.2 — chuyển nhánh. `null` = bỏ con trỏ, hội thoại hiện lại như rỗng.
    active_leaf_id: uuid.UUID | None = None


class ConversationOut(BaseModel):
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


class PathMessage(BaseModel):
    """Một message trên đường đi hiện tại, kèm vị trí giữa các anh em (C13).

    `sibling_index` đếm từ **0** (B-60): giao diện `‹ 2/3 ›` của §8.2 hiển thị
    `sibling_index + 1`. Hai số do SQL tính, FE không tự đếm.

    Không có `raw_response`, `tool_calls`, `prompt_tokens`, `heartbeat_at`:
    chúng là dữ liệu vận hành chứ không phải thứ màn chat cần, và thêm vào đây
    là mở một đường rò dữ liệu mà không ai xin.

    **`messages.py` dùng lại lớp này cho `GET /messages/{id}/siblings`** (T-1.13)
    thay vì chép danh sách trường sang file thứ hai. Một anh em *là* một node
    có thể trở thành đường đi ngay khi người dùng bấm `‹ 2/3 ›`, nên hai chỗ
    phải trả về đúng cùng một hình dạng — và quan trọng hơn, luật "ba cột này
    không được ra khỏi server" ở trên chỉ có một chỗ để đúng.
    """

    id: uuid.UUID
    parent_id: uuid.UUID | None
    role: MessageRole
    status: MessageStatus
    content: str
    reasoning: str | None
    model_id: str | None
    #: Mức suy luận worker đã GỬI cho lượt này (§24.2b·S4, T-S.6) — chip "model
    #: · mức" dưới bong bóng (T-S.15) đọc từ đây sau F5. `null` = không gửi
    #: tham số suy luận nào, và luôn `null` ở message `user`.
    reasoning_effort: str | None
    finish_reason: str | None
    error_code: str | None
    created_at: datetime
    sibling_index: int
    sibling_count: int
    #: Like/Dislike đã lưu (§18.2, T-3.7a). FE vẽ trạng thái hai nút **từ đây**,
    #: không từ một bản sao trong state của mình — F5 phải ra đúng thứ vừa bấm.
    #:
    #: `feedback_reason` **không** có mặt, cố ý: nó là trường tự do dài tới
    #: `FEEDBACK_REASON_MAX_CHARS`, và đường đi là thứ được tải lại mỗi lần mở
    #: một hội thoại. Hai nút sáng/tối chỉ cần một enum; ai vừa gõ lý do thì đã
    #: nhận lại nguyên văn trong response của chính `POST .../feedback`.
    feedback: MessageFeedback | None

    @classmethod
    def from_path_node(cls, node: PathNode) -> PathMessage:
        """Một node của `get_path`, hai con số anh em do SQL tính sẵn (§8.3)."""
        return cls.from_message(
            node.message,
            sibling_index=node.sibling_index,
            sibling_count=node.sibling_count,
        )

    @classmethod
    def from_message(cls, m: Message, *, sibling_index: int, sibling_count: int) -> PathMessage:
        """Liệt từng trường bằng tay, **không** `from_attributes`.

        `Message` có 20 cột và ba trong số đó (`raw_response`, `tool_calls`,
        `heartbeat_at`) không được ra khỏi server. Một model đọc thuộc tính tự
        động sẽ lặng lẽ nhận thêm cột mới ở migration sau; danh sách viết tay
        thì không đổi cho tới khi có người cố ý sửa nó.

        Hai con số anh em là tham số chứ không đọc từ `m`: chúng **không phải
        thuộc tính của message** (xem `PathNode`) — `get_path` tính chúng bằng
        LATERAL, còn `GET /messages/{id}/siblings` tính bằng vị trí trong danh
        sách đã sắp. Cùng kết quả, hai đường đi.
        """
        return cls(
            id=m.id,
            parent_id=m.parent_id,
            role=m.role,
            status=m.status,
            content=m.content,
            reasoning=m.reasoning,
            model_id=m.model_id,
            reasoning_effort=m.reasoning_effort,
            finish_reason=m.finish_reason,
            error_code=m.error_code,
            created_at=m.created_at,
            sibling_index=sibling_index,
            sibling_count=sibling_count,
            feedback=m.feedback,
        )


class ConversationDetail(ConversationOut):
    """`GET /conversations/{id}` — metadata + đường đi hiện tại (§18.2)."""

    #: Gốc trước, lá sau. Rỗng khi `active_leaf_id` là NULL.
    path: list[PathMessage]


class ConversationList(BaseModel):
    """`GET /conversations` — một trang, kèm con trỏ sang trang kế."""

    items: list[ConversationOut]
    #: `updated_at` của dòng cuối trang này; gửi lại vào `?updated_before=` để
    #: lấy trang kế. `null` = hết. **Không** trả tổng số dòng: đếm cả bảng mỗi
    #: lần mở sidebar là một câu quét mà không màn hình nào hiển thị kết quả.
    #: Luôn `null` ở `?pinned=true` — danh sách ấy không có trang kế.
    next_cursor: datetime | None
    #: T-S.8 — chỉ có nghĩa ở `?pinned=true`: `true` = số hội thoại ghim vượt
    #: `CONVERSATION_PINNED_MAX`, và `items` là đúng ngần ấy hàng mới nhất.
    #: Danh sách phân trang luôn `false` — phần còn lại của nó nói bằng
    #: `next_cursor`, không bằng cờ này.
    truncated: bool


@router.get(
    "/conversations",
    response_model=ConversationList,
    responses={
        400: {
            "model": ErrorEnvelope,
            "description": "pinned=true di kem limit/updated_before (BAD_REQUEST)",
        },
        422: {"model": ErrorEnvelope, "description": "limit ngoai khoang cho phep"},
    },
)
async def list_conversations(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    limit: Annotated[
        int | None,
        Query(
            ge=1,
            le=settings.CONVERSATION_PAGE_SIZE,
            description="so hoi thoai toi da; vang = CONVERSATION_PAGE_SIZE",
        ),
    ] = None,
    updated_before: Annotated[
        datetime | None,
        Query(description="next_cursor cua trang truoc"),
    ] = None,
    pinned: Annotated[
        bool | None,
        Query(description="true = moi hoi thoai ghim, mot lan; false = phan con lai"),
    ] = None,
) -> ConversationList:
    """Sidebar: mới nhất trước, phân trang bằng con trỏ `updated_at` (§17.4).

    **`?pinned=` — T-S.8, §24.2b·S8, NQ-112 (đóng B-227).** Sidebar có hai
    nguồn: mục "Đã ghim" hỏi `?pinned=true` và nhận **mọi** hội thoại ghim
    trong một response — không con trỏ, trần `CONVERSATION_PINNED_MAX` (vượt
    ⇒ đúng trần hàng mới nhất kèm `truncated: true`); phần còn lại hỏi
    `?pinned=false`, phân trang y hệt danh sách không lọc. Vắng tham số ⇒ mọi
    hội thoại, như trước T-S.8.

    Hai nhánh đi qua **cùng** `list_conversations` của repository, nên
    `WHERE user_id` nằm trong câu SQL ở cả nhánh không phân trang (Cạm bẫy ①).
    `pinned=false` chỉ thêm một vế `WHERE`: con trỏ vẫn là `updated_at`,
    `ORDER BY` không đổi (Cạm bẫy ②).

    `?pinned=true` kèm `limit` hoặc `updated_before` ⇒ `400`, không bỏ qua im
    lặng: danh sách ghim không có trang, và một tham số bị nuốt là thứ người
    gọi chỉ phát hiện khi đếm hàng.
    """
    if pinned is True:
        if limit is not None or updated_before is not None:
            raise ApiError(
                status.HTTP_400_BAD_REQUEST,
                ApiErrorCode.BAD_REQUEST,
                "pinned=true tra moi hoi thoai ghim mot lan; khong nhan limit/updated_before",
            )
        return await _pinned(user_id)

    page_size = settings.CONVERSATION_PAGE_SIZE if limit is None else limit
    async with session_scope() as session:
        rows = await ConversationRepository(session).list_conversations(
            user_id=user_id, limit=page_size, updated_before=updated_before, pinned=pinned
        )
        items = [ConversationOut.model_validate(row) for row in rows]

    # Trang chưa đầy ⇒ chắc chắn hết dữ liệu, khỏi mời client hỏi thêm một vòng
    # nữa chỉ để nhận về danh sách rỗng.
    has_more = len(items) == page_size
    return ConversationList(
        items=items,
        next_cursor=items[-1].updated_at if (items and has_more) else None,
        truncated=False,
    )


async def _pinned(user_id: uuid.UUID) -> ConversationList:
    """Mọi hội thoại ghim của `user_id`, một lần — nhánh `?pinned=true`.

    Hỏi **trần + 1** hàng: hàng thừa là cách duy nhất biết "vượt trần" mà
    không cần một câu `count(*)` thứ hai; nó bị cắt trước khi ra response.
    """
    cap = settings.CONVERSATION_PINNED_MAX
    async with session_scope() as session:
        rows = await ConversationRepository(session).list_conversations(
            user_id=user_id, limit=cap + 1, pinned=True
        )
        items = [ConversationOut.model_validate(row) for row in rows[:cap]]
    return ConversationList(items=items, next_cursor=None, truncated=len(rows) > cap)


@router.post(
    "/conversations",
    status_code=status.HTTP_201_CREATED,
    response_model=ConversationOut,
    responses={
        400: {"model": ErrorEnvelope, "description": "default_model khong co trong catalog"}
    },
)
async def create_conversation(
    body: CreateConversationRequest,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
) -> ConversationOut:
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
        out = ConversationOut.model_validate(conversation)
        await session.commit()
    return out


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetail,
    responses={404: {"model": ErrorEnvelope, "description": "Khong thay (§20 gop ba ca)"}},
)
async def get_conversation(
    conversation_id: uuid.UUID,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
) -> ConversationDetail:
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
        path = await _path(session, conversation, user_id=user_id)
        meta = ConversationOut.model_validate(conversation)

    return ConversationDetail(**meta.model_dump(), path=path)


@router.patch(
    "/conversations/{conversation_id}",
    response_model=ConversationDetail,
    responses={
        400: {"model": ErrorEnvelope, "description": "default_model la, hoac pinned=null"},
        404: {"model": ErrorEnvelope, "description": "Khong thay hoi thoai, hoac leaf la"},
    },
)
async def update_conversation(
    conversation_id: uuid.UUID,
    body: UpdateConversationRequest,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
) -> ConversationDetail:
    """Đổi tiêu đề, model mặc định, ghim, và **con trỏ nhánh** (§18.2, §8.2).

    Đây là đường CHUYỂN NHÁNH của T-1.13: `‹ 2/3 ›` trên màn hình chỉ là một
    `PATCH` đặt `active_leaf_id` sang id của anh em được chọn (lấy từ `GET
    /messages/{id}/siblings`). **Không xoá gì, không sửa message nào** — §8.2
    ghi đúng một dòng cho thao tác này: *"Chỉ đổi `active_leaf_id`"*.

    **Con trỏ dừng ở LÁ SÂU NHẤT của nhánh được chọn, không ở đúng id client
    gửi** (B-109, ngả (a) của NQ-35 — xem `_is_deepest`). Anh em được chọn có
    thể còn cả một đoạn hội thoại phía dưới, và `get_path` đi ngược từ con trỏ
    lên gốc nên đậu lại ở đó sẽ cắt cụt màn hình. Vì thế `active_leaf_id` trong
    response **có thể khác** id vừa gửi lên; nó là con số DB đang giữ, và đó là
    lý do cả FE lẫn test phải đọc nó từ response chứ không giả định. Node đã là
    lá thì hai con số bằng nhau — tức mọi lần chuyển nhánh giữa các anh em lá
    (Retry) không đổi gì so với trước.

    Trả về **cùng hình dạng với `GET /conversations/{id}`**, tức kèm cả đường
    đi mới, vì đường đi chính là thứ vừa đổi: bắt FE gọi thêm một `GET` ngay
    sau mỗi lần bấm mũi tên là hai vòng mạng cho một thao tác mà người dùng
    mong thấy đổi ngay.

    **Vắng mặt khác `null`** (cùng luật với `parent_id` của `POST
    .../messages`, đọc bằng `model_fields_set`): không gửi `title` là "đừng
    đụng tới tiêu đề", gửi `title: null` là "xoá tiêu đề". `default_model:
    null` = quay về model `default` của catalog; `active_leaf_id: null` = bỏ
    con trỏ, hội thoại hiện lại như lúc rỗng. `pinned: null` thì **không** có
    nghĩa nào (cột `NOT NULL`) nên nó là `400` chứ không phải một lần bỏ qua
    im lặng.

    Body rỗng `{}` là hợp lệ và không đổi gì — nó trả về trạng thái hiện tại,
    đúng như `GET`. Một `400 "phải gửi ít nhất một trường"` chỉ bắt FE viết
    thêm một nhánh `if` mà không ngăn được sai sót nào.
    """
    changes = {
        name: getattr(body, name) for name in body.model_fields_set if name in EDITABLE_FIELDS
    }
    if "pinned" in changes and changes["pinned"] is None:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            ApiErrorCode.BAD_REQUEST,
            "pinned khong nhan null; gui true hoac false",
        )
    new_model: str | None = changes.get("default_model")
    if new_model is not None and catalog.get_model(new_model) is None:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            ApiErrorCode.MODEL_UNKNOWN,
            f"model khong co trong catalog hoac da tat: {new_model}",
            details={"model_id": new_model},
        )

    async with session_scope() as session:
        conversations = ConversationRepository(session)
        conversation = await conversations.get_conversation(conversation_id, user_id=user_id)
        if conversation is None:
            raise ApiError(
                status.HTTP_404_NOT_FOUND,
                ApiErrorCode.CONVERSATION_NOT_FOUND,
                "khong tim thay hoi thoai",
            )

        if changes:
            await conversations.update_conversation(
                conversation_id, user_id=user_id, changes=changes
            )
        if "active_leaf_id" in body.model_fields_set:
            # B-109 ngả (a) — đi tiếp xuống lá sâu nhất của nhánh vừa chọn.
            unknown = await _is_deepest(session, body.active_leaf_id, user_id=user_id)
            try:
                await conversations.set_active_leaf(
                    conversation_id, user_id=user_id, message_id=unknown
                )
            except MessageNotInConversationError as exc:
                # §20: câu trả lời không nói message ấy có tồn tại ở hội thoại
                # khác hay không. Trỏ con trỏ nhánh sang cây của hội thoại khác
                # sẽ làm `get_path` dựng ra đường đi lẫn hai hội thoại (C11).
                raise ApiError(
                    status.HTTP_404_NOT_FOUND,
                    ApiErrorCode.LEAF_NOT_FOUND,
                    "active_leaf_id khong nam trong hoi thoai nay",
                ) from exc

        # Hai câu UPDATE ở trên đi THẲNG xuống DB (`synchronize_session=False`),
        # nên object `conversation` vẫn mang giá trị cũ và identity map sẽ trả
        # lại đúng nó nếu `get_conversation` được gọi lần nữa. `refresh` là
        # cách duy nhất đọc được thứ DB thực sự đang chứa — thiếu nó thì
        # response của mọi `PATCH` là ảnh chụp TRƯỚC khi sửa.
        await session.refresh(conversation)
        path = await _path(session, conversation, user_id=user_id)
        meta = ConversationOut.model_validate(conversation)
        await session.commit()

    return ConversationDetail(**meta.model_dump(), path=path)


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
        deleted = await ConversationRepository(session).soft_delete_conversation(
            conversation_id, user_id=user_id
        )
        if not deleted:
            raise ApiError(
                status.HTTP_404_NOT_FOUND,
                ApiErrorCode.CONVERSATION_NOT_FOUND,
                "khong tim thay hoi thoai",
            )
        await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _is_deepest(
    session: AsyncSession, leaf_id: uuid.UUID | None, *, user_id: uuid.UUID
) -> uuid.UUID | None:
    """`active_leaf_id` client gửi → lá SÂU NHẤT của nhánh đó (B-109, NQ-35).

    `PATCH` nhận id của **anh em được chọn** (FE lấy từ `GET
    /messages/{id}/siblings`), mà anh em ấy có thể còn cả một đoạn hội thoại
    phía dưới — đúng ca hay gặp nhất: sửa một câu hỏi ở giữa rồi bấm `‹` quay
    về bản cũ. `get_path` đi **ngược** từ con trỏ lên gốc, nên đặt con trỏ vào
    node đó sẽ dừng đường đi ngay tại câu hỏi cũ và câu trả lời của nó biến
    khỏi màn hình dù vẫn nằm nguyên trong DB. Đó là B-109.

    NQ-35 chốt ngả (a): chỗ đi tiếp là **API**, không phải client. Hai ngả kia
    bị bác vì (b) là N request theo độ sâu — đúng thứ §8.3 đã bác cho
    `get_path` — còn (c) (`siblings` trả kèm `leaf_id`) tạo ra hai chỗ hiểu
    "chuyển nhánh" khác nhau. Nhờ (a), `tree.ts` của FE **không phải sửa một
    dòng nào**: nó vẫn gửi `PATCH {active_leaf_id: sibling.id}` như từ T-1.13.

    Node không thấy được ⇒ trả lại **nguyên** id client gửi, để
    `set_active_leaf` ném `MessageNotInConversationError` và handler trả đúng
    `404 LEAF_NOT_FOUND` như trước. Một đường báo lỗi thứ hai ở đây sẽ chỉ để
    nói lại cùng một câu, và nói trước cả phép kiểm quyền sở hữu hội thoại.

    `null` đi thẳng qua: bỏ con trỏ nhánh không phải một lần chuyển nhánh.
    """
    if leaf_id is None:
        return None
    deepest = await MessageRepository(session).get_deepest_leaf(leaf_id, user_id=user_id)
    return leaf_id if deepest is None else deepest


async def _path(
    session: AsyncSession, conversation: Conversation, *, user_id: uuid.UUID
) -> list[PathMessage]:
    """`get_path(active_leaf_id)` → schema. `active_leaf_id` NULL ⇒ rỗng."""
    if conversation.active_leaf_id is None:
        return []
    nodes = await MessageRepository(session).get_path(conversation.active_leaf_id, user_id=user_id)
    return [PathMessage.from_path_node(node) for node in nodes]
