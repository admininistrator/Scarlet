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

from app.config.settings import MIN_SECRET_CHARS, Settings, load_settings

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"
_ASSIGNMENT = re.compile(r"^([A-Z][A-Z0-9_]*)=")

#: Biến chỉ dành cho docker compose, backend không đọc — NQ-08.
#: Thêm vào đây là một quyết định, không phải cách vá test: mỗi tên ở đây phải
#: chỉ ra được service nào trong `docker-compose.yml` dùng nó.
#: - POSTGRES_PASSWORD: service `postgres`
#: - VITE_API_BASE_URL: service `web` (T-0.10) — Vite đọc lúc build/dev, không
#:   phải app Python
COMPOSE_ONLY = frozenset({"POSTGRES_PASSWORD", "VITE_API_BASE_URL"})

#: Biến chỉ dành cho pytest — backend KHÔNG đọc, docker compose cũng không.
#: Cùng lý do tồn tại như COMPOSE_ONLY, khác nguồn đọc, nên tách set riêng để
#: không làm nhoè nghĩa "biến của compose".
#: - TEST_DATABASE_URL: tests/db/conftest.py (T-1.1) — database `scarlet_test`
#:   riêng trên instance postgres của dev; đưa nó vào `Settings` sẽ là bắt app
#:   production khai một biến chỉ có nghĩa lúc chạy test.
TEST_ONLY = frozenset({"TEST_DATABASE_URL"})

#: Biến chỉ dành cho script trong `scripts/` — backend không đọc, compose không
#: đọc, pytest cũng không. Tách set riêng vì cùng lý lẽ với hai set trên: tên
#: nào ở đây phải chỉ ra được **file nào** đọc nó.
#: - DEV_DATABASE_URL: `scripts/test_resume.py` (T-1.11) — database `scarlet`
#:   của dev nhìn từ WSL host. Đưa vào `Settings` sẽ là bắt app production khai
#:   một biến chỉ có nghĩa khi đo S3 trên máy dev.
#: - DEV_LITELLM_BASE_URL: `scripts/bench_ttft.py` (T-1.12) — LiteLLM nhìn từ
#:   WSL host, cho đường "baseline" gọi thẳng provider. Cùng lý lẽ: app đọc
#:   LITELLM_BASE_URL (`litellm:4000`, chỉ sống trong network `internal`).
SCRIPT_ONLY = frozenset({"DEV_DATABASE_URL", "DEV_LITELLM_BASE_URL"})

#: Ba nhóm trên gộp lại: những tên được phép có trong `.env.example` mà không
#: có trong `Settings`.
OUTSIDE_SETTINGS = COMPOSE_ONLY | TEST_ONLY | SCRIPT_ONLY


def env_example_keys() -> set[str]:
    return {
        m.group(1)
        for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if (m := _ASSIGNMENT.match(line.strip()))
    }


REQUIRED_FIELDS = sorted(
    name for name, field in Settings.model_fields.items() if field.is_required()
)


def test_env_example_exists() -> None:
    assert ENV_EXAMPLE.is_file(), f"không tìm thấy {ENV_EXAMPLE}"
    assert env_example_keys(), ".env.example không có dòng gán biến nào"


def test_every_env_example_var_is_in_settings() -> None:
    missing = env_example_keys() - OUTSIDE_SETTINGS - set(Settings.model_fields)
    assert not missing, f"có trong .env.example nhưng thiếu trong Settings: {sorted(missing)}"


def test_every_settings_field_is_in_env_example() -> None:
    missing = set(Settings.model_fields) - env_example_keys()
    assert not missing, f"có trong Settings nhưng thiếu trong .env.example: {sorted(missing)}"


def test_compose_only_list_has_no_dead_entries() -> None:
    """Tên đã miễn trừ mà biến mất khỏi `.env.example` thì phải gỡ khỏi danh sách."""
    loser = OUTSIDE_SETTINGS - env_example_keys()
    assert not loser, f"danh sách miễn trừ còn tên không có trong .env.example: {sorted(loser)}"


def test_compose_only_stays_out_of_settings() -> None:
    """Biến của compose/pytest lọt vào Settings nghĩa là backend đọc thứ không phải của nó."""
    leaked = OUTSIDE_SETTINGS & set(Settings.model_fields)
    assert not leaked, f"danh sách miễn trừ trùng field của Settings: {sorted(leaked)}"


def test_at_least_one_required_var() -> None:
    assert REQUIRED_FIELDS, "không có biến bắt buộc nào — fail-fast trở thành vô nghĩa"


@pytest.mark.parametrize("name", REQUIRED_FIELDS)
def test_missing_required_var_raises_and_prints_its_name(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValidationError) as exc:
        Settings()
    assert name in str(exc.value)


@pytest.mark.parametrize("name", ["JWT_SECRET", "MASTER_ENCRYPTION_KEY"])
def test_short_secret_is_rejected(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv(name, "short")
    with pytest.raises(ValidationError) as exc:
        Settings()
    message = str(exc.value)
    assert name in message
    assert str(MIN_SECRET_CHARS) in message


def test_load_settings_missing_var_exits_with_its_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """S1 qua ``load_settings()`` — đường mà ``settings = …`` lúc import đi (B-18)."""
    name = REQUIRED_FIELDS[0]
    monkeypatch.delenv(name, raising=False)
    with pytest.raises(SystemExit) as exc:
        load_settings()
    assert name in str(exc.value.code)
    assert "missing" in str(exc.value.code)


def test_load_settings_bad_secret_message_has_name_not_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B-18: ``str(ValidationError)`` mang ``input_value='…'`` — secret yếu vào log."""
    value = "short-B18-CANARY"
    monkeypatch.setenv("JWT_SECRET", value)
    with pytest.raises(ValidationError) as raw:
        Settings()
    assert value in str(raw.value), "đối chứng: pydantic tự nó có in giá trị"
    with pytest.raises(SystemExit) as exc:
        load_settings()
    message = str(exc.value.code)
    assert "JWT_SECRET" in message and "value_error" in message
    assert value not in message
    assert exc.value.__cause__ is None and exc.value.__suppress_context__


@pytest.mark.parametrize("name", ["LITELLM_MASTER_KEY", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY"])
def test_required_secret_left_empty_is_rejected(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv(name, "")
    with pytest.raises(ValidationError) as exc:
        Settings()
    assert name in str(exc.value)


def test_warns_when_turnstile_secret_empty(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("TURNSTILE_SECRET", raising=False)
    with caplog.at_level("WARNING", logger="app.config.settings"):
        Settings()
    assert "TURNSTILE_SECRET" in caplog.text


def test_unknown_env_var_does_not_break_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`extra="forbid"` chỉ chặn tham số khởi tạo, không chặn biến môi trường lạ.

    Compose nạp cả `.env` cho `api`, nên `POSTGRES_PASSWORD` và mọi biến của
    service khác đều nằm trong môi trường của backend (NQ-08).
    """
    monkeypatch.setenv("POSTGRES_PASSWORD", "CHANGE_ME")
    monkeypatch.setenv("MOT_BIEN_KHONG_AI_KHAI", "x")
    assert Settings().MINIO_BUCKET == "scarlet"


def test_base_url_gets_no_extra_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://scarlet.example/")
    assert Settings().PUBLIC_BASE_URL == "https://scarlet.example"


def test_sandbox_base_url_must_be_unix_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    # T-7.2: `sandbox` không có mạng (ADR-09) ⇒ URL HTTP là cấu hình hỏng, chặn lúc boot.
    monkeypatch.setenv("SANDBOX_BASE_URL", "http://sandbox:8090")
    with pytest.raises(ValidationError):
        Settings()
    monkeypatch.setenv("SANDBOX_BASE_URL", "unix:///run/sandbox/sandbox.sock")
    assert Settings().SANDBOX_BASE_URL == "unix:///run/sandbox/sandbox.sock"


def test_module_import_provides_settings_instance() -> None:
    from app.config import settings as module

    assert isinstance(module.settings, Settings)
