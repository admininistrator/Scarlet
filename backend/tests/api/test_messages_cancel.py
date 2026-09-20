"""T-1.9 — `POST /api/v1/messages/{id}/cancel` (§7.5, §18.2, §20).

Dòng DoD thứ tư của task ("cancel một message đã `completed` → 200, không có
tác dụng phụ") nằm ở đây dưới dạng tự động; ba dòng còn lại đo trên hạ tầng
thật (chữ ngừng ≤ 500 ms, `messages.content` đúng phần đã sinh, log usage) nên
output của chúng nằm trong báo cáo task.

Cùng lối đi với `test_stream.py` và `test_messages.py`: `httpx.ASGITransport`,
`DEBUG` bật tay, `session_scope()` trỏ về đúng kết nối của test, Redis giả.
Redis phải giả vì `redis:6379` chỉ phân giải được **bên trong** network
`internal` của compose, còn `make test` chạy từ WSL host.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import settings
from app.core.access_token import encode_access_token
from app.core.deps import SESSION_COOKIE_NAME
from app.db.models import Message, MessageRole, MessageStatus, UserRole, UserStatus
from app.db.repositories import ConversationRepository, MessageRepository
from app.main import app
from app.streaming.cancel import GIA_TRI_CO, cancel_key

DUONG_DAN = "/api/v1/messages/{}/cancel"


class RedisGia:
    """Ghi lại mọi `SET`; `no_ra` mô phỏng Redis chết giữa lúc bấm Dừng."""

    def __init__(self) -> None:
        self.da_set: list[tuple[str, str, Any]] = []
        self.no_ra = False

    async def set(self, name: str, value: str, *, ex: int | None = None) -> bool:
        if self.no_ra:
            raise ConnectionError("redis chet giua chung (gia lap)")
        self.da_set.append((name, value, ex))
        return True


@pytest.fixture
def _db_cua_test(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`session_scope()` trong handler trỏ vào ĐÚNG kết nối của test (NQ-17)."""
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


@pytest.fixture
def redis_gia(monkeypatch: pytest.MonkeyPatch) -> RedisGia:
    gia = RedisGia()
    monkeypatch.setattr("app.api.v1.messages.get_redis", lambda: gia)
    return gia


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as http:
        yield http


def _phien(user_id: uuid.UUID) -> dict[str, str]:
    """Header `Cookie` mang phiên thật (§11.2) của `user_id` — T-3.1c.

    Trả một `dict` để truyền vào `headers=` của **từng request**, đúng chỗ mà
    header danh tính tạm của Phase 1 đứng trước đây: danh tính theo request
    chứ không đặt lên `client`, nên hai danh tính trong cùng một ca (phép kiểm
    quyền sở hữu, §20) vẫn viết được cạnh nhau mà không ai phải nhớ dọn.

    **Một header `Cookie`, không phải tham số `cookies=` của httpx.** httpx đã
    deprecate `cookies=` theo request (*"expected behaviour on cookie
    persistence is ambiguous"*) — và ở đây không có gì để persist: mỗi request
    tự mang phiên của nó. Một `dict` header còn ghép được bằng `|` với
    `Idempotency-Key` hay `Last-Event-ID` mà không phải trộn hai cơ chế.

    `status=ACTIVE` chứ không đọc từ bảng `users`: §11.1 kiểm trạng thái từ
    **claim** của access token (xem `core/deps.py`), và bộ test này đo chuyện
    khác — ma trận 5×4 của bảng ấy là việc của `test_account_states.py`.
    """
    token = encode_access_token(
        user_id=user_id,
        role=UserRole.USER,
        tier="free",
        status=UserStatus.ACTIVE,
        ttl_minutes=15,
    )
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


async def _tao_message(
    session_factory: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
    *,
    status: MessageStatus,
    content: str = "",
) -> Message:
    async with session_factory() as session:
        conversation = await ConversationRepository(session).create_conversation(user_id=user_id)
        message = await MessageRepository(session).create_message(
            conversation_id=conversation.id,
            user_id=user_id,
            role=MessageRole.ASSISTANT,
            status=status,
            content=content,
        )
        await session.commit()
        return message


async def _doc_lai(session_factory: async_sessionmaker[AsyncSession], mid: uuid.UUID) -> Message:
    async with session_factory() as session:
        message = await session.get(Message, mid)
        assert message is not None
        return message


# ═══════════════════ đường chạy đúng: còn cái để dừng ═══════════════════


@pytest.mark.parametrize("trang_thai", [MessageStatus.QUEUED, MessageStatus.STREAMING])
async def test_dat_co_khi_message_con_dang_sinh(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    trang_thai: MessageStatus,
    _db_cua_test: None,
    redis_gia: RedisGia,
) -> None:
    """§7.5: `SET cancel:{id} 1 EX CANCEL_TTL_S`, cho cả `queued` lẫn `streaming`.

    `queued` cũng phải nhận cờ: người dùng bấm Dừng ngay sau khi gửi thì job
    còn nằm trong hàng đợi, và cờ phải chờ sẵn ở đó khi worker nhặt nó lên.
    """
    message = await _tao_message(session_factory, user_a, status=trang_thai)

    resp = await client.post(DUONG_DAN.format(message.id), headers=_phien(user_a))

    assert resp.status_code == 200
    body = resp.json()
    assert body["cancel_requested"] is True
    assert body["status"] == trang_thai.value
    assert body["message_id"] == str(message.id)
    assert redis_gia.da_set == [(cancel_key(message.id), GIA_TRI_CO, settings.CANCEL_TTL_S)]


async def test_api_khong_tu_doi_trang_thai_trong_postgres(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_cua_test: None,
    redis_gia: RedisGia,
) -> None:
    """A1: handler dựng một lá cờ, KHÔNG ghi trạng thái xuống Postgres.

    Người ghi trạng thái là worker. Nếu API cũng ghi thì hai người cùng ghi
    một hàng: worker đang sinh sẽ ghi đè lại vài giây sau và nút Dừng trở
    thành thứ đôi khi có tác dụng.
    """
    message = await _tao_message(session_factory, user_a, status=MessageStatus.STREAMING)

    await client.post(DUONG_DAN.format(message.id), headers=_phien(user_a))

    sau = await _doc_lai(session_factory, message.id)
    assert sau.status is MessageStatus.STREAMING
    assert sau.finish_reason is None


async def test_bam_dung_hai_lan_deu_dat_co(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_cua_test: None,
    redis_gia: RedisGia,
) -> None:
    """Bấm hai lần trên một lượt ĐANG sinh: vô hại, và gia hạn TTL."""
    message = await _tao_message(session_factory, user_a, status=MessageStatus.STREAMING)
    phien = _phien(user_a)

    mot = await client.post(DUONG_DAN.format(message.id), headers=phien)
    hai = await client.post(DUONG_DAN.format(message.id), headers=phien)

    assert (mot.status_code, hai.status_code) == (200, 200)
    assert hai.json()["cancel_requested"] is True
    assert len(redis_gia.da_set) == 2


# ════════════ DoD dòng 4: idempotent trên message đã khép ════════════


@pytest.mark.parametrize(
    "trang_thai",
    [MessageStatus.COMPLETED, MessageStatus.FAILED, MessageStatus.CANCELLED],
)
async def test_message_da_khep_tra_200_va_khong_dat_co(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    trang_thai: MessageStatus,
    _db_cua_test: None,
    redis_gia: RedisGia,
) -> None:
    """DoD: cancel một message đã `completed` → `200`, **không có tác dụng phụ**.

    "Không tác dụng phụ" đọc theo nghĩa đen: không có khoá `cancel:{id}` nào
    được tạo. Đặt rồi kệ nó cũng ra `200`, nhưng để lại một khoá sống
    `CANCEL_TTL_S` giây cho một message đã xong — và nếu T-1.13 cho `retry`
    dùng lại cùng `message_id` thì đó là một quả mìn hẹn giờ.
    """
    message = await _tao_message(
        session_factory, user_a, status=trang_thai, content="cau tra loi cu"
    )

    resp = await client.post(DUONG_DAN.format(message.id), headers=_phien(user_a))

    assert resp.status_code == 200
    assert resp.json()["cancel_requested"] is False
    assert resp.json()["status"] == trang_thai.value
    assert redis_gia.da_set == []

    sau = await _doc_lai(session_factory, message.id)
    assert sau.status is trang_thai
    assert sau.content == "cau tra loi cu", "không được đụng tới nội dung đã có"


# ═══════════════════════ quyền sở hữu (§20) và lỗi ═══════════════════════


async def test_message_cua_user_khac_tra_404_khong_phai_403(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    _db_cua_test: None,
    redis_gia: RedisGia,
) -> None:
    """§20: 403 cho ca này là xác nhận `message_id` đó có thật.

    Và quan trọng hơn: **không** đặt cờ. Nếu handler đặt cờ trước rồi mới kiểm
    quyền thì bất kỳ ai biết một UUID cũng dừng được lượt chat của người khác.
    """
    message = await _tao_message(session_factory, user_a, status=MessageStatus.STREAMING)

    resp = await client.post(DUONG_DAN.format(message.id), headers=_phien(user_b))

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "MESSAGE_NOT_FOUND"
    assert redis_gia.da_set == []


async def test_message_khong_ton_tai_tra_404(
    client: AsyncClient,
    user_a: uuid.UUID,
    _db_cua_test: None,
    redis_gia: RedisGia,
) -> None:
    resp = await client.post(DUONG_DAN.format(uuid.uuid4()), headers=_phien(user_a))

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "MESSAGE_NOT_FOUND"
    assert redis_gia.da_set == []


async def test_redis_chet_tra_503_co_ma_rieng(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_cua_test: None,
    redis_gia: RedisGia,
) -> None:
    """Redis hỏng là sự cố *phụ thuộc* → `503` thử lại được, không phải `500`."""
    message = await _tao_message(session_factory, user_a, status=MessageStatus.STREAMING)
    redis_gia.no_ra = True

    resp = await client.post(DUONG_DAN.format(message.id), headers=_phien(user_a))

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "CANCEL_FAILED"


async def test_debug_bat_cung_khong_mo_cua_nao(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    _db_cua_test: None,
    redis_gia: RedisGia,
) -> None:
    """`DEBUG=true` không còn mua được gì — T-3.1c.

    Tới T-3.1b, bật `DEBUG` là mở nhánh danh tính tạm của Phase 1: một header
    người gọi tự gõ đủ để đi hết đường này. Ca này canh đúng chiều ngược lại —
    nhánh ấy chết rồi, nên `DEBUG` không đổi được kết cục của một request
    không mang cookie phiên. Nó là bản đảo của ca cũ (`DEBUG=false` ⇒ `503`),
    và nó chính là thứ sẽ đỏ nếu ai đó dựng lại một cửa sau thứ hai.
    """
    monkeypatch.setattr(settings, "DEBUG", True)

    resp = await client.post(DUONG_DAN.format(uuid.uuid4()))

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"
    assert redis_gia.da_set == []
