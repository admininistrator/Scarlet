"""Vòng nối lại của tiến trình worker — B-196.

KH tham chiếu: Phụ lục C · CLAUDE.md A3 · tasks.md B-196, rà P2 2026-09-20.

Bộ test này canh **bốn** hành vi, và ba trong bốn là hành vi *không* làm gì —
đó là chỗ một vòng `while True` dễ sai nhất:

1. mất Redis ⇒ dựng lại (thứ B-196 sinh ra để sửa);
2. SIGTERM ⇒ **thoát**, không dựng lại (một worker không tắt được còn tệ hơn
   lỗi nó đang vá — `docker compose stop` sẽ treo);
3. lỗi lập trình ⇒ **để nổ**, không dựng lại (quay vòng vô tận mà không ai
   đọc log là cách giấu một bug hiệu quả nhất);
4. `close()` treo ⇒ **không** kéo theo cả vòng lặp (nếu không thì ta chỉ đổi
   một kiểu treo lấy một kiểu treo khác — xem docstring `run.py`).

`asyncio.run` và `time.sleep` đều bị thay: bộ test đo *quyết định* của vòng
lặp, không đo đồng hồ. Thật ra chỉ cần một trong hai để chạy nhanh, nhưng thay
cả hai giữ cho một lần đổi backoff mặc định không làm bộ test này chậm đi.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.workers import run as run_module


class _FakeWorker:
    """Đủ bề mặt cho `_close_with_timeout`: chỉ một `close()`."""

    def __init__(self, *, close_treo: bool = False, close_no: Exception | None = None) -> None:
        self.close_treo = close_treo
        self.close_no = close_no
        self.da_dong = False

    async def close(self) -> None:
        if self.close_treo:
            await asyncio.sleep(3600)
        self.da_dong = True
        if self.close_no is not None:
            raise self.close_no


@pytest.fixture
def khong_ngu(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Thay `time.sleep` — trả về danh sách các khoảng chờ đã yêu cầu."""
    da_cho: list[float] = []
    monkeypatch.setattr(run_module.time, "sleep", da_cho.append)
    return da_cho


def _dat_ket_qua(monkeypatch: pytest.MonkeyPatch, ket_qua: list[Any]) -> list[int]:
    """Mỗi lần `asyncio.run` được gọi, lấy phần tử kế tiếp của `ket_qua`.

    Phần tử là `Exception` ⇒ ném; là `None` ⇒ trả về bình thường.
    """
    so_lan: list[int] = []

    def gia(coro: Any) -> None:
        coro.close()  # đóng coroutine chưa chạy để Python không kêu RuntimeWarning
        so_lan.append(len(so_lan))
        buoc = ket_qua[len(so_lan) - 1]
        if isinstance(buoc, BaseException):
            raise buoc

    monkeypatch.setattr(run_module.asyncio, "run", gia)
    return so_lan


@pytest.mark.parametrize(
    "loi",
    [
        RedisConnectionError(
            "Error while reading from redis:6379 : (104, 'Connection reset by peer')"
        ),
        RedisTimeoutError("Timeout connecting to server"),
        ConnectionResetError(104, "Connection reset by peer"),
    ],
)
def test_mat_redis_thi_dung_lai(
    monkeypatch: pytest.MonkeyPatch, khong_ngu: list[float], loi: Exception
) -> None:
    """Ba hình dạng của cùng một sự cố, cả ba đều phải dẫn tới một lần dựng lại.

    `ConnectionResetError` có mặt vì đó là errno 104 **thô** — redis-py không
    phải lúc nào cũng kịp bọc nó lại, và `NETWORK_ERRORS` cố ý không lấy cả
    `OSError` nên ca này không tự khắc đúng.
    """
    so_lan = _dat_ket_qua(monkeypatch, [loi, None])

    assert run_module.main() == 0
    assert len(so_lan) == 2, "phai dung lai dung mot lan roi thoat sach"
    assert len(khong_ngu) == 1


def test_sigterm_thi_thoat_chu_khong_dung_lai(
    monkeypatch: pytest.MonkeyPatch, khong_ngu: list[float]
) -> None:
    """`docker compose stop` gửi SIGTERM; arq huỷ `main_task` ⇒ `CancelledError`.

    Đây là phép kiểm quan trọng nhất của file: coi nó là lỗi mạng thì worker
    **không tắt được**, và lỗi ấy tệ hơn lỗi B-196 đang vá.
    """
    so_lan = _dat_ket_qua(monkeypatch, [asyncio.CancelledError()])

    assert run_module.main() == 0
    assert len(so_lan) == 1, "khong duoc dung lai sau tin hieu dung"
    assert khong_ngu == []


def test_loi_lap_trinh_thi_de_no(monkeypatch: pytest.MonkeyPatch, khong_ngu: list[float]) -> None:
    """Một `TypeError` không phải sự cố hạ tầng — dựng lại chỉ giấu nó đi."""
    so_lan = _dat_ket_qua(monkeypatch, [TypeError("WorkerSettings sai kieu")])

    with pytest.raises(TypeError):
        run_module.main()
    assert len(so_lan) == 1
    assert khong_ngu == []


def test_backoff_nhan_doi_roi_cham_tran(
    monkeypatch: pytest.MonkeyPatch, khong_ngu: list[float]
) -> None:
    """Khoảng chờ nhân đôi và bị kẹp ở `WORKER_RECONNECT_BACKOFF_MAX_S`.

    Sáu lần đứt liên tiếp: 1, 2, 4, 8, 16, rồi **30** (trần) — không phải 32.
    """
    monkeypatch.setattr(run_module.settings, "WORKER_RECONNECT_BACKOFF_S", 1.0)
    monkeypatch.setattr(run_module.settings, "WORKER_RECONNECT_BACKOFF_MAX_S", 30.0)
    loi = RedisConnectionError("mat ket noi")
    _dat_ket_qua(monkeypatch, [loi, loi, loi, loi, loi, loi, None])

    assert run_module.main() == 0
    assert khong_ngu == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0]


def test_vong_doi_song_lau_thi_backoff_ve_moc_dau(
    monkeypatch: pytest.MonkeyPatch, khong_ngu: list[float]
) -> None:
    """Đứt sau khi đã chạy lâu = sự cố MỚI, không phải lần thử lại thứ n.

    Thiếu vế này thì sau vài lần Redis chớp trong nhiều ngày, worker ngủ tối
    đa trước **mỗi** lần dựng lại, kể cả khi Redis sống lại tức thì.
    """
    monkeypatch.setattr(run_module.settings, "WORKER_RECONNECT_BACKOFF_S", 1.0)
    monkeypatch.setattr(run_module.settings, "WORKER_RECONNECT_BACKOFF_MAX_S", 30.0)
    loi = RedisConnectionError("mat ket noi")

    # Đồng hồ giả: hai lần đứt đầu sát nhau (backoff leo), lần thứ ba xảy ra
    # sau một vòng đời dài 10 000 s (backoff phải quay về mốc đầu).
    moc = iter([0.0, 0.0, 0.0, 1.0, 1.0, 10_001.0, 10_001.0, 10_001.0])
    monkeypatch.setattr(run_module.time, "monotonic", lambda: next(moc))
    _dat_ket_qua(monkeypatch, [loi, loi, loi, None])

    assert run_module.main() == 0
    assert khong_ngu == [1.0, 2.0, 1.0], "lan thu ba phai ve 1.0, khong phai 4.0"


async def test_close_treo_khong_keo_theo_ca_vong_lap(monkeypatch: pytest.MonkeyPatch) -> None:
    """`close()` treo ⇒ `_close_with_timeout` bỏ cuộc đúng hạn và trả quyền về.

    Đây là toàn bộ lý do file `run.py` không gọi `run_worker()`: chỗ treo nằm
    trong `finally` của arq, nơi một `try/except` ở ngoài không với tới.
    """
    monkeypatch.setattr(run_module.settings, "WORKER_SHUTDOWN_TIMEOUT_S", 0.05)
    worker = _FakeWorker(close_treo=True)

    await run_module._close_with_timeout(worker)  # không được treo, không được ném

    assert worker.da_dong is False


async def test_close_nem_loi_van_di_tiep(monkeypatch: pytest.MonkeyPatch) -> None:
    """`close()` ném (Redis đã chết) cũng không được chặn lần dựng lại."""
    monkeypatch.setattr(run_module.settings, "WORKER_SHUTDOWN_TIMEOUT_S", 5.0)
    worker = _FakeWorker(close_no=RedisConnectionError("redis da chet"))

    await run_module._close_with_timeout(worker)

    assert worker.da_dong is True


async def test_don_tai_nguyen_gan_loop_chay_KE_CA_khi_close_hong(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Engine SQLAlchemy phải được dọn dù `Worker.close()` chết giữa chừng.

    Lỗi thật, do stack thật phát hiện chứ không phải do đọc code: `close()` của
    arq gọi `pool.delete(health_check_key)` **trước** `on_shutdown`, nên đúng
    trong ca B-196 (Redis chết) thì `on_shutdown` không chạy, `dispose_engine()`
    không chạy, và vòng đời kế tiếp — với một event loop MỚI — gặp

        RuntimeError: ... got Future ... attached to a different loop

    tức worker sống lại trong một trạng thái hỏng theo kiểu khác. Test này canh
    đúng chiều đó: `close()` ném, mà phần dọn vẫn phải chạy.
    """
    da_don: list[str] = []

    async def on_shutdown_gia(ctx: dict[str, Any]) -> None:
        da_don.append("on_shutdown")

    monkeypatch.setattr(run_module, "on_shutdown", on_shutdown_gia)
    monkeypatch.setattr(run_module.settings, "WORKER_SHUTDOWN_TIMEOUT_S", 0.05)

    class _WorkerCloseHong(_FakeWorker):
        ctx: dict[str, Any] = {}

    worker = _WorkerCloseHong(close_treo=True)

    async def async_run_gia() -> None:
        raise RedisConnectionError("mat ket noi giua chung")

    worker.async_run = async_run_gia  # type: ignore[method-assign]
    monkeypatch.setattr(run_module, "create_worker", lambda _settings: worker)

    with pytest.raises(RedisConnectionError):
        await run_module._run_one_lifecycle()

    assert da_don == ["on_shutdown"], "phan don phai chay ke ca khi close() treo"


async def test_don_tai_nguyen_nem_loi_cung_khong_chan_vong_lap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bản thân bước dọn hỏng cũng không được nuốt mất lỗi gốc."""

    async def on_shutdown_no(ctx: dict[str, Any]) -> None:
        raise RuntimeError("postgres cung di vang")

    monkeypatch.setattr(run_module, "on_shutdown", on_shutdown_no)

    class _W(_FakeWorker):
        ctx: dict[str, Any] = {}

    await run_module._release_loop_bound_resources(_W())  # không được ném


@pytest.mark.parametrize(
    ("ten_file", "lenh_phai_co"),
    [
        ("docker-compose.yml", "command: python -m app.workers.run"),
        ("docker-compose.override.yml", 'command: watchfiles "python -m app.workers.run" /app/app'),
    ],
)
def test_compose_goi_dung_module(ten_file: str, lenh_phai_co: str) -> None:
    """CẢ HAI file compose phải gọi đúng module này.

    Không có phép kiểm nào khác nối hai đầu ấy: để nguyên `command: arq …` thì
    mọi test trên đây vẫn xanh trong khi **không dòng nào của `run.py` chạy
    trong container** — đúng kiểu xanh giả mà B-196 vừa vá.

    `docker-compose.override.yml` có mặt trong bảng vì nó **thay** `command`
    chứ không bổ sung, và đó là cái bẫy đã sập thật khi viết B-196: bản vá vào
    `docker-compose.yml` còn máy dev vẫn chạy `arq` trần. Sửa một file mà quên
    file kia là lệch dev/production, loại lệch không ai nhìn thấy cho tới lúc
    gặp sự cố.
    """
    from pathlib import Path

    compose = Path(__file__).resolve().parents[3] / ten_file
    noi_dung = compose.read_text(encoding="utf-8")

    assert lenh_phai_co in noi_dung
    assert "command: arq app.workers.main.WorkerSettings" not in noi_dung
