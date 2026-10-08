"""Repository của bảng `messages` — các thao tác trên CÂY (A2, §8.2).

KH tham chiếu: §8.2, §17.2, §20, C12.

Ba luật của `conversations.py` áp nguyên ở đây (nhận `user_id` và lọc trong
SQL · mặc định `deleted_at IS NULL` · không `commit()`), cộng thêm một luật
riêng của bảng này:

**Quyền sở hữu message là quyền sở hữu hội thoại chứa nó.** `messages` không
có cột `user_id` (Phụ lục A), nên mọi truy vấn phải JOIN hoặc lồng truy vấn
sang `conversations` — vẫn là lọc TRONG câu SQL, không phải lấy về rồi so.

Truy vấn CÂY (`get_path`, `get_siblings`) nằm ở nửa dưới file, sau các thao tác
ghi/đọc một message. Hai luật sắp xếp của chúng khác nhau và **không** được
hoán đổi — NQ-18 giải thích, tóm tắt ngay cạnh từng hàm.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import (
    CTE,
    Integer,
    Select,
    and_,
    bindparam,
    func,
    literal_column,
    or_,
    select,
    text,
    true,
    update,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.selectable import LateralFromClause

from app.db.models import Conversation, Message, MessageFeedback, MessageRole, MessageStatus
from app.db.repositories.errors import (
    ConversationNotFoundError,
    MessageNotInConversationError,
)


@dataclass(frozen=True, slots=True)
class OwnedMessage:
    """Một message kèm `user_id` của chủ hội thoại chứa nó.

    Tồn tại vì `messages` không có cột `user_id` (Phụ lục A) và worker cần con
    số đó để mọi truy vấn sau của lượt sinh vẫn lọc được trong SQL. Xem
    `MessageRepository.get_message_for_worker`.
    """

    message: Message
    user_id: uuid.UUID


#: Hai trạng thái của §7.2 mà một lượt sinh còn CHƯA KHÉP. Một hằng chứ không
#: hai chuỗi gõ tay ở mỗi chỗ hỏi: `reap_stale_queued` và `reap_stale_streaming`
#: mỗi hàm lo một trạng thái, còn trần đồng thời của §10.6 (T-2.9) hỏi về **cả
#: hai** — một message đứng trong hàng đợi vẫn là một lượt sinh đã hứa.
IN_FLIGHT_STATUSES = (MessageStatus.QUEUED, MessageStatus.STREAMING)


@dataclass(frozen=True, slots=True)
class GenerationStates:
    """Postgres biết gì về một nhúm `message_id` — §10.6 hàng "Đồng thời".

    Hai tập hợp chứ không một, và khác biệt giữa chúng là thứ giữ cho trần
    đồng thời của T-2.9 vừa **chính xác** vừa **không đua** với transaction
    đang ghi:

    * `known` — id có thật, thuộc về user đang hỏi. Không nằm trong đây nghĩa
      là Postgres **chưa từng nghe tới** id đó: hoặc transaction tạo nó còn
      chưa commit (chuyện của vài mili-giây), hoặc nó đã rollback.
    * `in_flight` — trong số `known`, cái nào còn `queued`/`streaming`.

    `known - in_flight` = "đã khép, nhả ghế ngay". Còn `members - known` thì
    **không** được nhả ngay: đó có thể là một lượt sinh vừa được ghi mà chưa
    commit, và nhả nó là tự mở đường cho lượt thứ tư.
    """

    known: frozenset[uuid.UUID]
    in_flight: frozenset[uuid.UUID]


@dataclass(frozen=True, slots=True)
class PathNode:
    """Một message trên đường đi, kèm vị trí của nó giữa các anh em (C13).

    `sibling_index` đếm từ **0**; giao diện `‹ 2/3 ›` của §8.2 hiển thị
    `sibling_index + 1` trên `sibling_count`. Hai số này do SQL tính chứ không
    do FE tự đếm — đó là toàn bộ nội dung của C13.

    `Message` không mang sẵn hai trường này vì chúng không phải thuộc tính của
    message: "thứ mấy trong các anh em còn sống" đổi mỗi lần một anh em bị xoá
    mềm. Đó là kết quả của một truy vấn, không phải một cột.
    """

    message: Message
    sibling_index: int
    sibling_count: int


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_message(
        self,
        *,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
        role: MessageRole,
        parent_id: uuid.UUID | None = None,
        content: str | None = None,
        status: MessageStatus | None = None,
        model_id: str | None = None,
        tool_call_id: str | None = None,
        reasoning_effort: str | None = None,
        web_tools: bool = False,
    ) -> Message:
        """Thêm một node vào cây.

        `parent_id=None` là gốc của một nhánh — hợp lệ và có thể có NHIỀU gốc
        trong cùng hội thoại (sửa message đầu tiên, §8.2). Truyền `parent_id`
        của một message đã có = tạo con; truyền đúng `parent_id` của một message
        đang tồn tại = tạo ANH EM của nó, tức là retry.

        Raise:
            ConversationNotFoundError: hội thoại không tồn tại/đã xoá/của người khác.
            MessageNotInConversationError: `parent_id` thuộc hội thoại khác hoặc
                đã bị xoá mềm. FK của Postgres không bắt được trường hợp này —
                nó chỉ kiểm message cha có tồn tại hay không.
        """
        await self._assert_conversation_visible(conversation_id, user_id=user_id)

        if parent_id is not None:
            parent_ok = select(Message.id).where(
                Message.id == parent_id,
                Message.conversation_id == conversation_id,
                Message.deleted_at.is_(None),
            )
            if (await self._session.execute(parent_ok)).scalar_one_or_none() is None:
                raise MessageNotInConversationError(parent_id, conversation_id)

        message = Message(
            conversation_id=conversation_id,
            parent_id=parent_id,
            role=role,
            model_id=model_id,
            tool_call_id=tool_call_id,
            reasoning_effort=reasoning_effort,
            web_tools=web_tools,
        )
        # `content` và `status` có DEFAULT trong DDL (Phụ lục A). `None` nghĩa là
        # KHÔNG đặt thuộc tính, để Postgres áp default của nó — không chép hai
        # giá trị đó sang Python cho hai nguồn khỏi lệch nhau (xem models/base.py).
        if content is not None:
            message.content = content
        if status is not None:
            message.status = status

        self._session.add(message)
        await self._session.flush()
        return message

    async def get_message(
        self,
        message_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        include_deleted: bool = False,
    ) -> Message | None:
        """Trả `None` khi không tồn tại, đã xoá mềm, hoặc thuộc user khác (→ 404)."""
        stmt = (
            select(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.id == message_id,
                Conversation.user_id == user_id,
                Conversation.deleted_at.is_(None),
            )
        )
        if not include_deleted:
            stmt = stmt.where(Message.deleted_at.is_(None))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def soft_delete_message(self, message_id: uuid.UUID, *, user_id: uuid.UUID) -> bool:
        """Xoá MỀM một message. Trả `False` khi không có gì để xoá.

        C12 sống ở đây: **không** đụng tới con cháu. Message biến khỏi truy vấn
        mặc định, nhưng các node phía dưới vẫn nguyên trong DB và vẫn trỏ
        `parent_id` vào nó. Xoá cứng (hoặc `ON DELETE CASCADE`) sẽ mất cả nhánh.
        """
        owned_conversations = select(Conversation.id).where(
            Conversation.user_id == user_id,
            Conversation.deleted_at.is_(None),
        )
        stmt = (
            update(Message)
            .where(
                Message.id == message_id,
                Message.deleted_at.is_(None),
                Message.conversation_id.in_(owned_conversations),
            )
            .values(deleted_at=func.now())
            .returning(Message.id)
            .execution_options(synchronize_session=False)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    async def set_feedback(
        self,
        message_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        value: MessageFeedback | None,
        reason: str | None,
    ) -> bool:
        """Ghi Like/Dislike lên một message — §18.2, T-3.7a. `False` = không có gì để ghi.

        **Ghi CẢ HAI cột trong mọi lần gọi, kể cả khi `reason=None`.** Đánh giá
        là một tài nguyên thay-cả-cụm chứ không vá từng trường: đổi Like thành
        Dislike mà giữ lại câu lý do của lần Like là để một hàng tự mâu thuẫn.
        Cùng lý lẽ với `PUT /settings` của T-3.0 ("`PUT` thay cả tài nguyên").

        **Idempotent theo message** (chữ của "Việc cần làm"): đây là `UPDATE`
        trên một hàng đã có, không phải `INSERT`. Like rồi Like lại vẫn đúng
        một hàng với đúng một giá trị; `value=None` là **gỡ** đánh giá, và
        `reason` đi theo về `NULL` — CHECK `ck_msg_feedback_reason_needs_value`
        của migration 0005 canh đúng chuyện đó.

        **`user_id` lọc TRONG câu SQL (§20), không sau khi đã SELECT.** Lồng
        đúng truy vấn `owned_conversations` mà `soft_delete_message` dùng, chứ
        không mở một đường tra quyền thứ hai — đó là cả lý do NQ-80 chọn hai
        cột trên `messages` thay vì một bảng `message_feedback` riêng.

        Không kiểm `role` ở đây: "chỉ đánh giá được câu trả lời" là luật của
        tầng API (§18.2 gắn hai nút này dưới câu trả lời), và nó cần trả `400
        MESSAGE_ROLE_MISMATCH` — một mã HTTP thì không phải việc của repository.
        """
        owned_conversations = select(Conversation.id).where(
            Conversation.user_id == user_id,
            Conversation.deleted_at.is_(None),
        )
        stmt = (
            update(Message)
            .where(
                Message.id == message_id,
                Message.deleted_at.is_(None),
                Message.conversation_id.in_(owned_conversations),
            )
            .values(feedback=value, feedback_reason=reason)
            .returning(Message.id)
            .execution_options(synchronize_session=False)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    # ──────────────── vòng đời một lượt sinh (§7.2 ③, T-1.6) ────────────────

    async def get_message_for_worker(self, message_id: uuid.UUID) -> OwnedMessage | None:
        """Message + `user_id` của chủ hội thoại. **Chỉ worker được gọi.**

        Đây là hàm duy nhất trong file không nhận `user_id` — và đó không phải
        kẽ hở của §20. Worker chạy thay **hệ thống**, không thay một phiên đăng
        nhập: nó nhận một `message_id` từ hàng đợi (§7.2 ①, do chính `api` đẩy
        vào **sau** khi đã kiểm quyền), nên nó không có `user_id` nào để lọc.
        Thay vì bỏ qua quyền sở hữu, hàm **trả về** `user_id` để mọi truy vấn
        tiếp theo của lượt sinh — `get_path` của `context.build` — vẫn lọc
        trong câu SQL đúng như luật.

        Tầng `api` **không** được dùng hàm này: đường của nó là `get_message`,
        nơi `user_id` là tham số bắt buộc và câu 404 là câu trả lời cho cả ba
        ca "không có / đã xoá / của người khác".

        `None` khi message không tồn tại, đã xoá mềm, hoặc hội thoại chứa nó đã
        xoá mềm — cả ba đều là "không còn gì để sinh".
        """
        stmt = (
            select(Message, Conversation.user_id)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.id == message_id,
                Message.deleted_at.is_(None),
                Conversation.deleted_at.is_(None),
            )
        )
        row = (await self._session.execute(stmt)).first()
        if row is None:
            return None
        message, user_id = row
        return OwnedMessage(message=message, user_id=user_id)

    async def mark_streaming(
        self, message_id: uuid.UUID, *, model_id: str, reasoning_effort: str | None
    ) -> bool:
        """`queued` → `streaming`, đặt `model_id` + `reasoning_effort`, mở `heartbeat_at`.

        `WHERE status = 'queued'` chứ không chỉ `WHERE id = …`: hai worker cùng
        nhận một `message_id` (arq giao lại sau SIGKILL — B-72) thì chỉ một
        trong hai đổi được trạng thái, người thua trả `False` và bỏ lượt. Không
        có điều kiện này thì cả hai cùng sinh, cùng ghi đè `content`, và người
        dùng trả tiền hai lần cho một câu hỏi.

        `heartbeat_at` đặt **ngay tại đây**, không đợi nhịp đầu tiên: reaper
        (§7.6) so `heartbeat_at < now() - REAPER_STALE_S`, mà `NULL` thì phép
        so đó không bao giờ đúng — một worker chết ngay sau khi đổi trạng thái
        sẽ để message kẹt `streaming` vĩnh viễn.

        `reasoning_effort` ghi đè mức API đã ghi lúc tạo hàng bằng mức worker
        **thật sự gửi** (T-S.6): hai giá trị chỉ khác nhau khi catalog vừa bỏ
        mức ấy giữa lúc job còn trong hàng đợi, và khi đó cột phải nói điều đã
        xảy ra chứ không phải điều đã định — chip dưới bong bóng đọc từ đây.
        """
        stmt = (
            update(Message)
            .where(Message.id == message_id, Message.status == MessageStatus.QUEUED)
            .values(
                status=MessageStatus.STREAMING,
                model_id=model_id,
                reasoning_effort=reasoning_effort,
                heartbeat_at=func.now(),
            )
            .returning(Message.id)
            .execution_options(synchronize_session=False)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    async def touch_heartbeat(self, message_id: uuid.UUID) -> bool:
        """Nhịp "tôi còn sống" của §7.6, worker gọi mỗi `WORKER_HEARTBEAT_S`.

        `clock_timestamp()` chứ không `now()`: `now()` là
        `transaction_timestamp()`, đứng yên suốt một transaction — cùng cái bẫy
        của NQ-18, và ở đây nó còn tệ hơn vì một heartbeat đứng yên là đúng
        định nghĩa "worker đã chết" dưới mắt reaper.
        """
        stmt = (
            update(Message)
            .where(Message.id == message_id, Message.status == MessageStatus.STREAMING)
            .values(heartbeat_at=func.clock_timestamp())
            .returning(Message.id)
            .execution_options(synchronize_session=False)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    async def generation_states(
        self, message_ids: Sequence[uuid.UUID], *, user_id: uuid.UUID
    ) -> GenerationStates:
        """Trong `message_ids`, cái nào CÓ THẬT và cái nào còn đang sinh.

        Người gọi duy nhất là trần đồng thời `MAX_CONCURRENT_STREAMS` của
        §10.6 (`app/core/ratelimit.py`, T-2.9): Redis giữ danh sách ghế đang
        bận, còn câu hỏi "ghế này còn bận thật không" thì chỉ Postgres trả lời
        được — đúng luật §10.3 ("Redis là cache, Postgres là sự thật").

        `user_id` lọc **trong câu SQL** (luật của file này), qua `conversations`
        vì `messages` không có cột đó. Một `message_id` của người khác vì vậy
        rơi ra khỏi `known` và được đối xử như một id lạ, không phải như một
        ghế đang bận.

        **Message đã xoá mềm — hoặc nằm trong hội thoại đã xoá mềm — tính là
        ĐÃ KHÉP**, dù cột `status` còn ghi `queued`. Ngược lại là một ghế không
        bao giờ được nhả: xoá một hội thoại giữa lúc câu trả lời đang chảy thì
        `get_message_for_worker` trả `None` và worker bỏ lượt mà **không** ghi
        `status` mới, nên hàng đó nằm lại ở `queued` vĩnh viễn.
        """
        if not message_ids:
            return GenerationStates(known=frozenset(), in_flight=frozenset())

        stmt = (
            select(Message.id, Message.status, Message.deleted_at, Conversation.deleted_at)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Message.id.in_(list(message_ids)), Conversation.user_id == user_id)
        )
        rows = (await self._session.execute(stmt)).all()

        known: set[uuid.UUID] = set()
        in_flight: set[uuid.UUID] = set()
        for mid, mstatus, message_deleted_at, conversation_deleted_at in rows:
            known.add(mid)
            deleted = message_deleted_at is not None or conversation_deleted_at is not None
            if not deleted and mstatus in IN_FLIGHT_STATUSES:
                in_flight.add(mid)
        return GenerationStates(known=frozenset(known), in_flight=frozenset(in_flight))

    async def count_streaming(self) -> int:
        """Bao nhiêu lượt sinh đang chảy ngay lúc này — §16.3 màn "Hệ thống".

        Đây là hàm thứ ba **không** nhận `user_id`, và cùng lý do với
        `reap_stale_*`: người hỏi là hệ thống, không phải một người dùng đứng
        trước hội thoại của mình. Nó chỉ trả về một **con số**, không trả về
        hàng nào, nên không có gì của người này rò sang màn hình người kia.

        **Đếm `streaming`, không đếm `queued`.** §16.3 tách hai chỉ số cạnh
        nhau — *"độ dài hàng đợi arq, số stream đang chạy"* — nên gộp `queued`
        vào đây là đếm cùng một job hai lần trên cùng một màn hình. Hai con số
        ấy cũng đo hai thứ khác nhau: hàng đợi nói worker có theo kịp không
        (§21.2), còn con số này nói đang có bao nhiêu câu trả lời thật sự chảy.

        **Không** lọc `deleted_at`: một hội thoại bị xoá giữa lúc đang stream
        thì lượt sinh ấy vẫn đang tiêu CPU của worker và tiền của provider cho
        tới khi nó tự khép hoặc reaper §7.6 dọn. Màn hình "Hệ thống" đo tải
        thật, và tải thật không quan tâm ai đã bấm nút xoá.
        """
        stmt = (
            select(func.count())
            .select_from(Message)
            .where(Message.status == MessageStatus.STREAMING)
        )
        return (await self._session.execute(stmt)).scalar_one()

    async def reap_stale_streaming(
        self, *, stale_after_s: int, error_code: str
    ) -> Sequence[uuid.UUID]:
        """Câu UPDATE của §7.6 — đánh `failed` mọi lượt sinh mất nhịp tim.

        Đây là hàm thứ hai (sau `get_message_for_worker`) **không** nhận
        `user_id`, và vì cùng một lý do: reaper chạy thay **hệ thống**, không
        thay một phiên đăng nhập. Nó cũng không lọc `deleted_at IS NULL` —
        khác luật chung của file — vì một message đã xoá mềm mà kẹt
        `status='streaming'` vĩnh viễn là đúng thứ §7.6 sinh ra để dọn, và
        cái giá của việc dọn nó là một `XADD` vào stream không ai đọc.

        **`status = 'streaming'` phải ra SQL dưới dạng HẰNG, không phải tham
        số** — đó là toàn bộ lý do có `bindparam(..., literal_execute=True)` ở
        đây. `ix_msg_streaming` là **partial index** (`WHERE status =
        'streaming'`): Postgres chỉ dùng được nó khi chứng minh được vị từ của
        câu truy vấn kéo theo vị từ của index, mà với `status = $1` thì ở
        *generic plan* nó không chứng minh được. Hệ quả nếu để tham số: năm
        lần chạy đầu (custom plan, biết giá trị) dùng index, rồi từ lần thứ sáu
        Postgres đổi sang generic plan và cùng câu lệnh ấy thành `Seq Scan` —
        chậm dần theo tháng, không có gì báo. Cùng lý do, ngưỡng thời gian cũng
        nội suy thẳng thành `make_interval(secs=>…)`; giá trị vẫn tới từ
        `settings.REAPER_STALE_S` nên A3 không bị vi phạm, chỉ có *chỗ ghép
        chuỗi* là ở đây.

        `now()` (= `transaction_timestamp()`) chứ không `clock_timestamp()`,
        đúng chữ §7.6 và **ngược** với `touch_heartbeat`: ở đây một mốc đứng
        yên suốt transaction là thứ mình muốn — mọi message trong cùng một lượt
        quét phải được đo bằng cùng một cái đồng hồ.

        Trả về `id` của những message **thực sự bị đổi** (qua `RETURNING`), vì
        reaper phải `XADD` đúng cho từng cái. Danh sách rỗng là đường chạy
        thường ngày, không phải lỗi.
        """
        stale = func.now() - bindparam(
            "reaper_stale", value=timedelta(seconds=stale_after_s), literal_execute=True
        )
        streaming = bindparam(
            "reaper_status",
            value=MessageStatus.STREAMING,
            type_=Message.status.type,
            literal_execute=True,
        )
        stmt = (
            update(Message)
            .where(Message.status == streaming, Message.heartbeat_at < stale)
            .values(status=MessageStatus.FAILED, error_code=error_code)
            .returning(Message.id)
            .execution_options(synchronize_session=False)
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def reap_stale_queued(
        self, *, stale_after_s: int, error_code: str
    ) -> Sequence[uuid.UUID]:
        """Nhánh thứ hai của §7.6 — message mồ côi trong HÀNG ĐỢI (B-123).

        `reap_stale_streaming` ở trên không thấy được tập này, và không phải vì
        sót: worker chết *sau* khi nhận job nhưng *trước* `mark_streaming` để
        lại `status='queued'` **và** `heartbeat_at=NULL`, nên cả hai vế của câu
        UPDATE kia đều trượt — `NULL < now() - interval` cho ra `NULL`, tức
        không khớp. Job thì bị arq từ chối bằng `max retries 1 exceeded` sau
        khi khoá `arq:in-progress:` hết hạn (B-72/NQ-28), nên không ai quay lại
        đổi trạng thái. Kết cục: message kẹt `queued` **vĩnh viễn**, và §7.4
        cấm FE suy ra "xong" từ im lặng nên với client đó là *đang chờ* mãi.

        Đo trên `created_at` vì đó là mốc duy nhất message này có. Ngưỡng là
        `REAPER_QUEUED_STALE_S` — biến RIÊNG, xem docstring của nó cho lý do nó
        phải lớn hơn `GENERATE_TIMEOUT_S`.

        Cùng ba quyết định với hàm trên và cùng lý do: hằng chứ không tham số
        (partial index `ix_msg_queued` là `WHERE status = 'queued'`, và
        `status = $1` ở generic plan không chứng minh được vị từ ⇒ `Seq Scan`
        từ lần chạy thứ sáu), `now()` chứ không `clock_timestamp()` (một lượt
        quét đo bằng một cái đồng hồ), và `RETURNING` chứ không SELECT-rồi-UPDATE.
        """
        stale = func.now() - bindparam(
            "reaper_queued_stale", value=timedelta(seconds=stale_after_s), literal_execute=True
        )
        queued = bindparam(
            "reaper_queued_status",
            value=MessageStatus.QUEUED,
            type_=Message.status.type,
            literal_execute=True,
        )
        stmt = (
            update(Message)
            .where(Message.status == queued, Message.created_at < stale)
            .values(status=MessageStatus.FAILED, error_code=error_code)
            .returning(Message.id)
            .execution_options(synchronize_session=False)
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def finish_generation(
        self,
        message_id: uuid.UUID,
        *,
        status: MessageStatus,
        content: str,
        reasoning: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_rounds: list[dict[str, Any]] | None = None,
        finish_reason: str | None = None,
        error_code: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
    ) -> bool:
        """Ghi kết quả cuối của một lượt sinh — §7.2 ③, §17.2.

        Đây là lần ghi **duy nhất** vào `messages.content`: trong lúc stream,
        nguồn sự thật là Redis (§17.2, C5). Ghi từng delta xuống Postgres là
        ~2000 `UPDATE` cho một câu trả lời dài, đúng phương án ADR-01 đã loại.

        Gọi cho **cả** đường thành công lẫn đường lỗi: `status='failed'` vẫn
        mang theo phần chữ đã sinh được. Người dùng đã nhìn thấy phần đó trên
        màn hình, nên xoá nó đi sẽ làm màn hình và lịch sử nói hai chuyện khác
        nhau — cùng lý lẽ với `cancelled` ở §7.5 và với `USABLE_STATUSES` của
        `llm/context.py`.

        **Không** đụng `heartbeat_at`: §17.2 nói cột đó chỉ có nghĩa khi
        `status='streaming'`, và giữ lại dấu vết nhịp cuối cùng giúp đọc được
        "nó chết lúc nào" khi soi một message `failed`.
        """
        stmt = (
            update(Message)
            .where(Message.id == message_id)
            .values(
                status=status,
                content=content,
                reasoning=reasoning,
                tool_calls=tool_calls,
                tool_rounds=tool_rounds,
                finish_reason=finish_reason,
                error_code=error_code,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            .returning(Message.id)
            .execution_options(synchronize_session=False)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    async def tool_summaries(
        self, message_ids: Sequence[uuid.UUID], *, user_id: uuid.UUID
    ) -> dict[uuid.UUID, list[dict[str, Any]]]:
        """Tóm tắt tool của từng message: `[{name, ok, reason, sources}]` (T-6.7a).

        MỘT câu cho cả danh sách (lối `with_artifacts`), và tách khỏi `get_path`:
        `tool_rounds` mang chữ trang web nên là cột deferred — Postgres bóc
        `results` ngay trong SQL, `content` không bao giờ ra khỏi DB ở đây.
        Message không gọi tool vắng khỏi dict. `user_id` lọc trong SQL (§20).
        """
        if not message_ids:
            return {}
        stmt = text(
            """
            SELECT m.id, jsonb_agg(jsonb_build_object(
                       'name', res -> 'name', 'ok', res -> 'ok',
                       'reason', res -> 'reason', 'sources', res -> 'sources')
                   ORDER BY rd.i, rs.j) AS tools
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            CROSS JOIN LATERAL jsonb_array_elements(m.tool_rounds) WITH ORDINALITY rd(round, i)
            CROSS JOIN LATERAL jsonb_array_elements(rd.round -> 'results')
                 WITH ORDINALITY rs(res, j)
            WHERE m.id = ANY(:ids) AND m.tool_rounds IS NOT NULL
              AND c.user_id = :user_id AND c.deleted_at IS NULL
            GROUP BY m.id
            """
        ).bindparams(
            bindparam("ids", list(message_ids), type_=ARRAY(UUID(as_uuid=True))),
            bindparam("user_id", user_id, type_=UUID(as_uuid=True)),
        )
        return {mid: tools for mid, tools in (await self._session.execute(stmt)).all()}

    # ─────────────────────── truy vấn cây (§8.3) ───────────────────────

    async def get_path(self, leaf_id: uuid.UUID, *, user_id: uuid.UUID) -> list[PathNode]:
        """Đường đi từ GỐC xuống `leaf_id`, gốc trước lá sau — §8.3, A2.

        Đây là hàm chống C11: dựng ngữ cảnh gửi model bằng
        `WHERE conversation_id = ... ORDER BY created_at` sẽ gom cả những nhánh
        người dùng đã bỏ, và bạn trả tiền cho chúng ở **mọi** lượt sau.

        Trả danh sách **rỗng** (không raise) khi lá không tồn tại, đã xoá mềm,
        hoặc thuộc user khác — cùng lối đi tới 404 như `get_message` (§20).

        Một tổ tiên bị xoá mềm sẽ **cắt** đường đi ở đó: hàm trả về phần từ lá
        lên tới ngay dưới node đã xoá, chứ không nhảy qua nó. §8.3 đòi lọc
        `deleted_at IS NULL` ở **cả hai** nhánh của CTE chính là để thế — một
        message đã xoá không được lỏn vào ngữ cảnh gửi model (C12).
        """
        rows = await self._session.execute(path_statement(leaf_id, user_id=user_id))
        return [
            PathNode(message=message, sibling_index=index, sibling_count=count)
            for message, index, count in rows.all()
        ]

    async def get_siblings(
        self,
        conversation_id: uuid.UUID,
        parent_id: uuid.UUID | None,
        *,
        user_id: uuid.UUID,
    ) -> Sequence[Message]:
        """Các anh em cùng `parent_id` trong một hội thoại, đã sắp thứ tự — §8.3.

        `parent_id=None` là hợp lệ và là trường hợp quan trọng nhất: message gốc
        có `parent_id` NULL, và sửa câu hỏi đầu tiên tạo ra **nhiều** gốc trong
        cùng hội thoại (§8.2). Vì thế điều kiện phải là `IS NOT DISTINCT FROM`,
        không phải `=`: trong SQL, `parent_id = NULL` không bao giờ đúng, nên
        viết `=` thì mọi gốc đều báo "có 0 anh em" và điều hướng `‹ n/m ›` biến
        mất đúng lúc người dùng cần nó nhất.

        `ORDER BY created_at, id` chứ không phải riêng `created_at`: xem NQ-18.
        `clock_timestamp()` chỉ phân giải tới micro-giây nên hai anh em vẫn có
        thể trùng thời điểm; khoá phụ `id` không nói lên thứ tự tạo, nhưng làm
        kết quả **xác định** — và một `sibling_index` nhảy qua nhảy lại giữa hai
        lần tải trang chính là C13.
        """
        stmt = (
            select(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.conversation_id == conversation_id,
                Message.parent_id.is_not_distinct_from(_parent_id_param(parent_id)),
                Message.deleted_at.is_(None),
                Conversation.user_id == user_id,
                Conversation.deleted_at.is_(None),
            )
            .order_by(Message.created_at, Message.id)
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def get_deepest_leaf(
        self, message_id: uuid.UUID, *, user_id: uuid.UUID
    ) -> uuid.UUID | None:
        """Lá sâu nhất (mới nhất) của nhánh mọc từ `message_id` — B-109, NQ-35.

        Truy vấn cây thứ **ba** cạnh `get_path`/`get_siblings`, và là cái duy
        nhất đi **xuôi**: từ một node đi xuống theo `parent_id` của con.

        Nó tồn tại vì `get_path` đi ngược từ `active_leaf_id` lên gốc, nên đặt
        con trỏ nhánh vào một node **có con** sẽ cắt đường đi ngay tại node đó
        — phần bên dưới vẫn nằm nguyên trong DB nhưng biến khỏi màn hình. Đó
        là B-109, và ngả (a) của NQ-35 chốt rằng chỗ sửa là **API**, không phải
        client: `PATCH /conversations/{id}` nhận id của anh em được chọn rồi tự
        đi tiếp xuống hết nhánh ấy.

        Trả `None` khi `message_id` không thấy được (không tồn tại, đã xoá mềm,
        hoặc của user khác) — cùng lối đi tới 404 như `get_path`, và để chỗ gọi
        giữ nguyên câu trả lời `LEAF_NOT_FOUND` của `set_active_leaf` thay vì
        mọc thêm một đường báo lỗi thứ hai. Node **đã là lá** thì trả về chính
        nó, nên chỗ gọi không cần một nhánh `if` nào.

        `ORDER BY depth DESC, created_at DESC, id DESC` — ba khoá, và cả ba đều
        cần. `depth` chọn nhánh dài nhất; khi hai nhánh dài bằng nhau thì
        `created_at` chọn cái **mới nhất** (đúng chữ "mới nhất" của B-109); `id`
        là khoá cuối cho kết quả **xác định** khi `created_at` hoà — cùng lý lẽ
        NQ-18 đã dùng cho `get_siblings`, vì một con trỏ nhánh nhảy qua nhảy lại
        giữa hai lần bấm cũng khó tìm y như một `sibling_index` nhảy.
        """
        tree = _subtree_cte(message_id, user_id=user_id)
        stmt = (
            select(tree.c.id)
            .order_by(tree.c.depth.desc(), tree.c.created_at.desc(), tree.c.id.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def _assert_conversation_visible(
        self, conversation_id: uuid.UUID, *, user_id: uuid.UUID
    ) -> None:
        stmt = select(Conversation.id).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
            Conversation.deleted_at.is_(None),
        )
        if (await self._session.execute(stmt)).scalar_one_or_none() is None:
            raise ConversationNotFoundError(conversation_id, user_id)


# ─────────────── câu lệnh của `get_path`, tách ra để đo được ───────────────


def path_statement(leaf_id: uuid.UUID, *, user_id: uuid.UUID) -> Select[Any]:
    """Dựng ĐÚNG câu lệnh mà `get_path` chạy, trả về `(Message, index, count)`.

    Tách khỏi `get_path` vì DoD của T-1.2 đòi đo bằng `EXPLAIN ANALYZE`, và một
    câu lệnh chép lại bằng tay để đo là đo nhầm thứ khác.

    Toàn bộ nằm trong **một** câu lệnh là có chủ ý: lấy đường đi rồi lặp Python
    gọi `get_siblings` cho từng node là N+1 truy vấn, và N ở đây là độ sâu của
    hội thoại — nó lớn dần theo thời gian đúng như hoá đơn của C11.
    """
    path = _path_cte(leaf_id, user_id=user_id)
    siblings = _sibling_stats(path)
    return (
        select(Message, siblings.c.sibling_index, siblings.c.sibling_count)
        .select_from(path)
        .join(Message, Message.id == path.c.id)
        # CROSS JOIN LATERAL: mệnh đề bên trong đọc `path.c.*` của CHÍNH dòng
        # đang xét, nên nó phải là lateral chứ không phải một subquery rời.
        .join(siblings, true())
        # Sắp theo DEPTH, không theo thời gian (NQ-18): mỗi tầng của một đường
        # đi có đúng một message nên `depth` không bao giờ hoà, còn `created_at`
        # thì hoà được. `desc()` cho gốc (depth lớn nhất) ra trước.
        .order_by(path.c.depth.desc())
    )


def _parent_id_param(parent_id: uuid.UUID | None) -> Any:
    """Bọc `parent_id` thành bind param có KIỂU rõ ràng.

    Truyền thẳng `None` vào `is_not_distinct_from()` cũng ra SQL đúng, nhưng ra
    `IS NOT DISTINCT FROM NULL` — một câu lệnh có hình dạng khác hẳn so với khi
    `parent_id` có giá trị. Bind param giữ cho cả hai trường hợp dùng chung một
    câu lệnh, và `::UUID` cắt đứt mọi chuyện suy đoán kiểu của Postgres.
    """
    return bindparam("parent_id", parent_id, type_=UUID(as_uuid=True))


def _path_cte(leaf_id: uuid.UUID, *, user_id: uuid.UUID) -> CTE:
    """Recursive CTE đi NGƯỢC từ lá lên gốc theo `parent_id` (§8.3).

    CTE chỉ mang 5 cột khoá chứ không `SELECT m.*`: `content` của một hội thoại
    dài là vài trăm KB, và nó phải được lôi qua từng vòng lặp của CTE rồi mới bị
    vứt đi. Bản đầy đủ của message được JOIN lại một lần ở câu ngoài.

    Không có cột nào chặn vòng lặp vô hạn, và không cần: `parent_id` chỉ được
    đặt lúc tạo message và không hàm nào sửa nó, nên một node mới luôn trỏ vào
    một node đã có — cây không thể có chu trình.
    """
    leaf = aliased(Message, name="leaf")
    anchor = (
        select(
            leaf.id.label("id"),
            leaf.conversation_id.label("conversation_id"),
            leaf.parent_id.label("parent_id"),
            leaf.created_at.label("created_at"),
            # `literal_column` chứ không `literal(0)`: một bind param không kiểu
            # ở nhánh neo làm Postgres không suy được kiểu của cột `depth`.
            literal_column("0", Integer).label("depth"),
        )
        # Quyền sở hữu kiểm ở ĐÂY, trong SQL (§20). Chỉ cần ở nhánh neo: nhánh
        # đệ quy không rời khỏi hội thoại của lá (điều kiện ngay bên dưới).
        .join(Conversation, Conversation.id == leaf.conversation_id)
        .where(
            leaf.id == leaf_id,
            leaf.deleted_at.is_(None),
            Conversation.user_id == user_id,
            Conversation.deleted_at.is_(None),
        )
        .cte("path", recursive=True)
    )
    ancestor = aliased(Message, name="ancestor")
    step = (
        select(
            ancestor.id,
            ancestor.conversation_id,
            ancestor.parent_id,
            ancestor.created_at,
            anchor.c.depth + 1,
        )
        .join(anchor, anchor.c.parent_id == ancestor.id)
        .where(
            # C12: lọc ở CẢ HAI nhánh, không chỉ nhánh neo.
            ancestor.deleted_at.is_(None),
            # FK `messages.parent_id` chỉ bảo đảm message cha TỒN TẠI, không bảo
            # đảm cùng hội thoại. `create_message` chặn ở đường ghi; điều kiện này
            # chặn ở đường đọc, để một dòng hỏng do tay người sửa DB không biến
            # thành ngữ cảnh lẫn hai hội thoại gửi lên model (C11).
            ancestor.conversation_id == anchor.c.conversation_id,
        )
    )
    return anchor.union_all(step)


def _subtree_cte(root_id: uuid.UUID, *, user_id: uuid.UUID) -> CTE:
    """Recursive CTE đi XUÔI từ `root_id` xuống theo `parent_id` của con (B-109).

    Ảnh soi gương của `_path_cte`, và ba ràng buộc của nó giữ nguyên vì lý do
    giữ nguyên:

    - chỉ mang 4 cột khoá, không `SELECT m.*` — `content` của cả một nhánh bị
      lôi qua từng vòng lặp rồi vứt đi;
    - `deleted_at IS NULL` ở **cả hai** nhánh (C12) — một node đã xoá mềm cắt
      nhánh tại đó chứ không bị nhảy qua, nên con trỏ nhánh không bao giờ đậu
      xuống dưới một message đã xoá;
    - `conversation_id` khoá lại ở nhánh đệ quy: FK `messages.parent_id` chỉ
      bảo đảm cha **tồn tại**, không bảo đảm cùng hội thoại (C11).

    Khác `_path_cte` đúng một chỗ và chỗ ấy là bản chất: đi ngược thì mỗi tầng
    có đúng **một** hàng (một node có một cha), đi xuôi thì một tầng có bao
    nhiêu hàng tuỳ số nhánh. Vì thế `get_deepest_leaf` phải SẮP rồi lấy một,
    chứ không đọc thẳng hàng cuối như `get_path`.
    """
    root = aliased(Message, name="root")
    anchor = (
        select(
            root.id.label("id"),
            root.conversation_id.label("conversation_id"),
            root.created_at.label("created_at"),
            literal_column("0", Integer).label("depth"),
        )
        # Quyền sở hữu kiểm ở ĐÂY, trong SQL (§20) và chỉ ở nhánh neo: nhánh
        # đệ quy không rời khỏi hội thoại của gốc.
        .join(Conversation, Conversation.id == root.conversation_id)
        .where(
            root.id == root_id,
            root.deleted_at.is_(None),
            Conversation.user_id == user_id,
            Conversation.deleted_at.is_(None),
        )
        .cte("subtree", recursive=True)
    )
    child = aliased(Message, name="child")
    step = (
        select(
            child.id,
            child.conversation_id,
            child.created_at,
            anchor.c.depth + 1,
        )
        .join(anchor, child.parent_id == anchor.c.id)
        .where(
            child.deleted_at.is_(None),
            child.conversation_id == anchor.c.conversation_id,
        )
    )
    return anchor.union_all(step)


def _sibling_stats(path: CTE) -> LateralFromClause:
    """Đếm anh em cho MỘT dòng của `path` — `sibling_index` và `sibling_count`.

    Cùng một điều kiện `IS NOT DISTINCT FROM` như `get_siblings`, vì hai chỗ
    phải hiểu "anh em" giống hệt nhau: FE đọc `sibling_count` từ đường đi rồi
    bấm mũi tên để lấy danh sách từ `get_siblings`, và hai con số lệch nhau là
    C13 ở dạng khó tìm nhất.

    `sibling_index` = số anh em đứng TRƯỚC nó theo đúng khoá sắp xếp
    `(created_at, id)` của §8.3 — viết thành `count(*) FILTER (WHERE ...)` để
    cả hai con số ra trong một lần quét.
    """
    sibling = aliased(Message, name="sibling")
    comes_before = or_(
        sibling.created_at < path.c.created_at,
        and_(sibling.created_at == path.c.created_at, sibling.id < path.c.id),
    )
    return (
        select(
            func.count().filter(comes_before).label("sibling_index"),
            # Đếm cả chính nó: gốc có 3 anh em ⇒ `sibling_count == 3`, khớp
            # `‹ 1/3 ›` mà người dùng nhìn thấy.
            func.count().label("sibling_count"),
        )
        .where(
            sibling.conversation_id == path.c.conversation_id,
            sibling.parent_id.is_not_distinct_from(path.c.parent_id),
            sibling.deleted_at.is_(None),
        )
        .lateral("sibling_stats")
    )
