"""Năm endpoint message của §18.2: tạo một lượt chat, dừng nó, và ba thao tác CÂY.

    POST  /api/v1/conversations/{id}/messages   §7.2 ① — T-1.8
    POST  /api/v1/messages/{id}/cancel          §7.5   — T-1.9
    POST  /api/v1/messages/{id}/retry           §8.2   — T-1.13
    PATCH /api/v1/messages/{id}                 §8.2   — T-1.13
    GET   /api/v1/messages/{id}/siblings        §8.3   — T-1.13

KH tham chiếu: §7.2 ①, §7.5, §8.2, §8.3, §11.4, §18.2, §20 · CLAUDE.md A1, A2,
A3, A8.

**Đây là chỗ A1 được quyết định.** Handler này làm đúng bốn việc rồi trả lời:

    ① INSERT message(role=user,      parent_id=<lá client đang thấy>)
    ② INSERT message(role=assistant, parent_id=<user msg>, status='queued')
    ③ UPDATE conversations.active_leaf_id
    ④ arq.enqueue('generate', assistant_message_id)   → 202 + stream_url

Không có `await` nào tới model ở đây, và §7.2 ① chốt ngân sách thời gian là
**< 100 ms** (DoD của task nới thành < 200 ms để tính cả Nginx). Cám dỗ "gọi
model luôn cho nhanh, sau tách ra" chính là kiến trúc §3.1 đã bác bỏ: câu trả
lời khi đó sống bằng kết nối HTTP, và F5 giữa chừng là mất chữ — tức mất luôn
UC-03, mốc M3, và tiêu chí S3. `scripts/check_hardcode.sh` lệnh 1 canh chiều
này bằng một câu grep trên cả `backend/app/api/`.

**Bốn việc đó nằm trong MỘT transaction, và `enqueue` nằm TRONG nó.** Thứ tự
ấy quyết định ngả nào hỏng trước khi có chuyện:

- `enqueue` ném (Redis chết) → `async with session_scope()` đóng session →
  rollback → **không có message mồ côi**, người dùng nhận `503` và gửi lại
  được. Đây là dòng DoD "ép enqueue thất bại".
- commit ném *sau khi* `enqueue` đã xong → job tồn tại mà hàng không tồn tại →
  worker đọc `get_message_for_worker` ra `None`, ghi `MESSAGE_NOT_FOUND` rồi
  thôi. Vẫn không có hàng mồ côi, vẫn không tốn xu nào.

Ngả ngược lại (commit trước, enqueue sau) hỏng nặng hơn nhiều: enqueue trượt
là để lại hai message `queued` **vĩnh viễn** — reaper §7.6 chỉ dọn
`status='streaming'`, nên không ai nhặt chúng lên nữa.

Khe hở còn lại đã ghi vào Backlog B-91: worker có thể nhận job **trước** khi
transaction commit và thấy một message chưa tồn tại. Nó không làm hỏng dữ
liệu, chỉ làm lượt sinh đó chết oan.

**`parent_id`: có mặt và vắng mặt là hai chuyện khác nhau (C14).** Client gửi
kèm *cái lá nó đang nhìn thấy*; khác `active_leaf_id` hiện tại thì vẫn nhận —
đó **là** một nhánh hợp lệ theo §8.2 — nhưng response mang `branched: true` để
FE nói cho người dùng biết. Vắng hẳn `parent_id` nghĩa là "nối vào nhánh đang
xem", tức `active_leaf_id`. Phân biệt bằng `model_fields_set` chứ không bằng
`is None`, vì `parent_id: null` **cũng là một câu trả lời có nghĩa**: gốc của
một nhánh mới (§8.2 — một hội thoại có thể có nhiều gốc).

**Không dùng `Depends(get_session)`.** Cùng lý do với `stream.py`: dependency
kiểu `yield` chỉ đóng sau khi response đã gửi xong. Ở đây response ngắn nên
cái giá nhỏ hơn nhiều, nhưng để hai endpoint cùng một lối vào Postgres thì chỗ
đặt ranh giới transaction chỉ có một chỗ để đọc.

┌──────────────────────────────────────────────────────────────────────────┐
│  T-1.13 — BA THAO TÁC CÂY, VÀ MỘT CÂU DUY NHẤT CHÚNG PHẢI GIỮ            │
└──────────────────────────────────────────────────────────────────────────┘

**Không thao tác nào ở đây SỬA hay XOÁ một hàng đã có.** Cả ba đều chỉ *thêm*
node vào cây rồi dời `active_leaf_id`:

    retry  → thêm assistant ANH EM của message đang xem (cùng `parent_id`)
    PATCH  → thêm user ANH EM của message đang sửa, rồi assistant con của nó
    siblings → đọc, không ghi

Đó là cạm bẫy mà `tasks.md` T-1.13 gọi tên: *"cám dỗ 'xoá nhánh cũ cho gọn'.
Cả điểm của cây là giữ lại"*. `PATCH /messages/{id}` đặc biệt dễ hiểu sai —
tên method nói "sửa", nhưng §18.2 ghi rõ *"Sửa nội dung message user → tạo
nhánh mới"*, và `messages.content` của hàng cũ **không đổi một ký tự**. Nhánh
con phía dưới bản cũ vẫn nguyên và vẫn mở lại được bằng `active_leaf_id` cũ —
đó là dòng DoD thứ tư của task.

**Ba đường đều dùng lại `_mo_luot_sinh`**, tức đúng ba bước cuối của §7.2 ①
(assistant `queued` → dời `active_leaf_id` → `enqueue` **trong** transaction).
Viết lại ba lần là ba cơ hội để một trong ba quên `status='queued'` hoặc đẩy
job sau `commit`, và không test nào của hai đường kia bắt được.

**`retry` và `PATCH` trả `202` + `stream_url` y như `POST .../messages`,** vì
chúng tạo ra đúng cùng một thứ: một lượt sinh chưa có chữ nào. FE không cần
biết ba đường này khác nhau ở đâu — nó nhận `stream_url` rồi mở `EventSource`.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.conversations import MessageTrenDuongDi
from app.config import catalog
from app.config.settings import settings
from app.core.deps import (
    STATUSES_CAN_CHAT_SYSTEM_KEY,
    ensure_status_allowed,
    get_current_user_id,
    get_current_user_status,
    require_chat_access,
)
from app.core.errors import ApiError, ApiErrorCode, ErrorEnvelope
from app.core.queue import GENERATE_JOB_NAME, get_arq_pool
from app.core.ratelimit import gioi_han_chat, nha_ghe_sinh, nhan_ghe_sinh
from app.core.redis import get_redis
from app.db.models import Conversation, KeySource, Message, MessageRole, MessageStatus, UserStatus
from app.db.repositories import (
    ConversationRepository,
    MessageNotInConversationError,
    MessageRepository,
)
from app.db.session import session_scope
from app.llm.credentials import resolve_key_source
from app.quota.estimator import QuotaWarning, check_quota
from app.streaming.cancel import dat_co_huy

logger = logging.getLogger(__name__)

router = APIRouter(tags=["messages"])

#: Tên route của `GET /messages/{id}/stream` trong `stream.py`. `stream_url`
#: dựng bằng `url_path_for(...)` chứ không nội suy chuỗi: tiền tố `/api/v1`
#: sống ở `api/v1/__init__.py` và đường dẫn sống ở `stream.py`, nên chép lại
#: ở đây là tạo bản thứ ba sẽ lệch trong im lặng (A3 cùng tinh thần).
TEN_ROUTE_STREAM = "stream_message"

#: Tên route của chính `POST /conversations/{id}/messages`. `api/v1/__init__.py`
#: đọc nó để khai "route này BẮT BUỘC `Idempotency-Key`" (§11.4, A8) — tên
#: route chứ không phải đường dẫn, cùng lý do đã ghi ở hằng trên và ở
#: `app/core/idempotency.py::build_key`. FastAPI lấy tên route từ tên hàm, nên
#: đổi tên `create_message` mà quên hằng này là gỡ luật bắt buộc **trong im
#: lặng**; test `test_ten_route_khop_ham` canh đúng chiều đó.
TEN_ROUTE_TAO_MESSAGE = "create_message"

#: Hai luật của §10.6 áp cho ba route SINH CHỮ, dựng MỘT lần ở đây rồi gắn ba
#: chỗ — cùng lối `_idempotency` của `api/v1/__init__.py`.
#:
#: Hạn mức theo user (20/phút, nhóm `chat`) là một **dependency**: nó chỉ cần
#: `user_id` nên nó chạy được trước khi handler ghi dòng nào. Trần đồng thời
#: thì **không** thể là dependency — nó phải biết `message_id` của lượt sinh,
#: mà id đó chỉ tồn tại sau `INSERT`; nó sống trong `_mo_luot_sinh`.
_GIOI_HAN_CHAT = gioi_han_chat()

#: Ba route sinh chữ khai chung khối này. Viết một lần thay vì chép ba lần: hai
#: luật phải luôn đi cùng nhau, và một route thứ tư quên một trong hai là đúng
#: kiểu hỏng không ai thấy.
_ROUTE_SINH_CHU = [Depends(require_chat_access), Depends(_GIOI_HAN_CHAT)]


@dataclass(frozen=True, slots=True)
class LuotSinhMoi:
    """Thứ `_mo_luot_sinh` trả về: id của message assistant, cộng cảnh báo quota.

    Là một khối chứ không phải một `uuid.UUID` trần như trước T-2.11: ba
    endpoint sinh chữ đều phải mang cảnh báo của UC-07 ra body, và cảnh báo ấy
    chỉ tính được ở **trong** hàm đã đọc hai cửa sổ. Trả thêm một giá trị thứ
    hai rẻ hơn nhiều so với để ba handler tự gọi lại `check_quota` — đọc Redis
    hai lần cho một request là hai câu trả lời có thể khác nhau.
    """

    assistant_message_id: uuid.UUID
    quota_warning: QuotaWarning | None


class TaoMessageRequest(BaseModel):
    """Body của §18.2. Ba trường, hai trong đó là tuỳ chọn có ý nghĩa riêng."""

    #: Nội dung người dùng gõ. `min_length=1` vì một lượt rỗng không cho model
    #: thêm thông tin nào mà vẫn tốn một lượt sinh — và `llm/context.py::_to_wire`
    #: sẽ lặng lẽ loại nó khỏi ngữ cảnh, để lại một hoá đơn không có câu hỏi.
    #:
    #: `max_length` là **cửa chặn đầu tiên** của B-205/NQ-78, và nó phải nằm ở
    #: đây chứ không ở FE: nginx cho qua tới 25 MB, nên một trần chỉ có trong ô
    #: nhập thì `curl` đi vòng qua được. Trước bản vá, thứ chặn đầu tiên là
    #: `token_budget()` của §9.6 — tức một lần dán quá dài tạo xong **hai** hàng
    #: `messages`, tiêu một lượt `Idempotency-Key`, rồi mới nổ `CONTEXT_TOO_LARGE`
    #: ở `llm/context.py` giữa lượt sinh. Nay nó là `422` ở biên vào, chưa chạm
    #: Postgres.
    content: str = Field(min_length=1, max_length=settings.MESSAGE_MAX_CHARS)
    #: C14 — lá client **đang thấy**. Vắng ⇒ dùng `active_leaf_id`; có (kể cả
    #: `null`) ⇒ dùng đúng giá trị đó. Xem docstring module.
    parent_id: uuid.UUID | None = None
    #: Vắng ⇒ `conversations.default_model` ⇒ model `default` của catalog (§9.2).
    model_id: str | None = None


class TaoMessageResponse(BaseModel):
    """`202` của §7.2 ①, cộng cờ `branched` của C14."""

    user_message_id: uuid.UUID
    assistant_message_id: uuid.UUID
    #: Đường dẫn TƯƠNG ĐỐI tới SSE. Tương đối vì `location /api/` trong
    #: `config/nginx/nginx.conf` không gửi `X-Forwarded-Proto`, nên một URL
    #: tuyệt đối dựng từ request sẽ ra `http://` trong khi người dùng đang ở
    #: `https://`; và vì FE đã nói chuyện với API qua `VITE_API_BASE_URL`
    #: (`/api/v1`) trên cùng origin.
    stream_url: str
    #: `true` = `parent_id` client gửi lên khác `active_leaf_id` lúc nhận
    #: request, tức vừa mở một nhánh. Không phải lỗi — xem C14.
    branched: bool
    #: UC-07 dòng 1 — *"Còn ≤ 20% quota → hiện thanh cảnh báo, không chặn"*.
    #: `null` là ca thường: còn nhiều tiền thì không có gì để nói. Xem
    #: `app/quota/estimator.py::QuotaWarning` cho bốn con số bên trong.
    quota_warning: QuotaWarning | None = None


@router.post(
    "/conversations/{conversation_id}/messages",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TaoMessageResponse,
    # §11.1 (T-2.7) + §10.6 (T-2.9) — xem `_ROUTE_SINH_CHU`.
    dependencies=_ROUTE_SINH_CHU,
    responses={
        400: {
            "model": ErrorEnvelope,
            "description": "model_id khong co trong catalog, hoac thieu Idempotency-Key",
        },
        409: {"model": ErrorEnvelope, "description": "Mot request cung khoa dang chay (§11.4)"},
        429: {
            "model": ErrorEnvelope,
            "description": "Qua 20 luot/phut (RATE_LIMITED), da co "
            "MAX_CONCURRENT_STREAMS luot sinh chua khep (TOO_MANY_STREAMS) — §10.6, "
            "hoac het han muc chi tieu (QUOTA_EXCEEDED) — §10.2",
        },
        404: {"model": ErrorEnvelope, "description": "Hoi thoai hoac parent_id khong thay"},
        503: {"model": ErrorEnvelope, "description": "Khong day duoc job vao hang doi"},
    },
)
async def create_message(
    request: Request,
    conversation_id: uuid.UUID,
    body: TaoMessageRequest,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    user_status: Annotated[UserStatus | None, Depends(get_current_user_status)],
) -> TaoMessageResponse:
    """Ghi hai message, dời con trỏ nhánh, đẩy job, trả `202`. Không gọi model.

    `Idempotency-Key` (§11.4, A8) **không** xuất hiện trong chữ ký này nữa kể
    từ T-2.8: cả phép kiểm lẫn việc lưu response sống ở
    `app/core/idempotency.py` và được gắn ở `api/v1/__init__.py`. Handler
    không biết header đó tồn tại, đúng như nó không biết `require_app_access`
    tồn tại — một luật gắn theo router chỉ giữ được tính chất "không ai quên"
    khi không endpoint nào phải nhắc tới nó.
    """
    async with session_scope() as session:
        conversations = ConversationRepository(session)
        messages = MessageRepository(session)

        conversation = await conversations.get_conversation(conversation_id, user_id=user_id)
        if conversation is None:
            # §20: "không có", "đã xoá" và "của người khác" trả cùng một câu.
            raise ApiError(
                status.HTTP_404_NOT_FOUND,
                ApiErrorCode.CONVERSATION_NOT_FOUND,
                "khong tim thay hoi thoai",
            )

        model = _chon_model(body.model_id, conversation.default_model)

        # C14 — đọc `active_leaf_id` TRƯỚC khi ghi đè nó, nếu không `branched`
        # luôn là `False` (so một giá trị với chính nó).
        leaf_hien_tai = conversation.active_leaf_id
        parent_id = body.parent_id if "parent_id" in body.model_fields_set else leaf_hien_tai
        branched = parent_id != leaf_hien_tai

        try:
            user_message = await messages.create_message(
                conversation_id=conversation_id,
                user_id=user_id,
                role=MessageRole.USER,
                parent_id=parent_id,
                content=body.content,
            )
        except MessageNotInConversationError as loi:
            raise ApiError(
                status.HTTP_404_NOT_FOUND,
                ApiErrorCode.PARENT_NOT_FOUND,
                "parent_id khong nam trong hoi thoai nay",
            ) from loi

        # Hai UUID lấy ra TRƯỚC khi session đóng: `Message` sau đó là object
        # detached, và đọc thuộc tính của nó ngoài session là chỗ sinh
        # `DetachedInstanceError` nếu có ai lỡ bật `expire_on_commit`.
        uid = user_message.id
        luot = await _mo_luot_sinh(
            session=session,
            messages=messages,
            conversations=conversations,
            conversation_id=conversation_id,
            user_id=user_id,
            user_status=user_status,
            parent_id=uid,
            model=model,
        )
        await session.commit()

    return TaoMessageResponse(
        user_message_id=uid,
        assistant_message_id=luot.assistant_message_id,
        stream_url=_stream_url(request, luot.assistant_message_id),
        branched=branched,
        quota_warning=luot.quota_warning,
    )


def _stream_url(request: Request, message_id: uuid.UUID) -> str:
    """Đường dẫn SSE của một message — xem docstring `TaoMessageResponse`."""
    return str(request.app.url_path_for(TEN_ROUTE_STREAM, message_id=str(message_id)))


async def _mo_luot_sinh(
    *,
    session: AsyncSession,
    messages: MessageRepository,
    conversations: ConversationRepository,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    user_status: UserStatus | None,
    parent_id: uuid.UUID | None,
    model: catalog.ModelEntry,
) -> LuotSinhMoi:
    """Bốn bước cuối của §7.2 ① — assistant `queued`, dời lá, KIỂM QUOTA, đẩy job.

    Dùng chung cho cả ba đường tạo một lượt sinh (`POST .../messages`,
    `retry`, `PATCH /messages/{id}`). Thứ tự bên trong là hợp đồng, không phải
    phong cách — xem docstring module: `enqueue` nằm **trong** transaction của
    caller và caller `commit()` sau khi hàm này trả về.

    Nhận cả `ModelEntry` chứ không chỉ `model.id` kể từ T-2.11: cửa chặn
    §10.2 cần `max_output` và giá của model, và tra lại catalog từ một chuỗi
    `id` ngay bên trong hàm là làm hai lần một việc caller vừa làm xong
    (`_chon_model`).

    **Nhận thêm `user_status` kể từ T-2.15, và đó là chỗ B-140 được đóng.**
    `require_chat_access` gắn ở route chạy **trước** khi body được đọc, nên nó
    chỉ hỏi được "người này có khoá **nào đó** không". Câu đúng của §11.1 là
    "có khoá cho provider của model **đang gọi** không", và chỗ duy nhất trả
    lời được là đây — sau `_chon_model`. Hai lớp, thô rồi tinh: lớp ngoài chặn
    sớm mà không cần đọc DB thêm cho `active`, lớp trong chặn đúng.

    Trả `id` của message assistant vừa tạo, đọc ra **trước** khi session đóng,
    cộng cảnh báo quota của UC-07 (có thể `None`).

    Raise:
        ApiError 403 `PENDING_APPROVAL`: trạng thái chỉ chat được bằng khoá
            riêng (§11.1), mà lượt này lại đi bằng system key vì chưa có khoá
            dùng được cho provider của model đã chọn (B-140).
        ApiError 404 `PARENT_NOT_FOUND`: `parent_id` không nằm trong hội thoại
            này (hoặc vừa bị xoá mềm). Với `POST .../messages` ca này không thể
            xảy ra — cha là message vừa ghi ở dòng trên — nhưng `retry` thì có:
            nó nhận `parent_id` từ một hàng đã tồn tại từ trước.
        ApiError 429 `TOO_MANY_STREAMS`: người này đã có
            `MAX_CONCURRENT_STREAMS` lượt sinh chưa khép (§10.6, T-2.9).
        ApiError 429 `QUOTA_EXCEEDED`: dự toán xấu nhất của lượt này cộng chi
            tiêu đã có vượt hạn mức 5 giờ hoặc 7 ngày (§10.2, T-2.11) — chỉ
            trên nhánh system key.
        ApiError 503 `ENQUEUE_FAILED`: xem `_day_job`.
    """
    # §10.5 — ai trả tiền cho lượt này. Hỏi TRƯỚC `create_message`: cả hai
    # phép kiểm ngay dưới đều có thể ném, và ném trước khi ghi nghĩa là không
    # có hàng nào phải rollback (cùng tinh thần với thứ tự quota/ghế bên dưới).
    key_source = await resolve_key_source(session, user_id=user_id, model=model)

    # B-140 — phép kiểm §11.1 CHÍNH XÁC, xem docstring. Bảng vẫn sống ở
    # `core/deps.py`: ở đây chỉ hỏi nó, bằng đúng hàm mà `POST /auth/login`
    # dùng. Nhánh tạm Phase 1 (`user_status is None`) đi thẳng qua, y như
    # `require_status` cho nó đi qua — xem `get_current_user_status`.
    if user_status is not None and key_source is KeySource.SYSTEM:
        ensure_status_allowed(user_status, STATUSES_CAN_CHAT_SYSTEM_KEY)

    try:
        assistant = await messages.create_message(
            conversation_id=conversation_id,
            user_id=user_id,
            role=MessageRole.ASSISTANT,
            parent_id=parent_id,
            # `queued` là trạng thái worker đòi thấy (`mark_streaming` có
            # `WHERE status='queued'`); mặc định của cột là `completed`, nên
            # quên dòng này là tạo một message assistant rỗng mà DB coi như đã
            # xong — nó sẽ đi thẳng vào ngữ cảnh của lượt sau.
            status=MessageStatus.QUEUED,
            # Model chốt **tại đây**, không phải lúc worker chạy: đổi model mặc
            # định giữa lúc job còn trong hàng đợi không được đổi model của một
            # câu hỏi đã gửi. Worker đọc lại đúng cột này (§7.2 ③).
            model_id=model.id,
        )
    except MessageNotInConversationError as loi:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            ApiErrorCode.PARENT_NOT_FOUND,
            "parent_id khong nam trong hoi thoai nay",
        ) from loi

    # A2: con trỏ nhánh trỏ vào message ASSISTANT, không phải message user.
    # Lượt sau nối tiếp sau câu trả lời, và `context.build` đi ngược từ chính
    # nó (nó tự rơi khỏi ngữ cảnh vì `status='queued'`).
    await conversations.set_active_leaf(conversation_id, user_id=user_id, message_id=assistant.id)

    amid = assistant.id

    # §10.2 cửa TRƯỚC (T-2.11). Đứng **trước** `nhan_ghe_sinh` chứ không sau,
    # và thứ tự ấy là hợp đồng: ghế bận nhả bằng phép đối chiếu Postgres sau
    # `PHANTOM_GRACE_S`, nên từ chối *sau* khi đã nhận ghế là khoá một ghế 60
    # giây cho một lượt sinh chưa từng tồn tại. Cửa quota thì không để lại gì
    # khi nó ném — nó chỉ đọc.
    #
    # Và ở **đây** chứ không ở một dependency, cùng lý do với ghế: phép ước
    # tính cần đúng ngữ cảnh worker sắp gửi, mà ngữ cảnh ấy đi từ `amid` —
    # một id chỉ ra đời sau `create_message` phía trên.
    #
    # **BYOK bỏ qua HẲN cửa này (§10.5, B-157)** — không phải "ước tính rồi
    # tha": tiền của lượt này không phải tiền của người vận hành, nên không
    # có hạn mức nào để so. Bỏ qua cả phép đọc Redis luôn, vì một `read_window`
    # ở đây chỉ để vứt đi là một lần `503` không đáng có khi Redis chớp. Cảnh
    # báo UC-07 cũng vắng mặt: thanh "còn ~X USD" nói về quota hệ thống, và
    # hiện nó cho một lượt không trừ quota là nói sai. Rate limit của §10.6
    # thì **vẫn** áp — nó là dependency của route, không đi qua đây.
    canh_bao = None
    if key_source is KeySource.SYSTEM:
        canh_bao = await check_quota(session, user_id=user_id, leaf_id=amid, model=model)

    # §10.6 hàng "Đồng thời" (T-2.9, B-85, NQ-49). Ở **đây** chứ không ở một
    # dependency vì phép kiểm cần `message_id`, mà id đó chỉ ra đời ở dòng
    # `create_message` phía trên. Và **trước** `_day_job` chứ không sau: ném từ
    # đây làm cả transaction của caller rollback, nên một lượt bị từ chối không
    # để lại hàng `messages` nào — còn từ chối sau khi job đã vào hàng đợi thì
    # worker vẫn sinh chữ và vẫn tính tiền.
    await nhan_ghe_sinh(messages, user_id=user_id, message_id=amid)

    try:
        await _day_job(amid)
    except BaseException:
        # Transaction sắp rollback, nên hàng `messages` mang `amid` sẽ không
        # bao giờ tồn tại — nhả ghế ngay thay vì để phép đối chiếu Postgres
        # phát hiện nó là rác sau `PHANTOM_GRACE_S`. Bắt `BaseException` vì
        # `asyncio.CancelledError` (client ngắt giữa chừng) cũng để lại đúng
        # một cái ghế trỏ vào hư không.
        await nha_ghe_sinh(user_id=user_id, message_id=amid)
        raise
    return LuotSinhMoi(assistant_message_id=amid, quota_warning=canh_bao)


def _chon_model(*uu_tien: str | None) -> catalog.ModelEntry:
    """Duyệt các mức ưu tiên theo đúng thứ tự truyền vào, cuối cùng là catalog.

    `POST .../messages` truyền hai mức (request → `conversations.default_model`);
    `retry` truyền ba, chèn `messages.model_id` của chính câu trả lời đang thử
    lại vào giữa — bấm Retry mà không chọn gì phải sinh lại bằng **đúng model
    cũ**, không phải bằng model mặc định của hội thoại. Thứ tự là tham số chứ
    không phải điều kiện `if` nằm trong hàm: mỗi endpoint tự nói mức của mình.

    `get_model` lọc luôn `enabled`, nên một model bị tắt trong catalog sẽ dừng
    được mọi mức — kể cả khi nó còn nằm trong `conversations.default_model`
    của một hội thoại cũ, hoặc trong `model_id` của một câu trả lời cũ. Đó là
    điểm của cái công tắc ở §9.2: tắt một provider đang hỏng phải có hiệu lực
    ngay, không đợi ai sửa dữ liệu.

    Raise:
        ApiError 400 `MODEL_UNKNOWN`: request (hoặc hội thoại) chỉ đích danh
            một model không còn dùng được. Nói thẳng tên model trong thông
            điệp: nó đến từ chính người gọi và có trong `GET /models`.
        ApiError 503 `NO_MODEL_AVAILABLE`: không ai chỉ đích danh, mà model
            `default` cũng đã tắt. Đây là sự cố cấu hình phía server (5xx),
            không phải lỗi của request (4xx).
    """
    for nguon in uu_tien:
        if nguon:
            model = catalog.get_model(nguon)
            if model is None:
                raise ApiError(
                    status.HTTP_400_BAD_REQUEST,
                    ApiErrorCode.MODEL_UNKNOWN,
                    f"model khong co trong catalog hoac da tat: {nguon}",
                    details={"model_id": nguon},
                )
            return model

    mac_dinh = catalog.get_default_model()
    if mac_dinh is None:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ApiErrorCode.NO_MODEL_AVAILABLE,
            "khong co model nao dang bat trong catalog",
        )
    return mac_dinh


async def _day_job(assistant_message_id: uuid.UUID) -> None:
    """§7.2 ① bước cuối: `arq.enqueue('generate', assistant_message_id)`.

    Payload chỉ có một khoá chính, không có nội dung câu hỏi: hai message đã
    nằm trong Postgres trước khi hàm này chạy, nên nhét chữ vào payload là tạo
    nguồn sự thật thứ hai nằm trong Redis — đúng thứ C5 cấm — và làm hàng đợi
    phình theo độ dài hội thoại.

    **Hai ngả hỏng, một mã lỗi.** `enqueue_job` ném (Redis chết) hoặc trả
    `None` (arq từ chối vì trùng `_job_id`) — cả hai đều là "job không vào được
    hàng đợi", và cả hai đều phải thành `503 ENQUEUE_FAILED` chứ không phải
    `500`: Redis hỏng là sự cố **phụ thuộc**, tức có thể thử lại, và FE cần
    phân biệt nó với một lỗi lập trình. Ném `ApiError` từ trong `async with
    session_scope()` là thứ làm transaction rollback — xem docstring module.

    **`_job_id` là `assistant_message_id`** (B-92, T-2.8). arq từ chối một
    `_job_id` đã có mặt và trả `None`, nên đẩy **cùng một message** hai lần trở
    thành vô hại: không có lượt sinh thứ hai, không có hoá đơn thứ hai. Đây là
    lớp phòng thủ **thứ hai**, độc lập với `Idempotency-Key` của §11.4 — cái
    kia chặn ở mức *request* (hai lần bấm Gửi), cái này chặn ở mức *job* (một
    message, hai lần enqueue), và hai mức đó hỏng vì hai lý do khác nhau.
    Không thay được nhau: khoá job-id của arq chỉ sống theo `keep_result`, hết
    hạn thì `_job_id` cũ dùng lại được, còn khoá `idem:` sống đủ 24 giờ.

    Giá trị lấy thẳng từ khoá chính của hàng `messages` chứ không sinh riêng:
    một UUID mới cho mỗi lần enqueue là đúng thứ làm lớp chống trùng này vô
    nghĩa, và `assistant_message_id` đã là thứ duy nhất trên dây (xem đoạn
    payload ở trên) nên không cần thêm nguồn sự thật nào.
    """
    try:
        pool = await get_arq_pool()
        job = await pool.enqueue_job(
            GENERATE_JOB_NAME, str(assistant_message_id), _job_id=str(assistant_message_id)
        )
    except Exception as loi:
        # KHÔNG nuốt: log kèm traceback rồi đổi thành mã FE đọc được. Không có
        # dòng này thì nguyên nhân thật ("redis:6379 không phân giải được") chỉ
        # còn trong một `INTERNAL_ERROR` không ai truy được.
        logger.exception("khong day duoc job generate cho message %s", assistant_message_id)
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ApiErrorCode.ENQUEUE_FAILED,
            "khong day duoc job vao hang doi",
        ) from loi

    if job is None:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ApiErrorCode.ENQUEUE_FAILED,
            "hang doi tu choi job",
        )


# ══════════════════════ §7.5 — huỷ giữa chừng (T-1.9) ══════════════════════


#: Hai trạng thái còn có gì để dừng. Ba trạng thái còn lại (`completed`,
#: `failed`, `cancelled`) là ba ngả đã khép: bấm Dừng ở đó vẫn trả `200` nhưng
#: **không** đặt cờ — xem docstring `cancel_message`.
TRANG_THAI_CON_DUNG_DUOC = frozenset({MessageStatus.QUEUED, MessageStatus.STREAMING})


class HuyResponse(BaseModel):
    """`200` của `POST /messages/{id}/cancel`. §18.2 không ghi hình dạng body.

    Ba trường vì FE cần phân biệt hai lần bấm Dừng khác nhau: lần trúng một
    lượt đang sinh (`cancel_requested: true` — nút chuyển sang "đang dừng…") và
    lần bấm khi chữ vừa chảy hết (`false` — không hiện gì cả, câu trả lời đã
    xong rồi). Không có trường nào nói "đã dừng xong": lúc response về, worker
    còn chưa kịp đọc cờ. Sự thật đó tới qua event `done` của SSE (§7.4).
    """

    message_id: uuid.UUID
    #: Trạng thái **lúc nhận request**, đọc từ Postgres. Không phải trạng thái
    #: sau khi huỷ — `cancelled` chỉ xuất hiện khi worker đã ghi nó.
    status: MessageStatus
    #: `true` = đã đặt cờ `cancel:{id}`; `false` = không có gì để dừng.
    cancel_requested: bool


@router.post(
    "/messages/{message_id}/cancel",
    status_code=status.HTTP_200_OK,
    response_model=HuyResponse,
    responses={
        404: {"model": ErrorEnvelope, "description": "Message khong thay (§20 gop ba ca)"},
        503: {"model": ErrorEnvelope, "description": "Khong dat duoc co huy (Redis hong)"},
    },
)
async def cancel_message(
    message_id: uuid.UUID,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
) -> HuyResponse:
    """`SET cancel:{id} 1 EX CANCEL_TTL_S` — §7.5. Không đụng Postgres.

    **A1 ở đây cũng như ở `stream.py`:** handler không dừng cái gì cả. Nó dựng
    một lá cờ và trả lời ngay; người dừng vòng lặp là `workers/generate.py`,
    và người ghi `status='cancelled'` xuống Postgres cũng là worker. Ngả ngược
    lại — API tự `UPDATE messages SET status='cancelled'` — tạo hai người cùng
    ghi một hàng: worker đang sinh sẽ ghi đè lại bằng `completed` vài giây sau,
    và nút Dừng trở thành thứ đôi khi có tác dụng.

    **Idempotent theo đúng nghĩa của DoD:** bấm Dừng trên một message đã
    `completed`/`failed`/`cancelled` trả `200` và **không** đặt cờ. Không đặt
    chứ không phải đặt-rồi-kệ: một khoá `cancel:{id}` cho một message đã xong
    là rác sống `CANCEL_TTL_S` giây, và nếu T-1.13 cho `retry` dùng lại cùng
    `message_id` thì nó là một quả mìn hẹn giờ. Đặt cờ hai lần trên một lượt
    **đang** sinh thì vô hại và có ích — `SET` gia hạn TTL, xem `cancel.py`.

    **404 chứ không 403 (§20)**, cùng lối với `stream.py`: "không tồn tại", "đã
    xoá mềm" và "của người khác" trả về cùng một câu.
    """
    async with session_scope() as session:
        message = await MessageRepository(session).get_message(message_id, user_id=user_id)
        if message is None:
            raise ApiError(
                status.HTTP_404_NOT_FOUND,
                ApiErrorCode.MESSAGE_NOT_FOUND,
                "khong tim thay message",
            )
        trang_thai = message.status

    if trang_thai not in TRANG_THAI_CON_DUNG_DUOC:
        logger.info(
            "cancel: %s dang o trang thai %s — khong con gi de dung (§7.5)",
            message_id,
            trang_thai.value,
        )
        return HuyResponse(message_id=message_id, status=trang_thai, cancel_requested=False)

    try:
        await dat_co_huy(get_redis(), message_id, ttl_s=settings.CANCEL_TTL_S)
    except Exception as loi:
        # Cùng lý lẽ với `_day_job`: Redis chết là sự cố *phụ thuộc*, tức thử
        # lại được. Nguyên nhân thật đi vào log kèm traceback; FE nhận một mã
        # nó phân nhánh được thay vì một `INTERNAL_ERROR` không ai truy ra.
        logger.exception("khong dat duoc co huy cho message %s", message_id)
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ApiErrorCode.CANCEL_FAILED,
            "khong dat duoc co huy",
        ) from loi

    logger.info("cancel: da dat co cho %s (status=%s)", message_id, trang_thai.value)
    return HuyResponse(message_id=message_id, status=trang_thai, cancel_requested=True)


# ════════════════════ §8.2 — thao tác CÂY (T-1.13) ════════════════════════


class RetryRequest(BaseModel):
    """Body của `POST /messages/{id}/retry`. Toàn bộ body là tuỳ chọn.

    "Bấm Retry" (UC-04) gửi thân rỗng hoặc không gửi thân nào; "Đổi model &
    retry" (T-3.7) gửi `model_id`. Không có `content` ở đây: retry sinh lại
    **cùng một câu hỏi**, câu hỏi nằm ở message cha và không ai đụng vào nó.
    """

    #: Vắng ⇒ dùng lại `messages.model_id` của chính câu trả lời đang thử lại
    #: (xem `_chon_model`), rồi mới tới `conversations.default_model`.
    model_id: str | None = None


class RetryResponse(BaseModel):
    """`202` của retry — cùng hình dạng với `TaoMessageResponse` trừ hai chỗ.

    Không có `user_message_id`: retry **không** tạo message user nào, nó chỉ
    thêm một câu trả lời anh em cho câu hỏi đã có. Không có `branched`: cờ đó
    trả lời câu hỏi của C14 ("client gửi `parent_id` khác lá đang xem không"),
    còn retry thì *luôn* mở một nhánh — một cờ hằng `true` là một cờ vô dụng.

    `model_id` có mặt vì nó là thứ người dùng vừa đổi ở "Đổi model & retry" và
    là thứ FE phải hiện dưới bong bóng mới; bắt nó đợi tới `done` của SSE để
    biết mình vừa gọi model nào là một vòng chờ không cần thiết.
    """

    assistant_message_id: uuid.UUID
    stream_url: str
    model_id: str
    #: UC-07 dòng 1 — *"Còn ≤ 20% quota → hiện thanh cảnh báo, không chặn"*.
    #: `null` là ca thường: còn nhiều tiền thì không có gì để nói. Xem
    #: `app/quota/estimator.py::QuotaWarning` cho bốn con số bên trong.
    quota_warning: QuotaWarning | None = None


class SuaMessageRequest(BaseModel):
    """Body của `PATCH /messages/{id}` — chỉ nội dung mới của câu hỏi.

    `min_length=1` cùng lý do với `TaoMessageRequest.content`: sửa thành rỗng
    là trả tiền cho một lượt sinh không có câu hỏi. `max_length` cũng vậy —
    B-205 đếm được **hai** schema thiếu trần, và một nhánh sửa nội dung không
    có trần là đúng đường vòng mà bản vá này đang đóng.

    **Không có `model_id`.** §18.2 ghi endpoint này là "Sửa nội dung message
    user → tạo nhánh mới", và `tasks.md` T-1.13 chỉ cho retry quyền đổi model.
    Nhánh mới dùng `conversations.default_model` như một lượt chat bình thường.
    """

    content: str = Field(min_length=1, max_length=settings.MESSAGE_MAX_CHARS)


class SuaMessageResponse(BaseModel):
    """`202` của `PATCH /messages/{id}`.

    `user_message_id` là **message MỚI**, không phải `{id}` trong đường dẫn:
    hàng cũ còn nguyên, còn đây là bản đã sửa nằm cạnh nó (§8.2). FE phải trỏ
    màn hình sang id này, nếu không nó sẽ hiện lại chính câu hỏi cũ.
    """

    user_message_id: uuid.UUID
    assistant_message_id: uuid.UUID
    stream_url: str
    #: UC-07 dòng 1 — *"Còn ≤ 20% quota → hiện thanh cảnh báo, không chặn"*.
    #: `null` là ca thường: còn nhiều tiền thì không có gì để nói. Xem
    #: `app/quota/estimator.py::QuotaWarning` cho bốn con số bên trong.
    quota_warning: QuotaWarning | None = None


class AnhEmResponse(BaseModel):
    """`GET /messages/{id}/siblings` — mọi nhánh cùng cha, đã sắp thứ tự (§8.3).

    Bốn trường đầu là để FE vẽ `‹ 2/3 ›` mà **không phải tự đếm** — đó là toàn
    bộ nội dung của C13. `sibling_index` đếm từ **0** (B-60), khớp với
    `PathNode` của T-1.2 và `GET /conversations/{id}`; `‹ n/m ›` hiện
    `sibling_index + 1` trên `sibling_count`.

    `items` chứa **cả** message được hỏi. "Một message không có anh em" ra
    `sibling_count == 1`, không phải 0 — cùng quy ước với `_sibling_stats` của
    repository, và hai chỗ lệch nhau là C13 ở dạng khó tìm nhất.
    """

    message_id: uuid.UUID
    #: `null` khi message là gốc một nhánh — và đó là ca quan trọng nhất: sửa
    #: câu hỏi ĐẦU TIÊN tạo ra nhiều gốc trong cùng hội thoại (§8.2).
    parent_id: uuid.UUID | None
    sibling_index: int
    sibling_count: int
    items: list[MessageTrenDuongDi]


@router.post(
    "/messages/{message_id}/retry",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=RetryResponse,
    # §11.1 (T-2.7) + §10.6 (T-2.9) — xem `_ROUTE_SINH_CHU`.
    dependencies=_ROUTE_SINH_CHU,
    responses={
        400: {"model": ErrorEnvelope, "description": "Khong phai assistant, hoac model_id la"},
        404: {"model": ErrorEnvelope, "description": "Message khong thay (§20 gop ba ca)"},
        409: {"model": ErrorEnvelope, "description": "Luot sinh cu con dang chay"},
        429: {
            "model": ErrorEnvelope,
            "description": "Qua 20 luot/phut (RATE_LIMITED), da co "
            "MAX_CONCURRENT_STREAMS luot sinh chua khep (TOO_MANY_STREAMS) — §10.6, "
            "hoac het han muc chi tieu (QUOTA_EXCEEDED) — §10.2",
        },
        503: {"model": ErrorEnvelope, "description": "Khong day duoc job vao hang doi"},
    },
)
async def retry_message(
    request: Request,
    message_id: uuid.UUID,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    user_status: Annotated[UserStatus | None, Depends(get_current_user_status)],
    body: RetryRequest | None = None,
) -> RetryResponse:
    """Sinh lại một câu trả lời thành ANH EM của nó — §8.2, UC-04.

    Câu trả lời cũ **ở lại nguyên vẹn**: cùng `content`, cùng `model_id`, cùng
    `status`. Người dùng bấm `‹ 1/2 ›` là quay về được nó, và đó là lý do duy
    nhất cây message tồn tại (§8.1).

    **`parent_id` của bản mới chép từ bản cũ, không phải từ `active_leaf_id`.**
    Retry một câu trả lời ở *giữa* hội thoại (sau khi đã cuộn ngược lên) phải
    mọc nhánh ngay tại đó; lấy lá đang xem sẽ dán câu trả lời mới vào cuối hội
    thoại như thể người dùng vừa hỏi lại — sai cả cây lẫn ngữ cảnh gửi model.

    **Hai phép kiểm trước khi ghi bất cứ thứ gì:**

    - `role` phải là `assistant` → `400 MESSAGE_ROLE_MISMATCH`. Retry một
      message user không có nghĩa: câu hỏi thì sinh lại làm gì, và đường sửa
      câu hỏi là `PATCH /messages/{id}` ngay bên dưới.
    - `status` không được còn `queued`/`streaming` → `409
      GENERATION_IN_PROGRESS`. Lượt cũ chưa khép mà mở lượt mới là hai job
      cùng sinh cho một `parent_id`, hoá đơn trả hai lần, và `active_leaf_id`
      bỏ rơi lượt đang chảy giữa màn hình. Đường đúng là §7.5 (bấm Dừng) rồi
      retry — cùng bộ trạng thái `TRANG_THAI_CON_DUNG_DUOC` mà `cancel` dùng,
      cố ý dùng lại để hai endpoint không bao giờ hiểu "đang chạy" khác nhau.
    """
    async with session_scope() as session:
        messages = MessageRepository(session)
        conversations = ConversationRepository(session)

        goc = await _message_cua_toi(messages, message_id, user_id=user_id)
        _doi_role(goc, MessageRole.ASSISTANT)
        if goc.status in TRANG_THAI_CON_DUNG_DUOC:
            raise ApiError(
                status.HTTP_409_CONFLICT,
                ApiErrorCode.GENERATION_IN_PROGRESS,
                "luot sinh cu chua ket thuc; huy no truoc khi thu lai",
                details={"status": goc.status.value},
            )

        conversation = await _hoi_thoai_chua(conversations, goc, user_id=user_id)
        model = _chon_model(
            body.model_id if body is not None else None,
            goc.model_id,
            conversation.default_model,
        )
        luot = await _mo_luot_sinh(
            session=session,
            messages=messages,
            conversations=conversations,
            conversation_id=goc.conversation_id,
            user_id=user_id,
            user_status=user_status,
            parent_id=goc.parent_id,
            model=model,
        )
        await session.commit()

    return RetryResponse(
        assistant_message_id=luot.assistant_message_id,
        stream_url=_stream_url(request, luot.assistant_message_id),
        model_id=model.id,
        quota_warning=luot.quota_warning,
    )


@router.patch(
    "/messages/{message_id}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SuaMessageResponse,
    # §11.1 (T-2.7) + §10.6 (T-2.9) — xem `_ROUTE_SINH_CHU`.
    dependencies=_ROUTE_SINH_CHU,
    responses={
        400: {"model": ErrorEnvelope, "description": "Khong phai message user"},
        404: {"model": ErrorEnvelope, "description": "Message khong thay (§20 gop ba ca)"},
        429: {
            "model": ErrorEnvelope,
            "description": "Qua 20 luot/phut (RATE_LIMITED), da co "
            "MAX_CONCURRENT_STREAMS luot sinh chua khep (TOO_MANY_STREAMS) — §10.6, "
            "hoac het han muc chi tieu (QUOTA_EXCEEDED) — §10.2",
        },
        503: {"model": ErrorEnvelope, "description": "Khong day duoc job vao hang doi"},
    },
)
async def edit_message(
    request: Request,
    message_id: uuid.UUID,
    body: SuaMessageRequest,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    user_status: Annotated[UserStatus | None, Depends(get_current_user_status)],
) -> SuaMessageResponse:
    """Sửa một câu hỏi = thêm một câu hỏi ANH EM rồi sinh lại — §8.2, UC-04.

    **`PATCH` ở đây KHÔNG sửa hàng nào.** `messages.content` của `{message_id}`
    không đổi một ký tự, và cả nhánh con phía dưới nó vẫn nằm nguyên trong DB
    — dòng DoD thứ tư của T-1.13 là phép đo của đúng câu này: sau khi sửa, trỏ
    `active_leaf_id` về lá cũ thì nhánh cũ hiện lại đầy đủ.

    Tên method là `PATCH` vì §18.2 chốt thế, và vì từ phía người dùng thao tác
    *là* "sửa câu hỏi này". Phía dữ liệu thì nó thuần **thêm**: một message
    user mới cùng `parent_id`, rồi một assistant `queued` làm con của nó — tức
    đúng hai bước của `POST .../messages`, chỉ khác chỗ nối vào cây.

    Chỉ `role='user'` mới sửa được (`400 MESSAGE_ROLE_MISMATCH`): sửa lời của
    model rồi để nó nằm trong ngữ cảnh các lượt sau là bịa lịch sử hội thoại,
    và đường sinh lại một câu trả lời là `retry` ngay bên trên.

    **Không có phép kiểm `409` như `retry`.** Message user không bao giờ ở
    trạng thái `queued`/`streaming` — chỉ assistant mới có lượt sinh. Câu trả
    lời cũ *bên dưới* nó có thể còn đang chảy; nó cứ chảy nốt vào nhánh cũ,
    không ai mất gì (xem B-110 cho phần còn nợ).
    """
    async with session_scope() as session:
        messages = MessageRepository(session)
        conversations = ConversationRepository(session)

        goc = await _message_cua_toi(messages, message_id, user_id=user_id)
        _doi_role(goc, MessageRole.USER)
        conversation = await _hoi_thoai_chua(conversations, goc, user_id=user_id)
        model = _chon_model(conversation.default_model)

        try:
            user_message = await messages.create_message(
                conversation_id=goc.conversation_id,
                user_id=user_id,
                role=MessageRole.USER,
                # Cùng cha với bản cũ ⇒ ANH EM của nó, không phải con.
                parent_id=goc.parent_id,
                content=body.content,
            )
        except MessageNotInConversationError as loi:
            # Cha của bản cũ vừa bị xoá mềm giữa chừng. Không có endpoint nào
            # xoá message ở Phase 1, nhưng để ngả này thành `500` là để một
            # thao tác hợp lệ của người dùng hiện ra như lỗi lập trình.
            raise ApiError(
                status.HTTP_404_NOT_FOUND,
                ApiErrorCode.PARENT_NOT_FOUND,
                "message cha khong con nam trong hoi thoai nay",
            ) from loi

        uid = user_message.id
        luot = await _mo_luot_sinh(
            session=session,
            messages=messages,
            conversations=conversations,
            conversation_id=goc.conversation_id,
            user_id=user_id,
            user_status=user_status,
            parent_id=uid,
            model=model,
        )
        await session.commit()

    return SuaMessageResponse(
        user_message_id=uid,
        assistant_message_id=luot.assistant_message_id,
        stream_url=_stream_url(request, luot.assistant_message_id),
        quota_warning=luot.quota_warning,
    )


@router.get(
    "/messages/{message_id}/siblings",
    response_model=AnhEmResponse,
    responses={404: {"model": ErrorEnvelope, "description": "Message khong thay (§20 gop ba ca)"}},
)
async def list_siblings(
    message_id: uuid.UUID,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
) -> AnhEmResponse:
    """Mọi nhánh cùng cha với `{message_id}` — dữ liệu cho `‹ n/m ›` (§8.3, C13).

    Chỉ đọc. Chuyển nhánh là một request khác: `PATCH /conversations/{id}` với
    `active_leaf_id` = id của anh em được chọn.

    `sibling_index` tính bằng **vị trí trong danh sách đã sắp**, không phải một
    câu `COUNT` thứ hai: `get_siblings` sắp theo đúng khoá `(created_at, id)`
    mà `_sibling_stats` dùng, nên hai con số không thể lệch nhau. Đếm lại bằng
    SQL ở đây sẽ tạo nguồn thứ hai cho cùng một sự thật.

    Danh sách **luôn** chứa ít nhất chính `{message_id}`: nó vừa qua
    `get_message` với cùng bộ điều kiện (`deleted_at IS NULL`, cùng chủ) mà
    `get_siblings` lọc, trong cùng một transaction.
    """
    async with session_scope() as session:
        messages = MessageRepository(session)
        goc = await _message_cua_toi(messages, message_id, user_id=user_id)
        anh_em = await messages.get_siblings(goc.conversation_id, goc.parent_id, user_id=user_id)
        items = [
            MessageTrenDuongDi.from_message(m, sibling_index=vi_tri, sibling_count=len(anh_em))
            for vi_tri, m in enumerate(anh_em)
        ]
        cua_toi = next(i for i in items if i.id == message_id)
        return AnhEmResponse(
            message_id=message_id,
            parent_id=goc.parent_id,
            sibling_index=cua_toi.sibling_index,
            sibling_count=len(items),
            items=items,
        )


async def _message_cua_toi(
    messages: MessageRepository, message_id: uuid.UUID, *, user_id: uuid.UUID
) -> Message:
    """`get_message` + 404 của §20. Ba endpoint trên mở đầu bằng đúng câu này.

    "Không tồn tại", "đã xoá mềm" và "của người khác" ra cùng một câu trả lời —
    403 sẽ xác nhận cho kẻ dò rằng message đó có thật.
    """
    message = await messages.get_message(message_id, user_id=user_id)
    if message is None:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            ApiErrorCode.MESSAGE_NOT_FOUND,
            "khong tim thay message",
        )
    return message


def _doi_role(message: Message, can: MessageRole) -> None:
    """`400 MESSAGE_ROLE_MISMATCH` nếu thao tác gọi nhầm loại message."""
    if message.role is not can:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            ApiErrorCode.MESSAGE_ROLE_MISMATCH,
            f"thao tac nay chi ap dung cho message role={can.value}",
            details={"role": message.role.value, "expected": can.value},
        )


async def _hoi_thoai_chua(
    conversations: ConversationRepository, message: Message, *, user_id: uuid.UUID
) -> Conversation:
    """Hội thoại chứa `message` — cần `default_model` cho `_chon_model`.

    Không lặp lại phép kiểm quyền: `_message_cua_toi` đã JOIN sang
    `conversations` với đúng `user_id` và `deleted_at IS NULL`, trong cùng
    transaction. Nhánh `None` ở đây là chuyện không xảy ra được, nhưng trả 404
    vẫn đúng hơn là để một `AttributeError` thành `500`.
    """
    conversation = await conversations.get_conversation(message.conversation_id, user_id=user_id)
    if conversation is None:  # pragma: no cover - `_message_cua_toi` đã lọc cùng điều kiện
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            ApiErrorCode.CONVERSATION_NOT_FOUND,
            "khong tim thay hoi thoai",
        )
    return conversation
