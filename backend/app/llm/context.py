"""Dựng ngữ cảnh gửi model từ CÂY hội thoại, cắt theo ngân sách token.

KH tham chiếu: §9.6, §8.3, §19.1, C11, C15, C12 · CLAUDE.md A2, A3, A9 · B-33.

Đây là nơi §8 (cây) gặp §9 (provider). Đầu vào là một `leaf_id`; đầu ra là
`list[dict]` đúng hình dạng `messages` của OpenAI Chat Completions, sẵn sàng
đưa vào `LLMClient.stream()` (§9.1). Không chỗ nào khác trong backend được
dựng danh sách đó.

**Ba luật của file này:**

1. **Chỉ đi theo ĐƯỜNG ĐI (C11).** Ngữ cảnh lấy từ `MessageRepository.get_path`
   — một câu recursive CTE đi từ lá ngược lên gốc (§8.3). Không có, và không
   được có, truy vấn nào ở đây gom message theo `conversation_id`. C11 là con
   bug tốn tiền nhất của dự án: gom cả nhánh đã bỏ thì bạn trả tiền cho chúng ở
   **mọi** lượt sau, và model "nhớ" những thứ người dùng chưa hỏi ở nhánh này.

2. **Cặp `tool_call` + `tool_result` là một đơn vị NGUYÊN TỬ (C15).** Nhát cắt
   không bao giờ rơi vào giữa một cặp. Cắt lẻ khiến provider trả
   `400 invalid request`, và thông điệp lỗi của họ hầu như không bao giờ nói
   rằng nguyên nhân là một `tool_call_id` không có message trả lời.

3. **Thà nổ còn hơn gửi quá ngân sách.** Không có đường nào ra khỏi `build()`
   mà mang theo một danh sách vượt `budget`: hoặc trả về danh sách đã vừa,
   hoặc raise. Gửi đi rồi để provider từ chối là đổi một lỗi đọc được ở đây
   lấy một lỗi khó đọc ở giữa lượt chat, sau khi đã tốn một chặng mạng.

**Thứ KHÔNG bao giờ được gửi lại (B-33).** Cột `messages.reasoning` giữ phần
"suy nghĩ" của những lượt trước để FE hiện khối gấp được (§7.4). Nó **không**
vào ngữ cảnh: protocol §9.1 không có chỗ cho nó, model không cần đọc lại suy
nghĩ cũ của chính mình, và `deepseek-flash` sinh tới 333 chunk reasoning cho
một lượt (đo ở T-1.3) — gửi lại là nhân đôi hoá đơn để đổi lấy số không. Đây
chính là phần "trừ hao `reasoning_tokens`" mà §9.6 đòi: trừ bằng cách không gửi.

**Skill descriptions chưa có.** §9.6 xếp chúng ở ưu tiên thứ hai, giữa system
prompt và message mới nhất. Phase 7 mới sinh ra chúng (`app/skills/`), nên hôm
nay chúng vắng mặt chứ không phải bị bỏ; chỗ chèn là ngay sau `_system_message`
trong `build()`.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, Template
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.catalog import ModelEntry
from app.config.settings import settings
from app.db.models import Message, MessageRole, MessageStatus
from app.db.repositories import MessageRepository
from app.llm.tokens import count_message, count_messages

logger = logging.getLogger(__name__)

#: `config/` mounted ngoài image (§23) — cùng cách định vị với
#: `app/config/catalog.py`, không phải biến môi trường.
PROMPTS_DIR = Path(__file__).resolve().parents[3] / "config" / "prompts"

#: Tên file prompt hệ thống. tasks.md T-1.4 ghi thẳng tên này.
SYSTEM_PROMPT_NAME = "system.jinja"

#: §19.1: "System prompt · sửa file · không cần restart (đọc lại có cache 60 s)".
#: Con số là hợp đồng vận hành viết trong kế hoạch, không phải một nút vặn theo
#: môi trường, nên nó là hằng có tên ở đây chứ không phải một biến `.env` nữa.
SYSTEM_PROMPT_TTL_S = 60

#: Chỉ hai trạng thái này có nội dung đã chốt. `queued`/`streaming` là message
#: đang chờ hoặc đang sinh — với `build()` thì message ở lá chính là cái
#: `queued` mà worker sắp viết vào (§7.2 bước ③), gửi nó lên là gửi một lượt
#: assistant rỗng. `failed` không có chữ nào để gửi.
#: `cancelled` thì CÓ vào: §7.5 lưu phần đã sinh, người dùng đã đọc nó trên màn
#: hình, nên bỏ đi sẽ làm model và người dùng nhìn hai lịch sử khác nhau.
USABLE_STATUSES = frozenset({MessageStatus.COMPLETED, MessageStatus.CANCELLED})


class ContextError(RuntimeError):
    """Gốc cho mọi lỗi khi dựng ngữ cảnh."""


class EmptyPathError(ContextError):
    """`leaf_id` không cho ra message nào dùng được.

    Ba nguyên nhân gộp làm một, cùng lý do với `ConversationNotFoundError`
    (§20): lá không tồn tại · lá thuộc user khác · đường đi chỉ toàn message
    chưa xong hoặc đã xoá mềm. Tầng API map cả ba thành 404.
    """

    def __init__(self, leaf_id: uuid.UUID) -> None:
        super().__init__(
            f"đường đi từ leaf {leaf_id} không có message nào dùng được "
            f"(không tồn tại, thuộc user khác, hoặc chưa có nội dung)"
        )
        self.leaf_id = leaf_id


class BudgetTooSmallError(ContextError):
    """Ngân sách không chứa nổi system prompt + khối message mới nhất.

    Không có cách nào hạ thấp hơn nữa: §9.6 cấm cắt system prompt, và bỏ nốt
    message mới nhất thì không còn câu hỏi nào để trả lời. Nổ ở đây, với con số
    cụ thể, thay vì để provider trả `400 context_length_exceeded` — thông điệp
    của họ không nói được model này cần `max_output` bao nhiêu.
    """

    def __init__(self, *, budget: int, needed: int, model_id: str) -> None:
        super().__init__(
            f"model {model_id}: ngân sách {budget} token không đủ cho system prompt "
            f"+ khối mới nhất ({needed} token). Hạ max_output hoặc RESERVE_TOKENS, "
            f"hoặc rút ngắn system prompt (§9.6)"
        )
        self.budget = budget
        self.needed = needed
        self.model_id = model_id


# ───────────────────────── system prompt (§19.1) ─────────────────────────

_ENV = Environment(
    loader=FileSystemLoader(PROMPTS_DIR),
    # Prompt là văn bản thuần gửi cho model, KHÔNG phải HTML. Bật autoescape ở
    # đây sẽ biến mọi dấu `<`, `&`, `"` trong prompt thành thực thể HTML và
    # model đọc được thứ khác hẳn thứ người vận hành viết.
    autoescape=False,
    # Sửa file prompt mà gõ nhầm tên biến thì nổ ngay, không âm thầm render ra
    # chuỗi rỗng. Một system prompt cụt là lỗi vô hình đắt nhất trong cả file.
    undefined=StrictUndefined,
    keep_trailing_newline=True,
)


@dataclass(slots=True)
class _CachedTemplate:
    template: Template
    loaded_at: float


_cached_template: _CachedTemplate | None = None


def reload_system_prompt() -> None:
    """Vứt bản cache, buộc lần gọi sau đọc lại đĩa. Dùng trong test và ở T-2.16."""
    global _cached_template
    _cached_template = None


def _system_template() -> Template:
    """Template đã cache `SYSTEM_PROMPT_TTL_S` giây.

    Cache ở tầng này chứ không dựa vào `auto_reload` của Jinja: `auto_reload`
    gọi `stat()` mỗi lần `get_template`, tức mỗi lượt chat chạm đĩa một lần chỉ
    để biết file không đổi. §19.1 đòi đúng một điều — sửa file thì trong vòng
    60 giây là có hiệu lực — và một mốc thời gian làm được điều đó mà không
    chạm đĩa lần nào.
    """
    global _cached_template
    now = time.monotonic()
    cached = _cached_template
    if cached is None or now - cached.loaded_at >= SYSTEM_PROMPT_TTL_S:
        cached = _CachedTemplate(_ENV.get_template(SYSTEM_PROMPT_NAME), now)
        _cached_template = cached
    return cached.template


def render_system_prompt(*, model_display_name: str) -> str:
    """Render `config/prompts/system.jinja`.

    Tham số là **tường minh**, không phải `**kwargs`: `StrictUndefined` biến
    một biến thiếu thành exception giữa lượt chat, nên hợp đồng giữa file
    `.jinja` và code phải đọc được ở một chỗ. Thêm biến mới = thêm tham số ở
    đây và một dòng chú thích ở đầu file `.jinja`.
    """
    return _system_template().render(model_display_name=model_display_name).strip()


# ───────────────────────────── dựng ngữ cảnh ─────────────────────────────


async def build(
    session: AsyncSession,
    leaf_id: uuid.UUID,
    model_meta: ModelEntry,
    *,
    user_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Dựng `messages[]` cho một lượt gọi model, từ lá `leaf_id` ngược lên gốc.

    `leaf_id` thường là **message assistant đang `queued`** mà worker sắp sinh
    (§7.2 bước ③). Nó tự bị loại khỏi kết quả vì trạng thái của nó không nằm
    trong `USABLE_STATUSES` — không có xử lý đặc biệt nào cho "cái lá", chỉ có
    một luật chung áp cho mọi node.

    Raise:
        EmptyPathError: lá không tồn tại, thuộc user khác, hoặc cả đường đi
            không còn message nào có nội dung.
        BudgetTooSmallError: ngân sách không chứa nổi system prompt + khối
            message mới nhất.
    """
    path = await MessageRepository(session).get_path(leaf_id, user_id=user_id)

    system_message = _system_message(model_meta)
    # Ưu tiên thứ hai của §9.6 — skill descriptions — chèn vào đây ở Phase 7.

    blocks = _atomic_blocks(node.message for node in path)
    if not blocks:
        raise EmptyPathError(leaf_id)

    budget = token_budget(model_meta)
    kept = _fit(
        blocks,
        budget=budget,
        already_used=count_messages([system_message], model_id=model_meta.id),
        model_id=model_meta.id,
    )

    return [system_message, *(message for block in kept for message in block)]


def token_budget(model_meta: ModelEntry) -> int:
    """Ngân sách token của §9.6, đúng từng chữ:

    ``min(model.context_window, CONTEXT_WINDOW_CAP) - model.max_output - RESERVE_TOKENS``

    `CONTEXT_WINDOW_CAP` là cái hãm: một model khai 1 triệu token context vẫn
    tính tiền theo từng token gửi lên, nên trần này là chỗ chặn hoá đơn, không
    phải chỗ chặn kỹ thuật. Trừ `max_output` vì số token model **sắp sinh** ăn
    chung vào cùng cửa sổ; `RESERVE_TOKENS` là chỗ nuốt sai số của `tiktoken`
    trên model non-OpenAI (xem `tokens.py`) và phần khung mà provider tự thêm.
    """
    return (
        min(model_meta.context_window, settings.CONTEXT_WINDOW_CAP)
        - model_meta.max_output
        - settings.RESERVE_TOKENS
    )


def _system_message(model_meta: ModelEntry) -> dict[str, Any]:
    return {
        "role": MessageRole.SYSTEM.value,
        "content": render_system_prompt(model_display_name=model_meta.display_name),
    }


def _fit(
    blocks: list[list[dict[str, Any]]],
    *,
    budget: int,
    already_used: int,
    model_id: str,
) -> list[list[dict[str, Any]]]:
    """Giữ được bao nhiêu khối tính từ MỚI NHẤT lùi về quá khứ (§9.6).

    Dừng ở khối đầu tiên không vừa, **không** nhảy qua nó để thử khối cũ hơn.
    Nhảy qua sẽ tạo ra một lỗ ở giữa hội thoại: model đọc được câu hỏi hôm qua
    và câu trả lời hôm nay mà không có đoạn nối, và nó sẽ bịa ra đoạn nối đó.
    §9.6 viết "message mới nhất → lùi dần về quá khứ", tức là một đoạn LIỀN
    kề cuối, và C15 cũng nói "N message gần nhất".
    """
    used = already_used
    kept: list[list[dict[str, Any]]] = []

    for block in reversed(blocks):
        cost = sum(count_message(message, model_id=model_id) for message in block)
        if used + cost > budget:
            if not kept:
                raise BudgetTooSmallError(budget=budget, needed=used + cost, model_id=model_id)
            logger.info(
                "cắt ngữ cảnh theo §9.6: giữ %d/%d khối, %d/%d token",
                len(kept),
                len(blocks),
                used,
                budget,
            )
            break
        used += cost
        kept.append(block)

    kept.reverse()
    return kept


def _atomic_blocks(messages: Iterable[Message]) -> list[list[dict[str, Any]]]:
    """Gom đường đi thành các KHỐI không được cắt lẻ (C15).

    Một khối là một trong hai thứ:

    - một message thường, đứng một mình;
    - một message assistant có `tool_calls`, **cộng** mọi message `role=tool`
      đi ngay sau nó và trả lời đúng các `id` mà nó đã khai.

    C15 cấm cắt lẻ **một nửa nào** của cặp, nên hàm này canh cả hai chiều:

    - `tool_result` không có `tool_call` phía trên khai `tool_call_id` của nó
      thì bị bỏ (đây là dòng DoD thứ tư của T-1.4);
    - `tool_call` thiếu dù chỉ một `tool_result` thì cả khối bị gỡ `tool_calls`
      và mọi `tool_result` đi kèm — xem `_dong_khoi`.

    Nửa hỏng xuất hiện được ở hai đường: tổ tiên bị xoá mềm nên `get_path` cắt
    đường đi ngay giữa cặp (§8.3, C12), hoặc một lượt sinh chết giữa lúc chạy
    tool và không bao giờ ghi được message trả lời.
    """
    blocks: list[list[dict[str, Any]]] = []
    #: `tool_call_id` mà khối đang mở đã khai. Rỗng = khối hiện tại không nhận
    #: thêm `tool_result` nào.
    dang_cho: set[str] = set()

    for message in messages:
        wire = _to_wire(message)
        if wire is None:
            # Message chưa xong / đã xoá / rỗng. Nó KHÔNG đóng khối đang mở:
            # một message hỏng chen giữa `tool_call` và `tool_result` của nó
            # không được phép biến cặp đó thành mồ côi.
            continue

        if wire["role"] == MessageRole.TOOL.value:
            if blocks and wire.get("tool_call_id") in dang_cho:
                blocks[-1].append(wire)
            else:
                logger.warning(
                    "bỏ tool_result mồ côi của message %s (tool_call_id=%r) — C15",
                    message.id,
                    wire.get("tool_call_id"),
                )
            continue

        blocks.append([wire])
        dang_cho = _declared_call_ids(wire)

    return [block for block in map(_dong_khoi, blocks) if block]


def _declared_call_ids(wire: dict[str, Any]) -> set[str]:
    return {
        call["id"]
        for call in wire.get("tool_calls") or ()
        if isinstance(call, dict) and isinstance(call.get("id"), str)
    }


def _dong_khoi(block: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """Chốt một khối: hoặc cặp tool đủ đôi, hoặc không còn dấu vết cặp tool nào.

    Nửa còn lại của C15. Gửi một `tool_call` mà thiếu `tool_result` trả lời nó
    cũng là `400 invalid request` y như chiều ngược lại — và đây là chiều dễ
    gặp hơn, vì nó xảy ra mỗi khi một lượt sinh chết sau lúc model đã khai tool
    nhưng trước lúc tool trả lời.

    Xử lý là **gỡ `tool_calls`, giữ phần chữ**, chứ không vứt cả khối: phần chữ
    đó người dùng đã nhìn thấy trên màn hình, và bỏ nó đi tạo ra một lỗ giữa
    hội thoại — đúng thứ mà `_fit` tránh khi nó không nhảy qua khối không vừa.
    Các `tool_result` còn lại trong khối phải đi theo, vì không còn gì khai
    chúng nữa.
    """
    head = block[0]
    declared = _declared_call_ids(head)
    if not declared:
        return block

    answered = {message.get("tool_call_id") for message in block[1:]}
    missing = declared - answered
    if not missing:
        return block

    logger.warning(
        "khối tool thiếu %d/%d tool_result — gỡ tool_calls, giữ phần chữ (C15)",
        len(missing),
        len(declared),
    )
    stripped = {key: value for key, value in head.items() if key != "tool_calls"}
    return [stripped] if stripped["content"] else None


def _to_wire(message: Message) -> dict[str, Any] | None:
    """Đổi một `Message` của DB thành một message trên dây, hoặc `None` nếu bỏ.

    `None` khi: trạng thái chưa có nội dung chốt (`USABLE_STATUSES`), hoặc
    message không mang gì cả — không chữ, không `tool_calls`. Một lượt rỗng
    không giúp model thêm được gì mà vẫn tốn khung `TOKENS_PER_MESSAGE`, và một
    số provider từ chối thẳng `content: ""` ở role `user`.

    **Ngoại lệ: `role=tool` giữ lại kể cả khi rỗng.** "Tool chạy xong và không
    trả về gì" là một kết quả có thật và model cần biết; quan trọng hơn, bỏ nó
    đi sẽ để lại một `tool_call` không có ai trả lời — đúng nửa còn lại của
    C15 mà `_dong_khoi` phải đi dọn.

    **Hợp đồng của cột `messages.tool_calls` (JSONB)** — chốt ở NQ-22 (B-68):
    nó lưu **đúng** khối `tool_calls` của dây OpenAI —
    ``[{"id":…, "type":"function", "function":{"name":…, "arguments":"<JSON thô>"}}]``
    — và đi lên dây nguyên văn, không dựng lại. Bên **ghi** cột đó là worker
    (T-1.6) và nó ghi bằng `ToolCall.to_wire()` của `app/llm/client.py`, tức
    hình dạng này chỉ được viết ra ở đúng một chỗ trong cả backend. `arguments`
    giữ nguyên chuỗi provider đã gửi (điểm 3+4 ở docstring của `client.py`).
    """
    if message.status not in USABLE_STATUSES:
        return None

    wire: dict[str, Any] = {"role": message.role.value, "content": message.content}

    if message.role is MessageRole.ASSISTANT and message.tool_calls:
        wire["tool_calls"] = message.tool_calls
    elif message.role is MessageRole.TOOL:
        # Thiếu `tool_call_id` thì message này vô dụng: provider không biết nó
        # trả lời lời gọi nào. `_atomic_blocks` sẽ loại nó như một mồ côi.
        wire["tool_call_id"] = message.tool_call_id
        return wire

    if not wire["content"] and "tool_calls" not in wire:
        return None

    return wire
