"""T-1.2 — truy vấn đường đi (`get_path`) và đếm anh em (`get_siblings`).

KH tham chiếu: §8.3, C11, C12, C13, NQ-18.

Bốn dòng DoD của task nằm ở các test có chữ `DoD` trong docstring:

- `test_get_path_returns_the_four_messages_of_the_branch` — cây 3 nhánh × 4 tầng
- `test_get_path_root_with_three_siblings_has_sibling_count_3` — `parent_id IS NULL`
- `test_get_path_on_500_message_tree_under_threshold` — `EXPLAIN ANALYZE`
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
THRESHOLD_MS = 50.0
#: Hình dạng cây cho phép đo: 100 tầng × 5 anh em = 500 message, đường đi dài 100.
LEVELS_500 = 100
SIBLINGS_500 = 5


async def _make_chain(
    session: AsyncSession,
    conversation: Conversation,
    user_id: uuid.UUID,
    *,
    depth: int,
    root: uuid.UUID | None = None,
    label: str = "",
) -> list[Message]:
    """Một dây thẳng `sau` tầng, treo dưới `goc` (None = tạo gốc mới của nhánh)."""
    messages = MessageRepository(session)
    day: list[Message] = []
    parent_id = root
    for level in range(depth):
        message = await messages.create_message(
            conversation_id=conversation.id,
            user_id=user_id,
            role=MessageRole.USER if level % 2 == 0 else MessageRole.ASSISTANT,
            parent_id=parent_id,
            content=f"{label}t{level}",
        )
        day.append(message)
        parent_id = message.id
    return day


async def _tree_three_branches_four_levels(
    session: AsyncSession, user_id: uuid.UUID
) -> tuple[Conversation, list[list[Message]]]:
    """Ba gốc anh em (`parent_id IS NULL`), mỗi gốc một dây sâu 4 → 12 message.

    Đây là hình dạng của DoD: "3 nhánh × 4 tầng". Ba nhánh tách nhau ngay từ
    gốc, nên một `get_path` lẫn nhánh sẽ lộ ra ngay bằng số lượng message.
    """
    conversation = await ConversationRepository(session).create_conversation(user_id=user_id)
    branches = [
        await _make_chain(session, conversation, user_id, depth=4, label=f"n{so}-")
        for so in range(3)
    ]
    return conversation, branches


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
    params = tuple(compiled.params[name] for name in compiled.positiontup or ())
    rows = await connection.exec_driver_sql(f"EXPLAIN (ANALYZE, BUFFERS) {compiled}", params)
    plan = "\n".join(str(row[0]) for row in rows)
    match = re.search(r"Execution Time: ([\d.]+) ms", plan)
    assert match is not None, plan
    return float(match.group(1)), plan


# ────────────────────────────── get_path ──────────────────────────────


async def test_get_path_returns_root_first_leaf_last(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """§8.3: `ORDER BY depth DESC` — gốc đứng đầu, lá đứng cuối."""
    conversation = await ConversationRepository(session).create_conversation(user_id=user_a)
    day = await _make_chain(session, conversation, user_a, depth=4)

    path_msgs = await MessageRepository(session).get_path(day[-1].id, user_id=user_a)

    assert [node.message.id for node in path_msgs] == [m.id for m in day]
    assert path_msgs[0].message.parent_id is None
    assert path_msgs[-1].message.id == day[-1].id


async def test_get_path_returns_the_four_messages_of_the_branch(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """DoD: cây 3 nhánh × 4 tầng, `get_path(lá nhánh 2)` → đúng 4, không lẫn nhánh 1/3."""
    _, branches = await _tree_three_branches_four_levels(session, user_a)

    path_msgs = await MessageRepository(session).get_path(branches[1][-1].id, user_id=user_a)

    assert len(path_msgs) == 4
    assert [node.message.id for node in path_msgs] == [m.id for m in branches[1]]
    other_branches = {m.id for m in branches[0]} | {m.id for m in branches[2]}
    assert {node.message.id for node in path_msgs} & other_branches == set()


async def test_get_path_does_not_stray_into_sibling_branch_mid_tree(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """C11 — bug tốn tiền nhất của dự án, dưới dạng đếm được.

    Cây có 7 message; đường đi tới một lá chỉ được có 4. Một hàm dựng ngữ cảnh
    bằng `WHERE conversation_id = ... ORDER BY created_at` sẽ trả về cả 7.
    """
    conversation = await ConversationRepository(session).create_conversation(user_id=user_a)
    trunk = await _make_chain(session, conversation, user_a, depth=2, label="than-")
    dropped_branch = await _make_chain(
        session, conversation, user_a, depth=3, root=trunk[-1].id, label="bo-"
    )
    kept_branch = await _make_chain(
        session, conversation, user_a, depth=2, root=trunk[-1].id, label="giu-"
    )
    total = len(trunk) + len(dropped_branch) + len(kept_branch)
    assert total == 7

    path_msgs = await MessageRepository(session).get_path(kept_branch[-1].id, user_id=user_a)

    assert len(path_msgs) == 4
    assert [node.message.id for node in path_msgs] == [m.id for m in trunk + kept_branch]
    assert {node.message.id for node in path_msgs} & {m.id for m in dropped_branch} == set()


async def test_get_path_of_root_returns_one_node(session: AsyncSession, user_a: uuid.UUID) -> None:
    conversation = await ConversationRepository(session).create_conversation(user_id=user_a)
    day = await _make_chain(session, conversation, user_a, depth=3)

    path_msgs = await MessageRepository(session).get_path(day[0].id, user_id=user_a)

    assert len(path_msgs) == 1
    assert path_msgs[0].message.id == day[0].id


async def test_get_path_missing_leaf_returns_empty(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    assert await MessageRepository(session).get_path(uuid.uuid4(), user_id=user_a) == []


async def test_get_path_soft_deleted_leaf_returns_empty(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    conversation = await ConversationRepository(session).create_conversation(user_id=user_a)
    day = await _make_chain(session, conversation, user_a, depth=3)
    messages = MessageRepository(session)
    assert await messages.soft_delete_message(day[-1].id, user_id=user_a) is True

    assert await messages.get_path(day[-1].id, user_id=user_a) == []


async def test_get_path_of_other_user_returns_empty(
    session: AsyncSession, user_a: uuid.UUID, user_b: uuid.UUID
) -> None:
    """§20 — IDOR. A biết id lá của B vẫn không đọc được ngữ cảnh của B."""
    _, branches = await _tree_three_branches_four_levels(session, user_b)
    messages = MessageRepository(session)

    assert await messages.get_path(branches[0][-1].id, user_id=user_a) == []
    # Và B vẫn đọc được của chính mình — dòng trên không xanh chỉ vì hàm hỏng.
    assert len(await messages.get_path(branches[0][-1].id, user_id=user_b)) == 4


async def test_get_path_in_soft_deleted_conversation_returns_empty(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    conversation, branches = await _tree_three_branches_four_levels(session, user_a)
    await ConversationRepository(session).soft_delete_conversation(conversation.id, user_id=user_a)

    assert await MessageRepository(session).get_path(branches[0][-1].id, user_id=user_a) == []


async def test_get_path_cuts_at_soft_deleted_ancestor(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """C12 — CTE lọc `deleted_at IS NULL` ở CẢ HAI nhánh, không chỉ nhánh neo.

    Không có bộ lọc ở nhánh đệ quy thì message đã xoá vẫn lỏn vào ngữ cảnh gửi
    lên model. Có bộ lọc thì đường đi bị cắt tại đó — đúng như mong muốn.
    """
    conversation = await ConversationRepository(session).create_conversation(user_id=user_a)
    day = await _make_chain(session, conversation, user_a, depth=5)
    messages = MessageRepository(session)
    assert await messages.soft_delete_message(day[1].id, user_id=user_a) is True

    path_msgs = await messages.get_path(day[-1].id, user_id=user_a)

    assert [node.message.id for node in path_msgs] == [m.id for m in day[2:]]
    assert day[0].id not in {node.message.id for node in path_msgs}


async def test_get_path_stops_when_parent_id_points_to_other_conversation(
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
    day_1 = await _make_chain(session, conversation_1, user_a, depth=2, label="c1-")
    conversation_2 = await ConversationRepository(session).create_conversation(user_id=user_a)
    day_2 = await _make_chain(session, conversation_2, user_a, depth=2, label="c2-")
    await session.flush()
    await connection.execute(
        text("UPDATE messages SET parent_id = :lac WHERE id = :goc"),
        {"lac": day_2[-1].id, "goc": day_1[0].id},
    )

    path_msgs = await MessageRepository(session).get_path(day_1[-1].id, user_id=user_a)

    assert [node.message.id for node in path_msgs] == [m.id for m in day_1]
    assert {node.message.id for node in path_msgs} & {m.id for m in day_2} == set()


# ─────────────────── sibling_index / sibling_count (C13) ───────────────────


async def test_get_path_root_with_three_siblings_has_sibling_count_3(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """DoD: gốc (`parent_id IS NULL`) có 3 anh em → `sibling_count == 3`.

    Đây là case mà `parent_id = :parent_id` sẽ làm sai: trong SQL
    `NULL = NULL` cho UNKNOWN, nên mọi gốc sẽ báo `sibling_count == 0` và mũi
    tên `‹ n/m ›` biến mất đúng ở nhánh người dùng vừa tạo bằng cách sửa câu hỏi
    đầu tiên. Phải là `IS NOT DISTINCT FROM`.
    """
    _, branches = await _tree_three_branches_four_levels(session, user_a)

    path_msgs = await MessageRepository(session).get_path(branches[1][-1].id, user_id=user_a)
    root = path_msgs[0]

    assert root.message.parent_id is None
    assert root.sibling_count == 3
    assert root.sibling_index == 1  # nhánh 2 là gốc thứ hai được tạo
    # Các tầng dưới của nhánh này không có anh em nào.
    assert [node.sibling_count for node in path_msgs[1:]] == [1, 1, 1]
    assert [node.sibling_index for node in path_msgs[1:]] == [0, 0, 0]


async def test_get_path_sibling_index_follows_creation_order(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """Retry hai lần (§8.2) → ba anh em, index 0/1/2 theo thứ tự tạo."""
    conversation = await ConversationRepository(session).create_conversation(user_id=user_a)
    messages = MessageRepository(session)
    root = (await _make_chain(session, conversation, user_a, depth=1))[0]
    answer = [
        await messages.create_message(
            conversation_id=conversation.id,
            user_id=user_a,
            role=MessageRole.ASSISTANT,
            parent_id=root.id,
            content=f"lan {attempt}",
        )
        for attempt in range(3)
    ]

    for expected, message in enumerate(answer):
        path_msgs = await messages.get_path(message.id, user_id=user_a)
        assert path_msgs[-1].sibling_index == expected
        assert path_msgs[-1].sibling_count == 3


async def test_get_path_ignores_soft_deleted_siblings(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """Xoá mềm một anh em → `‹ n/m ›` phải tụt xuống, kể cả `sibling_index`."""
    conversation = await ConversationRepository(session).create_conversation(user_id=user_a)
    messages = MessageRepository(session)
    root = (await _make_chain(session, conversation, user_a, depth=1))[0]
    answer = [
        await messages.create_message(
            conversation_id=conversation.id,
            user_id=user_a,
            role=MessageRole.ASSISTANT,
            parent_id=root.id,
            content=f"lan {attempt}",
        )
        for attempt in range(3)
    ]
    assert await messages.soft_delete_message(answer[0].id, user_id=user_a) is True

    path_msgs = await messages.get_path(answer[2].id, user_id=user_a)

    assert path_msgs[-1].sibling_count == 2
    assert path_msgs[-1].sibling_index == 1  # đứng thứ 2 sau khi anh cả biến mất


async def test_get_path_ignores_siblings_from_other_conversation(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """`parent_id IS NOT DISTINCT FROM NULL` là TRUE với mọi gốc của MỌI hội thoại.

    Thiếu điều kiện `conversation_id` thì gốc của một hội thoại sẽ đếm luôn gốc
    của tất cả hội thoại khác cùng user — C13 ở dạng khó thấy nhất, vì nó chỉ
    sai khi người dùng có nhiều hơn một hội thoại.
    """
    conversation_1 = await ConversationRepository(session).create_conversation(user_id=user_a)
    day_1 = await _make_chain(session, conversation_1, user_a, depth=1)
    await _make_chain(session, conversation_1, user_a, depth=1)
    conversation_2 = await ConversationRepository(session).create_conversation(user_id=user_a)
    for _ in range(3):
        await _make_chain(session, conversation_2, user_a, depth=1)

    path_msgs = await MessageRepository(session).get_path(day_1[0].id, user_id=user_a)

    assert path_msgs[0].sibling_count == 2  # KHÔNG phải 5


async def test_get_path_message_without_siblings_has_count_1(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """`sibling_count` đếm cả chính nó: một mình vẫn là `‹ 1/1 ›`, không phải 0."""
    conversation = await ConversationRepository(session).create_conversation(user_id=user_a)
    day = await _make_chain(session, conversation, user_a, depth=3)

    path_msgs = await MessageRepository(session).get_path(day[-1].id, user_id=user_a)

    assert [node.sibling_count for node in path_msgs] == [1, 1, 1]
    assert [node.sibling_index for node in path_msgs] == [0, 0, 0]


# ───────────────────────────── get_siblings ─────────────────────────────


async def test_get_siblings_of_root_with_parent_id_none(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """§8.3: `parent_id=None` phải trả cả ba gốc — đây là chỗ `=` sẽ trả rỗng."""
    _, branches = await _tree_three_branches_four_levels(session, user_a)

    siblings = await MessageRepository(session).get_siblings(
        branches[0][0].conversation_id, None, user_id=user_a
    )

    assert [m.id for m in siblings] == [branches[so][0].id for so in range(3)]


async def test_get_siblings_of_mid_tree_node(session: AsyncSession, user_a: uuid.UUID) -> None:
    conversation = await ConversationRepository(session).create_conversation(user_id=user_a)
    messages = MessageRepository(session)
    root = (await _make_chain(session, conversation, user_a, depth=1))[0]
    answer = [
        await messages.create_message(
            conversation_id=conversation.id,
            user_id=user_a,
            role=MessageRole.ASSISTANT,
            parent_id=root.id,
            content=f"lan {attempt}",
        )
        for attempt in range(2)
    ]

    siblings = await messages.get_siblings(conversation.id, root.id, user_id=user_a)

    assert [m.id for m in siblings] == [m.id for m in answer]


async def test_get_siblings_sort_deterministic_on_created_at_tie(
    session: AsyncSession, connection: AsyncConnection, user_a: uuid.UUID
) -> None:
    """NQ-18: `clock_timestamp()` vẫn trùng được → khoá phụ `id` giữ thứ tự xác định.

    Ép ba gốc về cùng một `created_at` rồi đòi kết quả sắp theo `id`. Không có
    khoá phụ, Postgres được tự do trả ba dòng theo thứ tự bất kỳ và
    `sibling_index` sẽ nhảy giữa hai lần tải trang (C13).
    """
    _, branches = await _tree_three_branches_four_levels(session, user_a)
    root_ids = [branches[so][0].id for so in range(3)]
    await connection.execute(
        text("UPDATE messages SET created_at = clock_timestamp() WHERE id = ANY(:ids)"),
        {"ids": root_ids},
    )
    await connection.execute(
        text(
            "UPDATE messages SET created_at = ("
            "  SELECT min(created_at) FROM messages WHERE id = ANY(:ids)"
            ") WHERE id = ANY(:ids)"
        ),
        {"ids": root_ids},
    )
    messages = MessageRepository(session)

    siblings = await messages.get_siblings(branches[0][0].conversation_id, None, user_id=user_a)

    assert [m.id for m in siblings] == sorted(root_ids)
    # Và `get_path` phải đồng ý với `get_siblings` về vị trí — hai chỗ tính
    # `sibling_index` mà lệch nhau thì FE hiện một đằng, mũi tên nhảy một nẻo.
    for index, message in enumerate(siblings):
        path_msgs = await messages.get_path(message.id, user_id=user_a)
        assert path_msgs[0].sibling_index == index
        assert path_msgs[0].sibling_count == 3


async def test_get_siblings_skips_soft_deleted_versions(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    _, branches = await _tree_three_branches_four_levels(session, user_a)
    messages = MessageRepository(session)
    assert await messages.soft_delete_message(branches[1][0].id, user_id=user_a) is True

    siblings = await messages.get_siblings(branches[0][0].conversation_id, None, user_id=user_a)

    assert [m.id for m in siblings] == [branches[0][0].id, branches[2][0].id]


async def test_get_siblings_of_other_user_returns_empty(
    session: AsyncSession, user_a: uuid.UUID, user_b: uuid.UUID
) -> None:
    """§20 — A không đếm được nhánh của B dù biết `conversation_id`."""
    conversation_b, branches_b = await _tree_three_branches_four_levels(session, user_b)
    messages = MessageRepository(session)

    assert await messages.get_siblings(conversation_b.id, None, user_id=user_a) == []
    assert len(await messages.get_siblings(conversation_b.id, None, user_id=user_b)) == 3
    assert branches_b[0][0].parent_id is None


async def test_get_siblings_in_soft_deleted_conversation_returns_empty(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    conversation, _ = await _tree_three_branches_four_levels(session, user_a)
    await ConversationRepository(session).soft_delete_conversation(conversation.id, user_id=user_a)

    assert (
        await MessageRepository(session).get_siblings(conversation.id, None, user_id=user_a) == []
    )


async def test_get_siblings_does_not_stray_into_other_conversation(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    conversation_1, _ = await _tree_three_branches_four_levels(session, user_a)
    conversation_2 = await ConversationRepository(session).create_conversation(user_id=user_a)
    for _ in range(4):
        await _make_chain(session, conversation_2, user_a, depth=1)

    siblings = await MessageRepository(session).get_siblings(
        conversation_1.id, None, user_id=user_a
    )

    assert len(siblings) == 3  # KHÔNG phải 7
    assert {m.conversation_id for m in siblings} == {conversation_1.id}


async def test_get_siblings_of_childless_node_returns_empty(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    conversation = await ConversationRepository(session).create_conversation(user_id=user_a)
    day = await _make_chain(session, conversation, user_a, depth=2)

    assert (
        await MessageRepository(session).get_siblings(conversation.id, day[-1].id, user_id=user_a)
        == []
    )


# ───────────────────────────── DoD: hiệu năng ─────────────────────────────


async def test_get_path_on_500_message_tree_under_threshold(
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
    leaf: Message | None = None
    for level in range(LEVELS_500):
        same_level = [
            await messages.create_message(
                conversation_id=conversation.id,
                user_id=user_a,
                role=MessageRole.USER if level % 2 == 0 else MessageRole.ASSISTANT,
                parent_id=parent_id,
                content=f"t{level}-{nth}",
            )
            for nth in range(SIBLINGS_500)
        ]
        leaf = same_level[0]
        parent_id = leaf.id
    assert leaf is not None

    await session.flush()
    total = await connection.scalar(
        text("SELECT count(*) FROM messages WHERE conversation_id = :cid"),
        {"cid": conversation.id},
    )
    assert total == LEVELS_500 * SIBLINGS_500 == 500

    await connection.execute(text("ANALYZE messages"))
    elapsed_ms, plan = await _explain_analyze(connection, path_statement(leaf.id, user_id=user_a))
    print(f"\n=== EXPLAIN (ANALYZE, BUFFERS) get_path, cây 500 message ===\n{plan}")

    path_msgs = await messages.get_path(leaf.id, user_id=user_a)
    assert len(path_msgs) == LEVELS_500
    assert path_msgs[0].sibling_count == SIBLINGS_500
    assert elapsed_ms < THRESHOLD_MS, f"{elapsed_ms} ms ≥ {THRESHOLD_MS} ms\n{plan}"
