"""T-1.7 — `GET /api/v1/messages/{id}/stream` (§7.2 ②, §18.2, §20).

Bốn dòng DoD của task nằm ở các test có chữ `DoD` trong docstring; phần còn
lại của DoD (`curl -kN` qua Nginx, hai `curl` song song, ngắt rồi nối lại) chỉ
chứng minh được trên hạ tầng thật nên nó nằm trong báo cáo, không ở đây.

Dùng `httpx.ASGITransport` chứ **không** `TestClient`: `TestClient` chạy app
trong một event loop khác (portal thread), mà fixture `connection` của
`conftest.py` là một kết nối asyncpg gắn với event loop của chính test. Chia
một kết nối cho hai loop là nguồn lỗi "attached to a different loop"; đi thẳng
qua ASGI giữ mọi thứ trong một loop.

Tới T-3.1b, danh tính của bộ test này là chỗ tạm của Phase 1 (một header
người gọi tự gõ, rồi một cookie dev — NQ-24/NQ-33), và tám ca dưới mục "danh
tính" canh đúng hai đường ấy. T-3.1c xoá nhánh tạm, nên tám ca đó đổi **cùng
một commit**: chúng vẫn ở đây, vẫn đúng tám, nhưng nay hỏi câu ngược lại —
*không* còn cửa thứ hai nào, kể cả khi `DEBUG=true`.
"""

from __future__ import annotations

import json
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
from app.streaming.producer import FIELD_DATA, FIELD_TYPE, stream_key

DUONG_DAN = "/api/v1/messages/{}/stream"


class RedisRong:
    """Redis giả: stream nào có trong `streams` thì có, còn lại là không tồn tại.

    `xread` luôn trả `None` (hết BLOCK) thay vì chờ thật — mọi test ở file này
    đi đường kết thúc ngay, và một `XREAD` chờ thật sẽ treo bộ test.
    """

    def __init__(self, streams: dict[str, list[tuple[str, dict[str, str]]]] | None = None) -> None:
        self.streams = streams or {}

    async def xrange(
        self, name: str, start: str, end: str, count: int | None = None
    ) -> list[tuple[str, dict[str, str]]]:
        moc = start[1:] if start.startswith("(") else start
        return [(eid, f) for eid, f in self.streams.get(name, []) if eid > moc]

    async def xread(self, streams: dict[str, str], **_: Any) -> None:
        return None

    async def exists(self, name: str) -> int:
        return 1 if name in self.streams else 0


@pytest.fixture
def _db_cua_test(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`session_scope()` trong handler trỏ vào ĐÚNG kết nối của test (NQ-17)."""
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


@pytest.fixture
def redis_gia(monkeypatch: pytest.MonkeyPatch) -> RedisRong:
    gia = RedisRong()
    monkeypatch.setattr("app.api.v1.stream.get_redis", lambda: gia)
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
    **cot: Any,
) -> Message:
    """Một message assistant có thật trong DB test, đã commit để handler thấy."""
    async with session_factory() as session:
        conversation = await ConversationRepository(session).create_conversation(user_id=user_id)
        message = await MessageRepository(session).create_message(
            conversation_id=conversation.id,
            user_id=user_id,
            role=MessageRole.ASSISTANT,
            status=cot.pop("status", MessageStatus.COMPLETED),
            content=cot.pop("content", ""),
            model_id=cot.pop("model_id", "mx"),
        )
        for ten, gia_tri in cot.items():
            setattr(message, ten, gia_tri)
        await session.commit()
        return message


def _su_kien(body: str) -> list[tuple[str, dict[str, Any]]]:
    """Thân SSE → danh sách `(event, data đã parse)`."""
    ra: list[tuple[str, dict[str, Any]]] = []
    for khung in body.split("\n\n"):
        loai = [d[7:] for d in khung.split("\n") if d.startswith("event: ")]
        data = [d[6:] for d in khung.split("\n") if d.startswith("data: ")]
        if loai:
            ra.append((loai[0], json.loads("\n".join(data))))
    return ra


# ═════════════════════════ quyền sở hữu (§20, DoD) ═════════════════════════


async def test_message_cua_user_khac_tra_404(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    _db_cua_test: None,
    redis_gia: RedisRong,
) -> None:
    """DoD: message của user khác → 404 (không phải 403 — xem docstring router)."""
    cua_a = await _tao_message(session_factory, user_a)

    resp = await client.get(DUONG_DAN.format(cua_a.id), headers=_phien(user_b))

    assert resp.status_code == 404


async def test_message_da_xoa_mem_tra_404(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_cua_test: None,
    redis_gia: RedisRong,
) -> None:
    message = await _tao_message(session_factory, user_a)
    async with session_factory() as session:
        await MessageRepository(session).soft_delete_message(message.id, user_id=user_a)
        await session.commit()

    resp = await client.get(DUONG_DAN.format(message.id), headers=_phien(user_a))

    assert resp.status_code == 404


async def test_message_khong_ton_tai_tra_404(
    client: AsyncClient,
    user_a: uuid.UUID,
    _db_cua_test: None,
    redis_gia: RedisRong,
) -> None:
    resp = await client.get(DUONG_DAN.format(uuid.uuid4()), headers=_phien(user_a))

    assert resp.status_code == 404


# ═════════════════ danh tính: MỘT đường duy nhất (core/deps.py) ════════════
#
# Tám ca dưới đây từng canh hai đường của nhánh danh tính tạm Phase 1 (header
# tự gõ, rồi cookie dev). T-3.1c xoá nhánh ấy; tám ca ở nguyên nhưng đảo câu
# hỏi — xem docstring module. Bốn ca đầu đo chính cookie phiên, bốn ca sau đo
# rằng KHÔNG có cửa thứ hai nào, kể cả khi `DEBUG=true`.


async def test_thieu_cookie_phien_tra_401(client: AsyncClient, _db_cua_test: None) -> None:
    assert (await client.get(DUONG_DAN.format(uuid.uuid4()))).status_code == 401


async def test_cookie_phien_hong_tra_401_chu_khong_422(
    client: AsyncClient, _db_cua_test: None
) -> None:
    """Cookie phiên có mặt nhưng không giải mã được ⇒ `401 UNAUTHENTICATED`.

    `422` sẽ là câu trả lời sai: một cookie hỏng không phải lỗi cú pháp của
    request, nó là một phiên không dùng được — và FE đọc `UNAUTHENTICATED` để
    đẩy người dùng ra màn đăng nhập (`StatusGate`).
    """
    resp = await client.get(
        DUONG_DAN.format(uuid.uuid4()), headers={"Cookie": f"{SESSION_COOKIE_NAME}=khong-phai-jwt"}
    )

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_cookie_phien_doc_duoc_message_cua_minh(
    client: AsyncClient,
    user_a: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
    _db_cua_test: None,
    redis_gia: RedisRong,
) -> None:
    """Điều kiện để `new EventSource(...)` của Phụ lục F chạy được.

    `EventSource` **không** đặt được header tuỳ chọn, nên cả trước lẫn sau
    T-3.1c danh tính của đường stream đều đi bằng cookie. Nếu ca này đỏ thì
    màn chat không stream được dòng nào.
    """
    message = await _tao_message(session_factory, user_a, status=MessageStatus.COMPLETED)

    resp = await client.get(DUONG_DAN.format(message.id), headers=_phien(user_a))

    assert resp.status_code == 200


async def test_cookie_phien_cua_nguoi_khac_khong_doc_duoc(
    client: AsyncClient,
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
    _db_cua_test: None,
    redis_gia: RedisRong,
) -> None:
    """Message của A, phiên của B ⇒ `404` (§20) — không phải `403`.

    Ca này thay ca *"header thắng cookie"* của T-1.14: khi chỉ còn một đường
    mang danh tính thì câu hỏi *"đường nào thắng"* biến mất, và thứ đáng canh
    còn lại là đường duy nhất ấy có kiểm quyền sở hữu hay không.
    """
    cua_a = await _tao_message(session_factory, user_a, status=MessageStatus.COMPLETED)

    resp = await client.get(DUONG_DAN.format(cua_a.id), headers=_phien(user_b))

    assert resp.status_code == 404


# ── không có cửa thứ hai: cookie lạ, và `DEBUG=true` ──


@pytest.mark.parametrize("gia_tri", ["khong-phai-uuid", "00000000-0000-4000-8000-000000000000"])
async def test_cookie_la_khong_doi_duoc_danh_tinh(
    client: AsyncClient,
    user_a: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
    gia_tri: str,
    _db_cua_test: None,
    redis_gia: RedisRong,
) -> None:
    """Một cookie lạ đi kèm phiên hợp lệ ⇒ vẫn là A, vẫn `200`.

    Trước T-3.1c, cookie thứ hai ấy CÓ nghĩa: nó là chỗ tạm của Phase 1, và cả
    hai giá trị dưới đây đều đổi được kết cục (một cái ra `422`, một cái đổi
    hẳn danh tính). Nay nó chỉ là một cookie không ai đọc — đó là điều ca này
    canh, và là thứ sẽ đỏ nếu ai đó dựng lại một đường thứ hai.
    """
    message = await _tao_message(session_factory, user_a, status=MessageStatus.COMPLETED)

    them = _phien(user_a)["Cookie"]
    resp = await client.get(
        DUONG_DAN.format(message.id),
        headers={"Cookie": f"scarlet_cookie_la={gia_tri}; {them}"},
    )

    assert resp.status_code == 200


async def test_cookie_la_mot_minh_tra_401(client: AsyncClient, _db_cua_test: None) -> None:
    """Chỉ một cookie lạ mang đúng một UUID ⇒ `401`, không phải một lối vào."""
    resp = await client.get(
        DUONG_DAN.format(uuid.uuid4()),
        headers={"Cookie": "scarlet_cookie_la=00000000-0000-4000-8000-000000000000"},
    )

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_debug_bat_cung_khong_mo_cua_nao(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, _db_cua_test: None
) -> None:
    """`DEBUG=true` không còn mua được gì — T-3.1c.

    Ca cũ ở đúng chỗ này bật `DEBUG=false` rồi đòi `503`: đó là phép đo của
    nhánh tạm, thứ nay đã chết. Bản đảo bật `DEBUG` LÊN rồi vẫn đòi `401`.
    """
    monkeypatch.setattr(settings, "DEBUG", True)

    resp = await client.get(DUONG_DAN.format(uuid.uuid4()))

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_debug_bat_va_cookie_la_van_401(
    client: AsyncClient, user_a: uuid.UUID, monkeypatch: pytest.MonkeyPatch, _db_cua_test: None
) -> None:
    """Hai nửa của nhánh tạm gộp lại cũng không mở được gì.

    `DEBUG=true` **và** một cookie mang đúng `user_id` của một người có thật —
    đúng cấu hình từng cho `200` trước T-3.1c. Lớp phòng thủ không được có cửa
    sau thứ hai, và đây là ca canh nó.
    """
    monkeypatch.setattr(settings, "DEBUG", True)

    resp = await client.get(
        DUONG_DAN.format(uuid.uuid4()), headers={"Cookie": f"scarlet_cookie_la={user_a}"}
    )

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


# ══════════════════════════════ cursor (C3) ════════════════════════════════


@pytest.mark.parametrize(
    ("headers", "params"),
    [({"Last-Event-ID": "khong-phai-id"}, {}), ({}, {"cursor": "$"})],
)
async def test_cursor_sai_dang_tra_400_truoc_khi_mo_stream(
    client: AsyncClient,
    user_a: uuid.UUID,
    headers: dict[str, str],
    params: dict[str, str],
    _db_cua_test: None,
    redis_gia: RedisRong,
) -> None:
    """400 phải ra TRƯỚC khi header `200 text/event-stream` đi — sau đó thì client không đọc nổi."""
    resp = await client.get(
        DUONG_DAN.format(uuid.uuid4()),
        headers=_phien(user_a) | headers,
        params=params,
    )

    assert resp.status_code == 400
    # Khung lỗi của §18 (B-86): mã nằm ở `error.code`, không phải `detail`.
    assert resp.json()["error"]["code"] == "CURSOR_INVALID"
    assert "cursor" in resp.json()["error"]["message"]


async def test_last_event_id_nhan_tiep_tu_do_khong_lap(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_cua_test: None,
    redis_gia: RedisRong,
) -> None:
    """DoD: chạy lại với `Last-Event-ID: <id-cuối>` → nhận TIẾP, không lặp (C3)."""
    message = await _tao_message(session_factory, user_a, status=MessageStatus.STREAMING)
    redis_gia.streams[stream_key(message.id)] = [
        ("1-0", {FIELD_TYPE: "delta", FIELD_DATA: '{"t":"mot"}'}),
        ("2-0", {FIELD_TYPE: "delta", FIELD_DATA: '{"t":"hai"}'}),
        ("3-0", {FIELD_TYPE: "done", FIELD_DATA: '{"finish_reason":"stop","usage":null}'}),
    ]

    resp = await client.get(
        DUONG_DAN.format(message.id),
        headers=_phien(user_a) | {"Last-Event-ID": "1-0"},
    )

    assert [loai for loai, _ in _su_kien(resp.text)] == ["delta", "done"]
    assert '{"t":"mot"}' not in resp.text


# ═══════════════════════ header SSE (C1) và nội dung ═══════════════════════


async def test_header_sse_du_ba_thu(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_cua_test: None,
    redis_gia: RedisRong,
) -> None:
    """`X-Accel-Buffering: no` là lớp thứ hai của C1, độc lập với nginx.conf."""
    message = await _tao_message(session_factory, user_a, content="xong roi")

    resp = await client.get(DUONG_DAN.format(message.id), headers=_phien(user_a))

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers["x-accel-buffering"] == "no"
    assert resp.headers["cache-control"] == "no-cache"


async def test_stream_het_ttl_nhung_completed_van_tra_du_content(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_cua_test: None,
    redis_gia: RedisRong,
) -> None:
    """DoD: message `completed` từ 2 giờ trước (stream hết TTL) → content đầy đủ + `done`."""
    message = await _tao_message(
        session_factory,
        user_a,
        content="Mùa thu 🍂 lá rụng",
        finish_reason="stop",
        prompt_tokens=12,
        completion_tokens=7,
    )
    assert stream_key(message.id) not in redis_gia.streams

    resp = await client.get(DUONG_DAN.format(message.id), headers=_phien(user_a))

    su_kien = _su_kien(resp.text)
    assert [loai for loai, _ in su_kien] == ["start", "delta", "done"]
    assert su_kien[1][1] == {"t": "Mùa thu 🍂 lá rụng"}
    assert su_kien[2][1] == {"finish_reason": "stop", "usage": {"in": 12, "out": 7}}
