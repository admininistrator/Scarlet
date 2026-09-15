"""T-1.7 — `GET /api/v1/messages/{id}/stream` (§7.2 ②, §18.2, §20).

Bốn dòng DoD của task nằm ở các test có chữ `DoD` trong docstring; phần còn
lại của DoD (`curl -kN` qua Nginx, hai `curl` song song, ngắt rồi nối lại) chỉ
chứng minh được trên hạ tầng thật nên nó nằm trong báo cáo, không ở đây.

Dùng `httpx.ASGITransport` chứ **không** `TestClient`: `TestClient` chạy app
trong một event loop khác (portal thread), mà fixture `connection` của
`conftest.py` là một kết nối asyncpg gắn với event loop của chính test. Chia
một kết nối cho hai loop là nguồn lỗi "attached to a different loop"; đi thẳng
qua ASGI giữ mọi thứ trong một loop.

Bộ test chạy với `DEBUG=False` (conftest chỉ đặt biến BẮT BUỘC), nên
`_debug_bat` phải bật tay — và nhờ vậy chiều nguy hiểm của `app/core/deps.py`
(`DEBUG=false` → 503) kiểm được mà không phải dựng thêm gì.
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
from app.db.models import Message, MessageRole, MessageStatus
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
def _debug_bat(monkeypatch: pytest.MonkeyPatch) -> None:
    """Phase 1 chỉ chạy với `DEBUG=true` — xem `app/core/deps.py`."""
    monkeypatch.setattr(settings, "DEBUG", True)


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
    _debug_bat: None,
    _db_cua_test: None,
    redis_gia: RedisRong,
) -> None:
    """DoD: message của user khác → 404 (không phải 403 — xem docstring router)."""
    cua_a = await _tao_message(session_factory, user_a)

    resp = await client.get(DUONG_DAN.format(cua_a.id), headers={"X-User-Id": str(user_b)})

    assert resp.status_code == 404


async def test_message_da_xoa_mem_tra_404(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    redis_gia: RedisRong,
) -> None:
    message = await _tao_message(session_factory, user_a)
    async with session_factory() as session:
        await MessageRepository(session).soft_delete_message(message.id, user_id=user_a)
        await session.commit()

    resp = await client.get(DUONG_DAN.format(message.id), headers={"X-User-Id": str(user_a)})

    assert resp.status_code == 404


async def test_message_khong_ton_tai_tra_404(
    client: AsyncClient,
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    redis_gia: RedisRong,
) -> None:
    resp = await client.get(DUONG_DAN.format(uuid.uuid4()), headers={"X-User-Id": str(user_a)})

    assert resp.status_code == 404


# ═══════════════════ danh tính tạm của Phase 1 (core/deps.py) ══════════════


async def test_thieu_x_user_id_tra_401(
    client: AsyncClient, _debug_bat: None, _db_cua_test: None
) -> None:
    assert (await client.get(DUONG_DAN.format(uuid.uuid4()))).status_code == 401


async def test_debug_tat_thi_503_chu_khong_phai_mo_cua(
    client: AsyncClient, user_a: uuid.UUID, _db_cua_test: None
) -> None:
    """Không bật `_debug_bat`: đây là cấu hình của một máy mới (`.env.example`).

    Chỗ tạm của Phase 1 phải CHẾT khi `DEBUG=false`, không được im lặng cho qua
    — im lặng nghĩa là mọi hội thoại thành công khai cho tới khi T-2.3 xong.
    """
    assert settings.DEBUG is False

    resp = await client.get(DUONG_DAN.format(uuid.uuid4()), headers={"X-User-Id": str(user_a)})

    assert resp.status_code == 503


async def test_x_user_id_khong_phai_uuid_tra_422(
    client: AsyncClient, _debug_bat: None, _db_cua_test: None
) -> None:
    resp = await client.get(DUONG_DAN.format(uuid.uuid4()), headers={"X-User-Id": "khong-phai"})

    assert resp.status_code == 422


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
    _debug_bat: None,
    _db_cua_test: None,
    redis_gia: RedisRong,
) -> None:
    """400 phải ra TRƯỚC khi header `200 text/event-stream` đi — sau đó thì client không đọc nổi."""
    resp = await client.get(
        DUONG_DAN.format(uuid.uuid4()),
        headers={"X-User-Id": str(user_a), **headers},
        params=params,
    )

    assert resp.status_code == 400
    assert "cursor" in resp.json()["detail"]


async def test_last_event_id_nhan_tiep_tu_do_khong_lap(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
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
        headers={"X-User-Id": str(user_a), "Last-Event-ID": "1-0"},
    )

    assert [loai for loai, _ in _su_kien(resp.text)] == ["delta", "done"]
    assert '{"t":"mot"}' not in resp.text


# ═══════════════════════ header SSE (C1) và nội dung ═══════════════════════


async def test_header_sse_du_ba_thu(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    redis_gia: RedisRong,
) -> None:
    """`X-Accel-Buffering: no` là lớp thứ hai của C1, độc lập với nginx.conf."""
    message = await _tao_message(session_factory, user_a, content="xong roi")

    resp = await client.get(DUONG_DAN.format(message.id), headers={"X-User-Id": str(user_a)})

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers["x-accel-buffering"] == "no"
    assert resp.headers["cache-control"] == "no-cache"


async def test_stream_het_ttl_nhung_completed_van_tra_du_content(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
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

    resp = await client.get(DUONG_DAN.format(message.id), headers={"X-User-Id": str(user_a)})

    su_kien = _su_kien(resp.text)
    assert [loai for loai, _ in su_kien] == ["start", "delta", "done"]
    assert su_kien[1][1] == {"t": "Mùa thu 🍂 lá rụng"}
    assert su_kien[2][1] == {"finish_reason": "stop", "usage": {"in": 12, "out": 7}}
