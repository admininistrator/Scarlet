"""T-1.2 — truy vấn đường đi (`get_path`) và đếm anh em (`get_siblings`).

KH tham chiếu: §8.3, C11, C12, C13, NQ-18.

Bốn dòng DoD của task nằm ở các test có chữ `DoD` trong docstring:

- `test_get_path_tra_dung_bon_message_cua_dung_nhanh` — cây 3 nhánh × 4 tầng
- `test_get_path_goc_co_ba_anh_em_thi_sibling_count_bang_3` — `parent_id IS NULL`
- `test_get_path_tren_cay_500_message_duoi_nguong` — `EXPLAIN ANALYZE`
- (dòng "≥ 15 case xanh" là cả file này)

Hai phép kiểm quan trọng nhất không phải là "hàm chạy đúng" mà là "hàm KHÔNG
trả về thứ nó không được trả": C11 (đường đi không lẫn nhánh chị em) và C13
(`sibling_count` không đếm sang hội thoại khác). Cả hai đều xanh với một hàm
viết sai theo cách hiển nhiên, nên chúng được viết dưới dạng *so với tổng số
message trong cây*, không phải so với một danh sách chép tay.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import Select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.db.models import Conversation, Message, MessageRole
from app.db.repositories import (
    ConversationRepository,
    MessageRepository,
    path_statement,
)

#: DoD: `get_path` trên cây 500 message phải chạy dưới ngưỡng này (mili-giây).
NGUONG_MS = 50.0
#: Hình dạng cây cho phép đo: 100 tầng × 5 anh em = 500 message, đường đi dài 100.
SO_TANG_500 = 100
SO_ANH_EM_500 = 5


async def _tao_day(
    session: AsyncSession,
    conversation: Conversation,
    user_id: uuid.UUID,
    *,
    sau: int,
    goc: uuid.UUID | None = None,
    nhan: str = "",
) -> list[Message]:
    """Một dây thẳng `sau` tầng, treo dưới `goc` (None = tạo gốc mới của nhánh)."""
    messages = MessageRepository(session)
    day: list[Message] = []
    parent_id = goc
    for tang in range(sau):
        message = await messages.create_message(
            conversation_id=conversation.id,
            user_id=user_id,
            role=MessageRole.USER if tang % 2 == 0 else MessageRole.ASSISTANT,
            parent_id=parent_id,
            content=f"{nhan}t{tang}",
        )
        day.append(message)
        parent_id = message.id
    return day


async def _cay_ba_nhanh_bon_tang(
    session: AsyncSession, user_id: uuid.UUID
) -> tuple[Conversation, list[list[Message]]]:
    """Ba gốc anh em (`parent_id IS NULL`), mỗi gốc một dây sâu 4 → 12 message.

    Đây là hình dạng của DoD: "3 nhánh × 4 tầng". Ba nhánh tách nhau ngay từ
    gốc, nên một `get_path` lẫn nhánh sẽ lộ ra ngay bằng số lượng message.
    """
    conversation = await ConversationRepository(session).create_conversation(user_id=user_id)
    nhanh = [
        await _tao_day(session, conversation, user_id, sau=4, nhan=f"n{so}-") for so in range(3)
    ]
    return conversation, nhanh


async def _explain_analyze(
    connection: AsyncConnection, statement: Select[Any]
) -> tuple[float, str]:
    """Chạy `EXPLAIN (ANALYZE, BUFFERS)` trên ĐÚNG câu lệnh của `get_path`.

    Biên dịch bằng **dialect của chính kết nối** rồi đẩy thẳng xuống driver:
    câu lệnh được đo giống từng ký tự với câu `get_path` gửi đi, kể cả chỗ dùng
    bind param `$n` chứ không phải hằng số nhúng — plan của Postgres cho tham số
    và cho hằng số không nhất thiết giống nhau.

    Không dùng `text()` được: nó bỏ qua `:id_1` khi ngay sau là `::UUID` (dấu
    hai chấm đứng sau dấu hai chấm không được coi là bind param), nên tham số sẽ
    lọt xuống Postgres nguyên văn và thành lỗi cú pháp.
    """
    compiled = statement.compile(dialect=connection.sync_engine.dialect)
    tham_so = tuple(compiled.params[ten] for ten in compiled.positiontup or ())
    rows = await connection.exec_driver_sql(f"EXPLAIN (ANALYZE, BUFFERS) {compiled}", tham_so)
    plan = "\n".join(str(row[0]) for row in rows)
    khop = re.search(r"Execution Time: ([\d.]+) ms", plan)
    assert khop is not None, plan
    return float(khop.group(1)), plan


# ────────────────────────────── get_path ──────────────────────────────


async def test_get_path_tra_ve_goc_truoc_la_sau(session: AsyncSession, user_a: uuid.UUID) -> None:
    """§8.3: `ORDER BY depth DESC` — gốc đứng đầu, lá đứng cuối."""
    conversation = await ConversationRepository(session).create_conversation(user_id=user_a)
    day = await _tao_day(session, conversation, user_a, sau=4)

    duong_di = await MessageRepository(session).get_path(day[-1].id, user_id=user_a)

    assert [node.message.id for node in duong_di] == [m.id for m in day]
    assert duong_di[0].message.parent_id is None
    assert duong_di[-1].message.id == day[-1].id


async def test_get_path_tra_dung_bon_message_cua_dung_nhanh(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """DoD: cây 3 nhánh × 4 tầng, `get_path(lá nhánh 2)` → đúng 4, không lẫn nhánh 1/3."""
    _, nhanh = await _cay_ba_nhanh_bon_tang(session, user_a)

    duong_di = await MessageRepository(session).get_path(nhanh[1][-1].id, user_id=user_a)

    assert len(duong_di) == 4
    assert [node.message.id for node in duong_di] == [m.id for m in nhanh[1]]
    cua_nhanh_khac = {m.id for m in nhanh[0]} | {m.id for m in nhanh[2]}
    assert {node.message.id for node in duong_di} & cua_nhanh_khac == set()


async def test_get_path_khong_lan_sang_nhanh_chi_em_o_giua_cay(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """C11 — bug tốn tiền nhất của dự án, dưới dạng đếm được.

    Cây có 7 message; đường đi tới một lá chỉ được có 4. Một hàm dựng ngữ cảnh
    bằng `WHERE conversation_id = ... ORDER BY created_at` sẽ trả về cả 7.
    """
    conversation = await ConversationRepository(session).create_conversation(user_id=user_a)
    than = await _tao_day(session, conversation, user_a, sau=2, nhan="than-")
    nhanh_bo = await _tao_day(session, conversation, user_a, sau=3, goc=than[-1].id, nhan="bo-")
    nhanh_giu = await _tao_day(session, conversation, user_a, sau=2, goc=than[-1].id, nhan="giu-")
    tong = len(than) + len(nhanh_bo) + len(nhanh_giu)
    assert tong == 7

    duong_di = await MessageRepository(session).get_path(nhanh_giu[-1].id, user_id=user_a)

    assert len(duong_di) == 4
    assert [node.message.id for node in duong_di] == [m.id for m in than + nhanh_giu]
    assert {node.message.id for node in duong_di} & {m.id for m in nhanh_bo} == set()


async def test_get_path_cua_message_goc_tra_dung_mot_node(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    conversation = await ConversationRepository(session).create_conversation(user_id=user_a)
    day = await _tao_day(session, conversation, user_a, sau=3)

    duong_di = await MessageRepository(session).get_path(day[0].id, user_id=user_a)

    assert len(duong_di) == 1
    assert duong_di[0].message.id == day[0].id


async def test_get_path_leaf_khong_ton_tai_tra_rong(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    assert await MessageRepository(session).get_path(uuid.uuid4(), user_id=user_a) == []


async def test_get_path_leaf_da_xoa_mem_tra_rong(session: AsyncSession, user_a: uuid.UUID) -> None:
    conversation = await ConversationRepository(session).create_conversation(user_id=user_a)
    day = await _tao_day(session, conversation, user_a, sau=3)
    messages = MessageRepository(session)
    assert await messages.soft_delete_message(day[-1].id, user_id=user_a) is True

    assert await messages.get_path(day[-1].id, user_id=user_a) == []


async def test_get_path_cua_user_khac_tra_rong(
    session: AsyncSession, user_a: uuid.UUID, user_b: uuid.UUID
) -> None:
    """§20 — IDOR. A biết id lá của B vẫn không đọc được ngữ cảnh của B."""
    _, nhanh = await _cay_ba_nhanh_bon_tang(session, user_b)
    messages = MessageRepository(session)

    assert await messages.get_path(nhanh[0][-1].id, user_id=user_a) == []
    # Và B vẫn đọc được của chính mình — dòng trên không xanh chỉ vì hàm hỏng.
    assert len(await messages.get_path(nhanh[0][-1].id, user_id=user_b)) == 4


async def test_get_path_trong_conversation_da_xoa_mem_tra_rong(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    conversation, nhanh = await _cay_ba_nhanh_bon_tang(session, user_a)
    await ConversationRepository(session).soft_delete_conversation(conversation.id, user_id=user_a)

    assert await MessageRepository(session).get_path(nhanh[0][-1].id, user_id=user_a) == []


async def test_get_path_cat_o_to_tien_da_xoa_mem(session: AsyncSession, user_a: uuid.UUID) -> None:
    """C12 — CTE lọc `deleted_at IS NULL` ở CẢ HAI nhánh, không chỉ nhánh neo.

    Không có bộ lọc ở nhánh đệ quy thì message đã xoá vẫn lỏn vào ngữ cảnh gửi
    lên model. Có bộ lọc thì đường đi bị cắt tại đó — đúng như mong muốn.
    """
    conversation = await ConversationRepository(session).create_conversation(user_id=user_a)
    day = await _tao_day(session, conversation, user_a, sau=5)
    messages = MessageRepository(session)
    assert await messages.soft_delete_message(day[1].id, user_id=user_a) is True

    duong_di = await messages.get_path(day[-1].id, user_id=user_a)

    assert [node.message.id for node in duong_di] == [m.id for m in day[2:]]
    assert day[0].id not in {node.message.id for node in duong_di}


async def test_get_path_dung_lai_khi_parent_id_tro_sang_conversation_khac(
    session: AsyncSession, connection: AsyncConnection, user_a: uuid.UUID
) -> None:
    """Đường đi không rời khỏi hội thoại của lá, kể cả khi dữ liệu đã hỏng.

    `create_message` chặn việc nối hai cây ở đường GHI, nhưng FK của Postgres
    thì không: `messages.parent_id` chỉ đòi message cha tồn tại. Một lần sửa DB
    bằng tay, một migration vụng, là đủ để `get_path` gom ngữ cảnh của hai hội
    thoại lại làm một và gửi hết lên model (C11). Ở đây `parent_id` bị bẻ bằng
    SQL thô — đúng thứ mà repository không ngăn được.
    """
    conversation_1 = await ConversationRepository(session).create_conversation(user_id=user_a)
    day_1 = await _tao_day(session, conversation_1, user_a, sau=2, nhan="c1-")
    conversation_2 = await ConversationRepository(session).create_conversation(user_id=user_a)
    day_2 = await _tao_day(session, conversation_2, user_a, sau=2, nhan="c2-")
    await session.flush()
    await connection.execute(
        text("UPDATE messages SET parent_id = :lac WHERE id = :goc"),
        {"lac": day_2[-1].id, "goc": day_1[0].id},
    )

    duong_di = await MessageRepository(session).get_path(day_1[-1].id, user_id=user_a)

    assert [node.message.id for node in duong_di] == [m.id for m in day_1]
    assert {node.message.id for node in duong_di} & {m.id for m in day_2} == set()


# ─────────────────── sibling_index / sibling_count (C13) ───────────────────


async def test_get_path_goc_co_ba_anh_em_thi_sibling_count_bang_3(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """DoD: gốc (`parent_id IS NULL`) có 3 anh em → `sibling_count == 3`.

    Đây là case mà `parent_id = :parent_id` sẽ làm sai: trong SQL
    `NULL = NULL` cho UNKNOWN, nên mọi gốc sẽ báo `sibling_count == 0` và mũi
    tên `‹ n/m ›` biến mất đúng ở nhánh người dùng vừa tạo bằng cách sửa câu hỏi
    đầu tiên. Phải là `IS NOT DISTINCT FROM`.
    """
    _, nhanh = await _cay_ba_nhanh_bon_tang(session, user_a)

    duong_di = await MessageRepository(session).get_path(nhanh[1][-1].id, user_id=user_a)
    goc = duong_di[0]

    assert goc.message.parent_id is None
    assert goc.sibling_count == 3
    assert goc.sibling_index == 1  # nhánh 2 là gốc thứ hai được tạo
    # Các tầng dưới của nhánh này không có anh em nào.
    assert [node.sibling_count for node in duong_di[1:]] == [1, 1, 1]
    assert [node.sibling_index for node in duong_di[1:]] == [0, 0, 0]


async def test_get_path_sibling_index_theo_thu_tu_tao(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """Retry hai lần (§8.2) → ba anh em, index 0/1/2 theo thứ tự tạo."""
    conversation = await ConversationRepository(session).create_conversation(user_id=user_a)
    messages = MessageRepository(session)
    goc = (await _tao_day(session, conversation, user_a, sau=1))[0]
    tra_loi = [
        await messages.create_message(
            conversation_id=conversation.id,
            user_id=user_a,
            role=MessageRole.ASSISTANT,
            parent_id=goc.id,
            content=f"lan {lan}",
        )
        for lan in range(3)
    ]

    for mong_doi, message in enumerate(tra_loi):
        duong_di = await messages.get_path(message.id, user_id=user_a)
        assert duong_di[-1].sibling_index == mong_doi
        assert duong_di[-1].sibling_count == 3


async def test_get_path_khong_dem_anh_em_da_xoa_mem(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """Xoá mềm một anh em → `‹ n/m ›` phải tụt xuống, kể cả `sibling_index`."""
    conversation = await ConversationRepository(session).create_conversation(user_id=user_a)
    messages = MessageRepository(session)
    goc = (await _tao_day(session, conversation, user_a, sau=1))[0]
    tra_loi = [
        await messages.create_message(
            conversation_id=conversation.id,
            user_id=user_a,
            role=MessageRole.ASSISTANT,
            parent_id=goc.id,
            content=f"lan {lan}",
        )
        for lan in range(3)
    ]
    assert await messages.soft_delete_message(tra_loi[0].id, user_id=user_a) is True

    duong_di = await messages.get_path(tra_loi[2].id, user_id=user_a)

    assert duong_di[-1].sibling_count == 2
    assert duong_di[-1].sibling_index == 1  # đứng thứ 2 sau khi anh cả biến mất


async def test_get_path_khong_dem_anh_em_cua_conversation_khac(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """`parent_id IS NOT DISTINCT FROM NULL` là TRUE với mọi gốc của MỌI hội thoại.

    Thiếu điều kiện `conversation_id` thì gốc của một hội thoại sẽ đếm luôn gốc
    của tất cả hội thoại khác cùng user — C13 ở dạng khó thấy nhất, vì nó chỉ
    sai khi người dùng có nhiều hơn một hội thoại.
    """
    conversation_1 = await ConversationRepository(session).create_conversation(user_id=user_a)
    day_1 = await _tao_day(session, conversation_1, user_a, sau=1)
    await _tao_day(session, conversation_1, user_a, sau=1)
    conversation_2 = await ConversationRepository(session).create_conversation(user_id=user_a)
    for _ in range(3):
        await _tao_day(session, conversation_2, user_a, sau=1)

    duong_di = await MessageRepository(session).get_path(day_1[0].id, user_id=user_a)

    assert duong_di[0].sibling_count == 2  # KHÔNG phải 5


async def test_get_path_message_khong_co_anh_em_thi_count_bang_1(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """`sibling_count` đếm cả chính nó: một mình vẫn là `‹ 1/1 ›`, không phải 0."""
    conversation = await ConversationRepository(session).create_conversation(user_id=user_a)
    day = await _tao_day(session, conversation, user_a, sau=3)

    duong_di = await MessageRepository(session).get_path(day[-1].id, user_id=user_a)

    assert [node.sibling_count for node in duong_di] == [1, 1, 1]
    assert [node.sibling_index for node in duong_di] == [0, 0, 0]


# ───────────────────────────── get_siblings ─────────────────────────────


async def test_get_siblings_cua_goc_voi_parent_id_none(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """§8.3: `parent_id=None` phải trả cả ba gốc — đây là chỗ `=` sẽ trả rỗng."""
    _, nhanh = await _cay_ba_nhanh_bon_tang(session, user_a)

    anh_em = await MessageRepository(session).get_siblings(
        nhanh[0][0].conversation_id, None, user_id=user_a
    )

    assert [m.id for m in anh_em] == [nhanh[so][0].id for so in range(3)]


async def test_get_siblings_cua_mot_node_giua_cay(session: AsyncSession, user_a: uuid.UUID) -> None:
    conversation = await ConversationRepository(session).create_conversation(user_id=user_a)
    messages = MessageRepository(session)
    goc = (await _tao_day(session, conversation, user_a, sau=1))[0]
    tra_loi = [
        await messages.create_message(
            conversation_id=conversation.id,
            user_id=user_a,
            role=MessageRole.ASSISTANT,
            parent_id=goc.id,
            content=f"lan {lan}",
        )
        for lan in range(2)
    ]

    anh_em = await messages.get_siblings(conversation.id, goc.id, user_id=user_a)

    assert [m.id for m in anh_em] == [m.id for m in tra_loi]


async def test_get_siblings_sap_xep_xac_dinh_khi_trung_created_at(
    session: AsyncSession, connection: AsyncConnection, user_a: uuid.UUID
) -> None:
    """NQ-18: `clock_timestamp()` vẫn trùng được → khoá phụ `id` giữ thứ tự xác định.

    Ép ba gốc về cùng một `created_at` rồi đòi kết quả sắp theo `id`. Không có
    khoá phụ, Postgres được tự do trả ba dòng theo thứ tự bất kỳ và
    `sibling_index` sẽ nhảy giữa hai lần tải trang (C13).
    """
    _, nhanh = await _cay_ba_nhanh_bon_tang(session, user_a)
    goc_ids = [nhanh[so][0].id for so in range(3)]
    await connection.execute(
        text("UPDATE messages SET created_at = clock_timestamp() WHERE id = ANY(:ids)"),
        {"ids": goc_ids},
    )
    await connection.execute(
        text(
            "UPDATE messages SET created_at = ("
            "  SELECT min(created_at) FROM messages WHERE id = ANY(:ids)"
            ") WHERE id = ANY(:ids)"
        ),
        {"ids": goc_ids},
    )
    messages = MessageRepository(session)

    anh_em = await messages.get_siblings(nhanh[0][0].conversation_id, None, user_id=user_a)

    assert [m.id for m in anh_em] == sorted(goc_ids)
    # Và `get_path` phải đồng ý với `get_siblings` về vị trí — hai chỗ tính
    # `sibling_index` mà lệch nhau thì FE hiện một đằng, mũi tên nhảy một nẻo.
    for vi_tri, message in enumerate(anh_em):
        duong_di = await messages.get_path(message.id, user_id=user_a)
        assert duong_di[0].sibling_index == vi_tri
        assert duong_di[0].sibling_count == 3


async def test_get_siblings_bo_qua_ban_da_xoa_mem(session: AsyncSession, user_a: uuid.UUID) -> None:
    _, nhanh = await _cay_ba_nhanh_bon_tang(session, user_a)
    messages = MessageRepository(session)
    assert await messages.soft_delete_message(nhanh[1][0].id, user_id=user_a) is True

    anh_em = await messages.get_siblings(nhanh[0][0].conversation_id, None, user_id=user_a)

    assert [m.id for m in anh_em] == [nhanh[0][0].id, nhanh[2][0].id]


async def test_get_siblings_cua_user_khac_tra_rong(
    session: AsyncSession, user_a: uuid.UUID, user_b: uuid.UUID
) -> None:
    """§20 — A không đếm được nhánh của B dù biết `conversation_id`."""
    conversation_b, nhanh_b = await _cay_ba_nhanh_bon_tang(session, user_b)
    messages = MessageRepository(session)

    assert await messages.get_siblings(conversation_b.id, None, user_id=user_a) == []
    assert len(await messages.get_siblings(conversation_b.id, None, user_id=user_b)) == 3
    assert nhanh_b[0][0].parent_id is None


async def test_get_siblings_trong_conversation_da_xoa_mem_tra_rong(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    conversation, _ = await _cay_ba_nhanh_bon_tang(session, user_a)
    await ConversationRepository(session).soft_delete_conversation(conversation.id, user_id=user_a)

    assert (
        await MessageRepository(session).get_siblings(conversation.id, None, user_id=user_a) == []
    )


async def test_get_siblings_khong_lan_sang_conversation_khac(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    conversation_1, _ = await _cay_ba_nhanh_bon_tang(session, user_a)
    conversation_2 = await ConversationRepository(session).create_conversation(user_id=user_a)
    for _ in range(4):
        await _tao_day(session, conversation_2, user_a, sau=1)

    anh_em = await MessageRepository(session).get_siblings(conversation_1.id, None, user_id=user_a)

    assert len(anh_em) == 3  # KHÔNG phải 7
    assert {m.conversation_id for m in anh_em} == {conversation_1.id}


async def test_get_siblings_cua_node_khong_co_con_tra_rong(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    conversation = await ConversationRepository(session).create_conversation(user_id=user_a)
    day = await _tao_day(session, conversation, user_a, sau=2)

    assert (
        await MessageRepository(session).get_siblings(conversation.id, day[-1].id, user_id=user_a)
        == []
    )


# ───────────────────────────── DoD: hiệu năng ─────────────────────────────


async def test_get_path_tren_cay_500_message_duoi_nguong(
    session: AsyncSession, connection: AsyncConnection, user_a: uuid.UUID
) -> None:
    """DoD: cây 500 message → `get_path` chạy < 50 ms, đo bằng `EXPLAIN ANALYZE`.

    Cây được chèn TỪNG DÒNG một (NQ-18 ③): `INSERT ... SELECT generate_series`
    ghi 500 dòng trong cùng một micro-giây và `created_at` sẽ trùng hàng loạt,
    tức là đo trên một cây không giống cây thật.

    `ANALYZE messages` trước khi đo là cố ý: bảng trong transaction của test
    chưa có thống kê nào, planner thấy `reltuples = 0` và chọn plan cho một bảng
    rỗng. Đo một plan như thế không nói gì về production, nơi autovacuum đã chạy.
    """
    conversation = await ConversationRepository(session).create_conversation(user_id=user_a)
    messages = MessageRepository(session)
    parent_id: uuid.UUID | None = None
    la: Message | None = None
    for tang in range(SO_TANG_500):
        cung_tang = [
            await messages.create_message(
                conversation_id=conversation.id,
                user_id=user_a,
                role=MessageRole.USER if tang % 2 == 0 else MessageRole.ASSISTANT,
                parent_id=parent_id,
                content=f"t{tang}-{thu}",
            )
            for thu in range(SO_ANH_EM_500)
        ]
        la = cung_tang[0]
        parent_id = la.id
    assert la is not None

    await session.flush()
    tong = await connection.scalar(
        text("SELECT count(*) FROM messages WHERE conversation_id = :cid"),
        {"cid": conversation.id},
    )
    assert tong == SO_TANG_500 * SO_ANH_EM_500 == 500

    await connection.execute(text("ANALYZE messages"))
    thoi_gian_ms, plan = await _explain_analyze(connection, path_statement(la.id, user_id=user_a))
    print(f"\n=== EXPLAIN (ANALYZE, BUFFERS) get_path, cây 500 message ===\n{plan}")

    duong_di = await messages.get_path(la.id, user_id=user_a)
    assert len(duong_di) == SO_TANG_500
    assert duong_di[0].sibling_count == SO_ANH_EM_500
    assert thoi_gian_ms < NGUONG_MS, f"{thoi_gian_ms} ms ≥ {NGUONG_MS} ms\n{plan}"
