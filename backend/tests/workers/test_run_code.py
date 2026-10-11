"""T-7.7a — tool `run_code` → `sandbox` → MinIO → artifact `kind=file` (§13.1 mức b, C29).

KH tham chiếu: §13.3, C28, C29, §14.1, ADR-09, A6 · NQ-147 (Q-P7-1, Q-P7-6) · B-372, B-403.

Cùng khung giả của `test_tool_loop.py` (LLM `SeqClient`, Postgres + registry thật).
Giả ở MỘT chỗ nối mỗi đường: client UDS của `sandbox` (`sandbox_client._client`
⇒ `httpx.MockTransport` — `execute` + `_parse` vẫn thật) và MinIO (`storage.put`).
Quyền chạy code cấp bằng `limit_override_json` thật (đường `get_effective_limits`).
"""

from __future__ import annotations

import base64
import json
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_generate import FakeRedis, _ctx, _read_ledger, _reload
from test_tool_loop import (  # noqa: F401 — fixture autouse của khung tool-loop
    ROUND2,
    TOOLS_MODEL,
    SeqClient,
    _bind_session,
    _calls_turn,
    _rounds,
    _tree,
    quota_redis,
)

from app.config.settings import settings
from app.core import storage
from app.db.models import Artifact, MessageStatus, User
from app.db.repositories import SkillRepository
from app.llm.client import ToolCall
from app.tools import registry as registry_mod
from app.tools import sandbox_client
from app.workers.generate import generate

PNG = b"\x89PNG\r\n\x1a\nfake"
REPLY: dict[str, Any] = {
    "exit_code": 0,
    "stdout": "ve xong\n",
    "stderr": "",
    "files_out": {},
    "timeout": False,
    "error": None,
}


class Sandbox:
    """`sandbox` giả sau client UDS: ghi body đã nhận, trả `reply` (hoặc ném)."""

    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []
        self.reply: dict[str, Any] = dict(REPLY)
        self.raises: Exception | None = None

    def client(self, timeout: float) -> httpx.AsyncClient:
        def handle(request: httpx.Request) -> httpx.Response:
            self.bodies.append(json.loads(request.content))
            if self.raises is not None:
                raise self.raises
            return httpx.Response(200, json=self.reply)

        return httpx.AsyncClient(transport=httpx.MockTransport(handle))


class Bucket:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = (data, content_type)


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def sandbox(monkeypatch: pytest.MonkeyPatch) -> Sandbox:
    fake = Sandbox()
    monkeypatch.setattr(sandbox_client, "_client", fake.client)
    return fake


@pytest.fixture
def bucket(monkeypatch: pytest.MonkeyPatch) -> Bucket:
    fake = Bucket()
    monkeypatch.setattr(storage, "put", fake.put)
    return fake


async def _grant(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Admin bật per-user (§16.3) — `limit_override`, tier `free` mặc định tắt."""
    await session.execute(
        update(User)
        .where(User.id == user_id)
        .values(limit_override_json={"can_execute_skills": True})
    )
    await session.commit()


def _run(call_id: str, code: str = "print(1)", **extra: Any) -> ToolCall:
    return ToolCall(call_id=call_id, name="run_code", arguments=json.dumps({"code": code, **extra}))


async def _turn(
    session: AsyncSession, user_id: uuid.UUID, fake_redis: FakeRedis, *calls: ToolCall
) -> SeqClient:
    message = await _tree(session, user_id, web_tools=False, question="Vẽ biểu đồ cột")
    client = SeqClient(_calls_turn(*calls), ROUND2)
    await generate(_ctx(fake_redis, client), str(message.id))  # type: ignore[arg-type]
    client.message_id = message.id  # type: ignore[attr-defined]
    return client


def _tool_result(fake_redis: FakeRedis) -> dict[str, Any]:
    data: dict[str, Any] = fake_redis.data(fake_redis.kind.index("tool_result"))
    return data


def _names(call: dict[str, Any]) -> list[str]:
    return [t["function"]["name"] for t in call["tools"] or []]


# ───────────────────────────── công tắc (gate thật ở T-7.8) ─────────────────────────────


async def test_no_permission_run_code_not_in_tools(
    session: AsyncSession, user_a: uuid.UUID, fake_redis: FakeRedis, sandbox: Sandbox
) -> None:
    """Tier `free` (`can_execute_skills=false`) ⇒ model không thấy `run_code` (C18)."""
    client = await _turn(session, user_a, fake_redis)

    assert [c["tools"] for c in client.calls] == [None]
    assert sandbox.bodies == []


async def test_permission_via_override_offers_run_code(
    session: AsyncSession, user_a: uuid.UUID, fake_redis: FakeRedis, sandbox: Sandbox
) -> None:
    await _grant(session, user_a)
    client = await _turn(session, user_a, fake_redis)

    assert _names(client.calls[0]) == ["run_code"]


# ───────────────────────────── chạy ─────────────────────────────


async def test_run_code_tool_result_has_stdout(
    session: AsyncSession,
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    sandbox: Sandbox,
    bucket: Bucket,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _grant(session, user_a)
    client = await _turn(session, user_a, fake_redis, _run("c1", "print('ve xong')"))

    assert fake_redis.kind[:3] == ["start", "tool_call", "tool_result"]
    assert fake_redis.kind[-1] == "done"
    assert (_tool_result(fake_redis)["ok"], _tool_result(fake_redis)["name"]) == (True, "run_code")
    # Code đi vào sandbox ĐÚNG như model gửi, chạy bằng `python main.py` (A6).
    assert sandbox.bodies[0]["files"] == {"main.py": "print('ve xong')"}
    assert sandbox.bodies[0]["cmd"] == ["python", "main.py"]
    sent = client.calls[1]["messages"][-1]
    assert sent["role"] == "tool" and "stdout:\nve xong\n" in sent["content"]
    assert "exit_code: 0" in sent["content"]
    # Một lượt = một message, MỘT dòng sổ (B-160), vòng ở `tool_rounds`.
    mid = client.message_id  # type: ignore[attr-defined]
    assert (await _reload(session_factory, mid)).status == MessageStatus.COMPLETED
    rounds = await _rounds(session_factory, mid)
    assert [r["name"] for r in rounds[0]["results"]] == ["run_code"]
    assert len(await _read_ledger(session_factory, user_a)) == 1


async def test_file_is_put_to_minio_artifact_file_created_and_event_emitted(
    session: AsyncSession,
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    sandbox: Sandbox,
    bucket: Bucket,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _grant(session, user_a)
    sandbox.reply["files_out"] = {"chart.png": base64.b64encode(PNG).decode()}
    client = await _turn(session, user_a, fake_redis, _run("c1"))

    [(key, (data, content_type))] = bucket.objects.items()
    assert (data, content_type) == (PNG, "image/png")
    assert key.startswith(f"{user_a}/") and key.endswith(".png")
    async with session_factory() as s:
        [art] = (
            await s.execute(
                select(Artifact).where(Artifact.message_id == client.message_id)  # type: ignore[attr-defined]
            )
        ).scalars()
    assert (art.kind, art.title, art.content, art.storage_key) == ("file", "chart.png", None, key)
    kinds = fake_redis.kind
    assert kinds.index("tool_result") < kinds.index("artifact") < kinds.index("done")
    event = fake_redis.data(kinds.index("artifact"))
    assert (event["artifact_id"], event["kind"], event["title"]) == (
        str(art.id),
        "file",
        "chart.png",
    )
    # C33: model chỉ thấy TÊN file, không byte.
    sent = client.calls[1]["messages"][-1]["content"]
    assert "files: chart.png" in sent and base64.b64encode(PNG).decode() not in sent


async def test_active_file_type_is_stored_as_octet_stream(
    session: AsyncSession,
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    sandbox: Sandbox,
    bucket: Bucket,
) -> None:
    """Tên do model đặt: `.html` không lên MinIO với loại trình duyệt chạy được."""
    await _grant(session, user_a)
    sandbox.reply["files_out"] = {"x.html": base64.b64encode(b"<script>1</script>").decode()}
    await _turn(session, user_a, fake_redis, _run("c1"))

    [(_, content_type)] = bucket.objects.values()
    assert content_type == "application/octet-stream"


async def test_skill_scripts_sent_flat_beside_code_unknown_skill_refused(
    session: AsyncSession,
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    sandbox: Sandbox,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Q-P7-6: chỉ script của skill ĐÃ BẬT; skill chưa bật ⇒ không gọi sandbox."""
    monkeypatch.setattr(registry_mod, "SKILLS_DIR", tmp_path)
    (tmp_path / "demo" / "scripts").mkdir(parents=True)
    (tmp_path / "demo" / "SKILL.md").write_text("---\nname: demo\n---\n", encoding="utf-8")
    (tmp_path / "demo" / "scripts" / "make_doc.py").write_text("X = 1\n", encoding="utf-8")
    await SkillRepository(session).upsert(
        name="demo", display_name="demo", description="d", path="x", requires_execution=True
    )
    assert await SkillRepository(session).set_user_enabled(user_a, "demo", True)
    await _grant(session, user_a)

    await _turn(
        session,
        user_a,
        fake_redis,
        _run("c1", "import make_doc", skill="demo"),
        _run("c2", "print(1)", skill="khac"),
    )

    assert sandbox.bodies[0]["files"] == {"make_doc.py": "X = 1\n", "main.py": "import make_doc"}
    assert len(sandbox.bodies) == 1  # `khac` không bao giờ tới sandbox
    second = fake_redis.data([i for i, k in enumerate(fake_redis.kind) if k == "tool_result"][1])
    assert (second["ok"], second["result"]["reason"]) == (False, "unknown_skill")


async def test_timeout_is_always_settings_not_model_argument(
    session: AsyncSession, user_a: uuid.UUID, fake_redis: FakeRedis, sandbox: Sandbox
) -> None:
    """B-403 ⑦: `sandbox` tin `timeout_s` của peer ⇒ không bao giờ lấy từ model."""
    await _grant(session, user_a)
    await _turn(session, user_a, fake_redis, _run("c1", timeout_s=99999))

    assert sandbox.bodies[0]["timeout_s"] == settings.SANDBOX_TIMEOUT_S


# ─────────────────────── hỏng ⇒ ok=False, lượt vẫn done (Cạm bẫy ⑥) ───────────────────────


async def test_sandbox_dead_is_ok_false_sandbox_unavailable_turn_done(
    session: AsyncSession,
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    sandbox: Sandbox,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _grant(session, user_a)
    sandbox.raises = httpx.ConnectError("No such file or directory")
    client = await _turn(session, user_a, fake_redis, _run("c1"))

    result = _tool_result(fake_redis)
    assert (result["ok"], result["result"]["reason"]) == (False, "sandbox_unavailable")
    assert fake_redis.kind[-1] == "done" and "error" not in fake_redis.kind
    assert client.calls[1]["messages"][-1]["content"].startswith(
        "[run_code lỗi: sandbox_unavailable] Không chạy được code"
    )
    row = await _reload(session_factory, client.message_id)  # type: ignore[attr-defined]
    assert row.status == MessageStatus.COMPLETED


async def test_infinite_loop_timeout_is_ok_false_turn_done(
    session: AsyncSession, user_a: uuid.UUID, fake_redis: FakeRedis, sandbox: Sandbox
) -> None:
    """`while True` ⇒ sandbox giết ở `SANDBOX_TIMEOUT_S` (`exit_code=-9`, `timeout`)."""
    await _grant(session, user_a)
    sandbox.reply.update(exit_code=-9, stdout="", timeout=True)
    await _turn(session, user_a, fake_redis, _run("c1", "while True: pass"))

    result = _tool_result(fake_redis)
    assert (result["ok"], result["result"]["reason"]) == (False, "timeout")
    assert fake_redis.kind[-1] == "done"


async def test_output_over_cap_is_ok_false_nothing_stored(
    session: AsyncSession,
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    sandbox: Sandbox,
    bucket: Bucket,
) -> None:
    """`MAX_SKILL_OUTPUT_MB` (server: `output_too_large`, không gửi byte)."""
    await _grant(session, user_a)
    sandbox.reply.update(error="output_too_large")
    await _turn(session, user_a, fake_redis, _run("c1"))

    result = _tool_result(fake_redis)
    assert (result["ok"], result["result"]["reason"]) == (False, "output_too_large")
    assert bucket.objects == {} and "artifact" not in fake_redis.kind
    assert fake_redis.kind[-1] == "done"


async def test_too_many_files_is_ok_false_nothing_stored(
    session: AsyncSession,
    user_a: uuid.UUID,
    fake_redis: FakeRedis,
    sandbox: Sandbox,
    bucket: Bucket,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MAX_SKILL_OUTPUT_FILES", 2)
    await _grant(session, user_a)
    sandbox.reply["files_out"] = {f"{i}.txt": "eA==" for i in range(3)}
    await _turn(session, user_a, fake_redis, _run("c1"))

    result = _tool_result(fake_redis)
    assert (result["ok"], result["result"]["reason"]) == (False, "too_many_files")
    assert bucket.objects == {} and "artifact" not in fake_redis.kind


async def test_exit_nonzero_is_ok_false_with_stderr_tail_for_model(
    session: AsyncSession, user_a: uuid.UUID, fake_redis: FakeRedis, sandbox: Sandbox
) -> None:
    await _grant(session, user_a)
    sandbox.reply.update(
        exit_code=1, stdout="", stderr="Traceback...\nModuleNotFoundError: No module named 'x'\n"
    )
    client = await _turn(session, user_a, fake_redis, _run("c1", "import x"))

    result = _tool_result(fake_redis)
    assert (result["ok"], result["result"]["reason"]) == (False, "exit_nonzero")
    sent = client.calls[1]["messages"][-1]["content"]
    assert sent.startswith("[run_code lỗi: exit_nonzero] exit_code: 1")
    assert "No module named 'x'" in sent  # model đọc được lỗi để sửa code
