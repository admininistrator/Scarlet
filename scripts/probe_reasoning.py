#!/usr/bin/env python3
"""T-S.2 — mỗi mức suy luận có thật sự tới được model không.

KH tham chiếu: §24.2b·S3b, §9.1, §9.5, Phụ lục E · NQ-118 · tasks.md T-S.2.

    source scripts/llm_env.sh
    backend/.venv/bin/python scripts/probe_reasoning.py --dry-run
    backend/.venv/bin/python scripts/probe_reasoning.py --ledger-user-id <uuid> [--model ID]…
    backend/.venv/bin/python scripts/probe_reasoning.py --report      # chỉ in lại bảng

Kế hoạch đo (model × mức × đường, tham số từng mức, câu hỏi cố định, ngân sách)
là **dữ liệu** ở `scripts/probe_reasoning.json` — tên model và tham số provider
không được nằm trong `.py` (A3). Kết quả cộng dồn vào một file JSON ở
`evals/results/`, nên chạy từng model một (`--model`) vẫn ra một bảng.

┌──────────────────────────────────────────────────────────────────────────┐
│  SÁU QUYẾT ĐỊNH CỦA PHÉP ĐO                                              │
└──────────────────────────────────────────────────────────────────────────┘

**1. Bằng chứng là token, không phải `200`.** `drop_params: true` (Phụ lục E)
bỏ im lặng tham số provider không nhận: một mức sai vẫn `200 OK`. Mỗi lượt vì
vậy ghi `reasoning_tokens` (khi provider báo), `completion_tokens` (luôn có, và
gồm cả phần suy luận ở mọi provider đã tra — §24.2b·S4), độ dài chữ suy luận và
mã HTTP. Hai mức kề nhau trên cùng một thang chỉ "khác rõ" khi **mọi** lượt của
mức trên vượt **mọi** lượt của mức dưới theo ngưỡng `distinct` của kế hoạch.

**2. Đi đúng đường của app, không dựng client thứ hai.** Đường system là
`SystemAdapter`, đường BYOK là `ByokAdapter.for_provider()` — cùng thân
`openai_compat.py`, cùng parser — và `params` đi vào `extra`, đúng chỗ khối
`reasoning` của catalog v4 sẽ đi. "Độ dài chữ suy luận" vì thế là đúng số chữ
khối "Suy luận" của app sẽ nhận. Script chỉ **nghe lén** dòng thô (bọc
`openai_compat.parse_stream` bằng một bản tee) để ghi thêm các khoá của
`delta` có mặt: provider gửi suy luận dưới một khoá parser không đọc thì bảng
phải nói ra được, chứ không in "0 ký tự" rồi để người đọc kết luận sai.

**3. Đường BYOK dùng khoá hệ thống trong `.env.providers`.** Thứ được đo là
**đường đi** (gọi thẳng `provider.base_url`, lớp tương thích OpenAI của chính
provider), không phải chủ khoá. Tên biến lấy từ `api_key: os.environ/…` của
alias trong `config/litellm.config.yaml`; giá trị không bao giờ được in.

**4. Vòng tròn, như `bench_ttft.py`.** Lượt 1 chạy mọi ô rồi mới tới lượt 2:
một phút provider đổi tải không rơi trọn vào một ô rồi đội lốt "mức này khác".

**5. Tiền: chặn trước, ghi sổ ngay sau.** Trước mỗi lượt, tiền đã tiêu (cả các
lần chạy trước trong cùng file kết quả) cộng chi phí **xấu nhất** của lượt tới
(`max_tokens` toàn bộ là output, giá đang áp dụng) mà vượt `budget_usd` thì
lượt đó không được gửi (`skipped-budget`). Tiền mỗi lượt tính bằng chính
`meter.measure` / `cost_of` / `snapshot_of` của app rồi ghi thành một dòng
`usage_events`: `message_id` NULL (probe không tạo message), `key_source` =
`system` (khoá hệ thống trả tiền trên cả hai đường). Nhờ vậy câu SQL của DoD
đếm được chính thí nghiệm này và bảng Chi phí của admin khớp hoá đơn provider.
ZSET quota **không** bị chạm — "sổ có, ZSET thiếu" là chiều lành mà
`rebuild_quota` vá được (xem docstring `meter.record_usage`).

**6. Câu hỏi là một phần của ô đo (T-S.6).** Câu cố định `prompt` của kế
hoạch là câu dễ: đủ tách `off`/`low`/`high`, nhưng một mức "nghĩ kỹ hơn" như
`max` chỉ khác `high` trên một câu buộc model phải kiểm lại. Một ô có thể mang
`"prompt": "<tên>"` trỏ vào `prompts` của kế hoạch; tên ấy vào `variant`, nên
hai ô cùng mức khác câu không bao giờ bị so lẫn nhau.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import openai
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.config.catalog import Catalog, ModelEntry, get_catalog  # noqa: E402
from app.config.settings import settings  # noqa: E402
from app.db.models.usage_event import KeySource  # noqa: E402
from app.llm.adapters import openai_compat  # noqa: E402
from app.llm.adapters.byok import ByokAdapter  # noqa: E402
from app.llm.adapters.openai_compat import OpenAICompatAdapter  # noqa: E402
from app.llm.adapters.system import SystemAdapter  # noqa: E402
from app.llm.client import Usage  # noqa: E402
from app.llm.parser import RawChunk  # noqa: E402
from app.llm.tokens import count_messages  # noqa: E402
from app.quota import meter  # noqa: E402

PLAN_PATH = REPO / "scripts" / "probe_reasoning.json"
LITELLM_CONFIG = REPO / "config" / "litellm.config.yaml"
PROVIDER_ENV = REPO / ".env.providers"
COMPOSE_FILE = REPO / "docker-compose.yml"
RESULTS_DIR = REPO / "evals" / "results"

PATH_SYSTEM = "system"
PATH_BYOK = "byok"
#: Nhãn của ô đối chứng — không gửi tham số suy luận nào.
BASELINE = "default"
#: Cắt thông điệp lỗi: đủ đọc lý do, không đủ để chép cả body request vào file.
ERROR_CHARS = 300
#: Tiền tố tham chiếu biến môi trường của LiteLLM (`api_key: os.environ/NAME`).
ENV_REF_PREFIX = "os.environ/"
#: Nhãn phân cách chuỗi JSON trong câu SQL ghi sổ (dollar-quoting của Postgres).
SQL_TAG = "$probe$"


# ─────────────────────────────── kế hoạch ────────────────────────────────


@dataclass(frozen=True, slots=True)
class Case:
    """Một cách gửi một mức cho một model trên một đường."""

    model_id: str
    path: str
    level: str
    params: dict[str, Any]
    runs: int
    max_tokens: int
    ladder: str | None = None
    alias: str | None = None
    temperature: float | None = None
    #: Tên một câu trong `prompts` của kế hoạch; `None` = câu cố định `prompt`.
    prompt: str | None = None

    @property
    def variant(self) -> str:
        """Nhãn phân biệt hai cách gửi cùng một mức (câu hỏi, alias, tham số, temperature)."""
        parts: list[str] = []
        if self.prompt:
            parts.append(f"prompt={self.prompt}")
        if self.alias:
            parts.append(f"alias={self.alias}")
        if self.params:
            parts.append(json.dumps(self.params, separators=(",", ":"), sort_keys=True))
        if self.temperature is not None:
            parts.append(f"temperature={self.temperature}")
        return " ".join(parts) or "{}"

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.model_id, self.path, self.level, self.variant)


def load_plan(path: Path) -> dict[str, Any]:
    plan: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return plan


def build_cases(plan: dict[str, Any], catalog: Catalog, only: set[str]) -> list[Case]:
    """Trải kế hoạch thành danh sách ô. Sai kế hoạch thì dừng TRƯỚC khi tiêu đồng nào."""
    known = {m.id for m in catalog.models}
    planned = {entry["id"] for entry in plan["models"]}
    unknown = sorted((planned | only) - known)
    if unknown:
        raise SystemExit(f"model không có trong catalog: {unknown}")
    missing = sorted(only - planned)
    if missing:
        raise SystemExit(f"model chưa có trong kế hoạch {PLAN_PATH.name}: {missing}")

    levels = set(plan["levels"])
    prompts = plan.get("prompts", {})
    negative = plan["negative"]
    cases: list[Case] = []
    for entry in plan["models"]:
        model_id = entry["id"]
        if only and model_id not in only:
            continue
        for raw in entry["cases"]:
            level = raw["level"]
            if level != BASELINE and level not in levels:
                raise SystemExit(f"{model_id}: mức '{level}' ngoài bộ từ vựng {plan['levels']}")
            for path in raw.get("paths", entry["paths"]):
                if path not in (PATH_SYSTEM, PATH_BYOK):
                    raise SystemExit(f"{model_id}: đường '{path}' không tồn tại")
                if raw.get("alias") and path != PATH_SYSTEM:
                    raise SystemExit(f"{model_id}: alias chỉ có nghĩa trên đường system")
                if raw.get("prompt") and raw["prompt"] not in prompts:
                    raise SystemExit(
                        f"{model_id}: câu hỏi '{raw['prompt']}' không có trong prompts"
                    )
                cases.append(
                    Case(
                        model_id=model_id,
                        path=path,
                        level=level,
                        params=raw["params"],
                        runs=raw.get("runs", plan["runs"]),
                        max_tokens=raw.get("max_tokens", entry["max_tokens"]),
                        ladder=raw.get("ladder"),
                        alias=raw.get("alias"),
                        temperature=raw.get("temperature"),
                        prompt=raw.get("prompt"),
                    )
                )
        if PATH_SYSTEM in entry["paths"]:
            cases.append(
                Case(
                    model_id=model_id,
                    path=PATH_SYSTEM,
                    level=negative["level"],
                    params=negative["params"],
                    runs=negative["runs"],
                    max_tokens=entry["max_tokens"],
                )
            )

    seen: set[tuple[str, str, str, str]] = set()
    for case in cases:
        if case.key in seen:
            raise SystemExit(f"ô trùng trong kế hoạch: {case.key}")
        seen.add(case.key)
    return cases


# ─────────────────────────────── đường gọi ───────────────────────────────


def provider_key_env(model_id: str) -> str:
    """Tên biến chứa khoá provider của một alias — đọc từ chính cấu hình LiteLLM."""
    config = yaml.safe_load(LITELLM_CONFIG.read_text(encoding="utf-8"))
    for item in config["model_list"]:
        if item["model_name"] == model_id:
            ref = str(item["litellm_params"].get("api_key", ""))
            if not ref.startswith(ENV_REF_PREFIX):
                raise SystemExit(
                    f"{model_id}: api_key trong litellm.config.yaml không dạng {ENV_REF_PREFIX}NAME"
                )
            return ref.removeprefix(ENV_REF_PREFIX)
    raise SystemExit(f"{model_id}: không có alias này trong {LITELLM_CONFIG.name}")


def read_env_value(path: Path, name: str) -> str:
    """Một giá trị của file `.env`-dạng. Thiếu thì dừng và nói đúng tên biến (A4)."""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() != name:
            continue
        value = value.split(" #", 1)[0].strip().strip("'\"")
        if value:
            return value
    raise SystemExit(f"{path.name} thiếu biến {name} — đường BYOK cần nó")


class Adapters:
    """Một `SystemAdapter` dùng chung, một `ByokAdapter` cho mỗi provider."""

    def __init__(self, catalog: Catalog) -> None:
        self._catalog = catalog
        self._system: SystemAdapter | None = None
        self._byok: dict[str, ByokAdapter] = {}

    def get(self, case: Case, model: ModelEntry) -> OpenAICompatAdapter:
        if case.path == PATH_SYSTEM:
            if self._system is None:
                self._system = SystemAdapter.from_settings()
            return self._system
        if model.provider not in self._byok:
            provider = self._catalog.providers[model.provider]
            if not provider.byok_supported:
                raise SystemExit(f"{model.id}: provider '{model.provider}' không byok_supported")
            key = read_env_value(PROVIDER_ENV, provider_key_env(model.id))
            self._byok[model.provider] = ByokAdapter.for_provider(provider, api_key=key)
        return self._byok[model.provider]

    async def close(self) -> None:
        for adapter in [self._system, *self._byok.values()]:
            if adapter is not None:
                await adapter.close()


# ───────────────────────── nghe lén dòng thô (quyết định 2) ─────────────────────────


@dataclass(slots=True)
class WireObserver:
    delta_keys: set[str] = field(default_factory=set)
    models: set[str] = field(default_factory=set)
    usage: dict[str, Any] | None = None


#: Lượt đang chạy. Các lượt chạy tuần tự nên một biến là đủ.
_active_observer: WireObserver | None = None
_real_parse_stream = openai_compat.parse_stream


def _observe(raw: RawChunk) -> None:
    observer = _active_observer
    if observer is None:
        return
    model = raw.get("model")
    if isinstance(model, str) and model:
        observer.models.add(model)
    for choice in raw.get("choices") or ():
        delta = choice.get("delta") if isinstance(choice, Mapping) else None
        if isinstance(delta, Mapping):
            observer.delta_keys.update(k for k, v in delta.items() if v not in (None, "", [], {}))
    usage = raw.get("usage")
    if isinstance(usage, Mapping) and usage:
        observer.usage = dict(usage)


async def _tee(raw_stream: AsyncIterator[RawChunk]) -> AsyncIterator[RawChunk]:
    try:
        async for raw in raw_stream:
            _observe(raw)
            yield raw
    finally:
        aclose = getattr(raw_stream, "aclose", None)
        if aclose is not None:
            await aclose()


def _observing_parse_stream(raw_stream: AsyncIterator[RawChunk]) -> Any:
    return _real_parse_stream(_tee(raw_stream))


openai_compat.parse_stream = _observing_parse_stream


# ───────────────────────────────── một lượt ─────────────────────────────────


def _short(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:ERROR_CHARS]


def _messages(prompt: str) -> list[dict[str, Any]]:
    return [{"role": "user", "content": prompt}]


def question_of(plan: dict[str, Any], case: Case) -> tuple[str, str]:
    """(câu hỏi, đáp án) của một ô — câu cố định, hoặc câu riêng nó trỏ tới."""
    if case.prompt is None:
        return plan["prompt"], plan["expected_answer"]
    named = plan["prompts"][case.prompt]
    return named["text"], named["expected_answer"]


def worst_case_usd(catalog: Catalog, model: ModelEntry, case: Case, prompt: str) -> Decimal:
    """Chi phí nếu lượt tới tiêu trọn `max_tokens` — cận trên cho phép chặn ngân sách.

    `max_tokens` bao cả token suy luận ở mọi provider đã tra (§24.2b·S4), nên
    đây là cận trên thật. Phần prompt đếm bằng `tiktoken` của app (xấp xỉ vài
    phần trăm với model non-OpenAI — trên ~60 token, sai số dưới 1e-5 USD).
    """
    rates = catalog.effective_pricing(model.id, datetime.now(UTC))
    prompt_tokens = count_messages(_messages(prompt), model_id=model.id)
    spent = meter.Spent(
        prompt_tokens=prompt_tokens + catalog.prompt_overhead_tokens(model.id),
        completion_tokens=case.max_tokens,
        cached_tokens=0,
        measured=False,
    )
    return meter.cost_of(rates, spent)


async def run_call(
    adapters: Adapters,
    catalog: Catalog,
    case: Case,
    run: int,
    prompt: str,
    expected: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Gửi một lượt. Trả (bản ghi kết quả, dòng sổ hoặc None nếu không tiêu token)."""
    global _active_observer
    model = next(m for m in catalog.models if m.id == case.model_id)
    adapter = adapters.get(case, model)
    wire_model = case.alias or (model.id if case.path == PATH_SYSTEM else model.provider_model)
    temperature = case.temperature if case.temperature is not None else settings.LLM_TEMPERATURE
    messages = _messages(prompt)

    observer = WireObserver()
    content: list[str] = []
    reasoning: list[str] = []
    usage: Usage | None = None
    finish: str | None = None
    status: int | None = None
    error: str | None = None
    at = datetime.now(UTC)
    started = time.monotonic()
    _active_observer = observer
    try:
        stream = await adapter.stream(
            model=wire_model,
            messages=messages,
            tools=None,
            max_tokens=case.max_tokens,
            temperature=temperature,
            extra=dict(case.params),
        )
        # `await` đã nhận header 2xx — lỗi giữa dòng vẫn giữ mã này, ghi vào `error`.
        status = 200
        async for chunk in stream:
            if chunk.kind == "delta":
                content.append(chunk.text or "")
            elif chunk.kind == "reasoning":
                reasoning.append(chunk.text or "")
            elif chunk.kind == "done":
                usage = chunk.usage
                finish = chunk.finish_reason
    except openai.APIStatusError as exc:
        status = exc.status_code
        error = _short(exc)
    except (openai.APIError, httpx.HTTPError, OSError, TimeoutError) as exc:
        error = _short(exc)
    finally:
        _active_observer = None
    elapsed = time.monotonic() - started

    text = "".join(content)
    thought = "".join(reasoning)
    record: dict[str, Any] = {
        "model": case.model_id,
        "path": case.path,
        "level": case.level,
        "variant": case.variant,
        "ladder": case.ladder,
        "alias": case.alias,
        "params": case.params,
        "temperature": temperature,
        "max_tokens": case.max_tokens,
        "run": run,
        "at": at.isoformat(),
        "elapsed_s": round(elapsed, 2),
        "status": status,
        "error": error,
        "prompt_tokens": usage.prompt_tokens if usage else None,
        "completion_tokens": usage.completion_tokens if usage else None,
        "reasoning_tokens": usage.reasoning_tokens if usage else None,
        "reasoning_chars": len(thought),
        "content_chars": len(text),
        "answer": text.strip()[:80],
        "answer_ok": expected in text,
        "finish_reason": finish,
        "delta_keys": sorted(observer.delta_keys),
        "models_seen": sorted(observer.models),
        "usage_raw": observer.usage,
        "cost_usd": None,
        "cost_confidence": None,
    }

    if status != 200 or not (usage or text or thought):
        return record, None

    rates = catalog.effective_pricing(model.id, at)
    spent = meter.measure(
        model, usage=usage, sent=messages, content=text, reasoning=thought, tool_calls=None
    )
    cost = meter.cost_of(rates, spent)
    confidence = meter.confidence_of(model, spent)
    record["cost_usd"] = str(cost)
    record["cost_confidence"] = confidence.value
    row = {
        "model_id": model.id,
        "provider": model.provider,
        "key_source": KeySource.SYSTEM.value,
        "prompt_tokens": spent.prompt_tokens,
        "completion_tokens": spent.completion_tokens,
        "cached_tokens": spent.cached_tokens,
        "cost_usd": str(cost),
        "cost_confidence": confidence.value,
        "price_snapshot": meter.snapshot_of(model, rates, at),
        "created_at": at.isoformat(),
    }
    return record, row


# ─────────────────────────────── sổ usage_events ───────────────────────────────


def psql(sql: str) -> str:
    """Chạy SQL trong container `postgres` — Postgres không publish cổng ra host."""
    result = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "postgres",
            "sh",
            "-c",
            'psql -X -q -t -A -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"',
        ],
        input=sql,
        text=True,
        capture_output=True,
        cwd=REPO,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"psql lỗi: {result.stderr.strip()[:ERROR_CHARS]}")
    return result.stdout.strip()


def check_ledger_user(user_id: uuid.UUID) -> None:
    found = psql(f"SELECT count(*) FROM users WHERE id = '{user_id}' AND deleted_at IS NULL;")
    if found != "1":
        raise SystemExit(f"--ledger-user-id {user_id}: không có user đang tồn tại với id này")


def write_ledger(user_id: uuid.UUID, row: dict[str, Any]) -> None:
    """Một dòng `usage_events` cho một lượt đã tiêu token — xem quyết định 5."""
    payload = json.dumps(row, ensure_ascii=False, default=str)
    if SQL_TAG in payload:
        raise RuntimeError("dữ liệu sổ chứa nhãn phân cách SQL")
    psql(
        "INSERT INTO usage_events (user_id, message_id, model_id, provider, key_source,"
        " prompt_tokens, completion_tokens, cached_tokens, cost_usd, cost_confidence,"
        " price_snapshot, upstream_model_reported, created_at)"
        f" SELECT '{user_id}'::uuid, NULL, r.model_id, r.provider, r.key_source,"
        " r.prompt_tokens, r.completion_tokens, r.cached_tokens, r.cost_usd, r.cost_confidence,"
        " r.price_snapshot, NULL, r.created_at"
        f" FROM jsonb_to_record({SQL_TAG}{payload}{SQL_TAG}::jsonb) AS r(model_id text,"
        " provider text, key_source text, prompt_tokens int, completion_tokens int,"
        " cached_tokens int, cost_usd numeric, cost_confidence text, price_snapshot jsonb,"
        " created_at timestamptz);"
    )


# ─────────────────────────────── file kết quả ───────────────────────────────


def load_results(path: Path) -> dict[str, Any]:
    if path.exists():
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data
    return {"plan": str(PLAN_PATH.relative_to(REPO)), "sessions": [], "calls": []}


def save_results(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8"
    )
    os.replace(tmp, path)


def spent_usd(calls: list[dict[str, Any]]) -> Decimal:
    return sum((Decimal(c["cost_usd"]) for c in calls if c.get("cost_usd")), Decimal(0))


def litellm_image() -> str:
    compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    return str(compose["services"]["litellm"]["image"])


# ─────────────────────────────────── bảng ───────────────────────────────────


def _metric(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> str:
    """So bằng `reasoning_tokens` khi cả hai ô đều báo; không thì bằng `completion_tokens`."""
    both = a + b
    if both and all(c["reasoning_tokens"] is not None for c in both):
        return "reasoning_tokens"
    return "completion_tokens"


def _values(calls: list[dict[str, Any]], metric: str) -> list[int] | None:
    values = [c[metric] for c in calls]
    if not calls or any(v is None for v in values):
        return None
    return values


def distinct(lower: list[int], upper: list[int], rule: dict[str, Any]) -> bool:
    top, bottom = max(lower), min(upper)
    if bottom - top < rule["min_delta_tokens"]:
        return False
    return top == 0 or bottom / top >= rule["min_ratio"]


def _fmt(values: list[Any]) -> str:
    return " / ".join("—" if v is None else str(v) for v in values)


def report(data: dict[str, Any], plan: dict[str, Any]) -> None:
    calls = [c for c in data["calls"] if c["status"] != "skipped-budget"]
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for call in calls:
        groups[(call["model"], call["path"], call["level"], call["variant"])].append(call)

    order = {m["id"]: i for i, m in enumerate(plan["models"])}
    levels = [BASELINE, *plan["levels"], plan["negative"]["level"]]

    def sort_key(k: tuple[str, str, str, str]) -> tuple[int, str, int, str]:
        rank = levels.index(k[2]) if k[2] in levels else len(levels)
        return (order.get(k[0], len(order)), k[1], rank, k[3])

    print(
        "\n| model | đường | mức | cách gửi | HTTP | reasoning_tokens | completion_tokens "
        "| chữ suy luận | finish | đúng? |"
    )
    print("|---|---|---|---|---|---|---|---|---|---|")
    for key in sorted(groups, key=sort_key):
        runs = sorted(groups[key], key=lambda c: c["run"])
        print(
            f"| {key[0]} | {key[1]} | {key[2]} | `{key[3]}` | {_fmt([c['status'] for c in runs])} "
            f"| {_fmt([c['reasoning_tokens'] for c in runs])} "
            f"| {_fmt([c['completion_tokens'] for c in runs])} "
            f"| {_fmt([c['reasoning_chars'] for c in runs])} "
            f"| {_fmt([c['finish_reason'] for c in runs])} "
            f"| {_fmt(['✓' if c['answer_ok'] else '✗' for c in runs])} |"
        )

    print("\nLỗi (mỗi cách gửi một dòng):")
    printed: set[tuple[str, str, str, str]] = set()
    for key in sorted(groups, key=sort_key):
        for call in groups[key]:
            if call["error"] and key not in printed:
                printed.add(key)
                print(f"  {key[0]} · {key[1]} · {key[2]} · {key[3]}: {call['error']}")
    if not printed:
        print("  (không có)")

    print("\nKhoá delta có dữ liệu / trường usage (lượt đầu của mỗi cách gửi):")
    for key in sorted(groups, key=sort_key):
        first = groups[key][0]
        usage_fields = sorted((first.get("usage_raw") or {}).keys())
        print(
            f"  {key[0]} · {key[1]} · {key[2]} · {key[3]}: delta={first['delta_keys']} "
            f"usage={usage_fields} model={first['models_seen']}"
        )

    print("\nThang (mức kề nhau, mọi lượt):")
    ladders: dict[tuple[str, str, str], list[tuple[str, list[dict[str, Any]]]]] = defaultdict(list)
    for key, group in groups.items():
        ladder = group[0]["ladder"]
        if ladder:
            ladders[(key[0], key[1], ladder)].append((key[2], group))
    for (model_id, path, ladder), steps in sorted(
        ladders.items(), key=lambda i: (order.get(i[0][0], 0), i[0][1:])
    ):
        steps.sort(key=lambda s: levels.index(s[0]))
        print(f"  {model_id} · {path} · thang '{ladder}':")
        for (low_id, low), (high_id, high) in zip(steps, steps[1:], strict=False):
            metric = _metric(low, high)
            lv, hv = _values(low, metric), _values(high, metric)
            if lv is None or hv is None or len(lv) < plan["runs"] or len(hv) < plan["runs"]:
                verdict = "THIẾU LƯỢT ĐO"
            else:
                verdict = "khác rõ" if distinct(lv, hv, plan["distinct"]) else "KHÔNG khác rõ"
            print(
                f"    {low_id} → {high_id}: {verdict} "
                f"({metric} {_fmt(lv or [])} → {_fmt(hv or [])})"
            )

    total = spent_usd(calls)
    sessions = data["sessions"]
    print(f"\nTổng chi phí trong file: {total} USD / ngân sách {plan['budget_usd']} USD")
    if sessions:
        mark = sessions[0]["started_at"]
        print(f"Mốc bắt đầu: {mark}")
        print(f"DoD: SELECT sum(cost_usd) FROM usage_events WHERE created_at > '{mark}';")


# ─────────────────────────────────── chạy ───────────────────────────────────


async def execute(
    cases: list[Case],
    plan: dict[str, Any],
    catalog: Catalog,
    data: dict[str, Any],
    out: Path,
    ledger_user: uuid.UUID,
) -> None:
    budget = Decimal(plan["budget_usd"])
    # Chạy tiếp một lần bị ngắt: lượt đã có kết quả (kể cả 4xx — đó cũng là một
    # phép đo) không gửi lại, để không trả tiền hai lần cho cùng một ô.
    done = {
        (c["model"], c["path"], c["level"], c["variant"], c["run"])
        for c in data["calls"]
        if c["status"] != "skipped-budget"
    }
    adapters = Adapters(catalog)
    try:
        for run in range(1, max(c.runs for c in cases) + 1):
            for case in cases:
                if run > case.runs or (*case.key, run) in done:
                    continue
                model = next(m for m in catalog.models if m.id == case.model_id)
                prompt, expected = question_of(plan, case)
                worst = worst_case_usd(catalog, model, case, prompt)
                spent = spent_usd(data["calls"])
                if spent + worst > budget:
                    print(
                        f"  bỏ qua (ngân sách): {case.key} lượt {run} — "
                        f"đã tiêu {spent}, xấu nhất {worst}"
                    )
                    data["calls"].append(
                        {**asdict_case(case), "run": run, "status": "skipped-budget"}
                    )
                    save_results(out, data)
                    continue
                record, row = await run_call(adapters, catalog, case, run, prompt, expected)
                if row is not None:
                    write_ledger(ledger_user, row)
                data["calls"].append(record)
                save_results(out, data)
                print(
                    f"  [{run}] {case.model_id} · {case.path} · {case.level} · {case.variant}: "
                    f"HTTP {record['status']} reasoning={record['reasoning_tokens']} "
                    f"completion={record['completion_tokens']} chữ={record['reasoning_chars']} "
                    f"{record['elapsed_s']}s {record['cost_usd'] or ''}"
                    + (f" LỖI {record['error'][:120]}" if record["error"] else "")
                )
    finally:
        await adapters.close()


def asdict_case(case: Case) -> dict[str, Any]:
    return {
        "model": case.model_id,
        "path": case.path,
        "level": case.level,
        "variant": case.variant,
        "ladder": case.ladder,
        "alias": case.alias,
        "params": case.params,
        "temperature": case.temperature,
        "max_tokens": case.max_tokens,
        "prompt": case.prompt,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--model", action="append", default=[], help="chỉ chạy model này (lặp được)"
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=RESULTS_DIR / f"reasoning-{datetime.now(UTC).date().isoformat()}.json",
        help="file kết quả, cộng dồn nếu đã có",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run", action="store_true", help="in các lượt và chi phí xấu nhất, không gọi gì"
    )
    mode.add_argument("--report", action="store_true", help="chỉ in lại bảng từ file kết quả")
    mode.add_argument("--ledger-user-id", type=uuid.UUID, help="user nhận các dòng usage_events")
    args = parser.parse_args()

    plan = load_plan(PLAN_PATH)
    catalog = get_catalog()
    data = load_results(args.out)

    if args.report:
        report(data, plan)
        return 0

    cases = build_cases(plan, catalog, set(args.model))
    calls = sum(c.runs for c in cases)
    if args.dry_run:
        total = Decimal(0)
        for case in cases:
            model = next(m for m in catalog.models if m.id == case.model_id)
            worst = worst_case_usd(catalog, model, case, question_of(plan, case)[0]) * case.runs
            total += worst
            print(
                f"  {case.runs}× {case.model_id} · {case.path} · {case.level} · {case.variant}"
                f" — xấu nhất {worst}"
            )
        print(
            f"{calls} lượt, xấu nhất {total} USD; "
            f"đã tiêu trong {args.out.name}: {spent_usd(data['calls'])} USD"
        )
        return 0

    check_ledger_user(args.ledger_user_id)
    data["sessions"].append(
        {
            "started_at": datetime.now(UTC).isoformat(),
            "models": sorted({c.model_id for c in cases}),
            "litellm_image": litellm_image(),
        }
    )
    save_results(args.out, data)
    print(f"{calls} lượt → {args.out.relative_to(REPO)} (mốc {data['sessions'][-1]['started_at']})")
    asyncio.run(execute(cases, plan, catalog, data, args.out, args.ledger_user_id))
    report(data, plan)
    return 0


if __name__ == "__main__":
    sys.exit(main())
