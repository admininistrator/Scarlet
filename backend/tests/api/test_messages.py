"""T-1.8 — `POST /api/v1/conversations/{id}/messages` (§7.2 ①, §18.2, C14).

Ba dòng DoD của task nằm ở các test có chữ `DoD` trong docstring. Dòng thứ tư
(`curl -w "%{time_total}"` < 200 ms) đo cả chặng Nginx nên nó chỉ chứng minh
được trên hạ tầng thật — output nằm trong báo cáo, không ở đây.

Cùng lối đi với `test_stream.py`: `httpx.ASGITransport` (không `TestClient`,
vì `connection` của `conftest.py` là kết nối asyncpg gắn với event loop của
chính test), `DEBUG` bật tay, và `session_scope()` trong handler bị trỏ về
đúng kết nối của test.

`arq_gia` thay chỗ `get_arq_pool` là bắt buộc chứ không phải tiện: pool thật
nối tới `redis:6379`, một host chỉ phân giải được **bên trong** network
`internal` của compose — `make test` chạy từ WSL host. Và nó cho phép dựng
đúng ca DoD cuối: ép enqueue thất bại rồi đếm hàng trong DB.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import catalog
from app.config.settings import settings
from app.db.models import Conversation, Message, MessageRole, MessageStatus
from app.db.repositories import ConversationRepository, MessageRepository
from app.main import app

DUONG_DAN = "/api/v1/conversations/{}/messages"


class ArqGia:
    """Pool arq giả: ghi lại mọi lần enqueue, có công tắc để ép nó ném.

    `no_ra` mô phỏng Redis chết giữa bước ④ của §7.2 ①; `tra_none` mô phỏng
    arq từ chối job (trùng `_job_id`) — hai ngả khác nhau nhưng cùng phải dẫn
    tới "không có message mồ côi".
    """

    def __init__(self) -> None:
        self.da_day: list[tuple[str, tuple[Any, ...]]] = []
        self.no_ra = False
        self.tra_none = False

    async def enqueue_job(self, ten: str, *args: Any, **_: Any) -> object | None:
        if self.no_ra:
            raise ConnectionError("redis chet giua chung (gia lap)")
        self.da_day.append((ten, args))
        return None if self.tra_none else object()


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


@pytest_asyncio.fixture
async def arq_gia(monkeypatch: pytest.MonkeyPatch) -> ArqGia:
    gia = ArqGia()

    async def _pool() -> ArqGia:
        return gia

    monkeypatch.setattr("app.api.v1.messages.get_arq_pool", _pool)
    return gia


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as http:
        yield http


async def _tao_hoi_thoai(
    session_factory: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
    **cot: Any,
) -> Conversation:
    async with session_factory() as session:
        conversation = await ConversationRepository(session).create_conversation(
            user_id=user_id, **cot
        )
        await session.commit()
        return conversation


async def _dem_message(
    session_factory: async_sessionmaker[AsyncSession], conversation_id: uuid.UUID
) -> int:
    async with session_factory() as session:
        stmt = (
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == conversation_id)
        )
        return int((await session.execute(stmt)).scalar_one())


async def _doc_message(
    session_factory: async_sessionmaker[AsyncSession], message_id: uuid.UUID
) -> Message:
    async with session_factory() as session:
        message = await session.get(Message, message_id)
        assert message is not None
        return message


async def _active_leaf(
    session_factory: async_sessionmaker[AsyncSession], conversation_id: uuid.UUID
) -> uuid.UUID | None:
    async with session_factory() as session:
        stmt = select(Conversation.active_leaf_id).where(Conversation.id == conversation_id)
        return (await session.execute(stmt)).scalar_one()


def _mot_model_khac_mac_dinh() -> str:
    """Một `model_id` đang bật, KHÁC model `default`. A3: không gõ tên vào đây."""
    mac_dinh = catalog.get_default_model()
    assert mac_dinh is not None
    khac = [m.id for m in catalog.get_catalog().models if m.enabled and m.id != mac_dinh.id]
    assert khac, "catalog phải có ít nhất hai model bật thì test này mới có nghĩa"
    return khac[0]


# ════════════════════════ đường chạy đúng (§7.2 ①) ════════════════════════


async def test_tao_hai_message_va_day_job(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """Một POST ⇒ 202, hai message, một job, `active_leaf_id` dời sang assistant."""
    conversation = await _tao_hoi_thoai(session_factory, user_a)

    resp = await client.post(
        DUONG_DAN.format(conversation.id),
        headers={"X-User-Id": str(user_a)},
        json={"content": "xin chao"},
    )

    assert resp.status_code == 202
    body = resp.json()
    uid = uuid.UUID(body["user_message_id"])
    amid = uuid.UUID(body["assistant_message_id"])

    user_message = await _doc_message(session_factory, uid)
    assert user_message.role is MessageRole.USER
    assert user_message.content == "xin chao"
    assert user_message.parent_id is None, "hội thoại rỗng ⇒ message đầu là gốc (§8.2)"

    assistant = await _doc_message(session_factory, amid)
    assert assistant.role is MessageRole.ASSISTANT
    assert assistant.parent_id == uid
    assert assistant.content == ""

    assert await _active_leaf(session_factory, conversation.id) == amid
    assert arq_gia.da_day == [("generate", (str(amid),))]


async def test_assistant_o_trang_thai_queued(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """`queued` chứ không phải DEFAULT `completed` của cột.

    `mark_streaming` có `WHERE status='queued'`; để mặc định thì worker nhận
    job xong bỏ lượt, và message rỗng ấy lại **vào ngữ cảnh** của lượt sau vì
    `USABLE_STATUSES` nhận `completed`.
    """
    conversation = await _tao_hoi_thoai(session_factory, user_a)

    resp = await client.post(
        DUONG_DAN.format(conversation.id),
        headers={"X-User-Id": str(user_a)},
        json={"content": "hoi mot cau"},
    )

    assistant = await _doc_message(session_factory, uuid.UUID(resp.json()["assistant_message_id"]))
    assert assistant.status is MessageStatus.QUEUED


async def test_stream_url_tro_dung_route_cua_t17(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """`stream_url` phải gọi được thật, không chỉ "trông giống đường dẫn"."""
    conversation = await _tao_hoi_thoai(session_factory, user_a)

    resp = await client.post(
        DUONG_DAN.format(conversation.id),
        headers={"X-User-Id": str(user_a)},
        json={"content": "xin chao"},
    )
    amid = resp.json()["assistant_message_id"]
    stream_url = resp.json()["stream_url"]

    assert stream_url == f"/api/v1/messages/{amid}/stream"
    # Gọi thẳng vào nó: 404 (message của user khác) sẽ lộ ra nếu đường dẫn sai
    # tiền tố, 200/500 nếu đúng. Chỉ cần nó KHÔNG phải 404-không-có-route.
    lan_hai = await client.get(stream_url, headers={"X-User-Id": str(uuid.uuid4())})
    assert lan_hai.json()["error"]["code"] == "MESSAGE_NOT_FOUND"


# ═══════════════════════ A1 — không gọi model ở đây ═══════════════════════


async def test_khong_cho_model_sinh_chu(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """DoD/A1: response về khi `content` của assistant vẫn còn rỗng.

    Đây là phát biểu kiểm được của "endpoint trả về < 200 ms": nếu handler
    chờ model thì lúc nó trả lời, `messages.content` đã có chữ.
    """
    conversation = await _tao_hoi_thoai(session_factory, user_a)

    resp = await client.post(
        DUONG_DAN.format(conversation.id),
        headers={"X-User-Id": str(user_a)},
        json={"content": "viet cho toi 800 tu"},
    )

    assistant = await _doc_message(session_factory, uuid.UUID(resp.json()["assistant_message_id"]))
    assert assistant.content == ""
    assert assistant.status is MessageStatus.QUEUED
    assert assistant.finish_reason is None
    assert assistant.prompt_tokens is None


# ═════════════════════════ nhánh (C14, §8.2) ══════════════════════════════


async def test_parent_id_cu_tra_branched_va_cay_co_them_nhanh(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """DoD: gửi với `parent_id` cũ → `branched: true`, và cây có thêm nhánh."""
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    headers = {"X-User-Id": str(user_a)}

    mot = await client.post(
        DUONG_DAN.format(conversation.id), headers=headers, json={"content": "a"}
    )
    assert mot.json()["branched"] is False
    goc_user = uuid.UUID(mot.json()["user_message_id"])

    hai = await client.post(
        DUONG_DAN.format(conversation.id),
        headers=headers,
        json={"content": "b", "parent_id": str(goc_user)},
    )

    assert hai.status_code == 202
    assert hai.json()["branched"] is True

    # Message user của lượt 1 nay có HAI con: assistant của lượt 1, và message
    # user của lượt 2. Đó đúng là "cây có thêm nhánh".
    async with session_factory() as session:
        con = await MessageRepository(session).get_siblings(
            conversation.id, goc_user, user_id=user_a
        )
    assert len(con) == 2
    assert {m.id for m in con} == {
        uuid.UUID(mot.json()["assistant_message_id"]),
        uuid.UUID(hai.json()["user_message_id"]),
    }


async def test_parent_id_bang_leaf_hien_tai_khong_phai_nhanh(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """Gửi kèm `parent_id` ĐÚNG lá đang xem ⇒ `branched: false` (C14).

    C14 nói FE **luôn** gửi lá nó đang thấy; nếu mọi lần gửi đều bị gắn cờ
    `branched` thì cờ đó vô nghĩa và FE sẽ tắt nó đi.
    """
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    headers = {"X-User-Id": str(user_a)}

    mot = await client.post(
        DUONG_DAN.format(conversation.id), headers=headers, json={"content": "a"}
    )
    leaf = mot.json()["assistant_message_id"]

    hai = await client.post(
        DUONG_DAN.format(conversation.id),
        headers=headers,
        json={"content": "b", "parent_id": leaf},
    )

    assert hai.json()["branched"] is False


async def test_parent_id_vang_thi_noi_vao_leaf_dang_xem(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """Không gửi `parent_id` ⇒ dùng `active_leaf_id`, không phải `NULL`.

    Đây là chỗ `model_fields_set` khác `is None`: nếu handler đọc `parent_id`
    bằng `or active_leaf_id` thì `parent_id: null` (gốc nhánh mới) và "vắng
    hẳn" biến thành cùng một chuyện, và mọi lượt chat thứ hai sẽ thành một GỐC
    mới — hội thoại rơi thành N cây rời, model không thấy câu hỏi trước đó.
    """
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    headers = {"X-User-Id": str(user_a)}

    mot = await client.post(
        DUONG_DAN.format(conversation.id), headers=headers, json={"content": "a"}
    )
    leaf = uuid.UUID(mot.json()["assistant_message_id"])

    hai = await client.post(
        DUONG_DAN.format(conversation.id), headers=headers, json={"content": "b"}
    )

    user_hai = await _doc_message(session_factory, uuid.UUID(hai.json()["user_message_id"]))
    assert user_hai.parent_id == leaf
    assert hai.json()["branched"] is False


async def test_parent_id_null_tuong_minh_tao_goc_moi(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """`parent_id: null` gửi tường minh ⇒ gốc thứ hai của hội thoại (§8.2)."""
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    headers = {"X-User-Id": str(user_a)}

    await client.post(DUONG_DAN.format(conversation.id), headers=headers, json={"content": "a"})
    hai = await client.post(
        DUONG_DAN.format(conversation.id),
        headers=headers,
        json={"content": "b", "parent_id": None},
    )

    assert hai.json()["branched"] is True
    user_hai = await _doc_message(session_factory, uuid.UUID(hai.json()["user_message_id"]))
    assert user_hai.parent_id is None

    async with session_factory() as session:
        goc = await MessageRepository(session).get_siblings(conversation.id, None, user_id=user_a)
    assert len(goc) == 2, "hai gốc trong một hội thoại — §8.2 cho phép"


async def test_parent_id_cua_hoi_thoai_khac_tra_404(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """Nối hai cây của hai hội thoại làm một là đúng thứ `create_message` chặn."""
    mot = await _tao_hoi_thoai(session_factory, user_a)
    hai = await _tao_hoi_thoai(session_factory, user_a)
    headers = {"X-User-Id": str(user_a)}

    trong_mot = await client.post(DUONG_DAN.format(mot.id), headers=headers, json={"content": "a"})
    la_cua_mot = trong_mot.json()["assistant_message_id"]

    resp = await client.post(
        DUONG_DAN.format(hai.id),
        headers=headers,
        json={"content": "b", "parent_id": la_cua_mot},
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PARENT_NOT_FOUND"
    assert await _dem_message(session_factory, hai.id) == 0


# ═══════════════════ quyền sở hữu và danh tính (§20) ══════════════════════


async def test_hoi_thoai_cua_user_khac_tra_404_va_khong_ghi_gi(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """404 chứ không 403, và tuyệt đối không có hàng nào được ghi."""
    cua_a = await _tao_hoi_thoai(session_factory, user_a)

    resp = await client.post(
        DUONG_DAN.format(cua_a.id),
        headers={"X-User-Id": str(user_b)},
        json={"content": "toi khong so huu hoi thoai nay"},
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"
    assert await _dem_message(session_factory, cua_a.id) == 0
    assert arq_gia.da_day == []


async def test_hoi_thoai_khong_ton_tai_tra_404(
    client: AsyncClient,
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    resp = await client.post(
        DUONG_DAN.format(uuid.uuid4()),
        headers={"X-User-Id": str(user_a)},
        json={"content": "a"},
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"


async def test_thieu_x_user_id_tra_401(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    conversation = await _tao_hoi_thoai(session_factory, user_a)

    resp = await client.post(DUONG_DAN.format(conversation.id), json={"content": "a"})

    assert resp.status_code == 401
    assert await _dem_message(session_factory, conversation.id) == 0


async def test_debug_tat_thi_503(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """Không bật `_debug_bat` — cấu hình của một máy mới (`.env.example`)."""
    assert settings.DEBUG is False
    conversation = await _tao_hoi_thoai(session_factory, user_a)

    resp = await client.post(
        DUONG_DAN.format(conversation.id),
        headers={"X-User-Id": str(user_a)},
        json={"content": "a"},
    )

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "AUTH_NOT_IMPLEMENTED"


# ════════════════════════ chọn model (§9.2, A3) ═══════════════════════════


async def test_khong_noi_model_thi_dung_default_cua_catalog(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    mac_dinh = catalog.get_default_model()
    assert mac_dinh is not None

    resp = await client.post(
        DUONG_DAN.format(conversation.id),
        headers={"X-User-Id": str(user_a)},
        json={"content": "a"},
    )

    assistant = await _doc_message(session_factory, uuid.UUID(resp.json()["assistant_message_id"]))
    assert assistant.model_id == mac_dinh.id


async def test_default_model_cua_hoi_thoai_thang_default_cua_catalog(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    khac = _mot_model_khac_mac_dinh()
    conversation = await _tao_hoi_thoai(session_factory, user_a, default_model=khac)

    resp = await client.post(
        DUONG_DAN.format(conversation.id),
        headers={"X-User-Id": str(user_a)},
        json={"content": "a"},
    )

    assistant = await _doc_message(session_factory, uuid.UUID(resp.json()["assistant_message_id"]))
    assert assistant.model_id == khac


async def test_model_id_cua_request_thang_tat_ca(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    mac_dinh = catalog.get_default_model()
    assert mac_dinh is not None
    conversation = await _tao_hoi_thoai(session_factory, user_a, default_model=mac_dinh.id)
    khac = _mot_model_khac_mac_dinh()

    resp = await client.post(
        DUONG_DAN.format(conversation.id),
        headers={"X-User-Id": str(user_a)},
        json={"content": "a", "model_id": khac},
    )

    assistant = await _doc_message(session_factory, uuid.UUID(resp.json()["assistant_message_id"]))
    assert assistant.model_id == khac


async def test_model_khong_co_trong_catalog_tra_400_va_khong_ghi_gi(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    conversation = await _tao_hoi_thoai(session_factory, user_a)

    resp = await client.post(
        DUONG_DAN.format(conversation.id),
        headers={"X-User-Id": str(user_a)},
        json={"content": "a", "model_id": "khong-ton-tai"},
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "MODEL_UNKNOWN"
    assert resp.json()["error"]["details"] == {"model_id": "khong-ton-tai"}
    assert await _dem_message(session_factory, conversation.id) == 0


async def test_model_da_tat_cung_tra_400(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """`enabled: false` phải chặn cả đường gọi, không chỉ ẩn khỏi Model Picker."""
    khac = _mot_model_khac_mac_dinh()
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    monkeypatch.setattr(catalog, "get_model", lambda _: None)

    resp = await client.post(
        DUONG_DAN.format(conversation.id),
        headers={"X-User-Id": str(user_a)},
        json={"content": "a", "model_id": khac},
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "MODEL_UNKNOWN"


async def test_khong_con_model_nao_bat_tra_503(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """Sự cố cấu hình phía server ⇒ 5xx, không phải 4xx của người gọi."""
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    monkeypatch.setattr(catalog, "get_default_model", lambda: None)

    resp = await client.post(
        DUONG_DAN.format(conversation.id),
        headers={"X-User-Id": str(user_a)},
        json={"content": "a"},
    )

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "NO_MODEL_AVAILABLE"
    assert await _dem_message(session_factory, conversation.id) == 0


# ════════════ DoD: lỗi giữa transaction ⇒ KHÔNG có message mồ côi ═════════


async def test_enqueue_no_thi_khong_con_message_mo_coi(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """DoD: ép enqueue thất bại → 0 message, `active_leaf_id` không nhúc nhích.

    Đây là lý do `enqueue` nằm TRONG transaction. Đảo lại (commit trước,
    enqueue sau) thì ca này để lại hai message `queued` **vĩnh viễn**: reaper
    §7.6 chỉ dọn `status='streaming'`.
    """
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    arq_gia.no_ra = True

    resp = await client.post(
        DUONG_DAN.format(conversation.id),
        headers={"X-User-Id": str(user_a)},
        json={"content": "a"},
    )

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "ENQUEUE_FAILED"
    assert await _dem_message(session_factory, conversation.id) == 0
    assert await _active_leaf(session_factory, conversation.id) is None


async def test_arq_tu_choi_job_thi_cung_khong_con_message_mo_coi(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """Ngả thứ hai: `enqueue_job` trả `None` thay vì ném — cũng phải rollback."""
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    arq_gia.tra_none = True

    resp = await client.post(
        DUONG_DAN.format(conversation.id),
        headers={"X-User-Id": str(user_a)},
        json={"content": "a"},
    )

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "ENQUEUE_FAILED"
    assert await _dem_message(session_factory, conversation.id) == 0
    assert await _active_leaf(session_factory, conversation.id) is None


# ═════════════════════ body và Idempotency-Key (§11.4) ════════════════════


@pytest.mark.parametrize("body", [{}, {"content": ""}, {"content": "a", "parent_id": "khong-uuid"}])
async def test_body_sai_tra_422(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    body: dict[str, Any],
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    conversation = await _tao_hoi_thoai(session_factory, user_a)

    resp = await client.post(
        DUONG_DAN.format(conversation.id), headers={"X-User-Id": str(user_a)}, json=body
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
    assert await _dem_message(session_factory, conversation.id) == 0


async def test_idempotency_key_duoc_doc_va_log_chu_chua_xu_ly(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """T-1.8 chỉ log; T-2.8 mới chống trùng. Gửi HAI lần cùng key ⇒ HAI message.

    Ca này cố ý khẳng định hành vi **chưa đúng** của §11.4, để khi T-2.8 làm
    xong thì chính test này đỏ và buộc người viết sửa nó — thay vì để một hành
    vi tạm lặng lẽ sống tiếp.
    """
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    headers = {"X-User-Id": str(user_a), "Idempotency-Key": "khoa-cua-mot-lan-soan-thao"}

    with caplog.at_level("INFO", logger="app.api.v1.messages"):
        mot = await client.post(
            DUONG_DAN.format(conversation.id), headers=headers, json={"content": "a"}
        )
        hai = await client.post(
            DUONG_DAN.format(conversation.id), headers=headers, json={"content": "a"}
        )

    assert mot.status_code == hai.status_code == 202
    assert mot.json()["assistant_message_id"] != hai.json()["assistant_message_id"]
    assert await _dem_message(session_factory, conversation.id) == 4
    assert "khoa-cua-mot-lan-soan-thao" in caplog.text
    assert "T-2.8" in caplog.text


async def test_khong_co_idempotency_key_van_chay(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """§18.2 ghi header này là bắt buộc, nhưng **T-2.8** mới ép. Ở đây: 202."""
    conversation = await _tao_hoi_thoai(session_factory, user_a)

    resp = await client.post(
        DUONG_DAN.format(conversation.id),
        headers={"X-User-Id": str(user_a)},
        json={"content": "a"},
    )

    assert resp.status_code == 202


# ═══════════════ A1 dạng kiểm được bằng grep (§5.3, DoD) ══════════════════


def test_tang_api_khong_import_gi_cua_provider() -> None:
    """DoD: `grep -rnE "litellm|openai|AsyncOpenAI" backend/app/api/` phải rỗng.

    Chạy lại phép grep đó trong bộ test chứ không chỉ trong
    `scripts/check_hardcode.sh`: `make test` chạy ở mọi vòng sửa code, còn
    `make check-hardcode` thì người ta nhớ chạy lúc sắp commit.

    **Phân biệt hoa/thường, đúng như `grep -E` mặc định.** Bật `IGNORECASE`
    làm test này đỏ ở `health.py`, nơi một docstring liệt kê "LiteLLM" trong
    danh sách thứ `/health/deep` kiểm — tức là báo động giả trên một dòng chú
    thích. Một phép kiểm báo động giả là một phép kiểm sắp bị tắt.
    """
    import re
    from pathlib import Path

    mau = re.compile(r"litellm|openai|AsyncOpenAI")
    thu_muc = Path(__file__).resolve().parents[2] / "app" / "api"
    pham = [
        f"{f}:{so}"
        for f in sorted(thu_muc.rglob("*.py"))
        for so, dong in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
        if mau.search(dong)
    ]
    assert pham == []
