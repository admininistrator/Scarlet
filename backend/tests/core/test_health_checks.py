"""`app/core/health_checks.py` — B-193 (lý do không rỗng) và B-192 (bộ nhớ).

KH tham chiếu: §18.6, §21.2, §16.3 · tasks.md T-2.20, T-3.12, B-192, B-193.

**B-193** đo được hai lần trong DoD của T-2.20: `{"ok": false, "latency_ms":
2000, "error": ""}` cho `redis` lúc container đã dừng — `asyncio.wait_for` hết
giờ ném `TimeoutError` với `str()` rỗng. Hai ca đầu của file này đi đúng
đường ấy (`_timed` với một coroutine không bao giờ xong), không gọi thẳng hàm
định dạng — vì chỗ hỏng là *đường* từ exception tới `CheckResult.error`.

**B-192** — `CachedChecks` nhớ một lượt đo `ttl_s` giây. Ba tính chất: lượt
hỏi thứ hai trong hạn **không** đo lại; các lượt hỏi TRÙNG LÚC khi bộ nhớ
rỗng chỉ đo **một** lần; hết hạn thì đo lại và mốc `checked_at` đổi theo.
"""

from __future__ import annotations

import asyncio

import pytest

from app.core import health_checks
from app.core.health_checks import CachedChecks, CheckResult, describe_error


async def _khong_bao_gio_xong() -> None:
    await asyncio.Event().wait()


async def test_timeout_khong_de_lai_chuoi_rong(monkeypatch: pytest.MonkeyPatch) -> None:
    """B-193 — ca đã lọt: hết giờ ⇒ `error` phải nói được "hết giờ"."""
    monkeypatch.setattr(health_checks, "CHECK_TIMEOUT_S", 0.01)

    _, ket_qua = await health_checks._timed("redis", _khong_bao_gio_xong())

    assert ket_qua.ok is False
    assert ket_qua.error
    assert ket_qua.error.strip() != ""
    assert "TimeoutError" in ket_qua.error


async def test_exception_khong_thong_diep_van_co_ten_kieu() -> None:
    """Không chỉ timeout — mọi exception có `str()` rỗng (vài lỗi của redis-py)."""

    async def hong() -> None:
        raise ConnectionError()

    _, ket_qua = await health_checks._timed("redis", hong())

    assert ket_qua.error == "ConnectionError"


async def test_exception_co_thong_diep_giu_ca_hai() -> None:
    async def hong() -> None:
        raise ConnectionError("Error 111 connecting to redis:6379.")

    _, ket_qua = await health_checks._timed("redis", hong())

    assert ket_qua.error == "ConnectionError: Error 111 connecting to redis:6379."


def test_thong_diep_chi_co_khoang_trang_cung_tinh_la_rong() -> None:
    assert describe_error(ValueError("   ")) == "ValueError"


def test_ly_do_bi_cat_o_tran() -> None:
    assert len(describe_error(ValueError("x" * 1000))) == health_checks.ERROR_MAX_CHARS


# ═══════════════════════════ B-192 — CachedChecks ═══════════════════════════


class _DemLuotDo:
    def __init__(self) -> None:
        self.luot = 0

    async def __call__(self) -> dict[str, CheckResult]:
        self.luot += 1
        # Nhường vòng lặp một nhịp: đủ để các lượt hỏi trùng lúc chen vào
        # giữa lúc "đang đo" — đúng khe mà khoá phải đóng.
        await asyncio.sleep(0)
        return {"redis": CheckResult(ok=True, latency_ms=self.luot)}


async def test_hoi_lai_trong_han_khong_do_lai() -> None:
    bo_nho = CachedChecks()
    do = _DemLuotDo()

    dau = await bo_nho.get(do, ttl_s=60)
    lai = await bo_nho.get(do, ttl_s=60)

    assert do.luot == 1
    assert lai.checked_at == dau.checked_at
    assert lai.checks == dau.checks


async def test_hoi_trung_luc_khi_bo_nho_rong_chi_do_mot_lan() -> None:
    bo_nho = CachedChecks()
    do = _DemLuotDo()

    ket_qua = await asyncio.gather(*(bo_nho.get(do, ttl_s=60) for _ in range(5)))

    assert do.luot == 1
    assert len({r.checked_at for r in ket_qua}) == 1


async def test_het_han_thi_do_lai_va_moc_do_doi(monkeypatch: pytest.MonkeyPatch) -> None:
    bo_nho = CachedChecks()
    do = _DemLuotDo()
    dong_ho = [1000.0]
    monkeypatch.setattr(health_checks.time, "monotonic", lambda: dong_ho[0])

    dau = await bo_nho.get(do, ttl_s=10)
    dong_ho[0] += 9.9
    await bo_nho.get(do, ttl_s=10)
    assert do.luot == 1

    dong_ho[0] += 0.2
    sau = await bo_nho.get(do, ttl_s=10)

    assert do.luot == 2
    assert sau.checked_at >= dau.checked_at
    assert sau.checks["redis"].latency_ms == 2


async def test_clear_bat_do_lai() -> None:
    bo_nho = CachedChecks()
    do = _DemLuotDo()

    await bo_nho.get(do, ttl_s=60)
    bo_nho.clear()
    await bo_nho.get(do, ttl_s=60)

    assert do.luot == 2
