"""`Settings` và `.env.example` phải khớp nhau, và phải fail-fast (S1).

DoD của T-0.3: mọi biến trong `.env.example` xuất hiện trong `Settings`, và
ngược lại. Hai chiều, vì lệch chiều nào cũng đau: thiếu ở `Settings` là biến
chết, thiếu ở `.env.example` là biến vô hình cho người vận hành.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config.settings import MIN_SECRET_CHARS, Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"
_ASSIGNMENT = re.compile(r"^([A-Z][A-Z0-9_]*)=")

#: Biến chỉ dành cho docker compose, backend không đọc — NQ-08.
#: Thêm vào đây là một quyết định, không phải cách vá test: mỗi tên ở đây phải
#: chỉ ra được service nào trong `docker-compose.yml` dùng nó.
COMPOSE_ONLY = frozenset({"POSTGRES_PASSWORD"})


def env_example_keys() -> set[str]:
    return {
        m.group(1)
        for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if (m := _ASSIGNMENT.match(line.strip()))
    }


REQUIRED_FIELDS = sorted(
    name for name, field in Settings.model_fields.items() if field.is_required()
)


def test_env_example_ton_tai() -> None:
    assert ENV_EXAMPLE.is_file(), f"không tìm thấy {ENV_EXAMPLE}"
    assert env_example_keys(), ".env.example không có dòng gán biến nào"


def test_moi_bien_trong_env_example_deu_co_trong_settings() -> None:
    thieu = env_example_keys() - COMPOSE_ONLY - set(Settings.model_fields)
    assert not thieu, f"có trong .env.example nhưng thiếu trong Settings: {sorted(thieu)}"


def test_moi_field_cua_settings_deu_co_trong_env_example() -> None:
    thieu = set(Settings.model_fields) - env_example_keys()
    assert not thieu, f"có trong Settings nhưng thiếu trong .env.example: {sorted(thieu)}"


def test_danh_sach_compose_only_khong_muc_ruong() -> None:
    """Tên đã miễn trừ mà biến mất khỏi `.env.example` thì phải gỡ khỏi danh sách."""
    thua = COMPOSE_ONLY - env_example_keys()
    assert not thua, f"COMPOSE_ONLY còn tên không có trong .env.example: {sorted(thua)}"


def test_compose_only_khong_lan_vao_settings() -> None:
    """Biến của compose lọt vào `Settings` nghĩa là backend đang đọc thứ không phải của nó."""
    lan = COMPOSE_ONLY & set(Settings.model_fields)
    assert not lan, f"COMPOSE_ONLY trùng field của Settings: {sorted(lan)}"


def test_co_it_nhat_mot_bien_bat_buoc() -> None:
    assert REQUIRED_FIELDS, "không có biến bắt buộc nào — fail-fast trở thành vô nghĩa"


@pytest.mark.parametrize("name", REQUIRED_FIELDS)
def test_thieu_bien_bat_buoc_thi_raise_va_in_dung_ten(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValidationError) as exc:
        Settings()
    assert name in str(exc.value)


@pytest.mark.parametrize("name", ["JWT_SECRET", "MASTER_ENCRYPTION_KEY"])
def test_secret_ngan_bi_tu_choi(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv(name, "short")
    with pytest.raises(ValidationError) as exc:
        Settings()
    message = str(exc.value)
    assert name in message
    assert str(MIN_SECRET_CHARS) in message


@pytest.mark.parametrize("name", ["LITELLM_MASTER_KEY", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY"])
def test_secret_bat_buoc_de_rong_bi_tu_choi(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv(name, "")
    with pytest.raises(ValidationError) as exc:
        Settings()
    assert name in str(exc.value)


def test_canh_bao_khi_turnstile_secret_rong(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("TURNSTILE_SECRET", raising=False)
    with caplog.at_level("WARNING", logger="app.config.settings"):
        Settings()
    assert "TURNSTILE_SECRET" in caplog.text


def test_bien_la_trong_moi_truong_khong_lam_hong_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`extra="forbid"` chỉ chặn tham số khởi tạo, không chặn biến môi trường lạ.

    Compose nạp cả `.env` cho `api`, nên `POSTGRES_PASSWORD` và mọi biến của
    service khác đều nằm trong môi trường của backend (NQ-08).
    """
    monkeypatch.setenv("POSTGRES_PASSWORD", "CHANGE_ME")
    monkeypatch.setenv("MOT_BIEN_KHONG_AI_KHAI", "x")
    assert Settings().MINIO_BUCKET == "scarlet"


def test_base_url_khong_bi_them_dau_gach_cheo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://scarlet.example/")
    assert Settings().PUBLIC_BASE_URL == "https://scarlet.example"


def test_import_module_co_san_instance_settings() -> None:
    from app.config import settings as module

    assert isinstance(module.settings, Settings)
