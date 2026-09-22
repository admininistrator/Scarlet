"""T-3.7a — `POST /messages/{id}/feedback`: Like · Dislike · gỡ (§18.2, §20, B-207).

Năm dòng DoD của task nằm ở các test có chữ **DoD** trong docstring.

Hạ tầng giống `test_branching.py` — `httpx.ASGITransport`, `session_scope()`
trỏ về đúng kết nối của test, arq giả cho chặng enqueue — vì cây message mà bộ
test này đánh giá phải là cây mà `POST .../messages` **thật sự** dựng ra. Đánh
giá một hàng `INSERT` bằng tay sẽ xanh cả khi `parent_id` và `role` chỉ đúng
trong tưởng tượng của test.

**Bốn nhóm, và nhóm cuối là nhóm dễ bị bỏ qua nhất:**

1. Vòng đời Like → Like → Dislike → gỡ, đọc thẳng cột `messages.feedback` sau
   mỗi bước (DoD dòng 2).
2. Quyền: IDOR của §20 — user A đánh giá message của B ⇒ **404**, không `403`.
3. Biên của body: lý do quá dài, lý do không kèm đánh giá, khoá gõ sai.
4. **Hằng số Python và DDL có còn khớp nhau không.** `FEEDBACK_REASON_MAX_CHARS`
   xuất hiện ở hai chỗ — `max_length` của schema và một `CHECK` trong migration
   0005 — và chúng lệch nhau được trong im lặng. Hai test cuối file đâm thẳng
   vào Postgres bằng `UPDATE` để lệch ấy thành đỏ: nới hằng số Python mà quên
   migration sẽ biến một `422` gọn gàng thành một `500`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import FEEDBACK_REASON_MAX_CHARS
from app.core.access_token import encode_access_token
from app.core.deps import SESSION_COOKIE_NAME
from app.core.errors import ApiErrorCode
from app.db.models import (
    Conversation,
    Message,
    MessageFeedback,
    MessageStatus,
    UserRole,
    UserStatus,
)
from app.db.repositories import ConversationRepository, MessageRepository
from app.main import app

TAO_MESSAGE = "/api/v1/conversations/{}/messages"
DANH_GIA = "/api/v1/messages/{}/feedback"
HOI_THOAI = "/api/v1/conversations/{}"
ANH_EM = "/api/v1/messages/{}/siblings"


class ArqGia:
    """Pool arq giả — nuốt lần enqueue thay vì nối `redis:6379`.

    Bộ test này không đo hàng đợi; nó chỉ cần `POST .../messages` đi tới cuối
    để có một cây thật để đánh giá. Nhưng pool thật nối tới một host chỉ phân
    giải được **bên trong** network `internal` của compose, còn `make test`
    chạy từ WSL host — không có fake này thì mọi ca ở đây treo chứ không đỏ.
    """

    def __init__(self) -> None:
        self.da_day: list[tuple[str, tuple[Any, ...]]] = []

    async def enqueue_job(self, ten: str, *args: Any, **_: Any) -> object | None:
        self.da_day.append((ten, args))
        return object()


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
async def client(event_hooks: dict[str, Any]) -> AsyncIterator[AsyncClient]:
    # `event_hooks`: mỗi POST một `Idempotency-Key` mới (§11.4, T-2.8). Endpoint
    # của task này KHÔNG bắt buộc header ấy, nhưng `POST .../messages` — thứ
    # dựng cây cho mọi ca dưới đây — thì có.
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://localhost", event_hooks=event_hooks
    ) as http:
        yield http


def _phien(user_id: uuid.UUID) -> dict[str, str]:
    """Header `Cookie` mang phiên thật (§11.2) của `user_id` — cùng lối T-3.1c.

    Danh tính theo **request** chứ không đặt lên `client`: ca IDOR của §20 cần
    hai danh tính đứng cạnh nhau trong cùng một hàm mà không ai phải nhớ dọn.
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
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> Conversation:
    async with session_factory() as session:
        conversation = await ConversationRepository(session).create_conversation(user_id=user_id)
        await session.commit()
        return conversation


async def _hoan_tat(
    session_factory: async_sessionmaker[AsyncSession], message_id: uuid.UUID, noi_dung: str
) -> None:
    """Khép một lượt sinh như worker làm (§7.2 ③) — cây phải có câu trả lời thật."""
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
) -> tuple[uuid.UUID, uuid.UUID]:
    """Một lượt chat trọn vẹn qua HTTP, đã khép. Trả `(user_msg_id, assistant_msg_id)`."""
    resp = await client.post(
        TAO_MESSAGE.format(conversation_id),
        headers=_phien(user_id),
        json={"content": "cau hoi de danh gia"},
    )
    assert resp.status_code == 202, resp.text
    uid = uuid.UUID(resp.json()["user_message_id"])
    amid = uuid.UUID(resp.json()["assistant_message_id"])
    await _hoan_tat(session_factory, amid, "tra loi de danh gia")
    return uid, amid


async def _doc_cot_feedback(
    session_factory: async_sessionmaker[AsyncSession], message_id: uuid.UUID
) -> tuple[MessageFeedback | None, str | None]:
    """`SELECT feedback, feedback_reason FROM messages WHERE id = ...` — DoD dòng 2.

    Session MỚI mỗi lần: repository ghi bằng câu `UPDATE` thẳng, nên đọc lại
    bằng session đã ghi có thể trả về object cũ trong identity map.
    """
    async with session_factory() as session:
        stmt = select(Message.feedback, Message.feedback_reason).where(Message.id == message_id)
        feedback, reason = (await session.execute(stmt)).one()
        return feedback, reason


@pytest_asyncio.fixture
async def cay(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    _db_cua_test: None,
    arq_gia: ArqGia,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Một hội thoại của A với một lượt đã xong. Trả `(conversation, user_msg, assistant_msg)`."""
    conversation = await _tao_hoi_thoai(session_factory, user_a)
    uid, amid = await _mot_luot(client, session_factory, conversation.id, user_a)
    return conversation.id, uid, amid


# ═══════ 1. Vòng đời Like → Like → Dislike → gỡ (DoD dòng 2, "Việc cần làm") ═══


async def test_DoD_like_like_dislike_go(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    cay: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    """DoD dòng 2: bốn bước, bốn lần đọc cột ⇒ `like`, `like`, `dislike`, `NULL`.

    Bước hai là bước mang cả nội dung của chữ "**idempotent theo message**":
    Like lần thứ hai không tạo dòng thứ hai và không đổi giá trị. Đây là `UPDATE`
    chứ không `INSERT`, nên tính chất ấy không đến từ một `UNIQUE` nào cả.
    """
    _, _, amid = cay

    r1 = await client.post(DANH_GIA.format(amid), headers=_phien(user_a), json={"value": "like"})
    assert r1.status_code == 200, r1.text
    assert r1.json() == {
        "message_id": str(amid),
        "feedback": "like",
        "feedback_reason": None,
    }
    assert await _doc_cot_feedback(session_factory, amid) == (MessageFeedback.LIKE, None)

    r2 = await client.post(DANH_GIA.format(amid), headers=_phien(user_a), json={"value": "like"})
    assert r2.status_code == 200, r2.text
    assert await _doc_cot_feedback(session_factory, amid) == (MessageFeedback.LIKE, None)

    r3 = await client.post(DANH_GIA.format(amid), headers=_phien(user_a), json={"value": "dislike"})
    assert r3.status_code == 200, r3.text
    assert await _doc_cot_feedback(session_factory, amid) == (MessageFeedback.DISLIKE, None)

    r4 = await client.post(DANH_GIA.format(amid), headers=_phien(user_a), json={"value": None})
    assert r4.status_code == 200, r4.text
    assert r4.json()["feedback"] is None
    assert await _doc_cot_feedback(session_factory, amid) == (None, None)


async def test_van_dung_mot_hang_sau_bon_lan_bam(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    cay: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    """ "Like rồi Like lại vẫn MỘT dòng" — đo bằng `count(*)` của cả hội thoại.

    Một endpoint ghi bằng `INSERT` sẽ xanh hết các phép kiểm giá trị ở trên
    (câu `SELECT` đọc hàng mới nhất) mà vẫn để lại bốn hàng rác.
    """
    conversation_id, _, amid = cay
    async with session_factory() as session:
        truoc = len(
            (
                await session.execute(
                    select(Message.id).where(Message.conversation_id == conversation_id)
                )
            )
            .scalars()
            .all()
        )

    for gia_tri in ("like", "like", "dislike", None):
        resp = await client.post(
            DANH_GIA.format(amid), headers=_phien(user_a), json={"value": gia_tri}
        )
        assert resp.status_code == 200, resp.text

    async with session_factory() as session:
        sau = len(
            (
                await session.execute(
                    select(Message.id).where(Message.conversation_id == conversation_id)
                )
            )
            .scalars()
            .all()
        )
    assert sau == truoc, "đánh giá là UPDATE trên hàng đã có, không phải INSERT"


async def test_danh_gia_khong_dung_toi_cot_khac(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    cay: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    """Bấm Like không được sửa `content`/`status`/`model_id` của câu trả lời."""
    _, _, amid = cay

    async with session_factory() as session:
        truoc = await session.get(Message, amid)
        assert truoc is not None
        cu = (truoc.content, truoc.status, truoc.model_id, truoc.finish_reason)

    resp = await client.post(
        DANH_GIA.format(amid), headers=_phien(user_a), json={"value": "dislike"}
    )
    assert resp.status_code == 200, resp.text

    async with session_factory() as session:
        sau = await session.get(Message, amid)
        assert sau is not None
        assert (sau.content, sau.status, sau.model_id, sau.finish_reason) == cu


# ═════════════════════ 2. Lý do đi kèm (§18.2 "lý do tuỳ chọn") ═══════════════


async def test_ly_do_duoc_luu_va_tra_lai(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    cay: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    _, _, amid = cay
    resp = await client.post(
        DANH_GIA.format(amid),
        headers=_phien(user_a),
        json={"value": "dislike", "reason": "tra loi sai ngay o cau dau"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["feedback_reason"] == "tra loi sai ngay o cau dau"
    assert await _doc_cot_feedback(session_factory, amid) == (
        MessageFeedback.DISLIKE,
        "tra loi sai ngay o cau dau",
    )


async def test_doi_gia_tri_khong_giu_lai_ly_do_cu(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    cay: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    """Đánh giá là tài nguyên thay-cả-cụm: Dislike-có-lý-do → Like ⇒ lý do về `NULL`.

    Giữ lại câu "trả lời sai" bên cạnh một Like là để một hàng tự mâu thuẫn.
    """
    _, _, amid = cay
    await client.post(
        DANH_GIA.format(amid),
        headers=_phien(user_a),
        json={"value": "dislike", "reason": "sai be bet"},
    )

    resp = await client.post(DANH_GIA.format(amid), headers=_phien(user_a), json={"value": "like"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["feedback_reason"] is None
    assert await _doc_cot_feedback(session_factory, amid) == (MessageFeedback.LIKE, None)


async def test_go_danh_gia_xoa_luon_ly_do(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    cay: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    """`value: null` dọn cả hai cột — nếu không, CHECK của migration 0005 sẽ nổ."""
    _, _, amid = cay
    await client.post(
        DANH_GIA.format(amid),
        headers=_phien(user_a),
        json={"value": "dislike", "reason": "co ly do han hoi"},
    )

    resp = await client.post(DANH_GIA.format(amid), headers=_phien(user_a), json={"value": None})

    assert resp.status_code == 200, resp.text
    assert await _doc_cot_feedback(session_factory, amid) == (None, None)


# ══════════════════════ 3. Biên của body — bốn ca `422` ═══════════════════════


async def test_ly_do_dung_bang_tran_van_duoc_nhan(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    cay: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    """`FEEDBACK_REASON_MAX_CHARS` ký tự chẵn ⇒ `200`. Biên là "≤", không phải "<"."""
    _, _, amid = cay
    vua_du = "x" * FEEDBACK_REASON_MAX_CHARS

    resp = await client.post(
        DANH_GIA.format(amid),
        headers=_phien(user_a),
        json={"value": "dislike", "reason": vua_du},
    )

    assert resp.status_code == 200, resp.text
    _, reason = await _doc_cot_feedback(session_factory, amid)
    assert reason is not None
    assert len(reason) == FEEDBACK_REASON_MAX_CHARS


async def test_ly_do_qua_tran_nhan_422(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    cay: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    """Cạm bẫy ①: một trường tự do không trần trên bảng nóng nhất của app.

    `422` ở tầng schema, tức **trước** khi chuỗi ấy chạm Postgres — CHECK của
    DDL là lớp thứ hai, không phải lớp duy nhất.
    """
    _, _, amid = cay

    resp = await client.post(
        DANH_GIA.format(amid),
        headers=_phien(user_a),
        json={"value": "dislike", "reason": "x" * (FEEDBACK_REASON_MAX_CHARS + 1)},
    )

    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == ApiErrorCode.VALIDATION_ERROR.value
    assert await _doc_cot_feedback(session_factory, amid) == (None, None)


async def test_ly_do_khong_kem_danh_gia_nhan_422(
    client: AsyncClient, user_a: uuid.UUID, cay: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
) -> None:
    """`{"value": null, "reason": "..."}` không có nghĩa nào đọc được."""
    _, _, amid = cay

    resp = await client.post(
        DANH_GIA.format(amid),
        headers=_phien(user_a),
        json={"value": None, "reason": "mot ly do khong thuoc ve danh gia nao"},
    )

    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == ApiErrorCode.VALIDATION_ERROR.value


async def test_thieu_han_value_nhan_422(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    cay: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    """Body rỗng KHÔNG đọc thành "gỡ đánh giá" — nó là `422`.

    Đây là chỗ hợp đồng cố ý khác `PUT /settings` của T-3.0 (vắng mặt = `null`):
    một request hỏng không được phép âm thầm xoá thứ người dùng vừa bấm.
    """
    _, _, amid = cay
    await client.post(DANH_GIA.format(amid), headers=_phien(user_a), json={"value": "like"})

    resp = await client.post(DANH_GIA.format(amid), headers=_phien(user_a), json={})

    assert resp.status_code == 422, resp.text
    assert await _doc_cot_feedback(session_factory, amid) == (MessageFeedback.LIKE, None)


async def test_khoa_go_sai_nhan_422(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    cay: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    """`extra="forbid"`: `{"rating": "like"}` là `422`, không phải một lần bấm vô hiệu."""
    _, _, amid = cay

    resp = await client.post(DANH_GIA.format(amid), headers=_phien(user_a), json={"rating": "like"})

    assert resp.status_code == 422, resp.text
    assert await _doc_cot_feedback(session_factory, amid) == (None, None)


async def test_gia_tri_ngoai_enum_nhan_422(
    client: AsyncClient, user_a: uuid.UUID, cay: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
) -> None:
    _, _, amid = cay
    resp = await client.post(DANH_GIA.format(amid), headers=_phien(user_a), json={"value": "meh"})
    assert resp.status_code == 422, resp.text


# ════════════════ 4. Quyền — §20, và `404` chứ KHÔNG `403` ═══════════════════


async def test_DoD_IDOR_danh_gia_message_cua_nguoi_khac_nhan_404(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_b: uuid.UUID,
    cay: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    """DoD dòng 1, ca IDOR: B đánh giá message của A ⇒ **404**, không `403`.

    `403` xác nhận cho kẻ dò rằng message đó có thật (§20). Và phép kiểm không
    dừng ở con số: cột `feedback` phải **không đổi**, vì một `404` trả về sau
    khi đã ghi là một câu nói dối lịch sự.
    """
    _, _, amid = cay

    resp = await client.post(DANH_GIA.format(amid), headers=_phien(user_b), json={"value": "like"})

    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == ApiErrorCode.MESSAGE_NOT_FOUND.value
    assert await _doc_cot_feedback(session_factory, amid) == (None, None)


async def test_id_khong_ton_tai_nhan_cung_mot_cau_tra_loi(
    client: AsyncClient,
    user_b: uuid.UUID,
    cay: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    """§20 đo bằng phép SO: id của người khác và id bịa ra phải trả lời GIỐNG HỆT.

    Một `404` mang `MESSAGE_NOT_FOUND` cho id có thật nhưng `NOT_FOUND` cho id
    bịa vẫn là một kênh rò rỉ hoàn chỉnh — kẻ dò đọc `code` thay vì đọc status.
    """
    _, _, amid = cay
    body = {"value": "like"}

    cua_nguoi_khac = await client.post(DANH_GIA.format(amid), headers=_phien(user_b), json=body)
    bia_ra = await client.post(DANH_GIA.format(uuid.uuid4()), headers=_phien(user_b), json=body)

    assert cua_nguoi_khac.status_code == bia_ra.status_code == 404
    assert cua_nguoi_khac.json() == bia_ra.json()


async def test_message_da_xoa_mem_nhan_404(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    cay: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    """Ca thứ ba mà §20 gộp chung: đã xoá mềm (C12) cũng là `404`."""
    _, _, amid = cay
    async with session_factory() as session:
        assert await MessageRepository(session).soft_delete_message(amid, user_id=user_a)
        await session.commit()

    resp = await client.post(DANH_GIA.format(amid), headers=_phien(user_a), json={"value": "like"})

    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == ApiErrorCode.MESSAGE_NOT_FOUND.value


async def test_danh_gia_message_user_nhan_400(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    cay: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    """§18.2/UC-02 đặt hai nút dưới **câu trả lời** ⇒ `400 MESSAGE_ROLE_MISMATCH`.

    `400` chứ không `404`: message ấy là của chính người gọi và họ biết nó tồn
    tại, nên gộp vào câu trả lời của §20 sẽ che mất lỗi thật của FE.
    """
    _, uid, _ = cay

    resp = await client.post(DANH_GIA.format(uid), headers=_phien(user_a), json={"value": "like"})

    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["code"] == ApiErrorCode.MESSAGE_ROLE_MISMATCH.value
    assert await _doc_cot_feedback(session_factory, uid) == (None, None)


async def test_repository_loc_user_id_NGAY_TRONG_cau_UPDATE(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    cay: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    """Gọi THẲNG `set_feedback` với `user_id` của B ⇒ `False`, cột không đổi.

    Ca này đi vòng qua HTTP là có chủ ý. Tầng API đã chặn B ở `_message_cua_toi`,
    nên mọi phép đo qua HTTP vẫn xanh **kể cả khi** phép lọc `user_id` bị gỡ
    khỏi câu `UPDATE` — và lúc ấy §20 mất lớp ở đúng chỗ nó đòi phải có: câu SQL
    **ghi**, không phải một lần đọc trước đó rồi tin vào nó.

    Vế `True` của A đi kèm để khẳng định vế `False` không đúng vì một lý do khác
    (sai id, sai bảng, một câu `WHERE` không khớp gì cả).
    """
    _, _, amid = cay
    async with session_factory() as session:
        repo = MessageRepository(session)
        assert (
            await repo.set_feedback(amid, user_id=user_b, value=MessageFeedback.LIKE, reason=None)
            is False
        )
        await session.commit()
    assert await _doc_cot_feedback(session_factory, amid) == (None, None)

    async with session_factory() as session:
        repo = MessageRepository(session)
        assert (
            await repo.set_feedback(amid, user_id=user_a, value=MessageFeedback.LIKE, reason=None)
            is True
        )
        await session.commit()
    assert await _doc_cot_feedback(session_factory, amid) == (MessageFeedback.LIKE, None)


# ═════════ 5. `feedback` đi ra theo đường đi — DoD dòng 3 (F5 phải đúng) ══════


async def test_DoD_GET_conversation_tra_feedback_trong_moi_phan_tu_cua_path(
    client: AsyncClient, user_a: uuid.UUID, cay: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
) -> None:
    """DoD dòng 3: FE vẽ lại hai nút sau F5 bằng `path`, không bằng state của nó."""
    conversation_id, uid, amid = cay
    await client.post(
        DANH_GIA.format(amid),
        headers=_phien(user_a),
        json={"value": "like", "reason": "dung y minh can"},
    )

    resp = await client.get(HOI_THOAI.format(conversation_id), headers=_phien(user_a))

    assert resp.status_code == 200, resp.text
    path = resp.json()["path"]
    assert [p["id"] for p in path] == [str(uid), str(amid)]
    assert all("feedback" in p for p in path), "mọi phần tử phải có trường, kể cả khi null"
    assert path[0]["feedback"] is None
    assert path[1]["feedback"] == "like"
    # Lý do KHÔNG đi theo đường đi: nó là trường tự do dài nhất của bảng và
    # đường đi là thứ được tải lại mỗi lần mở một hội thoại.
    assert "feedback_reason" not in path[1]


async def test_siblings_cung_tra_feedback(
    client: AsyncClient, user_a: uuid.UUID, cay: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
) -> None:
    """`GET /messages/{id}/siblings` dùng CHUNG `MessageTrenDuongDi` (T-1.13).

    Hai chỗ trả cùng một hình dạng là chủ ý của lớp ấy; test này giữ cho chủ ý
    đó còn đúng sau khi lớp mọc thêm một trường.
    """
    _, _, amid = cay
    await client.post(DANH_GIA.format(amid), headers=_phien(user_a), json={"value": "dislike"})

    resp = await client.get(ANH_EM.format(amid), headers=_phien(user_a))

    assert resp.status_code == 200, resp.text
    assert [i["feedback"] for i in resp.json()["items"]] == ["dislike"]


# ══════ 6. DDL và hằng số Python có còn khớp không (xem docstring module) ═════


async def test_DDL_chan_ly_do_vuot_tran_du_schema_co_bi_noi(
    session_factory: async_sessionmaker[AsyncSession],
    cay: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    """`UPDATE` thẳng với `max + 1` ký tự ⇒ `IntegrityError` từ Postgres.

    Đi vòng qua tầng API là có chủ ý: phép kiểm này không đo endpoint, nó đo
    **CHECK của migration 0005 có đúng con số `FEEDBACK_REASON_MAX_CHARS` hay
    không**. Nới hằng số Python mà quên viết migration sẽ làm ca này đỏ —
    thay vì làm một `422` lặng lẽ biến thành `500` trên máy người dùng.
    """
    _, _, amid = cay
    async with session_factory() as session:
        stmt = (
            update(Message)
            .where(Message.id == amid)
            .values(
                feedback=MessageFeedback.DISLIKE,
                feedback_reason="x" * (FEEDBACK_REASON_MAX_CHARS + 1),
            )
        )
        with pytest.raises(IntegrityError, match="ck_msg_feedback_reason_len"):
            await session.execute(stmt)
        await session.rollback()


async def test_DDL_chan_ly_do_khong_co_danh_gia(
    session_factory: async_sessionmaker[AsyncSession],
    cay: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    """Lý do mà `feedback IS NULL` ⇒ `IntegrityError`, kể cả khi không qua endpoint."""
    _, _, amid = cay
    async with session_factory() as session:
        stmt = (
            update(Message)
            .where(Message.id == amid)
            .values(feedback=None, feedback_reason="mot ly do mo coi")
        )
        with pytest.raises(IntegrityError, match="ck_msg_feedback_reason_needs_value"):
            await session.execute(stmt)
        await session.rollback()
