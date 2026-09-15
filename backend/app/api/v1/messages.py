"""Hai endpoint ghi của §18.2: **tạo** một lượt chat, và **dừng** nó.

    POST /api/v1/conversations/{id}/messages   §7.2 ① — T-1.8
    POST /api/v1/messages/{id}/cancel          §7.5   — T-1.9

KH tham chiếu: §7.2 ①, §7.5, §8.2, §11.4, §18.2, §20 · CLAUDE.md A1, A2, A3, A8.

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
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel, Field

from app.config import catalog
from app.config.settings import settings
from app.core.deps import get_current_user_id
from app.core.errors import ApiError, ApiErrorCode, ErrorEnvelope
from app.core.queue import GENERATE_JOB_NAME, get_arq_pool
from app.core.redis import get_redis
from app.db.models import MessageRole, MessageStatus
from app.db.repositories import (
    ConversationRepository,
    MessageNotInConversationError,
    MessageRepository,
)
from app.db.session import session_scope
from app.streaming.cancel import dat_co_huy

logger = logging.getLogger(__name__)

router = APIRouter(tags=["messages"])

#: Tên route của `GET /messages/{id}/stream` trong `stream.py`. `stream_url`
#: dựng bằng `url_path_for(...)` chứ không nội suy chuỗi: tiền tố `/api/v1`
#: sống ở `api/v1/__init__.py` và đường dẫn sống ở `stream.py`, nên chép lại
#: ở đây là tạo bản thứ ba sẽ lệch trong im lặng (A3 cùng tinh thần).
TEN_ROUTE_STREAM = "stream_message"


class TaoMessageRequest(BaseModel):
    """Body của §18.2. Ba trường, hai trong đó là tuỳ chọn có ý nghĩa riêng."""

    #: Nội dung người dùng gõ. `min_length=1` vì một lượt rỗng không cho model
    #: thêm thông tin nào mà vẫn tốn một lượt sinh — và `llm/context.py::_to_wire`
    #: sẽ lặng lẽ loại nó khỏi ngữ cảnh, để lại một hoá đơn không có câu hỏi.
    content: str = Field(min_length=1)
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


@router.post(
    "/conversations/{conversation_id}/messages",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TaoMessageResponse,
    responses={
        400: {"model": ErrorEnvelope, "description": "model_id khong co trong catalog"},
        404: {"model": ErrorEnvelope, "description": "Hoi thoai hoac parent_id khong thay"},
        503: {"model": ErrorEnvelope, "description": "Khong day duoc job vao hang doi"},
    },
)
async def create_message(
    request: Request,
    conversation_id: uuid.UUID,
    body: TaoMessageRequest,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> TaoMessageResponse:
    """Ghi hai message, dời con trỏ nhánh, đẩy job, trả `202`. Không gọi model.

    `Idempotency-Key` (§11.4, A8) được **đọc và log, chưa xử lý** — middleware
    là T-2.8, và chính task đó mới bắt header này thành bắt buộc. Log ngay từ
    bây giờ vì nó là bằng chứng rẻ nhất cho C22 khi T-3.4 làm ô nhập: nếu FE
    sinh key mới mỗi lần bấm, log sẽ cho thấy hai key khác nhau cho một lần
    soạn thảo, và middleware của T-2.8 sẽ vô dụng trước cả khi nó ra đời.
    """
    if idempotency_key is not None:
        logger.info(
            "POST messages: Idempotency-Key=%s (doc, chua xu ly — tasks.md T-2.8)",
            idempotency_key,
        )

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

        assistant_message = await messages.create_message(
            conversation_id=conversation_id,
            user_id=user_id,
            role=MessageRole.ASSISTANT,
            parent_id=user_message.id,
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

        # A2: con trỏ nhánh trỏ vào message ASSISTANT, không phải message user.
        # Lượt sau nối tiếp sau câu trả lời, và `context.build` đi ngược từ
        # chính nó (nó tự rơi khỏi ngữ cảnh vì `status='queued'`).
        await conversations.set_active_leaf(
            conversation_id, user_id=user_id, message_id=assistant_message.id
        )

        # Hai UUID lấy ra TRƯỚC khi session đóng: `Message` sau đó là object
        # detached, và đọc thuộc tính của nó ngoài session là chỗ sinh
        # `DetachedInstanceError` nếu có ai lỡ bật `expire_on_commit`.
        uid, amid = user_message.id, assistant_message.id

        await _day_job(amid)
        await session.commit()

    return TaoMessageResponse(
        user_message_id=uid,
        assistant_message_id=amid,
        stream_url=str(request.app.url_path_for(TEN_ROUTE_STREAM, message_id=str(amid))),
        branched=branched,
    )


def _chon_model(xin: str | None, mac_dinh_hoi_thoai: str | None) -> catalog.ModelEntry:
    """Ba mức ưu tiên: request → `conversations.default_model` → catalog.

    `get_model` lọc luôn `enabled`, nên một model bị tắt trong catalog sẽ dừng
    được cả ba mức — kể cả khi nó còn nằm trong `conversations.default_model`
    của một hội thoại cũ. Đó là điểm của cái công tắc ở §9.2: tắt một provider
    đang hỏng phải có hiệu lực ngay, không đợi ai sửa dữ liệu.

    Raise:
        ApiError 400 `MODEL_UNKNOWN`: request (hoặc hội thoại) chỉ đích danh
            một model không còn dùng được. Nói thẳng tên model trong thông
            điệp: nó đến từ chính người gọi và có trong `GET /models`.
        ApiError 503 `NO_MODEL_AVAILABLE`: không ai chỉ đích danh, mà model
            `default` cũng đã tắt. Đây là sự cố cấu hình phía server (5xx),
            không phải lỗi của request (4xx).
    """
    for nguon in (xin, mac_dinh_hoi_thoai):
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

    T-1.8 không đặt `_job_id` nên ngả `None` chưa xảy ra hôm nay; xử nó ngay
    vì T-2.8 gắn idempotency vào đúng chỗ này (xem B-92).
    """
    try:
        pool = await get_arq_pool()
        job = await pool.enqueue_job(GENERATE_JOB_NAME, str(assistant_message_id))
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
