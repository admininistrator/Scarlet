"""Migration 0007 — `usage_events.purpose` và CHECK của nó (T-S.7, §24.2b·S14).

KH tham chiếu: §24.2b·S6, S14 · tasks.md T-S.7 · NQ-110.

Hai bản của cùng một tập giá trị phải khớp: `UsagePurpose` (tầng app) và
`_PURPOSES` đông cứng của migration 0007. Cùng lối `test_reasoning_effort_column.py`:
đâm thẳng vào Postgres để `DEFAULT` và `CHECK` tự nói ra hành vi thật, không tin
lời một hằng Python.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import UsagePurpose

_MIGRATION = Path(__file__).resolve().parents[2] / "alembic" / "versions"

#: `INSERT` viết tay KHÔNG nêu `purpose` — đúng hình dạng mọi câu ghi sổ trước
#: T-S.7 và mọi `INSERT` tay trong `psql` mà `DEFAULT` của DDL sinh ra để đỡ.
_INSERT_WITHOUT_PURPOSE = text(
    "INSERT INTO usage_events (user_id, model_id, provider, key_source, price_snapshot) "
    "VALUES (:u, 'm', 'p', 'system', '{}') RETURNING id, purpose"
)


def _migration_purposes() -> tuple[str, ...]:
    """`_PURPOSES` của migration 0007, đọc bằng import theo đường dẫn."""
    (path,) = _MIGRATION.glob("0007_*.py")
    spec = importlib.util.spec_from_file_location("migration_0007", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    purposes: tuple[str, ...] = module._PURPOSES
    return purposes


def test_two_copies_of_the_set_agree() -> None:
    assert tuple(p.value for p in UsagePurpose) == _migration_purposes()


async def test_column_is_not_null_text_default_chat(
    session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    """Mọi hàng có trước 0007 (và mọi `INSERT` tay) đọc ra `chat` — đúng nghĩa của chúng."""
    async with session_factory() as session:
        row = await session.execute(
            text(
                "SELECT data_type, is_nullable, column_default FROM information_schema.columns "
                "WHERE table_name = 'usage_events' AND column_name = 'purpose'"
            )
        )
        assert tuple(row.one()) == ("text", "NO", "'chat'::text")
        inserted = (await session.execute(_INSERT_WITHOUT_PURPOSE, {"u": user_a})).one()
        assert inserted.purpose == "chat"
        await session.rollback()


@pytest.mark.parametrize("purpose", [p.value for p in UsagePurpose])
async def test_DDL_accepts_every_purpose(
    session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID, purpose: str
) -> None:
    async with session_factory() as session:
        stored = await session.execute(
            text(
                "INSERT INTO usage_events (user_id, model_id, provider, key_source, "
                "price_snapshot, purpose) VALUES (:u, 'm', 'p', 'system', '{}', :purpose) "
                "RETURNING purpose"
            ),
            {"u": user_a, "purpose": purpose},
        )
        assert stored.scalar_one() == purpose
        await session.rollback()


async def test_DDL_rejects_value_outside_the_set(
    session_factory: async_sessionmaker[AsyncSession], user_a: uuid.UUID
) -> None:
    """CHECK `ck_usage_purpose` — một chuỗi lạ là một dòng sổ không ai dựng lại quota đúng được."""
    async with session_factory() as session:
        with pytest.raises(IntegrityError, match="ck_usage_purpose"):
            await session.execute(
                text(
                    "INSERT INTO usage_events (user_id, model_id, provider, key_source, "
                    "price_snapshot, purpose) VALUES (:u, 'm', 'p', 'system', '{}', 'probe')"
                ),
                {"u": user_a},
            )
        await session.rollback()
