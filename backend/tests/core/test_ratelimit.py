"""Rate limit của §10.6 — ba lớp, ba kiểu hỏng khác nhau (T-2.5, T-2.9).

Nửa trên: lớp **theo IP** (B-127, B-131, B-133, T-2.5).

1. `dia_chi_ip` — đọc nhầm IP thì cả 15–20 người dùng chung một bộ đếm (hoặc
   tệ hơn: ai cũng tự khai IP của mình và hạn mức thành trang trí).
2. `dem_va_kiem` — đếm sai hoặc quên TTL thì hạn mức "3 mỗi giờ" biến thành
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
    CUA_SO_GIO_S,
    CUA_SO_PHUT_S,
    GROUP_CHAT,
    HEADER_IP_THAT,
    IP_KHONG_RO,
    KetQuaXo,
    dem_va_kiem,
    dia_chi_ip,
    gioi_han_auth,
    gioi_han_chat,
    gioi_han_gui_email,
    ip_key,
    nha_ghe_sinh,
    nhan_ghe_sinh,
    stream_slot_key,
    take_token,
    user_key,
)
from app.db.repositories import GenerationStates


class _RedisDem:
    """Redis trong bộ nhớ — đúng ba lệnh của `dem_va_kiem`.

    `expire` tôn trọng `nx=True` thật sự (chỉ đặt khi khoá chưa có TTL) chứ
    không đặt bừa: đó chính là tính chất mà docstring của `ratelimit.py` dựa
    vào để cửa sổ cố định không bị đẩy hạn vô hạn, nên một stub dễ tính hơn
    Redis thật sẽ làm phép kiểm mất nghĩa (bài học B-102).
    """

    def __init__(self) -> None:
        self.dem: dict[str, int] = {}
        self.ttl_da_dat: dict[str, int] = {}
        self.no_ra = False

    async def incr(self, name: str) -> int:
        if self.no_ra:
            raise ConnectionError("redis chet (gia lap)")
        self.dem[name] = self.dem.get(name, 0) + 1
        return self.dem[name]

    async def expire(self, name: str, time: int, *, nx: bool = False) -> bool:
        if self.no_ra:
            raise ConnectionError("redis chet (gia lap)")
        if nx and name in self.ttl_da_dat:
            return False
        self.ttl_da_dat[name] = time
        return True

    async def ttl(self, name: str) -> int:
        if name not in self.dem:
            return -2
        return self.ttl_da_dat.get(name, -1)


@pytest.fixture
def redis_dem(monkeypatch: pytest.MonkeyPatch) -> _RedisDem:
    gia = _RedisDem()
    monkeypatch.setattr("app.core.ratelimit.get_redis", lambda: gia)
    return gia


# ───────────────────────────── `dia_chi_ip` ─────────────────────────────────


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


def test_ip_lay_tu_header_cua_nginx() -> None:
    request = _request({HEADER_IP_THAT: "203.0.113.7"}, client=("172.18.0.5", 40000))

    assert dia_chi_ip(request) == "203.0.113.7"


def test_header_thang_request_client() -> None:
    """Không có header thì `request.client` chỉ là IP của Nginx — mọi người
    dùng sẽ chung một bộ đếm. Có header thì header phải thắng."""
    khong_header = _request(client=("172.18.0.5", 40000))

    assert dia_chi_ip(khong_header) == "172.18.0.5"


def test_khong_co_gi_thi_ve_xo_chung() -> None:
    assert dia_chi_ip(_request()) == IP_KHONG_RO


def test_header_rong_khong_duoc_coi_la_mot_ip() -> None:
    request = _request({HEADER_IP_THAT: "   "}, client=("172.18.0.5", 40000))

    assert dia_chi_ip(request) == "172.18.0.5"


def test_khoa_tach_theo_nhom_route() -> None:
    """§10.6 cho mỗi route một hạn mức riêng ⇒ mỗi route một bộ đếm riêng."""
    assert ip_key("forgot-password", "1.2.3.4") != ip_key("resend-verification", "1.2.3.4")
    assert ip_key("forgot-password", "1.2.3.4").startswith(ratelimit.RL_IP_PREFIX)


# ──────────────────────────── `dem_va_kiem` ─────────────────────────────────


async def test_dem_tang_dan_va_chi_vuot_sau_khi_qua_tran() -> None:
    redis = _RedisDem()
    key = ip_key("forgot-password", "1.2.3.4")

    ket_qua = [await dem_va_kiem(redis, key, gioi_han=3, cua_so_s=CUA_SO_GIO_S) for _ in range(4)]

    assert [k.so_lan for k in ket_qua] == [1, 2, 3, 4]
    assert [k.vuot for k in ket_qua] == [False, False, False, True]


async def test_lan_dau_dat_ttl_bang_cua_so() -> None:
    redis = _RedisDem()
    key = ip_key("forgot-password", "1.2.3.4")

    await dem_va_kiem(redis, key, gioi_han=3, cua_so_s=CUA_SO_GIO_S)

    assert redis.ttl_da_dat[key] == CUA_SO_GIO_S


async def test_goi_tiep_KHONG_day_han_ra_xa() -> None:
    """`EXPIRE ... NX`: cửa sổ đứng yên kể từ lượt đầu.

    Nếu mỗi lượt gọi đặt lại TTL thì kẻ gọi liên tục sẽ giữ cửa sổ mở mãi và
    bộ đếm không bao giờ về 0 — "3 mỗi giờ" thành "3 mãi mãi".
    """
    redis = _RedisDem()
    key = ip_key("forgot-password", "1.2.3.4")
    await dem_va_kiem(redis, key, gioi_han=3, cua_so_s=CUA_SO_GIO_S)
    redis.ttl_da_dat[key] = 12  # giả lập "đã trôi gần hết cửa sổ"

    await dem_va_kiem(redis, key, gioi_han=3, cua_so_s=CUA_SO_GIO_S)

    assert redis.ttl_da_dat[key] == 12


async def test_khoa_mat_ttl_thi_luot_sau_tu_va() -> None:
    """Ca duy nhất mà cặp INCR/EXPIRE không nguyên tử hỏng: khoá không TTL.

    Lượt gọi kế tiếp phải vá được nó, nếu không một IP bị khoá vĩnh viễn.
    """
    redis = _RedisDem()
    key = ip_key("forgot-password", "1.2.3.4")
    await redis.incr(key)  # INCR chạy, EXPIRE thì không (tiến trình chết)

    await dem_va_kiem(redis, key, gioi_han=3, cua_so_s=CUA_SO_GIO_S)

    assert redis.ttl_da_dat[key] == CUA_SO_GIO_S


async def test_retry_after_lay_tu_ttl_con_lai() -> None:
    redis = _RedisDem()
    key = ip_key("forgot-password", "1.2.3.4")
    for _ in range(3):
        await dem_va_kiem(redis, key, gioi_han=3, cua_so_s=CUA_SO_GIO_S)
    redis.ttl_da_dat[key] = 417

    ket_qua = await dem_va_kiem(redis, key, gioi_han=3, cua_so_s=CUA_SO_GIO_S)

    assert ket_qua.vuot
    assert ket_qua.retry_after_s == 417


async def test_retry_after_khong_bao_gio_la_so_khong_hoac_am() -> None:
    """`TTL` trả `-1`/`-2` là hai ca có thật; đưa số đó vào `Retry-After` là
    bảo client "thử lại cách đây một giây"."""
    redis = _RedisDem()
    key = ip_key("forgot-password", "1.2.3.4")
    for _ in range(4):
        await dem_va_kiem(redis, key, gioi_han=3, cua_so_s=CUA_SO_GIO_S)
    redis.ttl_da_dat.pop(key)  # TTL → -1

    ket_qua = await dem_va_kiem(redis, key, gioi_han=3, cua_so_s=CUA_SO_GIO_S)

    assert ket_qua.retry_after_s >= 1


# ───────────────────────── dependency trong app thật ────────────────────────


@pytest.fixture
def app_gia() -> FastAPI:
    """Một app tí hon mang đúng khung lỗi §18 của app thật."""
    from app.core import errors

    app = FastAPI()
    errors.register(app)

    @app.post("/thu-3-moi-gio", dependencies=[Depends(gioi_han_gui_email("thu"))])
    async def thu() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/auth-5-moi-phut", dependencies=[Depends(gioi_han_auth("au"))])
    async def au() -> dict[str, str]:
        return {"status": "ok"}

    return app


@pytest.fixture
async def client(app_gia: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app_gia), base_url="https://localhost"
    ) as http:
        yield http


@pytest.mark.usefixtures("redis_dem")
async def test_qua_tran_tra_429_kem_retry_after(client: AsyncClient) -> None:
    for _ in range(3):
        assert (await client.post("/thu-3-moi-gio")).status_code == 200

    resp = await client.post("/thu-3-moi-gio")

    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == ApiErrorCode.RATE_LIMITED
    assert resp.json()["error"]["details"]["retry_after"] == CUA_SO_GIO_S
    assert resp.headers["Retry-After"] == str(CUA_SO_GIO_S)


@pytest.mark.usefixtures("redis_dem")
async def test_hai_ip_khac_nhau_khong_dung_chung_bo_dem(client: AsyncClient) -> None:
    """Cạm bẫy thật của rate limit theo IP: đếm nhầm theo IP của Nginx thì
    người thứ tư trong giờ bị chặn vì ba người khác."""
    for _ in range(3):
        await client.post("/thu-3-moi-gio", headers={HEADER_IP_THAT: "203.0.113.1"})

    resp = await client.post("/thu-3-moi-gio", headers={HEADER_IP_THAT: "203.0.113.2"})

    assert resp.status_code == 200


@pytest.mark.usefixtures("redis_dem")
async def test_hai_route_khac_nhom_dem_rieng(client: AsyncClient) -> None:
    for _ in range(3):
        await client.post("/thu-3-moi-gio")

    assert (await client.post("/auth-5-moi-phut")).status_code == 200


@pytest.mark.usefixtures("redis_dem")
async def test_nhom_auth_dung_cua_so_phut(client: AsyncClient) -> None:
    for _ in range(5):
        assert (await client.post("/auth-5-moi-phut")).status_code == 200

    resp = await client.post("/auth-5-moi-phut")

    assert resp.status_code == 429
    assert resp.headers["Retry-After"] == str(CUA_SO_PHUT_S)


async def test_redis_chet_tra_503_chu_khong_cho_qua(
    client: AsyncClient, redis_dem: _RedisDem
) -> None:
    """Không hỏi được Redis nghĩa là KHÔNG BIẾT IP này đã gọi mấy lần — cho
    qua là gỡ lớp chống dò đúng lúc hệ thống đang hỏng (cùng lý lẽ `deps.py`)."""
    redis_dem.no_ra = True

    resp = await client.post("/thu-3-moi-gio")

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == ApiErrorCode.SERVICE_UNAVAILABLE


@pytest.mark.usefixtures("redis_dem")
async def test_han_muc_doc_tu_settings_luc_goi(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hạn mức là cấu hình (A3), không phải hằng đóng băng lúc import."""
    monkeypatch.setattr(
        "app.config.settings.settings.RATE_LIMIT_EMAIL_IP_PER_HOUR", 1, raising=False
    )

    assert (await client.post("/thu-3-moi-gio")).status_code == 200
    assert (await client.post("/thu-3-moi-gio")).status_code == 429


async def test_apierror_cua_dependency_la_ApiError(redis_dem: _RedisDem) -> None:
    """Gọi thẳng dependency: 429 phải là `ApiError` (có `code`), không phải
    `HTTPException` trần — nếu không FE chỉ đọc được status."""
    redis_dem.dem[ip_key("truc-tiep", "9.9.9.9")] = 99
    kiem = gioi_han_gui_email("truc-tiep")

    with pytest.raises(ApiError) as loi:
        await kiem(_request({HEADER_IP_THAT: "9.9.9.9"}))

    assert loi.value.code == ApiErrorCode.RATE_LIMITED
    assert loi.value.status_code == 429


# ══════════════════════════════════════════════════════════════════════════
#  T-2.9 — lớp THEO USER (token bucket) và TRẦN ĐỒNG THỜI
# ══════════════════════════════════════════════════════════════════════════
#
# Ranh giới của bộ test này, nói thẳng ra để không ai đọc nhầm nó:
#
# Hai script Lua **không** được dịch sang Python ở đây. Một bản dịch là một
# bản hiện thực thứ hai, và test chạy trên bản dịch sẽ xanh cả khi bản Lua
# thật đã hỏng — tệ hơn không có test. Vì vậy `_RedisKichBan` chỉ **trả lời
# theo kịch bản** và ghi lại ARGV nó nhận.
#
# Thứ kiểm được ở đây: ánh xạ kết quả → header/mã lỗi, luật chọn ghế để nhả
# (`_ghe_can_nha`, Python thuần), và ai gọi ai. Thứ KHÔNG kiểm được: phép nạp
# lại của xô và tính nguyên tử — hai thứ đó chỉ có Redis thật mới chứng minh
# được, và đó là việc của `scripts/test_ratelimit.sh` (DoD dòng 1 và 2).


class _RedisKichBan:
    """Redis trả lời theo kịch bản — xem khối chú thích ngay trên."""

    def __init__(self) -> None:
        self.bucket: list[int] = [1, 19, 0, 3000]
        self.slot: list[int] = [1, 1]
        self.zset: dict[str, dict[str, float]] = {}
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.no_ra = False

    async def eval(self, script: str, numkeys: int, *args: object) -> list[int]:
        if self.no_ra:
            raise ConnectionError("redis chet (gia lap)")
        if script is ratelimit.LUA_TOKEN_BUCKET:
            self.calls.append(("bucket", args))
            return list(self.bucket)
        if script is ratelimit.LUA_GIU_GHE:
            self.calls.append(("slot", args))
            return list(self.slot)
        raise AssertionError("script Lua khong biet")

    async def zrange(
        self, name: str, start: int, end: int, *, withscores: bool = False
    ) -> list[tuple[str, float]]:
        if self.no_ra:
            raise ConnectionError("redis chet (gia lap)")
        assert withscores
        return sorted(self.zset.get(name, {}).items(), key=lambda item: item[1])

    async def zrem(self, name: str, *members: str) -> int:
        if self.no_ra:
            raise ConnectionError("redis chet (gia lap)")
        ghe = self.zset.get(name, {})
        return sum(1 for member in members if ghe.pop(member, None) is not None)


class _RepoKichBan:
    """`MessageRepository` giả — chỉ có câu hỏi mà trần đồng thời cần."""

    def __init__(self, known: set[uuid.UUID], in_flight: set[uuid.UUID]) -> None:
        self.states = GenerationStates(known=frozenset(known), in_flight=frozenset(in_flight))
        self.da_hoi: list[list[uuid.UUID]] = []

    async def generation_states(
        self, message_ids: Sequence[uuid.UUID], *, user_id: uuid.UUID
    ) -> GenerationStates:
        self.da_hoi.append(list(message_ids))
        return self.states


@pytest.fixture
def redis_kich_ban(monkeypatch: pytest.MonkeyPatch) -> _RedisKichBan:
    gia = _RedisKichBan()
    monkeypatch.setattr("app.core.ratelimit.get_redis", lambda: gia)
    return gia


# ──────────────────────── khoá: tách đúng trục ────────────────────────────


def test_khoa_theo_user_tach_theo_nhom_va_theo_nguoi() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()

    assert user_key(GROUP_CHAT, a).startswith(ratelimit.RL_USER_PREFIX)
    assert user_key(GROUP_CHAT, a) != user_key(GROUP_CHAT, b)
    assert user_key(GROUP_CHAT, a) != user_key("upload", a)


def test_khoa_ghe_va_khoa_xo_khong_dam_vao_nhau() -> None:
    """Hai cấu trúc dữ liệu khác nhau (hash và zset) trên cùng một user. Trùng
    khoá là một `WRONGTYPE` ở đúng lúc tệ nhất."""
    uid = uuid.uuid4()

    assert stream_slot_key(uid) != user_key(GROUP_CHAT, uid)
    assert stream_slot_key(uid).startswith(ratelimit.RL_STREAMS_PREFIX)


# ─────────────────────── quy đổi mili-giây → Retry-After ───────────────────


@pytest.mark.parametrize(
    ("milli", "cho_ra"),
    [(0, 1), (1, 1), (999, 1), (1000, 1), (1001, 2), (3000, 3), (3001, 4)],
)
def test_retry_after_lam_tron_len_va_khong_bao_gio_bang_0(milli: int, cho_ra: int) -> None:
    """Làm tròn xuống là mời client thử lại vào đúng lúc vẫn còn bị chặn; `0`
    thì tệ hơn — nó nghĩa là "thử ngay đi", tức một vòng lặp bận."""
    assert ratelimit._giay_len(milli) == cho_ra


# ──────────────────────────── `take_token` ────────────────────────────────


async def test_take_token_doc_dung_bon_so_cua_script(redis_kich_ban: _RedisKichBan) -> None:
    redis_kich_ban.bucket = [1, 7, 0, 4500]

    ket_qua = await take_token(
        redis_kich_ban,  # type: ignore[arg-type]
        "k",
        capacity=20,
        window_s=60,
        now=1000.5,
    )

    assert (ket_qua.allowed, ket_qua.limit, ket_qua.remaining) == (True, 20, 7)
    assert ket_qua.reset_s == 5, "4500 ms làm tròn lên"
    assert ket_qua.retry_after_s == 0, "chưa bị chặn thì không có gì để chờ"


async def test_take_token_truyen_now_giu_phan_thap_phan(redis_kich_ban: _RedisKichBan) -> None:
    """`int(now)` sẽ cắt mất phần lẻ và mọi phép nạp lại dưới một giây thành 0
    — xô 20/phút nạp một token mỗi 3 s, nên đó là sai số tích luỹ thật."""
    await take_token(
        redis_kich_ban,  # type: ignore[arg-type]
        "k",
        capacity=20,
        window_s=60,
        now=1000.25,
    )

    ten, argv = redis_kich_ban.calls[0]
    assert ten == "bucket"
    assert float(str(argv[3])) == 1000.25


async def test_take_token_bi_chan_thi_co_retry_after(redis_kich_ban: _RedisKichBan) -> None:
    redis_kich_ban.bucket = [0, 0, 2100, 60000]

    ket_qua = await take_token(
        redis_kich_ban,  # type: ignore[arg-type]
        "k",
        capacity=20,
        window_s=60,
        now=1.0,
    )

    assert ket_qua.allowed is False
    assert ket_qua.retry_after_s == 3, "2100 ms làm tròn lên"


def test_header_retry_after_chi_xuat_hien_khi_da_bi_chan() -> None:
    """`Retry-After` trên một response `202` nghĩa là "hãy thử lại" — sai hẳn
    nghĩa. Ba header `X-RateLimit-*` thì luôn có: FE cần biết mình sắp hết hạn
    mức TRƯỚC khi hết."""
    qua = KetQuaXo(allowed=True, limit=20, remaining=19, retry_after_s=0, reset_s=3)
    chan = KetQuaXo(allowed=False, limit=20, remaining=0, retry_after_s=3, reset_s=60)

    assert ratelimit.HEADER_RETRY_AFTER not in qua.headers()
    assert chan.headers()[ratelimit.HEADER_RETRY_AFTER] == "3"
    for header in (ratelimit.HEADER_LIMIT, ratelimit.HEADER_REMAINING, ratelimit.HEADER_RESET):
        assert header in qua.headers()
        assert header in chan.headers()


# ───────────────────── dependency token bucket theo user ──────────────────


def _app_chat(uid: uuid.UUID) -> FastAPI:
    app = FastAPI()
    errors.register(app)
    app.dependency_overrides[get_current_user_id] = lambda: uid

    @app.post("/chat", dependencies=[Depends(gioi_han_chat())])
    async def _chat() -> dict[str, bool]:
        return {"ok": True}

    return app


async def _goi_chat(app: FastAPI) -> Response:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as http:
        return await http.post("/chat")


async def test_dependency_dan_header_len_response_thanh_cong(
    redis_kich_ban: _RedisKichBan,
) -> None:
    redis_kich_ban.bucket = [1, 12, 0, 24000]

    resp = await _goi_chat(_app_chat(uuid.uuid4()))

    assert resp.status_code == 200
    assert resp.headers[ratelimit.HEADER_LIMIT] == str(settings.RATE_LIMIT_CHAT_PER_MIN)
    assert resp.headers[ratelimit.HEADER_REMAINING] == "12"
    assert resp.headers[ratelimit.HEADER_RESET] == "24"
    assert ratelimit.HEADER_RETRY_AFTER not in resp.headers


async def test_dependency_het_token_tra_429_kem_retry_after(
    redis_kich_ban: _RedisKichBan,
) -> None:
    """DoD dòng 1: request vượt hạn mức trả `429` với `Retry-After` là số giây."""
    redis_kich_ban.bucket = [0, 0, 3000, 60000]

    resp = await _goi_chat(_app_chat(uuid.uuid4()))

    assert resp.status_code == 429
    assert resp.headers["retry-after"] == "3"
    loi = resp.json()["error"]
    assert loi["code"] == ApiErrorCode.RATE_LIMITED.value
    assert loi["details"]["retry_after"] == 3
    assert loi["details"]["limit"] == settings.RATE_LIMIT_CHAT_PER_MIN


async def test_dependency_dung_dung_khoa_cua_nguoi_goi(
    redis_kich_ban: _RedisKichBan,
) -> None:
    uid = uuid.uuid4()

    await _goi_chat(_app_chat(uid))

    # `eval(script, numkeys, key, *ARGV)` ⇒ fake nhận `(key, ARGV…)`.
    _, argv = redis_kich_ban.calls[0]
    assert argv[0] == user_key(GROUP_CHAT, uid)


async def test_dependency_redis_chet_thi_503_chu_khong_cho_qua(
    redis_kich_ban: _RedisKichBan,
) -> None:
    """Cùng lý lẽ đã chốt bốn lần: không hỏi được nghĩa là không biết."""
    redis_kich_ban.no_ra = True

    resp = await _goi_chat(_app_chat(uuid.uuid4()))

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == ApiErrorCode.SERVICE_UNAVAILABLE.value


async def test_dependency_doc_han_muc_luc_goi_chu_khong_luc_import(
    redis_kich_ban: _RedisKichBan, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_CHAT_PER_MIN", 1)

    resp = await _goi_chat(_app_chat(uuid.uuid4()))

    _, argv = redis_kich_ban.calls[0]
    assert argv[1] == "1", "sức chứa của xô lấy từ Settings tại thời điểm gọi"
    assert resp.headers[ratelimit.HEADER_LIMIT] == "1"


# ───────────────── trần đồng thời: luật chọn ghế để nhả ───────────────────


async def test_ghe_dang_sinh_thi_giu_lai() -> None:
    mid = uuid.uuid4()
    repo = _RepoKichBan(known={mid}, in_flight={mid})

    can_nha = await ratelimit._ghe_can_nha(
        repo,  # type: ignore[arg-type]
        user_id=uuid.uuid4(),
        members=[(str(mid), 0.0)],
        now=10_000.0,
    )

    assert can_nha == []


async def test_ghe_da_khep_thi_nha_NGAY_du_con_rat_moi() -> None:
    """Đây là vế làm DoD dòng 4 chạy: một lượt sinh xong là ghế trống ngay,
    không phải đợi hết `PHANTOM_GRACE_S`."""
    mid = uuid.uuid4()
    repo = _RepoKichBan(known={mid}, in_flight=set())

    can_nha = await ratelimit._ghe_can_nha(
        repo,  # type: ignore[arg-type]
        user_id=uuid.uuid4(),
        members=[(str(mid), 9_999.0)],
        now=10_000.0,
    )

    assert can_nha == [str(mid)]


async def test_ghe_postgres_chua_biet_va_con_moi_thi_GIU(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Khe giữa `ZADD` và `commit()`: hàng `messages` đã ghi nhưng chưa commit
    nên Postgres chưa thấy. Nhả ở đây là cho lượt thứ tư đi qua — đúng cái đua
    mà DoD dòng 2 bắt phải không có."""
    mid = uuid.uuid4()
    repo = _RepoKichBan(known=set(), in_flight=set())

    can_nha = await ratelimit._ghe_can_nha(
        repo,  # type: ignore[arg-type]
        user_id=uuid.uuid4(),
        members=[(str(mid), 10_000.0 - ratelimit.PHANTOM_GRACE_S + 1)],
        now=10_000.0,
    )

    assert can_nha == []


async def test_ghe_postgres_chua_biet_va_qua_gia_thi_nha() -> None:
    """Transaction đã rollback sau khi giữ ghế ⇒ một ghế trỏ vào hư không.
    Không có vế này thì nó khoá người dùng cho tới `_tuoi_toi_da_ghe()`."""
    mid = uuid.uuid4()
    repo = _RepoKichBan(known=set(), in_flight=set())

    can_nha = await ratelimit._ghe_can_nha(
        repo,  # type: ignore[arg-type]
        user_id=uuid.uuid4(),
        members=[(str(mid), 10_000.0 - ratelimit.PHANTOM_GRACE_S)],
        now=10_000.0,
    )

    assert can_nha == [str(mid)]


async def test_member_khong_phai_uuid_thi_nha_ngay() -> None:
    repo = _RepoKichBan(known=set(), in_flight=set())

    can_nha = await ratelimit._ghe_can_nha(
        repo,  # type: ignore[arg-type]
        user_id=uuid.uuid4(),
        members=[("rac", 10_000.0)],
        now=10_000.0,
    )

    assert can_nha == ["rac"]
    assert repo.da_hoi == [[]], "không hỏi Postgres về một chuỗi không phải id"


# ──────────────────────── `nhan_ghe_sinh` / `nha_ghe_sinh` ────────────────


async def test_chua_cham_tran_thi_KHONG_hoi_postgres(redis_kich_ban: _RedisKichBan) -> None:
    """Đường đi thường phải là đúng một lệnh Redis: 15–20 người dùng nhân với
    mỗi lượt chat một truy vấn thừa là một cái giá trả mãi mãi."""
    uid = uuid.uuid4()
    repo = _RepoKichBan(known=set(), in_flight=set())
    redis_kich_ban.zset[stream_slot_key(uid)] = {str(uuid.uuid4()): 1.0}

    await nhan_ghe_sinh(repo, user_id=uid, message_id=uuid.uuid4())  # type: ignore[arg-type]

    assert repo.da_hoi == []
    assert [ten for ten, _ in redis_kich_ban.calls] == ["slot"]


async def test_cham_tran_thi_hoi_postgres_va_truyen_ghe_can_nha_vao_script(
    redis_kich_ban: _RedisKichBan,
) -> None:
    uid = uuid.uuid4()
    con_sinh, da_khep = uuid.uuid4(), uuid.uuid4()
    la = uuid.uuid4()
    repo = _RepoKichBan(known={con_sinh, da_khep}, in_flight={con_sinh})
    redis_kich_ban.zset[stream_slot_key(uid)] = {
        str(con_sinh): 9_000.0,
        str(da_khep): 9_000.0,
        str(la): 0.0,
    }
    moi = uuid.uuid4()

    await nhan_ghe_sinh(repo, user_id=uid, message_id=moi)  # type: ignore[arg-type]

    assert repo.da_hoi and set(repo.da_hoi[0]) == {con_sinh, da_khep, la}
    _, argv = redis_kich_ban.calls[0]
    assert argv[4] == str(moi), "ghế mới là member được cấp"
    assert set(argv[5:]) == {str(da_khep), str(la)}, "một cái đã khép, một cái quá già"


async def test_het_ghe_thi_429_TOO_MANY_STREAMS_khong_kem_retry_after(
    redis_kich_ban: _RedisKichBan,
) -> None:
    """DoD dòng 3. Không `Retry-After` vì không ai biết model sinh xong lúc
    nào — đoán một con số là nói dối bằng một header client sẽ tin."""
    redis_kich_ban.slot = [0, 3]
    repo = _RepoKichBan(known=set(), in_flight=set())

    with pytest.raises(ApiError) as loi:
        await nhan_ghe_sinh(  # type: ignore[arg-type]
            repo, user_id=uuid.uuid4(), message_id=uuid.uuid4()
        )

    assert loi.value.status_code == 429
    assert loi.value.code is ApiErrorCode.TOO_MANY_STREAMS
    assert loi.value.details == {"limit": settings.MAX_CONCURRENT_STREAMS, "active": 3}
    assert not (loi.value.headers or {}).get(ratelimit.HEADER_RETRY_AFTER)


async def test_tran_dong_thoi_redis_chet_thi_503(redis_kich_ban: _RedisKichBan) -> None:
    redis_kich_ban.no_ra = True
    repo = _RepoKichBan(known=set(), in_flight=set())

    with pytest.raises(ApiError) as loi:
        await nhan_ghe_sinh(  # type: ignore[arg-type]
            repo, user_id=uuid.uuid4(), message_id=uuid.uuid4()
        )

    assert loi.value.status_code == 503
    assert loi.value.code is ApiErrorCode.SERVICE_UNAVAILABLE


async def test_tuoi_toi_da_ghe_phu_duoc_luot_sinh_dai_nhat() -> None:
    """Suy ra từ hai giới hạn đã có, không phải một biến `.env` thứ ba: một
    lượt sinh nằm hàng đợi tối đa `REAPER_QUEUED_STALE_S` rồi sinh tối đa
    `GENERATE_TIMEOUT_S`. Nhỏ hơn tổng đó là cắt ghế của một lượt còn sống."""
    assert ratelimit._tuoi_toi_da_ghe() >= (
        settings.REAPER_QUEUED_STALE_S + settings.GENERATE_TIMEOUT_S
    )
    assert ratelimit._tuoi_toi_da_ghe() > ratelimit.PHANTOM_GRACE_S


async def test_nha_ghe_goi_zrem_dung_khoa(redis_kich_ban: _RedisKichBan) -> None:
    uid, mid = uuid.uuid4(), uuid.uuid4()
    redis_kich_ban.zset[stream_slot_key(uid)] = {str(mid): 1.0}

    await nha_ghe_sinh(user_id=uid, message_id=mid)

    assert redis_kich_ban.zset[stream_slot_key(uid)] == {}


async def test_nha_ghe_nuot_loi_redis(redis_kich_ban: _RedisKichBan) -> None:
    """Ném ở đây sẽ thay `503 ENQUEUE_FAILED` (câu đúng) bằng một câu về Redis
    mà người dùng không làm gì được."""
    redis_kich_ban.no_ra = True

    await nha_ghe_sinh(user_id=uuid.uuid4(), message_id=uuid.uuid4())
