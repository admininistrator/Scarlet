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
3. `IP_GROUPS` không lệch khỏi những chuỗi `api/v1/auth.py` thật sự dùng —
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
    IP_GROUPS,
    ROUTE_FORGOT_PASSWORD,
    ROUTE_REGISTER,
    ip_key,
    user_key,
)

USER = uuid.UUID("22222222-2222-4222-8222-222222222222")


class _KeyedRedis:
    """Redis trong bộ nhớ — bốn lệnh mà `_reset_rate_limit` dùng.

    `scan_iter` trả một async iterator và khớp mẫu bằng `fnmatch`, đúng như
    `SCAN MATCH` của Redis. Trả `bytes` chứ không `str`: client thật
    (`redis.asyncio`, xem `core/redis.py`) trả `bytes`, và một Redis giả dễ
    tính hơn bản thật sẽ giấu đúng lỗi mà `_chuoi()` sinh ra để chặn (bài học
    B-102).
    """

    def __init__(self, store: dict[str, tuple[str, int]] | None = None) -> None:
        #: khoá -> (giá trị, TTL còn lại)
        self.store: dict[str, tuple[str, int]] = dict(store or {})

    async def scan_iter(self, *, match: str, count: int = 10) -> AsyncIterator[bytes]:
        for key in sorted(self.store):
            if fnmatch(key, match):
                yield key.encode()

    async def get(self, name: str) -> bytes | None:
        row = self.store.get(name)
        return None if row is None else row[0].encode()

    async def ttl(self, name: str) -> int:
        row = self.store.get(name)
        return -2 if row is None else row[1]

    async def delete(self, name: str) -> int:
        return 1 if self.store.pop(name, None) is not None else 0


@pytest.fixture
def keyed_redis(monkeypatch: pytest.MonkeyPatch) -> _KeyedRedis:
    fake = _KeyedRedis(
        {
            ip_key(ROUTE_REGISTER, "172.18.0.1"): ("4", 2871),
            ip_key(ROUTE_REGISTER, "203.0.113.9"): ("1", 3400),
            ip_key(ROUTE_FORGOT_PASSWORD, "172.18.0.1"): ("2", 3000),
            user_key(GROUP_CHAT, USER): ("tokens", 60),
        }
    )
    monkeypatch.setattr("app.cli.get_redis", lambda: fake)
    return fake


# ───────────────────────── vỏ lệnh: cái phanh ───────────────────────────────


def test_no_identity_and_no_all_argparse_errors(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Cùng cái phanh của `rebuild-quota --all`: lệnh phải nói ra nó định làm gì."""
    with pytest.raises(SystemExit) as exc:
        cli.main([cli.RESET_RATE_LIMIT, cli.AXIS_IP, ROUTE_REGISTER])
    assert exc.value.code == 2
    assert "--all" in capsys.readouterr().err


def test_both_identity_and_all_also_errors(capsys: pytest.CaptureFixture[str]) -> None:
    """Hai ý định đối nhau trong một lệnh — không đoán hộ người gõ."""
    with pytest.raises(SystemExit) as exc:
        cli.main([cli.RESET_RATE_LIMIT, cli.AXIS_IP, ROUTE_REGISTER, "172.18.0.1", "--all"])
    assert exc.value.code == 2
    assert "--all" in capsys.readouterr().err


def test_misspelled_group_stops_at_argparse_not_printing_0_keys(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Đây là **lý do** lệnh này có `choices` — xem docstring `app/cli.py`."""
    with pytest.raises(SystemExit) as exc:
        cli.main([cli.RESET_RATE_LIMIT, cli.AXIS_IP, "regsiter", "--all"])
    assert exc.value.code == 2
    assert "regsiter" in capsys.readouterr().err


def test_right_group_wrong_axis_is_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    """`chat` là nhóm thật, nhưng của trục `user` — `rl:ip:chat:*` không tồn tại."""
    with pytest.raises(SystemExit) as exc:
        cli.main([cli.RESET_RATE_LIMIT, cli.AXIS_IP, GROUP_CHAT, "--all"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert GROUP_CHAT in err
    assert ROUTE_REGISTER in err  # có in ra danh sách nhóm hợp lệ của trục


def test_user_axis_requires_uuid_not_any_string(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main([cli.RESET_RATE_LIMIT, cli.AXIS_USER, GROUP_CHAT, "khong-phai-uuid"])
    assert exc.value.code == 2
    assert "UUID" in capsys.readouterr().err


# ───────────────────────── thân lệnh: xoá thật ──────────────────────────────


async def test_clearing_one_ip_touches_only_its_keys(
    keyed_redis: _KeyedRedis, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = await cli._reset_rate_limit(cli.AXIS_IP, ROUTE_REGISTER, "172.18.0.1")

    assert exit_code == 0
    assert ip_key(ROUTE_REGISTER, "172.18.0.1") not in keyed_redis.store
    # Cùng nhóm/IP khác, và cùng IP/nhóm khác: cả hai phải còn nguyên.
    assert ip_key(ROUTE_REGISTER, "203.0.113.9") in keyed_redis.store
    assert ip_key(ROUTE_FORGOT_PASSWORD, "172.18.0.1") in keyed_redis.store
    out = capsys.readouterr().out
    assert "4 luot, con 2871 giay" in out
    assert "1 khoa da xoa" in out


async def test_all_clears_every_ip_of_exactly_one_group(
    keyed_redis: _KeyedRedis, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ngả dùng được khi chạy DoD: người chạy không biết IP Nginx gắn cho mình."""
    exit_code = await cli._reset_rate_limit(cli.AXIS_IP, ROUTE_REGISTER, None)

    assert exit_code == 0
    assert ip_key(ROUTE_REGISTER, "172.18.0.1") not in keyed_redis.store
    assert ip_key(ROUTE_REGISTER, "203.0.113.9") not in keyed_redis.store
    assert ip_key(ROUTE_FORGOT_PASSWORD, "172.18.0.1") in keyed_redis.store
    assert user_key(GROUP_CHAT, USER) in keyed_redis.store
    assert "2 khoa da xoa" in capsys.readouterr().out


async def test_user_axis_clears_token_bucket_of_exactly_one_person(
    keyed_redis: _KeyedRedis,
) -> None:
    exit_code = await cli._reset_rate_limit(cli.AXIS_USER, GROUP_CHAT, str(USER))

    assert exit_code == 0
    assert user_key(GROUP_CHAT, USER) not in keyed_redis.store
    assert ip_key(ROUTE_REGISTER, "172.18.0.1") in keyed_redis.store


async def test_missing_key_is_reported_not_silent(
    keyed_redis: _KeyedRedis, capsys: pytest.CaptureFixture[str]
) -> None:
    """Mã thoát vẫn 0: "không còn gì để gỡ" là kết cục đúng, không phải lỗi."""
    exit_code = await cli._reset_rate_limit(cli.AXIS_IP, ROUTE_REGISTER, "10.0.0.99")

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "khong co" in out
    assert "0 khoa da xoa" in out


# ───────── `IP_GROUPS` không được lệch khỏi `api/v1/auth.py` ─────────────
#
# Cùng lối `tests/workers/test_run_loop.py::test_compose_goi_dung_module`: đọc
# file nguồn để canh một thoả thuận mà không phép gọi nào lúc chạy lộ ra.


def _auth_groups() -> set[str]:
    """Mọi đối số của `gioi_han_gui_email(...)` / `gioi_han_auth(...)` trong auth.py.

    Trả về **tên hằng**; một chuỗi trần lộ ra ở đây dưới dạng giá trị của nó
    trong ngoặc kép, nên ca test bên dưới bắt được cả hai kiểu lệch.
    """
    source = Path(__file__).resolve().parents[2] / "app" / "api" / "v1" / "auth.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"email_send_limit", "auth_limit"}
            and node.args
        ):
            argument = node.args[0]
            out.add(argument.id if isinstance(argument, ast.Name) else ast.unparse(argument))
    return out


def test_auth_py_calls_dependency_with_CONSTANT_not_bare_string() -> None:
    """Một chuỗi trần ở đây là chỗ `IP_GROUPS` bắt đầu lệch — xem B-188."""
    assert _auth_groups() == {
        "ROUTE_REGISTER",
        "ROUTE_RESEND_VERIFICATION",
        "ROUTE_FORGOT_PASSWORD",
        "ROUTE_RESET_PASSWORD",
        "ROUTE_LOGOUT",
    }


def test_every_group_in_IP_GROUPS_has_a_real_route() -> None:
    """Chiều ngược lại: một tên hợp lệ mà không route nào mang cũng là một lệch.

    Nó cho người vận hành một lệnh chạy xong, in "0 khoa", và không cách nào
    biết rằng nhóm ấy chưa từng đếm ai.
    """
    from app.core import ratelimit as rl

    constant_names = {n for n in dir(rl) if n.startswith("ROUTE_")}
    assert _auth_groups() == constant_names
    assert {getattr(rl, n) for n in constant_names} == set(IP_GROUPS)
