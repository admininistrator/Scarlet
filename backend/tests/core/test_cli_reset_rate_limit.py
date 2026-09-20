"""`python -m app.cli reset-rate-limit` — B-188.

B-188 ghi lại một sự cố **vận hành**, không một bug: hạn mức `register`
(3/giờ/IP, §10.6) chặn đúng dòng DoD dài nhất của T-3.1b, và đường duy nhất đi
tiếp là `redis-cli DEL rl:ip:register:<ip>` — *"tức người chạy phải biết cả tên
khoá lẫn quy ước đặt tên"*.

Vì vậy thứ được kiểm ở đây không phải "Redis có xoá được khoá không" (nó có),
mà là ba thứ **giữa người gõ và Redis**:

1. một tên nhóm gõ sai **dừng ở `argparse`**, không chạy xong rồi in "0 khoa"
   — vì dòng ấy đọc thành "hạn mức đã tự hết hạn";
2. `--all` và một định danh **loại trừ nhau**, cùng cái phanh mà
   `rebuild-quota --all` đã dựng;
3. `NHOM_THEO_IP` không lệch khỏi những chuỗi `api/v1/auth.py` thật sự dùng —
   một tên hợp lệ trong danh sách mà không route nào mang là cùng một triệu
   chứng ở chiều ngược lại.

Redis **giả**, và chỗ này thì giả là đúng: khoá đếm là một chuỗi với một TTL,
không có `NUMERIC(12,6)` hay `timestamptz` nào để Postgres phải trả lời (khác
`tests/quota/test_rebuild.py`). Bản đo trên Redis thật nằm trong báo cáo
T-3.1b.
"""

from __future__ import annotations

import ast
import uuid
from collections.abc import AsyncIterator
from fnmatch import fnmatch
from pathlib import Path

import pytest

from app import cli
from app.core.ratelimit import (
    GROUP_CHAT,
    NHOM_THEO_IP,
    ROUTE_FORGOT_PASSWORD,
    ROUTE_REGISTER,
    ip_key,
    user_key,
)

USER = uuid.UUID("22222222-2222-4222-8222-222222222222")


class _RedisKhoa:
    """Redis trong bộ nhớ — bốn lệnh mà `_reset_rate_limit` dùng.

    `scan_iter` trả một async iterator và khớp mẫu bằng `fnmatch`, đúng như
    `SCAN MATCH` của Redis. Trả `bytes` chứ không `str`: client thật
    (`redis.asyncio`, xem `core/redis.py`) trả `bytes`, và một Redis giả dễ
    tính hơn bản thật sẽ giấu đúng lỗi mà `_chuoi()` sinh ra để chặn (bài học
    B-102).
    """

    def __init__(self, kho: dict[str, tuple[str, int]] | None = None) -> None:
        #: khoá -> (giá trị, TTL còn lại)
        self.kho: dict[str, tuple[str, int]] = dict(kho or {})

    async def scan_iter(self, *, match: str, count: int = 10) -> AsyncIterator[bytes]:
        for khoa in sorted(self.kho):
            if fnmatch(khoa, match):
                yield khoa.encode()

    async def get(self, name: str) -> bytes | None:
        hang = self.kho.get(name)
        return None if hang is None else hang[0].encode()

    async def ttl(self, name: str) -> int:
        hang = self.kho.get(name)
        return -2 if hang is None else hang[1]

    async def delete(self, name: str) -> int:
        return 1 if self.kho.pop(name, None) is not None else 0


@pytest.fixture
def redis_khoa(monkeypatch: pytest.MonkeyPatch) -> _RedisKhoa:
    gia = _RedisKhoa(
        {
            ip_key(ROUTE_REGISTER, "172.18.0.1"): ("4", 2871),
            ip_key(ROUTE_REGISTER, "203.0.113.9"): ("1", 3400),
            ip_key(ROUTE_FORGOT_PASSWORD, "172.18.0.1"): ("2", 3000),
            user_key(GROUP_CHAT, USER): ("tokens", 60),
        }
    )
    monkeypatch.setattr("app.cli.get_redis", lambda: gia)
    return gia


# ───────────────────────── vỏ lệnh: cái phanh ───────────────────────────────


def test_khong_dinh_danh_va_khong_all_thi_argparse_bao_loi(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Cùng cái phanh của `rebuild-quota --all`: lệnh phải nói ra nó định làm gì."""
    with pytest.raises(SystemExit) as exc:
        cli.main([cli.RESET_RATE_LIMIT, cli.TRUC_IP, ROUTE_REGISTER])
    assert exc.value.code == 2
    assert "--all" in capsys.readouterr().err


def test_vua_dinh_danh_vua_all_cung_bao_loi(capsys: pytest.CaptureFixture[str]) -> None:
    """Hai ý định đối nhau trong một lệnh — không đoán hộ người gõ."""
    with pytest.raises(SystemExit) as exc:
        cli.main([cli.RESET_RATE_LIMIT, cli.TRUC_IP, ROUTE_REGISTER, "172.18.0.1", "--all"])
    assert exc.value.code == 2
    assert "--all" in capsys.readouterr().err


def test_ten_nhom_go_sai_dung_o_argparse_chu_khong_in_0_khoa(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Đây là **lý do** lệnh này có `choices` — xem docstring `app/cli.py`."""
    with pytest.raises(SystemExit) as exc:
        cli.main([cli.RESET_RATE_LIMIT, cli.TRUC_IP, "regsiter", "--all"])
    assert exc.value.code == 2
    assert "regsiter" in capsys.readouterr().err


def test_nhom_dung_nhung_sai_truc_bi_tu_choi(capsys: pytest.CaptureFixture[str]) -> None:
    """`chat` là nhóm thật, nhưng của trục `user` — `rl:ip:chat:*` không tồn tại."""
    with pytest.raises(SystemExit) as exc:
        cli.main([cli.RESET_RATE_LIMIT, cli.TRUC_IP, GROUP_CHAT, "--all"])
    assert exc.value.code == 2
    loi = capsys.readouterr().err
    assert GROUP_CHAT in loi
    assert ROUTE_REGISTER in loi  # có in ra danh sách nhóm hợp lệ của trục


def test_truc_user_doi_uuid_chu_khong_mot_chuoi_bat_ky(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main([cli.RESET_RATE_LIMIT, cli.TRUC_USER, GROUP_CHAT, "khong-phai-uuid"])
    assert exc.value.code == 2
    assert "UUID" in capsys.readouterr().err


# ───────────────────────── thân lệnh: xoá thật ──────────────────────────────


async def test_xoa_mot_ip_chi_dung_khoa_cua_ip_do(
    redis_khoa: _RedisKhoa, capsys: pytest.CaptureFixture[str]
) -> None:
    ma_thoat = await cli._reset_rate_limit(cli.TRUC_IP, ROUTE_REGISTER, "172.18.0.1")

    assert ma_thoat == 0
    assert ip_key(ROUTE_REGISTER, "172.18.0.1") not in redis_khoa.kho
    # Cùng nhóm/IP khác, và cùng IP/nhóm khác: cả hai phải còn nguyên.
    assert ip_key(ROUTE_REGISTER, "203.0.113.9") in redis_khoa.kho
    assert ip_key(ROUTE_FORGOT_PASSWORD, "172.18.0.1") in redis_khoa.kho
    ra = capsys.readouterr().out
    assert "4 luot, con 2871 giay" in ra
    assert "1 khoa da xoa" in ra


async def test_all_xoa_moi_ip_cua_dung_mot_nhom(
    redis_khoa: _RedisKhoa, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ngả dùng được khi chạy DoD: người chạy không biết IP Nginx gắn cho mình."""
    ma_thoat = await cli._reset_rate_limit(cli.TRUC_IP, ROUTE_REGISTER, None)

    assert ma_thoat == 0
    assert ip_key(ROUTE_REGISTER, "172.18.0.1") not in redis_khoa.kho
    assert ip_key(ROUTE_REGISTER, "203.0.113.9") not in redis_khoa.kho
    assert ip_key(ROUTE_FORGOT_PASSWORD, "172.18.0.1") in redis_khoa.kho
    assert user_key(GROUP_CHAT, USER) in redis_khoa.kho
    assert "2 khoa da xoa" in capsys.readouterr().out


async def test_truc_user_xoa_xo_token_cua_dung_mot_nguoi(redis_khoa: _RedisKhoa) -> None:
    ma_thoat = await cli._reset_rate_limit(cli.TRUC_USER, GROUP_CHAT, str(USER))

    assert ma_thoat == 0
    assert user_key(GROUP_CHAT, USER) not in redis_khoa.kho
    assert ip_key(ROUTE_REGISTER, "172.18.0.1") in redis_khoa.kho


async def test_khoa_khong_ton_tai_thi_noi_ra_chu_khong_im_lang(
    redis_khoa: _RedisKhoa, capsys: pytest.CaptureFixture[str]
) -> None:
    """Mã thoát vẫn 0: "không còn gì để gỡ" là kết cục đúng, không phải lỗi."""
    ma_thoat = await cli._reset_rate_limit(cli.TRUC_IP, ROUTE_REGISTER, "10.0.0.99")

    assert ma_thoat == 0
    ra = capsys.readouterr().out
    assert "khong co" in ra
    assert "0 khoa da xoa" in ra


# ───────── `NHOM_THEO_IP` không được lệch khỏi `api/v1/auth.py` ─────────────
#
# Cùng lối `tests/workers/test_run_loop.py::test_compose_goi_dung_module`: đọc
# file nguồn để canh một thoả thuận mà không phép gọi nào lúc chạy lộ ra.


def _nhom_trong_auth() -> set[str]:
    """Mọi đối số của `gioi_han_gui_email(...)` / `gioi_han_auth(...)` trong auth.py.

    Trả về **tên hằng**; một chuỗi trần lộ ra ở đây dưới dạng giá trị của nó
    trong ngoặc kép, nên ca test bên dưới bắt được cả hai kiểu lệch.
    """
    nguon = Path(__file__).resolve().parents[2] / "app" / "api" / "v1" / "auth.py"
    cay = ast.parse(nguon.read_text(encoding="utf-8"))
    ra: set[str] = set()
    for node in ast.walk(cay):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"gioi_han_gui_email", "gioi_han_auth"}
            and node.args
        ):
            doi_so = node.args[0]
            ra.add(doi_so.id if isinstance(doi_so, ast.Name) else ast.unparse(doi_so))
    return ra


def test_auth_py_goi_dependency_bang_HANG_chu_khong_chuoi_tran() -> None:
    """Một chuỗi trần ở đây là chỗ `NHOM_THEO_IP` bắt đầu lệch — xem B-188."""
    assert _nhom_trong_auth() == {
        "ROUTE_REGISTER",
        "ROUTE_RESEND_VERIFICATION",
        "ROUTE_FORGOT_PASSWORD",
        "ROUTE_RESET_PASSWORD",
        "ROUTE_LOGOUT",
    }


def test_moi_nhom_trong_NHOM_THEO_IP_deu_co_mot_route_that() -> None:
    """Chiều ngược lại: một tên hợp lệ mà không route nào mang cũng là một lệch.

    Nó cho người vận hành một lệnh chạy xong, in "0 khoa", và không cách nào
    biết rằng nhóm ấy chưa từng đếm ai.
    """
    from app.core import ratelimit as rl

    ten_hang = {n for n in dir(rl) if n.startswith("ROUTE_")}
    assert _nhom_trong_auth() == ten_hang
    assert {getattr(rl, n) for n in ten_hang} == set(NHOM_THEO_IP)
