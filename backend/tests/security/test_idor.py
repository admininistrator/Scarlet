"""IDOR — user A nhắm vào tài nguyên của user B (§20, T-2.18).

**Một dòng của §20 là toàn bộ hợp đồng của file này:** *"user A gọi
`/conversations/{id-của-B}` → **404** (không phải 403 — 403 xác nhận tài nguyên
tồn tại)"*. Và vì 403 không phải thứ duy nhất rò rỉ, mỗi ô của ma trận dưới
đây bị đo **hai lần**:

1. `test_A_targeting_Bs_resource_must_404` — câu trả lời là `404`.
2. `test_Bs_id_and_made_up_id_answer_IDENTICALLY` — câu trả lời ấy **trùng
   từng byte** với câu trả lời cho một UUID bịa ra. Đây mới là phép đo thật
   của §20: một `404` mang `code: CONVERSATION_NOT_FOUND` cho id của B nhưng
   `code: NOT_FOUND` cho id không tồn tại vẫn là một kênh rò rỉ hoàn chỉnh —
   kẻ dò đọc `code` thay vì đọc status và biết được cùng chừng ấy.

**Ma trận là dữ liệu, không phải 11 hàm rời** (cùng lối `MATRIX` của
`tests/api/test_account_states.py`): thêm một endpoint nhận `{conversation_id}`
hay `{message_id}` là thêm **một dòng**, và quên nó là một chỗ trống nhìn thấy
được. `test_matrix_covers_every_route_with_id_in_path` biến "nhìn thấy
được" thành "đỏ": nó đọc **surface OpenAPI thật** của app và bắt ma trận phủ
hết. Đó là cách duy nhất một bộ test IDOR sống sót qua Phase 4–8, nơi mỗi
phase thêm vài endpoint nữa — cạm bẫy "quên một endpoint là đủ" mà T-2.16 đã
đóng cho `/admin/*` bằng vị trí, ở đây đóng bằng một phép đếm.

**Sáu tài nguyên của "Việc cần làm", ba cái hôm nay có đường dẫn:**
`conversation`, `message`, `key`. Ba cái còn lại — `attachment` (Phase 4),
`artifact` (Phase 5), `usage` (§18.4 `GET /settings/usage`, chưa có task nào
nhận) — chưa có bảng, chưa có endpoint, nên không có gì để nhắm vào; chúng đi
Backlog **B-181 · B-182 · B-183** kèm đúng dòng phải thêm vào `MATRIX` khi
endpoint ra đời, chứ không nằm ở đây dưới dạng `pytest.skip` — một ca skip
trong bộ test bảo mật đọc ra là "đã kiểm", và đó là lời nói dối đắt nhất
trong file này.

**Vì sao `key` không nằm trong `MATRIX`:** khoá BYOK không có id trong đường
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

import re
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
    AttachmentKind,
    Conversation,
    Message,
    MessageRole,
    MessageStatus,
    User,
    UserProviderKey,
    UserRole,
    UserStatus,
)
from app.db.repositories import (
    ArtifactRepository,
    AttachmentRepository,
    ByokEndpointRepository,
    ConversationRepository,
    MessageRepository,
)
from app.db.repositories.provider_keys import ProviderKeyRepository
from app.db.repositories.users import UserRepository
from app.llm import byok_verify as verify_mod
from app.llm.artifact_blocks import ArtifactBlock
from app.main import app

API = "/api/v1"
KEYS_PATH = f"{API}/settings/keys"

_PASSWORD = "mot-mat-khau-du-manh-cho-test-t218-123"

#: Khoá BYOK của B. Không phải khoá của ai; đủ dài cho `mask_secret`.
KEY_OF_B = "sk-khoa-gia-cua-user-b-t218-7c31"
#: Khoá BYOK của A — khác hẳn, để phép kiểm "A ghi đè được hàng của B không"
#: đọc được kết quả bằng mắt chứ không phải bằng suy luận.
KEY_OF_A = "sk-khoa-gia-cua-user-a-t218-4d92"


# ═══════════════════════════ hạ tầng của bộ test ════════════════════════════


class _FakeRedis:
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


class _FakeStreamRedis:
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


class _FakeArq:
    """Pool arq giả — ghi lại lần enqueue thay vì nối `redis:6379`.

    Danh sách `pushed` **phải rỗng** ở cuối mỗi ca IDOR: một job đã vào hàng
    đợi nghĩa là handler đã đi qua chốt quyền sở hữu, và lúc đó `404` chỉ còn
    là một câu nói dối lịch sự trong khi worker vẫn sinh chữ và vẫn tính tiền.
    """

    def __init__(self) -> None:
        self.pushed: list[tuple[str, tuple[Any, ...]]] = []

    async def enqueue_job(self, name: str, *args: Any, **_: Any) -> object:
        self.pushed.append((name, args))
        return object()


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    fake = _FakeRedis()
    monkeypatch.setattr("app.core.deps.get_redis", lambda: fake)
    return fake


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
def fake_stream_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeStreamRedis:
    """§7.4 — đầu đọc SSE có `get_redis` thứ năm. Xem `_FakeStreamRedis`."""
    fake = _FakeStreamRedis()
    monkeypatch.setattr("app.api.v1.stream.get_redis", lambda: fake)
    return fake


@pytest_asyncio.fixture(autouse=True)
async def fake_arq(monkeypatch: pytest.MonkeyPatch) -> _FakeArq:
    fake = _FakeArq()

    async def _pool() -> _FakeArq:
        return fake

    monkeypatch.setattr("app.api.v1.messages.get_arq_pool", _pool)
    return fake


@pytest.fixture(autouse=True)
def provider_accepts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provider trả `200` ⇒ mọi khoá BYOK đều "sống" (§10.5).

    Autouse vì quên nó nghĩa là một test đi gọi Internet thật.
    """

    def _capture(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    monkeypatch.setattr(
        verify_mod, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(_capture))
    )


@pytest.fixture(autouse=True)
def _db_for_tests(
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
class Dataset:
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
    #: Một hàng `attachments` (T-4.2, B-181) — object MinIO không cần có thật.
    attachment: uuid.UUID
    #: Artifact trên câu trả lời (T-5.2a, B-182) — không có `user_id` trên bảng.
    artifact: uuid.UUID
    #: Endpoint BYOK (T-S.19b) — vào ma trận ở T-5.2a (B-342).
    byok_endpoint: uuid.UUID


def provider_byok() -> str:
    """Một provider `byok_supported` trong catalog — A3: không gõ tay tên."""
    supported = [name for name, p in catalog.get_catalog().providers.items() if p.byok_supported]
    assert supported, "catalog phải có ít nhất một provider hỗ trợ BYOK"
    return sorted(supported)[0]


async def _create_user(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    email = f"{uuid.uuid4().hex}@scarlet.example"
    async with session_factory() as session:
        user = await UserRepository(session).create_pending_user(
            email=email, password_hash=await hash_password(_PASSWORD)
        )
        assert user is not None
        await session.execute(
            update(User).where(User.id == user.id).values(status=UserStatus.ACTIVE)
        )
        await session.commit()
        return user.id


async def _build_data(
    session_factory: async_sessionmaker[AsyncSession], label: str, key: str
) -> Dataset:
    """Một user `active` + hội thoại + hai message + con trỏ nhánh + khoá BYOK."""
    user_id = await _create_user(session_factory)
    provider = provider_byok()

    async with session_factory() as session:
        conversations = ConversationRepository(session)
        messages = MessageRepository(session)

        conversation = await conversations.create_conversation(
            user_id=user_id, title=f"hoi thoai cua {label}"
        )
        question = await messages.create_message(
            conversation_id=conversation.id,
            user_id=user_id,
            role=MessageRole.USER,
            parent_id=None,
            content=f"cau hoi cua {label}",
        )
        answer = await messages.create_message(
            conversation_id=conversation.id,
            user_id=user_id,
            role=MessageRole.ASSISTANT,
            parent_id=question.id,
            content=f"cau tra loi cho {label}",
            status=MessageStatus.COMPLETED,
        )
        await conversations.set_active_leaf(conversation.id, user_id=user_id, message_id=answer.id)
        await ProviderKeyRepository(session).upsert(
            user_id=user_id,
            provider=provider,
            sealed=seal(key),
            masked=mask_secret(key),
            verified_at=None,
        )
        attachment = await AttachmentRepository(session).create(
            user_id=user_id,
            kind=AttachmentKind.FILE,
            mime_type="application/pdf",
            original_name=f"tep cua {label}.pdf",
            size_bytes=1,
            storage_key=f"{user_id}/idor.pdf",
        )
        [artifact] = await ArtifactRepository(session).create_for_message(
            message_id=answer.id,
            user_id=user_id,
            blocks=[ArtifactBlock(kind="html", language="html", title="Trang", content="<p/>")],
        )
        endpoint = await ByokEndpointRepository(session).create(
            user_id=user_id,
            label=f"endpoint cua {label}",
            base_url="https://byok.example/v1",
            sealed=seal(key),
            masked=mask_secret(key),
            models=["m"],
            verified_at=None,
        )
        await session.commit()
        return Dataset(
            user_id=user_id,
            conversation_id=conversation.id,
            message_user=question.id,
            message_assistant=answer.id,
            provider=provider,
            attachment=attachment.id,
            artifact=artifact.id,
            byok_endpoint=endpoint.id,
        )


@pytest_asyncio.fixture
async def b(session_factory: async_sessionmaker[AsyncSession]) -> Dataset:
    """Nạn nhân: đầy đủ tài nguyên, **không bao giờ** gửi một request nào."""
    return await _build_data(session_factory, "B", KEY_OF_B)


@pytest_asyncio.fixture
async def a(client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]) -> Dataset:
    """Kẻ tấn công: cũng là một người dùng **hợp lệ**, đã đăng nhập.

    Hợp lệ là điểm mấu chốt của IDOR và là lý do bộ test này khác
    `test_account_states.py`: không có gì sai với phiên của A cả — token còn
    hạn, tài khoản `active`, hạn mức còn nguyên. Thứ duy nhất sai là **id trong
    đường dẫn**. Một app chặn đúng ở lớp xác thực mà quên lớp sở hữu sẽ xanh
    hết `test_account_states.py` và đỏ hết file này.
    """
    data = await _build_data(session_factory, "A", KEY_OF_A)
    client.cookies.set(
        SESSION_COOKIE_NAME,
        encode_access_token(
            user_id=data.user_id,
            role=UserRole.USER,
            tier="free",
            status=UserStatus.ACTIVE,
            ttl_minutes=15,
        ),
    )
    return data


# ════════════════════════════ ma trận IDOR (§20) ════════════════════════════


@dataclass(frozen=True, slots=True)
class CaIDOR:
    """Một ô của ma trận: một endpoint × một tài nguyên của B."""

    #: Tên hiển thị trong `pytest -v`. Đọc được thành câu.
    name: str
    #: `conversation` | `message` — cột "tài nguyên" của "Việc cần làm".
    resource: str
    #: Đường dẫn dạng OpenAPI, để `test_ma_tran_phu_het...` đối chiếu.
    route: str
    method: str
    #: Tài nguyên nào của B bị nhắm: khoá của `_TARGETS` dưới đây.
    target: str
    #: `(id bị nhắm, hội thoại của chính A)` → đường dẫn thật.
    path: Callable[[uuid.UUID, uuid.UUID], str]
    #: `(id bị nhắm)` → body. `None` = không gửi body.
    body: Callable[[uuid.UUID], dict[str, Any]] | None
    #: Mã lỗi §18 phải thấy trong `error.code`.
    error_code: ApiErrorCode


#: Ba lối lấy "id của B" — tách ra để một ca chọn đúng loại message nó cần.
_TARGETS: dict[str, Callable[[Dataset], uuid.UUID]] = {
    "conversation": lambda d: d.conversation_id,
    "message_user": lambda d: d.message_user,
    "message_assistant": lambda d: d.message_assistant,
    "attachment": lambda d: d.attachment,
    "artifact": lambda d: d.artifact,
    "byok_endpoint": lambda d: d.byok_endpoint,
}


MATRIX: tuple[CaIDOR, ...] = (
    # ── conversation: id của B nằm thẳng trong đường dẫn ──
    CaIDOR(
        name="GET /conversations/{cua-B}",
        resource="conversation",
        route=f"{API}/conversations/{{conversation_id}}",
        method="GET",
        target="conversation",
        path=lambda target, _of_a: f"{API}/conversations/{target}",
        body=None,
        error_code=ApiErrorCode.CONVERSATION_NOT_FOUND,
    ),
    CaIDOR(
        name="PATCH /conversations/{cua-B}",
        resource="conversation",
        route=f"{API}/conversations/{{conversation_id}}",
        method="PATCH",
        target="conversation",
        path=lambda target, _of_a: f"{API}/conversations/{target}",
        body=lambda _target: {"title": "A vua doi ten hoi thoai cua B"},
        error_code=ApiErrorCode.CONVERSATION_NOT_FOUND,
    ),
    CaIDOR(
        name="DELETE /conversations/{cua-B}",
        resource="conversation",
        route=f"{API}/conversations/{{conversation_id}}",
        method="DELETE",
        target="conversation",
        path=lambda target, _of_a: f"{API}/conversations/{target}",
        body=None,
        error_code=ApiErrorCode.CONVERSATION_NOT_FOUND,
    ),
    CaIDOR(
        name="POST /conversations/{cua-B}/messages",
        resource="conversation",
        route=f"{API}/conversations/{{conversation_id}}/messages",
        method="POST",
        target="conversation",
        path=lambda target, _of_a: f"{API}/conversations/{target}/messages",
        body=lambda _target: {"content": "A chen mot cau hoi vao hoi thoai cua B"},
        error_code=ApiErrorCode.CONVERSATION_NOT_FOUND,
    ),
    # T-S.7 (§24.2b·S6): stream tiêu đề đọc `conversations.title` của B — tiêu
    # đề sinh từ câu hỏi đầu của B, tức rò đúng thứ §20 gọi tên. Thủng thì ra
    # `200 text/event-stream` (`_FakeStreamRedis`: không stream ⇒ dựng lại
    # `done` từ Postgres), không phải 404.
    CaIDOR(
        name="GET /conversations/{cua-B}/title/stream",
        resource="conversation",
        route=f"{API}/conversations/{{conversation_id}}/title/stream",
        method="GET",
        target="conversation",
        path=lambda target, _of_a: f"{API}/conversations/{target}/title/stream",
        body=None,
        error_code=ApiErrorCode.CONVERSATION_NOT_FOUND,
    ),
    # ── hai ca id-của-B-nằm-trong-BODY: đường dẫn là hội thoại của CHÍNH A ──
    #
    # Đây là hình dạng IDOR mà một bộ test chỉ thay id trong URL bỏ sót hoàn
    # toàn, và nó là hình dạng đắt nhất: cả hai đều ghép cây của hai hội thoại
    # vào nhau, tức C11 ở dạng vĩnh viễn (ngữ cảnh gửi model từ đó về sau lẫn
    # dữ liệu của người khác, và A trả tiền để đọc nó).
    CaIDOR(
        name="PATCH /conversations/{cua-A} voi active_leaf_id cua B",
        resource="message",
        route=f"{API}/conversations/{{conversation_id}}",
        method="PATCH",
        target="message_assistant",
        path=lambda _target, of_a: f"{API}/conversations/{of_a}",
        body=lambda target: {"active_leaf_id": str(target)},
        error_code=ApiErrorCode.LEAF_NOT_FOUND,
    ),
    CaIDOR(
        name="POST /conversations/{cua-A}/messages voi parent_id cua B",
        resource="message",
        route=f"{API}/conversations/{{conversation_id}}/messages",
        method="POST",
        target="message_assistant",
        path=lambda _target, of_a: f"{API}/conversations/{of_a}/messages",
        body=lambda target: {"content": "noi vao cay cua B", "parent_id": str(target)},
        error_code=ApiErrorCode.PARENT_NOT_FOUND,
    ),
    # T-4.4a (B-181): tệp chưa gắn của B trong thân request. Thủng ⇒ `202` và
    # tệp của B thành của message A — ảnh của B vào ngữ cảnh A trả tiền đọc.
    CaIDOR(
        name="POST /conversations/{cua-A}/messages voi attachment_ids cua B",
        resource="attachment",
        route=f"{API}/conversations/{{conversation_id}}/messages",
        method="POST",
        target="attachment",
        path=lambda _target, of_a: f"{API}/conversations/{of_a}/messages",
        body=lambda target: {"content": "gan tep cua B", "attachment_ids": [str(target)]},
        error_code=ApiErrorCode.ATTACHMENT_NOT_FOUND,
    ),
    # T-8.1 — chia sẻ: chỉ chủ tạo được snapshot; của B ⇒ 404, không hàng nào.
    CaIDOR(
        name="POST /conversations/{cua-B}/share",
        resource="conversation",
        route=f"{API}/conversations/{{conversation_id}}/share",
        method="POST",
        target="conversation",
        path=lambda target, _of_a: f"{API}/conversations/{target}/share",
        body=None,
        error_code=ApiErrorCode.CONVERSATION_NOT_FOUND,
    ),
    # T-8.5 — xuất: thủng ⇒ `200 text/markdown` mang nguyên đường đi của B.
    CaIDOR(
        name="GET /conversations/{cua-B}/export",
        resource="conversation",
        route=f"{API}/conversations/{{conversation_id}}/export",
        method="GET",
        target="conversation",
        path=lambda target, _of_a: f"{API}/conversations/{target}/export?format=md",
        body=None,
        error_code=ApiErrorCode.CONVERSATION_NOT_FOUND,
    ),
    # ── message: id của B nằm thẳng trong đường dẫn ──
    CaIDOR(
        name="GET /messages/{cua-B}/stream",
        resource="message",
        route=f"{API}/messages/{{message_id}}/stream",
        method="GET",
        target="message_assistant",
        path=lambda target, _of_a: f"{API}/messages/{target}/stream",
        body=None,
        error_code=ApiErrorCode.MESSAGE_NOT_FOUND,
    ),
    CaIDOR(
        name="POST /messages/{cua-B}/cancel",
        resource="message",
        route=f"{API}/messages/{{message_id}}/cancel",
        method="POST",
        target="message_assistant",
        path=lambda target, _of_a: f"{API}/messages/{target}/cancel",
        body=None,
        error_code=ApiErrorCode.MESSAGE_NOT_FOUND,
    ),
    CaIDOR(
        name="POST /messages/{cua-B}/retry",
        resource="message",
        route=f"{API}/messages/{{message_id}}/retry",
        method="POST",
        target="message_assistant",
        path=lambda target, _of_a: f"{API}/messages/{target}/retry",
        body=None,
        error_code=ApiErrorCode.MESSAGE_NOT_FOUND,
    ),
    CaIDOR(
        name="PATCH /messages/{cua-B}",
        resource="message",
        route=f"{API}/messages/{{message_id}}",
        method="PATCH",
        target="message_user",
        path=lambda target, _of_a: f"{API}/messages/{target}",
        body=lambda _target: {"content": "A vua sua cau hoi cua B"},
        error_code=ApiErrorCode.MESSAGE_NOT_FOUND,
    ),
    CaIDOR(
        name="POST /messages/{cua-B}/feedback",
        resource="message",
        route=f"{API}/messages/{{message_id}}/feedback",
        method="POST",
        target="message_assistant",
        path=lambda target, _of_a: f"{API}/messages/{target}/feedback",
        body=lambda _target: {"value": "like"},
        error_code=ApiErrorCode.MESSAGE_NOT_FOUND,
    ),
    CaIDOR(
        name="GET /messages/{cua-B}/siblings",
        resource="message",
        route=f"{API}/messages/{{message_id}}/siblings",
        method="GET",
        target="message_assistant",
        path=lambda target, _of_a: f"{API}/messages/{target}/siblings",
        body=None,
        error_code=ApiErrorCode.MESSAGE_NOT_FOUND,
    ),
    # ── attachment (T-4.2, B-181). Ô `attachment_ids` trong thân
    # `POST …/messages` ở nhóm id-trong-BODY phía trên (T-4.4a). `404` ở đây không đóng URL MinIO —
    # quyền ở tầng chữ ký là TTL + phạm vi khoá (T-4.1). ──
    CaIDOR(
        name="GET /attachments/{cua-B}",
        resource="attachment",
        route=f"{API}/attachments/{{attachment_id}}",
        method="GET",
        target="attachment",
        path=lambda target, _of_a: f"{API}/attachments/{target}",
        body=None,
        error_code=ApiErrorCode.ATTACHMENT_NOT_FOUND,
    ),
    # ── artifact (T-5.2a, B-182): bảng không có `user_id`, sở hữu qua JOIN
    # `messages → conversations`. Origin phụ không có id nào (T-5.6). ──
    CaIDOR(
        name="GET /artifacts/{cua-B}",
        resource="artifact",
        route=f"{API}/artifacts/{{artifact_id}}",
        method="GET",
        target="artifact",
        path=lambda target, _of_a: f"{API}/artifacts/{target}",
        body=None,
        error_code=ApiErrorCode.ARTIFACT_NOT_FOUND,
    ),
    CaIDOR(
        name="GET /artifacts/{cua-B}/versions",
        resource="artifact",
        route=f"{API}/artifacts/{{artifact_id}}/versions",
        method="GET",
        target="artifact",
        path=lambda target, _of_a: f"{API}/artifacts/{target}/versions",
        body=None,
        error_code=ApiErrorCode.ARTIFACT_NOT_FOUND,
    ),
    # T-5.2b: thủng ⇒ `201` và một phiên bản do A viết nằm trong dòng của B —
    # vào ngữ cảnh lượt kế tiếp của B (Q-P5-5).
    CaIDOR(
        name="POST /artifacts/{cua-B}/versions",
        resource="artifact",
        route=f"{API}/artifacts/{{artifact_id}}/versions",
        method="POST",
        target="artifact",
        path=lambda target, _of_a: f"{API}/artifacts/{target}/versions",
        body=lambda _target: {"content": "A chen ban sua vao artifact cua B"},
        error_code=ApiErrorCode.ARTIFACT_NOT_FOUND,
    ),
    # ── byok endpoint (T-S.19b) — lộ ra khi bộ lọc thành "mọi `{…_id}`" (B-342) ──
    CaIDOR(
        name="GET /settings/byok-endpoints/{cua-B}/models",
        resource="byok_endpoint",
        route=f"{API}/settings/byok-endpoints/{{endpoint_id}}/models",
        method="GET",
        target="byok_endpoint",
        path=lambda target, _of_a: f"{API}/settings/byok-endpoints/{target}/models",
        body=None,
        error_code=ApiErrorCode.BYOK_ENDPOINT_NOT_FOUND,
    ),
    CaIDOR(
        name="PATCH /settings/byok-endpoints/{cua-B}",
        resource="byok_endpoint",
        route=f"{API}/settings/byok-endpoints/{{endpoint_id}}",
        method="PATCH",
        target="byok_endpoint",
        path=lambda target, _of_a: f"{API}/settings/byok-endpoints/{target}",
        body=lambda _target: {"label": "A doi nhan endpoint cua B"},
        error_code=ApiErrorCode.BYOK_ENDPOINT_NOT_FOUND,
    ),
    CaIDOR(
        name="DELETE /settings/byok-endpoints/{cua-B}",
        resource="byok_endpoint",
        route=f"{API}/settings/byok-endpoints/{{endpoint_id}}",
        method="DELETE",
        target="byok_endpoint",
        path=lambda target, _of_a: f"{API}/settings/byok-endpoints/{target}",
        body=None,
        error_code=ApiErrorCode.BYOK_ENDPOINT_NOT_FOUND,
    ),
)

#: `pytest -v` in ra câu chữ của ma trận, không phải `MA_TRAN0..MA_TRAN10`.
CASE_NAMES = [ca.name for ca in MATRIX]


async def call(client: AsyncClient, ca: CaIDOR, target: uuid.UUID, of_a: uuid.UUID) -> Any:
    """Chạy một ô của ma trận, trả `(status, body-json | None)`.

    Một ô là SSE, nên khi chốt quyền sở hữu thủng thì body không phải JSON.
    Nhánh `text/event-stream` trả `None` thay vì cố `resp.json()`: phép kiểm
    cần **trạng thái**, và một `JSONDecodeError` che mất chính con số ấy.
    Phần giữ cho nhánh đó nhanh và không chạm Internet là `_FakeStreamRedis`.
    """
    path = ca.path(target, of_a)
    body = ca.body(target) if ca.body is not None else None
    resp = await client.request(ca.method, path, json=body)
    if resp.headers.get("content-type", "").startswith("text/event-stream"):
        return resp.status_code, None
    return resp.status_code, (resp.json() if resp.content else None)


# ═════════ 1. Mọi ô của ma trận trả 404 — KHÔNG 403 (§20, DoD dòng 2) ════════


@pytest.mark.parametrize("ca", MATRIX, ids=CASE_NAMES)
async def test_A_targeting_Bs_resource_must_404(
    client: AsyncClient, a: Dataset, b: Dataset, ca: CaIDOR
) -> None:
    """§20: `404`, và `403` là câu trả lời **sai** dù nó cũng chặn được.

    `403` nói "có thứ đó, nhưng không phải của anh". Với một id tuần tự thì đó
    là cả một danh bạ; với UUID thì nó vẫn đủ để xác nhận một id lấy được từ
    chỗ khác (log, link chia sẻ, ảnh chụp màn hình) là có thật.
    """
    target = _TARGETS[ca.target](b)
    status_code, body = await call(client, ca, target, a.conversation_id)

    assert status_code != 403, "403 xac nhan tai nguyen ton tai — §20 doi 404"
    assert status_code == 404, f"{ca.name} tra {status_code}, body={body}"
    assert body is not None
    assert body["error"]["code"] == ca.error_code.value


@pytest.mark.parametrize("ca", MATRIX, ids=CASE_NAMES)
async def test_Bs_id_and_made_up_id_answer_IDENTICALLY(
    client: AsyncClient, a: Dataset, b: Dataset, ca: CaIDOR
) -> None:
    """Phép đo THẬT của §20: hai câu trả lời không phân biệt được.

    "Trả 404" là điều kiện cần, không phải điều kiện đủ. Nếu id của B ra
    `404 CONVERSATION_NOT_FOUND` còn một UUID bịa ra ra `404 NOT_FOUND`, thì
    status đã đúng mà kênh rò rỉ vẫn còn nguyên — chỉ chuyển từ cột "status"
    sang cột "code". Vì vậy so **cả gói** `(status, body)`, và `ErrorBody` của
    §18 đúng ba trường tất định nên phép so này không nhấp nháy.
    """
    target = _TARGETS[ca.target](b)
    of_B = await call(client, ca, target, a.conversation_id)
    fabricated = await call(client, ca, uuid.uuid4(), a.conversation_id)

    assert of_B == fabricated, (
        f"{ca.name}: tai nguyen cua B va mot id khong ton tai tra loi KHAC nhau "
        f"— cua B: {of_B}, bia ra: {fabricated}"
    )


# ═══════ 2. 404 rồi thì cũng KHÔNG được đụng vào dữ liệu của B (§20) ════════


async def test_after_whole_matrix_Bs_data_is_intact(
    client: AsyncClient,
    a: Dataset,
    b: Dataset,
    fake_arq: _FakeArq,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Chạy **toàn bộ** ma trận rồi soi hàng Postgres của B.

    Một `404` trả về sau khi đã `UPDATE` là ca hỏng tệ nhất trong file này:
    status nói "không tìm thấy" nên không ai đi kiểm, còn tiêu đề hội thoại của
    B thì đã đổi. Ba câu `UPDATE` của `conversations.py` và hai câu `INSERT`
    của `messages.py` đều lọc `user_id` **trong SQL**, và đây là chỗ khẳng định
    điều đó từ phía dữ liệu thay vì từ phía response.

    `arq_gia.pushed` rỗng thuộc cùng một họ: nếu một job đã vào hàng đợi thì
    worker sẽ sinh chữ và ghi `usage_events` cho một lượt mà API vừa bảo là
    không tồn tại — tức A trả tiền để mọc thêm một nhánh vào cây của B.
    """
    for ca in MATRIX:
        target = _TARGETS[ca.target](b)
        status_code, _ = await call(client, ca, target, a.conversation_id)
        assert status_code == 404, ca.name

    async with session_factory() as session:
        conversation = (
            await session.execute(select(Conversation).where(Conversation.id == b.conversation_id))
        ).scalar_one()
        so_message = (
            await session.execute(
                select(func.count())
                .select_from(Message)
                .where(Message.conversation_id == b.conversation_id)
            )
        ).scalar_one()
        content = sorted(
            (
                await session.execute(
                    select(Message.content).where(Message.conversation_id == b.conversation_id)
                )
            )
            .scalars()
            .all()
        )

    assert conversation.deleted_at is None, "DELETE cua A da xoa mem hoi thoai cua B"
    assert conversation.title == "hoi thoai cua B", "PATCH cua A da doi tieu de cua B"
    assert conversation.active_leaf_id == b.message_assistant, "A da doi con tro nhanh cua B"
    assert so_message == 2, "A da chen them message vao cay cua B"
    assert content == ["cau hoi cua B", "cau tra loi cho B"]
    assert fake_arq.pushed == [], "mot job da vao hang doi cho mot request tra 404"
    async with session_factory() as session:
        attachment = await AttachmentRepository(session).get(
            user_id=b.user_id, attachment_id=b.attachment
        )
    assert attachment is not None and attachment.message_id is None, "A da gan tep cua B"
    async with session_factory() as session:
        endpoint = await ByokEndpointRepository(session).get(
            user_id=b.user_id, endpoint_id=b.byok_endpoint
        )
    assert endpoint is not None, "DELETE cua A da xoa endpoint BYOK cua B"
    assert endpoint.label == "endpoint cua B", "PATCH cua A da doi nhan endpoint cua B"


@pytest.mark.parametrize("deleted", ["message", "conversation"])
async def test_artifact_of_As_soft_deleted_message_is_404(
    client: AsyncClient,
    a: Dataset,
    session_factory: async_sessionmaker[AsyncSession],
    deleted: str,
) -> None:
    """C12 (Cạm bẫy ③ T-5.2a): artifact của message / hội thoại đã xoá mềm phải
    `404` — không chỉ vắng khỏi đường đi. `200` trước khi xoá là phép đối chứng."""
    paths = [f"{API}/artifacts/{a.artifact}", f"{API}/artifacts/{a.artifact}/versions"]
    assert [(await client.get(p)).status_code for p in paths] == [200, 200]

    async with session_factory() as session:
        if deleted == "message":
            await MessageRepository(session).soft_delete_message(
                a.message_assistant, user_id=a.user_id
            )
        else:
            await ConversationRepository(session).soft_delete_conversation(
                a.conversation_id, user_id=a.user_id
            )
        await session.commit()

    for p in paths:
        resp = await client.get(p)
        assert (resp.status_code, resp.json()["error"]["code"]) == (404, "ARTIFACT_NOT_FOUND")


# ═══════════ 3. Không rò qua DANH SÁCH — chỗ không có id để mà 404 ══════════
#
# `GET /conversations` không nhận id nào nên nó không thể trả 404; hình dạng rò
# rỉ của nó là "trả về nhiều hơn phần của mình". Cùng một luật §20 ("lọc
# `user_id` trong câu SQL"), khác hình dạng.


async def test_As_conversation_list_has_nothing_of_B(
    client: AsyncClient, a: Dataset, b: Dataset
) -> None:
    resp = await client.get(f"{API}/conversations")
    assert resp.status_code == 200, resp.text
    ids = {item["id"] for item in resp.json()["items"]}
    assert ids == {str(a.conversation_id)}
    assert str(b.conversation_id) not in resp.text


async def test_As_path_has_no_message_of_B(client: AsyncClient, a: Dataset, b: Dataset) -> None:
    """`GET /conversations/{cua-A}` dựng `path` bằng `get_path` (§8.3).

    Recursive CTE là chỗ dễ đánh rơi điều kiện `user_id` nhất trong cả repo —
    nó phải có mặt ở **cả hai** nhánh, và một nhánh thiếu thì đường đi trèo
    ngược lên cây của người khác mà không câu `SELECT` nào ở tầng trên thấy.
    """
    resp = await client.get(f"{API}/conversations/{a.conversation_id}")
    assert resp.status_code == 200, resp.text
    ids = {item["id"] for item in resp.json()["path"]}
    assert ids == {str(a.message_user), str(a.message_assistant)}
    assert str(b.message_user) not in resp.text
    assert str(b.message_assistant) not in resp.text


# ════════════════ 4. Khoá BYOK — IDOR không có id (§10.5, C20) ══════════════


async def _key_row(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> list[UserProviderKey]:
    async with session_factory() as session:
        stmt = select(UserProviderKey).where(UserProviderKey.user_id == user_id)
        return list((await session.execute(stmt)).scalars().all())


async def test_As_key_list_has_no_key_of_B(client: AsyncClient, a: Dataset, b: Dataset) -> None:
    """Cùng một URL cho hai người ⇒ `user_id` phải đến từ token, không từ input."""
    resp = await client.get(KEYS_PATH)
    assert resp.status_code == 200, resp.text
    key = resp.json()["keys"]
    assert len(key) == 1
    assert key[0]["masked_key"] == mask_secret(KEY_OF_A)
    assert mask_secret(KEY_OF_B) not in resp.text


async def test_A_cannot_delete_Bs_key(
    client: AsyncClient,
    a: Dataset,
    b: Dataset,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A xoá khoá của mình xong gọi lại: `404`, và hàng của B còn nguyên.

    Lần gọi thứ hai là phần đáng giá. Sau khi A đã xoá, **vẫn còn** một hàng
    cho đúng provider ấy trong bảng — của B. Một câu `DELETE` quên
    `user_id` sẽ xoá nó và trả `204`, và không ai biết cho tới lúc B đi chat.
    """
    assert (await client.delete(f"{KEYS_PATH}/{a.provider}")).status_code == 204

    resp = await client.delete(f"{KEYS_PATH}/{a.provider}")
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == ApiErrorCode.PROVIDER_KEY_NOT_FOUND.value

    remaining = await _key_row(session_factory, b.user_id)
    assert len(remaining) == 1
    assert remaining[0].key_last4 == mask_secret(KEY_OF_B)


async def test_A_writing_new_key_does_not_overwrite_Bs_row(
    client: AsyncClient,
    a: Dataset,
    b: Dataset,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """`upsert` khoá theo `(user_id, provider)` — không phải theo `provider`.

    Một `ON CONFLICT (provider)` thay vì `ON CONFLICT (user_id, provider)` cho
    đúng hình dạng hỏng ở đây: A đổi khoá của mình và khoá của B biến mất, đổi
    thành khoá của A. Hoá đơn từ đó về sau của B do A trả — hoặc ngược lại,
    tuỳ ai gọi sau.
    """
    before = (await _key_row(session_factory, b.user_id))[0]
    new_key = "sk-khoa-hoan-toan-moi-cua-A-8f10"
    resp = await client.put(f"{KEYS_PATH}/{a.provider}", json={"key": new_key})
    assert resp.status_code == 200, resp.text

    after = (await _key_row(session_factory, b.user_id))[0]
    assert after.key_cipher == before.key_cipher
    assert after.key_nonce == before.key_nonce
    assert after.key_last4 == mask_secret(KEY_OF_B)


# ═════════ 5. Ma trận phải phủ HẾT — "quên một endpoint là đủ" (§20) ════════


#: B-342 (T-5.2a): MỌI tham số đường dẫn `{…_id}` là id của một tài nguyên có
#: chủ, trừ danh sách miễn dưới đây — mỗi dòng một lý do. Danh sách tay các tên
#: CẦN đếm (`_ID_PARAMS` cũ) làm route mới lọt qua mà vẫn xanh (đo ở T-4.2).
_ID_PARAM = re.compile(r"\{(\w+_id)\}")
_EXEMPT_ID_PARAMS = {
    # `/admin/users/{user_id}…` — chặn ở `require_admin` (§16.3), phủ bởi
    # `tests/api/test_admin_authz.py`; admin đọc dữ liệu người khác là chức năng.
    "user_id": "admin",
    # `/admin/models/{model_id}` — tên model trong catalog, không phải tài nguyên có chủ.
    "model_id": "catalog",
}


async def test_matrix_covers_every_route_with_id_in_path() -> None:
    """Đọc surface OpenAPI THẬT và bắt `MATRIX` phủ hết.

    Đây là dòng duy nhất trong file giữ cho nó còn đúng sau Phase 3–8. Không
    có nó, "test A truy cập **mọi** tài nguyên của B" là một lời hứa đo tại
    một thời điểm; có nó, endpoint thứ mười hai nhận `{conversation_id}` hay
    `{message_id}` **không thêm được vào app** mà không thêm một dòng vào ma
    trận — cùng cách T-2.16 đóng cạm bẫy `require_admin` bằng vị trí, chỉ khác
    là ở đây phép đếm làm việc đó.

    Đếm **mọi** `{…_id}` trừ `_EXEMPT_ID_PARAMS` (B-342). Tham số không đuôi
    `_id` không phải id tài nguyên: `/settings/keys/{provider}` — tên trong
    catalog, tài nguyên nằm ở `(user_id, provider)` và nhóm 4 ở trên đo đúng
    nó; `/admin/tiers/{name}` — chặn ở `require_admin` (§16.3).
    """
    in_app: set[tuple[str, str]] = set()
    for path, methods in app.openapi()["paths"].items():
        if not set(_ID_PARAM.findall(path)) - _EXEMPT_ID_PARAMS.keys():
            continue
        for method in methods:
            in_app.add((method.upper(), path))

    in_matrix = {(ca.method, ca.route) for ca in MATRIX}

    assert in_app, "khong doc duoc route nao — phep kiem nay se xanh gia"
    assert in_app - in_matrix == set(), (
        "endpoint nhan id tai nguyen nhung KHONG co trong MA_TRAN cua "
        "tests/security/test_idor.py — them mot dong vao ma tran (§20)"
    )
    assert in_matrix - in_app == set(), (
        "MA_TRAN nhac toi route khong con ton tai — sua lai cho khoi xanh gia"
    )
