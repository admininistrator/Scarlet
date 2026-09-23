"""`app/core/security.py` — Argon2id hash/verify + kiểm mật khẩu (§11.6, T-2.1).

DoD T-2.1:
  - `SELECT password_hash FROM users` bắt đầu bằng `$argon2id$`
  - Thời gian hash 50–200 ms (đo lại ở đây, và xem thêm `pytest --durations`)
  - `password1234` → coi là quá phổ biến
"""

from __future__ import annotations

import time

import pytest

from app.core.security import hash_password, is_common_password, verify_password


async def test_hash_starts_with_argon2id() -> None:
    hash_value = await hash_password("mot-mat-khau-du-manh-123")
    assert hash_value.startswith("$argon2id$")


async def test_verify_right_password_is_true() -> None:
    password = "mot-mat-khau-du-manh-123"
    hash_value = await hash_password(password)
    assert await verify_password(hash_value, password) is True


async def test_verify_wrong_password_is_false() -> None:
    hash_value = await hash_password("mot-mat-khau-du-manh-123")
    assert await verify_password(hash_value, "sai-mat-khau-khac") is False


async def test_verify_broken_hash_is_false_not_raise() -> None:
    """Hash không đúng định dạng PHC — không được để lộ ra thành 500."""
    assert await verify_password("khong-phai-mot-hash-argon2", "gi-cung-duoc") is False


async def test_hash_time_within_50_200ms() -> None:
    """DoD T-2.1: "Thời gian hash 50–200 ms" — quá nhanh nghĩa là tham số quá yếu."""
    started = time.perf_counter()
    await hash_password("mot-mat-khau-du-manh-123")
    elapsed_s = time.perf_counter() - started

    assert 0.05 <= elapsed_s <= 0.2, f"hash mat {elapsed_s * 1000:.1f} ms, ngoai khoang 50-200 ms"


@pytest.mark.parametrize(
    "password",
    ["password1234", "12345678901234", "qwertyuiop123", "iloveyou1234567"],
)
def test_common_password_deemed_too_weak(password: str) -> None:
    assert is_common_password(password) is True


@pytest.mark.parametrize(
    "password",
    ["xK9#mP2!qR4w$vN8bL5", "Tr0ub4dor&3xyzQQ", "correct horse battery staple long random"],
)
def test_strong_password_not_deemed_too_weak(password: str) -> None:
    assert is_common_password(password) is False
