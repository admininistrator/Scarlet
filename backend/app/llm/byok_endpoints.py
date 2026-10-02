"""Endpoint BYOK do người dùng tự nhập — T-S.19b (NQ-134 ② ③).

KH tham chiếu: §10.5, §12.2, §9.1, C20, C40, C42, C43 · CLAUDE.md A3, A5, A9 ·
B-327.

Khác `byok_verify.py` ở đúng một điểm, và điểm ấy đổi mọi thứ: `base_url` ở đây
do **người dùng** gửi, nên A5 áp. Mọi lượt gọi tới nó — kiểm, liệt kê model,
sinh chữ — đi qua `check_base_url()` rồi `pinned_client()` của T-6.3, không
theo redirect. Đường này không có lớp 1 của §12.2 (`api` / `worker` ở mạng
`internal`, NQ-134 ①): lớp 2–4 là tất cả.

Model của endpoint không có trong catalog, nên nó đi qua app dưới dạng một
`ModelEntry` dựng tại chỗ (`endpoint_model`): id `byok:<endpoint_id>/<model>`,
provider `byok:<endpoint_id>`, không suy luận, không vision, không giá — tầng
trên (`_pick_reasoning`, `meter`, ngân sách §9.6) chạy nguyên như với model
catalog.

Không có `logger` (C20, cùng lối `api/v1/settings.py`).
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import catalog
from app.config.catalog import _VERSION_SEGMENT, ModelEntry
from app.config.settings import settings
from app.db.repositories import ByokEndpointRepository
from app.tools.ssrf import CheckedUrl, UnsafeUrlError, pinned_client, validate_url

#: Tiền tố của model id và của `usage_events.provider` cho endpoint tự nhập.
BYOK_PREFIX = "byok:"

#: Đường liệt kê model của Chat Completions — cũng là phép kiểm khoá (§10.5, C42).
MODELS_PATH = "/models"

_BEARER_PREFIX = "Bearer "
_STATUS_KEY_REJECTED = frozenset({httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN})
#: Endpoint không có `/models` — lưu được, chưa xác thực, FE cho gõ tay (C42).
_STATUS_NO_LIST = frozenset({httpx.codes.NOT_FOUND, httpx.codes.METHOD_NOT_ALLOWED})

BaseUrlReason = Literal["scheme", "userinfo", "query", "host", "version"]
_BASE_URL_MESSAGES: dict[BaseUrlReason, str] = {
    "scheme": "base URL phai dung https (khoa API di trong header)",
    "userinfo": "base URL khong duoc chua thong tin dang nhap",
    "query": "base URL khong duoc co query hay fragment",
    "host": "base URL khong hop le",
    "version": "base URL phai ket thuc bang segment phien ban, vi du /v1",
}


class BaseUrlRejected(Exception):
    """Base URL sai hình dạng — bị chặn trước cả `validate_url()`."""

    def __init__(self, reason: BaseUrlReason) -> None:
        super().__init__(_BASE_URL_MESSAGES[reason])
        self.reason: BaseUrlReason = reason


def normalize_base_url(raw: str) -> str:
    """Chỉ `https`, không userinfo / query / fragment, bỏ `/` cuối, đòi segment
    phiên bản ở cuối (C43, cùng luật `Catalog._base_url_has_version`).
    """
    text = raw.strip()
    try:
        url = httpx.URL(text)
    except httpx.InvalidURL:
        raise BaseUrlRejected("host") from None
    if url.scheme != "https":
        raise BaseUrlRejected("scheme")
    if url.userinfo:
        raise BaseUrlRejected("userinfo")
    if url.query or url.fragment or "?" in text or "#" in text:
        raise BaseUrlRejected("query")
    if not url.host:
        raise BaseUrlRejected("host")
    path = url.path.rstrip("/")
    if not _VERSION_SEGMENT.match(path.rsplit("/", 1)[-1]):
        raise BaseUrlRejected("version")
    return str(url.copy_with(path=path))


async def check_base_url(base_url: str) -> CheckedUrl:
    """`validate_url()` (A5) có trần thời gian cho DNS — B-327.

    `getaddrinfo` chờ theo resolver hệ thống, ngoài mọi timeout của `httpx`;
    hết `BYOK_VERIFY_TIMEOUT_S` ⇒ mã `dns` (không chắc thì đóng).
    """
    try:
        async with asyncio.timeout(settings.BYOK_VERIFY_TIMEOUT_S):
            return await validate_url(base_url)
    except TimeoutError:
        raise UnsafeUrlError("dns") from None


# ─────────────────────────── kiểm + liệt kê model ───────────────────────────


class ProbeOutcome(StrEnum):
    ALIVE = "alive"
    REJECTED = "rejected"
    #: Endpoint không có `GET /models` — khoá chưa kiểm được (C42).
    UNVERIFIED = "unverified"


@dataclass(frozen=True, slots=True)
class ProbeResult:
    outcome: ProbeOutcome
    models: list[str]


class ProbeUnavailable(Exception):
    """Không hỏi được endpoint — không biết khoá sống hay chết (⇒ `503`)."""


async def probe(base_url: str, key: str) -> ProbeResult:
    """`GET {base_url}/models` bằng khoá này, qua transport ghim IP (T-6.3).

    `base_url` đã qua `normalize_base_url`. Không theo redirect.

    Raises:
        UnsafeUrlError: lớp 2–3 của §12.2 từ chối.
        ProbeUnavailable: mạng hỏng, timeout, hay endpoint trả mã lạ.
    """
    checked = await check_base_url(base_url)
    headers = {"Authorization": f"{_BEARER_PREFIX}{key}"}
    try:
        async with pinned_client(checked, timeout=settings.BYOK_VERIFY_TIMEOUT_S) as client:
            resp = await client.get(f"{base_url}{MODELS_PATH}", headers=headers)
    except httpx.HTTPError:
        # Thông điệp của `httpx` có URL, không có header — nhưng không cần nó.
        raise ProbeUnavailable from None

    if resp.status_code in _STATUS_KEY_REJECTED:
        return ProbeResult(ProbeOutcome.REJECTED, [])
    if resp.status_code in _STATUS_NO_LIST:
        return ProbeResult(ProbeOutcome.UNVERIFIED, [])
    if not resp.is_success:
        raise ProbeUnavailable
    return ProbeResult(ProbeOutcome.ALIVE, _model_ids(resp))


def _model_ids(resp: httpx.Response) -> list[str]:
    """`data[].id` của danh sách model; hình dạng lạ ⇒ `[]` (FE cho gõ tay)."""
    try:
        body: Any = resp.json()
    except ValueError:
        return []
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        return []
    ids = (item.get("id") for item in data if isinstance(item, dict))
    return sorted({i for i in ids if isinstance(i, str) and i})


# ─────────────────────────── model id `byok:<id>/<model>` ───────────────────


def model_id_for(endpoint_id: uuid.UUID, model: str) -> str:
    return f"{BYOK_PREFIX}{endpoint_id}/{model}"


def provider_for(endpoint_id: uuid.UUID) -> str:
    """`usage_events.provider` của lượt gọi endpoint này."""
    return f"{BYOK_PREFIX}{endpoint_id}"


def parse_model_id(model_id: str) -> tuple[uuid.UUID, str] | None:
    """`byok:<uuid>/<model>` → `(uuid, model)`. Tên model được chứa `/`."""
    if not model_id.startswith(BYOK_PREFIX):
        return None
    endpoint, sep, model = model_id.removeprefix(BYOK_PREFIX).partition("/")
    if not sep or not model:
        return None
    try:
        return uuid.UUID(endpoint), model
    except ValueError:
        return None


def endpoint_id_of(model: ModelEntry) -> uuid.UUID | None:
    """Endpoint của một model đã dựng bằng `endpoint_model`, hoặc `None` (catalog)."""
    if not model.provider.startswith(BYOK_PREFIX):
        return None
    return uuid.UUID(model.provider.removeprefix(BYOK_PREFIX))


def endpoint_model(endpoint_id: uuid.UUID, label: str, model: str) -> ModelEntry:
    """`ModelEntry` tại chỗ cho một model của endpoint: chỉ chữ, không suy luận,
    không giá. `context_window` / `max_output` từ `Settings` (A3).
    """
    return ModelEntry(
        id=model_id_for(endpoint_id, model),
        display_name=model,
        provider=provider_for(endpoint_id),
        display_provider=label,
        upstream_model=model,
        context_window=settings.BYOK_ENDPOINT_CONTEXT_WINDOW,
        max_output=settings.BYOK_ENDPOINT_MAX_OUTPUT,
        pricing_mode="unmetered",
    )


async def resolve_model(
    session: AsyncSession, *, user_id: uuid.UUID, model_id: str
) -> ModelEntry | None:
    """Model theo id — catalog, hoặc model của một endpoint **của chính người này**.

    Endpoint tra theo `user_id` trong SQL; của người khác, đã xoá, hay model
    không còn trong `models` của nó ⇒ `None` (⇒ `MODEL_UNKNOWN`).
    """
    if not model_id.startswith(BYOK_PREFIX):
        return catalog.get_model(model_id)
    parsed = parse_model_id(model_id)
    if parsed is None:
        return None
    endpoint_id, name = parsed
    row = await ByokEndpointRepository(session).get(user_id=user_id, endpoint_id=endpoint_id)
    if row is None or name not in row.models:
        return None
    return endpoint_model(row.id, row.label, name)
