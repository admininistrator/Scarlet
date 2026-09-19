"""IDOR — user A nhắm vào tài nguyên của user B (§20, T-2.18).

**Một dòng của §20 là toàn bộ hợp đồng của file này:** *"user A gọi
`/conversations/{id-của-B}` → **404** (không phải 403 — 403 xác nhận tài nguyên
tồn tại)"*. Và vì 403 không phải thứ duy nhất rò rỉ, mỗi ô của ma trận dưới
đây bị đo **hai lần**:

1. `test_A_nham_tai_nguyen_cua_B_phai_404` — câu trả lời là `404`.
2. `test_cua_B_va_id_bia_ra_tra_loi_GIONG_HET_NHAU` — câu trả lời ấy **trùng
   từng byte** với câu trả lời cho một UUID bịa ra. Đây mới là phép đo thật
   của §20: một `404` mang `code: CONVERSATION_NOT_FOUND` cho id của B nhưng
   `code: NOT_FOUND` cho id không tồn tại vẫn là một kênh rò rỉ hoàn chỉnh —
   kẻ dò đọc `code` thay vì đọc status và biết được cùng chừng ấy.

**Ma trận là dữ liệu, không phải 11 hàm rời** (cùng lối `MA_TRAN` của
`tests/api/test_account_states.py`): thêm một endpoint nhận `{conversation_id}`
hay `{message_id}` là thêm **một dòng**, và quên nó là một chỗ trống nhìn thấy
được. `test_ma_tran_phu_het_moi_route_co_id_trong_duong_dan` biến "nhìn thấy
được" thành "đỏ": nó đọc **surface OpenAPI thật** của app và bắt ma trận phủ
hết. Đó là cách duy nhất một bộ test IDOR sống sót qua Phase 4–8, nơi mỗi
phase thêm vài endpoint nữa — cạm bẫy "quên một endpoint là đủ" mà T-2.16 đã
đóng cho `/admin/*` bằng vị trí, ở đây đóng bằng một phép đếm.

**Sáu tài nguyên của "Việc cần làm", ba cái hôm nay có đường dẫn:**
`conversation`, `message`, `key`. Ba cái còn lại — `attachment` (Phase 4),
`artifact` (Phase 5), `usage` (§18.4 `GET /settings/usage`, chưa có task nào
nhận) — chưa có bảng, chưa có endpoint, nên không có gì để nhắm vào; chúng đi
Backlog **B-181 · B-182 · B-183** kèm đúng dòng phải thêm vào `MA_TRAN` khi
endpoint ra đời, chứ không nằm ở đây dưới dạng `pytest.skip` — một ca skip
trong bộ test bảo mật đọc ra là "đã kiểm", và đó là lời nói dối đắt nhất
trong file này.

**Vì sao `key` không nằm trong `MA_TRAN`:** khoá BYOK không có id trong đường
dẫn (`UNIQUE (user_id, provider)`, §10.5), nên "id của B" ở đó không tồn tại
để mà thử. Hình dạng IDOR của nó khác — cùng một URL, hai người, hai hàng —
nên nó có nhóm riêng ở cuối file, và `test_ma_tran_phu_het_moi_route_co_id...`
biết về ngoại lệ đó một cách tường minh.

Hạ tầng giống `tests/api/test_account_states.py`: `httpx.ASGITransport`,
`session_scope()` trỏ về đúng kết nối của test, Redis giả cho cả bốn module có
`get_redis` (thiếu một cái là test **treo** chứ không đỏ), arq giả, và
`MockTransport` cho chặng đi hỏi provider — không lần chạy nào chạm Internet.
Bốn fake ấy lấy từ `tests/conftest.py`: bộ test này là người dùng thứ hai của
chúng, và đó là lý do T-2.18 chuyển chúng lên conftest gốc.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import catalog
from app.core.access_token import encode_access_token
from app.core.crypto import mask_secret, seal
from app.core.deps import SESSION_COOKIE_NAME
from app.core.errors import ApiErrorCode
from app.core.security import hash_password
from app.db.models import (
    Conversation,
    Message,
    MessageRole,
    MessageStatus,
    User,
    UserProviderKey,
    UserRole,
    UserStatus,
)
from app.db.repositories import ConversationRepository, MessageRepository
from app.db.repositories.provider_keys import ProviderKeyRepository
from app.db.repositories.users import UserRepository
from app.llm import byok_verify as verify_mod
from app.main import app

API = "/api/v1"
DUONG_DAN_KEYS = f"{API}/settings/keys"

_MAT_KHAU = "mot-mat-khau-du-manh-cho-test-t218-123"

#: Khoá BYOK của B. Không phải khoá của ai; đủ dài cho `mask_secret`.
KHOA_CUA_B = "sk-khoa-gia-cua-user-b-t218-7c31"
#: Khoá BYOK của A — khác hẳn, để phép kiểm "A ghi đè được hàng của B không"
#: đọc được kết quả bằng mắt chứ không phải bằng suy luận.
KHOA_CUA_A = "sk-khoa-gia-cua-user-a-t218-4d92"


# ═══════════════════════════ hạ tầng của bộ test ════════════════════════════


class _RedisGia:
    """Blacklist rỗng — mọi token đều "chưa bị thu hồi" (§11.3).

    Bộ test này đo **quyền sở hữu tài nguyên**, không đo blacklist (đó là việc
    của `test_auth.py`): một Redis nói "không có khoá nào" giữ mọi ca ở đây
    dừng lại ở đúng lớp cần đo.
    """

    async def mget(self, keys: list[str]) -> list[str | None]:
        return [None for _ in keys]

    async def incr(self, name: str) -> int:
        return 1

    async def expire(self, name: str, time: int, *, nx: bool = False) -> bool:
        return True


class _StreamRedisGia:
    """Redis giả cho đầu đọc SSE (`app/streaming/consumer.py`) — stream RỖNG.

    Fake này tồn tại vì **DoD dòng 3 của chính task này** đo ra nó. Khi chốt
    quyền sở hữu của `GET /messages/{id}/stream` bị bỏ, phép kiểm không đỏ gọn
    mà nổ thành `ConnectionError: Error -3 connecting to redis:6379` ném ra từ
    bên trong body của `StreamingResponse`, và bộ test chạy **41 s** thay vì
    10 s. Nguyên nhân: `httpx.ASGITransport` chạy ứng dụng **tới hết** kể cả
    khi phía test không đọc body, nên "không đọc thì không chạm Redis" là một
    giả định sai — và một fake thiếu ở đây là đúng kiểu hỏng mà
    `tests/api/conftest.py` đã phải trả giá một lần để học.

    `xrange` rỗng + `exists` = 0 + message của B đã `completed` ⇒ consumer đi
    nhánh ② của §7.3 (dựng lại từ Postgres) rồi đóng. Một lần thủng vì thế cho
    ra đúng một `200 text/event-stream` gọn gàng, tức một dòng `assert 200 ==
    404` đọc được, chứ không phải một vệt traceback.
    """

    async def xrange(
        self, name: str, min: str = "-", max: str = "+", count: int | None = None
    ) -> list[Any]:
        return []

    async def exists(self, *names: str) -> int:
        return 0


class _ArqGia:
    """Pool arq giả — ghi lại lần enqueue thay vì nối `redis:6379`.

    Danh sách `da_day` **phải rỗng** ở cuối mỗi ca IDOR: một job đã vào hàng
    đợi nghĩa là handler đã đi qua chốt quyền sở hữu, và lúc đó `404` chỉ còn
    là một câu nói dối lịch sự trong khi worker vẫn sinh chữ và vẫn tính tiền.
    """

    def __init__(self) -> None:
        self.da_day: list[tuple[str, tuple[Any, ...]]] = []

    async def enqueue_job(self, ten: str, *args: Any, **_: Any) -> object:
        self.da_day.append((ten, args))
        return object()


@pytest.fixture(autouse=True)
def redis_gia(monkeypatch: pytest.MonkeyPatch) -> _RedisGia:
    gia = _RedisGia()
    monkeypatch.setattr("app.core.deps.get_redis", lambda: gia)
    return gia


@pytest.fixture(autouse=True)
def idempotency_redis(monkeypatch: pytest.MonkeyPatch, idempotency_redis_fake: Any) -> Any:
    """§11.4 gắn ở router ⇒ mọi POST của ba router đi qua Redis (T-2.8)."""
    monkeypatch.setattr("app.core.idempotency.get_redis", lambda: idempotency_redis_fake)
    return idempotency_redis_fake


@pytest.fixture(autouse=True)
def ratelimit_redis(monkeypatch: pytest.MonkeyPatch, ratelimit_redis_fake: Any) -> Any:
    """§10.6 gắn ở ba route sinh chữ ⇒ chúng đi qua Redis (T-2.9)."""
    monkeypatch.setattr("app.core.ratelimit.get_redis", lambda: ratelimit_redis_fake)
    return ratelimit_redis_fake


@pytest.fixture(autouse=True)
def quota_redis(monkeypatch: pytest.MonkeyPatch, quota_redis_fake: Any) -> Any:
    """§10.2 — cửa chặn quota đọc hai ZSET **và** cache tier (T-2.11)."""
    monkeypatch.setattr("app.quota.estimator.get_redis", lambda: quota_redis_fake)
    monkeypatch.setattr("app.quota.tiers.get_redis", lambda: quota_redis_fake)
    return quota_redis_fake


@pytest.fixture(autouse=True)
def stream_redis_gia(monkeypatch: pytest.MonkeyPatch) -> _StreamRedisGia:
    """§7.4 — đầu đọc SSE có `get_redis` thứ năm. Xem `_StreamRedisGia`."""
    gia = _StreamRedisGia()
    monkeypatch.setattr("app.api.v1.stream.get_redis", lambda: gia)
    return gia


@pytest_asyncio.fixture(autouse=True)
async def arq_gia(monkeypatch: pytest.MonkeyPatch) -> _ArqGia:
    gia = _ArqGia()

    async def _pool() -> _ArqGia:
        return gia

    monkeypatch.setattr("app.api.v1.messages.get_arq_pool", _pool)
    return gia


@pytest.fixture(autouse=True)
def provider_noi_dong_y(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provider trả `200` ⇒ mọi khoá BYOK đều "sống" (§10.5).

    Autouse vì quên nó nghĩa là một test đi gọi Internet thật.
    """

    def _bat(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    monkeypatch.setattr(
        verify_mod, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(_bat))
    )


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


# ══════════════════════ hai người dùng, dữ liệu đầy đủ ══════════════════════


@dataclass(frozen=True, slots=True)
class DuLieu:
    """Một người dùng và **toàn bộ** tài nguyên có endpoint của họ (§20).

    "Đầy đủ" là chữ của "Việc cần làm", và nó quan trọng: một hội thoại rỗng
    không đo được `retry`/`siblings`/`stream`, nên B phải có cả cây message lẫn
    con trỏ nhánh lẫn khoá BYOK thì ma trận mới có gì để nhắm vào.
    """

    user_id: uuid.UUID
    conversation_id: uuid.UUID
    #: `role='user'` — đích của `PATCH /messages/{id}` (§8.2: sửa câu hỏi).
    message_user: uuid.UUID
    #: `role='assistant'`, `status='completed'` — đích của `retry`/`cancel`.
    message_assistant: uuid.UUID
    provider: str


def provider_byok() -> str:
    """Một provider `byok_supported` trong catalog — A3: không gõ tay tên."""
    ho_tro = [ten for ten, p in catalog.get_catalog().providers.items() if p.byok_supported]
    assert ho_tro, "catalog phải có ít nhất một provider hỗ trợ BYOK"
    return sorted(ho_tro)[0]


async def _tao_user(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    email = f"{uuid.uuid4().hex}@scarlet.example"
    async with session_factory() as session:
        user = await UserRepository(session).create_pending_user(
            email=email, password_hash=await hash_password(_MAT_KHAU)
        )
        assert user is not None
        await session.execute(
            update(User).where(User.id == user.id).values(status=UserStatus.ACTIVE)
        )
        await session.commit()
        return user.id


async def _dung_du_lieu(
    session_factory: async_sessionmaker[AsyncSession], nhan: str, khoa: str
) -> DuLieu:
    """Một user `active` + hội thoại + hai message + con trỏ nhánh + khoá BYOK."""
    user_id = await _tao_user(session_factory)
    provider = provider_byok()

    async with session_factory() as session:
        conversations = ConversationRepository(session)
        messages = MessageRepository(session)

        conversation = await conversations.create_conversation(
            user_id=user_id, title=f"hoi thoai cua {nhan}"
        )
        cau_hoi = await messages.create_message(
            conversation_id=conversation.id,
            user_id=user_id,
            role=MessageRole.USER,
            parent_id=None,
            content=f"cau hoi cua {nhan}",
        )
        cau_tra_loi = await messages.create_message(
            conversation_id=conversation.id,
            user_id=user_id,
            role=MessageRole.ASSISTANT,
            parent_id=cau_hoi.id,
            content=f"cau tra loi cho {nhan}",
            status=MessageStatus.COMPLETED,
        )
        await conversations.set_active_leaf(
            conversation.id, user_id=user_id, message_id=cau_tra_loi.id
        )
        await ProviderKeyRepository(session).upsert(
            user_id=user_id,
            provider=provider,
            sealed=seal(khoa),
            masked=mask_secret(khoa),
            verified_at=None,
        )
        await session.commit()
        return DuLieu(
            user_id=user_id,
            conversation_id=conversation.id,
            message_user=cau_hoi.id,
            message_assistant=cau_tra_loi.id,
            provider=provider,
        )


@pytest_asyncio.fixture
async def b(session_factory: async_sessionmaker[AsyncSession]) -> DuLieu:
    """Nạn nhân: đầy đủ tài nguyên, **không bao giờ** gửi một request nào."""
    return await _dung_du_lieu(session_factory, "B", KHOA_CUA_B)


@pytest_asyncio.fixture
async def a(client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]) -> DuLieu:
    """Kẻ tấn công: cũng là một người dùng **hợp lệ**, đã đăng nhập.

    Hợp lệ là điểm mấu chốt của IDOR và là lý do bộ test này khác
    `test_account_states.py`: không có gì sai với phiên của A cả — token còn
    hạn, tài khoản `active`, hạn mức còn nguyên. Thứ duy nhất sai là **id trong
    đường dẫn**. Một app chặn đúng ở lớp xác thực mà quên lớp sở hữu sẽ xanh
    hết `test_account_states.py` và đỏ hết file này.
    """
    du_lieu = await _dung_du_lieu(session_factory, "A", KHOA_CUA_A)
    client.cookies.set(
        SESSION_COOKIE_NAME,
        encode_access_token(
            user_id=du_lieu.user_id,
            role=UserRole.USER,
            tier="free",
            status=UserStatus.ACTIVE,
            ttl_minutes=15,
        ),
    )
    return du_lieu


# ════════════════════════════ ma trận IDOR (§20) ════════════════════════════


@dataclass(frozen=True, slots=True)
class CaIDOR:
    """Một ô của ma trận: một endpoint × một tài nguyên của B."""

    #: Tên hiển thị trong `pytest -v`. Đọc được thành câu.
    ten: str
    #: `conversation` | `message` — cột "tài nguyên" của "Việc cần làm".
    tai_nguyen: str
    #: Đường dẫn dạng OpenAPI, để `test_ma_tran_phu_het...` đối chiếu.
    route: str
    method: str
    #: Tài nguyên nào của B bị nhắm: khoá của `_MUC_TIEU` dưới đây.
    muc_tieu: str
    #: `(id bị nhắm, hội thoại của chính A)` → đường dẫn thật.
    duong_dan: Callable[[uuid.UUID, uuid.UUID], str]
    #: `(id bị nhắm)` → body. `None` = không gửi body.
    body: Callable[[uuid.UUID], dict[str, Any]] | None
    #: Mã lỗi §18 phải thấy trong `error.code`.
    ma_loi: ApiErrorCode


#: Ba lối lấy "id của B" — tách ra để một ca chọn đúng loại message nó cần.
_MUC_TIEU: dict[str, Callable[[DuLieu], uuid.UUID]] = {
    "conversation": lambda d: d.conversation_id,
    "message_user": lambda d: d.message_user,
    "message_assistant": lambda d: d.message_assistant,
}


MA_TRAN: tuple[CaIDOR, ...] = (
    # ── conversation: id của B nằm thẳng trong đường dẫn ──
    CaIDOR(
        ten="GET /conversations/{cua-B}",
        tai_nguyen="conversation",
        route=f"{API}/conversations/{{conversation_id}}",
        method="GET",
        muc_tieu="conversation",
        duong_dan=lambda muc_tieu, _cua_a: f"{API}/conversations/{muc_tieu}",
        body=None,
        ma_loi=ApiErrorCode.CONVERSATION_NOT_FOUND,
    ),
    CaIDOR(
        ten="PATCH /conversations/{cua-B}",
        tai_nguyen="conversation",
        route=f"{API}/conversations/{{conversation_id}}",
        method="PATCH",
        muc_tieu="conversation",
        duong_dan=lambda muc_tieu, _cua_a: f"{API}/conversations/{muc_tieu}",
        body=lambda _muc_tieu: {"title": "A vua doi ten hoi thoai cua B"},
        ma_loi=ApiErrorCode.CONVERSATION_NOT_FOUND,
    ),
    CaIDOR(
        ten="DELETE /conversations/{cua-B}",
        tai_nguyen="conversation",
        route=f"{API}/conversations/{{conversation_id}}",
        method="DELETE",
        muc_tieu="conversation",
        duong_dan=lambda muc_tieu, _cua_a: f"{API}/conversations/{muc_tieu}",
        body=None,
        ma_loi=ApiErrorCode.CONVERSATION_NOT_FOUND,
    ),
    CaIDOR(
        ten="POST /conversations/{cua-B}/messages",
        tai_nguyen="conversation",
        route=f"{API}/conversations/{{conversation_id}}/messages",
        method="POST",
        muc_tieu="conversation",
        duong_dan=lambda muc_tieu, _cua_a: f"{API}/conversations/{muc_tieu}/messages",
        body=lambda _muc_tieu: {"content": "A chen mot cau hoi vao hoi thoai cua B"},
        ma_loi=ApiErrorCode.CONVERSATION_NOT_FOUND,
    ),
    # ── hai ca id-của-B-nằm-trong-BODY: đường dẫn là hội thoại của CHÍNH A ──
    #
    # Đây là hình dạng IDOR mà một bộ test chỉ thay id trong URL bỏ sót hoàn
    # toàn, và nó là hình dạng đắt nhất: cả hai đều ghép cây của hai hội thoại
    # vào nhau, tức C11 ở dạng vĩnh viễn (ngữ cảnh gửi model từ đó về sau lẫn
    # dữ liệu của người khác, và A trả tiền để đọc nó).
    CaIDOR(
        ten="PATCH /conversations/{cua-A} voi active_leaf_id cua B",
        tai_nguyen="message",
        route=f"{API}/conversations/{{conversation_id}}",
        method="PATCH",
        muc_tieu="message_assistant",
        duong_dan=lambda _muc_tieu, cua_a: f"{API}/conversations/{cua_a}",
        body=lambda muc_tieu: {"active_leaf_id": str(muc_tieu)},
        ma_loi=ApiErrorCode.LEAF_NOT_FOUND,
    ),
    CaIDOR(
        ten="POST /conversations/{cua-A}/messages voi parent_id cua B",
        tai_nguyen="message",
        route=f"{API}/conversations/{{conversation_id}}/messages",
        method="POST",
        muc_tieu="message_assistant",
        duong_dan=lambda _muc_tieu, cua_a: f"{API}/conversations/{cua_a}/messages",
        body=lambda muc_tieu: {"content": "noi vao cay cua B", "parent_id": str(muc_tieu)},
        ma_loi=ApiErrorCode.PARENT_NOT_FOUND,
    ),
    # ── message: id của B nằm thẳng trong đường dẫn ──
    CaIDOR(
        ten="GET /messages/{cua-B}/stream",
        tai_nguyen="message",
        route=f"{API}/messages/{{message_id}}/stream",
        method="GET",
        muc_tieu="message_assistant",
        duong_dan=lambda muc_tieu, _cua_a: f"{API}/messages/{muc_tieu}/stream",
        body=None,
        ma_loi=ApiErrorCode.MESSAGE_NOT_FOUND,
    ),
    CaIDOR(
        ten="POST /messages/{cua-B}/cancel",
        tai_nguyen="message",
        route=f"{API}/messages/{{message_id}}/cancel",
        method="POST",
        muc_tieu="message_assistant",
        duong_dan=lambda muc_tieu, _cua_a: f"{API}/messages/{muc_tieu}/cancel",
        body=None,
        ma_loi=ApiErrorCode.MESSAGE_NOT_FOUND,
    ),
    CaIDOR(
        ten="POST /messages/{cua-B}/retry",
        tai_nguyen="message",
        route=f"{API}/messages/{{message_id}}/retry",
        method="POST",
        muc_tieu="message_assistant",
        duong_dan=lambda muc_tieu, _cua_a: f"{API}/messages/{muc_tieu}/retry",
        body=None,
        ma_loi=ApiErrorCode.MESSAGE_NOT_FOUND,
    ),
    CaIDOR(
        ten="PATCH /messages/{cua-B}",
        tai_nguyen="message",
        route=f"{API}/messages/{{message_id}}",
        method="PATCH",
        muc_tieu="message_user",
        duong_dan=lambda muc_tieu, _cua_a: f"{API}/messages/{muc_tieu}",
        body=lambda _muc_tieu: {"content": "A vua sua cau hoi cua B"},
        ma_loi=ApiErrorCode.MESSAGE_NOT_FOUND,
    ),
    CaIDOR(
        ten="GET /messages/{cua-B}/siblings",
        tai_nguyen="message",
        route=f"{API}/messages/{{message_id}}/siblings",
        method="GET",
        muc_tieu="message_assistant",
        duong_dan=lambda muc_tieu, _cua_a: f"{API}/messages/{muc_tieu}/siblings",
        body=None,
        ma_loi=ApiErrorCode.MESSAGE_NOT_FOUND,
    ),
)

#: `pytest -v` in ra câu chữ của ma trận, không phải `MA_TRAN0..MA_TRAN10`.
TEN_CA = [ca.ten for ca in MA_TRAN]


async def goi(client: AsyncClient, ca: CaIDOR, muc_tieu: uuid.UUID, cua_a: uuid.UUID) -> Any:
    """Chạy một ô của ma trận, trả `(status, body-json | None)`.

    Một ô là SSE, nên khi chốt quyền sở hữu thủng thì body không phải JSON.
    Nhánh `text/event-stream` trả `None` thay vì cố `resp.json()`: phép kiểm
    cần **trạng thái**, và một `JSONDecodeError` che mất chính con số ấy.
    Phần giữ cho nhánh đó nhanh và không chạm Internet là `_StreamRedisGia`.
    """
    duong_dan = ca.duong_dan(muc_tieu, cua_a)
    body = ca.body(muc_tieu) if ca.body is not None else None
    resp = await client.request(ca.method, duong_dan, json=body)
    if resp.headers.get("content-type", "").startswith("text/event-stream"):
        return resp.status_code, None
    return resp.status_code, (resp.json() if resp.content else None)


# ═════════ 1. Mọi ô của ma trận trả 404 — KHÔNG 403 (§20, DoD dòng 2) ════════


@pytest.mark.parametrize("ca", MA_TRAN, ids=TEN_CA)
async def test_A_nham_tai_nguyen_cua_B_phai_404(
    client: AsyncClient, a: DuLieu, b: DuLieu, ca: CaIDOR
) -> None:
    """§20: `404`, và `403` là câu trả lời **sai** dù nó cũng chặn được.

    `403` nói "có thứ đó, nhưng không phải của anh". Với một id tuần tự thì đó
    là cả một danh bạ; với UUID thì nó vẫn đủ để xác nhận một id lấy được từ
    chỗ khác (log, link chia sẻ, ảnh chụp màn hình) là có thật.
    """
    muc_tieu = _MUC_TIEU[ca.muc_tieu](b)
    status_code, body = await goi(client, ca, muc_tieu, a.conversation_id)

    assert status_code != 403, "403 xac nhan tai nguyen ton tai — §20 doi 404"
    assert status_code == 404, f"{ca.ten} tra {status_code}, body={body}"
    assert body is not None
    assert body["error"]["code"] == ca.ma_loi.value


@pytest.mark.parametrize("ca", MA_TRAN, ids=TEN_CA)
async def test_cua_B_va_id_bia_ra_tra_loi_GIONG_HET_NHAU(
    client: AsyncClient, a: DuLieu, b: DuLieu, ca: CaIDOR
) -> None:
    """Phép đo THẬT của §20: hai câu trả lời không phân biệt được.

    "Trả 404" là điều kiện cần, không phải điều kiện đủ. Nếu id của B ra
    `404 CONVERSATION_NOT_FOUND` còn một UUID bịa ra ra `404 NOT_FOUND`, thì
    status đã đúng mà kênh rò rỉ vẫn còn nguyên — chỉ chuyển từ cột "status"
    sang cột "code". Vì vậy so **cả gói** `(status, body)`, và `ErrorBody` của
    §18 đúng ba trường tất định nên phép so này không nhấp nháy.
    """
    muc_tieu = _MUC_TIEU[ca.muc_tieu](b)
    cua_B = await goi(client, ca, muc_tieu, a.conversation_id)
    bia_ra = await goi(client, ca, uuid.uuid4(), a.conversation_id)

    assert cua_B == bia_ra, (
        f"{ca.ten}: tai nguyen cua B va mot id khong ton tai tra loi KHAC nhau "
        f"— cua B: {cua_B}, bia ra: {bia_ra}"
    )


# ═══════ 2. 404 rồi thì cũng KHÔNG được đụng vào dữ liệu của B (§20) ════════


async def test_ca_ma_tran_chay_xong_du_lieu_cua_B_van_nguyen_ven(
    client: AsyncClient,
    a: DuLieu,
    b: DuLieu,
    arq_gia: _ArqGia,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Chạy **toàn bộ** ma trận rồi soi hàng Postgres của B.

    Một `404` trả về sau khi đã `UPDATE` là ca hỏng tệ nhất trong file này:
    status nói "không tìm thấy" nên không ai đi kiểm, còn tiêu đề hội thoại của
    B thì đã đổi. Ba câu `UPDATE` của `conversations.py` và hai câu `INSERT`
    của `messages.py` đều lọc `user_id` **trong SQL**, và đây là chỗ khẳng định
    điều đó từ phía dữ liệu thay vì từ phía response.

    `arq_gia.da_day` rỗng thuộc cùng một họ: nếu một job đã vào hàng đợi thì
    worker sẽ sinh chữ và ghi `usage_events` cho một lượt mà API vừa bảo là
    không tồn tại — tức A trả tiền để mọc thêm một nhánh vào cây của B.
    """
    for ca in MA_TRAN:
        muc_tieu = _MUC_TIEU[ca.muc_tieu](b)
        status_code, _ = await goi(client, ca, muc_tieu, a.conversation_id)
        assert status_code == 404, ca.ten

    async with session_factory() as session:
        hoi_thoai = (
            await session.execute(select(Conversation).where(Conversation.id == b.conversation_id))
        ).scalar_one()
        so_message = (
            await session.execute(
                select(func.count())
                .select_from(Message)
                .where(Message.conversation_id == b.conversation_id)
            )
        ).scalar_one()
        noi_dung = sorted(
            (
                await session.execute(
                    select(Message.content).where(Message.conversation_id == b.conversation_id)
                )
            )
            .scalars()
            .all()
        )

    assert hoi_thoai.deleted_at is None, "DELETE cua A da xoa mem hoi thoai cua B"
    assert hoi_thoai.title == "hoi thoai cua B", "PATCH cua A da doi tieu de cua B"
    assert hoi_thoai.active_leaf_id == b.message_assistant, "A da doi con tro nhanh cua B"
    assert so_message == 2, "A da chen them message vao cay cua B"
    assert noi_dung == ["cau hoi cua B", "cau tra loi cho B"]
    assert arq_gia.da_day == [], "mot job da vao hang doi cho mot request tra 404"


# ═══════════ 3. Không rò qua DANH SÁCH — chỗ không có id để mà 404 ══════════
#
# `GET /conversations` không nhận id nào nên nó không thể trả 404; hình dạng rò
# rỉ của nó là "trả về nhiều hơn phần của mình". Cùng một luật §20 ("lọc
# `user_id` trong câu SQL"), khác hình dạng.


async def test_danh_sach_hoi_thoai_cua_A_khong_chua_gi_cua_B(
    client: AsyncClient, a: DuLieu, b: DuLieu
) -> None:
    resp = await client.get(f"{API}/conversations")
    assert resp.status_code == 200, resp.text
    ids = {muc["id"] for muc in resp.json()["items"]}
    assert ids == {str(a.conversation_id)}
    assert str(b.conversation_id) not in resp.text


async def test_duong_di_cua_A_khong_chua_message_cua_B(
    client: AsyncClient, a: DuLieu, b: DuLieu
) -> None:
    """`GET /conversations/{cua-A}` dựng `path` bằng `get_path` (§8.3).

    Recursive CTE là chỗ dễ đánh rơi điều kiện `user_id` nhất trong cả repo —
    nó phải có mặt ở **cả hai** nhánh, và một nhánh thiếu thì đường đi trèo
    ngược lên cây của người khác mà không câu `SELECT` nào ở tầng trên thấy.
    """
    resp = await client.get(f"{API}/conversations/{a.conversation_id}")
    assert resp.status_code == 200, resp.text
    ids = {muc["id"] for muc in resp.json()["path"]}
    assert ids == {str(a.message_user), str(a.message_assistant)}
    assert str(b.message_user) not in resp.text
    assert str(b.message_assistant) not in resp.text


# ════════════════ 4. Khoá BYOK — IDOR không có id (§10.5, C20) ══════════════


async def _hang_khoa(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> list[UserProviderKey]:
    async with session_factory() as session:
        stmt = select(UserProviderKey).where(UserProviderKey.user_id == user_id)
        return list((await session.execute(stmt)).scalars().all())


async def test_danh_sach_khoa_cua_A_khong_chua_khoa_cua_B(
    client: AsyncClient, a: DuLieu, b: DuLieu
) -> None:
    """Cùng một URL cho hai người ⇒ `user_id` phải đến từ token, không từ input."""
    resp = await client.get(DUONG_DAN_KEYS)
    assert resp.status_code == 200, resp.text
    khoa = resp.json()["keys"]
    assert len(khoa) == 1
    assert khoa[0]["masked_key"] == mask_secret(KHOA_CUA_A)
    assert mask_secret(KHOA_CUA_B) not in resp.text


async def test_A_khong_xoa_duoc_khoa_cua_B(
    client: AsyncClient,
    a: DuLieu,
    b: DuLieu,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A xoá khoá của mình xong gọi lại: `404`, và hàng của B còn nguyên.

    Lần gọi thứ hai là phần đáng giá. Sau khi A đã xoá, **vẫn còn** một hàng
    cho đúng provider ấy trong bảng — của B. Một câu `DELETE` quên
    `user_id` sẽ xoá nó và trả `204`, và không ai biết cho tới lúc B đi chat.
    """
    assert (await client.delete(f"{DUONG_DAN_KEYS}/{a.provider}")).status_code == 204

    resp = await client.delete(f"{DUONG_DAN_KEYS}/{a.provider}")
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == ApiErrorCode.PROVIDER_KEY_NOT_FOUND.value

    con_lai = await _hang_khoa(session_factory, b.user_id)
    assert len(con_lai) == 1
    assert con_lai[0].key_last4 == mask_secret(KHOA_CUA_B)


async def test_A_ghi_khoa_moi_khong_de_len_hang_cua_B(
    client: AsyncClient,
    a: DuLieu,
    b: DuLieu,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """`upsert` khoá theo `(user_id, provider)` — không phải theo `provider`.

    Một `ON CONFLICT (provider)` thay vì `ON CONFLICT (user_id, provider)` cho
    đúng hình dạng hỏng ở đây: A đổi khoá của mình và khoá của B biến mất, đổi
    thành khoá của A. Hoá đơn từ đó về sau của B do A trả — hoặc ngược lại,
    tuỳ ai gọi sau.
    """
    truoc = (await _hang_khoa(session_factory, b.user_id))[0]
    khoa_moi = "sk-khoa-hoan-toan-moi-cua-A-8f10"
    resp = await client.put(f"{DUONG_DAN_KEYS}/{a.provider}", json={"key": khoa_moi})
    assert resp.status_code == 200, resp.text

    sau = (await _hang_khoa(session_factory, b.user_id))[0]
    assert sau.key_cipher == truoc.key_cipher
    assert sau.key_nonce == truoc.key_nonce
    assert sau.key_last4 == mask_secret(KHOA_CUA_B)


# ═════════ 5. Ma trận phải phủ HẾT — "quên một endpoint là đủ" (§20) ════════


async def test_ma_tran_phu_het_moi_route_co_id_trong_duong_dan() -> None:
    """Đọc surface OpenAPI THẬT và bắt `MA_TRAN` phủ hết.

    Đây là dòng duy nhất trong file giữ cho nó còn đúng sau Phase 3–8. Không
    có nó, "test A truy cập **mọi** tài nguyên của B" là một lời hứa đo tại
    một thời điểm; có nó, endpoint thứ mười hai nhận `{conversation_id}` hay
    `{message_id}` **không thêm được vào app** mà không thêm một dòng vào ma
    trận — cùng cách T-2.16 đóng cạm bẫy `require_admin` bằng vị trí, chỉ khác
    là ở đây phép đếm làm việc đó.

    Hai họ đường dẫn có `{...}` mà cố ý **không** tính:

    * `/settings/keys/{provider}` — `{provider}` là một tên trong catalog, ai
      cũng được phép gõ; tài nguyên nằm ở `(user_id, provider)` và nhóm 4 ở
      trên đo đúng nó.
    * `/admin/users/{user_id}` — `/admin/*` chặn ở `require_admin` (§16.3), và
      `tests/api/test_admin_authz.py` đã phủ cả bảy endpoint từ T-2.16. Một
      admin đọc dữ liệu của người khác là **chức năng**, không phải IDOR.
    """
    trong_app: set[tuple[str, str]] = set()
    for duong_dan, cac_method in app.openapi()["paths"].items():
        if "{conversation_id}" not in duong_dan and "{message_id}" not in duong_dan:
            continue
        for method in cac_method:
            trong_app.add((method.upper(), duong_dan))

    trong_ma_tran = {(ca.method, ca.route) for ca in MA_TRAN}

    assert trong_app, "khong doc duoc route nao — phep kiem nay se xanh gia"
    assert trong_app - trong_ma_tran == set(), (
        "endpoint nhan id tai nguyen nhung KHONG co trong MA_TRAN cua "
        "tests/security/test_idor.py — them mot dong vao ma tran (§20)"
    )
    assert trong_ma_tran - trong_app == set(), (
        "MA_TRAN nhac toi route khong con ton tai — sua lai cho khoi xanh gia"
    )
