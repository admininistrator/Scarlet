"""Provider nào đang trả lời được — nguồn của `available` trong `GET /models`.

KH tham chiếu: §9.3, §9.5, §18.3, RR-5, UC-05, §24.2b·S5 · tasks.md T-3.6,
T-S.4, B-192 · NQ-113 · CLAUDE.md A3.

§9.3 liệt kê bốn thứ mà `GET /models` làm được còn một file tĩnh thì không, và
hàng thứ ba là *"báo '9Router đang tắt' để làm xám model"*. §18.3 chốt hình
dạng: hai trường `available: bool` và `unavailable_reason`. RR-5 gọi việc host
tắt 9Router là ca **thường**, không phải ca lạ. Module này là chỗ trả lời câu
ấy, và nó là chỗ **duy nhất** — `api/v1/models.py` chỉ đọc kết quả.

Đặt ở `app/core/`, KHÔNG ở `app/api/`: §5.3 cấm tầng `api` gọi ra ngoài, và
`scripts/check_hardcode.sh` lệnh 1 kiểm đúng điều đó bằng `grep AsyncClient(`
trên `backend/app/api/`. Cùng lý lẽ đã đặt `core/health_checks.py` ở đây.

┌──────────────────────────────────────────────────────────────────────────┐
│  REQUEST KHÔNG BAO GIỜ CHỜ MỘT LƯỢT ĐO (T-S.4, NQ-113)                   │
└──────────────────────────────────────────────────────────────────────────┘

T-3.6 đo **theo yêu cầu** với bộ nhớ 30 s: request nào tới lúc bộ nhớ hết hạn
thì chờ lượt đo. Đo ngày 2026-09-23 với 9Router im lặng (gói tin rơi, không
từ chối TCP): `GET /models` **5.09 s**, rồi 0.22 s, rồi 31 s sau lại **5.06
s** — đúng trần đo mỗi khi bộ nhớ hết hạn, và trong khoảng ấy picker hiện
"Chưa có mô hình nào".

Từ T-S.4 phép đo chạy **ngầm**: một lượt lúc `api` khởi động (`background()`,
gắn vào `lifespan` của `app/main.py`), rồi một lượt mỗi
`PROVIDER_HEALTH_TTL_S` giây trong một tác vụ nền. `provider_statuses()` là
một hàm **đồng bộ** — không có `await` nào trong nó thì không có đường nào để
một request đứng chờ mạng; đó là bảo đảm bằng cấu trúc chứ không bằng kỷ luật.
Nó trả lượt đo gần nhất kèm `checked_at` (thời điểm backend BẮT ĐẦU đo), để
FE nói được "kiểm lúc …" đúng giờ đo chứ không đúng giờ đọc.

Hệ quả phải nói thẳng: câu trả lời có thể **cũ tới một nhịp** (cộng thời gian
của một lượt). Đó là đánh đổi có chủ ý — thứ tệ nhất một câu trả lời cũ gây
ra là một hàng xám thêm nửa phút (hoặc một hàng sáng mà bấm vào thì `POST
.../messages` trả lỗi của provider). FE **không** phải lớp bảo vệ (Cạm bẫy ③
của T-3.6); lớp bảo vệ là chính lượt gọi model.

**Trước lượt đo đầu** (`checked_at` là `None`) mọi provider coi như chọn
được — cùng hướng hỏng với `_AVAILABLE` của `api/v1/models.py`: không biết
không phải là đã tắt. Khoảng ấy chỉ tồn tại khi lượt đầu vượt trần chờ lúc
khởi động, và FE thấy `checked_at: null` thì hỏi lại ở lần mở picker kế.

┌──────────────────────────────────────────────────────────────────────────┐
│  TÁC VỤ NỀN KHÔNG ĐƯỢC CHẾT IM LẶNG (Cạm bẫy ① T-S.4)                    │
└──────────────────────────────────────────────────────────────────────────┘

Một `asyncio.create_task` ném ngoại lệ một lần là dừng mãi, và `available`
đóng băng ở giá trị cuối — không ai thấy gì ngoài một hàng xám không bao giờ
sáng lại. `run_forever()` bọc **từng vòng** trong `try/except Exception`, ghi
`logger.exception`, rồi vẫn ngủ tới nhịp kế. `CancelledError` là
`BaseException` nên lọt qua — tắt tiến trình vẫn dừng được vòng lặp. Và nếu
vòng lặp vẫn thoát bằng đường nào khác, `_log_if_died` ghi `ERROR`.

Nhịp tính từ **lúc bắt đầu** một lượt (tốc độ cố định), không từ lúc nó xong:
một lượt chạm trần 5 s không đẩy lượt sau lùi 5 s. Vì vậy bật lại 9Router thì
trong ≤ một nhịp + thời gian một lượt, bộ nhớ đã sáng.

**Mỗi tiến trình `api` có bộ nhớ riêng** (Cạm bẫy ② T-S.4): N worker uvicorn
là N lượt đo mỗi nhịp. Compose chạy một tiến trình; với R1 (15–20 người) thế
là đủ, và không dựng Redis cho nó — bộ nhớ này phải còn dùng được đúng lúc
Redis là thứ đang hỏng.

`POST /admin/catalog/reload` không cần ai nhớ gọi hàm dọn nào: mỗi lượt đo
đọc `get_catalog()` **lúc chạy**, nên lượt kế dùng catalog mới (S7, §19.1).
Tới lượt ấy, provider mới chưa có trong bộ nhớ thì coi như chọn được.

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
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from app.config.catalog import Catalog, Provider, get_catalog
from app.config.settings import settings

logger = logging.getLogger(__name__)

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


@dataclass(frozen=True, slots=True)
class ProviderSnapshot:
    """Một lượt đo trọn vẹn: trạng thái từng provider + lúc lượt ấy bắt đầu.

    `checked_at is None` ⇔ chưa lượt nào xong kể từ khi tiến trình khởi động;
    khi ấy `statuses` rỗng. Khoá của `statuses` là khoá provider trong
    `model_catalog.json` (`ModelEntry.provider` trỏ vào đúng đó), **không**
    phải `label`.
    """

    checked_at: datetime | None
    statuses: dict[str, ProviderStatus] = field(default_factory=dict)


_UNPROBED = ProviderSnapshot(checked_at=None)

#: Lượt đo gần nhất. Chỉ `refresh()` ghi; mọi request chỉ đọc. Một phép gán
#: tham chiếu là nguyên tử với vòng lặp sự kiện, nên người đọc không bao giờ
#: thấy một lượt đo ghi dở.
_snapshot: ProviderSnapshot = _UNPROBED


def _now() -> datetime:
    """Đồng hồ tường của `checked_at` — một hàm riêng để test thay được."""
    return datetime.now(UTC)


async def probe_provider(provider: Provider) -> None:
    """Một lượt `GET {base_url}{health_path}`. Hỏng thì **ném**, không nuốt.

    Hàm này cố ý không có timeout của riêng nó: người gọi quyết định chờ bao
    lâu (`PROVIDER_PROBE_TIMEOUT_S` ở đây, `CHECK_TIMEOUT_S` ở
    `health_checks.py`), và hai trần thời gian lồng nhau là hai chỗ để lệch.

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
        await asyncio.wait_for(probe_provider(provider), timeout=settings.PROVIDER_PROBE_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 — mọi kiểu hỏng đều là "không phản hồi"
        logger.info("provider '%s' khong phan hoi: %s", provider.label, str(exc)[:200])
        return ProviderStatus(
            available=False,
            reason=no_response_reason(provider, name_route=provider.user_visible),
        )
    return ProviderStatus(available=True, reason=None)


def no_response_reason(provider: Provider, *, name_route: bool) -> str:
    """Câu "không phản hồi" của một provider — một chỗ cho hai người đọc.

    `name_route=True` chèn `label` của **đường đi** — đúng cho provider
    `user_visible`, và cho màn quản trị (`GET /admin/models`, T-S.8): admin
    phải đọc được "9Router … không phản hồi" vì health đo theo đường đi (§9.5).
    `False` ⇒ câu chung của NQ-119, cho người dùng khi đường ấy bị ẩn.
    """
    if name_route:
        return NO_RESPONSE_REASON.format(label=provider.label)
    return HIDDEN_NO_RESPONSE_REASON


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


async def refresh() -> ProviderSnapshot:
    """Một lượt đo với catalog **hiện tại**, rồi thay bộ nhớ. Chỉ nền gọi.

    Đọc `get_catalog()` ở đây, lúc chạy, chứ không nhận catalog từ người gọi:
    đó là toàn bộ cơ chế để lượt đo sau `POST /admin/catalog/reload` dùng
    catalog mới.
    """
    global _snapshot
    checked_at = _now()
    statuses = await _probe_all(get_catalog())
    _snapshot = ProviderSnapshot(checked_at=checked_at, statuses=statuses)
    return _snapshot


def provider_statuses() -> ProviderSnapshot:
    """Lượt đo gần nhất. **Chỉ đọc bộ nhớ, không bao giờ đo** (NQ-113).

    Cố ý là hàm đồng bộ — xem khung đầu module.
    """
    return _snapshot


async def run_forever(
    *,
    sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
    first_done: asyncio.Event | None = None,
) -> None:
    """Vòng lặp nền: đo, ngủ tới nhịp kế, lặp lại — **không bao giờ tự thoát**.

    `sleep`/`clock` truyền vào để test chạy vòng lặp bằng đồng hồ giả và dừng
    nó sau vài vòng (Cạm bẫy ③: không mở một vòng lặp vô hạn thật trong
    `pytest`). `first_done` được `set()` sau lượt đầu **dù lượt ấy hỏng** —
    khởi động chờ một lượt, không chờ một lượt thành công.
    """
    while True:
        started = clock()
        try:
            await refresh()
        except Exception:
            # Cạm bẫy ①: một vòng hỏng không được là vòng cuối.
            logger.exception(
                "luot do provider hong — giu ket qua cu, thu lai sau %s s",
                settings.PROVIDER_HEALTH_TTL_S,
            )
        if first_done is not None:
            first_done.set()
        await sleep(max(0.0, settings.PROVIDER_HEALTH_TTL_S - (clock() - started)))


def _log_if_died(task: asyncio.Task[None]) -> None:
    """Lưới cuối: vòng lặp chỉ được phép kết thúc vì bị huỷ."""
    if task.cancelled():
        return
    exc = task.exception()
    logger.error(
        "vong do provider DA DUNG — available se dong bang toi khi api khoi dong lai",
        exc_info=exc,
    )


@asynccontextmanager
async def background() -> AsyncIterator[None]:
    """Chạy vòng đo nền trong suốt đời tiến trình `api` — dùng trong `lifespan`.

    Chờ lượt đầu tối đa `PROVIDER_PROBE_TIMEOUT_S` (Việc ① T-S.4): đủ để
    request đầu sau khi `api` healthy đã có `checked_at`, và `api` boot chậm
    thêm nhiều nhất một trần đo khi host im lặng (Cạm bẫy ④). Quá trần thì
    **không** huỷ lượt ấy — nó chạy tiếp trong nền và ghi bộ nhớ khi xong.
    """
    first_done = asyncio.Event()
    task = asyncio.create_task(run_forever(first_done=first_done), name="provider-health")
    task.add_done_callback(_log_if_died)
    try:
        await asyncio.wait_for(first_done.wait(), timeout=settings.PROVIDER_PROBE_TIMEOUT_S)
    except TimeoutError:
        logger.warning(
            "luot do provider dau tien chua xong sau %s s — api van khoi dong, "
            "checked_at la null toi khi no xong",
            settings.PROVIDER_PROBE_TIMEOUT_S,
        )
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def forget_all() -> None:
    """Vứt bộ nhớ đi, về trạng thái "chưa đo lần nào". Cho test."""
    global _snapshot
    _snapshot = _UNPROBED
