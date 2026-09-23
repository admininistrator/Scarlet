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
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from ipaddress import ip_address
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from app.api.v1 import admin as admin_api
from app.api.v1.admin import UpdateTierRequest
from app.config.settings import settings
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
    UsageEvent,
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

USERS_PATH = "/api/v1/admin/users"
USER_PATH = "/api/v1/admin/users/{}"
ACTION_PATH = "/api/v1/admin/users/{}/{}"
USAGE_PATH = "/api/v1/admin/usage"
RELOAD_PATH = "/api/v1/admin/catalog/reload"
TIERS_PATH = "/api/v1/admin/tiers"
TIER_PATH = "/api/v1/admin/tiers/{}"
SYSTEM_PATH = "/api/v1/admin/system"
AUDIT_PATH = "/api/v1/admin/audit-logs"


# ═══════════════════════════ hạ tầng của bộ test ════════════════════════════


class _FakeRedis:
    """Blacklist rỗng khi ĐỌC, có sổ khi GHI.

    `mget` luôn trả `None` nên không token nào của bộ test này bị coi là đã thu
    hồi — cùng lý do `test_account_states.py` làm vậy. `set` thì **giữ lại**,
    vì hai quyết định của task chỉ nhìn thấy được ở đó: `approve` phải đặt
    `bl:user:{uid}` (B-141/NQ-61) và `reject` phải **không** đặt gì.
    """

    def __init__(self) -> None:
        self.set_calls: dict[str, str] = {}
        self.deleted: list[str] = []

    async def mget(self, keys: list[str]) -> list[str | None]:
        return [None for _ in keys]

    async def set(self, name: str, value: str, *, ex: int | None = None, **_: Any) -> bool:
        self.set_calls[name] = value
        return True

    async def delete(self, *names: str) -> int:
        """Có mặt để ĐẾM, không phải để dùng (T-2.20, NQ-51).

        `PATCH /admin/tiers` cố ý **không** gỡ cache hạn mức — TTL 60 s là luật
        duy nhất. Một danh sách rỗng ở đây là cách duy nhất khẳng định điều đó
        từ phía Redis; không có phương thức này thì một lời gọi `delete` lén
        đưa vào sau sẽ nổ thành `AttributeError`, tức một `500` khó đọc thay vì
        một test đỏ nói đúng chuyện.
        """
        self.deleted.extend(names)
        return len(names)


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    fake = _FakeRedis()
    monkeypatch.setattr("app.core.deps.get_redis", lambda: fake)
    monkeypatch.setattr("app.api.v1.admin.get_redis", lambda: fake)
    return fake


@pytest.fixture(autouse=True)
def _db_for_tests(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`session_scope()` trong handler trỏ vào ĐÚNG kết nối của test (NQ-17)."""
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


@pytest.fixture(autouse=True)
def _forget_system_cache() -> Iterator[None]:
    """B-192 (T-3.12): `GET /admin/system` nhớ kết quả healthcheck vài giây.

    Bộ nhớ ấy sống ở tầm module, nên không dọn thì một ca thay `run_checks`
    bằng "Redis chết" sẽ đọc lại kết quả "mọi thứ sống" của ca chạy trước nó
    — một ca xanh vì lý do hoàn toàn khác với lý do nó tưởng.
    """
    admin_api._system_health.clear()
    yield
    admin_api._system_health.clear()


@pytest_asyncio.fixture
async def client(event_hooks: dict[str, Any]) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://localhost", event_hooks=event_hooks
    ) as http:
        yield http


async def _create_user(
    session_factory: async_sessionmaker[AsyncSession],
    status: UserStatus = UserStatus.PENDING_APPROVAL,
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
            update(User).where(User.id == user.id).values(status=status, role=role)
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
    admin_id = await _create_user(session_factory, UserStatus.ACTIVE, role=UserRole.ADMIN)
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


async def _status_in_db(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> UserStatus:
    async with session_factory() as session:
        return (await session.execute(select(User.status).where(User.id == user_id))).scalar_one()


# ════════════════ DoD dòng 2 — duyệt một user, ghi đúng một dòng ════════════


async def test_approve_user_changes_status_and_writes_one_audit_row(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """DoD dòng 2: *"Duyệt một user → `status='active'`, có 1 dòng `audit_logs`
    với `actor_id` đúng"*."""
    admin_id = await _admin(client, session_factory)
    user_id = await _create_user(session_factory, UserStatus.PENDING_APPROVAL)

    resp = await client.post(ACTION_PATH.format(user_id, "approve"))

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == UserStatus.ACTIVE.value
    assert await _status_in_db(session_factory, user_id) is UserStatus.ACTIVE

    rows = await _audit(session_factory)
    assert len(rows) == 1
    assert rows[0].actor_id == admin_id
    assert rows[0].action == AuditAction.USER_APPROVE
    assert rows[0].target_id == str(user_id)
    assert rows[0].details == {"from": UserStatus.PENDING_APPROVAL.value, "to": "active"}


async def test_approve_writes_approved_at_and_approved_by(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Hai cột của Phụ lục A trả lời *"ai đã nhận người này vào"* — chỉ nhánh duyệt."""
    admin_id = await _admin(client, session_factory)
    user_id = await _create_user(session_factory, UserStatus.PENDING_APPROVAL)

    body = (await client.post(ACTION_PATH.format(user_id, "approve"))).json()

    assert body["approved_by"] == str(admin_id)
    assert body["approved_at"] is not None


async def test_reject_does_not_write_approved_by(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`reject` **không** đặt `approved_*` — hai cột ấy là "ai nhận vào", không
    phải "ai đã bấm nút"."""
    await _admin(client, session_factory)
    user_id = await _create_user(session_factory, UserStatus.PENDING_APPROVAL)

    body = (await client.post(ACTION_PATH.format(user_id, "reject"))).json()

    assert body["status"] == UserStatus.REJECTED.value
    assert body["approved_by"] is None
    assert body["approved_at"] is None


async def test_approve_twice_writes_no_extra_row(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Đích đã đạt ⇒ `200` và **không** có dòng sổ thứ hai (xem docstring `admin.py`)."""
    await _admin(client, session_factory)
    user_id = await _create_user(session_factory, UserStatus.PENDING_APPROVAL)

    first = await client.post(ACTION_PATH.format(user_id, "approve"))
    again = await client.post(ACTION_PATH.format(user_id, "approve"))

    assert first.status_code == 200
    assert again.status_code == 200
    assert len(await _audit(session_factory)) == 1


# ══════════════════ §11.1 — mũi tên nào có, mũi tên nào không ═══════════════


@pytest.mark.parametrize(
    ("initial_status", "action", "final_status"),
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
async def test_existing_arrow_is_allowed(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    initial_status: UserStatus,
    action: str,
    final_status: UserStatus,
) -> None:
    await _admin(client, session_factory)
    user_id = await _create_user(session_factory, initial_status)

    resp = await client.post(ACTION_PATH.format(user_id, action))

    assert resp.status_code == 200, resp.text
    assert await _status_in_db(session_factory, user_id) is final_status


@pytest.mark.parametrize(
    ("initial_status", "action"),
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
async def test_missing_arrow_is_409_and_writes_no_ledger(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    initial_status: UserStatus,
    action: str,
) -> None:
    await _admin(client, session_factory)
    user_id = await _create_user(session_factory, initial_status)

    resp = await client.post(ACTION_PATH.format(user_id, action))

    assert resp.status_code == 409, resp.text
    error = resp.json()["error"]
    assert error["code"] == ApiErrorCode.INVALID_STATUS_TRANSITION
    assert error["details"]["status"] == initial_status.value
    assert await _status_in_db(session_factory, user_id) is initial_status
    assert await _audit(session_factory) == []


async def test_unknown_action_is_422_not_500(
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
    user_id = await _create_user(session_factory)

    resp = await client.post(ACTION_PATH.format(user_id, "delete"))

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == ApiErrorCode.VALIDATION_ERROR
    assert await _audit(session_factory) == []


async def test_missing_user_is_404_user_not_found(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _admin(client, session_factory)

    resp = await client.post(ACTION_PATH.format(uuid.uuid4(), "approve"))

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == ApiErrorCode.USER_NOT_FOUND


# ═══════ B-141 (NQ-61) và §11.3 — ba nút bấm, ba cách xử lý phiên ═══════════


async def test_approve_sets_user_cutoff_but_keeps_refresh_family(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: _FakeRedis,
) -> None:
    """B-141/NQ-61: **nửa Redis** của §11.3, không phải cả hai nửa.

    Mốc `bl:user:` giết access token cũ (cửa sổ 15 phút đóng ngay), nhưng
    refresh family còn sống nên `/auth/refresh` đổi được ra một cookie phiên
    mang `status='active'` — người dùng không phải gõ lại mật khẩu cho một tin
    vui. Đây là phép kiểm ngược của chính quyết định ấy: nếu ai đó đổi sang
    `revoke_all_sessions` thì `revoked_at` dưới đây thôi `None` và test đỏ.
    """
    await _admin(client, session_factory)
    user_id = await _create_user(session_factory, UserStatus.PENDING_APPROVAL)
    async with session_factory() as session:
        await RefreshTokenRepository(session).issue_new_family(
            user_id=user_id, ttl_days=30, user_agent=None
        )
        await session.commit()

    await client.post(ACTION_PATH.format(user_id, "approve"))

    assert user_key(user_id) in fake_redis.set_calls
    async with session_factory() as session:
        alive = (
            await session.execute(
                select(func.count())
                .select_from(RefreshToken)
                .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            )
        ).scalar_one()
    assert alive == 1, "duyet KHONG duoc thu hoi refresh family (B-141/NQ-61)"


async def test_suspend_revokes_both_halves_like_password_change(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: _FakeRedis,
) -> None:
    """§11.3: *"Admin suspend → như đổi mật khẩu"* — mốc `bl:user:` **và**
    revoke mọi refresh family."""
    await _admin(client, session_factory)
    user_id = await _create_user(session_factory, UserStatus.ACTIVE)
    async with session_factory() as session:
        await RefreshTokenRepository(session).issue_new_family(
            user_id=user_id, ttl_days=30, user_agent=None
        )
        await session.commit()

    await client.post(ACTION_PATH.format(user_id, "suspend"))

    assert user_key(user_id) in fake_redis.set_calls
    async with session_factory() as session:
        alive = (
            await session.execute(
                select(func.count())
                .select_from(RefreshToken)
                .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            )
        ).scalar_one()
    assert alive == 0, "suspend PHAI thu hoi refresh family (§11.3)"


async def test_reject_revokes_nothing(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: _FakeRedis,
) -> None:
    """§11.3 liệt đúng ba nhánh thu hồi và `rejected` không nằm trong đó (T-2.7).

    Không cần: mọi route trả `403 ACCOUNT_DISABLED` cho trạng thái ấy ngay từ
    claim, nên thu hồi thêm chỉ là một lượt ghi Redis không ai đọc.
    """
    await _admin(client, session_factory)
    user_id = await _create_user(session_factory, UserStatus.PENDING_APPROVAL)

    await client.post(ACTION_PATH.format(user_id, "reject"))

    assert user_key(user_id) not in fake_redis.set_calls


# ═══════════════════════ GET /admin/users — lọc theo status ═════════════════


async def test_status_filter_returns_only_that_group(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Màn "Duyệt user" của §16.3 là đúng một tham số của endpoint này."""
    await _admin(client, session_factory)
    pending = await _create_user(session_factory, UserStatus.PENDING_APPROVAL)
    await _create_user(session_factory, UserStatus.ACTIVE)

    resp = await client.get(USERS_PATH, params={"status": UserStatus.PENDING_APPROVAL.value})

    assert resp.status_code == 200, resp.text
    ids = [u["id"] for u in resp.json()["users"]]
    assert ids == [str(pending)]


async def test_no_filter_returns_whole_table(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    admin_id = await _admin(client, session_factory)
    a = await _create_user(session_factory, UserStatus.PENDING_APPROVAL)
    b = await _create_user(session_factory, UserStatus.SUSPENDED)

    resp = await client.get(USERS_PATH)

    ids = {u["id"] for u in resp.json()["users"]}
    assert {str(admin_id), str(a), str(b)} <= ids


async def test_unknown_status_is_422_not_empty_list(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Một bộ lọc gõ sai mà trả `[]` sẽ đọc y hệt "không còn ai chờ duyệt"."""
    await _admin(client, session_factory)

    resp = await client.get(USERS_PATH, params={"status": "khong-co-that"})

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == ApiErrorCode.VALIDATION_ERROR


async def test_soft_deleted_user_not_listed(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`deleted_at IS NULL` lọc **trong SQL** — §20, cùng lối `get_by_id`."""
    await _admin(client, session_factory)
    deleted = await _create_user(session_factory, UserStatus.ACTIVE)
    async with session_factory() as session:
        await session.execute(update(User).where(User.id == deleted).values(deleted_at=func.now()))
        await session.commit()

    resp = await client.get(USERS_PATH)

    assert str(deleted) not in {u["id"] for u in resp.json()["users"]}


async def test_list_does_not_leak_password_hash(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """§20 — màn admin hiện email, không hiện thứ đăng nhập được bằng."""
    await _admin(client, session_factory)
    await _create_user(session_factory)

    resp = await client.get(USERS_PATH)

    assert "password" not in resp.text.lower()


# ═══════════════════ PATCH /admin/users/{id} — tier & ghi đè ════════════════


async def test_change_tier_and_write_audit(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    admin_id = await _admin(client, session_factory)
    user_id = await _create_user(session_factory, UserStatus.ACTIVE)

    resp = await client.patch(USER_PATH.format(user_id), json={"tier_name": "trusted"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["tier_name"] == "trusted"
    rows = await _audit(session_factory)
    assert len(rows) == 1
    assert rows[0].actor_id == admin_id
    assert rows[0].action == AuditAction.USER_UPDATE
    assert rows[0].details == {"changed": {"tier_name": {"from": "free", "to": "trusted"}}}


async def test_nonexistent_tier_is_400_not_500(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Khoá ngoại `users.tier_name → tiers.name` không được phép nổi lên thành 500."""
    await _admin(client, session_factory)
    user_id = await _create_user(session_factory, UserStatus.ACTIVE)

    resp = await client.patch(USER_PATH.format(user_id), json={"tier_name": "khong-co-that"})

    assert resp.status_code == 400
    assert resp.json()["error"]["details"]["tier_name"] == "khong-co-that"
    assert await _audit(session_factory) == []


async def test_tier_name_null_is_400(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Cột `NOT NULL` ⇒ `null` không có nghĩa nào; im lặng bỏ qua là tệ hơn."""
    await _admin(client, session_factory)
    user_id = await _create_user(session_factory, UserStatus.ACTIVE)

    resp = await client.patch(USER_PATH.format(user_id), json={"tier_name": None})

    assert resp.status_code == 400


async def test_enable_can_execute_skills_via_limit_override(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """§16.3 *"bật `can_execute_skills`"* đi qua `limit_override`, không qua một
    trường thứ ba — xem docstring `UpdateUserRequest`."""
    await _admin(client, session_factory)
    user_id = await _create_user(session_factory, UserStatus.ACTIVE)

    resp = await client.patch(
        USER_PATH.format(user_id), json={"limit_override": {"can_execute_skills": True}}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["limit_override_json"] == {"can_execute_skills": True}


async def test_limit_override_null_clears_all_overrides(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`null` = "quay về đúng hạn mức của tier"; vắng mặt = "đừng đụng tới"."""
    await _admin(client, session_factory)
    user_id = await _create_user(session_factory, UserStatus.ACTIVE)
    await client.patch(USER_PATH.format(user_id), json={"limit_override": {"max_upload_mb": 50}})

    resp = await client.patch(USER_PATH.format(user_id), json={"limit_override": None})

    assert resp.json()["limit_override_json"] is None


async def test_no_fields_sent_changes_nothing_and_writes_no_ledger(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Body rỗng cư xử như `GET` — cùng lối `PATCH /conversations/{id}` (T-1.13)."""
    await _admin(client, session_factory)
    user_id = await _create_user(session_factory, UserStatus.ACTIVE)

    resp = await client.patch(USER_PATH.format(user_id), json={})

    assert resp.status_code == 200
    assert resp.json()["tier_name"] == "free"
    assert await _audit(session_factory) == []


async def test_limit_override_unknown_key_is_400(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`merge_override` sẽ **im lặng** bỏ qua khoá này lúc đọc — nên phải kêu lúc ghi."""
    await _admin(client, session_factory)
    user_id = await _create_user(session_factory, UserStatus.ACTIVE)

    resp = await client.patch(
        USER_PATH.format(user_id), json={"limit_override": {"khong_co_truong_nay": 1}}
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["details"]["unknown"] == ["khong_co_truong_nay"]


async def test_limit_override_wrong_type_is_400(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`merge_override` sẽ vứt **cả** bản ghi đè lúc đọc — một `200` ở đây là nói dối."""
    await _admin(client, session_factory)
    user_id = await _create_user(session_factory, UserStatus.ACTIVE)

    resp = await client.patch(
        USER_PATH.format(user_id), json={"limit_override": {"max_upload_mb": "rat-nhieu"}}
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["details"]["field"] == "max_upload_mb"


async def test_unknown_field_in_body_is_422(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`extra="forbid"`: gõ `tier` thay vì `tier_name` phải đọc được, không im lặng."""
    await _admin(client, session_factory)
    user_id = await _create_user(session_factory, UserStatus.ACTIVE)

    resp = await client.patch(USER_PATH.format(user_id), json={"tier": "trusted"})

    assert resp.status_code == 422


# ═════════════════ DoD dòng 3 — /admin/usage tách hai nhóm (C16) ════════════


async def _write_ledger(
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


async def test_usage_returns_two_separate_groups(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """DoD dòng 3: *"`/admin/usage` trả hai nhóm riêng biệt (C16)"*.

    Hai dòng sổ cùng một người, cùng một ngày, khác `cost_confidence`. Nếu hai
    cột bị trộn thì `metered.cost_usd` sẽ là `0.3` thay vì `0.1` — tức đúng con
    số mà C16 nói làm bảng chi phí vô nghĩa.
    """
    await _admin(client, session_factory)
    user_id = await _create_user(session_factory, UserStatus.ACTIVE)
    await _write_ledger(
        session_factory,
        user_id=user_id,
        model_id="model-do-duoc",
        cost="0.1",
        confidence=CostConfidence.EXACT,
    )
    await _write_ledger(
        session_factory,
        user_id=user_id,
        model_id="model-uoc-luong",
        cost="0.2",
        confidence=CostConfidence.LOW,
    )

    resp = await client.get(USAGE_PATH)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert Decimal(body["totals"]["metered"]["cost_usd"]) == Decimal("0.1")
    assert Decimal(body["totals"]["unmetered"]["cost_usd"]) == Decimal("0.2")
    assert body["totals"]["metered"]["events"] == 1
    assert body["totals"]["unmetered"]["events"] == 1
    # Không có trường nào cộng hai cột lại — xem docstring `MeteredSplit`.
    assert "tong" not in body["totals"]
    assert "total" not in body["totals"]

    by_model = {h["key"]: h for h in body["by_model"]}
    assert Decimal(by_model["model-do-duoc"]["metered"]["cost_usd"]) == Decimal("0.1")
    assert Decimal(by_model["model-do-duoc"]["unmetered"]["cost_usd"]) == Decimal("0")
    assert Decimal(by_model["model-uoc-luong"]["unmetered"]["cost_usd"]) == Decimal("0.2")
    assert Decimal(by_model["model-uoc-luong"]["metered"]["cost_usd"]) == Decimal("0")

    by_user = {h["key"]: h for h in body["by_user"]}
    assert Decimal(by_user[str(user_id)]["metered"]["cost_usd"]) == Decimal("0.1")
    assert Decimal(by_user[str(user_id)]["unmetered"]["cost_usd"]) == Decimal("0.2")
    assert by_user[str(user_id)]["label"] is not None

    assert len(body["by_day"]) == 1
    assert Decimal(body["by_day"][0]["metered"]["cost_usd"]) == Decimal("0.1")
    # Khoá của trục "theo ngày" là một NGÀY, không phải `"... 00:00:00"` — một
    # chuỗi mà mọi chỗ hiển thị sẽ phải cắt lại (xem `usage_events._khoa`).
    assert body["by_day"][0]["key"] == datetime.now(UTC).date().isoformat()


async def test_usage_also_splits_by_whose_money(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Trục thứ tư: §10.5 nói khoản `byok` **không** phải tiền của người vận hành."""
    await _admin(client, session_factory)
    user_id = await _create_user(session_factory, UserStatus.ACTIVE)
    await _write_ledger(
        session_factory,
        user_id=user_id,
        model_id="m",
        cost="0.5",
        confidence=CostConfidence.EXACT,
        key_source=KeySource.SYSTEM,
    )
    await _write_ledger(
        session_factory,
        user_id=user_id,
        model_id="m",
        cost="9.0",
        confidence=CostConfidence.EXACT,
        key_source=KeySource.BYOK,
    )

    body = (await client.get(USAGE_PATH)).json()

    by_source = {h["key"]: h for h in body["by_key_source"]}
    assert Decimal(by_source["system"]["metered"]["cost_usd"]) == Decimal("0.5")
    assert Decimal(by_source["byok"]["metered"]["cost_usd"]) == Decimal("9.0")


# ═══════════ T-2.19 / B-178 — `?key_source=` lọc BA trục, không phải bốn ════


async def _two_sources(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> uuid.UUID:
    """Một user, hai dòng sổ: `0.5` tiền hệ thống và `9.0` tiền của chính họ."""
    await _admin(client, session_factory)
    user_id = await _create_user(session_factory, UserStatus.ACTIVE)
    for cost, source in (("0.5", KeySource.SYSTEM), ("9.0", KeySource.BYOK)):
        await _write_ledger(
            session_factory,
            user_id=user_id,
            model_id="m",
            cost=cost,
            confidence=CostConfidence.EXACT,
            key_source=source,
        )
    return user_id


async def test_usage_system_filter_returns_the_real_bill(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """B-178: `?key_source=system` ⇒ `totals` là con số S13 đem đối chiếu được.

    Không lọc thì tổng là `9.5` — hoá đơn của người vận hành **cộng thêm** tiền
    của người khác (§10.5). Đúng con số mà B-178 ghi lại, nên nó được đo ở đây
    cạnh con số đã lọc chứ không phải ở một test khác: hai phép đo rời nhau thì
    ngày một trong hai đổi, không ai thấy chúng lệch.
    """
    user_id = await _two_sources(client, session_factory)

    default_window = (await client.get(USAGE_PATH)).json()
    assert Decimal(default_window["totals"]["metered"]["cost_usd"]) == Decimal("9.5")
    assert default_window["key_source"] is None

    resp = await client.get(USAGE_PATH, params={"key_source": "system"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["key_source"] == "system"
    assert Decimal(body["totals"]["metered"]["cost_usd"]) == Decimal("0.5")
    # Cả BA trục hoá đơn, không riêng `totals`: một bảng "theo model" còn `9.5`
    # trong khi tổng đã là `0.5` là một màn hình tự mâu thuẫn với chính nó.
    assert Decimal(body["by_day"][0]["metered"]["cost_usd"]) == Decimal("0.5")
    assert Decimal(body["by_model"][0]["metered"]["cost_usd"]) == Decimal("0.5")
    by_user = {h["key"]: h for h in body["by_user"]}
    assert Decimal(by_user[str(user_id)]["metered"]["cost_usd"]) == Decimal("0.5")


async def test_usage_filter_does_not_touch_by_source_axis(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`by_key_source` vẫn đủ **cả hai** nguồn kể cả khi ba trục kia đã bị lọc.

    Đây là điều kiện để mặc định `system` của màn "Chi phí" không thành một
    kiểu nói dối mới: lọc mà xoá sạch dấu vết phần bị loại ra thì người vận
    hành không còn đường nào biết là có phần ấy. Xem `admin_by_key_source`.
    """
    await _two_sources(client, session_factory)

    body = (await client.get(USAGE_PATH, params={"key_source": "system"})).json()

    by_source = {h["key"]: h for h in body["by_key_source"]}
    assert set(by_source) == {"system", "byok"}
    assert Decimal(by_source["byok"]["metered"]["cost_usd"]) == Decimal("9.0")


async def test_usage_byok_filter_returns_exactly_the_non_system_part(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Chiều ngược lại — nút "BYOK" của màn Chi phí đi qua đúng đường này."""
    await _two_sources(client, session_factory)

    body = (await client.get(USAGE_PATH, params={"key_source": "byok"})).json()

    assert body["key_source"] == "byok"
    assert Decimal(body["totals"]["metered"]["cost_usd"]) == Decimal("9.0")


async def test_usage_unknown_key_source_is_not_free_text(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`?key_source=abc` ⇒ `422`, không phải im lặng trả về "mọi nguồn".

    Cùng lý lẽ `?status=abc` của `list_users`: một bộ lọc gõ sai mà vẫn trả
    `200` sẽ đọc y hệt một hoá đơn phình to, và không có gì trên màn hình nói
    rằng bộ lọc đã bị bỏ qua.
    """
    await _admin(client, session_factory)

    resp = await client.get(USAGE_PATH, params={"key_source": "abc"})

    assert resp.status_code == 422


async def test_usage_skips_rows_outside_window(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Biên nửa mở `[since, until)` — hai cửa sổ liền nhau không đếm chung một dòng."""
    await _admin(client, session_factory)
    user_id = await _create_user(session_factory, UserStatus.ACTIVE)
    await _write_ledger(
        session_factory,
        user_id=user_id,
        model_id="m",
        cost="0.1",
        confidence=CostConfidence.EXACT,
    )

    now = datetime.now(UTC)
    resp = await client.get(
        USAGE_PATH,
        params={
            "since": (now - timedelta(days=30)).isoformat(),
            "until": (now - timedelta(days=29)).isoformat(),
        },
    )

    body = resp.json()
    assert body["by_day"] == []
    assert Decimal(body["totals"]["metered"]["cost_usd"]) == Decimal("0")


async def test_usage_since_after_until_is_400(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _admin(client, session_factory)
    now = datetime.now(UTC)

    resp = await client.get(
        USAGE_PATH,
        params={"since": now.isoformat(), "until": (now - timedelta(days=1)).isoformat()},
    )

    assert resp.status_code == 400


# ═══════════════════════ POST /admin/catalog/reload (B-34) ══════════════════


async def test_reload_catalog_writes_audit(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """B-34 đóng: endpoint vẫn làm đúng việc cũ, nay có khoá và có sổ."""
    admin_id = await _admin(client, session_factory)

    resp = await client.post(RELOAD_PATH)

    assert resp.status_code == 200, resp.text
    assert resp.json()["models"] > 0
    rows = await _audit(session_factory)
    assert len(rows) == 1
    assert rows[0].actor_id == admin_id
    assert rows[0].action == AuditAction.CATALOG_RELOAD
    assert rows[0].target_id is None
    assert rows[0].details["models"] == resp.json()["models"]


# ════════════════════════════ hai endpoint ĐỌC không ghi sổ ═════════════════


async def test_read_endpoints_leave_no_audit_rows(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """§20 nói "mọi **hành động** admin" — mở một màn hình không phải hành động."""
    await _admin(client, session_factory)

    await client.get(USERS_PATH)
    await client.get(USAGE_PATH)

    assert await _audit(session_factory) == []


# ═══════════════ cột `ip INET` — hai đường vào, hai kết cục ═════════════════


async def test_writes_real_ip_into_inet_column(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """§16.3 màn "Audit log" hỏi *"ai, lúc nào, làm gì, với ai"* — `ip` là phần
    trả lời cho câu thứ nhất khi tên người chưa đủ.

    `X-Real-IP` là header Nginx đặt (`$remote_addr`), cùng nguồn mà
    `core/ratelimit.py` đã tin — xem docstring của module đó cho lý do tin được.
    """
    await _admin(client, session_factory)
    user_id = await _create_user(session_factory, UserStatus.PENDING_APPROVAL)

    await client.post(ACTION_PATH.format(user_id, "approve"), headers={"X-Real-IP": "203.0.113.7"})

    rows = await _audit(session_factory)
    assert rows[0].ip == ip_address("203.0.113.7")


async def test_unreadable_ip_is_null_and_does_not_break_the_action(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`client_ip` trả `"unknown"` khi không có IP nào — một giá trị hợp lý cho
    một khoá Redis và **không hợp lệ** cho cột `INET`.

    Phép kiểm ngược của `_valid_ip`: bỏ nó đi thì Postgres từ chối `INSERT`,
    và vì dòng sổ nằm cùng transaction với việc nó mô tả (§20), **cả lần duyệt**
    đổ theo. Tức một chi tiết ghi log làm hỏng chính hành động admin.
    """
    monkeypatch.setattr("app.api.v1.admin.client_ip", lambda _request: "unknown")
    await _admin(client, session_factory)
    user_id = await _create_user(session_factory, UserStatus.PENDING_APPROVAL)

    resp = await client.post(ACTION_PATH.format(user_id, "approve"))

    assert resp.status_code == 200, resp.text
    rows = await _audit(session_factory)
    assert len(rows) == 1
    assert rows[0].ip is None


# ══════════ hai admin bấm cùng lúc — phép kiểm ngược của `WHERE status` ═════


async def test_two_admins_clicking_at_once_only_one_wins(
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
    user_id = await _create_user(session_factory, UserStatus.PENDING_APPROVAL)
    original = UserRepository.set_status

    async def cut_in(
        self: UserRepository,
        user_uuid: uuid.UUID,
        *,
        from_status: UserStatus,
        to_status: UserStatus,
        approved_by: uuid.UUID | None = None,
    ) -> User | None:
        async with session_factory() as other_session:
            await other_session.execute(
                update(User).where(User.id == user_uuid).values(status=UserStatus.REJECTED)
            )
            await other_session.commit()
        return await original(
            self, user_uuid, from_status=from_status, to_status=to_status, approved_by=approved_by
        )

    monkeypatch.setattr(UserRepository, "set_status", cut_in)

    resp = await client.post(ACTION_PATH.format(user_id, "approve"))

    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == ApiErrorCode.INVALID_STATUS_TRANSITION
    assert await _status_in_db(session_factory, user_id) is not UserStatus.ACTIVE
    assert await _audit(session_factory) == []


async def test_patch_resending_current_value_writes_no_ledger(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Lưu form lần hai mà không sửa gì ⇒ `200` và **không** dòng sổ nào.

    Cùng luật với nhánh "đích đã đạt" của `change_user_status` — xem docstring
    `update_user`. Không có nó thì sổ audit dài ra bằng số lần bấm Lưu chứ
    không bằng số thay đổi, và một sổ như thế thì không ai đọc nữa.
    """
    await _admin(client, session_factory)
    user_id = await _create_user(session_factory, UserStatus.ACTIVE)
    await client.patch(USER_PATH.format(user_id), json={"tier_name": "trusted"})

    resp = await client.patch(USER_PATH.format(user_id), json={"tier_name": "trusted"})

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


async def test_tier_list_has_nine_columns_sorted_by_name(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Hai tier của migration 0001, sắp theo tên, đủ chín cột của §10.4."""
    await _admin(client, session_factory)

    resp = await client.get(TIERS_PATH)

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


async def test_tier_list_writes_no_ledger(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Đọc không phải một hành động — §20, "Việc cần làm" dòng 4 của task."""
    await _admin(client, session_factory)

    await client.get(TIERS_PATH)

    assert await _audit(session_factory) == []


# ═════════════════ PATCH /admin/tiers/{name} — §10.4, §16.3 ════════════════


async def test_change_tier_limits_writes_one_audit_row(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Nửa "đổi" của §10.4 — một dòng sổ, `target_id` là **tên tier**."""
    admin_id = await _admin(client, session_factory)

    resp = await client.patch(TIER_PATH.format("free"), json={"limit_5h_usd": "1.2500"})

    assert resp.status_code == 200, resp.text
    assert Decimal(resp.json()["limit_5h_usd"]) == Decimal("1.2500")

    rows = await _audit(session_factory)
    assert len(rows) == 1
    assert rows[0].actor_id == admin_id
    assert rows[0].action == AuditAction.TIER_UPDATE
    assert rows[0].target_type == TARGET_TIER
    assert rows[0].target_id == "free"
    assert rows[0].details == {"changed": {"limit_5h_usd": {"from": "0.5000", "to": "1.2500"}}}


async def test_money_in_ledger_row_is_a_STRING_not_float(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`Decimal` đi vào JSONB phải qua `_json_safe` — nếu không, cả `PATCH` đỏ.

    Ca này là phép kiểm ngược của chính nó: bỏ `_json_safe` đi thì bộ mã hoá
    JSON của cột `details` ném `TypeError` **trong cùng transaction** với câu
    `UPDATE`, nên hạn mức cũng không đổi. Một `float` thì lặng lẽ hơn và tệ hơn
    — sổ ghi `0.5000000000000001` đúng lúc người ta mở sổ ra để đối chiếu tiền.
    """
    await _admin(client, session_factory)

    await client.patch(TIER_PATH.format("free"), json={"limit_7d_usd": "9.5000"})

    diff = (await _audit(session_factory))[0].details
    assert diff is not None
    assert diff["changed"]["limit_7d_usd"] == {"from": "3.0000", "to": "9.5000"}
    assert isinstance(diff["changed"]["limit_7d_usd"]["to"], str)


async def test_change_many_columns_at_once_writes_exactly_one_row(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Một lần bấm Lưu là một dòng sổ, dù nó đổi bốn cột."""
    await _admin(client, session_factory)

    resp = await client.patch(
        TIER_PATH.format("trusted"),
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

    rows = await _audit(session_factory)
    assert len(rows) == 1
    assert rows[0].details is not None
    assert set(rows[0].details["changed"]) == {
        "can_execute_skills",
        "can_use_web",
        "max_attachments",
        "allowed_model_tags",
    }


async def test_resending_current_value_writes_no_ledger(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Lưu cả form mà không sửa gì ⇒ `200`, không dòng sổ nào — cùng `update_user`."""
    await _admin(client, session_factory)

    resp = await client.patch(TIER_PATH.format("free"), json={"limit_5h_usd": "0.5000"})

    assert resp.status_code == 200, resp.text
    assert await _audit(session_factory) == []


async def test_empty_body_behaves_like_GET(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`PATCH {}` không chạy câu UPDATE nào nhưng vẫn trả hàng hiện tại."""
    await _admin(client, session_factory)

    resp = await client.patch(TIER_PATH.format("free"), json={})

    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "free"
    assert await _audit(session_factory) == []


async def test_nonexistent_tier_is_404(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Mã riêng, không phải `NOT_FOUND` chung — xem `ApiErrorCode.TIER_NOT_FOUND`."""
    await _admin(client, session_factory)

    resp = await client.patch(TIER_PATH.format("khong-co-that"), json={"max_upload_mb": 1})

    assert resp.status_code == 404, resp.text
    error = resp.json()["error"]
    assert error["code"] == ApiErrorCode.TIER_NOT_FOUND
    assert error["details"]["name"] == "khong-co-that"
    assert await _audit(session_factory) == []


async def test_null_for_a_NOT_NULL_column_is_400(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`null` không có nghĩa nào cho một cột `NOT NULL` — 400, không bỏ qua im lặng."""
    await _admin(client, session_factory)

    resp = await client.patch(TIER_PATH.format("free"), json={"can_use_web": None})

    assert resp.status_code == 400, resp.text
    error = resp.json()["error"]
    assert error["code"] == ApiErrorCode.BAD_REQUEST
    assert error["details"]["fields"] == ["can_use_web"]


@pytest.mark.parametrize("key", ["is_default", "name", "limit_5h"])
async def test_non_editable_key_is_422(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], key: str
) -> None:
    """`extra="forbid"`: `is_default` (B-152), `name` (khoá chính), và một lần gõ nhầm.

    Cả ba đi cùng một đường ra vì với người gọi chúng là cùng một câu chuyện —
    "trường này không sửa được ở đây". Ngả kia (`200` rồi bỏ qua) là đúng thứ
    "lệch trong im lặng" mà `update_user` đã từ chối.
    """
    await _admin(client, session_factory)

    resp = await client.patch(TIER_PATH.format("free"), json={key: "x"})

    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == ApiErrorCode.VALIDATION_ERROR


async def test_negative_limit_is_rejected(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`ge=0`: một `limit_5h_usd` âm khoá sạch tier mà không ai đọc ra lý do."""
    await _admin(client, session_factory)

    resp = await client.patch(TIER_PATH.format("free"), json={"limit_5h_usd": "-1"})

    assert resp.status_code == 422, resp.text


def test_PATCH_eight_fields_equal_OVERRIDABLE_FIELDS() -> None:
    """Hai tập ấy bằng nhau **không phải tình cờ** — xem docstring `UpdateTierRequest`.

    Ngày `EffectiveLimits` mọc thêm một trường mà body của `PATCH /admin/tiers`
    quên, đây là chỗ nó tự khai — thay vì một ô nhập biến mất khỏi màn hình
    admin mà không ai để ý.
    """
    assert set(UpdateTierRequest.model_fields) == OVERRIDABLE_FIELDS


async def test_change_tier_does_NOT_evict_cache_and_Postgres_sees_it_now(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], fake_redis: _FakeRedis
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
    user_id = await _create_user(session_factory, UserStatus.ACTIVE)

    await client.patch(TIER_PATH.format("free"), json={"limit_5h_usd": "7.0000"})

    assert fake_redis.deleted == []
    async with session_factory() as session:
        observed = await TierRepository(session).get_for_user(user_id)
    assert observed is not None
    assert observed.tier.name == "free"
    assert observed.tier.limit_5h_usd == Decimal("7.0000")


# ══════════════════ GET /admin/system — §16.3, §21.2, DoD dòng 4 ═══════════


def _fake_health(redis_ok: bool = True) -> dict[str, CheckResult]:
    """Kết quả `run_checks()` giả — năm mục như `app/core/health_checks.py`."""
    return {
        name: CheckResult(ok=True, latency_ms=1)
        for name in ("postgres", "minio", "litellm", "ninerouter")
    } | {
        "redis": CheckResult(
            ok=redis_ok,
            latency_ms=2000,
            error=None if redis_ok else "Error 111 connecting to redis:6379.",
        )
    }


@pytest.fixture
def fake_system(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hạ tầng giả cho màn "Hệ thống": `run_checks` và `queue_depth` đều là mock.

    Cả hai mở kết nối **ra ngoài** (năm service, và một pool arq riêng), thứ mà
    một bộ test đơn vị không có và không nên có. `count_streaming` thì **không**
    bị giả: nó đi đúng Postgres thật của bộ test, vì con số ấy là thứ duy nhất
    ở đây có thể sai một cách thú vị.
    """
    monkeypatch.setattr("app.api.v1.admin.run_checks", lambda: _returning(_fake_health()))
    monkeypatch.setattr("app.api.v1.admin.queue_depth", lambda: _returning(3))


async def _returning(value: Any) -> Any:
    return value


async def test_system_screen_returns_all_four_boxes(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    fake_system: None,
) -> None:
    """DoD dòng 4: `queue_depth`, `streams_dang_chay`, `version`, `health`.

    T-3.12 (B-192) thêm ô thứ năm, `health_checked_at`: kết quả healthcheck
    nay có thể cũ vài giây, và màn hình phải in ra nó cũ tới đâu.
    """
    await _admin(client, session_factory)

    resp = await client.get(SYSTEM_PATH)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {
        "queue_depth",
        "streams_dang_chay",
        "version",
        "health",
        "health_checked_at",
    }
    assert body["queue_depth"] == 3
    assert body["version"] == APP_VERSION
    assert set(body["health"]) == {"postgres", "redis", "minio", "litellm", "ninerouter"}


async def test_counts_running_streams_correctly(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    fake_system: None,
) -> None:
    """Đếm `streaming`, **không** đếm `queued` — §16.3 tách hai chỉ số cạnh nhau.

    Gộp `queued` vào đây là đếm cùng một job hai lần trên cùng một màn hình:
    nó đã nằm trong `queue_depth` rồi.
    """
    await _admin(client, session_factory)
    user_id = await _create_user(session_factory, UserStatus.ACTIVE)
    async with session_factory() as session:
        conv = Conversation(user_id=user_id)
        session.add(conv)
        await session.flush()
        for status in (
            MessageStatus.STREAMING,
            MessageStatus.STREAMING,
            MessageStatus.QUEUED,
            MessageStatus.COMPLETED,
        ):
            session.add(Message(conversation_id=conv.id, role=MessageRole.ASSISTANT, status=status))
        await session.commit()

    resp = await client.get(SYSTEM_PATH)

    assert resp.json()["streams_dang_chay"] == 2


async def test_dead_redis_still_answers_not_500(
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

    monkeypatch.setattr(
        "app.api.v1.admin.run_checks", lambda: _returning(_fake_health(redis_ok=False))
    )
    monkeypatch.setattr("app.api.v1.admin.queue_depth", _no)

    resp = await client.get(SYSTEM_PATH)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["queue_depth"] is None
    assert body["streams_dang_chay"] == 0
    assert body["health"]["redis"]["ok"] is False
    assert "111" in body["health"]["redis"]["error"]


async def test_system_screen_writes_no_ledger(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    fake_system: None,
) -> None:
    await _admin(client, session_factory)

    await client.get(SYSTEM_PATH)

    assert await _audit(session_factory) == []


# ═══════════ GET /admin/audit-logs — §16.3, DoD dòng 3 ═════════════════════


async def test_reads_the_row_PATCH_just_wrote(
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
    await client.patch(TIER_PATH.format("free"), json={"limit_5h_usd": "2.0000"})

    resp = await client.get(AUDIT_PATH)

    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 1
    rows = items[0]
    assert rows["actor_id"] == str(admin_id)
    assert rows["actor_email"] == email
    assert rows["action"] == AuditAction.TIER_UPDATE.value
    assert rows["target_type"] == TARGET_TIER
    assert rows["target_id"] == "free"
    assert rows["details"]["changed"]["limit_5h_usd"]["to"] == "2.0000"
    assert rows["created_at"] is not None


async def test_action_filter_is_INSIDE_the_SQL(
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

    resp = await client.get(AUDIT_PATH, params={"action": "user.approve", "limit": 2})

    items = resp.json()["items"]
    assert len(items) == 2
    assert {d["action"] for d in items} == {AuditAction.USER_APPROVE.value}


async def test_actor_id_filter_is_inside_the_SQL(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Cùng hình dạng với `?action=`, trục khác: `?actor_id=` cũng lọc trước `LIMIT`."""
    admin_id = await _admin(client, session_factory)
    other_admin = await _create_user(session_factory, UserStatus.ACTIVE, role=UserRole.ADMIN)
    for _ in range(3):
        await _audit_row(session_factory, actor_id=admin_id, action=AuditAction.USER_APPROVE)
    for _ in range(2):
        await _audit_row(session_factory, actor_id=other_admin, action=AuditAction.USER_APPROVE)

    resp = await client.get(AUDIT_PATH, params={"actor_id": str(admin_id), "limit": 2})

    items = resp.json()["items"]
    assert len(items) == 2
    assert {d["actor_id"] for d in items} == {str(admin_id)}


async def test_time_window_is_half_open(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`[since, until)` — dòng nằm đúng ở mốc `until` **không** thuộc trang này.

    Nửa mở là thứ giữ cho hai trang chia theo ngày không đếm hai lần cùng một
    dòng; nó cũng là quy ước `GET /admin/usage` đã dùng, nên hai màn hình cạnh
    nhau không đọc cùng một khoảng theo hai kiểu.
    """
    admin_id = await _admin(client, session_factory)
    audit_row = await _audit_row(
        session_factory, actor_id=admin_id, action=AuditAction.USER_APPROVE
    )
    async with session_factory() as session:
        mark = (
            await session.execute(select(AuditLog.created_at).where(AuditLog.id == audit_row))
        ).scalar_one()

    inside = await client.get(AUDIT_PATH, params={"since": mark.isoformat()})
    outside = await client.get(AUDIT_PATH, params={"until": mark.isoformat()})

    assert [d["id"] for d in inside.json()["items"]] == [audit_row]
    assert outside.json()["items"] == []


async def test_since_after_until_is_400(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Cùng câu trả lời với `GET /admin/usage` cho cùng một lỗi của người gọi."""
    await _admin(client, session_factory)
    now = datetime.now(UTC)

    resp = await client.get(
        AUDIT_PATH,
        params={
            "since": now.isoformat(),
            "until": (now - timedelta(days=1)).isoformat(),
        },
    )

    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["code"] == ApiErrorCode.BAD_REQUEST


async def test_cursor_pagination_no_repeats_no_gaps(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Con trỏ `id`, mới nhất trước — hai trang phủ đúng năm dòng, không trùng nhau.

    Trang cuối chưa đầy ⇒ `next_cursor` là `null`, không mời client hỏi thêm
    một vòng chỉ để nhận về danh sách rỗng (cùng lối `GET /conversations`).
    """
    admin_id = await _admin(client, session_factory)
    code = [
        await _audit_row(session_factory, actor_id=admin_id, action=AuditAction.USER_APPROVE)
        for _ in range(5)
    ]

    page1 = (await client.get(AUDIT_PATH, params={"limit": 3})).json()
    page2 = (
        await client.get(AUDIT_PATH, params={"limit": 3, "before_id": page1["next_cursor"]})
    ).json()

    assert [d["id"] for d in page1["items"]] == list(reversed(code[2:]))
    assert page1["next_cursor"] == code[2]
    assert [d["id"] for d in page2["items"]] == list(reversed(code[:2]))
    assert page2["next_cursor"] is None


async def test_deleted_actor_keeps_ledger_row(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`ON DELETE SET NULL`: dòng sổ ở lại, chỉ mất con trỏ về người.

    `actor_email` khi ấy là `None`, giống hệt một hành động do cron sinh ra —
    và cả hai đều là câu trả lời đúng: *"không còn biết là ai"*.
    """
    await _admin(client, session_factory)
    await _audit_row(session_factory, actor_id=None, action=AuditAction.CATALOG_RELOAD)

    items = (await client.get(AUDIT_PATH)).json()["items"]

    assert len(items) == 1
    assert items[0]["actor_id"] is None
    assert items[0]["actor_email"] is None


async def test_unknown_action_is_422(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Một bộ lọc gõ sai mà trả `[]` sẽ đọc y hệt "sổ trống" — cùng lối `?status=`."""
    await _admin(client, session_factory)

    resp = await client.get(AUDIT_PATH, params={"action": "user.xoa-het"})

    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == ApiErrorCode.VALIDATION_ERROR


async def test_reading_ledger_writes_no_rows(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Một sổ mà mỗi lần mở lại dài thêm một dòng là một sổ tự lấp chính nó."""
    await _admin(client, session_factory)

    await client.get(AUDIT_PATH)
    await client.get(AUDIT_PATH)

    assert await _audit(session_factory) == []


# ═══════════ T-3.12 — mảnh backend của giao diện quản trị đầy đủ ═══════════
#
# Năm thứ, không endpoint mới nào: hai cột NQ-66 của `GET /admin/users`, trần
# cửa sổ của `GET /admin/usage` (B-175), "với ai" đọc được của sổ audit
# (B-191), bộ nhớ healthcheck của màn Hệ thống (B-192), và TTL hạn mức đi ra
# `GET /admin/tiers` để màn hình nói đúng con số của `.env`.


async def _conversation(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID, *, deleted: bool = False
) -> None:
    async with session_factory() as session:
        conv = Conversation(user_id=user_id)
        if deleted:
            conv.deleted_at = datetime.now(UTC)
        session.add(conv)
        await session.commit()


def _row(body: dict[str, Any], user_id: uuid.UUID) -> dict[str, Any]:
    return next(u for u in body["users"] if u["id"] == str(user_id))


async def test_user_without_conversations_gets_0_not_null(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """DoD dòng 2 của T-3.12: *"user chưa có hội thoại ⇒ cột trả `0`, không
    `null`"*. Một ô trống đọc như "không đo được"; sự thật là "chưa dùng".
    Chi tiêu cũng vậy — và đủ sáu chữ số thập phân như mọi `cost_usd`."""
    await _admin(client, session_factory)
    new_user = await _create_user(session_factory, UserStatus.ACTIVE)

    resp = await client.get(USERS_PATH)

    assert resp.status_code == 200, resp.text
    row = _row(resp.json(), new_user)
    assert row["conversation_count"] == 0
    assert row["spend_7d_usd"] == "0.000000"


async def test_conversation_count_and_7_day_spend_count_the_right_set(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """NQ-66 — hai cột đếm ĐÚNG tập, không chỉ "có một con số".

    * hội thoại xoá mềm **không** đếm;
    * chi tiêu là tiền **hệ thống** trong cửa sổ quota dài — BYOK (tiền của
      người dùng, §10.5) và dòng ngoài cửa sổ đều không cộng: đúng tập mà
      quota 7 ngày của người ấy đang cộng;
    * con số của người khác không lọt sang (GROUP BY đúng cột).
    """
    await _admin(client, session_factory)
    person = await _create_user(session_factory, UserStatus.ACTIVE)
    neighbor = await _create_user(session_factory, UserStatus.ACTIVE)
    await _conversation(session_factory, person)
    await _conversation(session_factory, person)
    await _conversation(session_factory, person, deleted=True)
    await _conversation(session_factory, neighbor)

    for cost, source in (
        ("0.1", KeySource.SYSTEM),
        ("0.2", KeySource.SYSTEM),
        ("5", KeySource.BYOK),
    ):
        await _write_ledger(
            session_factory,
            user_id=person,
            model_id="m",
            cost=cost,
            confidence=CostConfidence.EXACT,
            key_source=source,
        )
    await _write_ledger(
        session_factory, user_id=person, model_id="m", cost="9", confidence=CostConfidence.LOW
    )
    async with session_factory() as session:
        await session.execute(
            update(UsageEvent)
            .where(UsageEvent.user_id == person, UsageEvent.cost_usd == Decimal("9"))
            .values(created_at=datetime.now(UTC) - timedelta(days=8))
        )
        await session.commit()
    await _write_ledger(
        session_factory, user_id=neighbor, model_id="m", cost="0.7", confidence=CostConfidence.EXACT
    )

    body = (await client.get(USERS_PATH)).json()

    assert _row(body, person)["conversation_count"] == 2
    assert _row(body, person)["spend_7d_usd"] == "0.300000"
    assert _row(body, neighbor)["conversation_count"] == 1
    assert _row(body, neighbor)["spend_7d_usd"] == "0.700000"


async def test_user_list_is_ONE_statement_regardless_of_user_count(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
) -> None:
    """DoD dòng 1 của T-3.12 ở tầng test: số câu lệnh chạm `conversations`/
    `usage_events` khi đọc bảng Người dùng là **1**, không phải 1 + 2N.

    Bốn người, mỗi người có dữ liệu ở cả hai bảng — một vòng lặp N+1 sẽ cho
    ra 8 câu ở đây. Đếm bằng sự kiện `before_cursor_execute` của chính kết
    nối mà handler dùng (xem `_db_cua_test`), tức đếm thứ Postgres NHẬN, không
    phải thứ Python định gửi.
    """
    await _admin(client, session_factory)
    for _ in range(4):
        uid = await _create_user(session_factory, UserStatus.ACTIVE)
        await _conversation(session_factory, uid)
        await _write_ledger(
            session_factory, user_id=uid, model_id="m", cost="0.1", confidence=CostConfidence.EXACT
        )

    statements: list[str] = []

    def record_statement(_conn: Any, _cursor: Any, statement: str, *_: Any) -> None:
        statements.append(statement)

    event.listen(connection.sync_connection, "before_cursor_execute", record_statement)
    try:
        resp = await client.get(USERS_PATH)
    finally:
        event.remove(connection.sync_connection, "before_cursor_execute", record_statement)

    assert resp.status_code == 200, resp.text
    touching = [c for c in statements if "conversations" in c or "usage_events" in c]
    assert len(touching) == 1, touching
    assert "conversations" in touching[0]
    assert "usage_events" in touching[0]


async def test_status_change_endpoint_omits_two_aggregate_columns(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Hai cột NQ-66 chỉ có ở DANH SÁCH — `approve`/`PATCH` trả một hàng vừa
    đổi và không chạy câu gom nhóm nào (xem `AdminUserRowOut`)."""
    await _admin(client, session_factory)
    user_id = await _create_user(session_factory, UserStatus.PENDING_APPROVAL)

    body = (await client.post(ACTION_PATH.format(user_id, "approve"))).json()

    assert "conversation_count" not in body
    assert "spend_7d_usd" not in body


async def test_usage_window_over_cap_is_400(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """B-175 — trần `ADMIN_USAGE_MAX_WINDOW_DAYS`. Đúng trần thì qua, quá một
    giây thì `400` — hai ca ở hai bên biên, không phải một ca ở giữa."""
    await _admin(client, session_factory)
    until = datetime.now(UTC)
    max_window = timedelta(days=settings.ADMIN_USAGE_MAX_WINDOW_DAYS)

    at_cap = await client.get(
        USAGE_PATH,
        params={"since": (until - max_window).isoformat(), "until": until.isoformat()},
    )
    over_cap = await client.get(
        USAGE_PATH,
        params={
            "since": (until - max_window - timedelta(seconds=1)).isoformat(),
            "until": until.isoformat(),
        },
    )

    assert at_cap.status_code == 200, at_cap.text
    assert over_cap.status_code == 400, over_cap.text
    assert over_cap.json()["error"]["details"]["max_days"] == settings.ADMIN_USAGE_MAX_WINDOW_DAYS


async def test_tier_list_carries_limit_ttl_from_env(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """ "Có hiệu lực trong vòng N giây" — N là `TIER_CACHE_TTL_S`, đọc từ server
    chứ không chép tay vào `vi.json` (A3)."""
    await _admin(client, session_factory)

    body = (await client.get(TIERS_PATH)).json()

    assert body["limits_cache_ttl_s"] == settings.TIER_CACHE_TTL_S


async def test_system_screen_twice_in_a_row_probes_once(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B-192 — mở màn Hệ thống hai lần liên tiếp: HAI response, MỘT lượt đo,
    cùng một `health_checked_at`. `queue_depth` thì vẫn đọc tươi mỗi lần."""
    await _admin(client, session_factory)
    probe_calls: list[int] = []
    depths: list[int] = []

    async def counting() -> dict[str, CheckResult]:
        probe_calls.append(1)
        return _fake_health()

    async def queue_length() -> int:
        depths.append(1)
        return len(depths)

    monkeypatch.setattr("app.api.v1.admin.run_checks", counting)
    monkeypatch.setattr("app.api.v1.admin.queue_depth", queue_length)

    first = (await client.get(SYSTEM_PATH)).json()
    again = (await client.get(SYSTEM_PATH)).json()

    assert len(probe_calls) == 1
    assert again["health_checked_at"] == first["health_checked_at"]
    assert (first["queue_depth"], again["queue_depth"]) == (1, 2)


async def test_audit_resolves_whom_by_email(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """B-191 / DoD dòng 3 của T-3.12 ở tầng API: sau khi Duyệt, dòng sổ nói
    được cả "ai" lẫn "với ai" bằng chữ, không phải UUID."""
    admin_id = await _admin(client, session_factory)
    user_id = await _create_user(session_factory, UserStatus.PENDING_APPROVAL)
    async with session_factory() as session:
        await session.execute(
            update(User).where(User.id == user_id).values(display_name="Người Được Duyệt")
        )
        await session.commit()
        emails = dict(
            (
                await session.execute(
                    select(User.id, User.email).where(User.id.in_([admin_id, user_id]))
                )
            ).all()
        )
    await client.post(ACTION_PATH.format(user_id, "approve"))

    rows = (await client.get(AUDIT_PATH)).json()["items"][0]

    assert rows["actor_email"] == emails[admin_id]
    assert rows["target_type"] == TARGET_USER
    assert rows["target_email"] == emails[user_id]
    assert rows["target_display_name"] == "Người Được Duyệt"


async def test_audit_on_tier_joins_no_user(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Nhánh JOIN chỉ mở cho `target_type='users'` — tên tier đã đọc được, và
    một tên tier KHÔNG được thử ép kiểu sang UUID (câu sẽ nổ cả trang)."""
    await _admin(client, session_factory)
    await client.patch(TIER_PATH.format("free"), json={"limit_5h_usd": "2.0000"})

    resp = await client.get(AUDIT_PATH)

    assert resp.status_code == 200, resp.text
    rows = resp.json()["items"][0]
    assert rows["target_id"] == "free"
    assert rows["target_email"] is None
    assert rows["target_display_name"] is None


async def test_audit_deleted_user_no_longer_shows_email(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """T-HD7: *"Người đã xoá không còn tên"* — xoá mềm cũng tính. `target_id`
    vẫn còn nguyên để màn hình in 8 ký tự đầu mà tra log."""
    await _admin(client, session_factory)
    user_id = await _create_user(session_factory, UserStatus.PENDING_APPROVAL)
    await client.post(ACTION_PATH.format(user_id, "approve"))
    async with session_factory() as session:
        await session.execute(update(User).where(User.id == user_id).values(deleted_at=func.now()))
        await session.commit()

    rows = (await client.get(AUDIT_PATH)).json()["items"][0]

    assert rows["target_id"] == str(user_id)
    assert rows["target_email"] is None
    assert rows["target_display_name"] is None
