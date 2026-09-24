"""T-S.7 — đặt tên hội thoại tự động, phía API (§24.2b·S6, NQ-110).

Hai nửa của task nằm ở tầng HTTP:

- `POST /conversations/{id}/messages` — câu hỏi **đầu tiên** của hội thoại
  chưa có tiêu đề đẩy thêm job `title` (job id `title:{id}`) ngay sau
  `generate`; câu thứ hai thì không (DoD dòng 6, nửa đầu).
- `GET /conversations/{id}/title/stream` — dùng lại consumer §7.3, lọc
  `user_id` trong SQL (IDOR ⇒ `404` nằm trong ma trận của
  `tests/security/test_idor.py`, DoD dòng 5).

Cùng hạ tầng với `test_messages.py`/`test_stream.py`: `httpx.ASGITransport`,
`session_scope()` trỏ về kết nối của test, pool arq giả.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.access_token import encode_access_token
from app.core.deps import SESSION_COOKIE_NAME
from app.db.models import Conversation, Message, UserRole, UserStatus
from app.db.repositories import ConversationRepository
from app.main import app
from app.streaming.producer import FIELD_DATA, FIELD_TYPE, title_stream_key

MESSAGES = "/api/v1/conversations/{}/messages"
TITLE_STREAM = "/api/v1/conversations/{}/title/stream"


class FakeArq:
    """Pool arq giả có đúng luật `_job_id` của arq: id đã có ⇒ `None`.

    Luật ấy là thứ biến "hai câu đầu song song" thành một job (NQ-110), nên
    fake phải mô phỏng nó chứ không trả `object()` cho mọi lần.
    """

    def __init__(self) -> None:
        self.pushed: list[tuple[str, tuple[Any, ...]]] = []
        self.accepted_ids: set[str] = set()
        self.rejected: list[str] = []
        self.raise_for: set[str] = set()

    async def enqueue_job(self, name: str, *args: Any, **kwargs: Any) -> object | None:
        if name in self.raise_for:
            raise ConnectionError("redis chet giua chung (gia lap)")
        job_id = kwargs.get("_job_id")
        if job_id is not None and job_id in self.accepted_ids:
            self.rejected.append(job_id)
            return None
        if job_id is not None:
            self.accepted_ids.add(job_id)
        self.pushed.append((name, args))
        return object()

    @property
    def names(self) -> list[str]:
        return [name for name, _ in self.pushed]


class TitleRedis:
    """Redis giả cho đầu đọc SSE: `streams` là dữ liệu có sẵn, `later` tới qua XREAD."""

    def __init__(
        self,
        streams: dict[str, list[tuple[str, dict[str, str]]]] | None = None,
        later: dict[str, list[tuple[str, dict[str, str]]]] | None = None,
    ) -> None:
        self.streams = streams or {}
        self.later = later or {}
        self.xread_calls = 0

    async def xrange(
        self, name: str, start: str, end: str, count: int | None = None
    ) -> list[tuple[str, dict[str, str]]]:
        mark = start[1:] if start.startswith("(") else start
        return [(eid, f) for eid, f in self.streams.get(name, []) if eid > mark]

    async def xrevrange(
        self, name: str, start: str, end: str, count: int | None = None
    ) -> list[tuple[str, dict[str, str]]]:
        return list(reversed(self.streams.get(name, [])))[: count or None]

    async def xread(self, streams: dict[str, str], **_: Any) -> Any:
        self.xread_calls += 1
        (name,) = streams
        entries = self.later.pop(name, [])
        return [(name, entries)] if entries else None

    async def exists(self, name: str) -> int:
        return 1 if name in self.streams else 0


@pytest.fixture(autouse=True)
def _db_for_tests(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


@pytest_asyncio.fixture
async def fake_arq(monkeypatch: pytest.MonkeyPatch) -> FakeArq:
    fake = FakeArq()

    async def _pool() -> FakeArq:
        return fake

    monkeypatch.setattr("app.api.v1.messages.get_arq_pool", _pool)
    return fake


@pytest_asyncio.fixture
async def client(event_hooks: dict[str, Any]) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://localhost", event_hooks=event_hooks
    ) as http:
        yield http


def _session(user_id: uuid.UUID) -> dict[str, str]:
    """Header `Cookie` mang phiên thật (§11.2) — cùng lối `test_messages.py`."""
    token = encode_access_token(
        user_id=user_id,
        role=UserRole.USER,
        tier="free",
        status=UserStatus.ACTIVE,
        ttl_minutes=15,
    )
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


async def _conversation(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID, **columns: Any
) -> uuid.UUID:
    async with session_factory() as session:
        conversation = await ConversationRepository(session).create_conversation(
            user_id=user_id, **columns
        )
        await session.commit()
        return conversation.id


def _events(body: str) -> list[tuple[str | None, str, dict[str, Any]]]:
    """Thân SSE → `(id, event, data)`; bỏ comment `: ping`."""
    out: list[tuple[str | None, str, dict[str, Any]]] = []
    for frame in body.split("\n\n"):
        fields = dict(line.split(": ", 1) for line in frame.splitlines() if ": " in line)
        if "event" in fields:
            out.append((fields.get("id"), fields["event"], json.loads(fields["data"])))
    return out


def _entry(kind: str, data: dict[str, Any]) -> dict[str, str]:
    return {FIELD_TYPE: kind, FIELD_DATA: json.dumps(data, ensure_ascii=False)}


# ═════════════════ POST …/messages đẩy `title` cho câu ĐẦU ═════════════════


async def test_first_question_enqueues_title_after_generate(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_arq: FakeArq,
) -> None:
    """Job id `title:{id}`, payload = (hội thoại, câu hỏi) — không có chữ nào (C5)."""
    cid = await _conversation(session_factory, user_a)

    resp = await client.post(MESSAGES.format(cid), headers=_session(user_a), json={"content": "a"})

    assert resp.status_code == 202, resp.text
    uid = resp.json()["user_message_id"]
    assert fake_arq.pushed[1] == ("title", (str(cid), uid))
    assert fake_arq.names == ["generate", "title"]
    assert f"title:{cid}" in fake_arq.accepted_ids


async def test_second_question_does_NOT_enqueue_title(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_arq: FakeArq,
) -> None:
    """DoD 6 (nửa đầu) — một hội thoại một lượt đặt tên; cả nhánh gốc mới cũng không."""
    cid = await _conversation(session_factory, user_a)
    auth = _session(user_a)

    first = await client.post(MESSAGES.format(cid), headers=auth, json={"content": "a"})
    second = await client.post(MESSAGES.format(cid), headers=auth, json={"content": "b"})
    new_root = await client.post(
        MESSAGES.format(cid), headers=auth, json={"content": "c", "parent_id": None}
    )

    assert first.status_code == second.status_code == new_root.status_code == 202
    assert fake_arq.names == ["generate", "title", "generate", "generate"]
    assert fake_arq.rejected == [], "khong duoc thu day title lan hai roi nho arq chan"


async def test_conversation_with_title_does_NOT_enqueue_title(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_arq: FakeArq,
) -> None:
    """Người dùng đặt tên lúc tạo hội thoại ⇒ không có gì để đặt, không tốn xu nào."""
    cid = await _conversation(session_factory, user_a, title="Tên có sẵn")

    resp = await client.post(MESSAGES.format(cid), headers=_session(user_a), json={"content": "a"})

    assert resp.status_code == 202
    assert fake_arq.names == ["generate"]


async def test_duplicate_title_job_id_is_not_an_error(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_arq: FakeArq,
) -> None:
    """Hai câu đầu song song (double-click, hai khoá) cùng thấy "đầu tiên" — arq trả `None`.

    Stack thật mới chen được hai request vào đúng khe ấy (DoD 6, báo cáo); ở đây
    dựng lại đúng trạng thái arq thấy ở request thứ hai: `_job_id` đã có. Handler
    phải coi `None` là ca **đúng** — vẫn `202`, câu hỏi vẫn được trả lời.
    """
    cid = await _conversation(session_factory, user_a)
    fake_arq.accepted_ids.add(f"title:{cid}")

    resp = await client.post(MESSAGES.format(cid), headers=_session(user_a), json={"content": "a"})

    assert resp.status_code == 202, resp.text
    assert fake_arq.names == ["generate"]
    assert fake_arq.rejected == [f"title:{cid}"]


async def test_title_enqueue_failure_does_NOT_fail_the_question(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_arq: FakeArq,
) -> None:
    """Đẩy `title` SAU `commit`, hỏng thì chỉ log: câu hỏi đã vào hàng đợi là thật."""
    cid = await _conversation(session_factory, user_a)
    fake_arq.raise_for.add("title")

    resp = await client.post(MESSAGES.format(cid), headers=_session(user_a), json={"content": "a"})

    assert resp.status_code == 202, resp.text
    assert fake_arq.names == ["generate"]
    async with session_factory() as session:
        count = (
            await session.execute(
                select(func.count()).select_from(Message).where(Message.conversation_id == cid)
            )
        ).scalar_one()
        title = (
            await session.execute(select(Conversation.title).where(Conversation.id == cid))
        ).scalar_one()
    assert count == 2, "hai message da commit — khong bi rollback vi luot dat ten"
    assert title is None


async def test_rejected_first_question_opens_no_title_job(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    fake_arq: FakeArq,
    ratelimit_redis: Any,
) -> None:
    """Cạm bẫy ④ — không đường tạo hội thoại/đặt tên nào đi vòng qua cửa chặn.

    Câu đầu bị từ chối (ở đây: trần đồng thời §10.6) thì `title` cũng không
    ra đời — trần tự nhiên "một lượt mỗi hội thoại đã qua cửa" giữ nguyên.
    """
    cid = await _conversation(session_factory, user_a)
    ratelimit_redis.slot = [0, 3]  # [allowed, running] của script Lua trần đồng thời

    resp = await client.post(MESSAGES.format(cid), headers=_session(user_a), json={"content": "a"})

    assert resp.status_code == 429, resp.text
    assert fake_arq.pushed == []


# ═══════════════════ GET /conversations/{id}/title/stream ═══════════════════


class Pending:
    """`title_job_pending` giả: trả `answer`, ghi lại ai đã hỏi."""

    def __init__(self) -> None:
        self.answer = False
        self.calls: list[uuid.UUID] = []

    async def __call__(self, conversation_id: uuid.UUID) -> bool:
        self.calls.append(conversation_id)
        return self.answer


@pytest.fixture
def pending(monkeypatch: pytest.MonkeyPatch) -> Pending:
    fake = Pending()
    monkeypatch.setattr("app.api.v1.stream.title_job_pending", fake)
    return fake


def _redis(monkeypatch: pytest.MonkeyPatch, fake: TitleRedis) -> TitleRedis:
    monkeypatch.setattr("app.api.v1.stream.get_redis", lambda: fake)
    return fake


async def test_stream_replays_start_deltas_done_from_redis(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    pending: Pending,
) -> None:
    """Consumer §7.3 trên khoá `stream:title:{id}`: `id:` là Redis Stream ID, đóng ở `done`."""
    cid = await _conversation(session_factory, user_a)
    key = title_stream_key(cid)
    _redis(
        monkeypatch,
        TitleRedis(
            {
                key: [
                    ("1-0", _entry("start", {"message_id": "q", "model_id": "m"})),
                    ("2-0", _entry("delta", {"t": "Nấu "})),
                    ("3-0", _entry("delta", {"t": "phở"})),
                    ("4-0", _entry("done", {"title": "Nấu phở"})),
                ]
            }
        ),
    )

    resp = await client.get(TITLE_STREAM.format(cid), headers=_session(user_a))

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers["x-accel-buffering"] == "no", "lop thu hai cua C1"
    assert [(i, e) for i, e, _ in _events(resp.text)] == [
        ("1-0", "start"),
        ("2-0", "delta"),
        ("3-0", "delta"),
        ("4-0", "done"),
    ]
    assert _events(resp.text)[-1][2] == {"title": "Nấu phở"}


async def test_stream_resumes_after_last_event_id(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    pending: Pending,
) -> None:
    """`Last-Event-ID` — loại trừ, như C3: không lặp chữ đã có."""
    cid = await _conversation(session_factory, user_a)
    key = title_stream_key(cid)
    _redis(
        monkeypatch,
        TitleRedis(
            {
                key: [
                    ("1-0", _entry("start", {"message_id": "q", "model_id": "m"})),
                    ("2-0", _entry("delta", {"t": "Nấu "})),
                    ("3-0", _entry("done", {"title": "Nấu"})),
                ]
            }
        ),
    )

    resp = await client.get(
        TITLE_STREAM.format(cid), headers=_session(user_a) | {"Last-Event-ID": "2-0"}
    )

    assert [(i, e) for i, e, _ in _events(resp.text)] == [("3-0", "done")]


async def test_title_set_and_no_stream_rebuilds_done_from_postgres(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    pending: Pending,
) -> None:
    """Stream đã hết TTL (hoặc chưa từng có): Postgres là sự thật — `done` không mang `id:`."""
    cid = await _conversation(session_factory, user_a, title="Tiêu đề đã có")
    _redis(monkeypatch, TitleRedis())

    resp = await client.get(TITLE_STREAM.format(cid), headers=_session(user_a))

    assert _events(resp.text) == [(None, "done", {"title": "Tiêu đề đã có"})]
    assert pending.calls == [], "tieu de co roi thi khong can hoi hang doi"


async def test_null_title_no_stream_no_job_closes_with_error(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    pending: Pending,
) -> None:
    """Không tiêu đề, không stream, không job ⇒ `error` rồi đóng — KHÔNG treo bằng `: ping`."""
    cid = await _conversation(session_factory, user_a)
    fake = _redis(monkeypatch, TitleRedis())

    resp = await client.get(TITLE_STREAM.format(cid), headers=_session(user_a))

    assert _events(resp.text) == [
        (None, "error", {"code": "JOB_LOST", "message": "khong co luot dat ten nao dang chay"})
    ]
    assert pending.calls == [cid]
    assert fake.xread_calls == 0


async def test_null_title_with_pending_job_waits_for_worker(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    pending: Pending,
) -> None:
    """Job còn trong hàng đợi, chưa `XADD start` ⇒ chờ (`: ping`), rồi nhận đủ khi worker ghi."""
    cid = await _conversation(session_factory, user_a)
    pending.answer = True
    key = title_stream_key(cid)
    fake = _redis(
        monkeypatch,
        TitleRedis(
            later={
                key: [
                    ("5-0", _entry("start", {"message_id": "q", "model_id": "m"})),
                    ("6-0", _entry("delta", {"t": "Phở"})),
                    ("7-0", _entry("done", {"title": "Phở"})),
                ]
            }
        ),
    )

    resp = await client.get(TITLE_STREAM.format(cid), headers=_session(user_a))

    assert [e for _, e, _ in _events(resp.text)] == ["start", "delta", "done"]
    assert fake.xread_calls == 1


async def test_bad_cursor_is_400(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    pending: Pending,
) -> None:
    cid = await _conversation(session_factory, user_a)

    resp = await client.get(
        TITLE_STREAM.format(cid), headers=_session(user_a) | {"Last-Event-ID": "khong-phai-id"}
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "CURSOR_INVALID"


async def test_other_users_conversation_is_404_not_403(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    pending: Pending,
) -> None:
    """DoD 5 — IDOR: B đọc stream tiêu đề của A ⇒ `404`, và không chạm Redis lẫn hàng đợi."""
    cid = await _conversation(session_factory, user_a, title="Bí mật của A")
    fake = _redis(monkeypatch, TitleRedis())

    resp = await client.get(TITLE_STREAM.format(cid), headers=_session(user_b))

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"
    assert "Bí mật" not in resp.text
    assert pending.calls == []
    assert fake.xread_calls == 0
