"""T-7.6 — progressive disclosure ba tầng + tool `load_skill` (§13.2, §13.5, §9.6, C30).

KH tham chiếu: §13.2, §13.5, §9.6, C30 · NQ-147 (Q-P7-3).

Cùng khung giả của `test_tool_loop.py`: LLM giả (`SeqClient`), Postgres +
`context.build` + registry thật. Skill viết dưới `tmp_path` (`SKILLS_DIR` của
registry vá về đó — `make test` không đụng `skills/` thật), sổ `skills` +
`user_skills` ghi bằng `SkillRepository` thật.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_generate import FakeRedis, _ctx
from test_tool_loop import (  # noqa: F401 — fixture autouse của khung tool-loop
    NO_TOOLS_MODEL,
    ROUND2,
    TOOLS_MODEL,
    SeqClient,
    _bind_session,
    _calls_turn,
    _tree,
    quota_redis,
)

from app.config.catalog import get_model
from app.config.settings import settings
from app.db.repositories import SkillRepository
from app.llm import context as llm_context
from app.llm.client import ToolCall
from app.llm.tokens import count_messages
from app.quota import estimator
from app.tools import registry as registry_mod
from app.workers.generate import generate

#: `TOOLS_MODEL` miễn phí (giá 0) — dự toán cần model có `tools` VÀ có giá.
PRICED_TOOLS_MODEL = "claude-haiku"
SKILL = "demo"
OTHER = "khac"
BODY = "# Demo\n\nBước 1: gọi python-docx. Bước 2: lưu tệp vào thư mục hiện tại.\n"
#: Dài hơn mọi trần hợp lý — ca "đã cắt" cần nó vượt `SKILL_DESCRIPTION_MAX_CHARS`.
LONG_DESC = "Tạo và sửa tài liệu Word (.docx): " + "đoạn, bảng, tiêu đề, mục lục. " * 40


async def _skill(
    session: AsyncSession, root: Path, name: str, *, description: str = LONG_DESC
) -> None:
    (root / name).mkdir()
    (root / name / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: x\n---\n{BODY}", encoding="utf-8"
    )
    await SkillRepository(session).upsert(
        name=name,
        display_name=name,
        description=description,
        path=str(root / name),
        requires_execution=False,
    )


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def skills_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(registry_mod, "SKILLS_DIR", tmp_path)
    return tmp_path


async def _enable(session: AsyncSession, user_id: uuid.UUID, name: str) -> None:
    assert await SkillRepository(session).set_user_enabled(user_id, name, True)
    await session.commit()


def _load(call_id: str, name: str = SKILL) -> ToolCall:
    return ToolCall(call_id=call_id, name="load_skill", arguments=json.dumps({"name": name}))


def _tool_names(call: dict[str, object]) -> list[str]:
    tools = call["tools"]
    assert isinstance(tools, list)
    return [t["function"]["name"] for t in tools]


# ───────────────────────────── tầng 1 + công tắc ─────────────────────────────


async def test_zero_skills_enabled_no_skill_block_and_no_load_skill(
    session: AsyncSession, user_a: uuid.UUID, fake_redis: FakeRedis, skills_dir: Path
) -> None:
    """C30 "0 thuế": skill có trong sổ nhưng user chưa bật ⇒ không khối, `tools=None`."""
    await _skill(session, skills_dir, SKILL)
    message = await _tree(session, user_a, web_tools=False)
    client = SeqClient(ROUND2)

    await generate(_ctx(fake_redis, client), str(message.id))  # type: ignore[arg-type]

    assert [c["tools"] for c in client.calls] == [None]
    system = client.calls[0]["messages"][0]["content"]
    assert "load_skill" not in system and SKILL not in system


async def test_one_skill_enabled_tier1_has_name_and_cut_description_tools_has_load_skill(
    session: AsyncSession, user_a: uuid.UUID, fake_redis: FakeRedis, skills_dir: Path
) -> None:
    await _skill(session, skills_dir, SKILL)
    await _enable(session, user_a, SKILL)
    message = await _tree(session, user_a, web_tools=False)
    client = SeqClient(ROUND2)

    await generate(_ctx(fake_redis, client), str(message.id))  # type: ignore[arg-type]

    assert _tool_names(client.calls[0]) == ["load_skill"]  # web tắt ⇒ chỉ load_skill
    system = client.calls[0]["messages"][0]["content"]
    line = next(x for x in system.splitlines() if x.startswith(f"- {SKILL}: "))
    assert line == f"- {SKILL}: {llm_context.skill_description(LONG_DESC)}"
    assert LONG_DESC.strip() not in system and BODY not in system  # tầng 2 KHÔNG ở tầng 1


async def test_web_and_skill_both_on_all_three_tools(
    session: AsyncSession, user_a: uuid.UUID, fake_redis: FakeRedis, skills_dir: Path
) -> None:
    await _skill(session, skills_dir, SKILL)
    await _enable(session, user_a, SKILL)
    message = await _tree(session, user_a, web_tools=True)
    client = SeqClient(ROUND2)

    await generate(_ctx(fake_redis, client), str(message.id))  # type: ignore[arg-type]

    assert _tool_names(client.calls[0]) == ["fetch_url", "web_search", "load_skill"]


async def test_skill_on_model_without_tools_no_block_no_tools(
    session: AsyncSession, user_a: uuid.UUID, fake_redis: FakeRedis, skills_dir: Path
) -> None:
    """C18/C41: model không `tools` không gọi được `load_skill` ⇒ không quảng cáo nó."""
    await _skill(session, skills_dir, SKILL)
    await _enable(session, user_a, SKILL)
    message = await _tree(session, user_a, model_id=NO_TOOLS_MODEL, web_tools=False)
    client = SeqClient(ROUND2)

    await generate(_ctx(fake_redis, client), str(message.id))  # type: ignore[arg-type]

    assert [c["tools"] for c in client.calls] == [None]
    assert "load_skill" not in client.calls[0]["messages"][0]["content"]


def test_long_description_cut_at_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SKILL_DESCRIPTION_MAX_CHARS", 50)
    cut = llm_context.skill_description(LONG_DESC)
    assert len(cut) <= 50 and cut.endswith("…") and LONG_DESC.startswith(cut[:-1])
    assert llm_context.skill_description("ngắn") == "ngắn"
    assert llm_context.skill_description("x" * 50) == "x" * 50  # đúng trần ⇒ không cắt


# ───────────────────────────── tầng 2: load_skill ─────────────────────────────


async def test_load_skill_tool_result_is_skill_md_body_not_untrusted_block(
    session: AsyncSession, user_a: uuid.UUID, fake_redis: FakeRedis, skills_dir: Path
) -> None:
    await _skill(session, skills_dir, SKILL)
    await _enable(session, user_a, SKILL)
    message = await _tree(session, user_a, web_tools=False)
    client = SeqClient(_calls_turn(_load("c_l1")), ROUND2)

    await generate(_ctx(fake_redis, client), str(message.id))  # type: ignore[arg-type]

    kinds = fake_redis.kind
    assert kinds[:3] == ["start", "tool_call", "tool_result"] and kinds[-1] == "done"
    result = fake_redis.data(2)
    assert (result["ok"], result["name"]) == (True, "load_skill")
    sent = client.calls[1]["messages"][-1]
    assert sent["role"] == "tool" and sent["tool_call_id"] == "c_l1"
    assert sent["content"] == (skills_dir / SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "<untrusted_content" not in sent["content"]  # Cạm bẫy ⑤: nội dung của ta


async def test_load_skill_unknown_name_is_ok_false(
    session: AsyncSession, user_a: uuid.UUID, fake_redis: FakeRedis, skills_dir: Path
) -> None:
    await _skill(session, skills_dir, SKILL)
    await _enable(session, user_a, SKILL)
    message = await _tree(session, user_a, web_tools=False)
    client = SeqClient(_calls_turn(_load("c_x", "khong-co")), ROUND2)

    await generate(_ctx(fake_redis, client), str(message.id))  # type: ignore[arg-type]

    result = fake_redis.data(fake_redis.kind.index("tool_result"))
    assert (result["ok"], result["result"]["reason"]) == (False, "unknown_skill")
    assert client.calls[1]["messages"][-1]["content"] == (
        f"[load_skill lỗi: unknown_skill] Skill đang bật: {SKILL}."
    )
    assert fake_redis.last["type"] == "done"


async def test_load_skill_of_skill_user_did_not_enable_is_unknown_not_leaked(
    session: AsyncSession,
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    fake_redis: FakeRedis,
    skills_dir: Path,
) -> None:
    """Skill `OTHER` user B bật, user A không ⇒ A gọi nó là `unknown_skill`, chữ không lộ tên."""
    await _skill(session, skills_dir, SKILL)
    await _skill(session, skills_dir, OTHER)
    await _enable(session, user_a, SKILL)
    await _enable(session, user_b, OTHER)
    message = await _tree(session, user_a, web_tools=False)
    client = SeqClient(_calls_turn(_load("c_o", OTHER)), ROUND2)

    await generate(_ctx(fake_redis, client), str(message.id))  # type: ignore[arg-type]

    sent = client.calls[1]["messages"][-1]["content"]
    assert "unknown_skill" in sent and OTHER not in sent.split("]", 1)[1]
    assert f"- {OTHER}:" not in client.calls[0]["messages"][0]["content"]


# ───────────────────────────── lượt sau, quota, §9.6 ─────────────────────────────


async def test_next_turn_after_load_skill_has_no_web_line_no_skill_body(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    skills_dir: Path,
) -> None:
    await _skill(session, skills_dir, SKILL)
    await _enable(session, user_a, SKILL)
    first = await _tree(session, user_a, web_tools=False)
    client = SeqClient(_calls_turn(_load("c_l1")), ROUND2)
    await generate(_ctx(fake_redis, client), str(first.id))  # type: ignore[arg-type]
    nxt = await _tree(
        session,
        user_a,
        question="cảm ơn",
        parent_id=first.id,
        conversation_id=first.conversation_id,
    )
    model = get_model(TOOLS_MODEL)
    assert model is not None

    async with session_factory() as fresh:
        built = await llm_context.build(fresh, nxt.id, model, user_id=user_a)

    dumped = json.dumps(built, ensure_ascii=False)
    assert "đã dùng web" not in dumped and "Bước 1: gọi python-docx" not in dumped


async def test_quota_estimate_of_skill_turn_counts_tool_rounds(
    session: AsyncSession, user_a: uuid.UUID, skills_dir: Path
) -> None:
    """Lượt có skill mời `load_skill` ⇒ tới `MAX_TOOL_ROUNDS + 1` lần gọi (Q-P6-6)."""
    await _skill(session, skills_dir, SKILL)
    await _enable(session, user_a, SKILL)
    message = await _tree(session, user_a, model_id=PRICED_TOOLS_MODEL, web_tools=False)
    model = get_model(PRICED_TOOLS_MODEL)
    assert model is not None

    estimated = await estimator._estimate(
        session, leaf_id=message.id, model=model, user_id=user_a, web_tools=False
    )

    built = await llm_context.build(session, message.id, model, user_id=user_a)
    assert estimated.est_max_usd == estimator.estimate(model, built, web_tools=True).est_max_usd > 0


async def test_budget_too_small_for_skill_block_drops_it_keeps_question(
    session: AsyncSession,
    user_a: uuid.UUID,
    skills_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§9.6: skill descriptions xếp sau system prompt — hẹp ngân sách ⇒ bỏ chúng, không nổ."""
    await _skill(session, skills_dir, SKILL)
    message = await _tree(session, user_a, web_tools=False)
    model = get_model(TOOLS_MODEL)
    assert model is not None
    bare = count_messages(
        await llm_context.build(session, message.id, model, user_id=user_a), model_id=model.id
    )
    await _enable(session, user_a, SKILL)
    full = count_messages(
        await llm_context.build(session, message.id, model, user_id=user_a), model_id=model.id
    )
    assert full > bare
    room = (bare + full) // 2
    cap = min(model.context_window, settings.CONTEXT_WINDOW_CAP) - model.max_output
    monkeypatch.setattr(settings, "RESERVE_TOKENS", cap - room)

    built = await llm_context.build(session, message.id, model, user_id=user_a)

    assert f"- {SKILL}:" not in built[0]["content"]
    assert built[-1]["role"] == "user"
