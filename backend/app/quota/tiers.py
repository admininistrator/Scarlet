"""Hạn mức có hiệu lực của một người dùng — tier gộp ghi đè, cache 60 s (§10.4).

KH tham chiếu: §10.4, §10.3, UC-07 · CLAUDE.md A3, A7 · tasks.md T-2.10, T-H6.

§10.4 viết ra đúng ba dòng, và cả file này là chúng:

    tiers(name PK, limit_5h_usd, limit_7d_usd, can_execute_skills, can_use_web,
          max_upload_mb, max_attachments, allowed_model_tags[], is_default)
    users.tier_name → tiers.name
    users.limit_override_json → ghi đè từng trường cho một user cụ thể

    "Đổi hạn mức trong admin panel có hiệu lực ≤ 60 s (cache tier trong Redis
     TTL 60). Đây là AC của UC-07."

╔══════════════════════════════════════════════════════════════════════════╗
║  CACHE CÁI GÌ: KẾT QUẢ ĐÃ GỘP CỦA MỘT USER, KHÔNG PHẢI HÀNG `tiers`      ║
╚══════════════════════════════════════════════════════════════════════════╝

§10.4 viết "cache tier trong Redis TTL 60" — nhưng cache đúng hàng `tiers` thì
**không tiết kiệm được gì**: vế thứ hai của luật (`limit_override_json`) nằm ở
bảng `users`, nên mỗi lần hỏi vẫn phải đi Postgres một chuyến, và chuyến ấy
mới là chuyến đắt. Thứ duy nhất cache được mà bỏ hẳn Postgres ra khỏi đường đi
thường là **kết quả đã gộp**, tức `EffectiveLimits` của một `user_id`.

TTL vẫn là 60 s nên tính chất mà UC-07 đòi không đổi: đổi một hàng `tiers` có
hiệu lực cho **mọi** user của tier đó trong ≤ 60 s, không cần restart, không
cần ai đi xoá khoá. Cái giá là N khoá thay vì một — với 15–20 người dùng (R1)
thì N ≤ 20, và không có bước dọn nào vì TTL tự làm việc đó.

**Không có hàm `invalidate()`.** Một nút gỡ cache là một nút *phải có người
bấm*, và chỗ quên bấm sẽ là chỗ admin đổi hạn mức rồi không hiểu vì sao không
thấy gì. TTL 60 s là luật duy nhất, và nó chạy kể cả khi không ai nhớ tới nó.

╔══════════════════════════════════════════════════════════════════════════╗
║  REDIS CHẾT ⇒ ĐỌC POSTGRES, KHÁC BLACKLIST — VÀ KHÁC CÓ CHỦ Ý           ║
╚══════════════════════════════════════════════════════════════════════════╝

`core/deps.py` chọn `503` khi không hỏi được Redis, vì ở đó Redis là **nguồn
sự thật duy nhất**: không có khoá `bl:user:*` thì không có cách nào khác để
biết một token đã bị thu hồi hay chưa. Ở đây thì ngược lại — §10.3 nói thẳng
"**Redis là cache, Postgres là sự thật**", nên Redis chết chỉ có nghĩa là mất
một lối tắt. Trả `503` cho một lối tắt bị mất là tự khoá cả app vì một thứ
không ai cần.

Vì vậy mọi lỗi Redis ở đây đều thành một dòng WARNING rồi đi tiếp bằng
Postgres. Cùng lý lẽ cho một bản cache **đọc không hiểu được** (ví dụ vừa
deploy một phiên bản thêm trường, còn 60 giây JSON cũ nằm trong Redis): bỏ nó
đi và đọc lại DB, chứ không ném `ValidationError` ra giữa một lượt chat.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from app.config.settings import settings
from app.core.redis import get_redis
from app.db.models import Tier
from app.db.repositories.tiers import TierRepository
from app.db.session import session_scope
from app.quota.windows import LimitType, Window

logger = logging.getLogger(__name__)

#: Tiền tố khoá. Cùng luật với `IDEM_PREFIX`, `RL_IP_PREFIX`, `cancel_key()`:
#: không ai tự nối chuỗi ở chỗ khác, vì một tiền tố gõ lệch ở đây là một cache
#: không bao giờ trúng — và không trúng thì chỉ chậm hơn, tức im lặng.
TIER_CACHE_PREFIX = "tier:limits:"


class UserLimitsNotFoundError(Exception):
    """Không dựng được hạn mức cho `user_id` — user không tồn tại hoặc đã xoá.

    Là một exception chứ không phải `None`, và đó là quyết định an toàn của
    file này: một hàm trả `None` mời người gọi viết `limits or KHONG_GIOI_HAN`,
    còn "không biết người này là ai" thì **không bao giờ** được đọc thành
    "người này không có trần chi tiêu".
    """

    def __init__(self, user_id: uuid.UUID) -> None:
        super().__init__(f"không có tier cho user {user_id} (không tồn tại hoặc đã xoá mềm)")
        self.user_id = user_id


class EffectiveLimits(BaseModel):
    """Hạn mức **thật sự** áp cho một người: tier đã gộp `limit_override_json`.

    Là một `BaseModel` chứ không phải `dataclass` vì nó phải đi qua Redis dưới
    dạng JSON và quay về nguyên vẹn — `model_validate_json` vừa là bộ giải mã
    vừa là phép kiểm kiểu cho bản cache, trong một lời gọi.

    `Decimal` cho hai trường tiền, đúng kiểu `NUMERIC(10,4)` của Phụ lục A.
    Pydantic serialise `Decimal` thành chuỗi JSON nên con số đi vòng qua Redis
    rồi về vẫn là đúng con số ấy, không phải một `float` gần bằng nó.
    """

    model_config = ConfigDict(extra="forbid")

    tier_name: str
    limit_5h_usd: Decimal
    limit_7d_usd: Decimal
    can_execute_skills: bool
    can_use_web: bool
    web_searches_per_day: int
    max_upload_mb: int
    max_attachments: int
    allowed_model_tags: list[str]

    def for_window(self, window: Window) -> Decimal:
        """Hạn mức USD của một cửa sổ trượt — hai cửa sổ, hai cột của `tiers`.

        Là một method của chính `EffectiveLimits` chứ không phải một hàm rời ở
        chỗ gọi, vì phép ánh xạ `5h → limit_5h_usd` / `weekly → limit_7d_usd`
        là **một** luật và nó có hai người hỏi: cửa chặn trước một lượt sinh
        (`quota/estimator.py`) và bản chụp để hiển thị (`quota/snapshot.py`).
        Hai bản chép của cùng một `if` là hai chỗ để lệch, và chỗ lệch ấy sẽ là
        một thanh quota đo cửa sổ này trong khi cửa chặn đo cửa sổ kia.
        """
        if window.limit_type is LimitType.SHORT:
            return self.limit_5h_usd
        return self.limit_7d_usd


#: Những trường mà `users.limit_override_json` được phép đè. `tier_name` không
#: có mặt: đổi tier của một người là sửa cột `users.tier_name`, không phải nhét
#: một tên tier khác vào JSON ghi đè — hai đường làm cùng một việc thì đường
#: thứ hai là đường không ai nhớ khi đọc `SELECT tier_name FROM users`.
OVERRIDABLE_FIELDS = frozenset(EffectiveLimits.model_fields) - {"tier_name"}


def tier_cache_key(user_id: uuid.UUID) -> str:
    return f"{TIER_CACHE_PREFIX}{user_id}"


def merge_override(tier: Tier, override: dict[str, Any] | None) -> EffectiveLimits:
    """Gộp `limit_override_json` lên trên một hàng `tiers` (§10.4).

    Ghi đè **từng trường**, không thay cả khối: `{"limit_5h_usd": 5.0}` chỉ đổi
    hạn mức 5 giờ, mọi trường còn lại vẫn của tier. Đó là chữ của §10.4 ("ghi
    đè từng trường cho một user cụ thể") và cũng là hình dạng dùng được duy
    nhất — bắt admin chép lại cả chín trường để sửa một con số là mời họ chép
    sai tám trường kia.

    **Khoá lạ bị bỏ qua kèm WARNING, khoá hỏng làm rơi CẢ bản ghi đè.** Hai ca
    khác nhau vì hai nguyên nhân khác nhau: một khoá không có trong
    `OVERRIDABLE_FIELDS` là thứ file này không hiểu (có thể là ghi chú của
    admin, có thể là một trường của phiên bản sau), còn một giá trị sai kiểu là
    dữ liệu hỏng — và gộp nửa bản ghi đè hỏng thì cho ra một tập hạn mức mà
    **không ai từng viết ra**. Cả hai ngả đều rơi về hạn mức của tier, tức về
    phía chặt hơn hoặc bằng ý định của admin, không bao giờ rộng hơn.
    """
    base = {
        "tier_name": tier.name,
        "limit_5h_usd": tier.limit_5h_usd,
        "limit_7d_usd": tier.limit_7d_usd,
        "can_execute_skills": tier.can_execute_skills,
        "can_use_web": tier.can_use_web,
        "web_searches_per_day": tier.web_searches_per_day,
        "max_upload_mb": tier.max_upload_mb,
        "max_attachments": tier.max_attachments,
        "allowed_model_tags": list(tier.allowed_model_tags),
    }
    if not override:
        return EffectiveLimits.model_validate(base)

    merged = dict(base)
    for field, value in override.items():
        if field not in OVERRIDABLE_FIELDS:
            logger.warning(
                "limit_override_json chứa khoá không ghi đè được: %r (tier %s) — bỏ qua",
                field,
                tier.name,
            )
            continue
        merged[field] = value

    try:
        return EffectiveLimits.model_validate(merged)
    except ValidationError:
        logger.exception(
            "limit_override_json hỏng kiểu cho tier %s — dùng hạn mức của tier, "
            "BỎ QUA toàn bộ bản ghi đè",
            tier.name,
        )
        return EffectiveLimits.model_validate(base)


async def _read_from_db(user_id: uuid.UUID) -> EffectiveLimits:
    async with session_scope() as session:
        found = await TierRepository(session).get_for_user(user_id)
    if found is None:
        raise UserLimitsNotFoundError(user_id)
    return merge_override(found.tier, found.override)


async def get_effective_limits(user_id: uuid.UUID) -> EffectiveLimits:
    """Hạn mức đang áp cho `user_id`. Đây là đường DUY NHẤT tầng app hỏi câu này.

    Đọc cache trước (Redis, TTL `TIER_CACHE_TTL_S`), trượt thì đọc Postgres rồi
    ghi lại cache. Xem docstring module cho ba quyết định: cache kết quả đã gộp
    chứ không cache hàng `tiers`, không có `invalidate()`, và Redis chết thì đi
    tiếp bằng Postgres.

    Raise:
        UserLimitsNotFoundError: user không tồn tại hoặc đã xoá mềm.
    """
    key = tier_cache_key(user_id)
    redis = get_redis()

    try:
        cached = await redis.get(key)
    except Exception:
        logger.warning("khong doc duoc cache tier cua user %s — doc thang Postgres", user_id)
        cached = None

    if cached is not None:
        try:
            return EffectiveLimits.model_validate_json(cached)
        except ValidationError:
            # Bản cache của một phiên bản trước (thêm/bớt trường). Không phải
            # lỗi của người dùng, và nó tự hết sau ≤ TTL — đọc lại DB, ghi đè.
            logger.warning("cache tier cua user %s khong doc duoc — nap lai tu Postgres", user_id)

    limits = await _read_from_db(user_id)

    try:
        await redis.set(key, limits.model_dump_json(), ex=settings.TIER_CACHE_TTL_S)
    except Exception:
        logger.warning("khong ghi duoc cache tier cua user %s — bo qua", user_id)

    return limits
