"""`app/core/provider_health.py` — nguồn của `available` trong `GET /models`.

KH tham chiếu: §9.3, §9.5, §18.3, RR-5, UC-05 · tasks.md T-3.6, B-192.

Không một ca nào ở đây chạm mạng thật: `probe_provider` là hàm **duy nhất**
gọi ra ngoài, nên mọi ca thay chính nó. Nhờ vậy bộ test đo đúng phần logic
(ai được đo, nhớ bao lâu, hỏng thì nói gì) chứ không đo xem 9Router trên máy
này có đang bật hay không — thứ đổi theo từng lần chạy.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.config import catalog
from app.config.catalog import Provider
from app.core import provider_health
from app.core.provider_health import HOST_DEPENDENT

#: Khoá provider `host-dependent` duy nhất của catalog thật (§9.2).
NINEROUTER = "ninerouter"


@pytest.fixture(autouse=True)
def _don_bo_nho() -> Iterator[None]:
    """Bộ nhớ của module là state toàn cục — dọn trước VÀ sau mỗi ca.

    Trước, vì một ca chạy trước có thể để lại kết quả còn hạn `TTL_S` (30 s)
    và ca sau sẽ xanh mà không đo gì. Sau, vì cùng lý do theo chiều ngược lại.
    """
    provider_health.quen_het()
    yield
    provider_health.quen_het()
    catalog.reload(path=catalog.CATALOG_PATH)


def _ghi_catalog(tmp_path: Path, raw: dict[str, object]) -> Path:
    fixture = tmp_path / "model_catalog.json"
    fixture.write_text(json.dumps(raw), encoding="utf-8")
    return fixture


def _catalog_khong_health_path(tmp_path: Path) -> Path:
    """Bản catalog y hệt, trừ việc 9Router mất `health_path`."""
    raw = json.loads(catalog.CATALOG_PATH.read_text(encoding="utf-8"))
    del raw["providers"][NINEROUTER]["health_path"]
    return _ghi_catalog(tmp_path, raw)


def _catalog_always_co_health_path(tmp_path: Path) -> tuple[Path, str]:
    """Bản catalog trong đó một provider `always` **có** `health_path`.

    Cần một bản riêng vì catalog thật che mất phép đo: bốn provider của nó
    chỉ có 9Router khai `health_path`, nên bỏ hẳn phép lọc `availability` đi
    thì ba provider kia vẫn không bị gọi — chúng dừng ở nhánh "thiếu
    health_path" của `_do_mot`. Một phép kiểm xanh vì lý do đó là phép kiểm
    đang đo chỗ khác (đo được bằng phép kiểm ngược, xem báo cáo T-3.6).
    """
    raw = json.loads(catalog.CATALOG_PATH.read_text(encoding="utf-8"))
    khoa = next(k for k, p in raw["providers"].items() if p["availability"] != HOST_DEPENDENT)
    raw["providers"][khoa]["health_path"] = "/models"
    return _ghi_catalog(tmp_path, raw), khoa


async def test_provider_always_khong_bi_do_du_co_health_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A3 + §9.2: ai được đo là **dữ liệu** (`availability`), không phải một
    danh sách tên provider trong `.py`.

    Provider `always` ở đây được cho hẳn một `health_path` để phép kiểm đo
    đúng phép lọc `availability` chứ không đo nhánh "thiếu health_path" —
    xem `_catalog_always_co_health_path`.
    """
    fixture, khoa_always = _catalog_always_co_health_path(tmp_path)
    catalog.reload(path=fixture)
    da_do: list[str] = []

    async def probe_hong(provider: Provider) -> None:
        da_do.append(provider.label)
        raise ConnectionError("khong ket noi duoc")

    monkeypatch.setattr(provider_health, "probe_provider", probe_hong)

    trang_thai = await provider_health.provider_statuses()

    cat = catalog.get_catalog()
    assert cat.providers[khoa_always].health_path is not None
    assert trang_thai[khoa_always].available is True
    assert trang_thai[khoa_always].reason is None
    assert da_do == [cat.providers[NINEROUTER].label]


async def test_host_dependent_hong_thi_khong_kha_dung_va_co_ly_do(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def probe_hong(provider: Provider) -> None:
        raise ConnectionError("Connection refused")

    monkeypatch.setattr(provider_health, "probe_provider", probe_hong)

    trang_thai = await provider_health.provider_statuses()

    nr = trang_thai[NINEROUTER]
    assert nr.available is False
    assert nr.reason is not None
    # Câu lấy tên provider từ CATALOG, không từ một literal trong `.py`.
    assert catalog.get_catalog().providers[NINEROUTER].label in nr.reason


async def test_host_dependent_song_thi_khong_kem_ly_do(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def probe_ok(provider: Provider) -> None:
        return None

    monkeypatch.setattr(provider_health, "probe_provider", probe_ok)

    trang_thai = await provider_health.provider_statuses()

    assert trang_thai[NINEROUTER].available is True
    assert trang_thai[NINEROUTER].reason is None


async def test_qua_gio_cho_thi_coi_nhu_khong_phan_hoi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Host im lặng (gói tin rơi) khác host từ chối — cả hai phải ra cùng một
    câu trả lời, và cái đầu chỉ lộ ra qua `asyncio.wait_for`."""

    async def probe_treo(provider: Provider) -> None:
        await asyncio.sleep(10)

    monkeypatch.setattr(provider_health, "probe_provider", probe_treo)
    monkeypatch.setattr(provider_health, "PROBE_TIMEOUT_S", 0.05)

    trang_thai = await provider_health.provider_statuses()

    assert trang_thai[NINEROUTER].available is False


async def test_thieu_health_path_van_coi_la_kha_dung(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Không đo được ≠ đã tắt. Xám một model vì cấu hình thiếu một trường là
    đổ lỗi cho người dùng về việc của người vận hành."""
    catalog.reload(path=_catalog_khong_health_path(tmp_path))

    async def probe_no_le(provider: Provider) -> None:
        raise AssertionError("khong duoc goi khi thieu health_path")

    monkeypatch.setattr(provider_health, "probe_provider", probe_no_le)

    trang_thai = await provider_health.provider_statuses()

    assert trang_thai[NINEROUTER].available is True
    assert trang_thai[NINEROUTER].reason is None


async def test_hai_lan_goi_lien_tiep_chi_mot_luot_do(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cạm bẫy ② của T-3.6 / B-192: 854 ms mỗi lượt đo, picker mở rất nhiều."""
    so_lan = 0

    async def probe_dem(provider: Provider) -> None:
        nonlocal so_lan
        so_lan += 1

    monkeypatch.setattr(provider_health, "probe_provider", probe_dem)

    await provider_health.provider_statuses()
    await provider_health.provider_statuses()
    await provider_health.provider_statuses()

    assert so_lan == 1


async def test_nhieu_lan_goi_song_song_cung_chi_mot_luot_do(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mở app trong bốn tab cùng lúc là bốn `GET /models` gần như đồng thời.
    Không có `_khoa` thì cả bốn đều thấy bộ nhớ hết hạn và cùng đi đo."""
    so_lan = 0

    async def probe_cham(provider: Provider) -> None:
        nonlocal so_lan
        so_lan += 1
        await asyncio.sleep(0.05)

    monkeypatch.setattr(provider_health, "probe_provider", probe_cham)

    await asyncio.gather(*(provider_health.provider_statuses() for _ in range(4)))

    assert so_lan == 1


async def test_het_han_thi_do_lai(monkeypatch: pytest.MonkeyPatch) -> None:
    so_lan = 0

    async def probe_dem(provider: Provider) -> None:
        nonlocal so_lan
        so_lan += 1

    monkeypatch.setattr(provider_health, "probe_provider", probe_dem)
    monkeypatch.setattr(provider_health, "TTL_S", 0.0)

    await provider_health.provider_statuses()
    await provider_health.provider_statuses()

    assert so_lan == 2


async def test_nap_lai_catalog_lam_bo_nho_het_hieu_luc(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """S7/§19.1 — `POST /admin/catalog/reload` có hiệu lực NGAY. Không ai phải
    nhớ gọi `quen_het()`: `catalog.reload()` thay cả object nên phép so `is`
    trong `provider_statuses()` tự thấy."""
    so_lan = 0

    async def probe_dem(provider: Provider) -> None:
        nonlocal so_lan
        so_lan += 1

    monkeypatch.setattr(provider_health, "probe_provider", probe_dem)

    await provider_health.provider_statuses()
    assert so_lan == 1

    catalog.reload(path=catalog.CATALOG_PATH)
    await provider_health.provider_statuses()

    assert so_lan == 2
