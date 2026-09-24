"""Job `title` — đặt tên hội thoại tự động (§24.2b·S6, §23 `workers/title.py`).

KH tham chiếu: §24.2b·S3d, S6, S14, §7.2–§7.4, §10.2, §10.3 · CLAUDE.md A1, A3,
A7, A9 · tasks.md T-S.7 · NQ-110.

`api/v1/messages.py` đẩy job này ngay sau `generate` khi nhận **câu hỏi đầu
tiên** của một hội thoại chưa có tiêu đề (job id `title:{conversation_id}`).
Handler chỉ tạo record + enqueue (A1); toàn bộ phần gọi model nằm ở đây:

    ① đọc câu hỏi + hội thoại    → tiêu đề đã có? ⇒ `done` ngay, không gọi model
    ② XADD start (+ EXPIRE sớm) → ③ gọi `title_model` bằng SYSTEM KEY, XADD delta
    ④ làm sạch → UPDATE … WHERE title IS NULL
    ⑤ ghi sổ `purpose='title'` (KHÔNG ZADD) → ⑥ XADD done|error → EXPIRE

**Ba luật mượn nguyên của `generate.py`, cùng lý do:**

1. **Mọi đường thoát ghi event kết thúc (C19).** `finally` gọi `_close` đúng
   một lần cho cả ba ngả: xong, lỗi, bị arq huỷ. §7.4 cấm FE suy "đã xong" từ
   việc stream im lặng, nên thiếu event cuối là một hàng sidebar chờ mãi.
2. **Ghi Postgres TRƯỚC, `XADD done` SAU.** FE nhận `done` rồi tải lại danh
   sách hội thoại phải thấy đúng tiêu đề ấy.
3. **Ghi sổ trước event cuối, và trên cả đường lỗi** — provider tính tiền mọi
   token đã sinh (A7). `billable` chặn đường chết trước khi gọi model.

**Khác `generate` ở bốn chỗ, và cả bốn là chủ ý:**

* **Luôn system key.** Không hỏi `llm/credentials.py`: lượt này là việc của
  hệ thống, không phải một câu người dùng tự trả tiền (NQ-110). Dùng thẳng
  `SYSTEM_CREDENTIAL` để `model_name`/`reasoning_params` đi đúng đường system.
* **Không trừ quota.** `record_usage(purpose=TITLE)` ghi dòng sổ mà không
  `ZADD`; nửa đọc của luật ở ba câu dựng lại quota (Cạm bẫy ① của T-S.7).
* **Không có hàng `messages` nào của riêng nó** ⇒ không `heartbeat_at`, không
  reaper. Thay vào đó `EXPIRE` đặt **ngay sau `start`** chứ không chỉ sau event
  cuối như `generate`: lượt đặt tên ngắn hơn `STREAM_TTL_S` nhiều bậc, nên đặt
  sớm không cắt được gì, mà worker bị giết giữa chừng thì khoá vẫn tự hết hạn
  (C8) thay vì sống mãi vì không có reaper nào dọn.
* **Chỉ bốn event:** `start` · `delta` · `done` · `error` (S6). Chunk
  `reasoning` (suy luận tắt nên không nên có) được gom để ghi sổ nhưng không
  phát lên dây. `done` là `TitleDoneEvent` — mang tiêu đề, không mang `usage`.

**Không log tiêu đề hay câu hỏi.** Cả hai sinh từ chữ của người dùng (§20 — lý
do `Conversation.__repr__` không in `title`); log chỉ nói độ dài.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.config import catalog
from app.config.catalog import ModelEntry, ReasoningOption
from app.config.settings import CONVERSATION_TITLE_MAX_CHARS, settings
from app.db.models import KeySource, MessageRole, UsagePurpose
from app.db.repositories import ConversationRepository, MessageRepository
from app.db.session import session_scope
from app.llm import context
from app.llm.client import Chunk, LLMClient, Usage
from app.llm.credentials import SYSTEM_CREDENTIAL
from app.quota import meter
from app.streaming.events import (
    DeltaEvent,
    ErrorCode,
    ErrorEvent,
    Event,
    StartEvent,
    TitleDoneEvent,
)
from app.streaming.producer import StreamProducer
from app.workers.generate import CTX_LLM_CLIENT, GenerationError

logger = logging.getLogger(__name__)

#: Ký tự bọc ngoài mà model hay thêm dù prompt dặn không: ngoặc kép thẳng/cong,
#: ngoặc góc, backtick, dấu nhấn Markdown. Chỉ bóc ở HAI ĐẦU — một dấu nháy nằm
#: giữa tiêu đề ("Hàm `map` trong Python") là chữ thật.
_WRAPPERS = "\"'`*_#“”‘’«»"

_WHITESPACE = re.compile(r"\s+")


def clean_title(raw: str) -> str | None:
    """Chữ model trả về → tiêu đề ghi vào `conversations.title`, hoặc `None` nếu rỗng.

    Dòng không rỗng đầu tiên, gộp khoảng trắng, bóc ký tự bọc ngoài và dấu chấm
    cuối, rồi cắt theo `CONVERSATION_TITLE_MAX_CHARS` — cùng trần `PATCH
    /conversations` áp cho tên người dùng tự gõ, để một tiêu đề tự đặt luôn là
    thứ người dùng sửa lại được mà không vấp `422`. Cắt theo **ký tự** (C9):
    `str` của Python không bao giờ cắt đôi một chữ có dấu.

    Bóc **lặp tới khi đứng yên**: `“Nấu phở bò”.` có dấu chấm nằm ngoài ngoặc,
    nên một lượt bóc-ngoặc-rồi-bóc-chấm để lại `”` ở cuối.
    """
    line = next((part for part in raw.splitlines() if part.strip()), "")
    text = _WHITESPACE.sub(" ", line).strip()
    previous = None
    while text != previous:
        previous = text
        text = text.strip(_WRAPPERS).rstrip(".").strip()
    text = text[:CONVERSATION_TITLE_MAX_CHARS].rstrip()
    return text or None


@dataclass(slots=True)
class _Run:
    """Những gì gom được trong một lượt đặt tên. Sống đúng một job (§5.2)."""

    #: Câu hỏi được đặt tên — cũng là `usage_events.message_id` của dòng sổ,
    #: để một khoản "Đặt tên" truy ngược được về hội thoại của nó.
    question_id: uuid.UUID
    #: Ba trường điền cùng lúc ngay trước khi gọi model — thiếu một là chưa
    #: chạm tới provider, xem `billable`.
    model: ModelEntry | None = None
    user_id: uuid.UUID | None = None
    started_at: datetime | None = None
    sent: list[dict[str, Any]] = field(default_factory=list)
    text: list[str] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)
    usage: Usage | None = None
    #: Tiêu đề đang nằm trong Postgres sau lượt này — thứ `done` mang đi.
    final_title: str | None = None
    error: GenerationError | None = None

    @property
    def billable(self) -> bool:
        """Cùng luật `generate._Result.billable`: đã gọi model VÀ có gì để tính."""
        if self.model is None or self.user_id is None or self.started_at is None:
            return False
        return bool(self.usage or self.text or self.reasoning)


async def generate_title(ctx: dict[str, Any], conversation_id: str, question_id: str) -> None:
    """Đặt tên cho `conversation_id` từ câu hỏi `question_id` (message user đầu tiên).

    Payload chỉ có hai khoá chính, không có chữ của câu hỏi — cùng lý do C5
    của `generate`: câu hỏi đã nằm trong Postgres trước khi job vào hàng đợi.
    """
    cid = uuid.UUID(conversation_id)
    producer = StreamProducer.for_title(ctx["redis"], cid, ttl_s=settings.STREAM_TTL_S)
    run = _Run(question_id=uuid.UUID(question_id))

    logger.info("title: bat dau hoi thoai %s (job=%s)", cid, ctx.get("job_id"))
    try:
        await _run(ctx, cid, producer, run)
    except GenerationError as error:
        run.error = error
        logger.warning("title: %s dung vi %s", cid, error)
    except asyncio.CancelledError:
        run.error = GenerationError(ErrorCode.WORKER_TIMEOUT, "job bi huy giua chung")
        logger.warning("title: %s bi huy giua chung", cid)
        raise
    except Exception as exc:  # noqa: BLE001 — C19, cùng lý do `generate`
        run.error = GenerationError(ErrorCode.INTERNAL_ERROR, type(exc).__name__)
        logger.exception("title: %s loi khong phan loai duoc", cid)
    finally:
        await _close(ctx, cid, producer, run)


async def _run(ctx: dict[str, Any], cid: uuid.UUID, producer: StreamProducer, run: _Run) -> None:
    """Bước ① → ④. Ném `GenerationError` cho mọi ngả không đi tiếp được."""
    question, user_id, existing = await _prepare(cid, run)
    if existing is not None:
        # Người dùng đặt tên trước khi job kịp chạy: không gọi model, không tốn
        # xu nào — `done` mang đúng tên của họ.
        run.final_title = existing
        logger.info("title: %s da co tieu de truoc khi chay — bo qua model", cid)
        return

    spec = catalog.get_catalog().title_model
    model = catalog.get_model(spec.model)
    if model is None:
        raise GenerationError(
            ErrorCode.MODEL_UNKNOWN,
            f"title_model {spec.model!r} khong co trong catalog hoac da tat",
        )
    # `None` = không gửi tham số suy luận nào (`TitleModel.reasoning`). KHÔNG đi
    # qua `reasoning_to_send`: hàm ấy rơi về `reasoning.default` khi vắng mức,
    # tức bật suy luận cho đúng lượt mà catalog muốn tắt.
    level: ReasoningOption | None = (
        model.reasoning.option(spec.reasoning)
        if spec.reasoning is not None and model.reasoning is not None
        else None
    )
    run.sent = [
        {
            "role": MessageRole.USER.value,
            "content": context.render_title_prompt(
                question=question[: settings.TITLE_INPUT_MAX_CHARS]
            ),
        }
    ]

    await producer.emit(
        StartEvent(
            message_id=str(run.question_id),
            model_id=model.id,
            reasoning_effort=level.id if level is not None else None,
        )
    )
    # EXPIRE sớm — xem docstring module (không có reaper cho stream này).
    await producer.expire()

    client: LLMClient = ctx[CTX_LLM_CLIENT]
    run.model = model
    run.user_id = user_id
    # Mốc giá A7: lúc gửi request, như `generate`.
    run.started_at = datetime.now(UTC)
    try:
        stream = await client.stream(
            model=SYSTEM_CREDENTIAL.model_name(model, level),
            messages=run.sent,
            tools=None,
            max_tokens=spec.max_output,
            temperature=(
                None if level is not None and level.omit_temperature else settings.LLM_TEMPERATURE
            ),
            extra=SYSTEM_CREDENTIAL.reasoning_params(level),
        )
    except Exception as exc:
        raise GenerationError(ErrorCode.UPSTREAM_ERROR, f"{type(exc).__name__}: {exc}") from exc

    try:
        async for chunk in stream:
            await _emit(producer, run, chunk)
    except Exception as exc:
        raise GenerationError(ErrorCode.UPSTREAM_ERROR, f"{type(exc).__name__}: {exc}") from exc

    title = clean_title("".join(run.text))
    if title is None:
        raise GenerationError(ErrorCode.UPSTREAM_ERROR, "model tra ve tieu de rong")

    try:
        async with session_scope() as session:
            applied, current = await ConversationRepository(session).set_title_if_unset(
                cid, user_id=user_id, title=title
            )
            await session.commit()
    except Exception as exc:
        raise GenerationError(ErrorCode.PERSIST_FAILED, "UPDATE conversations that bai") from exc
    if current is None:
        raise GenerationError(ErrorCode.MESSAGE_NOT_FOUND, "hoi thoai khong con trong DB")
    run.final_title = current
    if not applied:
        logger.info("title: %s nguoi dung da doi ten trong luc job chay — giu ten cua ho", cid)


async def _prepare(cid: uuid.UUID, run: _Run) -> tuple[str, uuid.UUID, str | None]:
    """Bước ①: câu hỏi, chủ hội thoại, tiêu đề hiện có — một session rồi đóng.

    `get_message_for_worker` là đường của worker (nó trả `user_id` thay vì lọc
    theo nó); từ đó mọi câu sau lại lọc `user_id` trong SQL như luật §20.
    """
    async with session_scope() as session:
        owned = await MessageRepository(session).get_message_for_worker(run.question_id)
        if (
            owned is None
            or owned.message.conversation_id != cid
            or owned.message.role is not MessageRole.USER
        ):
            raise GenerationError(ErrorCode.MESSAGE_NOT_FOUND, "cau hoi dau khong con trong DB")
        conversation = await ConversationRepository(session).get_conversation(
            cid, user_id=owned.user_id
        )
        if conversation is None:
            raise GenerationError(ErrorCode.MESSAGE_NOT_FOUND, "hoi thoai khong con trong DB")
        return owned.message.content, owned.user_id, conversation.title


async def _emit(producer: StreamProducer, run: _Run, chunk: Chunk) -> None:
    """Một `Chunk` → `delta` trên dây, hoặc chỉ gom lại. Xem "bốn event" ở docstring module."""
    match chunk.kind:
        case "delta":
            text = chunk.text or ""
            run.text.append(text)
            await producer.emit(DeltaEvent(text=text))
        case "reasoning":
            run.reasoning.append(chunk.text or "")
        case "usage" if chunk.usage is not None:
            run.usage = chunk.usage
        case "done":
            run.usage = chunk.usage or run.usage
        case _:
            logger.warning("title: bo qua chunk kind=%r", chunk.kind)


async def _close(ctx: dict[str, Any], cid: uuid.UUID, producer: StreamProducer, run: _Run) -> None:
    """Bước ⑤ → ⑥: ghi sổ, `XADD done|error`, `EXPIRE`. Ba `try` riêng — C19, C8."""
    await _record_usage(ctx, cid, run)

    error = run.error
    title = run.final_title
    final_event: Event
    if error is None and title is not None:
        final_event = TitleDoneEvent(title=title)
    else:
        if error is None:  # pragma: no cover - mọi ngả không lỗi đều điền `final_title`
            error = GenerationError(ErrorCode.INTERNAL_ERROR, "khong co tieu de de gui")
        final_event = ErrorEvent(code=error.code, message=error.details)
    try:
        await producer.emit(final_event)
    except Exception:  # noqa: BLE001 — cùng lý do `generate._close_ledger`
        logger.exception("title: %s khong XADD duoc event ket thuc (C19)", cid)
    try:
        await producer.expire()
    except Exception:  # noqa: BLE001
        logger.exception("title: %s khong EXPIRE duoc %s (C8)", cid, producer.key)

    logger.info(
        "title: xong %s · %s · %d ky tu tieu de",
        cid,
        "loi " + error.code.value if error is not None else "ok",
        len(run.final_title or ""),
    )


async def _record_usage(ctx: dict[str, Any], cid: uuid.UUID, run: _Run) -> None:
    """Bước ⑤ — `usage_events` `purpose='title'`, `key_source='system'`, KHÔNG `ZADD`.

    Nuốt mọi ngoại lệ, cùng lý lẽ `generate._record_usage`: mất một dòng sổ
    không được biến một tiêu đề đã ghi xong thành lỗi trên màn hình.
    """
    if not run.billable:
        return
    model, user_id, started_at = run.model, run.user_id, run.started_at
    if model is None or user_id is None or started_at is None:  # pragma: no cover
        return
    try:
        async with session_scope() as session:
            record = await meter.record_usage(
                session,
                ctx["redis"],
                user_id=user_id,
                message_id=run.question_id,
                model=model,
                at=started_at,
                now=time.time(),
                usage=run.usage,
                sent=run.sent,
                content="".join(run.text),
                reasoning="".join(run.reasoning),
                tool_calls=None,
                key_source=KeySource.SYSTEM,
                purpose=UsagePurpose.TITLE,
            )
            await session.commit()
    except Exception:  # noqa: BLE001 — xem docstring
        logger.exception(
            "title: %s KHONG ghi duoc usage_events (user=%s model=%s)", cid, user_id, model.id
        )
        return
    logger.info(
        "title: %s ghi so %s · %s · purpose=title · in=%d out=%d · %s USD · %s",
        cid,
        record.id,
        model.id,
        record.spent.prompt_tokens,
        record.spent.completion_tokens,
        record.cost_usd,
        record.confidence.value,
    )
