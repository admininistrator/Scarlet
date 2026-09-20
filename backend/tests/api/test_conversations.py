"""B-93 — bốn endpoint hội thoại của §18.2 (`app/api/v1/conversations.py`).

Cùng lối đi với `test_messages.py`: `httpx.ASGITransport` (không `TestClient`,
vì `connection` của `conftest.py` là kết nối asyncpg gắn với event loop của
chính test), `DEBUG` bật tay, và `session_scope()` trong handler bị trỏ về đúng
kết nối của test.

Không có `arq_gia` ở đây: bốn endpoint này **không đẩy job nào**. Đó cũng là
một phần của phép kiểm — một `POST /conversations` chạm tới hàng đợi là dấu
hiệu ai đó đã trộn §7.2 ① vào nhầm chỗ.

**`conversations.updated_at` mặc định là `now()`, tức hằng số suốt một
transaction** (NQ-18 nói đúng chuyện này cho `messages.created_at`). Cả bộ test
chạy trong MỘT transaction, nên mọi hội thoại tạo ở đây sinh ra với cùng một
mốc thời gian và không phép kiểm sắp xếp nào có nghĩa. Vì thế `_dat_moc` đặt
`updated_at` tường minh — xem B-101.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import catalog
from app.config.settings import settings
from app.core.access_token import encode_access_token
from app.core.deps import SESSION_COOKIE_NAME
from app.db.models import Conversation, Message, MessageRole, MessageStatus, UserRole, UserStatus
from app.db.repositories import ConversationRepository, MessageRepository
from app.main import app

DUONG_DAN = "/api/v1/conversations"


@pytest.fixture
def _db_cua_test(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`session_scope()` trong handler trỏ vào ĐÚNG kết nối của test (NQ-17)."""
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


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


async def _tao_hoi_thoai(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID, **cot: Any
) -> Conversation:
    async with session_factory() as session:
        conversation = await ConversationRepository(session).create_conversation(
            user_id=user_id, **cot
        )
        await session.commit()
        return conversation


async def _dat_moc(
    session_factory: async_sessionmaker[AsyncSession],
    conversation_id: uuid.UUID,
    moc: datetime,
) -> None:
    """Đặt `updated_at` tường minh — xem docstring module."""
    async with session_factory() as session:
        await session.execute(
            update(Conversation).where(Conversation.id == conversation_id).values(updated_at=moc)
        )
        await session.commit()


async def _tao_message(
    session_factory: async_sessionmaker[AsyncSession],
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    role: MessageRole,
    parent_id: uuid.UUID | None,
    content: str,
    **cot: Any,
) -> Message:
    async with session_factory() as session:
        message = await MessageRepository(session).create_message(
            conversation_id=conversation_id,
            user_id=user_id,
            role=role,
            parent_id=parent_id,
            content=content,
            **cot,
        )
        await session.commit()
        return message


async def _tro_la(
    session_factory: async_sessionmaker[AsyncSession],
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    message_id: uuid.UUID,
) -> None:
    async with session_factory() as session:
        await ConversationRepository(session).set_active_leaf(
            conversation_id, user_id=user_id, message_id=message_id
        )
        await session.commit()


async def _dem_hoi_thoai(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> int:
    async with session_factory() as session:
        stmt = select(func.count()).select_from(Conversation).where(Conversation.user_id == user_id)
        return int((await session.execute(stmt)).scalar_one())


# ═══════════════════════════ POST /conversations ═══════════════════════════


@pytest.mark.usefixtures("_db_cua_test")
async def test_tao_hoi_thoai_rong_tra_201_va_active_leaf_null(
    client: AsyncClient, user_a: uuid.UUID, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """§18.2 "Tạo rỗng": có hàng trong DB, chưa message nào, chưa con trỏ nhánh."""
    res = await client.post(DUONG_DAN, json={"title": "buoi sang"}, headers=_phien(user_a))

    assert res.status_code == 201
    body = res.json()
    assert body["title"] == "buoi sang"
    assert body["active_leaf_id"] is None
    assert body["pinned"] is False

    async with session_factory() as session:
        row = await session.get(Conversation, uuid.UUID(body["id"]))
        assert row is not None and row.user_id == user_a


@pytest.mark.usefixtures("_db_cua_test")
async def test_tao_hoi_thoai_khong_can_body_nao_ca(client: AsyncClient, user_a: uuid.UUID) -> None:
    res = await client.post(DUONG_DAN, json={}, headers=_phien(user_a))

    assert res.status_code == 201
    assert res.json()["title"] is None


@pytest.mark.usefixtures("_db_cua_test")
async def test_default_model_co_trong_catalog_thi_duoc_ghi(
    client: AsyncClient, user_a: uuid.UUID, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    mac_dinh = catalog.get_default_model()
    assert mac_dinh is not None

    res = await client.post(DUONG_DAN, json={"default_model": mac_dinh.id}, headers=_phien(user_a))

    assert res.status_code == 201
    async with session_factory() as session:
        row = await session.get(Conversation, uuid.UUID(res.json()["id"]))
        assert row is not None and row.default_model == mac_dinh.id


@pytest.mark.usefixtures("_db_cua_test")
async def test_default_model_la_thi_400_va_KHONG_tao_hang_nao(
    client: AsyncClient, user_a: uuid.UUID, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Kiểm ngay lúc tạo: một hội thoại mang model không tồn tại là mìn hẹn giờ."""
    res = await client.post(
        DUONG_DAN, json={"default_model": "khong-co-model-nay"}, headers=_phien(user_a)
    )

    assert res.status_code == 400
    assert res.json()["error"]["code"] == "MODEL_UNKNOWN"
    assert await _dem_hoi_thoai(session_factory, user_a) == 0


@pytest.mark.usefixtures("_db_cua_test")
async def test_debug_bat_cung_khong_tao_duoc_gi_neu_khong_co_phien(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`DEBUG=true` không còn mua được gì — T-3.1c.

    Tới T-3.1b, bật `DEBUG` là mở nhánh danh tính tạm của Phase 1: một header
    người gọi tự gõ đủ để đi hết đường này. Ca này canh đúng chiều ngược lại —
    nhánh ấy chết rồi, nên `DEBUG` không đổi được kết cục của một request
    không mang cookie phiên. Nó là bản đảo của ca cũ (`DEBUG=false` ⇒ `503`),
    và nó chính là thứ sẽ đỏ nếu ai đó dựng lại một cửa sau thứ hai.
    """
    monkeypatch.setattr(settings, "DEBUG", True)

    res = await client.post(DUONG_DAN, json={})

    assert res.status_code == 401
    assert res.json()["error"]["code"] == "UNAUTHENTICATED"
    assert await _dem_hoi_thoai(session_factory, user_a) == 0


@pytest.mark.usefixtures("_db_cua_test")
async def test_thieu_cookie_phien_thi_401(client: AsyncClient) -> None:
    res = await client.post(DUONG_DAN, json={})

    assert res.status_code == 401
    assert res.json()["error"]["code"] == "UNAUTHENTICATED"


# ═══════════════════════════ GET /conversations ════════════════════════════


@pytest.mark.usefixtures("_db_cua_test")
async def test_danh_sach_moi_nhat_truoc(
    client: AsyncClient, user_a: uuid.UUID, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    goc = datetime(2026, 9, 15, 10, 0, tzinfo=UTC)
    ids = []
    for i in range(3):
        hoi_thoai = await _tao_hoi_thoai(session_factory, user_a, title=f"ht{i}")
        await _dat_moc(session_factory, hoi_thoai.id, goc + timedelta(minutes=i))
        ids.append(str(hoi_thoai.id))

    res = await client.get(DUONG_DAN, headers=_phien(user_a))

    assert res.status_code == 200
    assert [x["id"] for x in res.json()["items"]] == list(reversed(ids))


@pytest.mark.usefixtures("_db_cua_test")
async def test_danh_sach_chi_thay_hoi_thoai_cua_chinh_minh(
    client: AsyncClient,
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """§20 — lọc `user_id` trong SQL. Một dòng của người khác lọt ra là IDOR."""
    await _tao_hoi_thoai(session_factory, user_b, title="cua nguoi khac")
    cua_toi = await _tao_hoi_thoai(session_factory, user_a, title="cua toi")

    res = await client.get(DUONG_DAN, headers=_phien(user_a))

    assert [x["id"] for x in res.json()["items"]] == [str(cua_toi.id)]


@pytest.mark.usefixtures("_db_cua_test")
async def test_hoi_thoai_da_xoa_khong_con_trong_danh_sach(
    client: AsyncClient, user_a: uuid.UUID, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    hoi_thoai = await _tao_hoi_thoai(session_factory, user_a)
    await client.delete(f"{DUONG_DAN}/{hoi_thoai.id}", headers=_phien(user_a))

    res = await client.get(DUONG_DAN, headers=_phien(user_a))

    assert res.json()["items"] == []


@pytest.mark.usefixtures("_db_cua_test")
async def test_phan_trang_bang_con_tro_updated_at(
    client: AsyncClient, user_a: uuid.UUID, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Con trỏ, không phải OFFSET: trang 2 nối đúng sau trang 1, không lặp dòng."""
    goc = datetime(2026, 9, 15, 10, 0, tzinfo=UTC)
    ids = []
    for i in range(5):
        hoi_thoai = await _tao_hoi_thoai(session_factory, user_a, title=f"ht{i}")
        await _dat_moc(session_factory, hoi_thoai.id, goc + timedelta(minutes=i))
        ids.append(str(hoi_thoai.id))
    moi_nhat_truoc = list(reversed(ids))

    trang1 = (await client.get(DUONG_DAN, params={"limit": 2}, headers=_phien(user_a))).json()
    assert [x["id"] for x in trang1["items"]] == moi_nhat_truoc[:2]
    assert trang1["next_cursor"] is not None

    trang2 = (
        await client.get(
            DUONG_DAN,
            params={"limit": 2, "updated_before": trang1["next_cursor"]},
            headers=_phien(user_a),
        )
    ).json()
    assert [x["id"] for x in trang2["items"]] == moi_nhat_truoc[2:4]

    trang3 = (
        await client.get(
            DUONG_DAN,
            params={"limit": 2, "updated_before": trang2["next_cursor"]},
            headers=_phien(user_a),
        )
    ).json()
    assert [x["id"] for x in trang3["items"]] == moi_nhat_truoc[4:]
    assert trang3["next_cursor"] is None, "trang chua day thi khong moi client hoi them"


@pytest.mark.usefixtures("_db_cua_test")
async def test_danh_sach_rong_thi_next_cursor_la_null(
    client: AsyncClient, user_a: uuid.UUID
) -> None:
    res = await client.get(DUONG_DAN, headers=_phien(user_a))

    assert res.json() == {"items": [], "next_cursor": None}


@pytest.mark.usefixtures("_db_cua_test")
async def test_limit_vuot_tran_cau_hinh_thi_422(client: AsyncClient, user_a: uuid.UUID) -> None:
    """A3: trần là `settings.CONVERSATION_PAGE_SIZE`, không phải một số trong `.py`."""
    res = await client.get(
        DUONG_DAN,
        params={"limit": settings.CONVERSATION_PAGE_SIZE + 1},
        headers=_phien(user_a),
    )

    assert res.status_code == 422
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


# ═════════════════════════ GET /conversations/{id} ═════════════════════════


@pytest.mark.usefixtures("_db_cua_test")
async def test_chi_tiet_hoi_thoai_rong_thi_path_rong(
    client: AsyncClient, user_a: uuid.UUID, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    hoi_thoai = await _tao_hoi_thoai(session_factory, user_a)

    res = await client.get(f"{DUONG_DAN}/{hoi_thoai.id}", headers=_phien(user_a))

    assert res.status_code == 200
    assert res.json()["path"] == []
    assert res.json()["active_leaf_id"] is None


@pytest.mark.usefixtures("_db_cua_test")
async def test_chi_tiet_tra_DUONG_DI_chu_khong_phai_moi_message(
    client: AsyncClient, user_a: uuid.UUID, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """A2/C11 — cây có hai nhánh, chỉ nhánh đang xem được trả về.

    `WHERE conversation_id = ... ORDER BY created_at` sẽ trả cả 4 message và
    gửi cả nhánh người dùng đã bỏ lên model ở mọi lượt sau.
    """
    hoi_thoai = await _tao_hoi_thoai(session_factory, user_a)
    hoi = await _tao_message(
        session_factory,
        hoi_thoai.id,
        user_a,
        role=MessageRole.USER,
        parent_id=None,
        content="cau hoi",
    )
    tra_loi_1 = await _tao_message(
        session_factory,
        hoi_thoai.id,
        user_a,
        role=MessageRole.ASSISTANT,
        parent_id=hoi.id,
        content="nhanh mot",
    )
    tra_loi_2 = await _tao_message(
        session_factory,
        hoi_thoai.id,
        user_a,
        role=MessageRole.ASSISTANT,
        parent_id=hoi.id,
        content="nhanh hai",
    )
    await _tro_la(session_factory, hoi_thoai.id, user_a, tra_loi_2.id)

    path = (await client.get(f"{DUONG_DAN}/{hoi_thoai.id}", headers=_phien(user_a))).json()["path"]

    assert [x["id"] for x in path] == [str(hoi.id), str(tra_loi_2.id)]
    assert str(tra_loi_1.id) not in [x["id"] for x in path]
    assert [x["content"] for x in path] == ["cau hoi", "nhanh hai"]


@pytest.mark.usefixtures("_db_cua_test")
async def test_chi_tiet_mang_sibling_index_va_count(
    client: AsyncClient, user_a: uuid.UUID, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """C13 — hai số do SQL tính; `sibling_index` đếm từ 0 (B-60)."""
    hoi_thoai = await _tao_hoi_thoai(session_factory, user_a)
    hoi = await _tao_message(
        session_factory,
        hoi_thoai.id,
        user_a,
        role=MessageRole.USER,
        parent_id=None,
        content="q",
    )
    await _tao_message(
        session_factory,
        hoi_thoai.id,
        user_a,
        role=MessageRole.ASSISTANT,
        parent_id=hoi.id,
        content="a1",
    )
    a2 = await _tao_message(
        session_factory,
        hoi_thoai.id,
        user_a,
        role=MessageRole.ASSISTANT,
        parent_id=hoi.id,
        content="a2",
    )
    await _tro_la(session_factory, hoi_thoai.id, user_a, a2.id)

    path = (await client.get(f"{DUONG_DAN}/{hoi_thoai.id}", headers=_phien(user_a))).json()["path"]

    assert path[0]["sibling_index"] == 0 and path[0]["sibling_count"] == 1
    assert path[1]["sibling_index"] == 1 and path[1]["sibling_count"] == 2


@pytest.mark.usefixtures("_db_cua_test")
async def test_chi_tiet_khong_lo_cot_van_hanh(
    client: AsyncClient, user_a: uuid.UUID, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`raw_response`/`tool_calls`/`heartbeat_at` không được ra khỏi server."""
    hoi_thoai = await _tao_hoi_thoai(session_factory, user_a)
    hoi = await _tao_message(
        session_factory,
        hoi_thoai.id,
        user_a,
        role=MessageRole.USER,
        parent_id=None,
        content="q",
    )
    await _tro_la(session_factory, hoi_thoai.id, user_a, hoi.id)

    path = (await client.get(f"{DUONG_DAN}/{hoi_thoai.id}", headers=_phien(user_a))).json()["path"]

    cam = {"raw_response", "tool_calls", "heartbeat_at", "prompt_tokens", "completion_tokens"}
    assert cam.isdisjoint(path[0].keys())


@pytest.mark.usefixtures("_db_cua_test")
async def test_chi_tiet_message_dang_streaming_van_nam_trong_path(
    client: AsyncClient, user_a: uuid.UUID, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """T-1.14 mở lại tab giữa lúc stream: phần đã ghi phải có mặt ngay."""
    hoi_thoai = await _tao_hoi_thoai(session_factory, user_a)
    hoi = await _tao_message(
        session_factory,
        hoi_thoai.id,
        user_a,
        role=MessageRole.USER,
        parent_id=None,
        content="q",
    )
    dang_chay = await _tao_message(
        session_factory,
        hoi_thoai.id,
        user_a,
        role=MessageRole.ASSISTANT,
        parent_id=hoi.id,
        content="phan da ghi",
        status=MessageStatus.STREAMING,
    )
    await _tro_la(session_factory, hoi_thoai.id, user_a, dang_chay.id)

    path = (await client.get(f"{DUONG_DAN}/{hoi_thoai.id}", headers=_phien(user_a))).json()["path"]

    assert path[-1]["status"] == "streaming"
    assert path[-1]["content"] == "phan da ghi"


@pytest.mark.usefixtures("_db_cua_test")
async def test_chi_tiet_cua_nguoi_khac_thi_404(
    client: AsyncClient,
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """§20 — 404 chứ không 403: 403 xác nhận hội thoại đó có thật."""
    cua_b = await _tao_hoi_thoai(session_factory, user_b)

    res = await client.get(f"{DUONG_DAN}/{cua_b.id}", headers=_phien(user_a))

    assert res.status_code == 404
    assert res.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"


@pytest.mark.usefixtures("_db_cua_test")
async def test_chi_tiet_hoi_thoai_khong_ton_tai_thi_404(
    client: AsyncClient, user_a: uuid.UUID
) -> None:
    res = await client.get(f"{DUONG_DAN}/{uuid.uuid4()}", headers=_phien(user_a))

    assert res.status_code == 404


# ═══════════════════════ DELETE /conversations/{id} ════════════════════════


@pytest.mark.usefixtures("_db_cua_test")
async def test_xoa_mem_tra_204_va_message_van_con_trong_db(
    client: AsyncClient, user_a: uuid.UUID, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """C12 — xoá hội thoại KHÔNG được đụng tới cây message bên dưới."""
    hoi_thoai = await _tao_hoi_thoai(session_factory, user_a)
    hoi = await _tao_message(
        session_factory,
        hoi_thoai.id,
        user_a,
        role=MessageRole.USER,
        parent_id=None,
        content="q",
    )

    res = await client.delete(f"{DUONG_DAN}/{hoi_thoai.id}", headers=_phien(user_a))

    assert res.status_code == 204
    assert res.content == b""
    async with session_factory() as session:
        row = await session.get(Conversation, hoi_thoai.id)
        assert row is not None and row.deleted_at is not None, "xoa MEM, hang van con"
        message = await session.get(Message, hoi.id)
        assert message is not None and message.deleted_at is None


@pytest.mark.usefixtures("_db_cua_test")
async def test_xoa_lan_thu_hai_thi_404(
    client: AsyncClient, user_a: uuid.UUID, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    hoi_thoai = await _tao_hoi_thoai(session_factory, user_a)
    await client.delete(f"{DUONG_DAN}/{hoi_thoai.id}", headers=_phien(user_a))

    lan_hai = await client.delete(f"{DUONG_DAN}/{hoi_thoai.id}", headers=_phien(user_a))

    assert lan_hai.status_code == 404
    assert lan_hai.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"


@pytest.mark.usefixtures("_db_cua_test")
async def test_xoa_roi_thi_GET_cung_404(
    client: AsyncClient, user_a: uuid.UUID, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    hoi_thoai = await _tao_hoi_thoai(session_factory, user_a)
    await client.delete(f"{DUONG_DAN}/{hoi_thoai.id}", headers=_phien(user_a))

    res = await client.get(f"{DUONG_DAN}/{hoi_thoai.id}", headers=_phien(user_a))

    assert res.status_code == 404


@pytest.mark.usefixtures("_db_cua_test")
async def test_khong_xoa_duoc_hoi_thoai_cua_nguoi_khac(
    client: AsyncClient,
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    cua_b = await _tao_hoi_thoai(session_factory, user_b)

    res = await client.delete(f"{DUONG_DAN}/{cua_b.id}", headers=_phien(user_a))

    assert res.status_code == 404
    async with session_factory() as session:
        row = await session.get(Conversation, cua_b.id)
        assert row is not None and row.deleted_at is None, "hang cua nguoi khac KHONG duoc dung"
