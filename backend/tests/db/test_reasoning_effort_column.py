"""Migration 0006 — `messages.reasoning_effort` và CHECK bộ từ vựng (T-S.6).

KH tham chiếu: §24.2b·S3b, S14 · tasks.md T-S.6.

Bộ từ vựng mức suy luận sống ở **ba** chỗ, và cả ba phải khớp: dữ liệu của
catalog (`catalog.REASONING_LEVELS`), bản đông cứng của migration (`_LEVELS`
của 0006), và bản của metadata (`Message.REASONING_EFFORT_LEVELS` — chép tay vì
import catalog là nạp một file JSON). Cùng lối hai ca DDL cuối của
`tests/api/test_feedback.py`: đâm thẳng vào Postgres để CHECK nói ra con số
thật của nó, chứ không tin vào lời của một hằng Python.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.catalog import REASONING_LEVELS
from app.db.models import Message, MessageRole, MessageStatus
from app.db.models.message import REASONING_EFFORT_LEVELS
from app.db.repositories import ConversationRepository, MessageRepository

_MIGRATION = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _migration_levels() -> tuple[str, ...]:
    """`_LEVELS` của migration 0006, đọc bằng import theo đường dẫn (tên file có số)."""
    (path,) = _MIGRATION.glob("0006_*.py")
    spec = importlib.util.spec_from_file_location("migration_0006", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    levels: tuple[str, ...] = module._LEVELS
    return levels


async def _answer(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> uuid.UUID:
    async with session_factory() as session:
        conversation = await ConversationRepository(session).create_conversation(user_id=user_id)
        message = await MessageRepository(session).create_message(
            conversation_id=conversation.id,
            user_id=user_id,
            role=MessageRole.ASSISTANT,
            status=MessageStatus.QUEUED,
            model_id="m",
            reasoning_effort="high",
        )
        await session.commit()
        return message.id


def test_three_copies_of_the_vocabulary_agree() -> None:
    assert tuple(REASONING_LEVELS) == REASONING_EFFORT_LEVELS == _migration_levels()


async def test_column_is_nullable_text_and_existing_rows_read_NULL(
    session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    """`NULL` = không gửi tham số suy luận nào — trạng thái của mọi hàng có trước 0006."""
    async with session_factory() as session:
        conversation = await ConversationRepository(session).create_conversation(user_id=user_a)
        message = await MessageRepository(session).create_message(
            conversation_id=conversation.id, user_id=user_a, role=MessageRole.USER, content="x"
        )
        await session.commit()
        row = await session.execute(
            text(
                "SELECT data_type, is_nullable, column_default FROM information_schema.columns "
                "WHERE table_name = 'messages' AND column_name = 'reasoning_effort'"
            )
        )
        assert tuple(row.one()) == ("text", "YES", None)
        assert (await session.get(Message, message.id)).reasoning_effort is None  # type: ignore[union-attr]


@pytest.mark.parametrize("level", REASONING_EFFORT_LEVELS)
async def test_DDL_accepts_every_level_of_the_vocabulary(
    session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID, level: str
) -> None:
    amid = await _answer(session_factory, user_a)
    async with session_factory() as session:
        await session.execute(
            update(Message).where(Message.id == amid).values(reasoning_effort=level)
        )
        await session.commit()


@pytest.mark.parametrize("junk", ["", "ultra-bogus", "HIGH", "minimal"])
async def test_DDL_blocks_a_level_outside_the_vocabulary(
    session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID, junk: str
) -> None:
    """Đường không qua API (psql tay, migration sau) vẫn không ghi được chip rác."""
    amid = await _answer(session_factory, user_a)
    async with session_factory() as session:
        stmt = update(Message).where(Message.id == amid).values(reasoning_effort=junk)
        with pytest.raises(IntegrityError, match="ck_msg_reasoning_effort_level"):
            await session.execute(stmt)
        await session.rollback()
