"""T-1.13 — retry, sửa câu hỏi, chuyển nhánh, đọc anh em (§8.2, §8.3, §18.2, UC-04).

Năm dòng DoD của task nằm ở các test có chữ **DoD** trong docstring.

Cùng lối đi với `test_messages.py` và `test_conversations.py`:
`httpx.ASGITransport` (không `TestClient`, vì `connection` của `conftest.py` là
kết nối asyncpg gắn với event loop của chính test), `DEBUG` bật tay, và
`session_scope()` trong handler bị trỏ về đúng kết nối của test.

`arq_gia` thay chỗ `get_arq_pool` vì pool thật nối tới `redis:6379` — một host
chỉ phân giải được **bên trong** network `internal` của compose, mà `make test`
chạy từ WSL host. Nó cũng là chỗ đo "có đúng một job mới cho mỗi nhánh mới".

**Câu mà gần như mọi test ở đây kiểm lại từ một góc khác:** không thao tác nào
của T-1.13 được **sửa hoặc xoá** một hàng đã có. Đó là cạm bẫy task gọi tên
("cám dỗ xoá nhánh cũ cho gọn") và là lý do duy nhất cây message tồn tại (§8.1).
Vì thế các test không chỉ khẳng định "nhánh mới đúng" mà còn đọc lại hàng cũ và
khẳng định nó **không đổi một cột nào**.
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

TAO_MESSAGE = "/api/v1/conversations/{}/messages"
RETRY = "/api/v1/messages/{}/retry"
SUA_MESSAGE = "/api/v1/messages/{}"
ANH_EM = "/api/v1/messages/{}/siblings"
HOI_THOAI = "/api/v1/conversations/{}"


class ArqGia:
    """Pool arq giả — ghi lại mọi lần enqueue, có công tắc để ép nó ném.

    Bản rút gọn của `ArqGia` trong `test_messages.py`: ở đây không cần ngả
    "arq trả `None`" (T-1.8 đã đo nó cho `_day_job`, và ba endpoint mới dùng
    **chung** hàm đó), nhưng vẫn cần ngả "Redis chết" để đo rollback.
    """

    def __init__(self) -> None:
        self.da_day: list[tuple[str, tuple[Any, ...]]] = []
        self.no_ra = False

    async def enqueue_job(self, ten: str, *args: Any, **_: Any) -> object | None:
        if self.no_ra:
            raise ConnectionError("redis chet giua chung (gia lap)")
        self.da_day.append((ten, args))
        return object()


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


def _headers(user_id: uuid.UUID) -> dict[str, str]:
    return {"X-User-Id": str(user_id)}


async def _tao_hoi_thoai(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID, **cot: Any
) -> Conversation:
    async with session_factory() as session:
        conversation = await ConversationRepository(session).create_conversation(
            user_id=user_id, **cot
        )
        await session.commit()
        return conversation


async def _doc_message(
    session_factory: async_sessionmaker[AsyncSession], message_id: uuid.UUID
) -> Message:
    """Đọc bằng session MỚI: repository ghi bằng UPDATE thẳng, identity map của
    session cũ sẽ trả lại object cũ. Xem docstring `session_factory`."""
    async with session_factory() as session:
        message = await session.get(Message, message_id)
        assert message is not None
        return message


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


async def _active_leaf(
    session_factory: async_sessionmaker[AsyncSession], conversation_id: uuid.UUID
) -> uuid.UUID | None:
    async with session_factory() as session:
        stmt = select(Conversation.active_leaf_id).where(Conversation.id == conversation_id)
        return (await session.execute(stmt)).scalar_one()


async def _hoan_tat(
    session_factory: async_sessionmaker[AsyncSession], message_id: uuid.UUID, noi_dung: str
) -> None:
    """Khép một lượt sinh như worker làm (§7.2 ③).

    Không có bước này thì mọi message assistant do `POST .../messages` tạo ra
    còn nằm ở `queued`, và `retry` sẽ đúng đắn trả `409` — tức mọi test nhánh
    sẽ đo nhầm một phép kiểm khác.
    """
    async with session_factory() as session:
        await MessageRepository(session).finish_generation(
            message_id,
            status=MessageStatus.COMPLETED,
            content=noi_dung,
            finish_reason="stop",
        )
        await session.commit()


async def _mot_luot(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    cau_hoi: str,
    *,
    tra_loi: str = "tra loi",
    **body: Any,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Một lượt chat trọn vẹn qua HTTP, đã khép. Trả `(user_id, assistant_id)`.

    Đi qua đúng endpoint thật chứ không `INSERT` tay: cây mà các test này thao
    tác phải là cây mà `POST .../messages` thật sự dựng ra, nếu không thì
    `parent_id` và `active_leaf_id` chỉ đúng trong tưởng tượng của test.
    """
    resp = await client.post(
        TAO_MESSAGE.format(conversation_id),
        headers=_headers(user_id),
        json={
            "content": cau_hoi,
            **body,
        },
    )
    assert resp.status_code == 202, resp.text
    uid = uuid.UUID(resp.json()["user_message_id"])
    amid = uuid.UUID(resp.json()["assistant_message_id"])
    await _hoan_tat(session_factory, amid, tra_loi)
    return uid, amid


def _mot_model_khac_mac_dinh() -> str:
    """Một `model_id` đang bật, KHÁC model `default`. A3: không gõ tên vào đây."""
    mac_dinh = catalog.get_default_model()
    assert mac_dinh is not None
    khac = [m.id for m in catalog.get_catalog().models if m.enabled and m.id != mac_dinh.id]
    assert khac, "catalog phải có ít nhất hai model bật thì test này mới có nghĩa"
    return khac[0]


# ═══════════════ POST /messages/{id}/retry — tạo anh em (§8.2) ═════════════


async def test_retry_tao_assistant_anh_em_cung_parent(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """202, assistant mới cùng `parent_id`, `queued`, một job, lá dời sang nó."""
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    uid, amid = await _mot_luot(client, session_factory, conversation.id, user_a, "a")
    arq_gia.da_day.clear()

    resp = await client.post(RETRY.format(amid), headers=_headers(user_a))

    assert resp.status_code == 202, resp.text
    moi = uuid.UUID(resp.json()["assistant_message_id"])
    assert moi != amid

    ban_moi = await _doc_message(session_factory, moi)
    assert ban_moi.role is MessageRole.ASSISTANT
    assert ban_moi.parent_id == uid, "ANH EM của bản cũ, không phải con của nó"
    assert ban_moi.status is MessageStatus.QUEUED
    assert ban_moi.content == ""

    assert await _active_leaf(session_factory, conversation.id) == moi
    assert arq_gia.da_day == [("generate", (str(moi),))]
    assert resp.json()["stream_url"] == f"/api/v1/messages/{moi}/stream"


async def test_retry_khong_dung_toi_ban_cu(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """Cạm bẫy của task: bản cũ giữ NGUYÊN `content`, `status`, `model_id`.

    Ngả sai — "ghi đè cho gọn" — không làm hỏng response nào, nên chỉ có phép
    kiểm này bắt được: câu trả lời cũ biến mất khỏi DB mà không ai báo gì.
    """
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    _, amid = await _mot_luot(
        client, session_factory, conversation.id, user_a, "a", tra_loi="cau tra loi cu"
    )
    truoc = await _doc_message(session_factory, amid)
    model_cu, deleted_cu = truoc.model_id, truoc.deleted_at

    await client.post(
        RETRY.format(amid),
        headers=_headers(user_a),
        json={"model_id": _mot_model_khac_mac_dinh()},
    )

    sau = await _doc_message(session_factory, amid)
    assert sau.content == "cau tra loi cu"
    assert sau.status is MessageStatus.COMPLETED
    assert sau.finish_reason == "stop"
    assert sau.model_id == model_cu
    assert sau.deleted_at is deleted_cu is None


async def test_retry_hai_lan_sibling_count_ba_va_ca_ba_con_trong_db(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """**DoD 2** — retry 2 lần → `sibling_count == 3`, cả ba đều còn trong DB."""
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    uid, amid = await _mot_luot(client, session_factory, conversation.id, user_a, "a")

    mot = await client.post(RETRY.format(amid), headers=_headers(user_a))
    hai = await client.post(RETRY.format(amid), headers=_headers(user_a))
    ba_id = [
        amid,
        uuid.UUID(mot.json()["assistant_message_id"]),
        uuid.UUID(hai.json()["assistant_message_id"]),
    ]

    resp = await client.get(ANH_EM.format(amid), headers=_headers(user_a))
    assert resp.status_code == 200, resp.text
    assert resp.json()["sibling_count"] == 3
    assert [uuid.UUID(m["id"]) for m in resp.json()["items"]] == ba_id

    # "Còn trong DB" đọc thẳng từ bảng, không qua API: một endpoint lọc
    # `deleted_at IS NULL` sẽ nói dối đúng ở ca người ta sợ nhất (xoá mềm).
    for mid in ba_id:
        hang = await _doc_message(session_factory, mid)
        assert hang.deleted_at is None
        assert hang.parent_id == uid
    assert await _dem_message(session_factory, conversation.id) == 4


async def test_retry_model_khac_nhanh_cu_khong_doi(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """**DoD 3** — nhánh mới mang `model_id` mới, nhánh cũ giữ model cũ."""
    mac_dinh = catalog.get_default_model()
    assert mac_dinh is not None
    khac = _mot_model_khac_mac_dinh()
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    _, amid = await _mot_luot(client, session_factory, conversation.id, user_a, "a")
    assert (await _doc_message(session_factory, amid)).model_id == mac_dinh.id

    resp = await client.post(RETRY.format(amid), headers=_headers(user_a), json={"model_id": khac})

    assert resp.json()["model_id"] == khac
    moi = await _doc_message(session_factory, uuid.UUID(resp.json()["assistant_message_id"]))
    assert moi.model_id == khac
    assert (await _doc_message(session_factory, amid)).model_id == mac_dinh.id


async def test_retry_khong_noi_model_thi_dung_lai_model_cua_ban_cu(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """Bấm Retry trơn ⇒ sinh lại bằng ĐÚNG model cũ, không phải model mặc định.

    Hội thoại để `default_model` là model `default` của catalog, còn lượt kia
    gọi đích danh một model khác — nếu `_chon_model` bỏ qua mức giữa
    (`messages.model_id`) thì bản retry sẽ lặng lẽ rơi về model mặc định.
    """
    mac_dinh = catalog.get_default_model()
    assert mac_dinh is not None
    khac = _mot_model_khac_mac_dinh()
    conversation = await _tao_hoi_thoai(session_factory, user_a, default_model=mac_dinh.id)
    _, amid = await _mot_luot(client, session_factory, conversation.id, user_a, "a", model_id=khac)

    resp = await client.post(RETRY.format(amid), headers=_headers(user_a))

    assert resp.json()["model_id"] == khac


async def test_retry_message_user_tra_400(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """Sinh lại một câu HỎI không có nghĩa — đường sửa câu hỏi là `PATCH`."""
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    uid, _ = await _mot_luot(client, session_factory, conversation.id, user_a, "a")
    truoc = await _dem_message(session_factory, conversation.id)
    arq_gia.da_day.clear()

    resp = await client.post(RETRY.format(uid), headers=_headers(user_a))

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "MESSAGE_ROLE_MISMATCH"
    assert resp.json()["error"]["details"] == {"role": "user", "expected": "assistant"}
    assert await _dem_message(session_factory, conversation.id) == truoc
    assert arq_gia.da_day == []


@pytest.mark.parametrize("trang_thai", [MessageStatus.QUEUED, MessageStatus.STREAMING])
async def test_retry_khi_luot_cu_chua_khep_tra_409(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    trang_thai: MessageStatus,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """Hai lượt sinh cho cùng một `parent_id` = trả tiền hai lần. Chặn ở 409.

    Không dùng `_mot_luot` (nó khép lượt lại): ở đây message assistant phải
    còn đúng trạng thái đang chạy.
    """
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    resp = await client.post(
        TAO_MESSAGE.format(conversation.id), headers=_headers(user_a), json={"content": "a"}
    )
    amid = uuid.UUID(resp.json()["assistant_message_id"])
    if trang_thai is MessageStatus.STREAMING:
        async with session_factory() as session:
            await MessageRepository(session).mark_streaming(amid, model_id="bat-ky")
            await session.commit()
    truoc = await _dem_message(session_factory, conversation.id)
    arq_gia.da_day.clear()

    lan_hai = await client.post(RETRY.format(amid), headers=_headers(user_a))

    assert lan_hai.status_code == 409
    assert lan_hai.json()["error"]["code"] == "GENERATION_IN_PROGRESS"
    assert lan_hai.json()["error"]["details"] == {"status": trang_thai.value}
    assert await _dem_message(session_factory, conversation.id) == truoc
    assert arq_gia.da_day == []


async def test_retry_message_cua_user_khac_tra_404_va_khong_ghi_gi(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """IDOR (§20): 404 chứ không 403, và tuyệt đối không hàng nào được ghi."""
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    _, amid = await _mot_luot(client, session_factory, conversation.id, user_a, "a")
    truoc = await _dem_message(session_factory, conversation.id)
    arq_gia.da_day.clear()

    resp = await client.post(RETRY.format(amid), headers=_headers(user_b))

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "MESSAGE_NOT_FOUND"
    assert await _dem_message(session_factory, conversation.id) == truoc
    assert arq_gia.da_day == []


async def test_retry_model_khong_co_trong_catalog_tra_400_va_khong_ghi_gi(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    _, amid = await _mot_luot(client, session_factory, conversation.id, user_a, "a")
    truoc = await _dem_message(session_factory, conversation.id)

    resp = await client.post(
        RETRY.format(amid), headers=_headers(user_a), json={"model_id": "khong-ton-tai"}
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "MODEL_UNKNOWN"
    assert await _dem_message(session_factory, conversation.id) == truoc


async def test_retry_enqueue_no_thi_khong_con_message_mo_coi(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """`enqueue` nằm TRONG transaction ở cả ba đường, không riêng T-1.8.

    Ngả ngược lại để lại một message `queued` **vĩnh viễn** (reaper §7.6 chỉ
    dọn `streaming`) và một `active_leaf_id` trỏ vào nó — tức hội thoại kẹt ở
    một bong bóng rỗng không bao giờ có chữ.
    """
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    _, amid = await _mot_luot(client, session_factory, conversation.id, user_a, "a")
    truoc = await _dem_message(session_factory, conversation.id)
    arq_gia.no_ra = True

    resp = await client.post(RETRY.format(amid), headers=_headers(user_a))

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "ENQUEUE_FAILED"
    assert await _dem_message(session_factory, conversation.id) == truoc
    assert await _active_leaf(session_factory, conversation.id) == amid


# ════════ PATCH /messages/{id} — sửa câu hỏi thành một nhánh (§8.2) ════════


async def test_sua_message_user_tao_anh_em_va_mot_luot_sinh_moi(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """202, user mới cùng `parent_id`, assistant `queued` làm con của nó."""
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    u1, a1 = await _mot_luot(client, session_factory, conversation.id, user_a, "cau hoi 1")
    u2, _ = await _mot_luot(client, session_factory, conversation.id, user_a, "cau hoi 2")
    arq_gia.da_day.clear()

    resp = await client.patch(
        SUA_MESSAGE.format(u2), headers=_headers(user_a), json={"content": "cau hoi 2 da sua"}
    )

    assert resp.status_code == 202, resp.text
    u2b = uuid.UUID(resp.json()["user_message_id"])
    a2b = uuid.UUID(resp.json()["assistant_message_id"])
    assert u2b != u2

    ban_sua = await _doc_message(session_factory, u2b)
    assert ban_sua.role is MessageRole.USER
    assert ban_sua.content == "cau hoi 2 da sua"
    assert ban_sua.parent_id == a1, "ANH EM của bản cũ ⇒ cùng cha là a1"

    tra_loi = await _doc_message(session_factory, a2b)
    assert tra_loi.role is MessageRole.ASSISTANT
    assert tra_loi.parent_id == u2b
    assert tra_loi.status is MessageStatus.QUEUED

    assert await _active_leaf(session_factory, conversation.id) == a2b
    assert arq_gia.da_day == [("generate", (str(a2b),))]
    assert resp.json()["stream_url"] == f"/api/v1/messages/{a2b}/stream"
    assert u1 is not None  # u1 chỉ để dựng cây, giữ tên cho dễ đọc


async def test_sua_message_khong_dung_toi_ban_cu(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """`PATCH` không sửa hàng nào — `messages.content` cũ không đổi một ký tự."""
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    u1, _ = await _mot_luot(client, session_factory, conversation.id, user_a, "ban goc")

    await client.patch(
        SUA_MESSAGE.format(u1), headers=_headers(user_a), json={"content": "ban sua"}
    )

    cu = await _doc_message(session_factory, u1)
    assert cu.content == "ban goc"
    assert cu.deleted_at is None


async def test_sua_message_giua_hoi_thoai_nhanh_con_cu_van_truy_cap_duoc(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """**DoD 4** — sửa message user ở giữa, nhánh con cũ vẫn mở lại được bằng
    `active_leaf_id` cũ.

    Cây trước khi sửa: `u1 → a1 → u2 → a2` (lá = `a2`). Sau khi sửa `u2`, lá
    dời sang nhánh mới; trả lá về `a2` phải cho lại **đúng** đường đi cũ, kể cả
    nội dung câu hỏi cũ.
    """
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    u1, a1 = await _mot_luot(client, session_factory, conversation.id, user_a, "cau hoi 1")
    u2, a2 = await _mot_luot(client, session_factory, conversation.id, user_a, "cau hoi 2")
    la_cu = a2

    sua = await client.patch(
        SUA_MESSAGE.format(u2), headers=_headers(user_a), json={"content": "cau hoi 2 khac han"}
    )
    u2b = uuid.UUID(sua.json()["user_message_id"])
    a2b = uuid.UUID(sua.json()["assistant_message_id"])

    # Màn hình ngay sau khi sửa: nhánh MỚI.
    ngay_sau = await client.get(HOI_THOAI.format(conversation.id), headers=_headers(user_a))
    assert [uuid.UUID(m["id"]) for m in ngay_sau.json()["path"]] == [u1, a1, u2b, a2b]

    # Quay về lá cũ — đúng một `PATCH`, không khôi phục gì cả.
    ve_cu = await client.patch(
        HOI_THOAI.format(conversation.id),
        headers=_headers(user_a),
        json={"active_leaf_id": str(la_cu)},
    )
    assert ve_cu.status_code == 200, ve_cu.text
    assert [uuid.UUID(m["id"]) for m in ve_cu.json()["path"]] == [u1, a1, u2, a2]
    assert ve_cu.json()["path"][2]["content"] == "cau hoi 2"
    # Và `‹ n/m ›` của câu hỏi cũ nay là 1/2 — C13 do API trả, FE không tự đếm.
    assert ve_cu.json()["path"][2]["sibling_index"] == 0
    assert ve_cu.json()["path"][2]["sibling_count"] == 2


async def test_sua_message_goc_tao_goc_thu_hai(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """Sửa câu hỏi ĐẦU TIÊN ⇒ hai gốc (`parent_id` NULL) trong một hội thoại.

    §8.2 cho phép, và `IS NOT DISTINCT FROM` của §8.3 tồn tại chính vì ca này:
    viết `parent_id = NULL` thì mọi gốc báo "0 anh em" và `‹ n/m ›` biến mất
    đúng lúc người dùng cần nó nhất.
    """
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    u1, _ = await _mot_luot(client, session_factory, conversation.id, user_a, "goc 1")

    sua = await client.patch(
        SUA_MESSAGE.format(u1), headers=_headers(user_a), json={"content": "goc 2"}
    )
    u1b = uuid.UUID(sua.json()["user_message_id"])

    assert (await _doc_message(session_factory, u1b)).parent_id is None
    anh_em = await client.get(ANH_EM.format(u1), headers=_headers(user_a))
    assert anh_em.json()["parent_id"] is None
    assert anh_em.json()["sibling_count"] == 2
    assert [uuid.UUID(m["id"]) for m in anh_em.json()["items"]] == [u1, u1b]


async def test_sua_message_assistant_tra_400(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """Sửa lời của model rồi để nó vào ngữ cảnh lượt sau là bịa lịch sử."""
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    _, amid = await _mot_luot(client, session_factory, conversation.id, user_a, "a")
    truoc = await _dem_message(session_factory, conversation.id)

    resp = await client.patch(
        SUA_MESSAGE.format(amid), headers=_headers(user_a), json={"content": "toi noi ho model"}
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "MESSAGE_ROLE_MISMATCH"
    assert resp.json()["error"]["details"] == {"role": "assistant", "expected": "user"}
    assert await _dem_message(session_factory, conversation.id) == truoc


async def test_sua_message_cua_user_khac_tra_404_va_khong_ghi_gi(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    u1, _ = await _mot_luot(client, session_factory, conversation.id, user_a, "a")
    truoc = await _dem_message(session_factory, conversation.id)
    arq_gia.da_day.clear()

    resp = await client.patch(
        SUA_MESSAGE.format(u1), headers=_headers(user_b), json={"content": "cua toi day"}
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "MESSAGE_NOT_FOUND"
    assert await _dem_message(session_factory, conversation.id) == truoc
    assert arq_gia.da_day == []
    assert (await _doc_message(session_factory, u1)).content == "a"


async def test_sua_message_noi_dung_rong_tra_422(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """Sửa thành rỗng = trả tiền cho một lượt sinh không có câu hỏi."""
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    u1, _ = await _mot_luot(client, session_factory, conversation.id, user_a, "a")
    truoc = await _dem_message(session_factory, conversation.id)

    resp = await client.patch(
        SUA_MESSAGE.format(u1), headers=_headers(user_a), json={"content": ""}
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
    assert await _dem_message(session_factory, conversation.id) == truoc


# ═════ PATCH /conversations/{id} — chuyển nhánh và metadata (§18.2) ════════


async def test_doi_active_leaf_id_doi_duong_di(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """Chuyển nhánh chỉ đổi con trỏ — số message trong DB không nhúc nhích."""
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    u1, a1 = await _mot_luot(client, session_factory, conversation.id, user_a, "a")
    retry = await client.post(RETRY.format(a1), headers=_headers(user_a))
    a1b = uuid.UUID(retry.json()["assistant_message_id"])
    truoc = await _dem_message(session_factory, conversation.id)

    resp = await client.patch(
        HOI_THOAI.format(conversation.id),
        headers=_headers(user_a),
        json={"active_leaf_id": str(a1)},
    )

    assert resp.status_code == 200, resp.text
    assert uuid.UUID(resp.json()["active_leaf_id"]) == a1
    assert [uuid.UUID(m["id"]) for m in resp.json()["path"]] == [u1, a1]
    assert resp.json()["path"][1]["sibling_count"] == 2
    assert await _active_leaf(session_factory, conversation.id) == a1
    assert await _dem_message(session_factory, conversation.id) == truoc
    assert (await _doc_message(session_factory, a1b)).deleted_at is None


async def test_chuyen_nhanh_roi_gui_tin_nhan_moi_gan_vao_nhanh_dang_xem(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """**DoD 5** — chuyển nhánh rồi gửi tin nhắn mới → gắn đúng nhánh đang xem.

    Cây: `u1 → a1` với `a1` có hai anh em (`a1`, `a1b`). Đang xem `a1b` mà trả
    lá về `a1` rồi gửi tiếp thì lượt mới phải mọc dưới `a1`, không phải `a1b`.
    """
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    _, a1 = await _mot_luot(client, session_factory, conversation.id, user_a, "a")
    retry = await client.post(RETRY.format(a1), headers=_headers(user_a))
    a1b = uuid.UUID(retry.json()["assistant_message_id"])
    assert await _active_leaf(session_factory, conversation.id) == a1b

    await client.patch(
        HOI_THOAI.format(conversation.id),
        headers=_headers(user_a),
        json={"active_leaf_id": str(a1)},
    )
    tiep = await client.post(
        TAO_MESSAGE.format(conversation.id), headers=_headers(user_a), json={"content": "tiep"}
    )

    assert tiep.json()["branched"] is False, "nối vào đúng lá đang xem, không phải nhánh mới"
    u2 = await _doc_message(session_factory, uuid.UUID(tiep.json()["user_message_id"]))
    assert u2.parent_id == a1


async def test_active_leaf_id_cua_hoi_thoai_khac_tra_404(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """Trỏ con trỏ nhánh sang cây khác ⇒ `get_path` lẫn hai hội thoại (C11)."""
    mot = await _tao_hoi_thoai(session_factory, user_a)
    hai = await _tao_hoi_thoai(session_factory, user_a)
    _, a1 = await _mot_luot(client, session_factory, mot.id, user_a, "a")

    resp = await client.patch(
        HOI_THOAI.format(hai.id), headers=_headers(user_a), json={"active_leaf_id": str(a1)}
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "LEAF_NOT_FOUND"
    assert await _active_leaf(session_factory, hai.id) is None


async def test_doi_tieu_de_model_va_ghim(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """Ba trường còn lại của §18.2, và `null` tường minh xoá được tiêu đề."""
    khac = _mot_model_khac_mac_dinh()
    conversation = await _tao_hoi_thoai(session_factory, user_a, title="ten cu")

    dat = await client.patch(
        HOI_THOAI.format(conversation.id),
        headers=_headers(user_a),
        json={"title": "ten moi", "default_model": khac, "pinned": True},
    )
    assert dat.status_code == 200, dat.text
    assert dat.json()["title"] == "ten moi"
    assert dat.json()["default_model"] == khac
    assert dat.json()["pinned"] is True

    xoa = await client.patch(
        HOI_THOAI.format(conversation.id), headers=_headers(user_a), json={"title": None}
    )
    assert xoa.json()["title"] is None
    assert xoa.json()["default_model"] == khac, "trường không gửi thì không bị đụng"
    assert xoa.json()["pinned"] is True


async def test_pinned_null_tra_400(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """Cột `NOT NULL` ⇒ `null` không có nghĩa, và bỏ qua im lặng là tệ hơn."""
    conversation = await _tao_hoi_thoai(session_factory, user_a)

    resp = await client.patch(
        HOI_THOAI.format(conversation.id), headers=_headers(user_a), json={"pinned": None}
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "BAD_REQUEST"


async def test_default_model_khong_co_trong_catalog_tra_400(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    conversation = await _tao_hoi_thoai(session_factory, user_a, title="giu nguyen")

    resp = await client.patch(
        HOI_THOAI.format(conversation.id),
        headers=_headers(user_a),
        json={"title": "doi luon", "default_model": "khong-ton-tai"},
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "MODEL_UNKNOWN"
    # Kiểm TRƯỚC khi ghi: `title` trong cùng request cũng không được áp.
    doc = await client.get(HOI_THOAI.format(conversation.id), headers=_headers(user_a))
    assert doc.json()["title"] == "giu nguyen"


async def test_patch_hoi_thoai_cua_user_khac_tra_404(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    conversation = await _tao_hoi_thoai(session_factory, user_a, title="cua a")

    resp = await client.patch(
        HOI_THOAI.format(conversation.id), headers=_headers(user_b), json={"title": "cua b"}
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"
    async with session_factory() as session:
        con = await ConversationRepository(session).get_conversation(
            conversation.id, user_id=user_a
        )
    assert con is not None
    assert con.title == "cua a"


async def test_patch_body_rong_khong_doi_gi(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """`{}` hợp lệ: trả về trạng thái hiện tại, đúng như `GET`."""
    conversation = await _tao_hoi_thoai(session_factory, user_a, title="ten")
    _, a1 = await _mot_luot(client, session_factory, conversation.id, user_a, "a")

    resp = await client.patch(HOI_THOAI.format(conversation.id), headers=_headers(user_a), json={})

    assert resp.status_code == 200, resp.text
    assert resp.json()["title"] == "ten"
    assert uuid.UUID(resp.json()["active_leaf_id"]) == a1
    assert len(resp.json()["path"]) == 2


# ═════════════ GET /messages/{id}/siblings — dữ liệu cho ‹ n/m › ══════════


async def test_siblings_gom_ca_chinh_no_va_sap_xac_dinh(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """`sibling_index` 0-based (B-60) và khớp vị trí trong danh sách đã sắp.

    Hỏi từ **mỗi** anh em một lần: `sibling_index` phải đổi theo người hỏi,
    còn `items` và `sibling_count` thì không.
    """
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    _, a1 = await _mot_luot(client, session_factory, conversation.id, user_a, "a")
    mot = await client.post(RETRY.format(a1), headers=_headers(user_a))
    a1b = uuid.UUID(mot.json()["assistant_message_id"])
    hai = await client.post(RETRY.format(a1), headers=_headers(user_a))
    a1c = uuid.UUID(hai.json()["assistant_message_id"])

    for vi_tri, mid in enumerate([a1, a1b, a1c]):
        resp = await client.get(ANH_EM.format(mid), headers=_headers(user_a))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert uuid.UUID(body["message_id"]) == mid
        assert body["sibling_index"] == vi_tri
        assert body["sibling_count"] == 3
        assert [uuid.UUID(m["id"]) for m in body["items"]] == [a1, a1b, a1c]
        assert [m["sibling_index"] for m in body["items"]] == [0, 1, 2]
        assert {m["sibling_count"] for m in body["items"]} == {3}


async def test_siblings_khong_co_anh_em_van_tra_mot(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """`sibling_count == 1`, không phải 0 — cùng quy ước với `_sibling_stats`.

    Lệch quy ước ở đây là C13 ở dạng khó tìm nhất: `‹ 1/0 ›` trên màn hình.
    """
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    _, a1 = await _mot_luot(client, session_factory, conversation.id, user_a, "a")

    resp = await client.get(ANH_EM.format(a1), headers=_headers(user_a))

    assert resp.json()["sibling_count"] == 1
    assert resp.json()["sibling_index"] == 0
    assert len(resp.json()["items"]) == 1


async def test_siblings_khong_ro_ri_cot_van_hanh(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """`raw_response`, `tool_calls`, `heartbeat_at`, `prompt_tokens` không ra dây."""
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    _, a1 = await _mot_luot(client, session_factory, conversation.id, user_a, "a")

    resp = await client.get(ANH_EM.format(a1), headers=_headers(user_a))

    cam = {"raw_response", "tool_calls", "heartbeat_at", "prompt_tokens", "completion_tokens"}
    assert set(resp.json()["items"][0]) & cam == set()


async def test_siblings_cua_user_khac_tra_404(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    _, a1 = await _mot_luot(client, session_factory, conversation.id, user_a, "a")

    resp = await client.get(ANH_EM.format(a1), headers=_headers(user_b))

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "MESSAGE_NOT_FOUND"


async def test_siblings_message_khong_ton_tai_tra_404(
    client: AsyncClient,
    user_a: uuid.UUID,
    _debug_bat: None,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    resp = await client.get(ANH_EM.format(uuid.uuid4()), headers=_headers(user_a))

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "MESSAGE_NOT_FOUND"


async def test_debug_tat_thi_ba_endpoint_deu_503(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> None:
    """Không bật `_debug_bat` — cấu hình của một máy mới (`.env.example`).

    `get_current_user_id` là chỗ tạm của Phase 1 (NQ-24); ba endpoint mới phải
    đi qua đúng cửa đó chứ không tự đọc header.
    """
    assert settings.DEBUG is False
    mid = uuid.uuid4()

    for goi in (
        client.post(RETRY.format(mid), headers=_headers(user_a)),
        client.patch(SUA_MESSAGE.format(mid), headers=_headers(user_a), json={"content": "x"}),
        client.get(ANH_EM.format(mid), headers=_headers(user_a)),
        client.patch(HOI_THOAI.format(mid), headers=_headers(user_a), json={"pinned": True}),
    ):
        resp = await goi
        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "AUTH_NOT_IMPLEMENTED"
