"""Tool registry (§13.5) — nguồn DUY NHẤT của tên tool, schema và lời gọi (T-6.7a).

KH tham chiếu: §13.5, §12, §20 · NQ-144 (Q-P6-1, Q-P6-3).

`ToolProvider` là điểm cắm §13.5 viết sẵn cho MCP: thêm một nguồn tool là thêm
một provider vào `registry`, không sửa dòng nào ở `workers/generate.py`. Hôm nay
một nguồn — `BuiltinTools` — và một tool: `fetch_url` (client T-6.5).

**Không bao giờ ném.** Tool lạ, tham số hỏng, tool nổ ⇒ `ToolResult(ok=False,
reason=<mã cố định>)` cho model đọc; lượt sinh đi tiếp tới `done`. Mã không
mang host / IP (lối `ssrf.py` `_MESSAGES`).
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.tools.fetch_url import fetch_url

logger = logging.getLogger(__name__)

#: Mã `reason` do registry đặt — thêm vào bộ mã của `fetcher` / `ssrf.py`.
REASON_UNKNOWN_TOOL = "unknown_tool"
REASON_INVALID_ARGUMENTS = "invalid_arguments"
REASON_TOOL_ERROR = "tool_error"
#: Worker đặt: lời gọi vượt `MAX_TOOL_CALLS_PER_TURN` của lượt — không chạy.
REASON_TOO_MANY_CALLS = "too_many_calls"


@dataclass(frozen=True, slots=True)
class UserContext:
    """Ai đang gọi tool — §13.5. T-6.8 / P7 đọc quyền từ đây."""

    user_id: uuid.UUID


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
    #: Chữ cho model — CHƯA cắt, chưa bọc `untrusted_block` (worker làm).
    content: str = ""
    #: `[{url, title}]` — lên chip nguồn (§7.4 `tool_result`); không mang chữ trang.
    sources: list[dict[str, str]] = field(default_factory=list)
    reason: str | None = None


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


class BuiltinTools:
    def list_tools(self, ctx: UserContext) -> list[ToolSpec]:
        return [FETCH_URL]

    async def call(self, name: str, args: dict[str, Any], ctx: UserContext) -> ToolResult:
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
