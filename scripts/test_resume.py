#!/usr/bin/env python3
"""S3 — ngắt giữa lúc stream, nối lại, so byte-by-byte với `messages.content`.

KH tham chiếu: §2.3 (S3), §7.2 ②, §7.3, §7.4, C3, C4, C9 · tasks.md T-1.11.

**Đây là tiêu chí nghiệm thu của toàn bộ Phase 1.** §3 đặt cả kiến trúc lên một
câu: *câu trả lời phải sống độc lập với kết nối HTTP*. Script này là chỗ duy
nhất chứng minh câu đó đúng trên hạ tầng thật — model thật, Redis thật, Nginx
thật — chứ không phải trên một `RedisGia` biết trước câu trả lời.

    make test-resume        # hoặc: backend/.venv/bin/python scripts/test_resume.py

┌──────────────────────────────────────────────────────────────────────────┐
│  MỘT LƯỢT ĐO                                                             │
└──────────────────────────────────────────────────────────────────────────┘

    POST /conversations/{id}/messages        → 202 + stream_url
    GET  stream_url                          → đọc tới delta thứ N
    ✂ NGẮT CỨNG (đóng socket, không đọc hết)
    ngủ 2 s
    GET  stream_url  +  Last-Event-ID: <id event CUỐI CÙNG đã nhận>
    đọc tới `done`
    A + B  ==  messages.content ?            (so theo BYTE)

Sáu lượt: lượt 1 ngắt đúng ở **delta thứ 50** (con số trong "Việc cần làm" của
T-1.11), lượt 2–5 ngắt ở điểm **ngẫu nhiên**, lượt 6 ngắt **hai lần** trong
cùng một stream. Hạt giống ngẫu nhiên in ra ở đầu và nhận lại được bằng
`--seed`, nếu không một lượt đỏ sẽ không tái hiện được.

┌──────────────────────────────────────────────────────────────────────────┐
│  BỐN QUYẾT ĐỊNH CỦA PHÉP ĐO — MỖI CÁI LÀ MỘT CÁCH TỰ LỪA MÌNH ĐÃ TRÁNH   │
└──────────────────────────────────────────────────────────────────────────┘

**1. Chỉ nối `delta`, và chỉ nối event ĐÃ TRỌN VẸN.** Một khung SSE kết thúc
bằng dòng trống; ngắt giữa chừng thì phần dở dang bị **vứt**, và
`Last-Event-ID` giữ nguyên ở event trọn vẹn cuối cùng — đúng việc mà
`EventSource` của trình duyệt làm. Đếm cả phần dở dang là tự cho mình điểm cho
những byte chưa bao giờ tới nơi, và khi đó C3 (lặp) sẽ không bao giờ hiện ra.
`reasoning` **không** được nối: nó đi vào `messages.reasoning`, không vào
`content`, và model mặc định `deepseek-flash` có khai cờ `reasoning` — nối
nhầm là mọi lượt đều đỏ vì một lý do sai.

**2. So sánh bằng `.encode("utf-8")`, không bằng `==` của `str`.** T-1.11 ghi
"byte-by-byte" và đó không phải cách nói cho oai: C9 là ca chữ tiếng Việt bị
cắt giữa hai byte của một ký tự. Hai chuỗi `str` bằng nhau thì bytes cũng bằng
nhau, nhưng đọc kết quả theo byte là cách duy nhất báo được *lệch ở byte thứ
mấy*.

**3. Mọi lượt có TRẦN THỜI GIAN và TRẦN KÝ TỰ.** Đây là bài học B-88 áp cho
một script: hai dòng DoD của T-1.11 bắt phải **phá** consumer, mà cả hai kiểu
phá đều có thể làm treo thay vì đỏ — `$` có thể nuốt luôn event `done` (không
ai đóng stream nữa), `[cursor` biến vòng đuổi kịp thành vòng lặp nóng phát lại
mãi. Treo là kiểu đỏ không tự khai báo. Ở đây treo thành `FAIL … TREO` kèm số
ký tự đã nhận, tức vẫn trả lời đúng câu hỏi "thiếu hay lặp".

**4. Đi qua Nginx (`PUBLIC_BASE_URL`), không gọi thẳng `api:8000`.** Đường mà
người dùng thật đi có C1 (`proxy_buffering off`) và C2 (`proxy_read_timeout`)
trên đó. Một phép đo bỏ qua Nginx sẽ xanh trong khi trình duyệt im lặng.

**TLS**: chứng chỉ dev do `mkcert` cấp và CA của nó nằm trên máy Windows
(T-H1), không nằm trong trust store của WSL — nên mặc định script **không**
kiểm chứng chỉ, đúng như mọi `curl -k` của các DoD trước. Có CA thì truyền
`--cacert`.

**Dữ liệu**: script tự tạo user + hội thoại của riêng nó rồi **xoá sạch** ở
cuối (`--khong-don-dep` để giữ lại mà soi). Đó là bài học B-81: DoD của T-1.6
để lại ba user trong database dev và chúng vẫn còn tới hôm nay.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

# ──────────────────────────── hằng số của phép đo ───────────────────────────

#: Số lượt đo. DoD đòi in đúng `PASS 6/6`.
RUNS = 6

#: Lượt 1 ngắt ở đây — con số ghi thẳng trong "Việc cần làm" của T-1.11.
#: Các lượt sau ngẫu nhiên trong `[KHOANG_NGAT_NGAU_NHIEN]`.
FIRST_RUN_CUT_DELTA = 50
RANDOM_CUT_RANGE = (15, 120)

#: §7.4: `EventSource` của trình duyệt đợi ~3 s trước khi tự nối lại. T-1.11
#: chốt 2 s — đủ dài để worker sinh thêm một mảng chữ trong lúc đứt (nếu không
#: thì C4 chẳng có gì để lộ ra), đủ ngắn để stream chưa hết `STREAM_TTL_S`.
WAIT_BEFORE_RESUME_S = 2.0

#: Trần cho MỘT lượt. Một lượt bình thường (~800 từ, `deepseek-flash`) đo được
#: dưới 60 s; trần này là cái phanh cho ca treo, không phải phép đo hiệu năng
#: (đó là T-1.12). Xem quyết định 3 ở đầu file.
MAX_RUN_S = 150.0

#: Trần ký tự nhận được trong một lượt. `[cursor` biến vòng ① thành vòng lặp
#: nóng phát lại bản ghi cuối, nên không có trần này thì script nuốt hết RAM
#: trước khi kịp in `FAIL`. Rộng gấp nhiều lần một câu trả lời 800 từ.
MAX_CHARS = 200_000

#: Đặt vào `messages.content` của model. Xin dài để có đủ chỗ mà ngắt: một câu
#: trả lời 20 chữ thì "ngắt ở delta thứ 50" không tồn tại.
PROMPT = (
    "Viết một bài văn tiếng Việt CÓ DẤU, dài ít nhất 800 từ, về vai trò của "
    "sông Hồng trong đời sống của người dân đồng bằng Bắc Bộ. Chia thành nhiều "
    "đoạn, có mở bài và kết bài. Không dùng danh sách gạch đầu dòng, không "
    "dùng bảng. Viết liền mạch thành văn xuôi."
)

#: `.env` của repo — nguồn của `PUBLIC_BASE_URL` và `DEV_DATABASE_URL` khi
#: chạy từ WSL host (compose nạp file này cho container, host thì không).
ENV_FILE = REPO_ROOT / ".env"
DB_VAR = "DEV_DATABASE_URL"

_ASSIGNMENT_LINE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")
_TRAILING_COMMENT = re.compile(r"\s+#.*$")


def load_env() -> None:
    """Nạp `.env` vào `os.environ` — **không đè** biến đã export sẵn.

    Cùng việc mà `scripts/llm_env.sh` làm cho hai script LLM, viết lại bằng
    Python để `make test-resume` là **một** lệnh chứ không phải "nhớ source
    trước". Thô sơ có chủ ý: cắt ở dấu `=` đầu tiên và chỉ bỏ chú thích đứng
    sau khoảng trắng — đúng bài học B-44, nơi một chú thích cuối dòng sau giá
    trị rỗng biến thành chính giá trị đó.
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

from app.config.catalog import get_catalog  # noqa: E402
from app.config.settings import settings  # noqa: E402
from app.core.access_token import encode_access_token  # noqa: E402
from app.core.deps import SESSION_COOKIE_NAME  # noqa: E402
from app.db.models import UserRole, UserStatus  # noqa: E402


def dev_database_url() -> str:
    """URL Postgres nhìn từ HOST, trỏ vào database `scarlet` của dev.

    **Không** dùng `settings.DATABASE_URL`: nó ghi `postgres:5432`, một tên chỉ
    phân giải được bên trong network `internal` của compose (C17/C45), còn
    script này chạy ở WSL host. Cũng **không** dùng `TEST_DATABASE_URL`: nó trỏ
    vào `scarlet_test`, nơi `api` và `worker` không ghi một dòng nào — so
    byte-by-byte với một bảng rỗng là một phép đo luôn đỏ vì lý do sai.

    Thiếu biến thì **nổ ngay kèm tên biến** (A4), không lùi về một giá trị đoán.
    """
    url = os.environ.get(DB_VAR)
    if not url:
        raise SystemExit(
            f"thiếu {DB_VAR}. Đặt nó trong môi trường hoặc trong {ENV_FILE} "
            f"(mẫu ở .env.example), và bảo đảm `docker compose up -d postgres` "
            f"đã publish cổng 127.0.0.1:5432"
        )
    # asyncpg nhận DSN thuần, không hiểu phương ngữ `+asyncpg` của SQLAlchemy.
    return url.replace("postgresql+asyncpg://", "postgresql://")


# ═══════════════════════════ phân tích dòng SSE ════════════════════════════


@dataclass(slots=True)
class SseEvent:
    """Một khung SSE **đã trọn vẹn** (đã thấy dòng trống kết thúc)."""

    id: str | None
    event: str
    data: str


class SseReader:
    """Gom byte thành event, đúng luật WHATWG ở phần mà script này cần.

    Chỉ phát ra event khi đã gặp dòng trống. Phần dở dang nằm lại trong `_dem`
    và **biến mất** khi socket đóng — đó chính là hành vi phải mô phỏng, xem
    quyết định 1 ở đầu file.
    """

    __slots__ = ("_buffer", "_id", "_event", "_data")

    def __init__(self) -> None:
        self._buffer = ""
        self._reset()

    def _reset(self) -> None:
        self._id: str | None = None
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
                    out.append(SseEvent(self._id, self._event, "\n".join(self._data)))
                self._reset()
                continue
            if line.startswith(":"):
                continue  # comment `: ping` — không phải event, không đụng id
            name, _, value = line.partition(":")
            value = value[1:] if value.startswith(" ") else value
            if name == "id":
                self._id = value
            elif name == "event":
                self._event = value
            elif name == "data":
                self._data.append(value)
        return out


# ════════════════════════════ kết quả một lượt ═════════════════════════════


@dataclass(slots=True)
class RunResult:
    name: str
    passed: bool
    reason: str
    cuts: int
    received: int = 0
    in_db: int = 0
    mismatch_byte: int | None = None
    seconds: float = 0.0
    cut_points: list[int] = field(default_factory=list)


class HardCut(Exception):  # noqa: N818 - tên theo nghiệp vụ, không phải lỗi
    """Đã đọc đủ số delta cần thiết — đóng socket ngay tại đây."""


class Timeout(Exception):  # noqa: N818
    """Vượt `MAX_RUN_S` hoặc `MAX_CHARS` — treo cũng là đỏ."""


# ═════════════════════════════ máy đo một lượt ═════════════════════════════


class Measurement:
    """Một vòng đo hoàn chỉnh: hỏi, ngắt, nối lại, so."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        pool: asyncpg.Pool,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        on_am: bool,
    ) -> None:
        self._http = http
        self._pool = pool
        self._cid = conversation_id
        self._uid = user_id
        self._on_am = on_am

    def _log(self, *parts: object) -> None:
        if self._on_am:
            return
        print("   ", *parts, flush=True)

    async def run(self, name: str, cut_points: list[int]) -> RunResult:
        started = time.monotonic()
        deadline = started + MAX_RUN_S
        try:
            amid, stream_url = await self._send_question()
            text, attempts = await self._read_whole_stream(stream_url, cut_points, deadline)
        except Timeout as error:
            return RunResult(
                name=name,
                passed=False,
                reason=f"TREO — {error}",
                cuts=len(cut_points),
                seconds=time.monotonic() - started,
                cut_points=cut_points,
            )
        except httpx.HTTPError as error:
            return RunResult(
                name=name,
                passed=False,
                reason=f"LỖI HTTP — {type(error).__name__}: {error}",
                cuts=len(cut_points),
                seconds=time.monotonic() - started,
                cut_points=cut_points,
            )

        if attempts < len(cut_points):
            # Một lượt không ngắt được lần nào là một lượt KHÔNG đo gì cả, và
            # nó sẽ xanh — đúng cái "test luôn xanh là test vô dụng" mà cạm bẫy
            # của T-1.11 nói tới. Câu trả lời ngắn hơn điểm ngắt ⇒ đỏ, kèm số
            # thật để người đọc biết phải nới `PROMPT` hay hạ điểm ngắt.
            return RunResult(
                name=name,
                passed=False,
                reason=(
                    f"CHUA NGAT DU — dinh {len(cut_points)} lan, ngat duoc {attempts}: "
                    f"cau tra loi khong du delta (diem ngat {cut_points})"
                ),
                cuts=attempts,
                received=len(text.encode("utf-8")),
                seconds=time.monotonic() - started,
                cut_points=cut_points,
            )

        in_db = await self._read_content(amid)
        return self._compare(name, text, in_db, attempts, cut_points, time.monotonic() - started)

    async def _send_question(self) -> tuple[uuid.UUID, str]:
        """§7.2 ① — `202` + `stream_url`, không một byte chữ nào ở đây."""
        res = await self._http.post(
            f"/api/v1/conversations/{self._cid}/messages",
            json={"content": PROMPT},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        res.raise_for_status()
        body = res.json()
        return uuid.UUID(body["assistant_message_id"]), body["stream_url"]

    async def _read_whole_stream(
        self, stream_url: str, cut_points: list[int], deadline: float
    ) -> tuple[str, int]:
        """Đọc — ngắt — nối lại … cho tới `done`/`error`. Trả chữ đã nối và số lần ngắt."""
        parts: list[str] = []
        cursor: str | None = None
        so_delta = 0
        cuts = 0

        for index, cut_at in enumerate([*cut_points, None]):
            if index > 0:
                self._log(f"ngắt ở delta #{so_delta}, cursor={cursor}, chờ {WAIT_BEFORE_RESUME_S}s")
                await asyncio.sleep(WAIT_BEFORE_RESUME_S)
            text, cursor, so_delta, done = await self._one_connection(
                stream_url, cursor, so_delta, cut_at, deadline, len("".join(parts))
            )
            parts.append(text)
            if cut_at is not None:
                cuts += 1
            if done:
                break
        return "".join(parts), cuts

    async def _one_connection(
        self,
        stream_url: str,
        cursor: str | None,
        so_delta: int,
        cut_at: int | None,
        deadline: float,
        received_so_far: int,
    ) -> tuple[str, str | None, int, bool]:
        """Một kết nối SSE. `moc_ngat=None` ⇒ đọc tới hết.

        Trả về `(chữ nhận được, Last-Event-ID, tổng số delta, đã thấy done/error)`.
        """
        headers = {"Last-Event-ID": cursor} if cursor is not None else {}
        reader = SseReader()
        text: list[str] = []
        done = False

        try:
            async with self._http.stream("GET", stream_url, headers=headers) as res:
                res.raise_for_status()
                async for chunk in res.aiter_text():
                    if time.monotonic() > deadline:
                        raise Timeout(
                            f"quá {MAX_RUN_S:.0f}s, mới nhận "
                            f"{received_so_far + len(''.join(text))} ký tự"
                        )
                    for event in reader.feed(chunk):
                        # Cursor tiến theo event ĐÃ TRỌN VẸN, kể cả event không
                        # mang chữ — đó là thứ trình duyệt gửi lại (§7.4).
                        if event.id is not None:
                            cursor = event.id
                        if event.event == "delta":
                            text.append(json.loads(event.data)["t"])
                            so_delta += 1
                        elif event.event in ("done", "error"):
                            done = True
                            raise HardCut
                        if received_so_far + len("".join(text)) > MAX_CHARS:
                            raise Timeout(f"nhận quá {MAX_CHARS} ký tự — gần như chắc chắn là LẶP")
                        if cut_at is not None and so_delta >= cut_at:
                            raise HardCut
        except HardCut:
            pass
        return "".join(text), cursor, so_delta, done

    async def _read_content(self, message_id: uuid.UUID) -> str:
        """`messages.content` — nguồn sự thật (C5). Đọc SAU khi đã thấy `done`.

        Không có khe nào ở đây: `workers/generate.py` ghi Postgres **trước** rồi
        mới `XADD done`, nên thấy `done` nghĩa là hàng đã khép.
        """
        async with self._pool.acquire() as conn:
            content = await conn.fetchval("SELECT content FROM messages WHERE id = $1", message_id)
        return content or ""

    def _compare(
        self,
        name: str,
        received_text: str,
        in_db: str,
        cuts: int,
        cut_points: list[int],
        seconds: float,
    ) -> RunResult:
        """So theo BYTE và nói rõ **thiếu** hay **lặp** — xem quyết định 2."""
        b_received, b_db = received_text.encode("utf-8"), in_db.encode("utf-8")
        common = min(len(b_received), len(b_db))
        mismatch = next((i for i in range(common) if b_received[i] != b_db[i]), None)
        if mismatch is None and len(b_received) != len(b_db):
            mismatch = common

        if b_received == b_db and b_db:
            reason = f"{len(b_db)} byte khớp"
            passed = True
        elif not b_db:
            reason = "messages.content RỖNG — lượt sinh không ghi được gì"
            passed = False
        else:
            diff = len(b_received) - len(b_db)
            if diff < 0:
                remark = f"THIẾU {-diff} byte"
            elif diff > 0:
                remark = f"LẶP {diff} byte"
            else:
                remark = "KHÁC NỘI DUNG (cùng độ dài)"
            reason = f"{remark}, lệch từ byte #{mismatch}"
            passed = False

        return RunResult(
            name=name,
            passed=passed,
            reason=reason,
            cuts=cuts,
            received=len(b_received),
            in_db=len(b_db),
            mismatch_byte=mismatch,
            seconds=seconds,
            cut_points=cut_points,
        )


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

    `tier_name` để trống ⇒ DEFAULT `'free'`, tier do migration 0001 seed —
    và trả nó ra để `session_cookie` khỏi phải gõ lại tên tier (A3).
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            # `status='active'` từ T-3.1c: cookie phiên mang claim `active`
            # (xem `session_cookie`), và hàng trong DB phải nói cùng một câu.
            "INSERT INTO users (email, password_hash, status) "
            "VALUES ($1, $2, 'active') RETURNING id, tier_name",
            f"{marker}@scarlet.test",
            "khong-phai-hash-that",
        )
    assert row is not None
    assert isinstance(row["id"], uuid.UUID)
    return row["id"], str(row["tier_name"])


async def cleanup(pool: asyncpg.Pool, user_id: uuid.UUID) -> tuple[int, int]:
    """Xoá **cứng** mọi thứ script vừa tạo. Bài học B-81.

    Thứ tự bắt buộc: `conversations.active_leaf_id` trỏ vào `messages`, nên
    phải gỡ con trỏ trước rồi mới xoá message, rồi mới xoá hội thoại.
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


# ══════════════════════════════════ chạy ═══════════════════════════════════


def cut_points_for_run(i: int, rng: random.Random) -> list[int]:
    """Lượt 1: đúng delta thứ 50. Lượt 2–5: ngẫu nhiên. Lượt 6: ngắt HAI lần."""
    if i == 0:
        return [FIRST_RUN_CUT_DELTA]
    if i == RUNS - 1:
        point = rng.randint(*RANDOM_CUT_RANGE)
        return [point, point + rng.randint(*RANDOM_CUT_RANGE)]
    return [rng.randint(*RANDOM_CUT_RANGE)]


async def run(args: argparse.Namespace) -> int:
    rng = random.Random(args.seed)
    model = args.model or _default_model()
    marker = f"t111-{uuid.uuid4().hex[:8]}"

    print(f"seed={args.seed}  model={model}  base={settings.PUBLIC_BASE_URL}  dau_vet={marker}")

    pool = await asyncpg.create_pool(dev_database_url(), min_size=1, max_size=2)
    assert pool is not None
    user_id, tier = await create_user(pool, marker)
    results: list[RunResult] = []

    try:
        async with httpx.AsyncClient(
            base_url=settings.PUBLIC_BASE_URL,
            headers=session_cookie(user_id, tier),
            verify=args.cacert or False,
            timeout=httpx.Timeout(MAX_RUN_S, read=MAX_RUN_S),
        ) as http:
            res = await http.post(
                "/api/v1/conversations",
                json={"title": f"S3 {marker}", "default_model": model},
            )
            res.raise_for_status()
            conversation_id = uuid.UUID(res.json()["id"])

            do = Measurement(http, pool, conversation_id, user_id, on_am=args.im_lang)
            for i in range(RUNS):
                # Access token sống `ACCESS_TOKEN_TTL_MIN` (15 phút, §11.2) còn
                # cả lượt đo này dài hơn thế. Làm mới ở đầu mỗi lượt là việc mà
                # một client thật làm bằng `POST /auth/refresh`; ở đây ký thẳng
                # rẻ hơn và không tiêu một refresh token nào.
                http.headers.update(session_cookie(user_id, tier))
                scores = cut_points_for_run(i, rng)
                name = f"luot {i + 1}/{RUNS} (ngat {len(scores)} lan tai {scores})"
                print(f"\n▶ {name}", flush=True)
                kq = await do.run(name, scores)
                results.append(kq)
                print(
                    f"{'✓ PASS' if kq.passed else '✗ FAIL'}  {kq.reason}  "
                    f"(nhan {kq.received} byte / db {kq.in_db} byte, {kq.seconds:.1f}s)",
                    flush=True,
                )
    finally:
        if args.khong_don_dep:
            print(f"\n(giữ lại dữ liệu: user_id={user_id})")
        else:
            so_msg, so_ht = await cleanup(pool, user_id)
            print(f"\nđã dọn: {so_msg} message, {so_ht} hội thoại, 1 user")
        await pool.close()

    return print_summary(results)


def _default_model() -> str:
    default = next((m for m in get_catalog().models if m.default and m.enabled), None)
    if default is None:
        raise SystemExit("catalog không có model `default` nào đang bật (§9.2)")
    return default.id


def print_summary(results: list[RunResult]) -> int:
    passed = sum(1 for k in results if k.passed)
    print("\n" + "═" * 74)
    for k in results:
        verdict = "PASS" if k.passed else "FAIL"
        print(f"  {verdict}  {k.name}: {k.reason}")
    print("═" * 74)
    # Dòng này là thứ DoD của T-1.11 đọc. `PASS 6/6` hay `FAIL 4/6`, một dòng.
    print(f"{'PASS' if passed == len(results) else 'FAIL'} {passed}/{len(results)}")
    return 0 if passed == len(results) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seed", type=int, default=random.randrange(2**31), help="hạt giống điểm ngắt"
    )
    parser.add_argument("--model", default=None, help="mặc định: model `default` của catalog")
    parser.add_argument("--cacert", default=None, help="CA của mkcert; không có thì bỏ kiểm TLS")
    parser.add_argument("--khong-don-dep", action="store_true", help="giữ user/hội thoại lại")
    parser.add_argument("--im-lang", action="store_true", help="không in tiến trình từng lượt")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
