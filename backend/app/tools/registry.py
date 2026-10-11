"""Tool registry (§13.5) — nguồn DUY NHẤT của tên tool, schema và lời gọi (T-6.7a).

KH tham chiếu: §13.5, §12, §20 · NQ-144 (Q-P6-1, Q-P6-3).

`ToolProvider` là điểm cắm §13.5 viết sẵn cho MCP: thêm một nguồn tool là thêm
một provider vào `registry`, không sửa dòng nào ở `workers/generate.py`. Hôm nay
một nguồn — `BuiltinTools` — và ba tool: `fetch_url` (client T-6.5) và
`web_search` (`SearchProvider` T-6.1, T-6.7b), cùng công tắc "Tìm web" (Q-P6-3);
`load_skill` (T-7.6, §13.2 tầng 2) khi user bật ≥ 1 skill. Công tắc nằm ở
`list_tools(ctx)` — tool không có trong danh sách thì gọi cũng là `unknown_tool`.

**Không bao giờ ném.** Tool lạ, tham số hỏng, tool nổ ⇒ `ToolResult(ok=False,
reason=<mã cố định>)` cho model đọc; lượt sinh đi tiếp tới `done`. Mã không
mang host / IP (lối `ssrf.py` `_MESSAGES`).
"""

from __future__ import annotations

import json
import logging
import math
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from app.quota.tiers import get_effective_limits
from app.quota.web_searches import take_search
from app.skills.loader import SKILL_FILE, SKILLS_DIR
from app.tools.fetch_url import fetch_url
from app.tools.web_search import SearchHit, SearchProvider, TavilySearch

logger = logging.getLogger(__name__)

#: Mã `reason` do registry đặt — thêm vào bộ mã của `fetcher` / `ssrf.py`.
REASON_UNKNOWN_TOOL = "unknown_tool"
REASON_INVALID_ARGUMENTS = "invalid_arguments"
REASON_TOOL_ERROR = "tool_error"
#: Worker đặt: lời gọi vượt `MAX_TOOL_CALLS_PER_TURN` của lượt — không chạy.
REASON_TOO_MANY_CALLS = "too_many_calls"
#: Hết `web_searches_per_day` trong 24 h trượt (T-6.8) — không gọi Tavily.
REASON_WEB_QUOTA = "web_quota"
#: `load_skill` với tên không thuộc skill user đã bật (T-7.6).
REASON_UNKNOWN_SKILL = "unknown_skill"

#: `web_search` hỏng (UC-08 dòng 5): câu CỦA MÌNH cho model, đi sau dòng lỗi có
#: mã — để model trả lời bằng kiến thức sẵn có thay vì im hay bịa nguồn.
SEARCH_UNAVAILABLE = (
    "Không tìm được trên web lúc này. Hãy trả lời bằng kiến thức sẵn có và nói rõ "
    "là chưa kiểm được trên web."
)

#: Câu cho model khi hết lượt search (T-6.8), cùng vai `SEARCH_UNAVAILABLE`.
WEB_QUOTA_TEXT = (
    "Đã dùng hết {limit} lượt tìm web trong 24 giờ{refill}. Hãy trả lời bằng kiến "
    "thức sẵn có và nói rõ là chưa kiểm được trên web."
)
WEB_QUOTA_REFILL = "; có lại một lượt lúc {at} (UTC)"

#: `load_skill` tên lạ: liệt skill CỦA user này để model tự sửa (không lộ của người khác).
UNKNOWN_SKILL_TEXT = "Skill đang bật: {names}."


@dataclass(frozen=True, slots=True)
class UserContext:
    """Ai đang gọi tool — §13.5. Quyền đọc lúc gọi qua `get_effective_limits` (T-6.8)."""

    user_id: uuid.UUID
    #: Công tắc "Tìm web" của lượt (`messages.web_tools`, Q-P6-3).
    web_tools: bool = False
    #: Tên skill user đã bật lúc lượt bắt đầu (T-7.6) — rỗng ⇒ không `load_skill`.
    skills: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]

    def to_wire(self) -> dict[str, Any]:
        """Một phần tử `tools` của Chat Completions (A9)."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(frozen=True, slots=True)
class ToolResult:
    ok: bool
    #: `ok`: chữ cho model — CHƯA cắt, chưa bọc `untrusted_block` (worker làm).
    #: `not ok`: câu của registry (không bao giờ chữ của bên ngoài), hoặc rỗng.
    content: str = ""
    #: `[{url, title}]` — lên chip nguồn (§7.4 `tool_result`); không mang chữ trang.
    sources: list[dict[str, str]] = field(default_factory=list)
    reason: str | None = None
    #: Nội dung CỦA TA (`SKILL.md`, T-7.6) ⇒ worker không bọc `untrusted_block` (§20).
    trusted: bool = False


class ToolProvider(Protocol):
    def list_tools(self, ctx: UserContext) -> list[ToolSpec]: ...

    async def call(self, name: str, args: dict[str, Any], ctx: UserContext) -> ToolResult: ...


FETCH_URL = ToolSpec(
    name="fetch_url",
    description=(
        "Đọc nội dung chữ của một trang web công khai theo URL http(s). Dùng khi "
        "người dùng đưa một đường link hoặc cần đọc một trang cụ thể."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL đầy đủ, http:// hoặc https://"}
        },
        "required": ["url"],
    },
)


WEB_SEARCH = ToolSpec(
    name="web_search",
    description=(
        "Tìm trên web, trả về danh sách kết quả (tiêu đề, URL, đoạn trích). Dùng khi "
        "cần thông tin mới, sự kiện gần đây hoặc cần nguồn để dẫn."
    ),
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Câu cần tìm"}},
        "required": ["query"],
    },
)

LOAD_SKILL = ToolSpec(
    name="load_skill",
    description=(
        "Đọc hướng dẫn đầy đủ của một skill đang bật (danh sách ở system prompt). "
        "Gọi trước khi làm việc mà skill đó mô tả."
    ),
    parameters={
        "type": "object",
        "properties": {"name": {"type": "string", "description": "Tên skill"}},
        "required": ["name"],
    },
)

#: Nguồn tìm của `web_search` — biến module để test thay (lối `fetch_url`).
search_provider: SearchProvider = TavilySearch()


def _hits_text(hits: tuple[SearchHit, ...]) -> str:
    """`title · url · content` từng kết quả — chữ do trang đặt, worker bọc `untrusted_block`."""
    return "\n\n".join(f"{i}. {h.title} · {h.url}\n{h.content}" for i, h in enumerate(hits, 1))


class BuiltinTools:
    def list_tools(self, ctx: UserContext) -> list[ToolSpec]:
        web = [FETCH_URL, WEB_SEARCH] if ctx.web_tools else []
        return [*web, LOAD_SKILL] if ctx.skills else web

    async def call(self, name: str, args: dict[str, Any], ctx: UserContext) -> ToolResult:
        if name == LOAD_SKILL.name:
            return _load_skill(args, ctx)
        if name == WEB_SEARCH.name:
            return await _web_search(args, ctx)
        if name != FETCH_URL.name:
            return ToolResult(ok=False, reason=REASON_UNKNOWN_TOOL)
        url = args.get("url")
        if not isinstance(url, str) or not url:
            return ToolResult(ok=False, reason=REASON_INVALID_ARGUMENTS)
        page = await fetch_url(url)
        if not page.ok:
            return ToolResult(ok=False, reason=page.reason)
        return ToolResult(
            ok=True,
            content=page.text,
            sources=[{"url": page.final_url or url, "title": page.title or ""}],
        )


def _load_skill(args: dict[str, Any], ctx: UserContext) -> ToolResult:
    """Tầng 2 (§13.2): nguyên `SKILL.md` — worker cắt ở `TOOL_RESULT_MAX_CHARS`.

    Chỉ skill trong `ctx.skills` (đã bật, tên đã qua `_NAME_RE` của loader ⇒
    không `..`). Đọc từ `SKILLS_DIR` của tiến trình này (mount `:ro` ở cả
    `api` lẫn `worker`, B-404 ①); file mất ⇒ `OSError` ⇒ registry trả `tool_error`.
    """
    name = args.get("name")
    if not isinstance(name, str) or not name:
        return ToolResult(ok=False, reason=REASON_INVALID_ARGUMENTS)
    if name not in ctx.skills:
        return ToolResult(
            ok=False,
            content=UNKNOWN_SKILL_TEXT.format(names=", ".join(sorted(ctx.skills))),
            reason=REASON_UNKNOWN_SKILL,
        )
    text = (SKILLS_DIR / name / SKILL_FILE).read_text(encoding="utf-8")
    return ToolResult(ok=True, content=text, trusted=True)


async def _web_search(args: dict[str, Any], ctx: UserContext) -> ToolResult:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        return ToolResult(ok=False, reason=REASON_INVALID_ARGUMENTS)
    # Trần đọc lúc gọi (B-153), kiểm TRƯỚC Tavily; hết ⇒ tool lỗi, lượt vẫn chạy (UC-08).
    limit = (await get_effective_limits(ctx.user_id)).web_searches_per_day
    refill_at = await take_search(ctx.user_id, limit=limit, now=time.time())
    if refill_at is not None:
        refill = (
            ""
            if math.isinf(refill_at)
            else WEB_QUOTA_REFILL.format(
                at=datetime.fromtimestamp(refill_at, UTC).isoformat(timespec="seconds")
            )
        )
        return ToolResult(
            ok=False,
            content=WEB_QUOTA_TEXT.format(limit=limit, refill=refill),
            reason=REASON_WEB_QUOTA,
        )
    found = await search_provider.search(query)
    if found.error is not None:
        return ToolResult(ok=False, content=SEARCH_UNAVAILABLE, reason=found.error.value)
    return ToolResult(
        ok=True,
        content=_hits_text(found.results),
        sources=[{"url": h.url, "title": h.title} for h in found.results],
    )


class Registry:
    def __init__(self, providers: list[ToolProvider]) -> None:
        self._providers = providers

    def specs(self, ctx: UserContext) -> list[ToolSpec]:
        return [spec for p in self._providers for spec in p.list_tools(ctx)]

    async def call(self, name: str, arguments: str, ctx: UserContext) -> ToolResult:
        """`arguments` là chuỗi JSON thô của model (NQ-22) — parse ở đây, một lần."""
        owner = next(
            (p for p in self._providers if any(s.name == name for s in p.list_tools(ctx))), None
        )
        if owner is None:
            return ToolResult(ok=False, reason=REASON_UNKNOWN_TOOL)
        try:
            args = json.loads(arguments or "{}")
        except ValueError:
            args = None
        if not isinstance(args, dict):
            return ToolResult(ok=False, reason=REASON_INVALID_ARGUMENTS)
        try:
            return await owner.call(name, args, ctx)
        except Exception:  # noqa: BLE001 — tool nổ là dữ liệu cho model, không phải lỗi lượt
            logger.exception("tool %s no — tra ok=false cho model", name)
            return ToolResult(ok=False, reason=REASON_TOOL_ERROR)


registry = Registry([BuiltinTools()])
