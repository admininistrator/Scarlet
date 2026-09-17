"""Máy trạng thái tài khoản + phân quyền (§11.1, UC-01) — T-2.7.

Ma trận **5 trạng thái × 4 hành động = 20 ca** của DoD nằm trong `MA_TRAN`
ngay dưới, một dòng một ô của bảng §11.1. Viết thành một bảng dữ liệu chứ
không 20 hàm rời: bảng trong kế hoạch có hình dạng gì thì bảng ở đây có đúng
hình dạng ấy, nên thêm một trạng thái thứ sáu là thêm bốn dòng — và quên mất
một ô là một chỗ trống nhìn thấy được.

**Hai hàng cuối của §11.1 (`rejected`, `suspended`) ghi "—" ở ba cột sau, và
"—" ở đó nghĩa là "không tới được vì không đăng nhập được" — KHÔNG phải "không
cần kiểm".** Test vẫn dựng token cho chúng bằng `encode_access_token`, vì một
token phát hành *trước* khi admin đổi trạng thái là thứ có thật: `rejected`
không nằm trong nhánh thu hồi nào của §11.3 (chỉ `suspend` mới "như đổi mật
khẩu"), nên một người bị từ chối vẫn cầm cookie phiên còn hạn tới 15 phút.
Ba cột ấy phải chặn được người đó, không thì "—" chỉ là một lời hứa.

Hạ tầng giống `test_auth.py`: `httpx.ASGITransport`, `session_scope()` trỏ về
đúng kết nối của test, Redis giả (autouse — từ T-2.4 **mọi** request mang
cookie phiên đều hỏi blacklist), arq giả (pool thật nối `redis:6379`, một host
chỉ phân giải được bên trong network `internal` của compose).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import LargeBinary, bindparam, text, update
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import catalog
from app.core.access_token import encode_access_token
from app.core.deps import SESSION_COOKIE_NAME
from app.core.errors import ApiErrorCode
from app.core.security import hash_password
from app.db.models import User, UserRole, UserStatus
from app.db.repositories import ConversationRepository
from app.db.repositories.users import UserRepository
from app.main import app

DUONG_DAN_LOGIN = "/api/v1/auth/login"
DUONG_DAN_ME = "/api/v1/auth/me"
DUONG_DAN_HOI_THOAI = "/api/v1/conversations/{}"
DUONG_DAN_MESSAGES = "/api/v1/conversations/{}/messages"
DUONG_DAN_RETRY = "/api/v1/messages/{}/retry"
DUONG_DAN_SUA = "/api/v1/messages/{}"

_MAT_KHAU = "mot-mat-khau-du-manh-cho-test-t27-123"

#: Bốn cột của bảng §11.1, dưới dạng tên hành động.
LOGIN = "dang_nhap"
VIEW = "xem_ui"
CHAT_SYSTEM = "chat_system_key"
CHAT_BYOK = "chat_byok"


# ═══════════════════════════ hạ tầng của bộ test ════════════════════════════


class _RedisGia:
    """Blacklist rỗng — mọi token đều "chưa bị thu hồi" (§11.3).

    Bộ test này đo phép kiểm **trạng thái**, không đo blacklist (đó là việc của
    `test_auth.py`): một Redis nói "không có khoá nào" giữ cho mọi ca ở đây
    dừng lại ở đúng lớp cần đo.
    """

    async def mget(self, keys: list[str]) -> list[str | None]:
        return [None for _ in keys]

    async def incr(self, name: str) -> int:
        return 1

    async def expire(self, name: str, time: int, *, nx: bool = False) -> bool:
        return True


class _ArqGia:
    """Pool arq giả — ghi lại lần enqueue thay vì nối `redis:6379`."""

    def __init__(self) -> None:
        self.da_day: list[tuple[str, tuple[Any, ...]]] = []

    async def enqueue_job(self, ten: str, *args: Any, **_: Any) -> object:
        self.da_day.append((ten, args))
        return object()


@pytest.fixture(autouse=True)
def redis_gia(monkeypatch: pytest.MonkeyPatch) -> _RedisGia:
    gia = _RedisGia()
    monkeypatch.setattr("app.core.deps.get_redis", lambda: gia)
    monkeypatch.setattr("app.core.ratelimit.get_redis", lambda: gia)
    return gia


@pytest_asyncio.fixture(autouse=True)
async def arq_gia(monkeypatch: pytest.MonkeyPatch) -> _ArqGia:
    gia = _ArqGia()

    async def _pool() -> _ArqGia:
        return gia

    monkeypatch.setattr("app.api.v1.messages.get_arq_pool", _pool)
    return gia


@pytest.fixture(autouse=True)
def _db_cua_test(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`session_scope()` trong handler trỏ vào ĐÚNG kết nối của test (NQ-17)."""
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


@pytest_asyncio.fixture
async def client(event_hooks: dict[str, Any]) -> AsyncIterator[AsyncClient]:
    # `event_hooks`: mỗi POST một `Idempotency-Key` mới, đúng hành vi FE của C22
    # — xem `tests/api/conftest.py`. Không có nó thì mọi POST tới
    # `.../messages` nhận `400 IDEMPOTENCY_KEY_REQUIRED` (§11.4, A8, T-2.8).
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://localhost", event_hooks=event_hooks
    ) as http:
        yield http


def _provider_byok() -> str:
    """Tên một provider có `byok_supported` trong catalog — A3: không gõ tay."""
    ho_tro = [ten for ten, p in catalog.get_catalog().providers.items() if p.byok_supported]
    assert ho_tro, "catalog phải có ít nhất một provider hỗ trợ BYOK"
    return sorted(ho_tro)[0]


async def _tao_user(
    session_factory: async_sessionmaker[AsyncSession],
    trang_thai: UserStatus,
    *,
    co_byok: bool = False,
) -> tuple[uuid.UUID, str]:
    """User với hash Argon2 thật, đặt sẵn `status`, tuỳ chọn thêm một khoá BYOK.

    Hàng `user_provider_keys` chèn bằng SQL thô vì bảng chưa có ORM model —
    cùng lý do đã ghi ở `UserRepository.has_provider_key`: hình dạng thật của
    nó là việc của T-2.14. Giá trị `key_cipher`/`key_nonce` chỉ cần **tồn tại**
    (phép kiểm của §11.1 là "có khoá hay không"), và cố ý là hai chuỗi byte vô
    nghĩa — không có khoá thật nào đi qua bộ test này.
    """
    email = f"{uuid.uuid4().hex}@scarlet.example"
    async with session_factory() as session:
        user = await UserRepository(session).create_pending_user(
            email=email, password_hash=await hash_password(_MAT_KHAU)
        )
        assert user is not None
        await session.execute(update(User).where(User.id == user.id).values(status=trang_thai))
        if co_byok:
            await session.execute(
                text(
                    "INSERT INTO user_provider_keys "
                    "(user_id, provider, key_cipher, key_nonce, key_last4) "
                    "VALUES (:user_id, :provider, :cipher, :nonce, :last4)"
                ).bindparams(
                    bindparam("user_id", type_=PgUUID(as_uuid=True)),
                    bindparam("cipher", type_=LargeBinary),
                    bindparam("nonce", type_=LargeBinary),
                ),
                {
                    "user_id": user.id,
                    "provider": _provider_byok(),
                    "cipher": b"khong-phai-ban-ma-that",
                    "nonce": b"khong-phai-nonce-that",
                    "last4": "0000",
                },
            )
        await session.commit()
        return user.id, email


def _dat_cookie_phien(client: AsyncClient, user_id: uuid.UUID, trang_thai: UserStatus) -> None:
    """Cookie phiên mang đúng `status` cần đo — claim `status` là thứ
    `require_status` đọc (xem `app/core/deps.py`)."""
    client.cookies.set(
        SESSION_COOKIE_NAME,
        encode_access_token(
            user_id=user_id,
            role=UserRole.USER,
            tier="free",
            status=trang_thai,
            ttl_minutes=15,
        ),
    )


async def _tao_hoi_thoai(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> uuid.UUID:
    async with session_factory() as session:
        conversation = await ConversationRepository(session).create_conversation(user_id=user_id)
        await session.commit()
        return conversation.id


# ══════════════════════ ma trận 5 trạng thái × 4 hành động ══════════════════
#
# `(trạng thái, hành động, status code chờ đợi, mã lỗi chờ đợi)`.
# `None` ở cột cuối = ca thành công, không có `error.code` nào để so.

MA_TRAN: list[tuple[UserStatus, str, int, ApiErrorCode | None]] = [
    # ── pending_email: vào được, nhìn được, KHÔNG chat bằng đường nào ──
    (UserStatus.PENDING_EMAIL, LOGIN, 200, None),
    (UserStatus.PENDING_EMAIL, VIEW, 200, None),
    (UserStatus.PENDING_EMAIL, CHAT_SYSTEM, 403, ApiErrorCode.EMAIL_NOT_VERIFIED),
    (UserStatus.PENDING_EMAIL, CHAT_BYOK, 403, ApiErrorCode.EMAIL_NOT_VERIFIED),
    # ── pending_approval: BYOK mở được cánh cửa mà system key thì không ──
    (UserStatus.PENDING_APPROVAL, LOGIN, 200, None),
    (UserStatus.PENDING_APPROVAL, VIEW, 200, None),
    (UserStatus.PENDING_APPROVAL, CHAT_SYSTEM, 403, ApiErrorCode.PENDING_APPROVAL),
    (UserStatus.PENDING_APPROVAL, CHAT_BYOK, 202, None),
    # ── active: cả bốn cột ──
    (UserStatus.ACTIVE, LOGIN, 200, None),
    (UserStatus.ACTIVE, VIEW, 200, None),
    (UserStatus.ACTIVE, CHAT_SYSTEM, 202, None),
    (UserStatus.ACTIVE, CHAT_BYOK, 202, None),
    # ── rejected / suspended: đóng cả bốn cột, BYOK không cứu được ──
    (UserStatus.REJECTED, LOGIN, 403, ApiErrorCode.ACCOUNT_DISABLED),
    (UserStatus.REJECTED, VIEW, 403, ApiErrorCode.ACCOUNT_DISABLED),
    (UserStatus.REJECTED, CHAT_SYSTEM, 403, ApiErrorCode.ACCOUNT_DISABLED),
    (UserStatus.REJECTED, CHAT_BYOK, 403, ApiErrorCode.ACCOUNT_DISABLED),
    (UserStatus.SUSPENDED, LOGIN, 403, ApiErrorCode.ACCOUNT_DISABLED),
    (UserStatus.SUSPENDED, VIEW, 403, ApiErrorCode.ACCOUNT_DISABLED),
    (UserStatus.SUSPENDED, CHAT_SYSTEM, 403, ApiErrorCode.ACCOUNT_DISABLED),
    (UserStatus.SUSPENDED, CHAT_BYOK, 403, ApiErrorCode.ACCOUNT_DISABLED),
]


@pytest.mark.parametrize(("trang_thai", "hanh_dong", "ma_http", "ma_loi"), MA_TRAN)
async def test_bang_phan_quyen_11_1(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    trang_thai: UserStatus,
    hanh_dong: str,
    ma_http: int,
    ma_loi: ApiErrorCode | None,
) -> None:
    """DoD T-2.7: **cả 5 trạng thái × 4 hành động = 20 case** của bảng §11.1."""
    user_id, email = await _tao_user(session_factory, trang_thai, co_byok=hanh_dong == CHAT_BYOK)

    if hanh_dong == LOGIN:
        resp = await client.post(DUONG_DAN_LOGIN, json={"email": email, "password": _MAT_KHAU})
    elif hanh_dong == VIEW:
        _dat_cookie_phien(client, user_id, trang_thai)
        resp = await client.get(DUONG_DAN_ME)
    else:
        _dat_cookie_phien(client, user_id, trang_thai)
        conversation_id = await _tao_hoi_thoai(session_factory, user_id)
        resp = await client.post(
            DUONG_DAN_MESSAGES.format(conversation_id), json={"content": "xin chao"}
        )

    assert resp.status_code == ma_http, resp.text
    if ma_loi is not None:
        body = resp.json()["error"]
        assert body["code"] == ma_loi
        # `details.status` nói đúng trạng thái đang chặn — thứ duy nhất phân
        # biệt `rejected` với `suspended` (hai ca dùng chung `ACCOUNT_DISABLED`).
        assert body["details"]["status"] == trang_thai.value


# ═══════════ năm dòng DoD, tách riêng cho đọc được một mình ═════════════════


async def test_pending_email_gui_message_tra_403_email_not_verified(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """DoD T-2.7 dòng 2 (và UC-01): `pending_email` gọi `POST .../messages`."""
    user_id, _ = await _tao_user(session_factory, UserStatus.PENDING_EMAIL)
    _dat_cookie_phien(client, user_id, UserStatus.PENDING_EMAIL)
    conversation_id = await _tao_hoi_thoai(session_factory, user_id)

    resp = await client.post(
        DUONG_DAN_MESSAGES.format(conversation_id), json={"content": "xin chao"}
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == ApiErrorCode.EMAIL_NOT_VERIFIED


async def test_pending_approval_khong_byok_tra_403_pending_approval(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """DoD T-2.7 dòng 3: chờ duyệt mà chưa có khoá riêng thì chưa chat được."""
    user_id, _ = await _tao_user(session_factory, UserStatus.PENDING_APPROVAL)
    _dat_cookie_phien(client, user_id, UserStatus.PENDING_APPROVAL)
    conversation_id = await _tao_hoi_thoai(session_factory, user_id)

    resp = await client.post(
        DUONG_DAN_MESSAGES.format(conversation_id), json={"content": "xin chao"}
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == ApiErrorCode.PENDING_APPROVAL


async def test_pending_approval_co_byok_tra_202(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], arq_gia: _ArqGia
) -> None:
    """DoD T-2.7 dòng 4 — "case dễ bỏ sót nhất" (§10.5, §11.1).

    Không chỉ đo mã `202`: job **thật sự** được đẩy đi, tức một lượt sinh đã mở
    ra chứ không phải một response lịch sự rồi thôi.
    """
    user_id, _ = await _tao_user(session_factory, UserStatus.PENDING_APPROVAL, co_byok=True)
    _dat_cookie_phien(client, user_id, UserStatus.PENDING_APPROVAL)
    conversation_id = await _tao_hoi_thoai(session_factory, user_id)

    resp = await client.post(
        DUONG_DAN_MESSAGES.format(conversation_id), json={"content": "xin chao"}
    )

    assert resp.status_code == 202, resp.text
    assert len(arq_gia.da_day) == 1


async def test_byok_cua_NGUOI_KHAC_khong_mo_cua_cho_minh(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Phép kiểm BYOK lọc `user_id` **trong câu SQL** (§20, CLAUDE.md).

    Hai `pending_approval`: một người có khoá, một người không. Người không có
    khoá vẫn phải nhận `403` — một `SELECT EXISTS` quên mất `WHERE user_id`
    sẽ mở cửa cho cả nhà chỉ vì một người hàng xóm đã cấu hình BYOK, và
    không ca nào của ma trận ở trên bắt được điều đó (mỗi ca chỉ có một user).
    """
    await _tao_user(session_factory, UserStatus.PENDING_APPROVAL, co_byok=True)
    user_id, _ = await _tao_user(session_factory, UserStatus.PENDING_APPROVAL)
    _dat_cookie_phien(client, user_id, UserStatus.PENDING_APPROVAL)
    conversation_id = await _tao_hoi_thoai(session_factory, user_id)

    resp = await client.post(
        DUONG_DAN_MESSAGES.format(conversation_id), json={"content": "xin chao"}
    )

    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == ApiErrorCode.PENDING_APPROVAL


async def test_suspended_khong_dang_nhap_duoc(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """DoD T-2.7 dòng 5: `suspended` → không đăng nhập được.

    `403 ACCOUNT_DISABLED` chứ không `401 INVALID_CREDENTIALS`: mật khẩu ĐÚNG,
    và nói "sai mật khẩu" ở đây là đẩy người dùng đi đặt lại mật khẩu để rồi
    vẫn không vào được. Không rò gì cho người lạ — phải qua được cửa mật khẩu
    mới thấy được câu này.
    """
    _, email = await _tao_user(session_factory, UserStatus.SUSPENDED)

    resp = await client.post(DUONG_DAN_LOGIN, json={"email": email, "password": _MAT_KHAU})

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == ApiErrorCode.ACCOUNT_DISABLED


async def test_suspended_sai_mat_khau_van_tra_401_invalid_credentials(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Thứ tự của hai phép kiểm trong `login`, đo được: mật khẩu TRƯỚC.

    Ngược lại thì gõ một email bất kỳ là biết tài khoản đó có tồn tại và đang
    ở trạng thái nào — đúng kênh dò mà §11.5 đóng.
    """
    _, email = await _tao_user(session_factory, UserStatus.SUSPENDED)

    resp = await client.post(
        DUONG_DAN_LOGIN, json={"email": email, "password": "mat-khau-khac-han-va-du-dai"}
    )

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == ApiErrorCode.INVALID_CREDENTIALS


async def test_suspended_dang_nhap_hong_khong_phat_hanh_cookie_nao(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Phép kiểm trạng thái đứng TRƯỚC lúc phát hành refresh family.

    Một tài khoản bị khoá không có việc gì phải cầm một credential 30 ngày —
    và nếu nó cầm được thì `POST /auth/refresh` sẽ là một đường vòng đi quanh
    đúng bức tường vừa dựng.
    """
    _, email = await _tao_user(session_factory, UserStatus.SUSPENDED)

    resp = await client.post(DUONG_DAN_LOGIN, json={"email": email, "password": _MAT_KHAU})

    assert resp.status_code == 403
    assert "set-cookie" not in resp.headers


# ════════ cạm bẫy của task: MỘT luật, không phải mỗi endpoint một luật ══════


async def test_moi_route_sinh_chu_deu_chan_pending_email(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Cạm bẫy T-2.7 ở dạng kiểm được: lặp qua **danh sách** route sinh chữ.

    `POST .../messages` là route duy nhất DoD gọi tên, nhưng `retry` và
    `PATCH /messages/{id}` cũng mở một lượt sinh — quên một trong ba là để hở
    đúng cánh cửa vừa khoá. Lặp qua danh sách thay vì viết tay từng cái, đúng
    lối mà cạm bẫy của T-2.16 dặn.

    `message_id` không cần tồn tại: `403` phải đến **trước** `404`, vì thứ tự
    ngược lại nói cho một tài khoản chưa xác thực email biết message nào có
    thật (§20).
    """
    user_id, _ = await _tao_user(session_factory, UserStatus.PENDING_EMAIL)
    _dat_cookie_phien(client, user_id, UserStatus.PENDING_EMAIL)
    conversation_id = await _tao_hoi_thoai(session_factory, user_id)
    message_id = uuid.uuid4()

    phan_hoi = [
        await client.post(DUONG_DAN_MESSAGES.format(conversation_id), json={"content": "a"}),
        await client.post(DUONG_DAN_RETRY.format(message_id), json={}),
        await client.patch(DUONG_DAN_SUA.format(message_id), json={"content": "b"}),
    ]
    for resp in phan_hoi:
        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["code"] == ApiErrorCode.EMAIL_NOT_VERIFIED


async def test_route_khong_sinh_chu_khong_bi_chan_boi_luat_chat(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Mặt kia của cùng một luật: `pending_email` vẫn xem được hội thoại.

    §11.1 cho họ "Xem UI ✓". Chặn cả đường đọc là biến một banner nhắc verify
    thành một bức tường trắng — và người dùng không còn chỗ nào để bấm "gửi
    lại thư".
    """
    user_id, _ = await _tao_user(session_factory, UserStatus.PENDING_EMAIL)
    _dat_cookie_phien(client, user_id, UserStatus.PENDING_EMAIL)
    conversation_id = await _tao_hoi_thoai(session_factory, user_id)

    resp = await client.get(DUONG_DAN_HOI_THOAI.format(conversation_id))

    assert resp.status_code == 200


async def test_suspended_khong_doc_duoc_hoi_thoai_cua_chinh_minh(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Cột "Xem UI" của §11.1 áp cho CẢ router `conversations`, không chỉ `/me`.

    Đây là phép kiểm mà cách gắn dependency ở `api/v1/__init__.py` tồn tại vì
    nó: một route không ai nhớ tới vẫn phải đóng.
    """
    user_id, _ = await _tao_user(session_factory, UserStatus.SUSPENDED)
    conversation_id = await _tao_hoi_thoai(session_factory, user_id)
    _dat_cookie_phien(client, user_id, UserStatus.SUSPENDED)

    resp = await client.get(DUONG_DAN_HOI_THOAI.format(conversation_id))

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == ApiErrorCode.ACCOUNT_DISABLED
