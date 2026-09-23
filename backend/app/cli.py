"""Lệnh vận hành chạy tay — `python -m app.cli <lệnh>` (T-2.13).

KH tham chiếu: §10.3, RR-7 · CLAUDE.md A4 · tasks.md T-2.13.

Hôm nay **hai** lệnh:

    docker compose exec api python -m app.cli rebuild-quota --all
    docker compose exec api python -m app.cli reset-rate-limit ip register --all

Chạy **trong container** chứ không từ WSL host: `DATABASE_URL` và `REDIS_URL`
trong `.env` trỏ tới `postgres:5432`/`redis:6379`, tức tên service trên network
`internal` — từ host thì hai tên ấy không phân giải được. Đây cũng là lý do
file này không tự nạp `.env`: `Settings` đọc môi trường của tiến trình (A4,
§19.2), và môi trường ấy do compose bơm vào container.

╔══════════════════════════════════════════════════════════════════════════╗
║  VÌ SAO `argparse` CHỨ KHÔNG PHẢI MỘT THƯ VIỆN CLI                       ║
╚══════════════════════════════════════════════════════════════════════════╝

`click`/`typer` đều tốt hơn cho một CLI có mười lệnh. Ở đây có hai, và thêm
một dependency vào `pyproject.toml` cho hai lệnh là đổi một thứ mọi người phải
cài lấy một thứ thư viện chuẩn làm được. B-163 đặt mốc cân lại ở **lệnh thứ
tư** chứ không lệnh thứ hai, và lệnh thứ hai (B-188) không đòi gì `argparse`
không có sẵn: hai subparser, một nhóm loại trừ, một `choices`. Xem NQ-89.

╔══════════════════════════════════════════════════════════════════════════╗
║  `--all` LÀ BẮT BUỘC, VÀ ĐÓ LÀ MỘT CÁI PHANH                             ║
╚══════════════════════════════════════════════════════════════════════════╝

`rebuild-quota` trần, không cờ nào, sẽ là một lệnh mà người gõ không nói được
mình định làm gì. Khai `required=True` biến nó thành một lỗi `argparse` đọc
được ngay thay vì một lần chạy im lặng lên toàn bộ người dùng. Cờ `--user
<uuid>` chưa có vì "Việc cần làm" của T-2.13 chỉ ghi `--all`, và với 15–20
người dùng (R1) thì `--all` đã là tập con của chính nó — xem Backlog.

`reset-rate-limit` chép đúng cái phanh ấy: hoặc một định danh, hoặc `--all`,
không bao giờ cả hai và không bao giờ không có cái nào.

╔══════════════════════════════════════════════════════════════════════════╗
║  `reset-rate-limit` — B-188                                              ║
╚══════════════════════════════════════════════════════════════════════════╝

B-188 ghi nguyên văn: *"đường duy nhất đi tiếp hôm nay là `redis-cli DEL
rl:ip:register:<ip>`, tức người chạy phải biết cả tên khoá lẫn quy ước đặt
tên"*. Lệnh này lấy đi cả hai đòi hỏi đó, và lấy thêm một đòi hỏi thứ ba mà
B-188 không nêu tên: **người chạy cũng không biết IP của chính mình**.
`X-Real-IP` do Nginx đặt là địa chỉ của host trên network `internal`, không
phải thứ đọc được từ trình duyệt — nên `--all` (xoá mọi IP của một nhóm) là
ngả thật sự dùng được khi chạy DoD, còn dạng một định danh là ngả của lúc
vận hành thật, khi đã biết mình cần gỡ cho ai.

**Vì sao `choices` chứ không nhận bất cứ chuỗi nào.** Một tên nhóm gõ sai cho
ra một lệnh chạy xong, mã thoát 0, in "0 khoa" — và người vận hành đọc nó
thành "hạn mức đã tự hết hạn" rồi bấm tiếp và lại `429`. Đúng triệu chứng
B-188 mô tả, chỉ lùi thêm một bước. Danh sách nhóm hợp lệ **không** được chép
vào file này: nó là `IP_GROUPS`/`GROUP_CHAT` của `core/ratelimit.py`, cùng
chỗ với `ip_key`/`user_key`.

**Vì sao `SCAN` chứ không `KEYS`.** `KEYS` chặn Redis trong suốt lượt quét, và
Redis ở đây là phụ thuộc cứng của cả app (A1) — một lệnh vận hành không được
phép dừng mọi lượt stream đang chảy để tìm một khoá.

**Trục `streams` cố ý KHÔNG có mặt.** `rl:streams:{uuid}` là ZSET ghế bận của
§10.6 hàng 3, và nó đã có đường tự nhả (`release_generation_seat` + đối chiếu Postgres +
`PHANTOM_GRACE_S`). Thêm một đường xoá tay cạnh một đường tự nhả là mời người
vận hành dùng cái thứ hai thay vì sửa cái thứ nhất khi nó kẹt.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
import uuid
from collections.abc import Coroutine
from typing import Any

from app.config.settings import settings
from app.core.log_redact import install_log_redaction
from app.core.ratelimit import (
    GROUP_CHAT,
    IP_GROUPS,
    ip_key,
    ip_key_pattern,
    user_key,
    user_key_pattern,
)
from app.core.redis import dispose_redis, get_redis
from app.db.session import dispose_engine, session_scope
from app.quota.rebuild import rebuild_all

logger = logging.getLogger(__name__)

REBUILD_QUOTA = "rebuild-quota"
RESET_RATE_LIMIT = "reset-rate-limit"

#: Hai trục của `reset-rate-limit`, khớp hai lớp đầu của §10.6. Xem docstring
#: module cho lý do trục `streams` vắng mặt.
AXIS_IP = "ip"
AXIS_USER = "user"

#: Nhóm hợp lệ theo trục. **Tham chiếu**, không phải bản chép: cả hai vế đều
#: sống ở `core/ratelimit.py` cạnh chính hàm dựng khoá.
GROUPS_BY_AXIS: dict[str, tuple[str, ...]] = {
    AXIS_IP: IP_GROUPS,
    AXIS_USER: (GROUP_CHAT,),
}


def _setup_logging() -> None:
    """Gắn handler cho cây logger `app.*` — cùng thân với `workers/main.py`.

    Không có nó thì mọi `logger.info` của `quota/rebuild.py` rơi vào
    `lastResort` của Python (chỉ WARNING trở lên, ra stderr, không timestamp)
    — tức một lệnh vận hành chạy xong mà không in ra nó đã làm gì.
    """
    # C20 (T-2.14) — trước cả `return` sớm: bộ che là của TIẾN TRÌNH,
    # không của handler, nên nó phải được cài kể cả khi handler đã có.
    install_log_redaction()
    app_logger = logging.getLogger("app")
    if app_logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s: %(message)s", datefmt="%H:%M:%S"))
    app_logger.addHandler(handler)
    app_logger.setLevel(settings.LOG_LEVEL)
    app_logger.propagate = False


async def _rebuild_quota_all() -> int:
    """Thân của `rebuild-quota --all`. Trả về mã thoát.

    **Một** `now` cho cả lượt chạy, lấy trước vòng lặp: hai người dùng cạnh
    nhau trong danh sách không được nhận hai biên cửa sổ khác nhau chỉ vì lượt
    chạy mất vài giây.

    `commit()` không cần và cố ý không có: cả ba câu truy vấn của đường này
    đều là `SELECT`. Thứ duy nhất bị ghi nằm ở Redis.
    """
    now = time.time()
    async with session_scope() as session:
        reports = await rebuild_all(session, get_redis(), now=now)

    total_members = sum(r.members for r in reports)
    print(f"{REBUILD_QUOTA}: {len(reports)} nguoi, {total_members} member da nap lai")
    for report in reports:
        details = "  ".join(
            f"{w.limit_type.value}={w.members} member/{w.spent} USD" for w in report.windows
        )
        print(f"  {report.user_id}  {details}")
    return 0


async def _reset_rate_limit(axis: str, group: str, identity: str | None) -> int:
    """Thân của `reset-rate-limit`. Trả về mã thoát.

    `identity is None` nghĩa là `--all` — `_parser` đã ép đúng một trong hai
    có mặt, nên ở đây không có nhánh thứ ba.

    In `TTL` của từng khoá **trước** khi xoá, không chỉ tên nó. Một dòng
    `rl:ip:register:172.18.0.1  4 luot, con 2871 giay` nói cho người vận hành
    biết họ vừa gỡ đúng thứ đang chặn mình; một dòng chỉ có tên khoá thì
    không phân biệt được "gỡ đúng" với "gỡ nhầm một khoá cùng tên nhóm của
    người khác".

    Mã thoát **0 kể cả khi không có khoá nào**: "không còn gì để gỡ" là một
    kết cục đúng của lệnh này, không phải một lần chạy hỏng.
    """
    redis = get_redis()

    if identity is None:
        pattern = ip_key_pattern(group) if axis == AXIS_IP else user_key_pattern(group)
        # SCAN chứ không KEYS — xem docstring module. `scan_iter` tự lặp cursor.
        keys = [k async for k in redis.scan_iter(match=pattern, count=100)]
    elif axis == AXIS_IP:
        keys = [ip_key(group, identity)]
    else:
        keys = [user_key(group, uuid.UUID(identity))]

    deleted = 0
    for key in sorted(_to_str(k) for k in keys):
        value = await redis.get(key) if axis == AXIS_IP else None
        ttl = int(await redis.ttl(key))
        if int(await redis.delete(key)) == 0:
            # Khoá không tồn tại. Nói ra chứ không im lặng: với dạng một định
            # danh, đây là ca thường gặp nhất và cũng là ca dễ đọc nhầm nhất.
            print(f"  {key}  khong co (han muc nay chua/khong con bi dem)")
            continue
        deleted += 1
        description = f"con {ttl} giay" if ttl >= 0 else "khong co TTL"
        count = f"{_to_str(value)} luot, " if value is not None else ""
        print(f"  {key}  {count}{description}  -> da xoa")

    print(f"{RESET_RATE_LIMIT}: {deleted} khoa da xoa")
    return 0


def _to_str(value: Any) -> str:
    """`bytes` → `str`. Client thật trả `bytes`, Redis giả của test trả `str`."""
    return value.decode() if isinstance(value, bytes) else str(value)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="lenh", required=True)
    rebuild = commands.add_parser(
        REBUILD_QUOTA,
        help="dung lai hai ZSET quota tu usage_events (RR-7, §10.3)",
    )
    rebuild.add_argument(
        "--all",
        action="store_true",
        required=True,
        help="dung lai cho moi nguoi co chi tieu trong cua so dai",
    )

    reset = commands.add_parser(
        RESET_RATE_LIMIT,
        help="xoa bo dem rate limit cua mot (truc, nhom, dinh danh) — §10.6, B-188",
    )
    reset.add_argument("truc", choices=sorted(GROUPS_BY_AXIS), help="truc dem")
    reset.add_argument(
        "nhom",
        # Hợp của cả hai trục: `choices` của argparse không đọc được giá trị
        # của một positional khác. Cặp (trục, nhóm) được kiểm ngay bên dưới,
        # nơi biết cả hai.
        choices=sorted({n for ds in GROUPS_BY_AXIS.values() for n in ds}),
        help="ten route (truc ip) hoac ten nhom route (truc user)",
    )
    reset.add_argument(
        "dinh_danh",
        nargs="?",
        metavar="DINH-DANH",
        help="dia chi IP (truc ip) hoac user_id dang UUID (truc user)",
    )
    reset.add_argument(
        "--all",
        action="store_true",
        help="xoa MOI dinh danh cua nhom nay — dung khi khong biet IP cua chinh minh",
    )
    return parser


def _check_reset(parser: argparse.ArgumentParser, args: argparse.Namespace) -> str | None:
    """Kiểm ba thứ `argparse` không tự kiểm được, rồi trả `dinh_danh` đã chuẩn hoá.

    `parser.error` chứ không `ApiError`/`raise`: mã thoát 2 và một dòng trợ
    giúp là ngôn ngữ mà người gõ nhầm một lệnh vận hành đang chờ đọc.
    """
    if args.all == (args.dinh_danh is not None):
        parser.error("can dung MOT trong hai: mot DINH-DANH, hoac --all")
    if args.nhom not in GROUPS_BY_AXIS[args.truc]:
        valid = " ".join(GROUPS_BY_AXIS[args.truc])
        parser.error(f"truc {args.truc!r} khong co nhom {args.nhom!r}; nhom hop le: {valid}")
    if args.truc == AXIS_USER and args.dinh_danh is not None:
        # Kiểm ở đây chứ không trong thân lệnh: một `ValueError` của
        # `uuid.UUID` giữa lượt chạy là một traceback, không phải một lời chỉ
        # ra chỗ gõ sai.
        try:
            uuid.UUID(args.dinh_danh)
        except ValueError:
            parser.error(
                f"truc {AXIS_USER} can mot user_id dang UUID, nhan duoc {args.dinh_danh!r}"
            )
    return args.dinh_danh


def main(argv: list[str] | None = None) -> int:
    """Điểm vào. Trả mã thoát thay vì tự gọi `sys.exit` — để test gọi được.

    Ngoại lệ **không** bị bắt ở đây: một lệnh vận hành hỏng phải để lại
    traceback đầy đủ và một mã thoát khác 0. Nuốt nó thành một dòng "that bai"
    là lấy đi đúng thứ người đang sửa cần đọc.
    """
    parser = _parser()
    args = parser.parse_args(argv)
    _setup_logging()
    if args.lenh == REBUILD_QUOTA:
        return asyncio.run(_run(_rebuild_quota_all()))
    if args.lenh == RESET_RATE_LIMIT:
        identity = _check_reset(parser, args)
        return asyncio.run(_run(_reset_rate_limit(args.truc, args.nhom, identity)))
    raise AssertionError(f"lenh khong co nguoi xu ly: {args.lenh}")


async def _run(coro: Coroutine[Any, Any, int]) -> int:
    """Chạy một lệnh rồi đóng cả hai pool.

    Engine và client Redis dựng **lười** (xem `db/session.py`,
    `core/redis.py`), nên chúng chỉ tồn tại nếu lệnh thật sự chạm tới — nhưng
    lệnh nào cũng phải đóng chúng, nếu không `asyncio.run` kết thúc với một
    kết nối chưa đóng và in ra một `ResourceWarning` giữa output vận hành.
    """
    try:
        return await coro
    finally:
        await dispose_redis()
        await dispose_engine()


if __name__ == "__main__":  # pragma: no cover - điểm vào tiến trình
    sys.exit(main())
