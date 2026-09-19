"""Lệnh vận hành chạy tay — `python -m app.cli <lệnh>` (T-2.13).

KH tham chiếu: §10.3, RR-7 · CLAUDE.md A4 · tasks.md T-2.13.

Hôm nay đúng **một** lệnh:

    docker compose exec api python -m app.cli rebuild-quota --all

Chạy **trong container** chứ không từ WSL host: `DATABASE_URL` và `REDIS_URL`
trong `.env` trỏ tới `postgres:5432`/`redis:6379`, tức tên service trên network
`internal` — từ host thì hai tên ấy không phân giải được. Đây cũng là lý do
file này không tự nạp `.env`: `Settings` đọc môi trường của tiến trình (A4,
§19.2), và môi trường ấy do compose bơm vào container.

╔══════════════════════════════════════════════════════════════════════════╗
║  VÌ SAO `argparse` CHỨ KHÔNG PHẢI MỘT THƯ VIỆN CLI                       ║
╚══════════════════════════════════════════════════════════════════════════╝

`click`/`typer` đều tốt hơn cho một CLI có mười lệnh. Ở đây có một, và thêm
một dependency vào `pyproject.toml` cho một lệnh là đổi một thứ mọi người phải
cài lấy một thứ thư viện chuẩn làm được. Ngày lệnh thứ tư ra đời thì đó là
một quyết định đáng cân lại — ghi vào Backlog, không sửa lén ở đây.

╔══════════════════════════════════════════════════════════════════════════╗
║  `--all` LÀ BẮT BUỘC, VÀ ĐÓ LÀ MỘT CÁI PHANH                             ║
╚══════════════════════════════════════════════════════════════════════════╝

`rebuild-quota` trần, không cờ nào, sẽ là một lệnh mà người gõ không nói được
mình định làm gì. Khai `required=True` biến nó thành một lỗi `argparse` đọc
được ngay thay vì một lần chạy im lặng lên toàn bộ người dùng. Cờ `--user
<uuid>` chưa có vì "Việc cần làm" của T-2.13 chỉ ghi `--all`, và với 15–20
người dùng (R1) thì `--all` đã là tập con của chính nó — xem Backlog.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from collections.abc import Coroutine
from typing import Any

from app.config.settings import settings
from app.core.log_redact import install_log_redaction
from app.core.redis import dispose_redis, get_redis
from app.db.session import dispose_engine, session_scope
from app.quota.rebuild import rebuild_all

logger = logging.getLogger(__name__)

REBUILD_QUOTA = "rebuild-quota"


def _dung_logging() -> None:
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

    tong_member = sum(r.members for r in reports)
    print(f"{REBUILD_QUOTA}: {len(reports)} nguoi, {tong_member} member da nap lai")
    for report in reports:
        chi_tiet = "  ".join(
            f"{w.limit_type.value}={w.members} member/{w.spent} USD" for w in report.windows
        )
        print(f"  {report.user_id}  {chi_tiet}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    lenh = parser.add_subparsers(dest="lenh", required=True)
    rebuild = lenh.add_parser(
        REBUILD_QUOTA,
        help="dung lai hai ZSET quota tu usage_events (RR-7, §10.3)",
    )
    rebuild.add_argument(
        "--all",
        action="store_true",
        required=True,
        help="dung lai cho moi nguoi co chi tieu trong cua so dai",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Điểm vào. Trả mã thoát thay vì tự gọi `sys.exit` — để test gọi được.

    Ngoại lệ **không** bị bắt ở đây: một lệnh vận hành hỏng phải để lại
    traceback đầy đủ và một mã thoát khác 0. Nuốt nó thành một dòng "that bai"
    là lấy đi đúng thứ người đang sửa cần đọc.
    """
    args = _parser().parse_args(argv)
    _dung_logging()
    if args.lenh == REBUILD_QUOTA:
        return asyncio.run(_chay(_rebuild_quota_all()))
    raise AssertionError(f"lenh khong co nguoi xu ly: {args.lenh}")


async def _chay(coro: Coroutine[Any, Any, int]) -> int:
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
