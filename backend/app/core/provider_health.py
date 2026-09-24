"""Provider nào đang trả lời được — nguồn của `available` trong `GET /models`.

KH tham chiếu: §9.3, §9.5, §18.3, RR-5, UC-05 · tasks.md T-3.6, B-192 ·
CLAUDE.md A3.

§9.3 liệt kê bốn thứ mà `GET /models` làm được còn một file tĩnh thì không, và
hàng thứ ba là *"báo '9Router đang tắt' để làm xám model"*. §18.3 chốt hình
dạng: hai trường `available: bool` và `unavailable_reason`. RR-5 gọi việc host
tắt 9Router là ca **thường**, không phải ca lạ. Module này là chỗ trả lời câu
ấy, và nó là chỗ **duy nhất** — `api/v1/models.py` chỉ đọc kết quả.

Đặt ở `app/core/`, KHÔNG ở `app/api/`: §5.3 cấm tầng `api` gọi ra ngoài, và
`scripts/check_hardcode.sh` lệnh 1 kiểm đúng điều đó bằng `grep AsyncClient(`
trên `backend/app/api/`. Cùng lý lẽ đã đặt `core/health_checks.py` ở đây.

┌──────────────────────────────────────────────────────────────────────────┐
│  KHÔNG ĐO LẠI Ở MỖI REQUEST — ĐÓ LÀ CẢ LÝ DO MODULE NÀY CÓ MỘT BỘ NHỚ    │
└──────────────────────────────────────────────────────────────────────────┘

B-192 đo chặng 9Router của `GET /admin/system`: **854 / 806 / 941 ms** ba lần
liên tiếp. Model Picker mở nhiều hơn màn Hệ thống rất nhiều lần, và `GET
/models` còn được gọi lúc mở trang. Một lượt đo cho mỗi request nghĩa là mỗi
lần mở app cộng thêm gần một giây, cho một câu trả lời đổi vài lần một ngày.

Vì vậy kết quả sống trong `_cache` với hạn `TTL_S`. Hệ quả phải nói thẳng:
câu trả lời có thể **cũ tới `TTL_S` giây**. Đó là đánh đổi có chủ ý — thứ tệ
nhất một câu trả lời cũ gây ra là một hàng xám thêm nửa phút (hoặc một hàng
sáng mà bấm vào thì `POST .../messages` trả lỗi của provider). FE **không**
phải lớp bảo vệ (Cạm bẫy ③ của T-3.6); lớp bảo vệ là chính lượt gọi model.

┌──────────────────────────────────────────────────────────────────────────┐
│  CHỈ ĐO PROVIDER `host-dependent`                                        │
└──────────────────────────────────────────────────────────────────────────┘

`availability` là **dữ liệu trong catalog** (§9.2), không phải một danh sách
tên provider viết trong `.py` — A3. Provider `always` đi thẳng vào `available:
True` mà không tốn một gói tin nào: chúng là API công cộng hoặc service trong
compose, và "DeepSeek có sập không" là câu hỏi của lượt gọi thật chứ không
phải của một picker.

Hôm nay đúng một provider là `host-dependent` (9Router, chạy ngoài Docker trên
host Windows). Thêm provider thứ hai cùng loại thì nó tự được đo, không sửa
một dòng nào ở đây — đúng tinh thần §9.8.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import httpx

from app.config.catalog import Catalog, Provider, get_catalog

logger = logging.getLogger(__name__)

#: Trần cho MỘT lượt đo. **Rộng hơn `CHECK_TIMEOUT_S` (2 s) của `/health/deep`
#: một cách có chủ ý**, và đây là lý do đo được:
#:
#: 9Router trả lời trong **717 / 757 / 781 ms** (đo 2026-09-22 trên stack này,
#: khớp 854 / 806 / 941 ms mà B-192 đo ở `/admin/system`). Với trần 2 s thì
#: biên chỉ còn ~2,5× — và một lần chạm trần ở đây **không** giống chạm trần ở
#: `/health/deep`: ở đó nó là một dòng `degraded` cho người vận hành đang nhìn
#: màn hình, còn ở đây nó xám một model **đang chạy được** suốt `TTL_S` giây
#: trước mặt người dùng, kèm một câu nói rằng nguồn ấy không phản hồi.
#:
#: Giá của trần rộng hơn chỉ phải trả khi host **im lặng** (gói tin rơi) — ca
#: hiếm. Ca thường trên máy này là 9Router **tắt hẳn**, và khi ấy TCP bị từ
#: chối trong vài mili giây chứ không chờ hết trần.
PROBE_TIMEOUT_S = 5.0

#: Hạn của một câu trả lời. 30 giây là chỗ cân giữa hai phía: đủ dài để một
#: loạt tab mở cùng lúc chỉ tốn MỘT lượt đo, đủ ngắn để bật 9Router lên rồi
#: bấm nút làm mới trong picker là thấy hàng sáng lại mà không phải F5.
TTL_S = 30.0

#: Giá trị `availability` nghĩa là "sống ngoài Docker, có thể tắt" (§9.2).
#: Chuỗi này khớp `Availability` của `app/config/catalog.py`.
HOST_DEPENDENT = "host-dependent"

#: Câu hiện nguyên văn trong tooltip của Model Picker (T-HD4, UC-05 dòng 2).
#:
#: Không vi phạm A3: A3 cấm literal cho **tên model, giá, giới hạn, URL
#: provider, màu sắc** — không cấm một câu tiếng Việt. Và cái tên duy nhất
#: trong câu này (`{label}`) đến từ catalog chứ không từ đây, nên thêm một
#: provider `host-dependent` không phải sửa chuỗi nào.
#:
#: Có dấu, khác các `message` của `core/errors.py`: những câu kia là mã cho
#: FE phân nhánh (§18 khung lỗi), câu này đi thẳng lên màn hình người dùng —
#: cùng hạng với `badge` trong `model_catalog.json`, thứ cũng có dấu.
NO_RESPONSE_REASON = (
    "{label} đang không phản hồi, nên các model của nguồn này tạm thời không "
    "chọn được. Hãy thử lại sau ít phút, hoặc xem mục Hệ thống để biết chi tiết."
)

#: Cùng câu, cho provider `user_visible: false` (đường trung gian — NQ-119):
#: tên của nó không được tới người dùng, nên câu không chèn `label`. Cũng không
#: chèn `display_provider`: "Google AI đang không phản hồi" là nói sai — thứ
#: không trả lời là đường đi, không phải hãng.
HIDDEN_NO_RESPONSE_REASON = (
    "Nguồn cung cấp model này đang không phản hồi, nên model tạm thời không "
    "chọn được. Hãy thử lại sau ít phút, hoặc xem mục Hệ thống để biết chi tiết."
)


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    """Một provider, dưới dạng Model Picker cần thấy.

    `reason` **luôn** đi cùng `available=False` và luôn là `None` khi
    `available=True`: hai trường nói một chuyện, và để chúng lệch nhau là để
    FE phải đoán xem tin cái nào.
    """

    available: bool
    reason: str | None


#: Kết quả của lượt đo gần nhất, cùng thời điểm hết hạn và **catalog nào đã
#: sinh ra nó**. Vế thứ ba là cách bộ nhớ này tự hết hiệu lực sau `POST
#: /admin/catalog/reload`: `catalog.reload()` thay cả object, nên một phép so
#: sánh `is` là đủ — không cần ai nhớ gọi một hàm dọn (§19.1, S7).
_cache: dict[str, ProviderStatus] = {}
_expires_at: float = 0.0
_probed_catalog: Catalog | None = None

#: Hai tab mở cùng lúc lúc bộ nhớ vừa hết hạn là hai lượt đo song song cho
#: cùng một câu hỏi. Khoá này gộp chúng lại làm một.
_lock = asyncio.Lock()


async def probe_provider(provider: Provider) -> None:
    """Một lượt `GET {base_url}{health_path}`. Hỏng thì **ném**, không nuốt.

    Hàm này cố ý không có timeout của riêng nó: người gọi quyết định chờ bao
    lâu (`PROBE_TIMEOUT_S` ở đây, `CHECK_TIMEOUT_S` ở `health_checks.py`), và
    hai trần thời gian lồng nhau là hai chỗ để lệch.

    Không gắn `Authorization`: `/v1/models` của 9Router trả `200` khi không có
    header, và một phép kiểm sống còn không có lý do gì phải cầm khoá provider
    (C20). `base_url` + `health_path` lấy từ catalog chứ không từ biến môi
    trường — NQ-15/B-26, A3.
    """
    if provider.health_path is None:
        raise ValueError(f"provider '{provider.label}' thiếu health_path trong model_catalog.json")
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{provider.base_url}{provider.health_path}")
        resp.raise_for_status()


async def _probe_one(provider: Provider) -> ProviderStatus:
    """Đo một provider `host-dependent`. **Không bao giờ ném.**

    Thiếu `health_path` thì trả `available=True` chứ không `False`: không đo
    được không phải là đã tắt, và xám một model vì cấu hình thiếu một trường
    là đổ lỗi cho người dùng về một việc của người vận hành. Dòng `WARNING`
    gọi đúng tên provider để chỗ sai lộ ra ở log chứ không ở giao diện.
    """
    if provider.health_path is None:
        logger.warning(
            "provider '%s' khai availability=%s nhung thieu health_path — "
            "coi nhu kha dung vi khong do duoc",
            provider.label,
            HOST_DEPENDENT,
        )
        return ProviderStatus(available=True, reason=None)

    try:
        await asyncio.wait_for(probe_provider(provider), timeout=PROBE_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 — mọi kiểu hỏng đều là "không phản hồi"
        logger.info("provider '%s' khong phan hoi: %s", provider.label, str(exc)[:200])
        return ProviderStatus(
            available=False,
            reason=(
                NO_RESPONSE_REASON.format(label=provider.label)
                if provider.user_visible
                else HIDDEN_NO_RESPONSE_REASON
            ),
        )
    return ProviderStatus(available=True, reason=None)


async def _probe_all(cat: Catalog) -> dict[str, ProviderStatus]:
    """Một lượt đo cho cả catalog. Các provider chạy **song song**."""
    can_do = [(key, p) for key, p in cat.providers.items() if p.availability == HOST_DEPENDENT]
    result = {key: ProviderStatus(available=True, reason=None) for key in cat.providers}
    if not can_do:
        return result
    probed = await asyncio.gather(*(_probe_one(p) for _, p in can_do))
    for (key, _), status in zip(can_do, probed, strict=True):
        result[key] = status
    return result


async def provider_statuses() -> dict[str, ProviderStatus]:
    """Trạng thái của mọi provider trong catalog hiện tại, có nhớ `TTL_S` giây.

    Khoá của dict là khoá provider trong `model_catalog.json` (`ModelEntry.provider`
    trỏ vào đúng đó), **không** phải `label`.
    """
    global _cache, _expires_at, _probed_catalog

    cat = get_catalog()
    if _probed_catalog is cat and time.monotonic() < _expires_at:
        return _cache

    async with _lock:
        # Người khác vừa đo xong trong lúc mình chờ khoá.
        cat = get_catalog()
        if _probed_catalog is cat and time.monotonic() < _expires_at:
            return _cache
        _cache = await _probe_all(cat)
        _expires_at = time.monotonic() + TTL_S
        _probed_catalog = cat
    return _cache


def forget_all() -> None:
    """Vứt bộ nhớ đi. Cho test, và cho một lượt đo lại tường minh."""
    global _cache, _expires_at, _probed_catalog
    _cache = {}
    _expires_at = 0.0
    _probed_catalog = None
