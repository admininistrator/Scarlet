#!/usr/bin/env python3
"""Eval golden set §21.3 — `make eval MODEL=<id>`.

KH tham chiếu: §21.3, §9.6, §9.9 bước 5, §7.4–7.5, §13.5, §15.3, C9, C10, C11,
C41 · tasks.md T-9.1 (Q-P9-2, NQ-151).

Mỗi tệp `evals/cases/*.json` là một ca (dữ liệu — A3); phép kiểm ở
`evals/checks.py`. Runner đi đúng đường người dùng đi: user tạm + cookie mint
(lối `scripts/bench_ttft.py`), qua Nginx (`PUBLIC_BASE_URL`), mỗi ca một hội
thoại mới; đọc SSE, rồi đọc `messages` / `usage_events` / `artifacts` qua
`DEV_DATABASE_URL`.

- Ca cần capability mà model không khai (`needs`) ⇒ `skip` (§21.3 "nếu vision",
  "nếu có" — áp cả `tools`, C41).
- Kết quả `evals/results/{model}-{date}.json`; tệp đã có ⇒ **từ chối** trước khi
  tiêu đồng nào, trừ `--overwrite` (B-106).
- Trần tiền một lần chạy: `evals/config.json` — chạm trần ⇒ ca còn lại `aborted`.
- Mã thoát = số ca `fail` + `aborted` (một lần chạy dừng giữa chừng không xanh).
- `--case` chạy vài ca để gỡ lỗi / kiểm ngược: in kết quả, **không** ghi tệp.
- Model phải đang `enabled` — API trả `MODEL_UNKNOWN` cho model tắt.

Cuối lần chạy user tạm bị xoá mềm; hội thoại và `usage_events` giữ nguyên để
`SELECT sum(cost_usd)` của DoD đếm đủ.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

EVALS_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVALS_DIR.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(EVALS_DIR))

# `bench_ttft` nạp `.env` lúc import (trước `app.config.settings`) — dùng lại
# SSE reader, cookie mint, DSN của nó thay vì chép lần thứ ba.
import asyncpg  # noqa: E402
import httpx  # noqa: E402
from bench_ttft import SseReader, close_quietly, dev_database_url, session_cookie  # noqa: E402
from checks import CHECKS, Context, SseEvent, Turn  # noqa: E402

from app.config.catalog import ModelEntry, get_catalog  # noqa: E402
from app.config.settings import settings  # noqa: E402
from app.llm.context import token_budget  # noqa: E402
from app.llm.tokens import count_message  # noqa: E402

CASES_DIR = EVALS_DIR / "cases"
RESULTS_DIR = EVALS_DIR / "results"
CONFIG_FILE = EVALS_DIR / "config.json"
API = "/api/v1"

#: Chữ lấp lịch sử ca ⑩ — ASCII (Cạm bẫy ⑥: đo cắt, không đo tokenizer).
_FILLER_WORDS = ["river", "stone", "window", "garden", "paper", "light", "orange", "table"]
#: Từ mỗi message của lịch sử seed — một khối user + assistant ~1 000 token.
_FILLER_WORDS_PER_MESSAGE = 500


@dataclass(slots=True)
class CaseResult:
    id: str
    check: str
    status: str
    reasons: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    seconds: float = 0.0
    turns: list[dict[str, Any]] = field(default_factory=list)


class EvalError(Exception):
    """Một lượt không chạy hết được (HTTP, treo) — ca `fail` kèm lý do (Cạm bẫy ①)."""


# ═════════════════════════════════ một lượt ═════════════════════════════════


class Session:
    def __init__(
        self, http: httpx.AsyncClient, pool: asyncpg.Pool, model: ModelEntry, timeout_s: float
    ) -> None:
        self.http = http
        self.pool = pool
        self.model = model
        self.timeout_s = timeout_s

    async def conversation(self, title: str) -> uuid.UUID:
        res = await self.http.post(f"{API}/conversations", json={"title": title})
        res.raise_for_status()
        return uuid.UUID(res.json()["id"])

    async def upload(self, name: str) -> str:
        path = CASES_DIR / name
        files = {"file": (path.name, path.read_bytes(), "image/png")}
        res = await self.http.post(f"{API}/attachments", files=files)
        if res.status_code != 201:
            raise EvalError(f"upload {name}: {res.status_code} {res.text[:200]}")
        return str(res.json()["id"])

    async def turn(self, conv: uuid.UUID, spec: dict[str, Any]) -> Turn:
        body: dict[str, Any] = {"content": spec["content"], "model_id": self.model.id}
        if spec.get("parent") == "root":
            body["parent_id"] = None
        if spec.get("web_tools"):
            body["web_tools"] = True
        if spec.get("attachment"):
            body["attachment_ids"] = [await self.upload(spec["attachment"])]
        res = await self.http.post(
            f"{API}/conversations/{conv}/messages",
            json=body,
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        if res.status_code != 202:
            raise EvalError(f"POST messages: {res.status_code} {res.text[:300]}")
        created = res.json()
        amid = uuid.UUID(created["assistant_message_id"])
        events = await self._read(
            created["stream_url"], amid, cancel=bool(spec.get("cancel_after_first_delta"))
        )
        return await self._row(amid, events)

    async def _read(self, stream_url: str, amid: uuid.UUID, *, cancel: bool) -> list[SseEvent]:
        """SSE tới `done` / `error`. Trần `GENERATE_TIMEOUT_S × hệ số` (B-103, B-250)."""
        reader = SseReader()
        events: list[SseEvent] = []
        deadline = time.monotonic() + self.timeout_s
        async with self.http.stream("GET", stream_url) as res:
            if res.status_code != 200:
                raise EvalError(f"GET stream: {res.status_code}")
            chunks = res.aiter_text()
            try:
                async for chunk in chunks:
                    if time.monotonic() > deadline:
                        raise EvalError(f"quá {self.timeout_s:.0f}s chưa có `done`")
                    for ev in reader.feed(chunk):
                        events.append(SseEvent(ev.event, ev.data))
                        if cancel and ev.event == "delta":
                            cancel = False
                            await self.http.post(f"{API}/messages/{amid}/cancel")
                        if ev.event in ("done", "error"):
                            return events
            finally:
                await close_quietly(chunks)
        raise EvalError("stream đóng khi chưa có `done` / `error`")

    async def _row(self, amid: uuid.UUID, events: list[SseEvent]) -> Turn:
        """Postgres ghi TRƯỚC `XADD done` (§7.2) ⇒ sau `done` hàng đã đủ."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT status::text, content, reasoning, finish_reason, error_code, "
                "prompt_tokens, completion_tokens, tool_rounds::text FROM messages WHERE id = $1",
                amid,
            )
            usage_rows = await conn.fetchval(
                "SELECT count(*) FROM usage_events WHERE message_id = $1", amid
            )
            languages = await conn.fetch(
                "SELECT language FROM artifacts WHERE message_id = $1", amid
            )
        assert row is not None
        return Turn(
            events=events,
            status=row["status"],
            content=row["content"],
            reasoning=row["reasoning"],
            finish_reason=row["finish_reason"],
            error_code=row["error_code"],
            prompt_tokens=row["prompt_tokens"],
            completion_tokens=row["completion_tokens"],
            usage_rows=int(usage_rows or 0),
            tool_rounds=json.loads(row["tool_rounds"]) if row["tool_rounds"] else None,
            artifact_languages=[r["language"] for r in languages],
        )

    async def seed_history(self, conv: uuid.UUID, target_tokens: int) -> int:
        """Ca ⑩ — lịch sử user/assistant chèn TỪNG DÒNG (Cạm bẫy ⑤), tới ≥ `target_tokens`.

        Đếm bằng `count_message` — đúng thước §9.6 dùng để cắt. Trả tổng token.
        """
        rng = random.Random(target_tokens)
        total = 0
        parent: uuid.UUID | None = None
        async with self.pool.acquire() as conn:
            while total < target_tokens:
                for role in ("user", "assistant"):
                    text = " ".join(rng.choices(_FILLER_WORDS, k=_FILLER_WORDS_PER_MESSAGE))
                    total += count_message({"role": role, "content": text}, model_id=self.model.id)
                    parent = await conn.fetchval(
                        "INSERT INTO messages (conversation_id, parent_id, role, status, content, "
                        "model_id) VALUES ($1, $2, $3::message_role, 'completed', $4, $5) "
                        "RETURNING id",
                        conv,
                        parent,
                        role,
                        text,
                        self.model.id if role == "assistant" else None,
                    )
            await conn.execute(
                "UPDATE conversations SET active_leaf_id = $2 WHERE id = $1", conv, parent
            )
        return total

    async def spent(self, user_id: uuid.UUID) -> Decimal:
        async with self.pool.acquire() as conn:
            value = await conn.fetchval(
                "SELECT coalesce(sum(cost_usd), 0) FROM usage_events WHERE user_id = $1", user_id
            )
        return Decimal(value)


# ══════════════════════════════════ một ca ══════════════════════════════════


def _turn_summary(turn: Turn) -> dict[str, Any]:
    return {
        "status": turn.status,
        "finish_reason": turn.finish_reason,
        "error_code": turn.error_code,
        "prompt_tokens": turn.prompt_tokens,
        "completion_tokens": turn.completion_tokens,
        "content_chars": len(turn.content),
        "events": len(turn.events),
    }


async def run_case(session: Session, case: dict[str, Any]) -> CaseResult:
    result = CaseResult(id=case["id"], check=case["check"], status="fail")
    model = session.model
    ctx = Context(
        thresholds=case.get("thresholds", {}),
        context_window=model.context_window,
        budget=token_budget(model),
    )
    try:
        conv = await session.conversation(f"eval {case['id']}")
        if ratio := case.get("seed_history_ratio"):
            seeded = await session.seed_history(conv, int(ratio * ctx.budget))
            ctx = Context(ctx.thresholds, ctx.context_window, ctx.budget, history_tokens=seeded)
        turns = [await session.turn(conv, spec) for spec in case["turns"]]
    except (EvalError, httpx.HTTPError) as exc:
        result.reasons = [f"{type(exc).__name__}: {exc}"]
        return result
    result.turns = [_turn_summary(t) for t in turns]
    if ctx.history_tokens:
        result.turns[0]["history_tokens"] = ctx.history_tokens
        result.turns[0]["budget"] = ctx.budget
    result.reasons = CHECKS[case["check"]](turns, ctx)
    result.status = "fail" if result.reasons else "pass"
    return result


# ══════════════════════════════════ chạy ═══════════════════════════════════


def load_cases(only: list[str]) -> list[dict[str, Any]]:
    cases = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(CASES_DIR.glob("*.json"))]
    for case in cases:
        if case["check"] not in CHECKS:
            raise SystemExit(f"{case['id']}: check {case['check']!r} không có trong checks.py")
    if only:
        cases = [c for c in cases if c["id"] in only or c["id"].split("-", 1)[0] in only]
        if not cases:
            raise SystemExit(f"--case {only}: không ca nào khớp")
    return cases


async def create_user(pool: asyncpg.Pool, tier: str) -> uuid.UUID:
    async with pool.acquire() as conn:
        user_id = await conn.fetchval(
            "INSERT INTO users (email, password_hash, status, tier_name) "
            "VALUES ($1, 'not-a-real-hash', 'active', $2) RETURNING id",
            f"eval-{uuid.uuid4().hex[:8]}@scarlet.test",
            tier,
        )
    assert isinstance(user_id, uuid.UUID)
    return user_id


def write_results(path: Path, payload: dict[str, Any], *, overwrite: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # "x" — tệp xuất hiện giữa lúc chạy cũng không bị đè (B-106).
    with path.open("w" if overwrite else "x", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


async def run(args: argparse.Namespace) -> int:
    model = next((m for m in get_catalog().models if m.id == args.model), None)
    if model is None:
        raise SystemExit(f"model {args.model!r} không có trong catalog")
    if not model.enabled:
        raise SystemExit(f"model {args.model!r} đang tắt — API trả MODEL_UNKNOWN, eval không chạy")
    path = RESULTS_DIR / f"{model.id}-{date.today().isoformat()}.json"
    if not args.case and path.exists() and not args.overwrite:
        print(f"TỪ CHỐI: {path.relative_to(REPO_ROOT)} đã có — `--overwrite` để đè (B-106)")
        return 2
    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    cap = Decimal(str(config["max_cost_usd_per_run"]))
    cases = load_cases(args.case)

    pool = await asyncpg.create_pool(dev_database_url(), min_size=1, max_size=2)
    assert pool is not None
    user_id = await create_user(pool, config["tier"])
    started_at = datetime.now(UTC)
    t0 = time.monotonic()
    results: list[CaseResult] = []
    print(f"eval {model.id} · {len(cases)} ca · trần {cap} USD · user {user_id}", flush=True)
    try:
        async with httpx.AsyncClient(
            base_url=settings.PUBLIC_BASE_URL,
            verify=False,  # CA mkcert nằm ở Windows (lối bench_ttft / test_resume)
            timeout=httpx.Timeout(60.0, read=float(settings.GENERATE_TIMEOUT_S)),
        ) as http:
            session = Session(
                http, pool, model, settings.GENERATE_TIMEOUT_S * float(config["timeout_factor"])
            )
            for case in cases:
                # Access token sống ACCESS_TOKEN_TTL_MIN — ký lại mỗi ca (lối bench_ttft).
                http.headers.update(session_cookie(user_id, config["tier"]))
                missing = sorted(set(case.get("needs", [])) - set(model.capabilities))
                before = await session.spent(user_id)
                if missing:
                    result = CaseResult(
                        case["id"], case["check"], "skip", [f"model không khai {missing}"]
                    )
                elif before >= cap:
                    result = CaseResult(
                        case["id"], case["check"], "aborted", [f"đã tiêu {before} ≥ trần {cap}"]
                    )
                else:
                    t_case = time.monotonic()
                    result = await run_case(session, case)
                    result.seconds = round(time.monotonic() - t_case, 1)
                    result.cost_usd = float(await session.spent(user_id) - before)
                results.append(result)
                why = f" — {'; '.join(result.reasons)}" if result.status != "pass" else ""
                print(
                    f"  {result.status:<7} {case['id']:<18} {result.seconds:>6.1f}s"
                    f"  {result.cost_usd:.6f} USD{why}",
                    flush=True,
                )
        spent = await session.spent(user_id)
    finally:
        async with pool.acquire() as conn:
            await conn.execute("UPDATE users SET deleted_at = now() WHERE id = $1", user_id)
        await pool.close()

    counts = {k: sum(r.status == k for r in results) for k in ("pass", "skip", "fail", "aborted")}
    elapsed = time.monotonic() - t0
    line = (
        f"{model.id}: pass {counts['pass']} / skip {counts['skip']} / fail {counts['fail']}"
        f" / aborted {counts['aborted']} · {elapsed:.0f}s · {spent} USD"
    )
    if args.case:
        print(f"{line} · --case: không ghi tệp")
    else:
        payload = {
            "model": model.id,
            "date": date.today().isoformat(),
            "started_at": started_at.isoformat(timespec="seconds"),
            "seconds": round(elapsed, 1),
            "base_url": settings.PUBLIC_BASE_URL,
            "capabilities": list(model.capabilities),
            "cost_cap_usd": float(cap),
            "cost_usd": float(spent),
            "summary": counts,
            "cases": [asdict(r) for r in results],
        }
        write_results(path, payload, overwrite=args.overwrite)
        print(f"{line} · {path.relative_to(REPO_ROOT)}")
    return counts["fail"] + counts["aborted"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="id model trong config/model_catalog.json")
    parser.add_argument("--overwrite", action="store_true", help="đè tệp kết quả cùng ngày")
    parser.add_argument(
        "--case", action="append", default=[], help="chỉ chạy ca này (id hoặc số, lặp lại được)"
    )
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
