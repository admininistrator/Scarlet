#!/usr/bin/env python3
"""S2 — TTFT p50/p95 theo từng model, đo từ TRƯỚC `POST` tới `delta` đầu tiên.

KH tham chiếu: §2.3 (S2), §21.2, §7.2, §7.4, C1, C2 · tasks.md T-1.12.

    make bench          # hoặc: backend/.venv/bin/python scripts/bench_ttft.py

┌──────────────────────────────────────────────────────────────────────────┐
│  MỘT LƯỢT ĐO — HAI ĐƯỜNG CHẠY SONG ĐÔI                                   │
└──────────────────────────────────────────────────────────────────────────┘

    ① QUA SCARLET (đường người dùng thật đi)

        t0 ─── POST /conversations/{id}/messages ──► 202 + stream_url
             │                                  └─ t_http
             ├─ GET stream_url ─────► event `start`
             │                      └─ hàng đợi arq + dựng ngữ cảnh (§7.2 ③)
             └──────────────────────► event `delta` ĐẦU TIÊN  ◄── S2 dừng ở đây
                                    └─ upstream (client.stream + mẩu đầu)
             POST /messages/{id}/cancel     ← §7.5, cắt hoá đơn ngay tại đây

    ② BASELINE (gọi THẲNG LiteLLM, không một dòng code Scarlet nào ở giữa)

        t0 ─── adapter.stream(...) ───────────► `Chunk(kind="delta")` đầu tiên

Hiệu hai số là **phần Scarlet cộng thêm**. Không có đường ② thì một con số
p95 = 22 s không nói được nó là lỗi của hàng đợi, của `context.build`, hay của
provider — mà ba kết luận đó dẫn tới ba việc sửa hoàn toàn khác nhau.

┌──────────────────────────────────────────────────────────────────────────┐
│  SÁU QUYẾT ĐỊNH CỦA PHÉP ĐO                                              │
└──────────────────────────────────────────────────────────────────────────┘

**1. `t0` đặt TRƯỚC `POST`, không phải lúc nhận event `start`.** Đây là cạm
bẫy T-1.12 ghi thẳng ra, và nó không phải chuyện câu chữ: `start` được
`workers/generate.py` phát **sau** `_prepare()`, tức sau khi job đã nằm chờ
trong hàng đợi arq và sau khi `context.build` đã chạy xong. Bấm giờ từ `start`
là tự tặng mình đúng hai chặng mà A1 vừa tạo ra — và người dùng thì đếm từ lúc
bấm nút.

**2. Mỗi lượt là một GỐC MỚI (`parent_id: null`), không nối vào lượt trước.**
§8.2 cho một hội thoại có nhiều gốc, và T-1.8 phân biệt `parent_id` vắng mặt
với `parent_id: null` tường minh đúng để chuyện này làm được. Nối tiếp nhau thì
lượt thứ 30 mang theo 29 lượt lịch sử: `context.build` chậm dần, `prompt_tokens`
phình dần, và p95 sẽ đo **độ dài hội thoại** chứ không đo TTFT.

**3. Vòng tròn giữa các model, không chạy hết model này rồi tới model kia.**
Lượt `i` chạy lần lượt cả bốn model rồi mới sang lượt `i+1`. Một cơn chậm của
mạng kéo dài vài phút mà xếp theo khối thì nó rơi trọn vào một model và biến
thành "model đó chậm". Vì cùng lý do, thứ tự hai đường ① ② **đảo theo parity**
của lượt: luôn chạy baseline sau sẽ cho baseline hưởng mọi thứ đã nóng sẵn.

**4. Lượt hỏng đếm là `+∞`, không bị vứt.** Một lượt không ra nổi `delta` là
một lượt người dùng **không nhận được chữ nào** — đó là độ trễ tệ nhất có thể,
không phải một mẫu "không hợp lệ" để loại khỏi bảng. Vứt nó đi là làm p95 đẹp
lên đúng ở những lần hệ thống hỏng nhất. Với `--luot 30`, p95 lấy phần tử thứ
29/30 nên **một** lượt hỏng chưa đụng p95 (nhưng đụng `max`), **hai** lượt thì
p95 thành `∞` và model đó đỏ.

**5. Phân vị theo THỨ HẠNG, không nội suy.** `statistics.quantiles` nội suy
tuyến tính giữa hai mẫu và đẻ ra một con số **chưa ai đo được bao giờ**; ở đây
mọi số in ra đều là một lượt có thật. Cùng tinh thần NQ-23: không biến "không
đo được" thành "đo được".

**6. Huỷ ngay sau `delta` đầu tiên (§7.5).** S2 chỉ hỏi tới token đầu; sinh
nốt 800 chữ nữa là trả tiền cho phần không ai đo. `POST /messages/{id}/cancel`
đặt cờ, worker dừng ở lần kiểm 8-chunk kế tiếp. Điều này **không** đụng vào con
số: mọi mốc thời gian đã chốt trước khi cờ được đặt.

**Ngưỡng S2 và hai nhóm model.** §2.3 chia "model qua 9Router local" (≤ 2.0 s)
và "model qua API" (≤ 4.0 s). Nhóm suy ra từ **scheme của `base_url` trong
catalog**: `https://` ⇒ đi ra Internet ⇒ nhóm `api`; `http://` ⇒ chạy trên
chính máy này (`host.docker.internal`, `ollama:11434`) ⇒ nhóm `local`. Suy từ
dữ liệu catalog chứ không chép tên provider vào đây (A3) — nhưng nó là một suy
luận, không phải một trường được khai: xem Backlog.

**TLS**: như `scripts/test_resume.py` — CA của mkcert nằm trên máy Windows
(T-H1), không nằm trong trust store của WSL, nên mặc định bỏ kiểm chứng chỉ.

**Dữ liệu**: script tự tạo user + hội thoại rồi **xoá sạch** ở cuối (B-81).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import sys
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

# ──────────────────────────── hằng số của phép đo ───────────────────────────

#: "30 lượt cho mỗi model" — con số trong "Việc cần làm" của T-1.12.
RUNS = 30

#: Hai ngưỡng p95 của S2 (§2.3). Để ở đây chứ không trong `Settings`: chúng là
#: *tiêu chí nghiệm thu* của một script chạy tay, không phải cấu hình mà app
#: đọc lúc boot — cùng chỗ đứng với `RUNS`/`MAX_RUN_S` của
#: `test_resume.py`. Đổi số ở đây là đổi tiêu chí, và phải đổi §2.3 trước.
P95_LIMIT_LOCAL_S = 2.0
P95_LIMIT_API_S = 4.0

#: Trần cho MỘT lượt. Bài học B-88 ở mức script: mọi vòng chờ phải có phanh,
#: nếu không "hỏng" sẽ đội lốt "đang chạy". Rộng: 9Router đo được ~22 s ngay cả
#: khi khoẻ, nên trần chặt sẽ cắt nhầm một phép đo đúng.
MAX_RUN_S = 150.0

#: Nghỉ giữa hai lượt. Không phải để làm đẹp số: 30 lượt bắn liên tiếp vào cùng
#: một provider là cách nhanh nhất để nhận `429`, và một `429` ở đây sẽ được
#: ghi thành `+∞` (quyết định 4) — tức một lỗi hạ tầng của phép đo trông y hệt
#: một lần hệ thống chậm thật.
PAUSE_BETWEEN_RUNS_S = 0.5

#: Câu hỏi. Ngắn và tầm thường có chủ ý — S2 đo **độ trễ tới token đầu**, nên
#: mọi thứ làm câu trả lời dài ra chỉ thêm nhiễu. Với model reasoning
#: (`deepseek-flash`, B-33/B-97) câu càng dễ thì pha "suy nghĩ" càng ngắn, tức
#: khoảng cách `reasoning` → `delta` càng gần với thứ người dùng thường gặp.
PROMPT = "Trả lời thật ngắn, đúng một câu: thủ đô của Việt Nam là thành phố nào?"

#: DoD: `evals/results/ttft-{date}.json`. Thư mục đã nằm trong `.gitignore`.
RESULTS_DIR = REPO_ROOT / "evals" / "results"

#: `.env` của repo — nguồn của `PUBLIC_BASE_URL` và hai biến `DEV_*` khi chạy
#: từ WSL host (compose nạp file này cho container, host thì không).
ENV_FILE = REPO_ROOT / ".env"

#: Postgres nhìn từ host. `DATABASE_URL` ghi `postgres:5432`, chỉ phân giải
#: được trong network `internal` (C17/C45).
DB_VAR = "DEV_DATABASE_URL"

#: LiteLLM nhìn từ host — cùng hình dạng vấn đề, cùng cách giải. `Settings`
#: ghi `LITELLM_BASE_URL=http://litellm:4000/v1`, một tên chỉ sống trong
#: network `internal`; đường ② của script chạy ở WSL host nên phải đi qua cổng
#: mà `docker-compose.yml` publish. Không dùng `os.getenv(..., "mặc định")`:
#: A4 cấm, và một baseline trỏ nhầm chỗ là một baseline sai trong im lặng.
LITELLM_VAR = "DEV_LITELLM_BASE_URL"

_ASSIGNMENT_LINE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")
_TRAILING_COMMENT = re.compile(r"\s+#.*$")


def load_env() -> None:
    """Nạp `.env` vào `os.environ` — **không đè** biến đã export sẵn.

    Bản sao có chủ ý của `scripts/test_resume.py::nap_env`: cùng lý do (một
    lệnh `make`, không phải "nhớ source trước") và cùng chỗ thô sơ (cắt ở dấu
    `=` đầu tiên, chỉ bỏ chú thích đứng sau khoảng trắng — bài học B-44).
    """
    if not ENV_FILE.is_file():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        match = _ASSIGNMENT_LINE.match(line.strip().rstrip("\r"))
        if match is None:
            continue
        name, value = match.group(1), _TRAILING_COMMENT.sub("", match.group(2)).strip()
        os.environ.setdefault(name, value)


load_env()

import asyncpg  # noqa: E402
import httpx  # noqa: E402

from app.config.catalog import ModelEntry, Provider, get_catalog  # noqa: E402
from app.config.settings import settings  # noqa: E402
from app.core.access_token import encode_access_token  # noqa: E402
from app.core.deps import SESSION_COOKIE_NAME  # noqa: E402
from app.db.models import UserRole, UserStatus  # noqa: E402
from app.llm.adapters.system import SystemAdapter  # noqa: E402


def required_var(name: str, hint: str) -> str:
    """Đọc một biến `DEV_*`, thiếu thì **nổ ngay kèm tên biến** (A4)."""
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"thiếu {name}. Đặt nó trong môi trường hoặc trong {ENV_FILE}. {hint}")
    return value


def dev_database_url() -> str:
    url = required_var(
        DB_VAR, "Mẫu ở .env.example; cần `docker compose up -d postgres` publish 127.0.0.1:5432"
    )
    # asyncpg nhận DSN thuần, không hiểu phương ngữ `+asyncpg` của SQLAlchemy.
    return url.replace("postgresql+asyncpg://", "postgresql://")


# ═════════════════════════ nhóm ngưỡng của một model ═══════════════════════


def group_of(provider: Provider) -> str:
    """`api` (≤ 4.0 s) hay `local` (≤ 2.0 s) — xem docstring module.

    Đọc `base_url` của chính catalog thay vì giữ một danh sách tên provider ở
    đây: thêm provider thứ năm không được kéo theo một lần sửa file này (A3,
    §9.8). Đánh đổi đã ghi vào Backlog — một provider local chạy sau TLS sẽ bị
    xếp nhầm nhóm, và catalog hôm nay không có trường nào nói thẳng điều đó.
    """
    return "api" if urlsplit(provider.base_url).scheme == "https" else "local"


def limit_of(group: str) -> float:
    return P95_LIMIT_API_S if group == "api" else P95_LIMIT_LOCAL_S


# ═════════════════════════════ phân tích dòng SSE ══════════════════════════


@dataclass(slots=True)
class SseEvent:
    event: str
    data: str


class SseReader:
    """Gom byte thành event, chỉ phát ra khi đã gặp dòng trống kết thúc.

    Rút gọn từ `test_resume.py`: ở đây không ai ngắt giữa chừng nên `id:` không
    cần giữ lại, nhưng luật "chưa thấy dòng trống thì chưa phải một event" vẫn
    y nguyên — bấm giờ lên một khung `data:` mới nhận được một nửa là bấm giờ
    lên những byte chưa tới nơi.
    """

    __slots__ = ("_buffer", "_event", "_data")

    def __init__(self) -> None:
        self._buffer = ""
        self._reset()

    def _reset(self) -> None:
        self._event = "message"
        self._data: list[str] = []

    def feed(self, chunk: str) -> list[SseEvent]:
        self._buffer += chunk
        out: list[SseEvent] = []
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.rstrip("\r")
            if line == "":
                if self._data or self._event != "message":
                    out.append(SseEvent(self._event, "\n".join(self._data)))
                self._reset()
                continue
            if line.startswith(":"):
                continue  # `: ping` của C2 — không phải event
            name, _, value = line.partition(":")
            value = value[1:] if value.startswith(" ") else value
            if name == "event":
                self._event = value
            elif name == "data":
                self._data.append(value)
        return out


# ══════════════════════════════ một lượt đo ════════════════════════════════

#: Giá trị của một chặng không đo được. Xem quyết định 4.
FAILED = math.inf


@dataclass(slots=True)
class Run:
    """Các mốc của một lượt, tính bằng giây kể từ `t0` (trước `POST`)."""

    luot: int
    model: str
    #: `POST` → `202`. Ngân sách §7.2 ① là < 100 ms; A1 sống hay chết ở đây.
    http: float = FAILED
    #: `202` → lúc CLIENT ĐỌC ĐƯỢC event `start`. Ba thứ nằm trong đây, không
    #: phải hai: hàng đợi arq (arq poll theo nhịp, nên 0–`poll_delay`),
    #: `_prepare()` tức `context.build` (§7.2 ③), **và** thời gian mở kết nối
    #: SSE qua Nginx — script chỉ `GET stream_url` sau khi `202` đã về, đúng
    #: như trình duyệt làm. Chặng này không tách nhỏ hơn được từ phía client;
    #: tách được thì phải đọc log `request_id` của §21.1 ở cả hai tiến trình.
    hang_doi_context: float = FAILED
    #: `start` → `delta` đầu tiên. `client.stream()` + mẩu đầu của provider.
    upstream: float = FAILED
    #: `t0` → `delta` đầu tiên. **Đây là con số của S2.**
    tong: float = FAILED
    #: `t0` → event `reasoning` đầu tiên, nếu model có (B-33). Không phải S2 —
    #: in ra vì với model reasoning, đây mới là lúc màn hình hết trống.
    reasoning: float | None = None
    #: Đường ② — gọi thẳng LiteLLM, không qua Scarlet.
    baseline: float = FAILED
    #: Rỗng nếu lượt đo trọn vẹn. Một lượt hỏng được ở CẢ HAI đường, nên
    #: `add_reason` nối chứ không ghi đè — mất một nửa lý do là mất đúng nửa
    #: mà người đọc đang cần.
    ly_do_hong: str = ""

    def add_reason(self, sentence: str) -> None:
        self.ly_do_hong = f"{self.ly_do_hong} · {sentence}" if self.ly_do_hong else sentence


@dataclass(slots=True)
class ModelResult:
    model: str
    provider: str
    group: str
    p95_limit_s: float
    luot: list[Run] = field(default_factory=list)

    def column(self, name: str) -> list[float]:
        return [getattr(run, name) for run in self.luot]

    @property
    def failed_count(self) -> int:
        return sum(1 for run in self.luot if run.ly_do_hong)

    @property
    def passed(self) -> bool:
        return percentile(self.column("tong"), 95) <= self.p95_limit_s


def per_run_overhead(k: ModelResult) -> tuple[list[float], int]:
    """`TTFT − baseline` của TỪNG lượt, bỏ những lượt không định nghĩa được.

    Một lượt mà **một trong hai** đường không ra chữ thì hiệu của nó không có
    nghĩa: `∞ − 0.7` là `∞` (đổ hết lỗi của một lượt hỏng lên phần "Scarlet
    cộng thêm"), và `∞ − ∞` là `nan` (một giá trị sẽ phá cả phép sắp xếp).
    Ngả đúng là **không tính** lượt đó và **nói ra đã bỏ bao nhiêu** — đây là
    cột duy nhất của bảng cần cả hai đường cùng thành công, nên nó là cột duy
    nhất được phép loại mẫu.
    """
    cap = zip(k.column("tong"), k.column("baseline"), strict=True)
    usable = [a - b for a, b in cap if math.isfinite(a) and math.isfinite(b)]
    return usable, len(k.luot) - len(usable)


def percentile(samples: list[float], p: float) -> float:
    """Phân vị thứ `p` theo **thứ hạng gần nhất** — xem quyết định 5.

    `ceil(p/100 * N)` là hạng (1-based) của phần tử cần lấy. Với N=30: p50 →
    hạng 15, p95 → hạng 29. Mọi giá trị trả về đều là một lượt có thật, kể cả
    khi nó là `+∞` của một lượt hỏng.
    """
    if not samples:
        return FAILED
    ordered = sorted(samples)
    rank = math.ceil(p / 100 * len(ordered))
    return ordered[min(max(rank, 1), len(ordered)) - 1]


class Timeout(Exception):  # noqa: N818 - tên theo nghiệp vụ
    """Vượt `MAX_RUN_S`. Treo cũng là đỏ, chỉ là kiểu đỏ không tự khai."""


async def close_quietly(stream: AsyncIterator[Any]) -> None:
    """Đóng một async iterator sau khi thoát sớm khỏi nó.

    **Cả hai đường của script này đều thoát sớm** — đó là toàn bộ điểm của
    phép đo: dừng ngay ở mẩu chữ đầu tiên. Nhưng `return`/`break` giữa một
    `async for` chỉ *bỏ lại* generator cho bộ dọn rác, và httpcore đóng muộn
    như vậy thì ném `RuntimeError: generator didn\'t stop after athrow()`
    thẳng ra stderr — đo được ở bản nháp đầu của script này, và nó rơi đúng
    vào giữa bảng kết quả.

    `getattr` chứ không phải gọi thẳng: `LLMClient.stream()` hứa trả
    `AsyncIterator[Chunk]` và `httpx.Response.aiter_text()` cũng vậy, mà
    `AsyncIterator` **không** hứa có `aclose()` — hôm nay cả hai đều là async
    generator nên đều có. Không có thì cũng không có gì để đóng.
    """
    aclose = getattr(stream, "aclose", None)
    if aclose is not None:
        await aclose()


class Measurement:
    """Hai đường chạy của một model, dùng lại cho cả 30 lượt."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        adapter: SystemAdapter,
        conversation_id: uuid.UUID,
        *,
        on_am: bool,
    ) -> None:
        self._http = http
        self._adapter = adapter
        self._cid = conversation_id
        self._on_am = on_am

    def _log(self, *parts: object) -> None:
        if not self._on_am:
            print("   ", *parts, flush=True)

    async def one_run(self, so: int, model: ModelEntry, baseline_first: bool) -> Run:
        """Chạy cả hai đường. `baseline_first` đảo thứ tự — xem quyết định 3."""
        kq = Run(luot=so, model=model.id)
        if baseline_first:
            await self._do_baseline(kq, model)
            await asyncio.sleep(PAUSE_BETWEEN_RUNS_S)
            await self._measure_via_scarlet(kq, model)
        else:
            await self._measure_via_scarlet(kq, model)
            await asyncio.sleep(PAUSE_BETWEEN_RUNS_S)
            await self._do_baseline(kq, model)
        return kq

    # ───────────────────────── ① qua Scarlet ─────────────────────────

    async def _measure_via_scarlet(self, kq: Run, model: ModelEntry) -> None:
        t0 = time.perf_counter()
        deadline = t0 + MAX_RUN_S
        amid: str | None = None
        try:
            res = await self._http.post(
                f"/api/v1/conversations/{self._cid}/messages",
                json={
                    "content": PROMPT,
                    "model_id": model.id,
                    # Tường minh `null` ⇒ gốc của một nhánh mới (§8.2, C14).
                    # Xem quyết định 2: đây là thứ giữ ngữ cảnh của lượt 30
                    # bằng đúng ngữ cảnh của lượt 1.
                    "parent_id": None,
                },
                headers={"Idempotency-Key": str(uuid.uuid4())},
            )
            res.raise_for_status()
            kq.http = time.perf_counter() - t0
            body = res.json()
            amid = body["assistant_message_id"]
            await self._read_until_first_delta(kq, body["stream_url"], t0, deadline)
        except Timeout as error:
            kq.ly_do_hong = f"TREO — {error}"
        except httpx.HTTPError as error:
            kq.ly_do_hong = f"HTTP — {type(error).__name__}: {error}"
        except (KeyError, ValueError) as error:
            kq.ly_do_hong = f"RESPONSE — {type(error).__name__}: {error}"
        finally:
            if amid is not None:
                await self._cancel(amid)

    async def _read_until_first_delta(self, kq: Run, stream_url: str, t0: float, deadline: float) -> None:
        """Đọc SSE tới `delta` đầu tiên rồi đóng. Ghi mốc `start`/`reasoning` dọc đường."""
        reader = SseReader()
        t_start: float | None = None
        async with self._http.stream("GET", stream_url) as res:
            res.raise_for_status()
            chunk_iter = res.aiter_text()
            try:
                async for chunk in chunk_iter:
                    if time.perf_counter() > deadline:
                        raise Timeout(f"quá {MAX_RUN_S:.0f}s chưa thấy `delta`")
                    for event in reader.feed(chunk):
                        elapsed = time.perf_counter() - t0
                        if event.event == "start" and t_start is None:
                            t_start = elapsed
                            kq.hang_doi_context = elapsed - kq.http
                        elif event.event == "reasoning" and kq.reasoning is None:
                            kq.reasoning = elapsed
                        elif event.event == "delta":
                            kq.tong = elapsed
                            # `start` phải tới trước `delta` (producer phát nó
                            # trước `client.stream`), nhưng không giả định:
                            # thiếu nó thì chặng upstream là không đo được,
                            # không phải bằng 0.
                            kq.upstream = elapsed - t_start if t_start is not None else FAILED
                            return
                        elif event.event in ("done", "error"):
                            # Mang theo cả payload: event `error` của §7.4 chở
                            # một MÃ (`UPSTREAM_ERROR`, `WORKER_LOST`…) và đó
                            # là câu trả lời duy nhất cho "vì sao lượt này
                            # hỏng". Bản đầu của script chỉ ghi tên loại event,
                            # và một lượt `nr-gemini-flash` hỏng thật trong
                            # phép đo 30 lượt đã không truy được nguyên nhân —
                            # script tự xoá dữ liệu của nó ở cuối nên message
                            # cũng không còn trong Postgres để hỏi lại.
                            kq.ly_do_hong = (
                                f"kết thúc bằng `{event.event}` mà chưa có "
                                f"`delta` — {event.data[:200]}"
                            )
                            return
            finally:
                await close_quietly(chunk_iter)

        # Stream đóng mà không `done`, không `error`, không `delta`.
        kq.ly_do_hong = "stream đóng khi chưa có `delta` nào"

    async def _cancel(self, assistant_message_id: str) -> None:
        """§7.5 — cắt hoá đơn. Lỗi ở đây KHÔNG được làm hỏng một phép đo đã xong."""
        try:
            await self._http.post(f"/api/v1/messages/{assistant_message_id}/cancel")
        except httpx.HTTPError as error:
            self._log(f"(không huỷ được {assistant_message_id}: {type(error).__name__}: {error})")

    # ───────────────────────── ② baseline ─────────────────────────

    async def _do_baseline(self, kq: Run, model: ModelEntry) -> None:
        """Gọi thẳng LiteLLM với ĐÚNG tham số mà `workers/generate.py` gửi.

        Giống tới từng tham số là điều kiện để hiệu hai số có nghĩa:
        `max_tokens=model.max_output` và `temperature=settings.LLM_TEMPERATURE`
        là hai thứ `_chay()` truyền vào, và cả hai đều đổi được thời gian tới
        token đầu ở một số provider. Khác biệt duy nhất còn lại giữa ① và ② là
        ngữ cảnh: ② gửi đúng một message user, ① gửi thêm system prompt mà
        `context.build` dựng — chênh lệch đó **là** thứ cần đo.
        """
        t0 = time.perf_counter()
        deadline = t0 + MAX_RUN_S
        try:
            stream = await self._adapter.stream(
                model=model.id,
                messages=[{"role": "user", "content": PROMPT}],
                tools=None,
                max_tokens=model.max_output,
                temperature=settings.LLM_TEMPERATURE,
                extra={},
            )
            try:
                async for chunk in stream:
                    if time.perf_counter() > deadline:
                        raise Timeout(f"quá {MAX_RUN_S:.0f}s chưa thấy chunk `delta`")
                    if chunk.kind == "delta" and chunk.text:
                        kq.baseline = time.perf_counter() - t0
                        return
                    if chunk.kind == "done":
                        break
            finally:
                await close_quietly(stream)
        except Timeout as error:
            kq.add_reason(f"BASELINE TREO — {error}")
            return
        except Exception as error:  # noqa: BLE001 — mọi lỗi provider đều là một lượt hỏng
            kq.add_reason(f"BASELINE — {type(error).__name__}: {error}")
            return
        kq.add_reason("BASELINE — hết stream mà không có chunk `delta`")


# ═══════════════════════════ dựng và dọn dữ liệu ═══════════════════════════


def session_cookie(user_id: uuid.UUID, tier: str) -> dict[str, str]:
    """Header `Cookie` mang một access JWT thật cho `user_id` (§11.2).

    T-3.1c xoá nhánh danh tính tạm của Phase 1, thứ script này mang danh tính
    bằng từ T-1.11. Script chạy từ WSL host nhưng đã `sys.path.insert` vào
    `backend/`, nên nó ký được token bằng **chính** `JWT_SECRET` mà `api` đọc
    — rẻ hơn hẳn đường `POST /auth/login` (cần một mật khẩu Argon2id thật, một
    lần Turnstile, và một suất trong hạn mức §10.6 cho mỗi lần chạy DoD).

    `status=ACTIVE` khớp đúng hàng mà `create_user` chèn vào Postgres, và `tier`
    đọc từ chính hàng ấy chứ không gõ tay (A3): một claim nói khác DB sẽ chạy
    được hôm nay — §11.1 đọc trạng thái từ claim — rồi hỏng vào đúng ngày ai
    đó đổi nó sang đọc DB.
    """
    token = encode_access_token(
        user_id=user_id,
        role=UserRole.USER,
        tier=tier,
        status=UserStatus.ACTIVE,
        ttl_minutes=settings.ACCESS_TOKEN_TTL_MIN,
    )
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


async def create_user(pool: asyncpg.Pool, marker: str) -> tuple[uuid.UUID, str]:
    """`users` chưa có model ORM (Phase 2, T-2.1) nên chèn bằng SQL thô.

    Trả kèm `tier_name` để `session_cookie` khỏi phải gõ lại tên tier (A3).
    """
    async with pool.acquire() as conn:
        rank = await conn.fetchrow(
            # `status='active'` từ T-3.1c: cookie phiên mang claim `active`
            # (xem `session_cookie`), và hàng trong DB phải nói cùng một câu.
            "INSERT INTO users (email, password_hash, status) "
            "VALUES ($1, $2, 'active') RETURNING id, tier_name",
            f"{marker}@scarlet.test",
            "khong-phai-hash-that",
        )
    assert rank is not None
    assert isinstance(rank["id"], uuid.UUID)
    return rank["id"], str(rank["tier_name"])


async def cleanup(pool: asyncpg.Pool, user_id: uuid.UUID) -> tuple[int, int]:
    """Xoá **cứng** mọi thứ script vừa tạo (B-81).

    `conversations.active_leaf_id` trỏ vào `messages` nên phải gỡ con trỏ
    trước, rồi mới xoá message, rồi mới xoá hội thoại.
    """
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "UPDATE conversations SET active_leaf_id = NULL WHERE user_id = $1", user_id
        )
        so_msg = await conn.fetchval(
            "WITH x AS (DELETE FROM messages WHERE conversation_id IN "
            "(SELECT id FROM conversations WHERE user_id = $1) RETURNING 1) "
            "SELECT count(*) FROM x",
            user_id,
        )
        so_ht = await conn.fetchval(
            "WITH x AS (DELETE FROM conversations WHERE user_id = $1 RETURNING 1) "
            "SELECT count(*) FROM x",
            user_id,
        )
        await conn.execute("DELETE FROM users WHERE id = $1", user_id)
    return int(so_msg or 0), int(so_ht or 0)


# ═════════════════════════════ in bảng và ghi JSON ═════════════════════════

#: Các chặng in ra bảng, theo thứ tự thời gian của một lượt.
STAGES = (
    ("http", "POST→202"),
    ("hang_doi_context", "→start"),
    ("upstream", "→delta"),
    ("tong", "TTFT"),
    ("baseline", "baseline"),
)


def s(value: float) -> str:
    """Giây → chuỗi rộng 8.

    `∞` là một lượt **không ra chữ nào** (quyết định 4), không phải "thiếu dữ
    liệu". `—` là một giá trị không định nghĩa được — chỉ xảy ra nếu một phép
    trừ nào đó lọt `inf - inf`; in ra chứ không để nó thành chuỗi `nan` giữa
    một cột số.
    """
    if math.isnan(value):
        return f"{'—':>8}"
    if math.isinf(value):
        return f"{'-∞' if value < 0 else '∞':>8}"
    return f"{value:8.3f}"


#: Hai câu phải đứng ngay dưới bảng, vì không có chúng thì bảng đọc sai được
#: theo đúng hai cách mà một người cẩn thận sẽ mắc.
TABLE_NOTES = (
    "mỗi chặng lấy phân vị ĐỘC LẬP trên cột của nó, nên bốn dòng đầu KHÔNG"
    " cộng lại thành dòng TTFT —\n    p95 của mỗi chặng đến từ một lượt khác"
    " nhau.",
    "`Scarlet cộng thêm` là hiệu theo TỪNG LƯỢT (TTFT − baseline của chính"
    " lượt đó), rồi mới lấy phân vị.\n    Số âm = lượt đó baseline chậm hơn"
    " đường qua Scarlet, tức nhiễu của provider lớn hơn phần Scarlet thêm vào.",
)


def print_table(results: list[ModelResult], bo_qua: set[str]) -> None:
    width = max(len(k.model) for k in results)
    print("\n" + "═" * 78)
    print("TTFT — giây, từ TRƯỚC `POST` tới event `delta` đầu tiên (S2, §2.3)")
    print("═" * 78)
    for k in results:
        limit = f"p95 ≤ {k.p95_limit_s:.1f}s"
        exempt = "  [MIỄN TRỪ]" if k.model in bo_qua else ""
        print(f"\n{k.model:<{width}}  ({k.provider} · nhóm {k.group} · {limit}){exempt}")
        print(f"  {'chặng':<18}{'p50':>8}{'p95':>8}{'max':>8}")
        for name, label in STAGES:
            column = k.column(name)
            print(f"  {label:<18}{s(percentile(column, 50))}{s(percentile(column, 95))}{s(max(column))}")
        added, dropped = per_run_overhead(k)
        label = "Scarlet cộng thêm"
        suffix = f"  — bỏ {dropped}/{len(k.luot)} lượt không đủ hai đầu" if dropped else ""
        print(
            f"  {label:<18}{s(percentile(added, 50))}{s(percentile(added, 95))}"
            f"{s(max(added) if added else FAILED)}{suffix}"
        )
        with_reasoning = [run.reasoning for run in k.luot if run.reasoning is not None]
        if with_reasoning:
            print(
                f"  {'(→reasoning đầu)':<18}{s(percentile(with_reasoning, 50))}"
                f"{s(percentile(with_reasoning, 95))}{s(max(with_reasoning))}  "
                f"— {len(with_reasoning)}/{len(k.luot)} lượt (B-33, không phải S2)"
            )
        if k.failed_count:
            print(f"  ✗ {k.failed_count}/{len(k.luot)} lượt hỏng — đếm là ∞ (quyết định 4):")
            for run in k.luot:
                if run.ly_do_hong:
                    print(f"      lượt {run.luot}: {run.ly_do_hong}")
    print()
    for sentence in TABLE_NOTES:
        print(f"  · {sentence}")


def _free_name(base: Path) -> Path:
    """Tên đầu tiên chưa bị chiếm, thử `-hhmm` rồi `-hhmm-2`, `-hhmm-3`…

    Hậu tố phút một mình là **chưa đủ** và đó không phải chuyện lý thuyết: một
    lượt 8 lượt trên `ol-qwen-small` chạy hết ~11 s, nên hai lần chạy liên tiếp
    rơi trọn vào cùng một phút — đã đè mất một phép đo đúng như thế ngay trong
    phiên vá B-106 này. Vòng lặp chạy tới khi tìm được tên trống nên hàm này
    **không bao giờ** trả về một đường dẫn đã có file.
    """
    minute = datetime.now().strftime("%H%M")
    candidate = base.with_name(f"{base.stem}-{minute}{base.suffix}")
    attempt = 2
    while candidate.is_file():
        candidate = base.with_name(f"{base.stem}-{minute}-{attempt}{base.suffix}")
        attempt += 1
    return candidate


def write_json(
    results: list[ModelResult], bo_qua: set[str], path: Path, *, ghi_de: bool = False
) -> None:
    """DoD: `evals/results/ttft-{date}.json`.

    Ghi cả **mẫu thô** chứ không chỉ ba con số: p95 của 30 mẫu không cho biết
    phân bố có hai đỉnh hay không, mà "đôi khi 0.4 s, đôi khi 22 s" và "luôn
    luôn 11 s" là hai sự cố khác hẳn nhau. `∞` không phải JSON hợp lệ nên lượt
    hỏng ghi `null` — trường `ly_do_hong` của chính lượt đó nói vì sao.

    **Không bao giờ huỷ một phép đo đã có (B-106, B-119).** Tên do DoD T-1.12
    chốt là `ttft-{date}.json`, tức mọi lần chạy trong cùng một ngày trỏ vào
    **một** chỗ. Đã mất dữ liệu vì điều đó **hai** lần: ba lần `--luot 1` thử
    cờ đè mất bản 30 lượt khi viết T-1.12, rồi bản 30 lượt của chính T-1.12 bị
    một lần rà phase `--luot 8` đè mất. Cả hai lần script *có* in `ĐÈ LÊN` —
    nhưng chỉ **sau** khi đã đè, nên dòng đó không cứu được gì.

    Luật nay là:

    - file chưa có     → ghi đúng tên của DoD (hợp đồng còn nguyên cho lần đầu)
    - file đã có       → ghi sang `ttft-{date}-{hhmm}.json`, **không** đụng bản cũ
    - có ``--ghi-de``  → đè bản cũ, và nói rõ là đang đè

    Chọn "ghi sang tên khác" chứ không phải "từ chối ghi": lượt chạy đã tốn
    tiền thật và tính bằng chục phút, nên vứt kết quả đi để bảo vệ kết quả cũ
    là đổi một mất mát lấy một mất mát khác. Ngả này không mất bên nào.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.is_file()
    if exists and not ghi_de:
        path = _free_name(path)

    def so(v: float) -> float | None:
        # `math.isfinite` chứ không phải `math.isinf`: `nan` cũng không phải
        # JSON hợp lệ, và `json.dumps` sẽ lặng lẽ ghi ra chữ `NaN` — một file
        # mà mọi bộ đọc JSON đúng chuẩn đều từ chối.
        return round(v, 4) if math.isfinite(v) else None

    payload = {
        "tieu_chi": "S2",
        "sinh_luc": datetime.now(UTC).isoformat(timespec="seconds"),
        "so_luot": len(results[0].luot) if results else 0,
        "prompt": PROMPT,
        "base_url": settings.PUBLIC_BASE_URL,
        "nguong_p95_s": {"local": P95_LIMIT_LOCAL_S, "api": P95_LIMIT_API_S},
        "bo_qua": sorted(bo_qua),
        "models": [
            {
                "model": k.model,
                "provider": k.provider,
                "nhom": k.group,
                "tran_p95_s": k.p95_limit_s,
                "dat": k.passed,
                "mien_tru": k.model in bo_qua,
                "so_hong": k.failed_count,
                "phan_vi": {
                    name: {
                        "p50": so(percentile(k.column(name), 50)),
                        "p95": so(percentile(k.column(name), 95)),
                        "max": so(max(k.column(name))),
                    }
                    for name, _ in STAGES
                },
                "scarlet_cong_them": {
                    "p50": so(percentile(per_run_overhead(k)[0], 50)),
                    "p95": so(percentile(per_run_overhead(k)[0], 95)),
                    "so_luot_bo": per_run_overhead(k)[1],
                },
                "mau": [_run_json(run, so) for run in k.luot],
            }
            for k in results
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if exists and ghi_de:
        print(f"\nĐÈ LÊN {path.relative_to(REPO_ROOT)}  (--ghi-de)")
    elif exists:
        print(
            f"\nđã ghi {path.relative_to(REPO_ROOT)}"
            f"\n  (hôm nay đã có một phép đo rồi nên KHÔNG đè lên nó; `--ghi-de` nếu muốn đè)"
        )
    else:
        print(f"\nđã ghi {path.relative_to(REPO_ROOT)}")


def _run_json(run: Run, so: Callable[[float], float | None]) -> dict[str, object]:
    """Một lượt → object JSON, với mọi chặng đã đi qua `so()`."""
    return {**asdict(run), **{name: so(getattr(run, name)) for name, _ in STAGES}}


def print_verdict(results: list[ModelResult], bo_qua: set[str]) -> int:
    """Một dòng cho mỗi model, rồi một dòng tổng. Mã thoát ≠ 0 nếu có model trượt."""
    print("\n" + "═" * 78)
    failing: list[str] = []
    for k in results:
        p95 = percentile(k.column("tong"), 95)
        if k.passed:
            verdict = "PASS"
        elif k.model in bo_qua:
            verdict = "MIỄN"
        else:
            verdict = "FAIL"
            failing.append(k.model)
        print(f"  {verdict}  {k.model}: p95 = {s(p95).strip()}s (trần {k.p95_limit_s:.1f}s)")
    print("═" * 78)
    print(f"{'FAIL' if failing else 'PASS'} {len(results) - len(failing)}/{len(results)}")
    if failing:
        print(f"S2 chưa đạt: {', '.join(failing)}")
    return 1 if failing else 0


# ══════════════════════════════════ chạy ═══════════════════════════════════


def pick_models(args: argparse.Namespace) -> list[ModelEntry]:
    enabled_models = [m for m in get_catalog().models if m.enabled]
    if args.model:
        requested = set(args.model)
        chosen = [m for m in enabled_models if m.id in requested]
        missing = requested - {m.id for m in chosen}
        if missing:
            raise SystemExit(f"model không có trong catalog hoặc đã tắt: {sorted(missing)}")
        return chosen
    if not enabled_models:
        raise SystemExit("catalog không có model nào đang bật (§9.2)")
    return enabled_models


async def run(args: argparse.Namespace) -> int:
    models = pick_models(args)
    bo_qua = set(args.bo_qua)
    known = {m.id for m in models}
    if unknown := bo_qua - known:
        raise SystemExit(f"--bo-qua nhắc model không nằm trong lượt đo: {sorted(unknown)}")

    marker = f"t112-{uuid.uuid4().hex[:8]}"
    litellm_url = required_var(
        LITELLM_VAR, "Mẫu ở .env.example; cần `docker compose up -d litellm` publish cổng 4000"
    )
    print(
        f"models={[m.id for m in models]}  luot={args.luot}\n"
        f"base={settings.PUBLIC_BASE_URL}  baseline={litellm_url}  dau_vet={marker}"
    )

    catalog = get_catalog()
    results = [
        ModelResult(
            model=m.id,
            provider=m.provider,
            group=(group := group_of(catalog.providers[m.provider])),
            p95_limit_s=limit_of(group),
        )
        for m in models
    ]
    by_model = {k.model: k for k in results}

    pool = await asyncpg.create_pool(dev_database_url(), min_size=1, max_size=2)
    assert pool is not None
    user_id, tier = await create_user(pool, marker)
    adapter = SystemAdapter(
        base_url=litellm_url,
        api_key=settings.LITELLM_MASTER_KEY.get_secret_value(),
        timeout_s=float(settings.LLM_REQUEST_TIMEOUT_S),
    )

    try:
        async with httpx.AsyncClient(
            base_url=settings.PUBLIC_BASE_URL,
            headers=session_cookie(user_id, tier),
            verify=args.cacert or False,
            timeout=httpx.Timeout(MAX_RUN_S, read=MAX_RUN_S),
        ) as http:
            res = await http.post("/api/v1/conversations", json={"title": f"S2 {marker}"})
            res.raise_for_status()
            conversation_id = uuid.UUID(res.json()["id"])

            do = Measurement(http, adapter, conversation_id, on_am=args.im_lang)
            started = time.monotonic()
            for i in range(args.luot):
                # Access token sống `ACCESS_TOKEN_TTL_MIN` (15 phút, §11.2) còn
                # cả lượt đo này dài hơn thế. Làm mới ở đầu mỗi lượt là việc mà
                # một client thật làm bằng `POST /auth/refresh`; ở đây ký thẳng
                # rẻ hơn và không tiêu một refresh token nào.
                http.headers.update(session_cookie(user_id, tier))
                # Vòng tròn: một lượt chạy hết cả bốn model rồi mới sang lượt
                # sau — xem quyết định 3.
                for model in models:
                    kq = await do.one_run(i + 1, model, baseline_first=i % 2 == 1)
                    by_model[model.id].luot.append(kq)
                    if not args.im_lang:
                        print(
                            f"  luot {i + 1:>3}/{args.luot}  {model.id:<18}"
                            f"TTFT={s(kq.tong).strip():>8}s  baseline={s(kq.baseline).strip():>8}s"
                            f"{'  ✗ ' + kq.ly_do_hong if kq.ly_do_hong else ''}",
                            flush=True,
                        )
                    await asyncio.sleep(PAUSE_BETWEEN_RUNS_S)
            print(f"\nxong {args.luot * len(models)} lượt trong {time.monotonic() - started:.0f}s")
    finally:
        await adapter.close()
        if args.khong_don_dep:
            print(f"\n(giữ lại dữ liệu: user_id={user_id})")
        else:
            so_msg, so_ht = await cleanup(pool, user_id)
            print(f"\nđã dọn: {so_msg} message, {so_ht} hội thoại, 1 user")
        await pool.close()

    print_table(results, bo_qua)
    write_json(
        results,
        bo_qua,
        RESULTS_DIR / f"ttft-{date.today().isoformat()}.json",
        ghi_de=args.ghi_de,
    )
    return print_verdict(results, bo_qua)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--luot", type=int, default=RUNS, help=f"số lượt mỗi model (mặc định {RUNS})"
    )
    parser.add_argument(
        "--model", action="append", default=[], help="chỉ đo model này (lặp lại được)"
    )
    parser.add_argument(
        "--ghi-de",
        action="store_true",
        help="đè lên kết quả cùng ngày. Mặc định KHÔNG đè mà ghi sang "
        "ttft-{date}-{hhmm}.json (B-106)",
    )
    parser.add_argument(
        "--bo-qua",
        action="append",
        default=[],
        metavar="MODEL_ID",
        help=(
            "vẫn đo và vẫn in, nhưng không cho model này làm đỏ mã thoát. Dùng khi "
            "ngưỡng S2 của nó đã được chốt lại — KHÔNG phải để làm xanh một phép đo đỏ"
        ),
    )
    parser.add_argument("--cacert", default=None, help="CA của mkcert; không có thì bỏ kiểm TLS")
    parser.add_argument("--khong-don-dep", action="store_true", help="giữ user/hội thoại lại")
    parser.add_argument("--im-lang", action="store_true", help="không in tiến trình từng lượt")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
