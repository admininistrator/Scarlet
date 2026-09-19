"""Admin API — hành vi của **mười một** endpoint §18.5 — T-2.16 và T-2.20.

Bảy endpoint đầu là T-2.16 (§16.3, §11.1, §11.3, C16); bốn endpoint cuối
(`GET/PATCH /admin/tiers`, `GET /admin/system`, `GET /admin/audit-logs`) là
T-2.20 và nằm ở nửa dưới file, sau một khung tiêu đề. Chúng đo thêm ba thứ mà
bảy cái đầu không có chỗ để đo: §10.4 nhìn từ phía *cả một tier* (và quyết định
**không gỡ cache** của NQ-51, đo từ hai phía cùng lúc), một màn hình chẩn đoán
phải sống sót qua chính sự cố mà người ta mở nó ra để xem, và đường **đọc** sổ
audit — thứ T-2.16 ghi đủ dữ liệu mà không có cách nào xem ngoài `psql`.

Phần **quyền** không nằm ở đây: nó có file riêng (`test_admin_authz.py`), vì
nó đọc bảng định tuyến chứ không đọc dữ liệu, và vì DoD gọi đích danh tên file
ấy. File này đo ba thứ còn lại:

* máy trạng thái của §11.1 nhìn từ phía admin — mỗi mũi tên một ca, mỗi mũi
  tên **không tồn tại** cũng một ca;
* sổ `audit_logs` — §20 nói "mọi hành động admin", nên mỗi hành động phải để
  lại **đúng một** dòng, và mỗi thao tác không đổi gì phải để lại **không**
  dòng nào;
* bảng chi phí — C16: hai cột không bao giờ được cộng vào nhau.

Hạ tầng giống `test_account_states.py`: Postgres thật (NQ-17), `session_scope()`
trỏ về đúng kết nối của test, Redis giả cho blacklist. Redis ở đây **ghi lại**
những gì bị `SET` thay vì chỉ trả `None` — B-141 và §11.3 là hai quyết định chỉ
đo được bằng cách nhìn vào đúng những khoá ấy.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from ipaddress import ip_address
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.v1.admin import UpdateTierRequest
from app.config.version import APP_VERSION
from app.core.access_token import encode_access_token
from app.core.blacklist import user_key
from app.core.deps import SESSION_COOKIE_NAME
from app.core.errors import ApiErrorCode
from app.core.health_checks import CheckResult
from app.db.models import (
    TARGET_TIER,
    TARGET_USER,
    AuditAction,
    AuditLog,
    Conversation,
    CostConfidence,
    KeySource,
    Message,
    MessageRole,
    MessageStatus,
    RefreshToken,
    User,
    UserRole,
    UserStatus,
)
from app.db.repositories import AuditLogRepository, UsageEventRepository
from app.db.repositories.refresh_tokens import RefreshTokenRepository
from app.db.repositories.tiers import TierRepository
from app.db.repositories.users import UserRepository
from app.main import app
from app.quota.tiers import OVERRIDABLE_FIELDS

DUONG_DAN_USERS = "/api/v1/admin/users"
DUONG_DAN_USER = "/api/v1/admin/users/{}"
DUONG_DAN_HANH_DONG = "/api/v1/admin/users/{}/{}"
DUONG_DAN_USAGE = "/api/v1/admin/usage"
DUONG_DAN_RELOAD = "/api/v1/admin/catalog/reload"
DUONG_DAN_TIERS = "/api/v1/admin/tiers"
DUONG_DAN_TIER = "/api/v1/admin/tiers/{}"
DUONG_DAN_SYSTEM = "/api/v1/admin/system"
DUONG_DAN_AUDIT = "/api/v1/admin/audit-logs"


# ═══════════════════════════ hạ tầng của bộ test ════════════════════════════


class _RedisGia:
    """Blacklist rỗng khi ĐỌC, có sổ khi GHI.

    `mget` luôn trả `None` nên không token nào của bộ test này bị coi là đã thu
    hồi — cùng lý do `test_account_states.py` làm vậy. `set` thì **giữ lại**,
    vì hai quyết định của task chỉ nhìn thấy được ở đó: `approve` phải đặt
    `bl:user:{uid}` (B-141/NQ-61) và `reject` phải **không** đặt gì.
    """

    def __init__(self) -> None:
        self.da_set: dict[str, str] = {}
        self.da_xoa: list[str] = []

    async def mget(self, keys: list[str]) -> list[str | None]:
        return [None for _ in keys]

    async def set(self, name: str, value: str, *, ex: int | None = None, **_: Any) -> bool:
        self.da_set[name] = value
        return True

    async def delete(self, *names: str) -> int:
        """Có mặt để ĐẾM, không phải để dùng (T-2.20, NQ-51).

        `PATCH /admin/tiers` cố ý **không** gỡ cache hạn mức — TTL 60 s là luật
        duy nhất. Một danh sách rỗng ở đây là cách duy nhất khẳng định điều đó
        từ phía Redis; không có phương thức này thì một lời gọi `delete` lén
        đưa vào sau sẽ nổ thành `AttributeError`, tức một `500` khó đọc thay vì
        một test đỏ nói đúng chuyện.
        """
        self.da_xoa.extend(names)
        return len(names)


@pytest.fixture(autouse=True)
def redis_gia(monkeypatch: pytest.MonkeyPatch) -> _RedisGia:
    gia = _RedisGia()
    monkeypatch.setattr("app.core.deps.get_redis", lambda: gia)
    monkeypatch.setattr("app.api.v1.admin.get_redis", lambda: gia)
    return gia


@pytest.fixture(autouse=True)
def _db_cua_test(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`session_scope()` trong handler trỏ vào ĐÚNG kết nối của test (NQ-17)."""
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


@pytest_asyncio.fixture
async def client(event_hooks: dict[str, Any]) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://localhost", event_hooks=event_hooks
    ) as http:
        yield http


async def _tao_user(
    session_factory: async_sessionmaker[AsyncSession],
    trang_thai: UserStatus = UserStatus.PENDING_APPROVAL,
    *,
    role: UserRole = UserRole.USER,
) -> uuid.UUID:
    """Một hàng `users` với `status`/`role` đặt sẵn.

    Không đi qua `POST /auth/register` vì mọi trạng thái ngoài `pending_email`
    đều không tới được bằng đường đó, và vì hash Argon2 thật tốn ~100 ms mỗi
    lần cho một thứ không ca nào ở đây đo.
    """
    async with session_factory() as session:
        user = await UserRepository(session).create_pending_user(
            email=f"{uuid.uuid4().hex}@scarlet.example",
            password_hash="khong-phai-hash-that",
        )
        assert user is not None
        await session.execute(
            update(User).where(User.id == user.id).values(status=trang_thai, role=role)
        )
        await session.commit()
        return user.id


async def _admin(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> uuid.UUID:
    """Một admin thật trong DB + cookie phiên mang `role=admin` cho `client`.

    Admin phải có hàng trong `users` chứ không chỉ một token: `audit_logs
    .actor_id` là khoá ngoại tới `users(id)`, nên một actor bịa ra sẽ làm mọi
    ca ghi sổ đỏ ở tầng Postgres — đúng chỗ nó phải đỏ.
    """
    admin_id = await _tao_user(session_factory, UserStatus.ACTIVE, role=UserRole.ADMIN)
    client.cookies.set(
        SESSION_COOKIE_NAME,
        encode_access_token(
            user_id=admin_id,
            role=UserRole.ADMIN,
            tier="free",
            status=UserStatus.ACTIVE,
            ttl_minutes=15,
        ),
    )
    return admin_id


async def _audit(session_factory: async_sessionmaker[AsyncSession]) -> list[AuditLog]:
    async with session_factory() as session:
        stmt = select(AuditLog).order_by(AuditLog.id)
        return list((await session.execute(stmt)).scalars())


async def _status_trong_db(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> UserStatus:
    async with session_factory() as session:
        return (await session.execute(select(User.status).where(User.id == user_id))).scalar_one()


# ════════════════ DoD dòng 2 — duyệt một user, ghi đúng một dòng ════════════


async def test_duyet_user_doi_status_va_ghi_mot_dong_audit(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """DoD dòng 2: *"Duyệt một user → `status='active'`, có 1 dòng `audit_logs`
    với `actor_id` đúng"*."""
    admin_id = await _admin(client, session_factory)
    user_id = await _tao_user(session_factory, UserStatus.PENDING_APPROVAL)

    resp = await client.post(DUONG_DAN_HANH_DONG.format(user_id, "approve"))

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == UserStatus.ACTIVE.value
    assert await _status_trong_db(session_factory, user_id) is UserStatus.ACTIVE

    dong = await _audit(session_factory)
    assert len(dong) == 1
    assert dong[0].actor_id == admin_id
    assert dong[0].action == AuditAction.USER_APPROVE
    assert dong[0].target_id == str(user_id)
    assert dong[0].details == {"from": UserStatus.PENDING_APPROVAL.value, "to": "active"}


async def test_duyet_ghi_approved_at_va_approved_by(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Hai cột của Phụ lục A trả lời *"ai đã nhận người này vào"* — chỉ nhánh duyệt."""
    admin_id = await _admin(client, session_factory)
    user_id = await _tao_user(session_factory, UserStatus.PENDING_APPROVAL)

    body = (await client.post(DUONG_DAN_HANH_DONG.format(user_id, "approve"))).json()

    assert body["approved_by"] == str(admin_id)
    assert body["approved_at"] is not None


async def test_tu_choi_khong_ghi_approved_by(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`reject` **không** đặt `approved_*` — hai cột ấy là "ai nhận vào", không
    phải "ai đã bấm nút"."""
    await _admin(client, session_factory)
    user_id = await _tao_user(session_factory, UserStatus.PENDING_APPROVAL)

    body = (await client.post(DUONG_DAN_HANH_DONG.format(user_id, "reject"))).json()

    assert body["status"] == UserStatus.REJECTED.value
    assert body["approved_by"] is None
    assert body["approved_at"] is None


async def test_duyet_lan_hai_khong_ghi_them_dong_nao(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Đích đã đạt ⇒ `200` và **không** có dòng sổ thứ hai (xem docstring `admin.py`)."""
    await _admin(client, session_factory)
    user_id = await _tao_user(session_factory, UserStatus.PENDING_APPROVAL)

    dau = await client.post(DUONG_DAN_HANH_DONG.format(user_id, "approve"))
    lai = await client.post(DUONG_DAN_HANH_DONG.format(user_id, "approve"))

    assert dau.status_code == 200
    assert lai.status_code == 200
    assert len(await _audit(session_factory)) == 1


# ══════════════════ §11.1 — mũi tên nào có, mũi tên nào không ═══════════════


@pytest.mark.parametrize(
    ("trang_thai_dau", "hanh_dong", "trang_thai_cuoi"),
    [
        (UserStatus.PENDING_APPROVAL, "approve", UserStatus.ACTIVE),
        (UserStatus.PENDING_APPROVAL, "reject", UserStatus.REJECTED),
        (UserStatus.ACTIVE, "suspend", UserStatus.SUSPENDED),
        # Hai đường ra khỏi trạng thái CUỐI — `core/deps.py` hứa "chỉ admin mới
        # đổi được", và đây là chỗ duy nhất trong app giữ được lời hứa đó.
        (UserStatus.REJECTED, "approve", UserStatus.ACTIVE),
        (UserStatus.SUSPENDED, "approve", UserStatus.ACTIVE),
    ],
)
async def test_mui_ten_co_that_thi_di_duoc(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    trang_thai_dau: UserStatus,
    hanh_dong: str,
    trang_thai_cuoi: UserStatus,
) -> None:
    await _admin(client, session_factory)
    user_id = await _tao_user(session_factory, trang_thai_dau)

    resp = await client.post(DUONG_DAN_HANH_DONG.format(user_id, hanh_dong))

    assert resp.status_code == 200, resp.text
    assert await _status_trong_db(session_factory, user_id) is trang_thai_cuoi


@pytest.mark.parametrize(
    ("trang_thai_dau", "hanh_dong"),
    [
        # `pending_email` không duyệt tắt được: §11.1 bắt đi qua link trong thư.
        (UserStatus.PENDING_EMAIL, "approve"),
        (UserStatus.PENDING_EMAIL, "reject"),
        (UserStatus.PENDING_EMAIL, "suspend"),
        # `reject` chỉ là câu trả lời cho một đơn đang chờ.
        (UserStatus.ACTIVE, "reject"),
        (UserStatus.SUSPENDED, "reject"),
        # `suspend` xuất phát từ `active`, không từ một đơn chưa duyệt.
        (UserStatus.PENDING_APPROVAL, "suspend"),
        (UserStatus.REJECTED, "suspend"),
    ],
)
async def test_mui_ten_khong_co_thi_409_va_khong_ghi_so(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    trang_thai_dau: UserStatus,
    hanh_dong: str,
) -> None:
    await _admin(client, session_factory)
    user_id = await _tao_user(session_factory, trang_thai_dau)

    resp = await client.post(DUONG_DAN_HANH_DONG.format(user_id, hanh_dong))

    assert resp.status_code == 409, resp.text
    loi = resp.json()["error"]
    assert loi["code"] == ApiErrorCode.INVALID_STATUS_TRANSITION
    assert loi["details"]["status"] == trang_thai_dau.value
    assert await _status_trong_db(session_factory, user_id) is trang_thai_dau
    assert await _audit(session_factory) == []


async def test_hanh_dong_la_thi_422_chu_khong_phai_500(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`pattern` của `Path` chặn TRƯỚC thân hàm, nên `_PHEP_CHUYEN[...]` không
    bao giờ nhận một khoá lạ.

    `422` chứ không `404`: đường dẫn vẫn khớp route (`{hanh_dong}` nhận mọi
    đoạn), thứ hỏng là **giá trị** của tham số — và FastAPI gọi đó là lỗi
    validate. Điều đáng giữ không phải con số mà là nó dừng ở đâu: một
    `KeyError` giữa thân hàm sẽ là `500`, tức một lỗi lập trình trả về cho
    người bấm nút.
    """
    await _admin(client, session_factory)
    user_id = await _tao_user(session_factory)

    resp = await client.post(DUONG_DAN_HANH_DONG.format(user_id, "delete"))

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == ApiErrorCode.VALIDATION_ERROR
    assert await _audit(session_factory) == []


async def test_user_khong_ton_tai_thi_404_user_not_found(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _admin(client, session_factory)

    resp = await client.post(DUONG_DAN_HANH_DONG.format(uuid.uuid4(), "approve"))

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == ApiErrorCode.USER_NOT_FOUND


# ═══════ B-141 (NQ-61) và §11.3 — ba nút bấm, ba cách xử lý phiên ═══════════


async def test_duyet_dat_moc_bl_user_nhung_giu_refresh_family(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    redis_gia: _RedisGia,
) -> None:
    """B-141/NQ-61: **nửa Redis** của §11.3, không phải cả hai nửa.

    Mốc `bl:user:` giết access token cũ (cửa sổ 15 phút đóng ngay), nhưng
    refresh family còn sống nên `/auth/refresh` đổi được ra một cookie phiên
    mang `status='active'` — người dùng không phải gõ lại mật khẩu cho một tin
    vui. Đây là phép kiểm ngược của chính quyết định ấy: nếu ai đó đổi sang
    `thu_hoi_moi_phien` thì `revoked_at` dưới đây thôi `None` và test đỏ.
    """
    await _admin(client, session_factory)
    user_id = await _tao_user(session_factory, UserStatus.PENDING_APPROVAL)
    async with session_factory() as session:
        await RefreshTokenRepository(session).issue_new_family(
            user_id=user_id, ttl_days=30, user_agent=None
        )
        await session.commit()

    await client.post(DUONG_DAN_HANH_DONG.format(user_id, "approve"))

    assert user_key(user_id) in redis_gia.da_set
    async with session_factory() as session:
        con_song = (
            await session.execute(
                select(func.count())
                .select_from(RefreshToken)
                .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            )
        ).scalar_one()
    assert con_song == 1, "duyet KHONG duoc thu hoi refresh family (B-141/NQ-61)"


async def test_suspend_thu_hoi_ca_hai_nua_nhu_doi_mat_khau(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    redis_gia: _RedisGia,
) -> None:
    """§11.3: *"Admin suspend → như đổi mật khẩu"* — mốc `bl:user:` **và**
    revoke mọi refresh family."""
    await _admin(client, session_factory)
    user_id = await _tao_user(session_factory, UserStatus.ACTIVE)
    async with session_factory() as session:
        await RefreshTokenRepository(session).issue_new_family(
            user_id=user_id, ttl_days=30, user_agent=None
        )
        await session.commit()

    await client.post(DUONG_DAN_HANH_DONG.format(user_id, "suspend"))

    assert user_key(user_id) in redis_gia.da_set
    async with session_factory() as session:
        con_song = (
            await session.execute(
                select(func.count())
                .select_from(RefreshToken)
                .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            )
        ).scalar_one()
    assert con_song == 0, "suspend PHAI thu hoi refresh family (§11.3)"


async def test_tu_choi_khong_thu_hoi_gi(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    redis_gia: _RedisGia,
) -> None:
    """§11.3 liệt đúng ba nhánh thu hồi và `rejected` không nằm trong đó (T-2.7).

    Không cần: mọi route trả `403 ACCOUNT_DISABLED` cho trạng thái ấy ngay từ
    claim, nên thu hồi thêm chỉ là một lượt ghi Redis không ai đọc.
    """
    await _admin(client, session_factory)
    user_id = await _tao_user(session_factory, UserStatus.PENDING_APPROVAL)

    await client.post(DUONG_DAN_HANH_DONG.format(user_id, "reject"))

    assert user_key(user_id) not in redis_gia.da_set


# ═══════════════════════ GET /admin/users — lọc theo status ═════════════════


async def test_loc_theo_status_chi_tra_dung_nhom(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Màn "Duyệt user" của §16.3 là đúng một tham số của endpoint này."""
    await _admin(client, session_factory)
    cho_duyet = await _tao_user(session_factory, UserStatus.PENDING_APPROVAL)
    await _tao_user(session_factory, UserStatus.ACTIVE)

    resp = await client.get(DUONG_DAN_USERS, params={"status": UserStatus.PENDING_APPROVAL.value})

    assert resp.status_code == 200, resp.text
    ids = [u["id"] for u in resp.json()["users"]]
    assert ids == [str(cho_duyet)]


async def test_khong_loc_thi_tra_ca_bang(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    admin_id = await _admin(client, session_factory)
    a = await _tao_user(session_factory, UserStatus.PENDING_APPROVAL)
    b = await _tao_user(session_factory, UserStatus.SUSPENDED)

    resp = await client.get(DUONG_DAN_USERS)

    ids = {u["id"] for u in resp.json()["users"]}
    assert {str(admin_id), str(a), str(b)} <= ids


async def test_status_la_thi_422_chu_khong_phai_danh_sach_rong(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Một bộ lọc gõ sai mà trả `[]` sẽ đọc y hệt "không còn ai chờ duyệt"."""
    await _admin(client, session_factory)

    resp = await client.get(DUONG_DAN_USERS, params={"status": "khong-co-that"})

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == ApiErrorCode.VALIDATION_ERROR


async def test_user_da_xoa_mem_khong_hien_trong_danh_sach(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`deleted_at IS NULL` lọc **trong SQL** — §20, cùng lối `get_by_id`."""
    await _admin(client, session_factory)
    da_xoa = await _tao_user(session_factory, UserStatus.ACTIVE)
    async with session_factory() as session:
        await session.execute(update(User).where(User.id == da_xoa).values(deleted_at=func.now()))
        await session.commit()

    resp = await client.get(DUONG_DAN_USERS)

    assert str(da_xoa) not in {u["id"] for u in resp.json()["users"]}


async def test_danh_sach_khong_lo_password_hash(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """§20 — màn admin hiện email, không hiện thứ đăng nhập được bằng."""
    await _admin(client, session_factory)
    await _tao_user(session_factory)

    resp = await client.get(DUONG_DAN_USERS)

    assert "password" not in resp.text.lower()


# ═══════════════════ PATCH /admin/users/{id} — tier & ghi đè ════════════════


async def test_doi_tier_va_ghi_audit(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    admin_id = await _admin(client, session_factory)
    user_id = await _tao_user(session_factory, UserStatus.ACTIVE)

    resp = await client.patch(DUONG_DAN_USER.format(user_id), json={"tier_name": "trusted"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["tier_name"] == "trusted"
    dong = await _audit(session_factory)
    assert len(dong) == 1
    assert dong[0].actor_id == admin_id
    assert dong[0].action == AuditAction.USER_UPDATE
    assert dong[0].details == {"changed": {"tier_name": {"from": "free", "to": "trusted"}}}


async def test_tier_khong_co_that_thi_400_chu_khong_500(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Khoá ngoại `users.tier_name → tiers.name` không được phép nổi lên thành 500."""
    await _admin(client, session_factory)
    user_id = await _tao_user(session_factory, UserStatus.ACTIVE)

    resp = await client.patch(DUONG_DAN_USER.format(user_id), json={"tier_name": "khong-co-that"})

    assert resp.status_code == 400
    assert resp.json()["error"]["details"]["tier_name"] == "khong-co-that"
    assert await _audit(session_factory) == []


async def test_tier_name_null_thi_400(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Cột `NOT NULL` ⇒ `null` không có nghĩa nào; im lặng bỏ qua là tệ hơn."""
    await _admin(client, session_factory)
    user_id = await _tao_user(session_factory, UserStatus.ACTIVE)

    resp = await client.patch(DUONG_DAN_USER.format(user_id), json={"tier_name": None})

    assert resp.status_code == 400


async def test_bat_can_execute_skills_qua_limit_override(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """§16.3 *"bật `can_execute_skills`"* đi qua `limit_override`, không qua một
    trường thứ ba — xem docstring `SuaUserRequest`."""
    await _admin(client, session_factory)
    user_id = await _tao_user(session_factory, UserStatus.ACTIVE)

    resp = await client.patch(
        DUONG_DAN_USER.format(user_id), json={"limit_override": {"can_execute_skills": True}}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["limit_override_json"] == {"can_execute_skills": True}


async def test_limit_override_null_xoa_sach_ghi_de(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`null` = "quay về đúng hạn mức của tier"; vắng mặt = "đừng đụng tới"."""
    await _admin(client, session_factory)
    user_id = await _tao_user(session_factory, UserStatus.ACTIVE)
    await client.patch(
        DUONG_DAN_USER.format(user_id), json={"limit_override": {"max_upload_mb": 50}}
    )

    resp = await client.patch(DUONG_DAN_USER.format(user_id), json={"limit_override": None})

    assert resp.json()["limit_override_json"] is None


async def test_khong_gui_truong_nao_thi_khong_doi_gi_va_khong_ghi_so(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Body rỗng cư xử như `GET` — cùng lối `PATCH /conversations/{id}` (T-1.13)."""
    await _admin(client, session_factory)
    user_id = await _tao_user(session_factory, UserStatus.ACTIVE)

    resp = await client.patch(DUONG_DAN_USER.format(user_id), json={})

    assert resp.status_code == 200
    assert resp.json()["tier_name"] == "free"
    assert await _audit(session_factory) == []


async def test_limit_override_khoa_la_thi_400(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`merge_override` sẽ **im lặng** bỏ qua khoá này lúc đọc — nên phải kêu lúc ghi."""
    await _admin(client, session_factory)
    user_id = await _tao_user(session_factory, UserStatus.ACTIVE)

    resp = await client.patch(
        DUONG_DAN_USER.format(user_id), json={"limit_override": {"khong_co_truong_nay": 1}}
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["details"]["unknown"] == ["khong_co_truong_nay"]


async def test_limit_override_sai_kieu_thi_400(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`merge_override` sẽ vứt **cả** bản ghi đè lúc đọc — một `200` ở đây là nói dối."""
    await _admin(client, session_factory)
    user_id = await _tao_user(session_factory, UserStatus.ACTIVE)

    resp = await client.patch(
        DUONG_DAN_USER.format(user_id), json={"limit_override": {"max_upload_mb": "rat-nhieu"}}
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["details"]["field"] == "max_upload_mb"


async def test_truong_la_trong_body_thi_422(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`extra="forbid"`: gõ `tier` thay vì `tier_name` phải đọc được, không im lặng."""
    await _admin(client, session_factory)
    user_id = await _tao_user(session_factory, UserStatus.ACTIVE)

    resp = await client.patch(DUONG_DAN_USER.format(user_id), json={"tier": "trusted"})

    assert resp.status_code == 422


# ═════════════════ DoD dòng 3 — /admin/usage tách hai nhóm (C16) ════════════


async def _ghi_so(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: uuid.UUID,
    model_id: str,
    cost: str,
    confidence: CostConfidence,
    key_source: KeySource = KeySource.SYSTEM,
) -> None:
    async with session_factory() as session:
        await UsageEventRepository(session).record(
            user_id=user_id,
            message_id=None,
            model_id=model_id,
            provider="nha-cung-cap-test",
            key_source=key_source,
            prompt_tokens=10,
            completion_tokens=20,
            cached_tokens=0,
            cost_usd=Decimal(cost),
            cost_confidence=confidence,
            price_snapshot={},
        )
        await session.commit()


async def test_usage_tra_hai_nhom_rieng_biet(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """DoD dòng 3: *"`/admin/usage` trả hai nhóm riêng biệt (C16)"*.

    Hai dòng sổ cùng một người, cùng một ngày, khác `cost_confidence`. Nếu hai
    cột bị trộn thì `metered.cost_usd` sẽ là `0.3` thay vì `0.1` — tức đúng con
    số mà C16 nói làm bảng chi phí vô nghĩa.
    """
    await _admin(client, session_factory)
    user_id = await _tao_user(session_factory, UserStatus.ACTIVE)
    await _ghi_so(
        session_factory,
        user_id=user_id,
        model_id="model-do-duoc",
        cost="0.1",
        confidence=CostConfidence.EXACT,
    )
    await _ghi_so(
        session_factory,
        user_id=user_id,
        model_id="model-uoc-luong",
        cost="0.2",
        confidence=CostConfidence.LOW,
    )

    resp = await client.get(DUONG_DAN_USAGE)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert Decimal(body["totals"]["metered"]["cost_usd"]) == Decimal("0.1")
    assert Decimal(body["totals"]["unmetered"]["cost_usd"]) == Decimal("0.2")
    assert body["totals"]["metered"]["events"] == 1
    assert body["totals"]["unmetered"]["events"] == 1
    # Không có trường nào cộng hai cột lại — xem docstring `HaiCot`.
    assert "tong" not in body["totals"]
    assert "total" not in body["totals"]

    theo_model = {h["key"]: h for h in body["by_model"]}
    assert Decimal(theo_model["model-do-duoc"]["metered"]["cost_usd"]) == Decimal("0.1")
    assert Decimal(theo_model["model-do-duoc"]["unmetered"]["cost_usd"]) == Decimal("0")
    assert Decimal(theo_model["model-uoc-luong"]["unmetered"]["cost_usd"]) == Decimal("0.2")
    assert Decimal(theo_model["model-uoc-luong"]["metered"]["cost_usd"]) == Decimal("0")

    theo_user = {h["key"]: h for h in body["by_user"]}
    assert Decimal(theo_user[str(user_id)]["metered"]["cost_usd"]) == Decimal("0.1")
    assert Decimal(theo_user[str(user_id)]["unmetered"]["cost_usd"]) == Decimal("0.2")
    assert theo_user[str(user_id)]["label"] is not None

    assert len(body["by_day"]) == 1
    assert Decimal(body["by_day"][0]["metered"]["cost_usd"]) == Decimal("0.1")
    # Khoá của trục "theo ngày" là một NGÀY, không phải `"... 00:00:00"` — một
    # chuỗi mà mọi chỗ hiển thị sẽ phải cắt lại (xem `usage_events._khoa`).
    assert body["by_day"][0]["key"] == datetime.now(UTC).date().isoformat()


async def test_usage_tach_ca_theo_tien_cua_ai(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Trục thứ tư: §10.5 nói khoản `byok` **không** phải tiền của người vận hành."""
    await _admin(client, session_factory)
    user_id = await _tao_user(session_factory, UserStatus.ACTIVE)
    await _ghi_so(
        session_factory,
        user_id=user_id,
        model_id="m",
        cost="0.5",
        confidence=CostConfidence.EXACT,
        key_source=KeySource.SYSTEM,
    )
    await _ghi_so(
        session_factory,
        user_id=user_id,
        model_id="m",
        cost="9.0",
        confidence=CostConfidence.EXACT,
        key_source=KeySource.BYOK,
    )

    body = (await client.get(DUONG_DAN_USAGE)).json()

    theo_nguon = {h["key"]: h for h in body["by_key_source"]}
    assert Decimal(theo_nguon["system"]["metered"]["cost_usd"]) == Decimal("0.5")
    assert Decimal(theo_nguon["byok"]["metered"]["cost_usd"]) == Decimal("9.0")


# ═══════════ T-2.19 / B-178 — `?key_source=` lọc BA trục, không phải bốn ════


async def _hai_nguon(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> uuid.UUID:
    """Một user, hai dòng sổ: `0.5` tiền hệ thống và `9.0` tiền của chính họ."""
    await _admin(client, session_factory)
    user_id = await _tao_user(session_factory, UserStatus.ACTIVE)
    for cost, nguon in (("0.5", KeySource.SYSTEM), ("9.0", KeySource.BYOK)):
        await _ghi_so(
            session_factory,
            user_id=user_id,
            model_id="m",
            cost=cost,
            confidence=CostConfidence.EXACT,
            key_source=nguon,
        )
    return user_id


async def test_usage_loc_system_tra_ve_hoa_don_that(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """B-178: `?key_source=system` ⇒ `totals` là con số S13 đem đối chiếu được.

    Không lọc thì tổng là `9.5` — hoá đơn của người vận hành **cộng thêm** tiền
    của người khác (§10.5). Đúng con số mà B-178 ghi lại, nên nó được đo ở đây
    cạnh con số đã lọc chứ không phải ở một test khác: hai phép đo rời nhau thì
    ngày một trong hai đổi, không ai thấy chúng lệch.
    """
    user_id = await _hai_nguon(client, session_factory)

    tron = (await client.get(DUONG_DAN_USAGE)).json()
    assert Decimal(tron["totals"]["metered"]["cost_usd"]) == Decimal("9.5")
    assert tron["key_source"] is None

    resp = await client.get(DUONG_DAN_USAGE, params={"key_source": "system"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["key_source"] == "system"
    assert Decimal(body["totals"]["metered"]["cost_usd"]) == Decimal("0.5")
    # Cả BA trục hoá đơn, không riêng `totals`: một bảng "theo model" còn `9.5`
    # trong khi tổng đã là `0.5` là một màn hình tự mâu thuẫn với chính nó.
    assert Decimal(body["by_day"][0]["metered"]["cost_usd"]) == Decimal("0.5")
    assert Decimal(body["by_model"][0]["metered"]["cost_usd"]) == Decimal("0.5")
    theo_user = {h["key"]: h for h in body["by_user"]}
    assert Decimal(theo_user[str(user_id)]["metered"]["cost_usd"]) == Decimal("0.5")


async def test_usage_loc_khong_cham_toi_truc_theo_nguon(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`by_key_source` vẫn đủ **cả hai** nguồn kể cả khi ba trục kia đã bị lọc.

    Đây là điều kiện để mặc định `system` của màn "Chi phí" không thành một
    kiểu nói dối mới: lọc mà xoá sạch dấu vết phần bị loại ra thì người vận
    hành không còn đường nào biết là có phần ấy. Xem `admin_by_key_source`.
    """
    await _hai_nguon(client, session_factory)

    body = (await client.get(DUONG_DAN_USAGE, params={"key_source": "system"})).json()

    theo_nguon = {h["key"]: h for h in body["by_key_source"]}
    assert set(theo_nguon) == {"system", "byok"}
    assert Decimal(theo_nguon["byok"]["metered"]["cost_usd"]) == Decimal("9.0")


async def test_usage_loc_byok_tra_ve_dung_phan_khong_phai_tien_minh(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Chiều ngược lại — nút "BYOK" của màn Chi phí đi qua đúng đường này."""
    await _hai_nguon(client, session_factory)

    body = (await client.get(DUONG_DAN_USAGE, params={"key_source": "byok"})).json()

    assert body["key_source"] == "byok"
    assert Decimal(body["totals"]["metered"]["cost_usd"]) == Decimal("9.0")


async def test_usage_key_source_la_khong_phai_chuoi_tu_do(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`?key_source=abc` ⇒ `422`, không phải im lặng trả về "mọi nguồn".

    Cùng lý lẽ `?status=abc` của `list_users`: một bộ lọc gõ sai mà vẫn trả
    `200` sẽ đọc y hệt một hoá đơn phình to, và không có gì trên màn hình nói
    rằng bộ lọc đã bị bỏ qua.
    """
    await _admin(client, session_factory)

    resp = await client.get(DUONG_DAN_USAGE, params={"key_source": "abc"})

    assert resp.status_code == 422


async def test_usage_bo_qua_dong_ngoai_cua_so(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Biên nửa mở `[since, until)` — hai cửa sổ liền nhau không đếm chung một dòng."""
    await _admin(client, session_factory)
    user_id = await _tao_user(session_factory, UserStatus.ACTIVE)
    await _ghi_so(
        session_factory,
        user_id=user_id,
        model_id="m",
        cost="0.1",
        confidence=CostConfidence.EXACT,
    )

    bay_gio = datetime.now(UTC)
    resp = await client.get(
        DUONG_DAN_USAGE,
        params={
            "since": (bay_gio - timedelta(days=30)).isoformat(),
            "until": (bay_gio - timedelta(days=29)).isoformat(),
        },
    )

    body = resp.json()
    assert body["by_day"] == []
    assert Decimal(body["totals"]["metered"]["cost_usd"]) == Decimal("0")


async def test_usage_since_sau_until_thi_400(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _admin(client, session_factory)
    bay_gio = datetime.now(UTC)

    resp = await client.get(
        DUONG_DAN_USAGE,
        params={"since": bay_gio.isoformat(), "until": (bay_gio - timedelta(days=1)).isoformat()},
    )

    assert resp.status_code == 400


# ═══════════════════════ POST /admin/catalog/reload (B-34) ══════════════════


async def test_reload_catalog_ghi_audit(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """B-34 đóng: endpoint vẫn làm đúng việc cũ, nay có khoá và có sổ."""
    admin_id = await _admin(client, session_factory)

    resp = await client.post(DUONG_DAN_RELOAD)

    assert resp.status_code == 200, resp.text
    assert resp.json()["models"] > 0
    dong = await _audit(session_factory)
    assert len(dong) == 1
    assert dong[0].actor_id == admin_id
    assert dong[0].action == AuditAction.CATALOG_RELOAD
    assert dong[0].target_id is None
    assert dong[0].details["models"] == resp.json()["models"]


# ════════════════════════════ hai endpoint ĐỌC không ghi sổ ═════════════════


async def test_endpoint_doc_khong_de_lai_dong_audit_nao(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """§20 nói "mọi **hành động** admin" — mở một màn hình không phải hành động."""
    await _admin(client, session_factory)

    await client.get(DUONG_DAN_USERS)
    await client.get(DUONG_DAN_USAGE)

    assert await _audit(session_factory) == []


# ═══════════════ cột `ip INET` — hai đường vào, hai kết cục ═════════════════


async def test_ghi_dung_ip_that_vao_cot_inet(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """§16.3 màn "Audit log" hỏi *"ai, lúc nào, làm gì, với ai"* — `ip` là phần
    trả lời cho câu thứ nhất khi tên người chưa đủ.

    `X-Real-IP` là header Nginx đặt (`$remote_addr`), cùng nguồn mà
    `core/ratelimit.py` đã tin — xem docstring của module đó cho lý do tin được.
    """
    await _admin(client, session_factory)
    user_id = await _tao_user(session_factory, UserStatus.PENDING_APPROVAL)

    await client.post(
        DUONG_DAN_HANH_DONG.format(user_id, "approve"), headers={"X-Real-IP": "203.0.113.7"}
    )

    dong = await _audit(session_factory)
    assert dong[0].ip == ip_address("203.0.113.7")


async def test_ip_khong_doc_duoc_thi_null_chu_khong_lam_hong_ca_hanh_dong(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`dia_chi_ip` trả `"unknown"` khi không có IP nào — một giá trị hợp lý cho
    một khoá Redis và **không hợp lệ** cho cột `INET`.

    Phép kiểm ngược của `_ip_hop_le`: bỏ nó đi thì Postgres từ chối `INSERT`,
    và vì dòng sổ nằm cùng transaction với việc nó mô tả (§20), **cả lần duyệt**
    đổ theo. Tức một chi tiết ghi log làm hỏng chính hành động admin.
    """
    monkeypatch.setattr("app.api.v1.admin.dia_chi_ip", lambda _request: "unknown")
    await _admin(client, session_factory)
    user_id = await _tao_user(session_factory, UserStatus.PENDING_APPROVAL)

    resp = await client.post(DUONG_DAN_HANH_DONG.format(user_id, "approve"))

    assert resp.status_code == 200, resp.text
    dong = await _audit(session_factory)
    assert len(dong) == 1
    assert dong[0].ip is None


# ══════════ hai admin bấm cùng lúc — phép kiểm ngược của `WHERE status` ═════


async def test_hai_admin_bam_cung_luc_thi_chi_mot_cau_thang(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`set_status` chuyển trạng thái **trong** câu UPDATE, không bằng một `if`
    chạy trước nó.

    **Test này ra đời vì phép kiểm ngược của nó lúc đầu XANH.** Bỏ
    `WHERE status = :tu` khỏi `UserRepository.set_status` không làm đỏ ca nào
    trong file này, và việc nó không đỏ là đúng: handler đã so trạng thái ở
    Python ngay trước đó, nên trong một bộ test chạy tuần tự thì câu `WHERE`
    ấy không đổi kết quả nào. Thứ nó bảo vệ chỉ lộ ra khi có **hai** người bấm:
    giữa lúc đọc và lúc ghi, đồng nghiệp bấm Từ chối xong.

    Vì vậy ca này chèn đúng cái khe đó — một session khác đổi `status` sau khi
    handler đã đọc user và trước khi nó ghi. Có `WHERE status = :tu` thì câu
    UPDATE không khớp hàng nào ⇒ `409`, không dòng sổ nào, và tài khoản **không**
    thành `active`. Không có nó thì lần Duyệt này ghi đè lần Từ chối vừa xong mà
    không ai biết — `200` và `status='active'`.

    Phép so cuối là *"không phải `active`"* chứ không phải *"đúng bằng
    `rejected`"*, và đó là giới hạn của hạ tầng test chứ không phải của luật:
    cả bộ test chạy trên **một** kết nối với savepoint lồng nhau (xem
    `tests/conftest.py`), nên khi `session_scope()` của handler cuộn lại vì
    `409`, savepoint của session "đồng nghiệp" nằm bên trong nó cuộn theo. Trên
    Postgres thật, hai request là hai kết nối và lần Từ chối ở lại.
    """
    await _admin(client, session_factory)
    user_id = await _tao_user(session_factory, UserStatus.PENDING_APPROVAL)
    goc = UserRepository.set_status

    async def chen_ngang(
        self: UserRepository,
        ma_user: uuid.UUID,
        *,
        tu: UserStatus,
        sang: UserStatus,
        approved_by: uuid.UUID | None = None,
    ) -> User | None:
        async with session_factory() as khac:
            await khac.execute(
                update(User).where(User.id == ma_user).values(status=UserStatus.REJECTED)
            )
            await khac.commit()
        return await goc(self, ma_user, tu=tu, sang=sang, approved_by=approved_by)

    monkeypatch.setattr(UserRepository, "set_status", chen_ngang)

    resp = await client.post(DUONG_DAN_HANH_DONG.format(user_id, "approve"))

    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == ApiErrorCode.INVALID_STATUS_TRANSITION
    assert await _status_trong_db(session_factory, user_id) is not UserStatus.ACTIVE
    assert await _audit(session_factory) == []


async def test_patch_gui_lai_dung_gia_tri_dang_co_thi_khong_ghi_so(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Lưu form lần hai mà không sửa gì ⇒ `200` và **không** dòng sổ nào.

    Cùng luật với nhánh "đích đã đạt" của `change_user_status` — xem docstring
    `update_user`. Không có nó thì sổ audit dài ra bằng số lần bấm Lưu chứ
    không bằng số thay đổi, và một sổ như thế thì không ai đọc nữa.
    """
    await _admin(client, session_factory)
    user_id = await _tao_user(session_factory, UserStatus.ACTIVE)
    await client.patch(DUONG_DAN_USER.format(user_id), json={"tier_name": "trusted"})

    resp = await client.patch(DUONG_DAN_USER.format(user_id), json={"tier_name": "trusted"})

    assert resp.status_code == 200
    assert resp.json()["tier_name"] == "trusted"
    assert len(await _audit(session_factory)) == 1


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  T-2.20 — bốn endpoint còn lại của §18.5                                 ║
# ╚══════════════════════════════════════════════════════════════════════════╝


async def _audit_row(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    actor_id: uuid.UUID | None,
    action: AuditAction,
    target_id: str | None = None,
) -> int:
    """Một dòng sổ đặt sẵn, trả về `id` của nó.

    Đi thẳng vào repository chứ không qua một endpoint: những ca dưới đây cần
    **thứ tự** và **số lượng** dòng chính xác, còn đi vòng qua `POST
    /admin/users/{id}/approve` thì mỗi dòng sổ phải kéo theo một tài khoản thật
    và một phép chuyển trạng thái hợp lệ — tức ba thứ phải đúng để đo một thứ.
    """
    async with session_factory() as session:
        row = await AuditLogRepository(session).record(
            actor_id=actor_id, action=action, target_type=TARGET_USER, target_id=target_id
        )
        await session.commit()
        return row.id


# ═══════════════════════ GET /admin/tiers — §10.4, §18.5 ═══════════════════


async def test_danh_sach_tier_du_chin_cot_va_sap_theo_ten(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Hai tier của migration 0001, sắp theo tên, đủ chín cột của §10.4."""
    await _admin(client, session_factory)

    resp = await client.get(DUONG_DAN_TIERS)

    assert resp.status_code == 200, resp.text
    tiers = resp.json()["tiers"]
    assert [t["name"] for t in tiers] == ["free", "trusted"]
    assert set(tiers[0]) == {
        "name",
        "limit_5h_usd",
        "limit_7d_usd",
        "can_execute_skills",
        "can_use_web",
        "web_searches_per_day",
        "max_upload_mb",
        "max_attachments",
        "allowed_model_tags",
        "is_default",
    }


async def test_danh_sach_tier_khong_ghi_so(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Đọc không phải một hành động — §20, "Việc cần làm" dòng 4 của task."""
    await _admin(client, session_factory)

    await client.get(DUONG_DAN_TIERS)

    assert await _audit(session_factory) == []


# ═════════════════ PATCH /admin/tiers/{name} — §10.4, §16.3 ════════════════


async def test_doi_han_muc_ca_tier_va_ghi_mot_dong_audit(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Nửa "đổi" của §10.4 — một dòng sổ, `target_id` là **tên tier**."""
    admin_id = await _admin(client, session_factory)

    resp = await client.patch(DUONG_DAN_TIER.format("free"), json={"limit_5h_usd": "1.2500"})

    assert resp.status_code == 200, resp.text
    assert Decimal(resp.json()["limit_5h_usd"]) == Decimal("1.2500")

    dong = await _audit(session_factory)
    assert len(dong) == 1
    assert dong[0].actor_id == admin_id
    assert dong[0].action == AuditAction.TIER_UPDATE
    assert dong[0].target_type == TARGET_TIER
    assert dong[0].target_id == "free"
    assert dong[0].details == {"changed": {"limit_5h_usd": {"from": "0.5000", "to": "1.2500"}}}


async def test_tien_trong_dong_so_la_CHUOI_khong_phai_float(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`Decimal` đi vào JSONB phải qua `_json_safe` — nếu không, cả `PATCH` đỏ.

    Ca này là phép kiểm ngược của chính nó: bỏ `_json_safe` đi thì bộ mã hoá
    JSON của cột `details` ném `TypeError` **trong cùng transaction** với câu
    `UPDATE`, nên hạn mức cũng không đổi. Một `float` thì lặng lẽ hơn và tệ hơn
    — sổ ghi `0.5000000000000001` đúng lúc người ta mở sổ ra để đối chiếu tiền.
    """
    await _admin(client, session_factory)

    await client.patch(DUONG_DAN_TIER.format("free"), json={"limit_7d_usd": "9.5000"})

    doi = (await _audit(session_factory))[0].details
    assert doi is not None
    assert doi["changed"]["limit_7d_usd"] == {"from": "3.0000", "to": "9.5000"}
    assert isinstance(doi["changed"]["limit_7d_usd"]["to"], str)


async def test_doi_nhieu_cot_mot_luot_ghi_dung_mot_dong(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Một lần bấm Lưu là một dòng sổ, dù nó đổi bốn cột."""
    await _admin(client, session_factory)

    resp = await client.patch(
        DUONG_DAN_TIER.format("trusted"),
        json={
            "can_execute_skills": False,
            "can_use_web": False,
            "max_attachments": 12,
            "allowed_model_tags": ["fast", "vision"],
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["can_execute_skills"] is False
    assert body["can_use_web"] is False
    assert body["max_attachments"] == 12
    assert body["allowed_model_tags"] == ["fast", "vision"]

    dong = await _audit(session_factory)
    assert len(dong) == 1
    assert dong[0].details is not None
    assert set(dong[0].details["changed"]) == {
        "can_execute_skills",
        "can_use_web",
        "max_attachments",
        "allowed_model_tags",
    }


async def test_gui_lai_dung_gia_tri_dang_co_thi_khong_ghi_so(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Lưu cả form mà không sửa gì ⇒ `200`, không dòng sổ nào — cùng `update_user`."""
    await _admin(client, session_factory)

    resp = await client.patch(DUONG_DAN_TIER.format("free"), json={"limit_5h_usd": "0.5000"})

    assert resp.status_code == 200, resp.text
    assert await _audit(session_factory) == []


async def test_body_rong_cu_xu_nhu_GET(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`PATCH {}` không chạy câu UPDATE nào nhưng vẫn trả hàng hiện tại."""
    await _admin(client, session_factory)

    resp = await client.patch(DUONG_DAN_TIER.format("free"), json={})

    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "free"
    assert await _audit(session_factory) == []


async def test_tier_khong_co_that_thi_404(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Mã riêng, không phải `NOT_FOUND` chung — xem `ApiErrorCode.TIER_NOT_FOUND`."""
    await _admin(client, session_factory)

    resp = await client.patch(DUONG_DAN_TIER.format("khong-co-that"), json={"max_upload_mb": 1})

    assert resp.status_code == 404, resp.text
    loi = resp.json()["error"]
    assert loi["code"] == ApiErrorCode.TIER_NOT_FOUND
    assert loi["details"]["name"] == "khong-co-that"
    assert await _audit(session_factory) == []


async def test_gui_null_cho_mot_cot_NOT_NULL_thi_400(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`null` không có nghĩa nào cho một cột `NOT NULL` — 400, không bỏ qua im lặng."""
    await _admin(client, session_factory)

    resp = await client.patch(DUONG_DAN_TIER.format("free"), json={"can_use_web": None})

    assert resp.status_code == 400, resp.text
    loi = resp.json()["error"]
    assert loi["code"] == ApiErrorCode.BAD_REQUEST
    assert loi["details"]["fields"] == ["can_use_web"]


@pytest.mark.parametrize("khoa", ["is_default", "name", "limit_5h"])
async def test_khoa_khong_sua_duoc_thi_422(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], khoa: str
) -> None:
    """`extra="forbid"`: `is_default` (B-152), `name` (khoá chính), và một lần gõ nhầm.

    Cả ba đi cùng một đường ra vì với người gọi chúng là cùng một câu chuyện —
    "trường này không sửa được ở đây". Ngả kia (`200` rồi bỏ qua) là đúng thứ
    "lệch trong im lặng" mà `update_user` đã từ chối.
    """
    await _admin(client, session_factory)

    resp = await client.patch(DUONG_DAN_TIER.format("free"), json={khoa: "x"})

    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == ApiErrorCode.VALIDATION_ERROR


async def test_han_muc_am_bi_tu_choi(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`ge=0`: một `limit_5h_usd` âm khoá sạch tier mà không ai đọc ra lý do."""
    await _admin(client, session_factory)

    resp = await client.patch(DUONG_DAN_TIER.format("free"), json={"limit_5h_usd": "-1"})

    assert resp.status_code == 422, resp.text


def test_tam_truong_cua_PATCH_dung_bang_OVERRIDABLE_FIELDS() -> None:
    """Hai tập ấy bằng nhau **không phải tình cờ** — xem docstring `UpdateTierRequest`.

    Ngày `EffectiveLimits` mọc thêm một trường mà body của `PATCH /admin/tiers`
    quên, đây là chỗ nó tự khai — thay vì một ô nhập biến mất khỏi màn hình
    admin mà không ai để ý.
    """
    assert set(UpdateTierRequest.model_fields) == OVERRIDABLE_FIELDS


async def test_doi_tier_KHONG_go_cache_va_Postgres_thay_ngay(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], redis_gia: _RedisGia
) -> None:
    """Cạm bẫy của task, đo từ **hai** phía cùng lúc (NQ-51, §10.4).

    Phía Redis: không một lệnh xoá nào được phát. Cache nhớ
    `tier:limits:{user_id}` — kết quả đã gộp của **từng người** — nên một lệnh
    xoá đặt theo *tên tier* sẽ xoá một khoá chưa từng tồn tại, chạy xong mà
    không báo gì, và để lại cảm giác đã gỡ cache. TTL 60 s là luật duy nhất.

    Phía Postgres: hạn mức mới có mặt **ngay**, nên ≤ 60 s của §10.4 là độ trễ
    của đúng một lớp cache chứ không phải của một câu UPDATE chưa chạy. Đây là
    nửa đo được trong bộ test của DoD dòng 2; nửa còn lại (đồng hồ thật, không
    restart) chạy trên stack thật.
    """
    await _admin(client, session_factory)
    user_id = await _tao_user(session_factory, UserStatus.ACTIVE)

    await client.patch(DUONG_DAN_TIER.format("free"), json={"limit_5h_usd": "7.0000"})

    assert redis_gia.da_xoa == []
    async with session_factory() as session:
        thay = await TierRepository(session).get_for_user(user_id)
    assert thay is not None
    assert thay.tier.name == "free"
    assert thay.tier.limit_5h_usd == Decimal("7.0000")


# ══════════════════ GET /admin/system — §16.3, §21.2, DoD dòng 4 ═══════════


def _health_gia(redis_ok: bool = True) -> dict[str, CheckResult]:
    """Kết quả `run_checks()` giả — năm mục như `app/core/health_checks.py`."""
    return {
        ten: CheckResult(ok=True, latency_ms=1)
        for ten in ("postgres", "minio", "litellm", "ninerouter")
    } | {
        "redis": CheckResult(
            ok=redis_ok,
            latency_ms=2000,
            error=None if redis_ok else "Error 111 connecting to redis:6379.",
        )
    }


@pytest.fixture
def he_thong_gia(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hạ tầng giả cho màn "Hệ thống": `run_checks` và `queue_depth` đều là mock.

    Cả hai mở kết nối **ra ngoài** (năm service, và một pool arq riêng), thứ mà
    một bộ test đơn vị không có và không nên có. `count_streaming` thì **không**
    bị giả: nó đi đúng Postgres thật của bộ test, vì con số ấy là thứ duy nhất
    ở đây có thể sai một cách thú vị.
    """
    monkeypatch.setattr("app.api.v1.admin.run_checks", lambda: _tra_ve(_health_gia()))
    monkeypatch.setattr("app.api.v1.admin.queue_depth", lambda: _tra_ve(3))


async def _tra_ve(gia_tri: Any) -> Any:
    return gia_tri


async def test_man_he_thong_tra_du_bon_o(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    he_thong_gia: None,
) -> None:
    """DoD dòng 4: `queue_depth`, `streams_dang_chay`, `version`, `health`."""
    await _admin(client, session_factory)

    resp = await client.get(DUONG_DAN_SYSTEM)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {"queue_depth", "streams_dang_chay", "version", "health"}
    assert body["queue_depth"] == 3
    assert body["version"] == APP_VERSION
    assert set(body["health"]) == {"postgres", "redis", "minio", "litellm", "ninerouter"}


async def test_dem_dung_so_stream_dang_chay(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    he_thong_gia: None,
) -> None:
    """Đếm `streaming`, **không** đếm `queued` — §16.3 tách hai chỉ số cạnh nhau.

    Gộp `queued` vào đây là đếm cùng một job hai lần trên cùng một màn hình:
    nó đã nằm trong `queue_depth` rồi.
    """
    await _admin(client, session_factory)
    user_id = await _tao_user(session_factory, UserStatus.ACTIVE)
    async with session_factory() as session:
        conv = Conversation(user_id=user_id)
        session.add(conv)
        await session.flush()
        for trang_thai in (
            MessageStatus.STREAMING,
            MessageStatus.STREAMING,
            MessageStatus.QUEUED,
            MessageStatus.COMPLETED,
        ):
            session.add(
                Message(conversation_id=conv.id, role=MessageRole.ASSISTANT, status=trang_thai)
            )
        await session.commit()

    resp = await client.get(DUONG_DAN_SYSTEM)

    assert resp.json()["streams_dang_chay"] == 2


async def test_redis_chet_van_tra_loi_khong_500(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DoD dòng 4 nửa sau: *"tắt `redis` → endpoint vẫn trả lời (báo hỏng), không 500"*.

    Đây là màn hình người ta mở **khi** có sự cố, nên nó là màn hình cuối cùng
    được phép chết theo sự cố ấy. Ba tính chất cùng lúc: `200` chứ không `500`
    và cũng không `503`; ô không hỏi được là `null` chứ không phải `0` (một `0`
    đọc ra là "hàng đợi rỗng", tức đúng ngược với sự thật); và lý do nằm ở
    `health`, một chỗ duy nhất.

    `streams_dang_chay` vẫn là một con số vì nó đi Postgres — mỗi ô một nguồn
    và hỏng riêng, không có ô nào kéo theo ô nào.
    """
    await _admin(client, session_factory)

    def _no(*_: Any, **__: Any) -> Any:
        raise ConnectionError("Error 111 connecting to redis:6379.")

    monkeypatch.setattr("app.api.v1.admin.run_checks", lambda: _tra_ve(_health_gia(redis_ok=False)))
    monkeypatch.setattr("app.api.v1.admin.queue_depth", _no)

    resp = await client.get(DUONG_DAN_SYSTEM)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["queue_depth"] is None
    assert body["streams_dang_chay"] == 0
    assert body["health"]["redis"]["ok"] is False
    assert "111" in body["health"]["redis"]["error"]


async def test_man_he_thong_khong_ghi_so(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    he_thong_gia: None,
) -> None:
    await _admin(client, session_factory)

    await client.get(DUONG_DAN_SYSTEM)

    assert await _audit(session_factory) == []


# ═══════════ GET /admin/audit-logs — §16.3, DoD dòng 3 ═════════════════════


async def test_doc_dung_dong_ma_PATCH_vua_ghi(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """DoD dòng 3: *"trả đúng dòng mà `PATCH` vừa ghi"*.

    Đo cả **bốn câu** của §16.3 trong một ca, vì chúng chỉ có ích cùng nhau:
    ai (`actor_email`, không phải một UUID), lúc nào (`created_at`), làm gì
    (`action`), với ai (`target_type` + `target_id`).
    """
    admin_id = await _admin(client, session_factory)
    async with session_factory() as session:
        email = (await session.execute(select(User.email).where(User.id == admin_id))).scalar_one()
    await client.patch(DUONG_DAN_TIER.format("free"), json={"limit_5h_usd": "2.0000"})

    resp = await client.get(DUONG_DAN_AUDIT)

    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 1
    dong = items[0]
    assert dong["actor_id"] == str(admin_id)
    assert dong["actor_email"] == email
    assert dong["action"] == AuditAction.TIER_UPDATE.value
    assert dong["target_type"] == TARGET_TIER
    assert dong["target_id"] == "free"
    assert dong["details"]["changed"]["limit_5h_usd"]["to"] == "2.0000"
    assert dong["created_at"] is not None


async def test_loc_action_nam_TRONG_cau_SQL(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """DoD dòng 3 nửa sau: *"`?action=` lọc **trong câu SQL**"* — và đây là phép đo.

    Bố cục cố ý: ba dòng `user.approve` **cũ**, rồi hai dòng `catalog.reload`
    **mới nhất**. Hỏi `?action=user.approve&limit=2`:

    * lọc trong SQL ⇒ `WHERE` chạy trước `LIMIT` ⇒ đúng **2** dòng, cả hai
      `user.approve`;
    * lọc ở Python sau khi đã `SELECT ... LIMIT 2` ⇒ hai dòng lấy về là hai
      dòng `catalog.reload` mới nhất, sàng xong còn **0**.

    Một ca "lọc đúng" thông thường (đếm tổng số dòng trả về) **không** phân
    biệt được hai ngả ấy; con số `limit` nhỏ hơn số dòng là thứ làm chúng tách
    ra.
    """
    admin_id = await _admin(client, session_factory)
    for _ in range(3):
        await _audit_row(session_factory, actor_id=admin_id, action=AuditAction.USER_APPROVE)
    for _ in range(2):
        await _audit_row(session_factory, actor_id=admin_id, action=AuditAction.CATALOG_RELOAD)

    resp = await client.get(DUONG_DAN_AUDIT, params={"action": "user.approve", "limit": 2})

    items = resp.json()["items"]
    assert len(items) == 2
    assert {d["action"] for d in items} == {AuditAction.USER_APPROVE.value}


async def test_loc_actor_id_nam_trong_cau_SQL(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Cùng hình dạng với `?action=`, trục khác: `?actor_id=` cũng lọc trước `LIMIT`."""
    admin_id = await _admin(client, session_factory)
    nguoi_khac = await _tao_user(session_factory, UserStatus.ACTIVE, role=UserRole.ADMIN)
    for _ in range(3):
        await _audit_row(session_factory, actor_id=admin_id, action=AuditAction.USER_APPROVE)
    for _ in range(2):
        await _audit_row(session_factory, actor_id=nguoi_khac, action=AuditAction.USER_APPROVE)

    resp = await client.get(DUONG_DAN_AUDIT, params={"actor_id": str(admin_id), "limit": 2})

    items = resp.json()["items"]
    assert len(items) == 2
    assert {d["actor_id"] for d in items} == {str(admin_id)}


async def test_cua_so_thoi_gian_nua_mo(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`[since, until)` — dòng nằm đúng ở mốc `until` **không** thuộc trang này.

    Nửa mở là thứ giữ cho hai trang chia theo ngày không đếm hai lần cùng một
    dòng; nó cũng là quy ước `GET /admin/usage` đã dùng, nên hai màn hình cạnh
    nhau không đọc cùng một khoảng theo hai kiểu.
    """
    admin_id = await _admin(client, session_factory)
    ma_dong = await _audit_row(session_factory, actor_id=admin_id, action=AuditAction.USER_APPROVE)
    async with session_factory() as session:
        moc = (
            await session.execute(select(AuditLog.created_at).where(AuditLog.id == ma_dong))
        ).scalar_one()

    trong = await client.get(DUONG_DAN_AUDIT, params={"since": moc.isoformat()})
    ngoai = await client.get(DUONG_DAN_AUDIT, params={"until": moc.isoformat()})

    assert [d["id"] for d in trong.json()["items"]] == [ma_dong]
    assert ngoai.json()["items"] == []


async def test_since_sau_until_thi_400(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Cùng câu trả lời với `GET /admin/usage` cho cùng một lỗi của người gọi."""
    await _admin(client, session_factory)
    bay_gio = datetime.now(UTC)

    resp = await client.get(
        DUONG_DAN_AUDIT,
        params={
            "since": bay_gio.isoformat(),
            "until": (bay_gio - timedelta(days=1)).isoformat(),
        },
    )

    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["code"] == ApiErrorCode.BAD_REQUEST


async def test_phan_trang_bang_con_tro_khong_lap_khong_sot(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Con trỏ `id`, mới nhất trước — hai trang phủ đúng năm dòng, không trùng nhau.

    Trang cuối chưa đầy ⇒ `next_cursor` là `null`, không mời client hỏi thêm
    một vòng chỉ để nhận về danh sách rỗng (cùng lối `GET /conversations`).
    """
    admin_id = await _admin(client, session_factory)
    ma = [
        await _audit_row(session_factory, actor_id=admin_id, action=AuditAction.USER_APPROVE)
        for _ in range(5)
    ]

    trang1 = (await client.get(DUONG_DAN_AUDIT, params={"limit": 3})).json()
    trang2 = (
        await client.get(DUONG_DAN_AUDIT, params={"limit": 3, "before_id": trang1["next_cursor"]})
    ).json()

    assert [d["id"] for d in trang1["items"]] == list(reversed(ma[2:]))
    assert trang1["next_cursor"] == ma[2]
    assert [d["id"] for d in trang2["items"]] == list(reversed(ma[:2]))
    assert trang2["next_cursor"] is None


async def test_actor_da_xoa_van_con_dong_so(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`ON DELETE SET NULL`: dòng sổ ở lại, chỉ mất con trỏ về người.

    `actor_email` khi ấy là `None`, giống hệt một hành động do cron sinh ra —
    và cả hai đều là câu trả lời đúng: *"không còn biết là ai"*.
    """
    await _admin(client, session_factory)
    await _audit_row(session_factory, actor_id=None, action=AuditAction.CATALOG_RELOAD)

    items = (await client.get(DUONG_DAN_AUDIT)).json()["items"]

    assert len(items) == 1
    assert items[0]["actor_id"] is None
    assert items[0]["actor_email"] is None


async def test_action_la_thi_422(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Một bộ lọc gõ sai mà trả `[]` sẽ đọc y hệt "sổ trống" — cùng lối `?status=`."""
    await _admin(client, session_factory)

    resp = await client.get(DUONG_DAN_AUDIT, params={"action": "user.xoa-het"})

    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == ApiErrorCode.VALIDATION_ERROR


async def test_doc_so_khong_ghi_them_dong_nao(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Một sổ mà mỗi lần mở lại dài thêm một dòng là một sổ tự lấp chính nó."""
    await _admin(client, session_factory)

    await client.get(DUONG_DAN_AUDIT)
    await client.get(DUONG_DAN_AUDIT)

    assert await _audit(session_factory) == []
