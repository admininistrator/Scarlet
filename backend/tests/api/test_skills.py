"""T-7.5 — loader skill (spec agentskills.io) + `GET /skills` · `PUT /skills/{name}/toggle`.

Loader đọc thư mục skill **giả** dưới `tmp_path` (chỗ nối duy nhất — luật chung
P7: `make test` không đụng `skills/` thật), ghi vào Postgres thật của test.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import SKILL_SPEC_DESCRIPTION_MAX_CHARS
from app.core.access_token import encode_access_token
from app.core.deps import SESSION_COOKIE_NAME
from app.db.models import Skill, UserRole, UserSkill, UserStatus
from app.main import app
from app.skills.loader import sync_skills

SKILLS = "/api/v1/skills"
TOGGLE = "/api/v1/skills/{}/toggle"


def _write_skill(root: Path, directory: str, frontmatter: str, *, scripts: bool = False) -> None:
    path = root / directory
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n\n# {directory}\n", encoding="utf-8")
    if scripts:
        (path / "scripts").mkdir()
        (path / "scripts" / "run.py").write_text("print(1)\n", encoding="utf-8")


async def _sync(session_factory: async_sessionmaker[AsyncSession], root: Path) -> list[str]:
    async with session_factory() as session:
        specs = await sync_skills(session, root)
        await session.commit()
    return [s.name for s in specs]


async def _rows(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, Skill]:
    async with session_factory() as session:
        return {s.name: s for s in (await session.execute(select(Skill))).scalars()}


def _session(user_id: uuid.UUID) -> dict[str, str]:
    token = encode_access_token(
        user_id=user_id,
        role=UserRole.USER,
        tier="free",
        status=UserStatus.ACTIVE,
        ttl_minutes=15,
    )
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


@pytest.fixture
def _db_for_tests(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


@pytest_asyncio.fixture
async def client(event_hooks: dict[str, Any], _db_for_tests: None) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://localhost", event_hooks=event_hooks
    ) as http:
        yield http


@pytest_asyncio.fixture
async def two_skills(
    tmp_path: Path, session_factory: async_sessionmaker[AsyncSession]
) -> list[str]:
    _write_skill(tmp_path, "alpha", "name: alpha\ndescription: Alpha skill.")
    _write_skill(tmp_path, "beta", "name: beta\ndescription: Beta skill.", scripts=True)
    return await _sync(session_factory, tmp_path)


# ═══════ Loader ═══════


async def test_valid_frontmatter_registers_name_and_description(
    tmp_path: Path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    _write_skill(
        tmp_path,
        "pdf-tools",
        "name: pdf-tools\ndescription: Merge PDFs.\nlicense: MIT\n"
        "metadata:\n  display_name: PDF Tools\nallowed-tools: run_code",
    )
    assert await _sync(session_factory, tmp_path) == ["pdf-tools"]
    row = (await _rows(session_factory))["pdf-tools"]
    assert (row.description, row.display_name, row.path, row.enabled) == (
        "Merge PDFs.",
        "PDF Tools",
        str(tmp_path / "pdf-tools"),
        True,
    )
    assert row.requires_execution is False


async def test_requires_execution_follows_scripts_dir(
    two_skills: list[str], session_factory: async_sessionmaker[AsyncSession]
) -> None:
    rows = await _rows(session_factory)
    assert (rows["alpha"].requires_execution, rows["beta"].requires_execution) == (False, True)


async def test_name_mismatching_directory_is_skipped_and_logged(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _write_skill(tmp_path, "real-dir", "name: other-name\ndescription: Lies about its name.")
    with caplog.at_level(logging.WARNING, logger="app.skills.loader"):
        assert await _sync(session_factory, tmp_path) == []
    assert "real-dir" in caplog.text and "lech thu muc" in caplog.text
    assert await _rows(session_factory) == {}


async def test_missing_name_is_skipped(
    tmp_path: Path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    _write_skill(tmp_path, "nameless", "description: No name field.")
    assert await _sync(session_factory, tmp_path) == []
    assert await _rows(session_factory) == {}


async def test_description_over_spec_limit_is_skipped(
    tmp_path: Path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    too_long = "x" * (SKILL_SPEC_DESCRIPTION_MAX_CHARS + 1)
    _write_skill(tmp_path, "wordy", f"name: wordy\ndescription: {too_long}")
    _write_skill(tmp_path, "edge", f"name: edge\ndescription: {too_long[:-1]}")
    assert await _sync(session_factory, tmp_path) == ["edge"]


async def test_broken_yaml_is_skipped_other_skills_still_load(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _write_skill(tmp_path, "broken", "name: broken\ndescription: [unclosed")
    _write_skill(tmp_path, "no-fence", "irrelevant")
    (tmp_path / "no-fence" / "SKILL.md").write_text("name: no-fence\n", encoding="utf-8")
    _write_skill(tmp_path, "good", "name: good\ndescription: Still loads.")
    with caplog.at_level(logging.WARNING, logger="app.skills.loader"):
        assert await _sync(session_factory, tmp_path) == ["good"]
    assert "broken" in caplog.text and "no-fence" in caplog.text


@pytest.mark.parametrize("bad", ["Upper", "-lead", "trail-", "two--dash", "a" * 65])
async def test_name_breaking_spec_rules_is_skipped(
    bad: str, tmp_path: Path, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    _write_skill(tmp_path, bad, f"name: {bad}\ndescription: Bad name.")
    assert await _sync(session_factory, tmp_path) == []


async def test_skill_gone_from_disk_is_disabled_on_resync(
    tmp_path: Path, two_skills: list[str], session_factory: async_sessionmaker[AsyncSession]
) -> None:
    (tmp_path / "beta" / "SKILL.md").unlink()
    assert await _sync(session_factory, tmp_path) == ["alpha"]
    rows = await _rows(session_factory)
    assert (rows["alpha"].enabled, rows["beta"].enabled) == (True, False)


# ═══════ API ═══════


async def test_get_skills_fresh_user_sees_all_disabled(
    client: AsyncClient, two_skills: list[str], user_a: uuid.UUID
) -> None:
    resp = await client.get(SKILLS, headers=_session(user_a))
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"] == [
        {
            "name": "alpha",
            "display_name": "alpha",
            "description": "Alpha skill.",
            "requires_execution": False,
            "enabled": False,
        },
        {
            "name": "beta",
            "display_name": "beta",
            "description": "Beta skill.",
            "requires_execution": True,
            "enabled": False,
        },
    ]


async def test_put_toggle_writes_user_skills_and_get_reflects(
    client: AsyncClient,
    two_skills: list[str],
    user_a: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def user_rows() -> list[tuple[str, bool]]:
        async with session_factory() as session:
            stmt = select(UserSkill.skill_name, UserSkill.enabled).where(
                UserSkill.user_id == user_a
            )
            return [tuple(r) for r in (await session.execute(stmt)).all()]

    for enabled in (True, True, False):
        resp = await client.put(
            TOGGLE.format("beta"), headers=_session(user_a), json={"enabled": enabled}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["enabled"] is enabled
        assert await user_rows() == [("beta", enabled)]
        listed = (await client.get(SKILLS, headers=_session(user_a))).json()["items"]
        assert {s["name"]: s["enabled"] for s in listed} == {"alpha": False, "beta": enabled}


async def test_toggle_is_per_user(
    client: AsyncClient, two_skills: list[str], user_a: uuid.UUID, user_b: uuid.UUID
) -> None:
    await client.put(TOGGLE.format("alpha"), headers=_session(user_a), json={"enabled": True})
    listed = (await client.get(SKILLS, headers=_session(user_b))).json()["items"]
    assert all(s["enabled"] is False for s in listed)


async def test_toggle_unknown_or_disabled_skill_is_404(
    client: AsyncClient,
    tmp_path: Path,
    two_skills: list[str],
    user_a: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    resp = await client.put(TOGGLE.format("nope"), headers=_session(user_a), json={"enabled": True})
    assert (resp.status_code, resp.json()["error"]["code"]) == (404, "SKILL_NOT_FOUND")

    (tmp_path / "alpha" / "SKILL.md").unlink()
    await _sync(session_factory, tmp_path)
    resp = await client.put(
        TOGGLE.format("alpha"), headers=_session(user_a), json={"enabled": True}
    )
    assert resp.status_code == 404
    listed = (await client.get(SKILLS, headers=_session(user_a))).json()["items"]
    assert [s["name"] for s in listed] == ["beta"]


async def test_skills_require_session(client: AsyncClient) -> None:
    assert (await client.get(SKILLS)).status_code == 401
