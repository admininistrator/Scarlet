"""Rate limit theo IP (§10.6) — B-127, B-131, T-2.5.

Ba tầng được kiểm riêng vì chúng hỏng theo ba kiểu khác nhau:

1. `dia_chi_ip` — đọc nhầm IP thì cả 15–20 người dùng chung một bộ đếm (hoặc
   tệ hơn: ai cũng tự khai IP của mình và hạn mức thành trang trí).
2. `dem_va_kiem` — đếm sai hoặc quên TTL thì hạn mức "3 mỗi giờ" biến thành
   "3 mãi mãi".
3. dependency — mã lỗi/`Retry-After` sai thì FE không nói được câu đúng.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import Depends, FastAPI, Request
from httpx import ASGITransport, AsyncClient

from app.core import ratelimit
from app.core.errors import ApiError, ApiErrorCode
from app.core.ratelimit import (
    CUA_SO_GIO_S,
    CUA_SO_PHUT_S,
    HEADER_IP_THAT,
    IP_KHONG_RO,
    dem_va_kiem,
    dia_chi_ip,
    gioi_han_auth,
    gioi_han_gui_email,
    ip_key,
)


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
