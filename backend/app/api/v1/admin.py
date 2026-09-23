"""Admin panel — **cả mười một** endpoint của §18.5.

    GET    /api/v1/admin/users                   danh sách, lọc theo status
    POST   /api/v1/admin/users/{id}/approve      pending_approval → active
    POST   /api/v1/admin/users/{id}/reject       pending_approval → rejected
    POST   /api/v1/admin/users/{id}/suspend      active → suspended
    PATCH  /api/v1/admin/users/{id}              tier · ghi đè hạn mức
    GET    /api/v1/admin/usage                   chi phí, TÁCH metered/unmetered
    POST   /api/v1/admin/catalog/reload          nạp lại model_catalog.json
    GET    /api/v1/admin/tiers                   bảng hạn mức          (T-2.20)
    PATCH  /api/v1/admin/tiers/{name}            đổi hạn mức CẢ tier   (T-2.20)
    GET    /api/v1/admin/system                  hàng đợi · stream · health
    GET    /api/v1/admin/audit-logs              sổ audit, lọc + con trỏ

KH tham chiếu: §16.3, §18.5, §20, §11.1, §11.3, §10.4, §10.5, §9.5, §21.2 ·
Cạm bẫy C16 · CLAUDE.md A3, A7 · tasks.md T-2.16, T-2.20, B-34, B-141 (NQ-61),
B-177 (NQ-67).

Bảy endpoint đầu là T-2.16; bốn endpoint cuối là T-2.20, và chúng đóng nốt ba
màn hình của §16.3 mà T-2.16/T-2.19 cố ý để lại ("Hệ thống", "Audit log", và
nửa "đổi" của hạn mức). T-3.12 (giao diện đầy đủ) thêm năm thứ, không thêm
endpoint nào: hai cột NQ-66 của `GET /admin/users`, trần cửa sổ của
`GET /admin/usage` (B-175), "với ai" đọc được của sổ audit (B-191), bộ nhớ
healthcheck của màn Hệ thống (B-192), và TTL hạn mức trong `GET /admin/tiers`.

╔══════════════════════════════════════════════════════════════════════════╗
║  QUYỀN GẮN Ở ROUTER, KHÔNG Ở TỪNG ENDPOINT                               ║
╚══════════════════════════════════════════════════════════════════════════╝

Cạm bẫy của task viết nguyên văn: *"quên `require_admin` ở MỘT endpoint là
đủ"*. Vì vậy trong file này **không có** một dòng `Depends(require_admin)` nào
— nó nằm ở đúng một chỗ, lời gọi `include_router` trong `api/v1/__init__.py`,
cạnh `require_app_access` của T-2.7 với cùng lý lẽ. Endpoint thứ tám thêm vào
file này sẽ được bảo vệ vì **vị trí** của nó, không vì ai đó nhớ chép thêm một
dòng; và `tests/api/test_admin_authz.py` lặp qua **bảng định tuyến thật** của
FastAPI chứ không qua một danh sách chép tay, nên một endpoint mới không đi
kèm phép kiểm là một test đỏ chứ không phải một lỗ im lặng.

Đây cũng là chỗ **B-34 được đóng**: `POST /admin/catalog/reload` mở toang từ
T-0.7 vì lúc đó chưa có hệ thống auth nào để gắn vào.

╔══════════════════════════════════════════════════════════════════════════╗
║  §11.1 LÀ MỘT BẢNG, NÊN BA NÚT BẤM CŨNG LÀ MỘT BẢNG                      ║
╚══════════════════════════════════════════════════════════════════════════╝

`_PHEP_CHUYEN` dưới đây là máy trạng thái của §11.1 đọc theo chiều của admin:
mỗi nút bấm là một đích đến cộng với tập trạng thái **đi từ đó tới được**. Ba
`if` rải trong ba handler sẽ là ba luật mà không ai đọc cùng lúc được — đúng
cạm bẫy mà T-2.7 đã đóng cho chiều ngược lại (`STATUSES_CAN_*` trong
`core/deps.py`).

Hai mũi tên **không** có trong sơ đồ §11.1 mà vẫn nằm trong bảng, và lý do là
một câu của chính `core/deps.py`: *"`rejected`/`suspended` là hai trạng thái
CUỐI: không có đường nào tự đi ra khỏi chúng, **chỉ admin mới đổi được**
(§16.3)"*. Không endpoint nào khác trong app làm được việc đó, nên nếu
`approve` không nhận hai trạng thái ấy thì câu trên là một lời hứa suông —
một tài khoản bị khoá nhầm sẽ phải sửa bằng `psql`.

`pending_email` thì **không** duyệt được, và đó là chủ ý: §11.1 bắt đi qua
`pending_approval` bằng cách bấm link trong thư, một việc không ai bấm hộ
được. Duyệt tắt cho nó là cấp tài khoản cho một hộp thư chưa ai chứng minh là
có thật.

╔══════════════════════════════════════════════════════════════════════════╗
║  B-141 (NQ-61): DUYỆT XONG THÌ ĐẶT MỐC `bl:user:`, KHÔNG THU HỒI FAMILY  ║
╚══════════════════════════════════════════════════════════════════════════╝

`require_status` đọc `status` từ **claim** của access token (T-2.7), nên một
người vừa được duyệt vẫn mang token `pending_approval` tới hết
`ACCESS_TOKEN_TTL_MIN`. `approve` vì vậy gọi `blacklist.dat_moc_user()` — đúng
**nửa Redis** của §11.3, không phải cả hai nửa:

* mốc `bl:user:{uid}` giết mọi access token phát **trước** thời điểm duyệt
  (`bi_chan` so `iat < mốc`), nên cửa sổ cũ đóng ngay ở request kế tiếp;
* refresh family trong Postgres **không** bị đụng tới, nên cookie refresh 30
  ngày còn sống và `POST /auth/refresh` (nó `get_by_id` rồi đọc `status` mới
  từ DB) phát ra cookie phiên mang `status='active'`.

Kết quả: người dùng không phải gõ lại mật khẩu cho một tin vui. `suspend` thì
gọi **cả hai** nửa (`thu_hoi_moi_phien`) vì §11.3 nói thẳng *"Admin suspend →
như đổi mật khẩu"* — ở đó mục đích là cắt đường quay lại, không phải làm mới
một claim.

`reject` **không** thu hồi gì: §11.3 chỉ liệt ba nhánh và `rejected` không
nằm trong đó (T-2.7 đã ghi lại điều này). Nó không cần — mọi route đều trả
`403 ACCOUNT_DISABLED` cho trạng thái ấy ngay từ claim, không phải đợi ai thu
hồi cái gì.

╔══════════════════════════════════════════════════════════════════════════╗
║  AUDIT GHI TRONG CÙNG TRANSACTION VỚI VIỆC NÓ MÔ TẢ                      ║
╚══════════════════════════════════════════════════════════════════════════╝

§20 hàng "Audit": *"Mọi hành động admin ghi `audit_logs`"*. Ở đây "mọi hành
động" nghĩa là mọi endpoint **đổi một thứ gì đó** — bốn cái `POST`/`PATCH`
cộng `catalog/reload`. Hai endpoint `GET` không ghi: đọc một danh sách không
phải một hành động, và một sổ audit mà 90% số dòng là "có người mở màn hình"
là một sổ không ai còn đọc nữa.

Dòng sổ và thay đổi nó mô tả nằm trong **một** `session_scope()`, nên chúng
cùng sống hoặc cùng chết — xem `db/repositories/audit_logs.py` cho hai khe mà
thứ tự ngược lại mở ra.

**Không có audit cho một thao tác không đổi gì.** Bấm Duyệt hai lần thì lần
thứ hai trả `200` và **không** ghi dòng nào: trạng thái đích đã đạt, không có
việc gì xảy ra để mà ghi. Ngả kia (`409` cho lần thứ hai) biến một cú double
click thành một lỗi đỏ trên màn hình admin, còn ngả "ghi thêm một dòng" thì
làm sổ nói rằng cùng một người được duyệt hai lần.

Luật ấy áp nguyên cho `PATCH /admin/tiers/{name}` của T-2.20, và bốn endpoint
mới chia đúng theo nó: một cái **đổi** thứ gì đó nên ghi sổ, ba cái chỉ **đọc**
nên không ghi dòng nào — kể cả `GET /admin/audit-logs`, thứ mà ghi sổ mỗi lần
mở sẽ tự bơm cho chính nó đầy những dòng "có người vừa đọc sổ".

╔══════════════════════════════════════════════════════════════════════════╗
║  T-2.20: ĐỔI HÀNG `tiers` KHÔNG ĐỤNG TỚI CACHE — TTL 60 s LÀ LUẬT DUY NHẤT ║
╚══════════════════════════════════════════════════════════════════════════╝

Cạm bẫy của task viết thẳng ra: cache của T-2.10 nhớ `tier:limits:{user_id}`,
tức **kết quả đã gộp của từng người**, không nhớ hàng `tiers`. Nên xoá một
khoá đặt theo *tên tier* là xoá một khoá chưa từng tồn tại — một lời gọi chạy
xong, không báo lỗi, và để lại cảm giác đã gỡ cache.

Ba đường đi tiếp, và đường đã chọn là đường **không làm gì cả** (NQ-51 lần
nữa): §10.4 hứa "có hiệu lực ≤ 60 s", `TIER_CACHE_TTL_S` đúng bằng 60, nên lời
hứa đã được giữ mà không cần ai bấm nút nào. Đường thứ hai — `SELECT id FROM
users WHERE tier_name = :ten` rồi `DEL` từng khoá — nhanh hơn, nhưng nó dựng
lại đúng cái `invalidate()` mà `quota/tiers.py` đã cố ý không viết, và chỗ
quên gọi nó sau này sẽ là chỗ admin đổi hạn mức rồi không hiểu vì sao không
thấy gì. Đường thứ ba — `SCAN tier:limits:*` rồi xoá sạch — cạm bẫy đã cấm
đích danh: nó ném cả hạn mức của người thuộc tier khác đi.

╔══════════════════════════════════════════════════════════════════════════╗
║  `GET /admin/system`: REDIS CHẾT LÀ MỘT CÂU TRẢ LỜI, KHÔNG PHẢI MỘT 500  ║
╚══════════════════════════════════════════════════════════════════════════╝

Đây là màn hình người ta mở **khi** có sự cố, nên nó là màn hình cuối cùng
được phép chết theo sự cố ấy. Mỗi con số vì vậy hỏi một nguồn khác nhau và
hỏng riêng: `queue_depth` đi Redis, `streams_dang_chay` đi Postgres, `version`
không đi đâu cả. Nguồn nào không trả lời thì ô ấy là `null`, và **lý do** nằm ở
`health` — một chỗ duy nhất, chứ không phải một chuỗi lỗi chép lại cạnh từng ô.

Hệ quả cố ý: endpoint này luôn `200`. Nó **không** trả `503` như
`GET /health/deep` — hai endpoint trả lời hai câu hỏi khác nhau. `/health/deep`
nói với **máy** ("đừng gửi request vào đây nữa"), còn màn "Hệ thống" nói với
**người** ("cái gì đang hỏng"), và một `503` ở đây chỉ làm màn hình chẩn đoán
tắt đúng lúc cần đọc nó nhất.
"""

from __future__ import annotations

import logging
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from ipaddress import IPv4Address, IPv6Address
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from app.config import catalog
from app.config.settings import settings
from app.config.version import APP_VERSION
from app.core.blacklist import dat_moc_user, thu_hoi_moi_phien
from app.core.deps import get_current_user_id
from app.core.errors import ApiError, ApiErrorCode, ErrorEnvelope
from app.core.health_checks import CachedChecks, CheckResult, run_checks
from app.core.queue import queue_depth
from app.core.ratelimit import dia_chi_ip
from app.core.redis import get_redis
from app.db.models import (
    TARGET_CATALOG,
    TARGET_TIER,
    TARGET_USER,
    AuditAction,
    CostConfidence,
    KeySource,
    User,
    UserRole,
    UserStatus,
)
from app.db.repositories import (
    AuditLogRepository,
    MessageRepository,
    UsageBucket,
    UsageEventRepository,
)
from app.db.repositories.tiers import TierRepository
from app.db.repositories.users import AdminUserRow, UserRepository
from app.db.session import session_scope
from app.quota.tiers import OVERRIDABLE_FIELDS, EffectiveLimits

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ════════════════════ §11.1 nhìn từ phía admin (ba nút bấm) ═════════════════


@dataclass(frozen=True, slots=True)
class PhepChuyen:
    """Một nút bấm của màn "Duyệt user": đích đến + tập nguồn đi tới được."""

    action: AuditAction
    sang: UserStatus
    tu: frozenset[UserStatus]


#: Ba mũi tên của sơ đồ §11.1 cộng hai đường ra khỏi trạng thái cuối — xem
#: docstring module cho lý do của từng dòng.
_PHEP_CHUYEN: dict[str, PhepChuyen] = {
    "approve": PhepChuyen(
        action=AuditAction.USER_APPROVE,
        sang=UserStatus.ACTIVE,
        tu=frozenset({UserStatus.PENDING_APPROVAL, UserStatus.REJECTED, UserStatus.SUSPENDED}),
    ),
    "reject": PhepChuyen(
        action=AuditAction.USER_REJECT,
        sang=UserStatus.REJECTED,
        tu=frozenset({UserStatus.PENDING_APPROVAL}),
    ),
    "suspend": PhepChuyen(
        action=AuditAction.USER_SUSPEND,
        sang=UserStatus.SUSPENDED,
        tu=frozenset({UserStatus.ACTIVE}),
    ),
}


# ══════════════════════════════ hình dạng ra vào ════════════════════════════


class AdminUserOut(BaseModel):
    """Một hàng của bảng "Người dùng" (§16.3).

    **Không** có `password_hash`, và không có gì suy ra được nó (§20). `email`
    thì có: đây là màn hình mà §16.3 nói phải hiện *"email + thời điểm đăng
    ký"* để admin biết mình đang duyệt ai.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str | None
    status: UserStatus
    role: UserRole
    tier_name: str
    #: §10.4 — ghi đè từng trường cho một user cụ thể. `None` = không có.
    limit_override_json: dict[str, Any] | None
    email_verified_at: datetime | None
    approved_at: datetime | None
    approved_by: uuid.UUID | None
    last_login_at: datetime | None
    created_at: datetime


class AdminUserRowOut(AdminUserOut):
    """Một hàng của `GET /admin/users` — `AdminUserOut` + hai cột NQ-66.

    Tách lớp chứ không thêm hai trường vào `AdminUserOut`: ba endpoint đổi
    trạng thái/`PATCH` trả về **một** hàng vừa đổi, và hai con số này là kết
    quả của một câu gom nhóm mà các endpoint ấy không có lý do để chạy. Cho
    chúng hai trường tuỳ chọn là để FE đọc được `null` ở một chỗ và `0` ở chỗ
    khác cho cùng một câu hỏi.
    """

    #: Số hội thoại chưa xoá mềm. `0` khi chưa có — **không** `null` (DoD).
    conversation_count: int
    #: Tiền HỆ THỐNG (`key_source='system'`) trong cửa sổ quota dài
    #: (`QUOTA_WINDOW_LONG_S`) — đúng tập mà quota 7 ngày của người ấy cộng.
    #: Chuỗi sáu chữ số thập phân từ `NUMERIC(12,6)`, như mọi `cost_usd`.
    spend_7d_usd: Decimal

    @classmethod
    def from_row(cls, row: AdminUserRow) -> AdminUserRowOut:
        base = AdminUserOut.model_validate(row.user).model_dump()
        return cls(
            **base,
            conversation_count=row.conversation_count,
            spend_7d_usd=row.spend_7d_usd,
        )


class AdminUserListOut(BaseModel):
    users: list[AdminUserRowOut]


class SuaUserRequest(BaseModel):
    """Body của `PATCH /admin/users/{id}` — §16.3, §10.4.

    **Hai trường, không ba.** §16.3 liệt kê ba hành động (*"đổi tier, override
    hạn mức, bật `can_execute_skills`"*) nhưng `can_execute_skills` là một
    **trường của** `limit_override` (`OVERRIDABLE_FIELDS` sinh ra từ
    `EffectiveLimits`, xem `app/quota/tiers.py`), nên nó đã nằm trong trường
    thứ hai. Cho nó một ô riêng nghĩa là hai đường ghi vào cùng một cột JSONB
    — và ngày chúng nói khác nhau trong một request thì không ai trả lời được
    đường nào thắng.

    `extra="forbid"`: gõ nhầm `tier` thay vì `tier_name` phải là một `422` đọc
    được, không phải một `PATCH` thành công mà không đổi gì.
    """

    model_config = ConfigDict(extra="forbid")

    tier_name: str | None = None
    limit_override: dict[str, Any] | None = None


class UsageAmount(BaseModel):
    """Bốn con số của một ô trong bảng chi phí."""

    cost_usd: Decimal
    prompt_tokens: int
    completion_tokens: int
    events: int


class HaiCot(BaseModel):
    """**Hai cột tách riêng** của C16 — không bao giờ có trường `tong`.

    C16: *"bảng chi phí không khớp hoá đơn provider vì trộn chung model
    `metered` và `unmetered` vào một con số"*. Một trường `tong` ở đây chính là
    con số đó, và nó sẽ được dùng vì nó tiện. Muốn cộng thì tầng hiển thị tự
    cộng, và khi ấy người viết ra phép cộng biết mình đang cộng cái gì.
    """

    metered: UsageAmount
    unmetered: UsageAmount


class UsageRow(HaiCot):
    """Một hàng của bảng chi phí: một khoá × hai cột."""

    key: str
    #: Nhãn đọc được của khoá (email, ở bảng theo user); `None` ở ba trục kia.
    label: str | None = None


class AdminUsageOut(BaseModel):
    """`GET /admin/usage` — §16.3 ("biểu đồ theo ngày; bảng theo user và model").

    Trục thứ tư (`by_key_source`) không có trong §16.3; xem
    `UsageEventRepository.admin_by_key_source` cho lý do nó tồn tại.
    """

    since: datetime
    until: datetime
    #: Bộ lọc §10.5 đang áp cho `totals`/`by_day`/`by_user`/`by_model`.
    #: `None` = mọi nguồn. **`by_key_source` không bao giờ bị lọc** — xem
    #: `admin_usage` và `UsageEventRepository.admin_by_key_source`.
    key_source: KeySource | None
    totals: HaiCot
    by_day: list[UsageRow]
    by_user: list[UsageRow]
    by_model: list[UsageRow]
    by_key_source: list[UsageRow]


class ReloadCatalogOut(BaseModel):
    models: int
    version: int


# ────────────────────────── T-2.20 · §10.4 hàng `tiers` ─────────────────────


class TierOut(BaseModel):
    """Một hàng của bảng "hạn mức" — `GET /admin/tiers`.

    Chín cột của §10.4, đủ cả `is_default` dù `PATCH` không cho sửa nó: **đọc
    được mà không sửa được** là đúng hình dạng của một cột mà B-152 còn để ngỏ
    — người vận hành cần nhìn thấy nó đang bật ở đâu để hiểu B-152 nói về cái
    gì, nhưng chưa ai chốt bật nó có nghĩa gì.
    """

    model_config = ConfigDict(from_attributes=True)

    name: str
    limit_5h_usd: Decimal
    limit_7d_usd: Decimal
    can_execute_skills: bool
    can_use_web: bool
    web_searches_per_day: int
    max_upload_mb: int
    max_attachments: int
    allowed_model_tags: list[str]
    is_default: bool


class AdminTierListOut(BaseModel):
    tiers: list[TierOut]
    #: `TIER_CACHE_TTL_S` — sau khi đổi tier / hạn mức / ghi đè, thay đổi có
    #: hiệu lực trong **tối đa** ngần này giây (§10.4, NQ-51: không gỡ cache).
    #: Đi ra đây để màn hình nói đúng con số của `.env` thay vì chép tay `60`
    #: vào `vi.json` (A3, cùng lý lẽ `message_max_chars` của T-3.0).
    limits_cache_ttl_s: int


class UpdateTierRequest(BaseModel):
    """Body của `PATCH /admin/tiers/{name}` — §10.4, §16.3.

    **Tám trường, và chúng KHÔNG được chép tay ra đây một cách tuỳ hứng:** đó
    đúng là `OVERRIDABLE_FIELDS` của `app/quota/tiers.py`, tức tập trường mà
    `users.limit_override_json` đè được lên một tier. Hai tập ấy bằng nhau
    không phải tình cờ — cả hai đều là "những gì tạo nên hạn mức của một
    người", chỉ khác phạm vi (một tier với một người). `tests/api/test_admin.py`
    khẳng định đẳng thức đó, nên ngày `EffectiveLimits` mọc thêm một trường mà
    ở đây quên là một test đỏ, không phải một ô nhập biến mất trong im lặng.

    **`name` không có mặt**: nó nằm trong đường dẫn, và nó là khoá chính mà
    `users.tier_name` tham chiếu tới — đổi tên một tier là một cuộc di trú dữ
    liệu, không phải một `PATCH`.

    **`is_default` cũng không có mặt**, và đó là B-152 chứ không phải một lần
    quên: hôm nay **không code nào ĐỌC** cột ấy — tier của một người mới đến từ
    `users.tier_name DEFAULT 'free'` trong DDL. Cho admin bật nó nghĩa là cho
    họ một công tắc không nối với gì, thứ tệ hơn cả việc không có công tắc.

    `extra="forbid"`: gõ `limit_5h` thay vì `limit_5h_usd` phải là một `422`
    đọc được, không phải một `PATCH` thành công mà không đổi gì.

    `ge=0` trên sáu trường số: một hạn mức âm không có nghĩa nào trong §10.4, và
    một `limit_5h_usd = -1` sẽ khoá sạch tier ấy khỏi app mà không ai đọc ra lý
    do từ màn hình quota.
    """

    model_config = ConfigDict(extra="forbid")

    limit_5h_usd: Decimal | None = Field(default=None, ge=0)
    limit_7d_usd: Decimal | None = Field(default=None, ge=0)
    can_execute_skills: bool | None = None
    can_use_web: bool | None = None
    web_searches_per_day: int | None = Field(default=None, ge=0)
    max_upload_mb: int | None = Field(default=None, ge=0)
    max_attachments: int | None = Field(default=None, ge=0)
    allowed_model_tags: list[str] | None = None


# ───────────────────────── T-2.20 · §16.3 màn "Hệ thống" ────────────────────


class AdminSystemOut(BaseModel):
    """Bốn ô của màn "Hệ thống" (§16.3) — ba chỉ số §21.2 cộng số phiên bản.

    **Ba `null` có thể xảy ra, và mỗi cái nói một chuyện khác nhau.** Xem
    docstring module cho lý do endpoint này không bao giờ trả `503`; ở đây chỉ
    nhắc phần đọc kết quả: một ô `null` nghĩa là *không hỏi được nguồn ấy*, và
    `health` nói nguồn nào đang hỏng.
    """

    #: Đọc từ `pyproject.toml`, chỗ duy nhất con số ấy sống (A3) — xem
    #: `app/config/version.py` cho lý do không phải `importlib.metadata`.
    version: str
    #: `ZCARD arq:queue` — §21.2 *"độ dài hàng đợi arq"*. `None` = Redis không
    #: trả lời.
    queue_depth: int | None
    #: Số message `status='streaming'` ngay lúc này. `None` = Postgres không
    #: trả lời.
    #:
    #: Tên trường là tiếng Việt không dấu **chỉ ở đây**, và có lý do: DoD của
    #: T-2.20 gọi đích danh bốn khoá JSON mà endpoint này phải trả, nên đổi nó
    #: thành `active_streams` là làm chính dòng DoD ấy không chạy được nguyên
    #: văn. Mọi định danh Python mới của task này đều tiếng Anh (B-142 vẫn mở
    #: cho code cũ).
    streams_dang_chay: int | None
    #: Năm mục của `GET /health/deep` (§18.6) — cùng một `run_checks()`, nên
    #: hai màn hình không bao giờ nói hai chuyện khác nhau về cùng hạ tầng.
    health: dict[str, CheckResult]
    #: Lúc `health` được ĐO (B-192) — có thể cũ tới `ADMIN_HEALTH_CACHE_TTL_S`
    #: giây. Màn hình in mốc này ra ("Kiểm lúc …"); `queue_depth` và
    #: `streams_dang_chay` thì luôn đọc tươi, chúng rẻ.
    health_checked_at: datetime


# ────────────────────── T-2.20 · §16.3 màn "Audit log" ──────────────────────


class AuditLogOut(BaseModel):
    """Một dòng sổ — bốn câu của §16.3: *"ai, lúc nào, làm gì, với ai"*.

    `actor_email` là phần **"ai"** đọc được, và nó đến từ một câu JOIN trong
    repository chứ không từ một vòng lặp tra từng `actor_id` ở tầng này —
    NQ-66 đã chốt đúng hình dạng ấy cho bảng Người dùng, và một trang 50 dòng
    không được biến thành 51 lượt đi Postgres.

    Phần **"với ai"** (B-191, chốt ở T-3.12): `target_email` +
    `target_display_name` từ một `LEFT JOIN users` **chỉ** cho `target_type =
    'users'` — nhánh duy nhất mà `target_id` không tự đọc được (tier đã là một
    cái tên, catalog không có id). Ngả "FE tra `GET /admin/users` rồi ghép" bị
    loại vì cùng lý do NQ-66 loại nó cho bảng Người dùng: hai response ghép ở
    FE là hai thời điểm đọc, và người đã xoá tài khoản sẽ không có trong danh
    sách ấy để mà ghép. Cả hai trường là `null` khi người ấy đã xoá — màn hình
    khi ấy chỉ còn 8 ký tự đầu của `target_id` (T-HD7).
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    actor_id: uuid.UUID | None
    #: `None` khi hành động không có người (cron) **hoặc** khi tài khoản ấy đã
    #: bị xoá — `ON DELETE SET NULL` giữ dòng sổ, bỏ con trỏ về người.
    actor_email: str | None
    actor_display_name: str | None
    action: AuditAction
    target_type: str | None
    target_id: str | None
    target_email: str | None
    target_display_name: str | None
    details: dict[str, Any] | None
    ip: IPv4Address | IPv6Address | None


class AuditLogListOut(BaseModel):
    """`GET /admin/audit-logs` — một trang, kèm con trỏ sang trang kế."""

    items: list[AuditLogOut]
    #: `id` của dòng cuối trang này; gửi lại vào `?before_id=` để lấy trang kế.
    #: `null` = hết. Cùng hợp đồng với `next_cursor` của `GET /conversations`,
    #: khác kiểu vì khác cột — xem `AuditLogRepository.list_page` cho lý do con
    #: trỏ ở đây là `id` chứ không phải `created_at`.
    next_cursor: int | None


# ═══════════════════════════════ phần dùng chung ════════════════════════════

_KHONG = UsageAmount(cost_usd=Decimal(0), prompt_tokens=0, completion_tokens=0, events=0)

#: B-192 — một lượt `run_checks()` dùng lại trong `ADMIN_HEALTH_CACHE_TTL_S`
#: giây cho màn "Hệ thống". Xem `CachedChecks` cho lý do nhớ ở server.
_system_health = CachedChecks()


def _gop(buckets: list[UsageBucket]) -> list[UsageRow]:
    """Hai dòng SQL của cùng một khoá (một `exact`, một `low`) → một hàng hai cột.

    `OrderedDict` giữ nguyên thứ tự Postgres đã sắp (`ORDER BY` của
    `_tong_hop`), nên biểu đồ theo ngày ra đúng thứ tự ngày mà không cần sắp
    lại lần thứ hai ở FE.
    """
    hang: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for b in buckets:
        vao = hang.setdefault(
            b.key,
            {"key": b.key, "label": b.label, "metered": _KHONG, "unmetered": _KHONG},
        )
        if b.label is not None:
            vao["label"] = b.label
        cot = "metered" if b.confidence is CostConfidence.EXACT else "unmetered"
        vao[cot] = UsageAmount(
            cost_usd=b.cost_usd,
            prompt_tokens=b.prompt_tokens,
            completion_tokens=b.completion_tokens,
            events=b.events,
        )
    return [UsageRow(**v) for v in hang.values()]


def _tong(rows: list[UsageRow]) -> HaiCot:
    """Tổng của một trục. Cộng **trong từng cột**, không bao giờ qua cột kia."""

    def cong(lay: str) -> UsageAmount:
        phan = [getattr(r, lay) for r in rows]
        return UsageAmount(
            cost_usd=sum((p.cost_usd for p in phan), Decimal(0)),
            prompt_tokens=sum(p.prompt_tokens for p in phan),
            completion_tokens=sum(p.completion_tokens for p in phan),
            events=sum(p.events for p in phan),
        )

    return HaiCot(metered=cong("metered"), unmetered=cong("unmetered"))


async def _lay_user(users: UserRepository, user_id: uuid.UUID) -> User:
    """Hàng `users` của `{id}` trong đường dẫn, hoặc `404 USER_NOT_FOUND`."""
    user = await users.get_by_id(user_id)
    if user is None:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            ApiErrorCode.USER_NOT_FOUND,
            "khong tim thay tai khoan nay",
            details={"user_id": str(user_id)},
        )
    return user


def _kiem_ghi_de(ghi_de: dict[str, Any]) -> None:
    """`limit_override` có đúng khoá và đúng kiểu không — xem `update_user`.

    Raises:
        ApiError 400 `BAD_REQUEST`: khoá không ghi đè được, hoặc giá trị sai
            kiểu so với trường cùng tên của `EffectiveLimits`.
    """
    la = sorted(set(ghi_de) - OVERRIDABLE_FIELDS)
    if la:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            ApiErrorCode.BAD_REQUEST,
            "limit_override co khoa khong ghi de duoc",
            details={"unknown": la, "allowed": sorted(OVERRIDABLE_FIELDS)},
        )
    for ten, gia_tri in ghi_de.items():
        try:
            TypeAdapter(EffectiveLimits.model_fields[ten].annotation).validate_python(gia_tri)
        except ValidationError as loi:
            raise ApiError(
                status.HTTP_400_BAD_REQUEST,
                ApiErrorCode.BAD_REQUEST,
                "limit_override co gia tri sai kieu",
                details={"field": ten},
            ) from loi


def _json_safe(value: Any) -> Any:
    """Giá trị đi vào cột `details` (JSONB) của một dòng audit.

    `Decimal` **phải** đổi sang chuỗi: bộ mã hoá JSON không biết kiểu ấy, nên
    một dòng sổ mang `limit_5h_usd` sẽ ném `TypeError` — và vì audit ghi trong
    cùng transaction với thay đổi nó mô tả (xem docstring module), lỗi ấy kéo
    theo cả cú `PATCH`. Chuỗi chứ không `float`: đây là tiền, và một sổ ghi
    `0.5000000000000001` là một sổ vô dụng đúng lúc cần đối chiếu. Cùng luật
    `cost_usd` đi từ Postgres tới FE — chuỗi suốt đường, đổi kiểu đúng một lần
    ở chỗ hiển thị.
    """
    return str(value) if isinstance(value, Decimal) else value


# ═══════════════════════════════ endpoint ═══════════════════════════════════


@router.get("/users", status_code=status.HTTP_200_OK, response_model=AdminUserListOut)
async def list_users(
    trang_thai: Annotated[UserStatus | None, Query(alias="status")] = None,
) -> AdminUserListOut:
    """Danh sách tài khoản, lọc theo trạng thái — §16.3 màn "Duyệt user".

    `?status=pending_approval` là chính màn hình đó; không có tham số thì trả
    cả bảng "Người dùng". Lọc **trong câu SQL** (xem
    `UserRepository.list_for_admin`), không đọc cả bảng rồi sàng ở Python.

    Giá trị lạ (`?status=abc`) ra `422` từ chính `UserStatus` chứ không phải
    một danh sách rỗng im lặng: một bộ lọc gõ sai mà trả `[]` sẽ đọc y hệt
    "không còn ai chờ duyệt".

    Hai cột NQ-66 (`conversation_count`, `spend_7d_usd`) đi trong **cùng**
    câu `SELECT` — xem `UserRepository.list_for_admin`. Cửa sổ chi tiêu là
    `QUOTA_WINDOW_LONG_S`, cùng con số của quota 7 ngày (A3).
    """
    spend_since = datetime.now(UTC) - timedelta(seconds=settings.QUOTA_WINDOW_LONG_S)
    async with session_scope() as session:
        hang = await UserRepository(session).list_for_admin(
            spend_since=spend_since, trang_thai=trang_thai
        )
        return AdminUserListOut(users=[AdminUserRowOut.from_row(h) for h in hang])


@router.post(
    "/users/{user_id}/{hanh_dong}",
    status_code=status.HTTP_200_OK,
    response_model=AdminUserOut,
    responses={
        404: {"model": ErrorEnvelope, "description": "khong co tai khoan (USER_NOT_FOUND)"},
        409: {
            "model": ErrorEnvelope,
            "description": "§11.1 khong co mui ten nay (INVALID_STATUS_TRANSITION)",
        },
    },
)
async def change_user_status(
    request: Request,
    actor_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    user_id: Annotated[uuid.UUID, Path()],
    hanh_dong: Annotated[str, Path(pattern="^(approve|reject|suspend)$")],
) -> AdminUserOut:
    """`approve` · `reject` · `suspend` — ba nút bấm của §16.3, một thân hàm.

    **Một route cho ba đường dẫn, không phải ba route chép ba lần.** §18.5 liệt
    kê chúng như ba endpoint và chúng *là* ba endpoint với người gọi (ba đường
    dẫn, ba nút trên màn hình); thứ dùng chung là phần thân, vì ba nút chỉ khác
    nhau đúng một dòng trong `_PHEP_CHUYEN`. Chép thân này ba lần là chép luôn
    ba thứ không ai sẽ nhớ đồng bộ: thứ tự "đổi trạng thái → ghi sổ → thu hồi
    phiên → commit", nhánh no-op không ghi sổ, và phép kiểm `409`.

    `pattern` trong `Path` là thứ giữ cho đường dẫn không mọc thêm nhánh: một
    `POST /admin/users/{id}/delete` dừng ở tầng validate (`422`) chứ không đi
    tới `_PHEP_CHUYEN[...]` để thành một `KeyError`, tức một `500` trả về cho
    người vừa bấm nút.

    Raises:
        ApiError 404 `USER_NOT_FOUND`: id không có hàng nào (hoặc đã xoá mềm).
        ApiError 409 `INVALID_STATUS_TRANSITION`: §11.1 không có mũi tên từ
            trạng thái hiện tại tới đích — hoặc có ai đó vừa đổi nó xong
            (`WHERE status = :tu` của `set_status` trượt).
    """
    phep = _PHEP_CHUYEN[hanh_dong]
    redis = get_redis()

    async with session_scope() as session:
        users = UserRepository(session)
        user = await _lay_user(users, user_id)
        truoc = user.status

        # Đích đã đạt ⇒ không có việc gì xảy ra, nên không có dòng sổ nào.
        if truoc is phep.sang:
            return AdminUserOut.model_validate(user)

        if truoc not in phep.tu:
            raise ApiError(
                status.HTTP_409_CONFLICT,
                ApiErrorCode.INVALID_STATUS_TRANSITION,
                "trang thai hien tai khong di toi trang thai dich duoc",
                details={
                    "status": truoc.value,
                    "target_status": phep.sang.value,
                    "allowed_from": sorted(s.value for s in phep.tu),
                },
            )

        moi = await users.set_status(
            user_id,
            tu=truoc,
            sang=phep.sang,
            approved_by=actor_id if phep.sang is UserStatus.ACTIVE else None,
        )
        if moi is None:
            # `WHERE status = :tu` trượt: một admin khác vừa đổi trạng thái
            # giữa lúc đọc và lúc ghi. Cùng mã lỗi vì với người bấm thì đó là
            # cùng một câu chuyện — "màn hình của bạn đã cũ, tải lại đi".
            raise ApiError(
                status.HTTP_409_CONFLICT,
                ApiErrorCode.INVALID_STATUS_TRANSITION,
                "trang thai vua bi nguoi khac doi, hay tai lai danh sach",
                details={"status": truoc.value, "target_status": phep.sang.value},
            )

        await AuditLogRepository(session).record(
            actor_id=actor_id,
            action=phep.action,
            target_type=TARGET_USER,
            target_id=str(user_id),
            details={"from": truoc.value, "to": phep.sang.value},
            ip=dia_chi_ip(request),
        )

        if phep.sang is UserStatus.SUSPENDED:
            # §11.3: "Admin suspend → như đổi mật khẩu" — CẢ HAI nửa.
            await thu_hoi_moi_phien(session, redis, user_id)
        elif phep.sang is UserStatus.ACTIVE:
            # B-141/NQ-61: chỉ nửa Redis — xem docstring module.
            await dat_moc_user(redis, user_id)

        await session.commit()
        return AdminUserOut.model_validate(moi)


@router.patch(
    "/users/{user_id}",
    status_code=status.HTTP_200_OK,
    response_model=AdminUserOut,
    responses={
        400: {
            "model": ErrorEnvelope,
            "description": "tier la, hoac limit_override sai khoa/sai kieu (BAD_REQUEST)",
        },
        404: {"model": ErrorEnvelope, "description": "khong co tai khoan (USER_NOT_FOUND)"},
    },
)
async def update_user(
    request: Request,
    body: SuaUserRequest,
    actor_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    user_id: Annotated[uuid.UUID, Path()],
) -> AdminUserOut:
    """Đổi tier và bản ghi đè hạn mức của một người — §10.4, §16.3.

    **Vắng mặt khác `null`**, đọc bằng `model_fields_set` — cùng luật với
    `PATCH /conversations/{id}` (T-1.13). Không gửi `limit_override` là "đừng
    đụng tới nó"; gửi `limit_override: null` là "xoá hết ghi đè, quay về đúng
    hạn mức của tier". `tier_name: null` thì **không** có nghĩa nào (cột `NOT
    NULL`) nên nó là `400` chứ không phải một lần bỏ qua im lặng.

    **Bản ghi đè được kiểm KIỂU ngay ở đây, không đợi lúc đọc.**
    `quota/tiers.py::merge_override` cố ý rộng lượng — khoá lạ thì bỏ qua,
    kiểu hỏng thì rơi cả bản ghi đè về hạn mức của tier — vì nó chạy giữa một
    lượt chat và không có ai để hỏi. Nhưng ở **đây** thì có: admin đang nhìn
    màn hình, và một `PATCH` trả `200` rồi âm thầm không có tác dụng gì là
    đúng thứ "lệch trong im lặng" tệ nhất. Danh sách khoá hợp lệ suy ra từ
    `OVERRIDABLE_FIELDS`, kiểu suy ra từ chính annotation của `EffectiveLimits`
    (A3: không chép lại chín trường ở đây để rồi lệch).

    **Không gỡ cache tier.** §10.4 hứa "≤ 60 s", và `quota/tiers.py` cố ý
    không có `invalidate()` — TTL là luật duy nhất, và nó chạy kể cả khi không
    ai nhớ tới nó.

    **Gửi lại đúng giá trị đang có thì không ghi sổ**, cùng luật với nhánh
    "đích đã đạt" của `change_user_status`: một màn hình admin lưu cả form sẽ
    gửi cả những ô không ai chạm tới, và mỗi lần bấm Lưu không được đẻ ra một
    dòng audit `{"from": "trusted", "to": "trusted"}`.

    Raises:
        ApiError 400 `BAD_REQUEST`: `tier_name` là `null`, tên tier không có
            trong bảng `tiers`, hoặc `limit_override` sai khoá/sai kiểu.
        ApiError 404 `USER_NOT_FOUND`: id không có hàng nào.
    """
    thay_doi: dict[str, Any] = {}
    dat = body.model_fields_set

    if "tier_name" in dat:
        if body.tier_name is None:
            raise ApiError(
                status.HTTP_400_BAD_REQUEST,
                ApiErrorCode.BAD_REQUEST,
                "tier_name khong nhan null; gui ten mot tier co that",
            )
        thay_doi["tier_name"] = body.tier_name

    if "limit_override" in dat:
        if body.limit_override is not None:
            _kiem_ghi_de(body.limit_override)
        thay_doi["limit_override_json"] = body.limit_override

    async with session_scope() as session:
        users = UserRepository(session)
        user = await _lay_user(users, user_id)

        ten_tier = thay_doi.get("tier_name")
        if ten_tier is not None and await TierRepository(session).get(ten_tier) is None:
            raise ApiError(
                status.HTTP_400_BAD_REQUEST,
                ApiErrorCode.BAD_REQUEST,
                "tier khong co trong bang tiers",
                details={"tier_name": ten_tier},
            )

        truoc = {ten: getattr(user, ten) for ten in thay_doi}
        # Chỉ giữ những trường THỰC SỰ đổi — cùng luật "không đổi gì thì không
        # ghi sổ" mà `change_user_status` áp cho nhánh no-op ở trên. Gửi lại
        # đúng giá trị đang có (màn hình admin lưu cả form) không được phép để
        # lại một dòng `{"from": "trusted", "to": "trusted"}`, thứ làm sổ dài ra
        # mà không nói thêm điều gì.
        thay_doi = {ten: gia_tri for ten, gia_tri in thay_doi.items() if truoc[ten] != gia_tri}
        moi = await users.update_by_admin(user_id, thay_doi=thay_doi)
        if moi is None:  # pragma: no cover - `_lay_user` vừa đọc xong ở trên
            raise ApiError(
                status.HTTP_404_NOT_FOUND,
                ApiErrorCode.USER_NOT_FOUND,
                "khong tim thay tai khoan nay",
                details={"user_id": str(user_id)},
            )

        if thay_doi:
            await AuditLogRepository(session).record(
                actor_id=actor_id,
                action=AuditAction.USER_UPDATE,
                target_type=TARGET_USER,
                target_id=str(user_id),
                details={
                    "changed": {
                        ten: {"from": truoc[ten], "to": gia_tri}
                        for ten, gia_tri in thay_doi.items()
                    }
                },
                ip=dia_chi_ip(request),
            )
            await session.commit()
        return AdminUserOut.model_validate(moi)


@router.get("/usage", status_code=status.HTTP_200_OK, response_model=AdminUsageOut)
async def admin_usage(
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    key_source: Annotated[KeySource | None, Query()] = None,
) -> AdminUsageOut:
    """Bảng chi phí, **hai cột tách riêng** — §16.3, §18.5, C16.

    **Trục tách là `cost_confidence`, không phải `pricing_mode`.** Hai lý do,
    và cả hai đã được viết ra trước task này: §9.5 nói *"admin panel hiển thị
    tách riêng khỏi chi phí thật"* về đúng những dòng mang `cost_confidence =
    'low'`, và `db/models/usage_event.py` chốt lại *"tiêu chí S13 (đối chiếu
    với hoá đơn provider) chỉ áp cho những dòng `exact`"*. Tách theo
    `pricing_mode` sẽ để lọt vào cột `metered` cả những lượt mà model đúng là
    metered nhưng provider **không** báo token (C40) — tức những con số
    `tiktoken` đếm hộ, thứ không đối chiếu với hoá đơn nào được.

    Cửa sổ mặc định là `QUOTA_WINDOW_LONG_S` (7 ngày) — cùng con số mà §16.3
    dùng cho cột *"chi tiêu 7 ngày"* của bảng Người dùng, và nó đến từ cấu
    hình chứ không từ một hằng số gõ ở đây (A3).

    ╔══════════════════════════════════════════════════════════════════════╗
    ║  `key_source` — B-178, và nó KHÔNG áp cho cả bốn trục                ║
    ╚══════════════════════════════════════════════════════════════════════╝

    B-178 ghi lại rằng `totals` của T-2.16 là *"hoá đơn của người vận hành
    cộng thêm tiền của người khác"*: §10.5 nói rõ lượt BYOK không tiêu tiền
    của hệ thống, nhưng nó vẫn nằm trong cùng một tổng với lượt `system`. Từ
    T-2.19 màn "Chi phí" mặc định hỏi `?key_source=system`, tức con số lớn
    nhất trên màn hình là con số S13 đem đối chiếu với hoá đơn provider được.

    Bộ lọc áp cho **ba trục hoá đơn** (`by_day`, `by_user`, `by_model`) và do
    đó cho cả `totals` — nhưng **không** áp cho `by_key_source`, và đó là chủ
    ý chứ không phải sót. Một mặc định lọc mà không để lại dấu vết gì của phần
    bị loại ra chỉ đổi một kiểu nói dối này lấy một kiểu khác: hôm nay tổng
    phình lên vì cộng nhầm tiền người khác, ngày mai nó tụt xuống mà không ai
    biết là có một phần đã bị cắt. Giữ trục thứ tư đủ cả hai nguồn nghĩa là
    một response trả lời được **cả hai** câu hỏi cùng lúc: "hoá đơn của tôi
    bao nhiêu" và "phần không phải của tôi bao nhiêu".

    `key_source` là `KeySource`, không phải `str`: `?key_source=abc` ra `422`
    từ chính enum, cùng lối `?status=abc` của `list_users` ở trên — một bộ lọc
    gõ sai mà im lặng trả về "mọi nguồn" sẽ đọc y hệt một hoá đơn phình to.

    **Có trần độ dài cửa sổ** (B-175, chốt ở T-3.12):
    `ADMIN_USAGE_MAX_WINDOW_DAYS`. Số hàng của trục "theo ngày" tỉ lệ với số
    ngày, không bị R1 chặn như `GET /admin/users`. Trần chứ không phân trang:
    `totals` là tổng của CẢ cửa sổ, và một tổng không chia trang được — trang 2
    của một báo cáo tổng hợp là một câu hỏi không có nghĩa.

    Raises:
        ApiError 400 `BAD_REQUEST`: `since >= until`, hoặc cửa sổ dài quá trần.
    """
    bay_gio = datetime.now(UTC)
    tu = since or bay_gio - timedelta(seconds=settings.QUOTA_WINDOW_LONG_S)
    den = until or bay_gio
    if tu >= den:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            ApiErrorCode.BAD_REQUEST,
            "since phai truoc until",
            details={"since": tu.isoformat(), "until": den.isoformat()},
        )
    tran = timedelta(days=settings.ADMIN_USAGE_MAX_WINDOW_DAYS)
    if den - tu > tran:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            ApiErrorCode.BAD_REQUEST,
            "cua so dai qua tran ADMIN_USAGE_MAX_WINDOW_DAYS",
            details={
                "since": tu.isoformat(),
                "until": den.isoformat(),
                "max_days": settings.ADMIN_USAGE_MAX_WINDOW_DAYS,
            },
        )

    async with session_scope() as session:
        events = UsageEventRepository(session)
        theo_ngay = _gop(
            list(await events.admin_by_day(since=tu, until=den, key_source=key_source))
        )
        theo_user = _gop(
            list(await events.admin_by_user(since=tu, until=den, key_source=key_source))
        )
        theo_model = _gop(
            list(await events.admin_by_model(since=tu, until=den, key_source=key_source))
        )
        theo_nguon = _gop(list(await events.admin_by_key_source(since=tu, until=den)))

    return AdminUsageOut(
        since=tu,
        until=den,
        key_source=key_source,
        totals=_tong(theo_ngay),
        by_day=theo_ngay,
        by_user=theo_user,
        by_model=theo_model,
        by_key_source=theo_nguon,
    )


@router.post("/catalog/reload", status_code=status.HTTP_200_OK, response_model=ReloadCatalogOut)
async def reload_catalog(
    request: Request,
    actor_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
) -> ReloadCatalogOut:
    """Nạp lại `config/model_catalog.json` — S7, §9.2, §9.9.

    Có từ T-0.7, và tới đây mới có khoá: B-34 ghi lại *"bất kỳ ai gọi được
    cổng 8000 lúc dev đều reload được catalog"* và giao việc đóng nó cho task
    gắn `require_admin`. Không một dòng nào trong thân hàm đổi vì chuyện đó —
    cánh cửa nằm ở `include_router`.

    Nạp **trước** rồi mới ghi sổ: dòng audit mang số model của catalog **mới**,
    tức nó ghi lại kết quả thật chứ không ghi lại ý định. Một file JSON hỏng
    làm `catalog.reload()` ném lỗi và khi ấy không có dòng sổ nào — đúng, vì
    không có gì đã xảy ra.
    """
    cat = catalog.reload()
    async with session_scope() as session:
        await AuditLogRepository(session).record(
            actor_id=actor_id,
            action=AuditAction.CATALOG_RELOAD,
            target_type=TARGET_CATALOG,
            details={"models": len(cat.models), "version": cat.version},
            ip=dia_chi_ip(request),
        )
        await session.commit()
    return ReloadCatalogOut(models=len(cat.models), version=cat.version)


# ═════════════════════ T-2.20 — bốn endpoint còn lại của §18.5 ══════════════


@router.get("/tiers", status_code=status.HTTP_200_OK, response_model=AdminTierListOut)
async def list_tiers() -> AdminTierListOut:
    """Bảng hạn mức — §10.4, §18.5.

    Không phân trang và không có bộ lọc nào: xem `TierRepository.list_all` cho
    lý do bảng này không dài được. Đây cũng là nguồn của ô chọn tier trên màn
    "Người dùng" — `PATCH /admin/users/{id}` từ chối một `tier_name` không có
    trong bảng `tiers`, nên FE phải có chỗ hỏi bảng ấy gồm những gì thay vì gõ
    sẵn hai chuỗi `free`/`trusted` vào một `<select>` (A3).
    """
    async with session_scope() as session:
        rows = await TierRepository(session).list_all()
        return AdminTierListOut(
            tiers=[TierOut.model_validate(t) for t in rows],
            limits_cache_ttl_s=settings.TIER_CACHE_TTL_S,
        )


@router.patch(
    "/tiers/{name}",
    status_code=status.HTTP_200_OK,
    response_model=TierOut,
    responses={
        400: {"model": ErrorEnvelope, "description": "mot truong duoc gui la null (BAD_REQUEST)"},
        404: {"model": ErrorEnvelope, "description": "khong co tier ten nay (TIER_NOT_FOUND)"},
    },
)
async def update_tier(
    request: Request,
    body: UpdateTierRequest,
    actor_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    name: Annotated[str, Path()],
) -> TierOut:
    """Đổi hạn mức của **cả một tier** — §10.4, §16.3: nửa còn thiếu của lời hứa.

    §10.4 viết *"đổi hạn mức trong admin panel có hiệu lực ≤ 60 s"*. T-2.16 chỉ
    mở được nửa "cho một người" (`limit_override_json`); nửa này là "cho cả
    tier", tức thứ mà câu trên thật sự nói về.

    **Vắng mặt khác `null`**, đọc bằng `model_fields_set` — cùng luật
    `PATCH /admin/users/{id}` và `PATCH /conversations/{id}`. Không gửi một
    trường là "đừng đụng tới nó"; gửi `null` cho nó thì **không** có nghĩa nào
    (cả tám cột đều `NOT NULL` trong Phụ lục A) nên đó là `400`, không phải một
    lần bỏ qua im lặng. Muốn "xoá hạn mức riêng" thì đó là `limit_override` của
    một **user**, không phải một cột của tier.

    **Gửi lại đúng giá trị đang có thì không ghi sổ**, cùng luật với nhánh
    "đích đã đạt" của `change_user_status`: màn hình admin lưu cả form sẽ gửi
    cả những ô không ai chạm tới.

    **Không gỡ cache** — xem docstring module, phần "TTL 60 s là luật duy nhất".

    Raises:
        ApiError 400 `BAD_REQUEST`: một trường được gửi mang giá trị `null`.
        ApiError 404 `TIER_NOT_FOUND`: không có hàng `tiers` nào tên ấy.
    """
    provided = body.model_fields_set
    nulls = sorted(field for field in provided if getattr(body, field) is None)
    if nulls:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            ApiErrorCode.BAD_REQUEST,
            "cot cua tier khong nhan null",
            details={"fields": nulls},
        )
    changes: dict[str, Any] = {field: getattr(body, field) for field in provided}

    async with session_scope() as session:
        repo = TierRepository(session)
        current = await repo.get(name)
        if current is None:
            raise ApiError(
                status.HTTP_404_NOT_FOUND,
                ApiErrorCode.TIER_NOT_FOUND,
                "khong co tier ten nay",
                details={"name": name},
            )

        before = {field: getattr(current, field) for field in changes}
        # Chỉ giữ những trường THỰC SỰ đổi — cùng luật "không đổi gì thì không
        # ghi sổ" của `update_user` ngay trên.
        changes = {f: v for f, v in changes.items() if before[f] != v}
        updated = await repo.update(name, changes=changes)
        if updated is None:  # pragma: no cover - `get` vừa đọc xong ở trên
            raise ApiError(
                status.HTTP_404_NOT_FOUND,
                ApiErrorCode.TIER_NOT_FOUND,
                "khong co tier ten nay",
                details={"name": name},
            )

        if changes:
            await AuditLogRepository(session).record(
                actor_id=actor_id,
                action=AuditAction.TIER_UPDATE,
                target_type=TARGET_TIER,
                target_id=name,
                details={
                    "changed": {
                        field: {"from": _json_safe(before[field]), "to": _json_safe(value)}
                        for field, value in changes.items()
                    }
                },
                ip=dia_chi_ip(request),
            )
            await session.commit()
        return TierOut.model_validate(updated)


@router.get("/system", status_code=status.HTTP_200_OK, response_model=AdminSystemOut)
async def admin_system() -> AdminSystemOut:
    """Màn "Hệ thống" của §16.3 — ba chỉ số §21.2 cộng số phiên bản.

    Mỗi ô hỏi một nguồn và hỏng riêng; endpoint luôn `200`. Lý do đầy đủ nằm
    trong docstring module, phần "REDIS CHẾT LÀ MỘT CÂU TRẢ LỜI".

    `run_checks()` chạy năm mục kiểm **song song**, mỗi mục timeout riêng, nên
    thời gian trả lời bị chặn trên bởi một timeout chứ không phải tổng năm cái
    (`app/core/health_checks.py`). Dùng lại đúng hàm ấy chứ không viết một bộ
    kiểm thứ hai: hai màn hình nói hai chuyện khác nhau về cùng một hạ tầng là
    cách chắc nhất để không ai còn tin màn nào.

    B-192 (T-3.12): kết quả `run_checks()` được nhớ `ADMIN_HEALTH_CACHE_TTL_S`
    giây và trả kèm `health_checked_at`. `run_checks` được tra ở **lúc gọi**
    (tên toàn cục của module này), nên test thay được hàm đo như trước.
    """
    snapshot = await _system_health.get(run_checks, ttl_s=settings.ADMIN_HEALTH_CACHE_TTL_S)

    try:
        depth: int | None = await queue_depth()
    except Exception:
        logger.warning("khong doc duoc do dai hang doi arq — tra null, xem `health.redis`")
        depth = None

    try:
        async with session_scope() as session:
            streams: int | None = await MessageRepository(session).count_streaming()
    except Exception:
        logger.warning("khong dem duoc stream dang chay — tra null, xem `health.postgres`")
        streams = None

    return AdminSystemOut(
        version=APP_VERSION,
        queue_depth=depth,
        streams_dang_chay=streams,
        health=snapshot.checks,
        health_checked_at=snapshot.checked_at,
    )


@router.get(
    "/audit-logs",
    status_code=status.HTTP_200_OK,
    response_model=AuditLogListOut,
    responses={
        400: {"model": ErrorEnvelope, "description": "since >= until (BAD_REQUEST)"},
        422: {"model": ErrorEnvelope, "description": "limit ngoai khoang, hoac action la"},
    },
)
async def list_audit_logs(
    limit: Annotated[
        int,
        Query(ge=1, le=settings.AUDIT_LOG_PAGE_SIZE, description="so dong toi da"),
    ] = settings.AUDIT_LOG_PAGE_SIZE,
    before_id: Annotated[int | None, Query(description="next_cursor cua trang truoc")] = None,
    actor_id: Annotated[uuid.UUID | None, Query()] = None,
    action: Annotated[AuditAction | None, Query()] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
) -> AuditLogListOut:
    """Màn "Audit log" của §16.3 — *"ai, lúc nào, làm gì, với ai"*.

    T-2.16 đã **ghi** đủ dữ liệu từ lâu; tới đây mới có đường đọc nó mà không
    phải mở `psql`. Một sổ không ai đọc được thì không khác gì một sổ không ai
    ghi — chỉ là nó tốn thêm chỗ trên đĩa.

    **Cả bốn bộ lọc nằm trong câu SQL** (§20, CLAUDE.md), và điều đó đo được
    chứ không phải một lời hứa: lọc sau `LIMIT` ở tầng Python sẽ trả về **ít
    hơn** `limit` dòng khi những dòng mới nhất thuộc về một `action` khác —
    `tests/api/test_admin.py` nhắm đúng vào chiều đó.

    **Mới nhất trước**, con trỏ là `id` — xem `AuditLogRepository.list_page`
    cho lý do nó không phải `created_at`.

    `[since, until)` nửa mở, cùng quy ước `GET /admin/usage`: hai trang chia
    theo ngày không đếm hai lần dòng nằm đúng ở mốc giao.

    **Không ghi sổ.** Đọc không phải một hành động (§20 nói "mọi hành động
    admin"), và một sổ mà mỗi lần mở lại dài thêm một dòng "có người vừa mở sổ"
    là một sổ tự lấp chính nó.

    Raises:
        ApiError 400 `BAD_REQUEST`: `since >= until`.
    """
    if since is not None and until is not None and since >= until:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            ApiErrorCode.BAD_REQUEST,
            "since phai truoc until",
            details={"since": since.isoformat(), "until": until.isoformat()},
        )

    async with session_scope() as session:
        rows = await AuditLogRepository(session).list_page(
            limit=limit,
            before_id=before_id,
            actor_id=actor_id,
            action=action,
            since=since,
            until=until,
        )
        items = [
            AuditLogOut(
                id=row.log.id,
                created_at=row.log.created_at,
                actor_id=row.log.actor_id,
                actor_email=row.email,
                actor_display_name=row.actor_display_name,
                action=row.log.action,
                target_type=row.log.target_type,
                target_id=row.log.target_id,
                target_email=row.target_email,
                target_display_name=row.target_display_name,
                details=row.log.details,
                ip=row.log.ip,
            )
            for row in rows
        ]

    # Trang chưa đầy ⇒ chắc chắn hết dữ liệu — cùng lối `GET /conversations`.
    has_more = len(items) == limit
    return AuditLogListOut(
        items=items,
        next_cursor=items[-1].id if (items and has_more) else None,
    )
