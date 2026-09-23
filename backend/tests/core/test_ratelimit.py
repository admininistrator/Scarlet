"""Rate limit của §10.6 — ba lớp, ba kiểu hỏng khác nhau (T-2.5, T-2.9).

Nửa trên: lớp **theo IP** (B-127, B-131, B-133, T-2.5).

1. `client_ip` — đọc nhầm IP thì cả 15–20 người dùng chung một bộ đếm (hoặc
   tệ hơn: ai cũng tự khai IP của mình và hạn mức thành trang trí).
2. `count_and_check` — đếm sai hoặc quên TTL thì hạn mức "3 mỗi giờ" biến thành
   "3 mãi mãi".
3. dependency — mã lỗi/`Retry-After` sai thì FE không nói được câu đúng.

Nửa dưới: lớp **theo user** (token bucket) và **trần đồng thời** (T-2.9,
B-85) — ranh giới của phần đó ghi ngay trước khối test tương ứng.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence

import pytest
from fastapi import Depends, FastAPI, Request
from httpx import ASGITransport, AsyncClient, Response

from app.config.settings import settings
from app.core import errors, ratelimit
from app.core.deps import get_current_user_id
from app.core.errors import ApiError, ApiErrorCode
from app.core.ratelimit import (
    GROUP_CHAT,
    HOUR_WINDOW_S,
    MINUTE_WINDOW_S,
    REAL_IP_HEADER,
    UNKNOWN_IP,
    BucketResult,
    acquire_generation_seat,
    auth_limit,
    chat_limit,
    client_ip,
    count_and_check,
    email_send_limit,
    ip_key,
    release_generation_seat,
    stream_slot_key,
    take_token,
    user_key,
)
from app.db.repositories import GenerationStates


class _CountingRedis:
    """Redis trong bộ nhớ — đúng ba lệnh của `count_and_check`.

    `expire` tôn trọng `nx=True` thật sự (chỉ đặt khi khoá chưa có TTL) chứ
    không đặt bừa: đó chính là tính chất mà docstring của `ratelimit.py` dựa
    vào để cửa sổ cố định không bị đẩy hạn vô hạn, nên một stub dễ tính hơn
    Redis thật sẽ làm phép kiểm mất nghĩa (bài học B-102).
    """

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.ttl_set: dict[str, int] = {}
        self.raises = False

    async def incr(self, name: str) -> int:
        if self.raises:
            raise ConnectionError("redis chet (gia lap)")
        self.counts[name] = self.counts.get(name, 0) + 1
        return self.counts[name]

    async def expire(self, name: str, time: int, *, nx: bool = False) -> bool:
        if self.raises:
            raise ConnectionError("redis chet (gia lap)")
        if nx and name in self.ttl_set:
            return False
        self.ttl_set[name] = time
        return True

    async def ttl(self, name: str) -> int:
        if name not in self.counts:
            return -2
        return self.ttl_set.get(name, -1)


@pytest.fixture
def counting_redis(monkeypatch: pytest.MonkeyPatch) -> _CountingRedis:
    fake = _CountingRedis()
    monkeypatch.setattr("app.core.ratelimit.get_redis", lambda: fake)
    return fake


# ───────────────────────────── `client_ip` ─────────────────────────────────


def _request(
    headers: dict[str, str] | None = None, client: tuple[str, int] | None = None
) -> Request:
    scope: dict[str, object] = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/auth/logout",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
    }
    if client is not None:
        scope["client"] = client
    return Request(scope)  # type: ignore[arg-type]


def test_ip_taken_from_nginx_header() -> None:
    request = _request({REAL_IP_HEADER: "203.0.113.7"}, client=("172.18.0.5", 40000))

    assert client_ip(request) == "203.0.113.7"


def test_header_beats_request_client() -> None:
    """Không có header thì `request.client` chỉ là IP của Nginx — mọi người
    dùng sẽ chung một bộ đếm. Có header thì header phải thắng."""
    no_header = _request(client=("172.18.0.5", 40000))

    assert client_ip(no_header) == "172.18.0.5"


def test_nothing_given_falls_to_shared_bucket() -> None:
    assert client_ip(_request()) == UNKNOWN_IP


def test_empty_header_is_not_an_ip() -> None:
    request = _request({REAL_IP_HEADER: "   "}, client=("172.18.0.5", 40000))

    assert client_ip(request) == "172.18.0.5"


def test_keys_split_by_route_group() -> None:
    """§10.6 cho mỗi route một hạn mức riêng ⇒ mỗi route một bộ đếm riêng."""
    assert ip_key("forgot-password", "1.2.3.4") != ip_key("resend-verification", "1.2.3.4")
    assert ip_key("forgot-password", "1.2.3.4").startswith(ratelimit.RL_IP_PREFIX)


# ──────────────────────────── `count_and_check` ─────────────────────────────────


async def test_count_grows_and_only_exceeds_past_cap() -> None:
    redis = _CountingRedis()
    key = ip_key("forgot-password", "1.2.3.4")

    result = [await count_and_check(redis, key, limit=3, window_s=HOUR_WINDOW_S) for _ in range(4)]

    assert [k.count for k in result] == [1, 2, 3, 4]
    assert [k.exceeded for k in result] == [False, False, False, True]


async def test_first_call_sets_ttl_to_window() -> None:
    redis = _CountingRedis()
    key = ip_key("forgot-password", "1.2.3.4")

    await count_and_check(redis, key, limit=3, window_s=HOUR_WINDOW_S)

    assert redis.ttl_set[key] == HOUR_WINDOW_S


async def test_further_calls_do_NOT_push_deadline_out() -> None:
    """`EXPIRE ... NX`: cửa sổ đứng yên kể từ lượt đầu.

    Nếu mỗi lượt gọi đặt lại TTL thì kẻ gọi liên tục sẽ giữ cửa sổ mở mãi và
    bộ đếm không bao giờ về 0 — "3 mỗi giờ" thành "3 mãi mãi".
    """
    redis = _CountingRedis()
    key = ip_key("forgot-password", "1.2.3.4")
    await count_and_check(redis, key, limit=3, window_s=HOUR_WINDOW_S)
    redis.ttl_set[key] = 12  # giả lập "đã trôi gần hết cửa sổ"

    await count_and_check(redis, key, limit=3, window_s=HOUR_WINDOW_S)

    assert redis.ttl_set[key] == 12


async def test_key_losing_ttl_self_heals_next_call() -> None:
    """Ca duy nhất mà cặp INCR/EXPIRE không nguyên tử hỏng: khoá không TTL.

    Lượt gọi kế tiếp phải vá được nó, nếu không một IP bị khoá vĩnh viễn.
    """
    redis = _CountingRedis()
    key = ip_key("forgot-password", "1.2.3.4")
    await redis.incr(key)  # INCR chạy, EXPIRE thì không (tiến trình chết)

    await count_and_check(redis, key, limit=3, window_s=HOUR_WINDOW_S)

    assert redis.ttl_set[key] == HOUR_WINDOW_S


async def test_retry_after_from_remaining_ttl() -> None:
    redis = _CountingRedis()
    key = ip_key("forgot-password", "1.2.3.4")
    for _ in range(3):
        await count_and_check(redis, key, limit=3, window_s=HOUR_WINDOW_S)
    redis.ttl_set[key] = 417

    result = await count_and_check(redis, key, limit=3, window_s=HOUR_WINDOW_S)

    assert result.exceeded
    assert result.retry_after_s == 417


async def test_retry_after_never_zero_or_negative() -> None:
    """`TTL` trả `-1`/`-2` là hai ca có thật; đưa số đó vào `Retry-After` là
    bảo client "thử lại cách đây một giây"."""
    redis = _CountingRedis()
    key = ip_key("forgot-password", "1.2.3.4")
    for _ in range(4):
        await count_and_check(redis, key, limit=3, window_s=HOUR_WINDOW_S)
    redis.ttl_set.pop(key)  # TTL → -1

    result = await count_and_check(redis, key, limit=3, window_s=HOUR_WINDOW_S)

    assert result.retry_after_s >= 1


# ───────────────────────── dependency trong app thật ────────────────────────


@pytest.fixture
def fake_app() -> FastAPI:
    """Một app tí hon mang đúng khung lỗi §18 của app thật."""
    from app.core import errors

    app = FastAPI()
    errors.register(app)

    @app.post("/thu-3-moi-gio", dependencies=[Depends(email_send_limit("thu"))])
    async def attempt_call() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/auth-5-moi-phut", dependencies=[Depends(auth_limit("au"))])
    async def au() -> dict[str, str]:
        return {"status": "ok"}

    return app


@pytest.fixture
async def client(fake_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=fake_app), base_url="https://localhost"
    ) as http:
        yield http


@pytest.mark.usefixtures("counting_redis")
async def test_over_cap_429_with_retry_after(client: AsyncClient) -> None:
    for _ in range(3):
        assert (await client.post("/thu-3-moi-gio")).status_code == 200

    resp = await client.post("/thu-3-moi-gio")

    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == ApiErrorCode.RATE_LIMITED
    assert resp.json()["error"]["details"]["retry_after"] == HOUR_WINDOW_S
    assert resp.headers["Retry-After"] == str(HOUR_WINDOW_S)


@pytest.mark.usefixtures("counting_redis")
async def test_two_ips_do_not_share_counter(client: AsyncClient) -> None:
    """Cạm bẫy thật của rate limit theo IP: đếm nhầm theo IP của Nginx thì
    người thứ tư trong giờ bị chặn vì ba người khác."""
    for _ in range(3):
        await client.post("/thu-3-moi-gio", headers={REAL_IP_HEADER: "203.0.113.1"})

    resp = await client.post("/thu-3-moi-gio", headers={REAL_IP_HEADER: "203.0.113.2"})

    assert resp.status_code == 200


@pytest.mark.usefixtures("counting_redis")
async def test_two_routes_in_different_groups_count_separately(client: AsyncClient) -> None:
    for _ in range(3):
        await client.post("/thu-3-moi-gio")

    assert (await client.post("/auth-5-moi-phut")).status_code == 200


@pytest.mark.usefixtures("counting_redis")
async def test_auth_group_uses_minute_window(client: AsyncClient) -> None:
    for _ in range(5):
        assert (await client.post("/auth-5-moi-phut")).status_code == 200

    resp = await client.post("/auth-5-moi-phut")

    assert resp.status_code == 429
    assert resp.headers["Retry-After"] == str(MINUTE_WINDOW_S)


async def test_dead_redis_503_not_let_through(
    client: AsyncClient, counting_redis: _CountingRedis
) -> None:
    """Không hỏi được Redis nghĩa là KHÔNG BIẾT IP này đã gọi mấy lần — cho
    qua là gỡ lớp chống dò đúng lúc hệ thống đang hỏng (cùng lý lẽ `deps.py`)."""
    counting_redis.raises = True

    resp = await client.post("/thu-3-moi-gio")

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == ApiErrorCode.SERVICE_UNAVAILABLE


@pytest.mark.usefixtures("counting_redis")
async def test_limit_read_from_settings_at_call(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hạn mức là cấu hình (A3), không phải hằng đóng băng lúc import."""
    monkeypatch.setattr(
        "app.config.settings.settings.RATE_LIMIT_EMAIL_IP_PER_HOUR", 1, raising=False
    )

    assert (await client.post("/thu-3-moi-gio")).status_code == 200
    assert (await client.post("/thu-3-moi-gio")).status_code == 429


async def test_dependency_apierror_is_ApiError(counting_redis: _CountingRedis) -> None:
    """Gọi thẳng dependency: 429 phải là `ApiError` (có `code`), không phải
    `HTTPException` trần — nếu không FE chỉ đọc được status."""
    counting_redis.counts[ip_key("truc-tiep", "9.9.9.9")] = 99
    check = email_send_limit("truc-tiep")

    with pytest.raises(ApiError) as error:
        await check(_request({REAL_IP_HEADER: "9.9.9.9"}))

    assert error.value.code == ApiErrorCode.RATE_LIMITED
    assert error.value.status_code == 429


# ══════════════════════════════════════════════════════════════════════════
#  T-2.9 — lớp THEO USER (token bucket) và TRẦN ĐỒNG THỜI
# ══════════════════════════════════════════════════════════════════════════
#
# Ranh giới của bộ test này, nói thẳng ra để không ai đọc nhầm nó:
#
# Hai script Lua **không** được dịch sang Python ở đây. Một bản dịch là một
# bản hiện thực thứ hai, và test chạy trên bản dịch sẽ xanh cả khi bản Lua
# thật đã hỏng — tệ hơn không có test. Vì vậy `_ScriptedRedis` chỉ **trả lời
# theo kịch bản** và ghi lại ARGV nó nhận.
#
# Thứ kiểm được ở đây: ánh xạ kết quả → header/mã lỗi, luật chọn ghế để nhả
# (`_seats_to_release`, Python thuần), và ai gọi ai. Thứ KHÔNG kiểm được: phép nạp
# lại của xô và tính nguyên tử — hai thứ đó chỉ có Redis thật mới chứng minh
# được, và đó là việc của `scripts/test_ratelimit.sh` (DoD dòng 1 và 2).


class _ScriptedRedis:
    """Redis trả lời theo kịch bản — xem khối chú thích ngay trên."""

    def __init__(self) -> None:
        self.bucket: list[int] = [1, 19, 0, 3000]
        self.slot: list[int] = [1, 1]
        self.zset: dict[str, dict[str, float]] = {}
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.raises = False

    async def eval(self, script: str, numkeys: int, *args: object) -> list[int]:
        if self.raises:
            raise ConnectionError("redis chet (gia lap)")
        if script is ratelimit.LUA_TOKEN_BUCKET:
            self.calls.append(("bucket", args))
            return list(self.bucket)
        if script is ratelimit.LUA_ACQUIRE_SEAT:
            self.calls.append(("slot", args))
            return list(self.slot)
        raise AssertionError("script Lua khong biet")

    async def zrange(
        self, name: str, start: int, end: int, *, withscores: bool = False
    ) -> list[tuple[str, float]]:
        if self.raises:
            raise ConnectionError("redis chet (gia lap)")
        assert withscores
        return sorted(self.zset.get(name, {}).items(), key=lambda item: item[1])

    async def zrem(self, name: str, *members: str) -> int:
        if self.raises:
            raise ConnectionError("redis chet (gia lap)")
        seats = self.zset.get(name, {})
        return sum(1 for member in members if seats.pop(member, None) is not None)


class _ScriptedRepo:
    """`MessageRepository` giả — chỉ có câu hỏi mà trần đồng thời cần."""

    def __init__(self, known: set[uuid.UUID], in_flight: set[uuid.UUID]) -> None:
        self.states = GenerationStates(known=frozenset(known), in_flight=frozenset(in_flight))
        self.queried: list[list[uuid.UUID]] = []

    async def generation_states(
        self, message_ids: Sequence[uuid.UUID], *, user_id: uuid.UUID
    ) -> GenerationStates:
        self.queried.append(list(message_ids))
        return self.states


@pytest.fixture
def scripted_redis(monkeypatch: pytest.MonkeyPatch) -> _ScriptedRedis:
    fake = _ScriptedRedis()
    monkeypatch.setattr("app.core.ratelimit.get_redis", lambda: fake)
    return fake


# ──────────────────────── khoá: tách đúng trục ────────────────────────────


def test_per_user_keys_split_by_group_and_person() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()

    assert user_key(GROUP_CHAT, a).startswith(ratelimit.RL_USER_PREFIX)
    assert user_key(GROUP_CHAT, a) != user_key(GROUP_CHAT, b)
    assert user_key(GROUP_CHAT, a) != user_key("upload", a)


def test_seat_key_and_bucket_key_do_not_collide() -> None:
    """Hai cấu trúc dữ liệu khác nhau (hash và zset) trên cùng một user. Trùng
    khoá là một `WRONGTYPE` ở đúng lúc tệ nhất."""
    uid = uuid.uuid4()

    assert stream_slot_key(uid) != user_key(GROUP_CHAT, uid)
    assert stream_slot_key(uid).startswith(ratelimit.RL_STREAMS_PREFIX)


# ─────────────────────── quy đổi mili-giây → Retry-After ───────────────────


@pytest.mark.parametrize(
    ("milli", "expected_wait"),
    [(0, 1), (1, 1), (999, 1), (1000, 1), (1001, 2), (3000, 3), (3001, 4)],
)
def test_retry_after_rounds_up_and_is_never_0(milli: int, expected_wait: int) -> None:
    """Làm tròn xuống là mời client thử lại vào đúng lúc vẫn còn bị chặn; `0`
    thì tệ hơn — nó nghĩa là "thử ngay đi", tức một vòng lặp bận."""
    assert ratelimit._ceil_seconds(milli) == expected_wait


# ──────────────────────────── `take_token` ────────────────────────────────


async def test_take_token_reads_scripts_four_numbers(scripted_redis: _ScriptedRedis) -> None:
    scripted_redis.bucket = [1, 7, 0, 4500]

    result = await take_token(
        scripted_redis,  # type: ignore[arg-type]
        "k",
        capacity=20,
        window_s=60,
        now=1000.5,
    )

    assert (result.allowed, result.limit, result.remaining) == (True, 20, 7)
    assert result.reset_s == 5, "4500 ms làm tròn lên"
    assert result.retry_after_s == 0, "chưa bị chặn thì không có gì để chờ"


async def test_take_token_passes_now_keeping_decimals(scripted_redis: _ScriptedRedis) -> None:
    """`int(now)` sẽ cắt mất phần lẻ và mọi phép nạp lại dưới một giây thành 0
    — xô 20/phút nạp một token mỗi 3 s, nên đó là sai số tích luỹ thật."""
    await take_token(
        scripted_redis,  # type: ignore[arg-type]
        "k",
        capacity=20,
        window_s=60,
        now=1000.25,
    )

    name, argv = scripted_redis.calls[0]
    assert name == "bucket"
    assert float(str(argv[3])) == 1000.25


async def test_take_token_blocked_has_retry_after(scripted_redis: _ScriptedRedis) -> None:
    scripted_redis.bucket = [0, 0, 2100, 60000]

    result = await take_token(
        scripted_redis,  # type: ignore[arg-type]
        "k",
        capacity=20,
        window_s=60,
        now=1.0,
    )

    assert result.allowed is False
    assert result.retry_after_s == 3, "2100 ms làm tròn lên"


def test_retry_after_header_only_when_blocked() -> None:
    """`Retry-After` trên một response `202` nghĩa là "hãy thử lại" — sai hẳn
    nghĩa. Ba header `X-RateLimit-*` thì luôn có: FE cần biết mình sắp hết hạn
    mức TRƯỚC khi hết."""
    passed = BucketResult(allowed=True, limit=20, remaining=19, retry_after_s=0, reset_s=3)
    blocked = BucketResult(allowed=False, limit=20, remaining=0, retry_after_s=3, reset_s=60)

    assert ratelimit.HEADER_RETRY_AFTER not in passed.headers()
    assert blocked.headers()[ratelimit.HEADER_RETRY_AFTER] == "3"
    for header in (ratelimit.HEADER_LIMIT, ratelimit.HEADER_REMAINING, ratelimit.HEADER_RESET):
        assert header in passed.headers()
        assert header in blocked.headers()


# ───────────────────── dependency token bucket theo user ──────────────────


def _app_chat(uid: uuid.UUID) -> FastAPI:
    app = FastAPI()
    errors.register(app)
    app.dependency_overrides[get_current_user_id] = lambda: uid

    @app.post("/chat", dependencies=[Depends(chat_limit())])
    async def _chat() -> dict[str, bool]:
        return {"ok": True}

    return app


async def _call_chat(app: FastAPI) -> Response:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as http:
        return await http.post("/chat")


async def test_dependency_sticks_headers_on_success_response(
    scripted_redis: _ScriptedRedis,
) -> None:
    scripted_redis.bucket = [1, 12, 0, 24000]

    resp = await _call_chat(_app_chat(uuid.uuid4()))

    assert resp.status_code == 200
    assert resp.headers[ratelimit.HEADER_LIMIT] == str(settings.RATE_LIMIT_CHAT_PER_MIN)
    assert resp.headers[ratelimit.HEADER_REMAINING] == "12"
    assert resp.headers[ratelimit.HEADER_RESET] == "24"
    assert ratelimit.HEADER_RETRY_AFTER not in resp.headers


async def test_dependency_out_of_tokens_429_with_retry_after(
    scripted_redis: _ScriptedRedis,
) -> None:
    """DoD dòng 1: request vượt hạn mức trả `429` với `Retry-After` là số giây."""
    scripted_redis.bucket = [0, 0, 3000, 60000]

    resp = await _call_chat(_app_chat(uuid.uuid4()))

    assert resp.status_code == 429
    assert resp.headers["retry-after"] == "3"
    error = resp.json()["error"]
    assert error["code"] == ApiErrorCode.RATE_LIMITED.value
    assert error["details"]["retry_after"] == 3
    assert error["details"]["limit"] == settings.RATE_LIMIT_CHAT_PER_MIN


async def test_dependency_uses_callers_key(
    scripted_redis: _ScriptedRedis,
) -> None:
    uid = uuid.uuid4()

    await _call_chat(_app_chat(uid))

    # `eval(script, numkeys, key, *ARGV)` ⇒ fake nhận `(key, ARGV…)`.
    _, argv = scripted_redis.calls[0]
    assert argv[0] == user_key(GROUP_CHAT, uid)


async def test_dependency_dead_redis_503_not_let_through(
    scripted_redis: _ScriptedRedis,
) -> None:
    """Cùng lý lẽ đã chốt bốn lần: không hỏi được nghĩa là không biết."""
    scripted_redis.raises = True

    resp = await _call_chat(_app_chat(uuid.uuid4()))

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == ApiErrorCode.SERVICE_UNAVAILABLE.value


async def test_dependency_reads_limit_at_call_not_import(
    scripted_redis: _ScriptedRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_CHAT_PER_MIN", 1)

    resp = await _call_chat(_app_chat(uuid.uuid4()))

    _, argv = scripted_redis.calls[0]
    assert argv[1] == "1", "sức chứa của xô lấy từ Settings tại thời điểm gọi"
    assert resp.headers[ratelimit.HEADER_LIMIT] == "1"


# ───────────────── trần đồng thời: luật chọn ghế để nhả ───────────────────


async def test_generating_seat_is_kept() -> None:
    mid = uuid.uuid4()
    repo = _ScriptedRepo(known={mid}, in_flight={mid})

    to_release = await ratelimit._seats_to_release(
        repo,  # type: ignore[arg-type]
        user_id=uuid.uuid4(),
        members=[(str(mid), 0.0)],
        now=10_000.0,
    )

    assert to_release == []


async def test_settled_seat_released_NOW_even_if_very_fresh() -> None:
    """Đây là vế làm DoD dòng 4 chạy: một lượt sinh xong là ghế trống ngay,
    không phải đợi hết `PHANTOM_GRACE_S`."""
    mid = uuid.uuid4()
    repo = _ScriptedRepo(known={mid}, in_flight=set())

    to_release = await ratelimit._seats_to_release(
        repo,  # type: ignore[arg-type]
        user_id=uuid.uuid4(),
        members=[(str(mid), 9_999.0)],
        now=10_000.0,
    )

    assert to_release == [str(mid)]


async def test_seat_unknown_to_postgres_and_fresh_is_KEPT(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Khe giữa `ZADD` và `commit()`: hàng `messages` đã ghi nhưng chưa commit
    nên Postgres chưa thấy. Nhả ở đây là cho lượt thứ tư đi qua — đúng cái đua
    mà DoD dòng 2 bắt phải không có."""
    mid = uuid.uuid4()
    repo = _ScriptedRepo(known=set(), in_flight=set())

    to_release = await ratelimit._seats_to_release(
        repo,  # type: ignore[arg-type]
        user_id=uuid.uuid4(),
        members=[(str(mid), 10_000.0 - ratelimit.PHANTOM_GRACE_S + 1)],
        now=10_000.0,
    )

    assert to_release == []


async def test_seat_unknown_to_postgres_and_too_old_is_released() -> None:
    """Transaction đã rollback sau khi giữ ghế ⇒ một ghế trỏ vào hư không.
    Không có vế này thì nó khoá người dùng cho tới `_seat_max_age()`."""
    mid = uuid.uuid4()
    repo = _ScriptedRepo(known=set(), in_flight=set())

    to_release = await ratelimit._seats_to_release(
        repo,  # type: ignore[arg-type]
        user_id=uuid.uuid4(),
        members=[(str(mid), 10_000.0 - ratelimit.PHANTOM_GRACE_S)],
        now=10_000.0,
    )

    assert to_release == [str(mid)]


async def test_non_uuid_member_released_immediately() -> None:
    repo = _ScriptedRepo(known=set(), in_flight=set())

    to_release = await ratelimit._seats_to_release(
        repo,  # type: ignore[arg-type]
        user_id=uuid.uuid4(),
        members=[("rac", 10_000.0)],
        now=10_000.0,
    )

    assert to_release == ["rac"]
    assert repo.queried == [[]], "không hỏi Postgres về một chuỗi không phải id"


# ──────────────────────── `acquire_generation_seat` / `release_generation_seat` ────────────────


async def test_below_cap_does_NOT_ask_postgres(scripted_redis: _ScriptedRedis) -> None:
    """Đường đi thường phải là đúng một lệnh Redis: 15–20 người dùng nhân với
    mỗi lượt chat một truy vấn thừa là một cái giá trả mãi mãi."""
    uid = uuid.uuid4()
    repo = _ScriptedRepo(known=set(), in_flight=set())
    scripted_redis.zset[stream_slot_key(uid)] = {str(uuid.uuid4()): 1.0}

    await acquire_generation_seat(repo, user_id=uid, message_id=uuid.uuid4())  # type: ignore[arg-type]

    assert repo.queried == []
    assert [name for name, _ in scripted_redis.calls] == ["slot"]


async def test_at_cap_asks_postgres_and_passes_seats_to_release_to_script(
    scripted_redis: _ScriptedRedis,
) -> None:
    uid = uuid.uuid4()
    still_generating, settled = uuid.uuid4(), uuid.uuid4()
    unknown = uuid.uuid4()
    repo = _ScriptedRepo(known={still_generating, settled}, in_flight={still_generating})
    scripted_redis.zset[stream_slot_key(uid)] = {
        str(still_generating): 9_000.0,
        str(settled): 9_000.0,
        str(unknown): 0.0,
    }
    fresh = uuid.uuid4()

    await acquire_generation_seat(repo, user_id=uid, message_id=fresh)  # type: ignore[arg-type]

    assert repo.queried and set(repo.queried[0]) == {still_generating, settled, unknown}
    _, argv = scripted_redis.calls[0]
    assert argv[4] == str(fresh), "ghế mới là member được cấp"
    assert set(argv[5:]) == {str(settled), str(unknown)}, "một cái đã khép, một cái quá già"


async def test_no_seats_429_TOO_MANY_STREAMS_without_retry_after(
    scripted_redis: _ScriptedRedis,
) -> None:
    """DoD dòng 3. Không `Retry-After` vì không ai biết model sinh xong lúc
    nào — đoán một con số là nói dối bằng một header client sẽ tin."""
    scripted_redis.slot = [0, 3]
    repo = _ScriptedRepo(known=set(), in_flight=set())

    with pytest.raises(ApiError) as error:
        await acquire_generation_seat(  # type: ignore[arg-type]
            repo, user_id=uuid.uuid4(), message_id=uuid.uuid4()
        )

    assert error.value.status_code == 429
    assert error.value.code is ApiErrorCode.TOO_MANY_STREAMS
    assert error.value.details == {"limit": settings.MAX_CONCURRENT_STREAMS, "active": 3}
    assert not (error.value.headers or {}).get(ratelimit.HEADER_RETRY_AFTER)


async def test_concurrency_cap_dead_redis_is_503(scripted_redis: _ScriptedRedis) -> None:
    scripted_redis.raises = True
    repo = _ScriptedRepo(known=set(), in_flight=set())

    with pytest.raises(ApiError) as error:
        await acquire_generation_seat(  # type: ignore[arg-type]
            repo, user_id=uuid.uuid4(), message_id=uuid.uuid4()
        )

    assert error.value.status_code == 503
    assert error.value.code is ApiErrorCode.SERVICE_UNAVAILABLE


async def test_seat_max_age_covers_longest_generation() -> None:
    """Suy ra từ hai giới hạn đã có, không phải một biến `.env` thứ ba: một
    lượt sinh nằm hàng đợi tối đa `REAPER_QUEUED_STALE_S` rồi sinh tối đa
    `GENERATE_TIMEOUT_S`. Nhỏ hơn tổng đó là cắt ghế của một lượt còn sống."""
    assert ratelimit._seat_max_age() >= (
        settings.REAPER_QUEUED_STALE_S + settings.GENERATE_TIMEOUT_S
    )
    assert ratelimit._seat_max_age() > ratelimit.PHANTOM_GRACE_S


async def test_release_seat_calls_zrem_on_right_key(scripted_redis: _ScriptedRedis) -> None:
    uid, mid = uuid.uuid4(), uuid.uuid4()
    scripted_redis.zset[stream_slot_key(uid)] = {str(mid): 1.0}

    await release_generation_seat(user_id=uid, message_id=mid)

    assert scripted_redis.zset[stream_slot_key(uid)] == {}


async def test_release_seat_swallows_redis_error(scripted_redis: _ScriptedRedis) -> None:
    """Ném ở đây sẽ thay `503 ENQUEUE_FAILED` (câu đúng) bằng một câu về Redis
    mà người dùng không làm gì được."""
    scripted_redis.raises = True

    await release_generation_seat(user_id=uuid.uuid4(), message_id=uuid.uuid4())
