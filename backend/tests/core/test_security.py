"""`app/core/security.py` — Argon2id hash/verify + kiểm mật khẩu (§11.6, T-2.1).

DoD T-2.1:
  - `SELECT password_hash FROM users` bắt đầu bằng `$argon2id$`
  - Thời gian hash 50–200 ms (đo lại ở đây, và xem thêm `pytest --durations`)
  - `password1234` → coi là quá phổ biến
"""

from __future__ import annotations

import time

import pytest

from app.core.security import hash_password, mat_khau_qua_pho_bien, verify_password


async def test_hash_bat_dau_bang_argon2id() -> None:
    hash_value = await hash_password("mot-mat-khau-du-manh-123")
    assert hash_value.startswith("$argon2id$")


async def test_verify_dung_mat_khau_tra_true() -> None:
    password = "mot-mat-khau-du-manh-123"
    hash_value = await hash_password(password)
    assert await verify_password(hash_value, password) is True


async def test_verify_sai_mat_khau_tra_false() -> None:
    hash_value = await hash_password("mot-mat-khau-du-manh-123")
    assert await verify_password(hash_value, "sai-mat-khau-khac") is False


async def test_verify_hash_hong_tra_false_khong_raise() -> None:
    """Hash không đúng định dạng PHC — không được để lộ ra thành 500."""
    assert await verify_password("khong-phai-mot-hash-argon2", "gi-cung-duoc") is False


async def test_thoi_gian_hash_trong_khoang_50_200ms() -> None:
    """DoD T-2.1: "Thời gian hash 50–200 ms" — quá nhanh nghĩa là tham số quá yếu."""
    bat_dau = time.perf_counter()
    await hash_password("mot-mat-khau-du-manh-123")
    thoi_gian_s = time.perf_counter() - bat_dau

    assert 0.05 <= thoi_gian_s <= 0.2, (
        f"hash mat {thoi_gian_s * 1000:.1f} ms, ngoai khoang 50-200 ms"
    )


@pytest.mark.parametrize(
    "password",
    ["password1234", "12345678901234", "qwertyuiop123", "iloveyou1234567"],
)
def test_mat_khau_pho_bien_bi_coi_la_qua_yeu(password: str) -> None:
    assert mat_khau_qua_pho_bien(password) is True


@pytest.mark.parametrize(
    "password",
    ["xK9#mP2!qR4w$vN8bL5", "Tr0ub4dor&3xyzQQ", "correct horse battery staple long random"],
)
def test_mat_khau_manh_khong_bi_coi_la_qua_yeu(password: str) -> None:
    assert mat_khau_qua_pho_bien(password) is False
