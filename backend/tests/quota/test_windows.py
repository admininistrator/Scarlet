"""Hai cửa sổ trượt: khoá, member, dọn-trước-đọc, `retry_after` (§10.3) — T-2.11.

Redis GIẢ, và bản giả này mô phỏng **thật** hai lệnh ZSET — xem docstring
`FakeQuotaRedis` ở `tests/conftest.py` cho lý do (khác `FakeRateLimitRedis`
của T-2.9, nơi một bản mô phỏng Lua bằng Python sẽ là bản hiện thực thứ hai).
Nó đến qua **fixture** `quota_redis_fake` chứ không qua `import`: `tests/`
không phải package.

Phép tính `retry_after` là phần đắt nhất của file này và nó **không** cần
Redis: `WindowState` là một dataclass thuần, nên mọi ca biên đo được bằng số.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest

from app.config.settings import settings
from app.quota.windows import (
    LimitType,
    Window,
    WindowState,
    encode_member,
    parse_member,
    read_window,
    windows,
)

USER = uuid.UUID("11111111-1111-1111-1111-111111111111")
NOW = 1_800_000_000.0


def _cua_so(seconds: int = 18000) -> Window:
    return Window(LimitType.SHORT, seconds)


def _state(*entries: tuple[float, str], seconds: int = 18000) -> WindowState:
    muc = tuple((score, Decimal(cost)) for score, cost in entries)
    return WindowState(
        window=_cua_so(seconds),
        spent=sum((cost for _, cost in muc), Decimal(0)),
        entries=muc,
    )


# ════════════════════════════ khoá và member ═══════════════════════════════


def test_khoa_mang_ca_ten_cua_so_lan_user_id() -> None:
    assert _cua_so().key(USER) == f"quota:5h:{USER}"
    assert Window(LimitType.LONG, 604800).key(USER) == f"quota:weekly:{USER}"


def test_hai_cua_so_doc_do_dai_tu_settings_luc_goi(monkeypatch: pytest.MonkeyPatch) -> None:
    """A3: hai con số là cấu hình, và `windows()` phải đọc chúng ở lúc GỌI."""
    monkeypatch.setattr(settings, "QUOTA_WINDOW_SHORT_S", 42)
    ngan, dai = windows()
    assert (ngan.limit_type, ngan.seconds) == (LimitType.SHORT, 42)
    assert dai.limit_type is LimitType.LONG


def test_member_di_vong_qua_chuoi_roi_ve_van_dung_con_so() -> None:
    usage_id = uuid.uuid4()
    member = encode_member(usage_id, Decimal("0.001234"))
    assert member == f"{usage_id}:0.001234"
    assert parse_member(member) == Decimal("0.001234")


def test_member_giu_du_sau_chu_so_thap_phan() -> None:
    """`NUMERIC(12,6)` của Phụ lục A — thiếu một chữ số là một phép đối chiếu tự sai."""
    assert parse_member(encode_member(uuid.uuid4(), Decimal("0.000001"))) == Decimal("0.000001")


def test_member_hong_tra_none_chu_khong_nem() -> None:
    assert parse_member("khong-co-dau-hai-cham") is None
    assert parse_member(f"{uuid.uuid4()}:khong-phai-so") is None


# ══════════════════════════ dọn trước, đọc sau ═════════════════════════════


async def test_don_chay_truoc_khi_doc_va_dung_bien(quota_redis_fake: Any) -> None:
    redis = quota_redis_fake
    window = _cua_so(100)
    key = window.key(USER)
    redis.zset[key] = {
        encode_member(uuid.uuid4(), Decimal("1.5")): NOW - 150,  # quá hạn
        encode_member(uuid.uuid4(), Decimal("2.5")): NOW - 50,  # còn trong cửa sổ
    }

    state = await read_window(redis, window, user_id=USER, now=NOW)

    assert redis.da_don == [(key, "-inf", f"({NOW - 100}")]
    assert state.spent == Decimal("2.5")
    assert len(redis.zset[key]) == 1


async def test_cua_so_rong_ra_khong_dong_nao(quota_redis_fake: Any) -> None:
    state = await read_window(quota_redis_fake, _cua_so(), user_id=USER, now=NOW)
    assert state.spent == Decimal(0)
    assert state.entries == ()


async def test_member_hong_bi_bo_qua_chu_khong_lam_do_ca_luot_doc(
    caplog: pytest.LogCaptureFixture, quota_redis_fake: Any
) -> None:
    redis = quota_redis_fake
    window = _cua_so(100)
    redis.zset[window.key(USER)] = {
        "rac-khong-doc-duoc": NOW - 10,
        encode_member(uuid.uuid4(), Decimal("0.5")): NOW - 10,
    }
    with caplog.at_level("WARNING", logger="app.quota.windows"):
        state = await read_window(redis, window, user_id=USER, now=NOW)
    assert state.spent == Decimal("0.5")
    assert "khong doc duoc" in caplog.text


async def test_redis_chet_thi_nem_ra_chu_khong_tra_cua_so_rong(quota_redis_fake: Any) -> None:
    """Cửa sổ rỗng giả nghĩa là "chưa tiêu gì" — chỗ gọi mới được quyết định."""
    redis = quota_redis_fake
    redis.fail = True
    with pytest.raises(ConnectionError):
        await read_window(redis, _cua_so(), user_id=USER, now=NOW)


# ═══════════════════════ retry_after theo §10.3 ════════════════════════════


def test_retry_after_la_luc_phan_tu_cu_nhat_roi_khoi_cua_so() -> None:
    """§10.3: `score` của phần tử cũ nhất cần rơi ra + độ dài cửa sổ − now."""
    state = _state((NOW - 17000, "1.0"), (NOW - 10000, "1.0"), seconds=18000)
    # Cần nhả 0.5 USD ⇒ chỉ phần tử cũ nhất là đủ ⇒ rơi sau 18000 − 17000 = 1000 s.
    assert state.retry_after_s(need_to_free=Decimal("0.5"), now=NOW) == 1000


def test_retry_after_di_tiep_khi_mot_phan_tu_chua_du() -> None:
    state = _state((NOW - 17000, "1.0"), (NOW - 10000, "1.0"), seconds=18000)
    # Cần 1.5 ⇒ phải nhả cả hai ⇒ mốc là phần tử THỨ HAI: 18000 − 10000 = 8000 s.
    assert state.retry_after_s(need_to_free=Decimal("1.5"), now=NOW) == 8000


def test_retry_after_lam_tron_LEN() -> None:
    """Làm tròn xuống là hẹn client quay lại lúc vẫn còn bị chặn (`_giay_len`).

    Mốc rơi ra sau **3.2 s**: làm tròn lên ra 4, làm tròn xuống ra 3 — và 3 là
    một lời hẹn sai. Con số phải đủ xa 0 để phép so sánh không bị `max(1, …)`
    che mất: đó chính là chỗ bản đầu của test này trượt.
    """
    state = _state((NOW - 17996.8, "1.0"), seconds=18000)
    assert state.retry_after_s(need_to_free=Decimal("0.5"), now=NOW) == 4


def test_retry_after_toi_thieu_1_giay() -> None:
    """`0` nghĩa là "thử ngay đi", tức một vòng lặp bận."""
    state = _state((NOW - 17999.9, "1.0"), seconds=18000)
    assert state.retry_after_s(need_to_free=Decimal("0.5"), now=NOW) == 1


def test_retry_after_none_khi_nha_het_cua_so_van_khong_du() -> None:
    """Ca của DoD dòng 1: một lượt sinh đơn lẻ đã vượt trần, không có gì để hẹn."""
    state = _state((NOW - 10000, "1.0"), seconds=18000)
    assert state.retry_after_s(need_to_free=Decimal("99"), now=NOW) is None


def test_retry_after_none_khi_cua_so_rong() -> None:
    assert _state().retry_after_s(need_to_free=Decimal("1"), now=NOW) is None


def test_retry_after_none_khi_khong_can_nha_gi() -> None:
    state = _state((NOW - 10, "1.0"))
    assert state.retry_after_s(need_to_free=Decimal(0), now=NOW) is None
