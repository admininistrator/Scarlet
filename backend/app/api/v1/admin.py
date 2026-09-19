"""Admin panel — bảy endpoint của §18.5 mà T-2.16 sở hữu.

    GET    /api/v1/admin/users                   danh sách, lọc theo status
    POST   /api/v1/admin/users/{id}/approve      pending_approval → active
    POST   /api/v1/admin/users/{id}/reject       pending_approval → rejected
    POST   /api/v1/admin/users/{id}/suspend      active → suspended
    PATCH  /api/v1/admin/users/{id}              tier · ghi đè hạn mức
    GET    /api/v1/admin/usage                   chi phí, TÁCH metered/unmetered
    POST   /api/v1/admin/catalog/reload          nạp lại model_catalog.json

KH tham chiếu: §16.3, §18.5, §20, §11.1, §11.3, §10.4, §10.5, §9.5 · Cạm bẫy
C16 · CLAUDE.md A3, A7 · tasks.md T-2.16, B-34, B-141 (NQ-61).

Bốn endpoint còn lại của §18.5 (`GET/PATCH /admin/tiers`, `GET /admin/system`,
`GET /admin/audit-logs`) **chưa** có task nào — không dựng sẵn.

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
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request, status
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from app.config import catalog
from app.config.settings import settings
from app.core.blacklist import dat_moc_user, thu_hoi_moi_phien
from app.core.deps import get_current_user_id
from app.core.errors import ApiError, ApiErrorCode, ErrorEnvelope
from app.core.ratelimit import dia_chi_ip
from app.core.redis import get_redis
from app.db.models import (
    TARGET_CATALOG,
    TARGET_USER,
    AuditAction,
    CostConfidence,
    User,
    UserRole,
    UserStatus,
)
from app.db.repositories import AuditLogRepository, UsageBucket, UsageEventRepository
from app.db.repositories.tiers import TierRepository
from app.db.repositories.users import UserRepository
from app.db.session import session_scope
from app.quota.tiers import OVERRIDABLE_FIELDS, EffectiveLimits

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


class AdminUserListOut(BaseModel):
    users: list[AdminUserOut]


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
    totals: HaiCot
    by_day: list[UsageRow]
    by_user: list[UsageRow]
    by_model: list[UsageRow]
    by_key_source: list[UsageRow]


class ReloadCatalogOut(BaseModel):
    models: int
    version: int


# ═══════════════════════════════ phần dùng chung ════════════════════════════

_KHONG = UsageAmount(cost_usd=Decimal(0), prompt_tokens=0, completion_tokens=0, events=0)


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
    """
    async with session_scope() as session:
        hang = await UserRepository(session).list_for_admin(trang_thai=trang_thai)
        return AdminUserListOut(users=[AdminUserOut.model_validate(u) for u in hang])


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

    Raises:
        ApiError 400 `BAD_REQUEST`: `since >= until`.
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

    async with session_scope() as session:
        events = UsageEventRepository(session)
        theo_ngay = _gop(list(await events.admin_by_day(since=tu, until=den)))
        theo_user = _gop(list(await events.admin_by_user(since=tu, until=den)))
        theo_model = _gop(list(await events.admin_by_model(since=tu, until=den)))
        theo_nguon = _gop(list(await events.admin_by_key_source(since=tu, until=den)))

    return AdminUsageOut(
        since=tu,
        until=den,
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
