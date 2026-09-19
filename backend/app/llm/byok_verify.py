"""Kiểm một khoá BYOK còn sống trước khi lưu (§10.5) — T-2.14.

KH tham chiếu: §10.5 (bảng BYOK, hàng "Kiểm tra khi thêm"), §9.2, C20, C42,
C44 · CLAUDE.md A3, A5, A9 · tasks.md T-2.14.

§10.5: *"Kiểm tra khi thêm: gọi `GET {base_url}/models` (hoặc endpoint rẻ
nhất) để xác nhận key sống, **trước khi lưu**."* Không có bước này thì một khoá
gõ sai nằm im trong DB cho tới lần chat đầu tiên, và người dùng gặp lỗi ở đúng
chỗ khó hiểu nhất — giữa một lượt sinh chữ, chứ không phải ở màn hình họ vừa
bấm Lưu.

┌──────────────────────────────────────────────────────────────────────────┐
│  KHÔNG CÓ LITERAL PROVIDER Ở ĐÂY (A3) — VÀ VÌ SAO A9 KHÔNG CẤM FILE NÀY  │
└──────────────────────────────────────────────────────────────────────────┘

Đường dẫn, cách gắn khoá và địa chỉ đều đọc từ `model_catalog.json`:
`base_url`, `verify_path` (C42), `auth_style` (C44). Thêm một provider vẫn là
sửa **một file JSON** — tiêu chí S15.

A9 ("backend chỉ nói MỘT protocol với model: OpenAI Chat Completions
streaming") nói về đường **sinh chữ**, và đường đó vẫn đi trọn vẹn qua LiteLLM
(`llm/adapters/system.py`). Phép kiểm ở đây không sinh một token nào: nó hỏi
"credential này còn dùng được không". Gửi nó qua LiteLLM là bất khả — LiteLLM
xác thực bằng `LITELLM_MASTER_KEY` của mình, nên câu trả lời sẽ nói về khoá
của **mình** chứ không phải của người dùng. Chính vì vậy Phụ lục §9.2 đặt
`verify_path` vào catalog: nó chỉ có nghĩa cho đúng đường này.

A5 (mọi URL người dùng gửi phải qua `tools/ssrf.py`) không áp: URL ở đây do
**người vận hành** viết trong catalog, không do người dùng gửi. Thứ người dùng
gửi là `provider` — một **khoá tra cứu** vào `providers`, nên một giá trị bịa
ra không ra được URL nào cả (router trả `404` trước khi tới đây).

┌──────────────────────────────────────────────────────────────────────────┐
│  BA KẾT CỤC, VÀ VÌ SAO "KHÔNG HỎI ĐƯỢC" KHÔNG PHẢI "KHOÁ SAI"           │
└──────────────────────────────────────────────────────────────────────────┘

* `ALIVE` — provider trả 2xx. Lưu, `verified_at = now()`.
* `REJECTED` — provider trả 401/403. Lưu **không** được: `400` cho người dùng.
* `SKIPPED` — catalog không cho đủ thứ để hỏi (C42: thiếu `verify_path`; hoặc
  `auth_style` chưa có đường gắn khoá — xem dưới). Lưu, `verified_at = NULL`.

Mọi kết cục còn lại — timeout, DNS hỏng, 500 của provider, 429 — là
`VerifyUnavailable`, và router đổi nó thành `503`. **Không** gộp nó vào
`REJECTED`: nói "khoá của bạn sai" khi thật ra mạng hỏng sẽ khiến người dùng
đi tạo một khoá mới để chữa một sự cố không phải của họ. Và **không** gộp vào
`SKIPPED`: lưu một khoá chưa kiểm được vì provider đang sập là biến một sự cố
tạm thời thành một hàng dữ liệu vĩnh viễn nói dối.

┌──────────────────────────────────────────────────────────────────────────┐
│  `auth_style="query"` CỐ Ý KHÔNG ĐƯỢC HIỆN THỰC (C20)                   │
└──────────────────────────────────────────────────────────────────────────┘

`AuthStyle` của catalog có ba giá trị; hai giá trị đầu (`bearer`, `x-api-key`)
là hai header, tên của chúng là hợp đồng và không phải đoán. Giá trị thứ ba
gắn khoá vào **query string**, và ở đó tên tham số khác nhau theo từng nhà
cung cấp — hôm nay **không provider nào** trong catalog dùng nó, nên mọi lựa
chọn đều là đoán.

Quan trọng hơn: một khoá trong query string là một khoá trong access log của
nginx, trong dòng `INFO` của `httpx`, và trong mọi proxy trên đường đi — tức
dựng sẵn đúng đường rò mà C20 (cạm bẫy của chính task này) sinh ra để đóng.
Đoán một tên tham số để mở đường đó là đánh đổi sai chiều.

Vì vậy `query` rơi vào `SKIPPED` kèm một dòng `WARNING` gọi tên provider — y
hệt ca C42. Xem Backlog khi provider đầu tiên dùng kiểu này xuất hiện.
"""

from __future__ import annotations

import logging
from enum import StrEnum

import httpx

from app.config.catalog import Provider
from app.config.settings import settings

logger = logging.getLogger(__name__)


class VerifyOutcome(StrEnum):
    """Ba kết cục của một lần kiểm khoá — xem docstring module."""

    ALIVE = "alive"
    REJECTED = "rejected"
    SKIPPED = "skipped"


class VerifyUnavailable(Exception):
    """Không hỏi được provider, nên KHÔNG biết khoá sống hay chết.

    Khác `REJECTED` như "chưa đọc được câu trả lời" khác "câu trả lời là
    không" — xem docstring module.
    """


#: Mã trạng thái nghĩa là "provider đã trả lời, và câu trả lời là khoá này
#: không dùng được". Chỉ hai mã này, không phải cả họ `4xx`: `404` là
#: `verify_path` sai (lỗi catalog, không phải lỗi khoá), `429` là bị siết nhịp
#: (khoá có thể hoàn toàn tốt).
_STATUS_KEY_REJECTED = frozenset({httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN})

#: `auth_style` → hàm dựng header mang khoá. Thiếu một `auth_style` trong bảng
#: này nghĩa là "chưa kiểm được", không phải "bỏ qua xác thực" — xem
#: `_headers_for`. Tên header là hợp đồng của HTTP/của provider, không phải
#: cấu hình vận hành, nên chúng là hằng ở đây chứ không ở `.env` (A3, cùng lối
#: `_FIELD_SECRET` của `core/turnstile.py`).
_AUTH_HEADER: dict[str, str] = {
    "bearer": "Authorization",
    "x-api-key": "x-api-key",
}

#: Tiền tố của scheme `Bearer` (RFC 6750).
_BEARER_PREFIX = "Bearer "


def _headers_for(provider: Provider, key: str) -> dict[str, str] | None:
    """Header mang khoá, hoặc `None` nếu `auth_style` này chưa kiểm được."""
    ten_header = _AUTH_HEADER.get(provider.auth_style)
    if ten_header is None:
        return None
    gia_tri = f"{_BEARER_PREFIX}{key}" if provider.auth_style == "bearer" else key
    return {ten_header: gia_tri}


def _client() -> httpx.AsyncClient:
    """Client cho MỘT lần kiểm.

    Tách thành hàm riêng để test bơm `httpx.MockTransport` vào mà vẫn chạy qua
    **toàn bộ** đường thật — dựng URL, gắn header, đọc mã trạng thái. Cùng lý
    do và cùng hình dạng với `_tao_client` của `core/turnstile.py`.
    """
    return httpx.AsyncClient(timeout=settings.BYOK_VERIFY_TIMEOUT_S)


async def verify_key(provider_name: str, provider: Provider, key: str) -> VerifyOutcome:
    """Hỏi provider xem khoá này còn sống không (§10.5).

    Args:
        provider_name: khoá trong `model_catalog.json::providers` — chỉ dùng
            cho log, để một dòng cảnh báo gọi được đúng tên.
        provider: bản ghi provider đã nạp từ catalog.
        key: khoá BYOK **bản rõ**. Không bao giờ đi vào log hay vào exception
            của hàm này (C20).

    Raises:
        VerifyUnavailable: không hỏi được provider — xem docstring module.
    """
    if provider.verify_path is None:
        # C42. Cảnh báo lúc nạp catalog đã có (`_canh_bao_verify_path_thieu`);
        # dòng này nói ra ca **đã xảy ra thật**, tức có một hàng trong DB mang
        # `verified_at IS NULL` vì lý do đó.
        logger.warning(
            "provider '%s' khong khai verify_path — luu khoa BYOK ma KHONG kiem (C42)",
            provider_name,
        )
        return VerifyOutcome.SKIPPED

    headers = _headers_for(provider, key)
    if headers is None:
        logger.warning(
            "provider '%s' dung auth_style='%s' — chua co duong kiem khoa, "
            "luu ma KHONG kiem (xem app/llm/byok_verify.py)",
            provider_name,
            provider.auth_style,
        )
        return VerifyOutcome.SKIPPED

    url = f"{provider.base_url}{provider.verify_path}"
    try:
        async with _client() as client:
            resp = await client.get(url, headers=headers)
    except Exception as loi:
        # KHÔNG log `headers` — nó mang khoá (C20). `logger.exception` in
        # traceback của `httpx`, và traceback ấy đi qua bộ che của
        # `core/log_redact.py` trước khi tới handler.
        logger.exception("khong hoi duoc provider '%s' de kiem khoa BYOK", provider_name)
        raise VerifyUnavailable(provider_name) from loi

    if resp.is_success:
        return VerifyOutcome.ALIVE
    if resp.status_code in _STATUS_KEY_REJECTED:
        logger.info("provider '%s' tu choi mot khoa BYOK: HTTP %s", provider_name, resp.status_code)
        return VerifyOutcome.REJECTED

    logger.warning(
        "provider '%s' tra HTTP %s khi kiem khoa BYOK — coi nhu KHONG hoi duoc",
        provider_name,
        resp.status_code,
    )
    raise VerifyUnavailable(provider_name)
