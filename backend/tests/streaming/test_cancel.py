"""T-1.9 — `app/streaming/cancel.py`: hợp đồng cờ huỷ giữa `api` và `worker` (§7.5).

File này kiểm đúng ba thứ mà hai tiến trình phải hiểu giống nhau: hình dạng
khoá, việc `SET` có kèm TTL, và việc `EXISTS` ra một `bool`.

Vì sao đáng một file riêng: khoá là thứ DUY NHẤT nối `POST /messages/{id}/cancel`
với vòng lặp trong `workers/generate.py`, và nếu hai đầu gõ lệch tiền tố thì
**không có gì báo lỗi** — nút Dừng chỉ đơn giản không bao giờ dừng được gì.
Cùng lý do `tests/streaming/test_producer.py` khoá `stream_key()` lại.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.streaming.cancel import (
    CANCEL_KEY_PREFIX,
    FINISH_REASON_CANCELLED,
    GIA_TRI_CO,
    cancel_key,
    da_yeu_cau_huy,
    dat_co_huy,
)


class RedisGia:
    """Chỉ đủ `set`/`exists`, và ghi lại mọi tham số để khẳng định được."""

    def __init__(self) -> None:
        self.da_set: list[tuple[str, str, Any]] = []
        self.co: set[str] = set()

    async def set(self, name: str, value: str, *, ex: int | None = None) -> bool:
        self.da_set.append((name, value, ex))
        self.co.add(name)
        return True

    async def exists(self, name: str) -> int:
        return 1 if name in self.co else 0


def test_khoa_dung_tien_to_cua_ke_hoach() -> None:
    """§7.5 viết `cancel:{amid}`. UUID và chuỗi phải ra cùng một khoá."""
    mid = uuid.uuid4()

    assert cancel_key(mid) == f"cancel:{mid}"
    assert cancel_key(str(mid)) == cancel_key(mid)
    assert CANCEL_KEY_PREFIX == "cancel:"


async def test_dat_co_co_kem_ttl() -> None:
    """`SET cancel:{id} 1 EX <ttl>` — thiếu `EX` là C8 ở dạng thứ hai."""
    redis = RedisGia()
    mid = uuid.uuid4()

    await dat_co_huy(redis, mid, ttl_s=300)

    assert redis.da_set == [(f"cancel:{mid}", GIA_TRI_CO, 300)]


async def test_dat_co_hai_lan_gia_han_dong_ho() -> None:
    """Bấm Dừng lần hai phải đặt lại TTL, không giữ đồng hồ của lần đầu.

    Đây là lý do `cancel.py` dùng `SET` chứ không `SETNX`: lần bấm thứ hai
    nghĩa là người dùng **vẫn** đang chờ nó dừng.
    """
    redis = RedisGia()
    mid = uuid.uuid4()

    await dat_co_huy(redis, mid, ttl_s=300)
    await dat_co_huy(redis, mid, ttl_s=300)

    assert len(redis.da_set) == 2
    assert {ex for _, _, ex in redis.da_set} == {300}


@pytest.mark.parametrize("dat_truoc", [True, False])
async def test_doc_co_tra_ve_bool(dat_truoc: bool) -> None:
    redis = RedisGia()
    mid = uuid.uuid4()
    if dat_truoc:
        await dat_co_huy(redis, mid, ttl_s=300)

    ket_qua = await da_yeu_cau_huy(redis, mid)

    assert ket_qua is dat_truoc
    assert isinstance(ket_qua, bool), "chỗ gọi là một câu `if`, không phải một phép so số"


async def test_co_cua_message_nay_khong_anh_huong_message_kia() -> None:
    """Một khoá cho mỗi message — huỷ lượt này không dừng lượt đang chạy song song."""
    redis = RedisGia()
    mot, hai = uuid.uuid4(), uuid.uuid4()

    await dat_co_huy(redis, mot, ttl_s=300)

    assert await da_yeu_cau_huy(redis, mot) is True
    assert await da_yeu_cau_huy(redis, hai) is False


def test_finish_reason_la_chuoi_cua_ke_hoach() -> None:
    """§7.5: `UPDATE finish_reason='cancelled'`. FE phân nhánh theo đúng chuỗi này."""
    assert FINISH_REASON_CANCELLED == "cancelled"
