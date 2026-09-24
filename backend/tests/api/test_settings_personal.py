"""`PUT /settings` — model mặc định theo NGƯỜI (§18.4, UC-05) — T-3.0, B-206;
hồ sơ + mức suy luận đã nhớ (§24.2b·S4, S10) — T-S.5.

Chín nhóm, mỗi nhóm đặt tên theo **thứ nó chặn**:

1. Ghi rồi đọc lại qua `GET /auth/me` — hai endpoint, một sự thật.
2. Model lạ hoặc đã tắt ⇒ `400 MODEL_UNKNOWN`, và **không** ghi gì.
3. `null` bỏ chọn được — nếu không thì người dùng chọn xong là kẹt.
4. Validate lúc **GHI**, không lúc đọc: model biến khỏi catalog sau đó vẫn đọc
   ra bình thường (Cạm bẫy ③ của T-3.0).
5. §20 — không tham số nào trỏ sang người khác, và hai người không thấy nhau.
6. `PUT` thay **cả** tài nguyên — hành vi có chủ ý (§18.4, S10, T-S.5 DoD 2).
7. Mức suy luận: kiểm từng cặp theo catalog lúc ghi, bỏ qua cặp hết hợp lệ
   lúc đọc (T-S.5 Việc 1, 4).
8. Tên hiển thị: rỗng ⇒ `NULL`, trần đếm theo ký tự (T-S.5 Cạm bẫy ②, ③).
9. Tên màu avatar: chỉ hình dạng, không mã màu (A3, NQ-116).

A3: không gõ tên model hay tên mức vào file này — mọi thứ lấy từ catalog đang
nạp, nên test vẫn đúng khi `model_catalog.json` đổi. Phép đo với đúng hai tên
của DoD dòng 3 chạy trên stack thật, không ở đây.

Hạ tầng giống `test_settings_keys.py`: `httpx.ASGITransport`, `session_scope()`
trỏ về đúng kết nối của test, Redis giả cho blacklist. Bộ test này **không**
đụng BYOK nên không cần `MockTransport` của provider.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import catalog
from app.config.settings import settings
from app.core.access_token import encode_access_token
from app.core.deps import SESSION_COOKIE_NAME
from app.core.errors import ApiErrorCode
from app.core.security import hash_password
from app.db.models import User, UserRole, UserSettings, UserStatus
from app.db.repositories import UserSettingsRepository
from app.db.repositories.users import UserRepository
from app.main import app

PATH = "/api/v1/settings"
ME_PATH = "/api/v1/auth/me"

_PASSWORD = "mot-mat-khau-du-manh-cho-test-t30-123"


class _FakeRedis:
    """Blacklist rỗng — bộ test này đo cài đặt cá nhân, không đo §11.3."""

    async def mget(self, keys: list[str]) -> list[str | None]:
        return [None for _ in keys]

    async def incr(self, name: str) -> int:
        return 1

    async def expire(self, name: str, time: int, *, nx: bool = False) -> bool:
        return True


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    fake = _FakeRedis()
    monkeypatch.setattr("app.core.deps.get_redis", lambda: fake)
    return fake


@pytest.fixture(autouse=True)
def _db_for_tests(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`session_scope()` trong handler trỏ vào ĐÚNG kết nối của test (NQ-17)."""
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


@pytest_asyncio.fixture
async def client(event_hooks: dict[str, Any]) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://localhost", event_hooks=event_hooks
    ) as http:
        yield http


async def create_user(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    email = f"{uuid.uuid4().hex}@scarlet.example"
    async with session_factory() as session:
        user = await UserRepository(session).create_pending_user(
            email=email, password_hash=await hash_password(_PASSWORD)
        )
        assert user is not None
        await session.execute(
            update(User).where(User.id == user.id).values(status=UserStatus.ACTIVE)
        )
        await session.commit()
        return user.id


def login_resp(client: AsyncClient, user_id: uuid.UUID) -> None:
    client.cookies.set(
        SESSION_COOKIE_NAME,
        encode_access_token(
            user_id=user_id,
            role=UserRole.USER,
            tier="free",
            status=UserStatus.ACTIVE,
            ttl_minutes=15,
        ),
    )


async def read_column(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> str | None:
    """Đọc thẳng cột `users.default_model` — không qua response nào."""
    async with session_factory() as session:
        stmt = select(User.default_model).where(User.id == user_id)
        return (await session.execute(stmt)).scalar_one()


def one_enabled_model() -> str:
    """Một `model_id` đang bật. A3: không gõ tên model vào file test."""
    enabled = [m.id for m in catalog.get_catalog().models if m.enabled]
    assert enabled, "catalog phải có ít nhất một model bật"
    return enabled[0]


# ══════════════ 1. Ghi rồi đọc lại — hai endpoint, một sự thật ══════════════


async def test_write_then_read_back_via_auth_me(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id = await create_user(session_factory)
    login_resp(client, user_id)
    model = one_enabled_model()

    record_statement = await client.put(PATH, json={"default_model": model})

    assert record_statement.status_code == 200, record_statement.text
    assert record_statement.json()["default_model"] == model
    assert await read_column(session_factory, user_id) == model
    assert (await client.get(ME_PATH)).json()["default_model"] == model


# ═════════ 2. Model lạ hoặc đã tắt ⇒ 400 MODEL_UNKNOWN, không ghi gì ════════


async def test_model_not_in_catalog_400_and_writes_nothing(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id = await create_user(session_factory)
    login_resp(client, user_id)

    resp = await client.put(PATH, json={"default_model": "khong-ton-tai"})

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == ApiErrorCode.MODEL_UNKNOWN.value
    assert resp.json()["error"]["details"] == {"model_id": "khong-ton-tai"}
    assert await read_column(session_factory, user_id) is None


async def test_disabled_model_is_also_400(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`enabled: false` là công tắc của §9.2 — chọn mặc định một model đang tắt
    là hẹn trước một `MODEL_UNKNOWN` cho mọi lượt chat sau đó."""
    user_id = await create_user(session_factory)
    login_resp(client, user_id)
    model = one_enabled_model()
    monkeypatch.setattr(catalog, "get_model", lambda _id: None)

    resp = await client.put(PATH, json={"default_model": model})

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == ApiErrorCode.MODEL_UNKNOWN.value
    assert await read_column(session_factory, user_id) is None


async def test_unknown_key_in_body_is_422(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`extra="forbid"`: gõ sai tên trường phải NỔ, không phải im lặng.

    `{"defaultModel": ...}` mà được nhận là một lần bấm Lưu không có tác dụng
    gì và không ai biết vì sao.
    """
    user_id = await create_user(session_factory)
    login_resp(client, user_id)

    resp = await client.put(PATH, json={"defaultModel": one_enabled_model()})

    assert resp.status_code == 422
    assert await read_column(session_factory, user_id) is None


# ════════════════════════ 3. `null` bỏ chọn được ═══════════════════════════


async def test_null_clears_choice(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Không có đường về mặc định thì người dùng chọn xong là kẹt (T-3.6)."""
    user_id = await create_user(session_factory)
    login_resp(client, user_id)
    await client.put(PATH, json={"default_model": one_enabled_model()})

    resp = await client.put(PATH, json={"default_model": None})

    assert resp.status_code == 200
    assert resp.json()["default_model"] is None
    assert await read_column(session_factory, user_id) is None


async def test_empty_body_also_clears_choice(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`PUT` thay cả tài nguyên: vắng mặt đọc thành `null`, không phải "giữ nguyên".

    Ngày tài nguyên có trường thứ hai (T-S.5), S10 đã quyết tường minh: vẫn
    `PUT` thay cả tài nguyên, FE gửi đủ — xem nhóm 6.
    """
    user_id = await create_user(session_factory)
    login_resp(client, user_id)
    await client.put(PATH, json={"default_model": one_enabled_model()})

    resp = await client.put(PATH, json={})

    assert resp.status_code == 200
    assert await read_column(session_factory, user_id) is None


# ═══════ 4. Validate lúc GHI, không lúc đọc (Cạm bẫy ③ của T-3.0) ═══════════


async def test_model_removed_from_catalog_later_still_reads_normally(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catalog là file sửa nóng (§19.1): một dòng admin vừa sửa không được phép
    ném lỗi vào mặt một người không làm gì cả."""
    user_id = await create_user(session_factory)
    login_resp(client, user_id)
    model = one_enabled_model()
    await client.put(PATH, json={"default_model": model})

    # admin gỡ model khỏi catalog rồi `POST /admin/catalog/reload`
    monkeypatch.setattr(catalog, "get_model", lambda _id: None)

    resp = await client.get(ME_PATH)

    assert resp.status_code == 200
    assert resp.json()["default_model"] == model, "tra nguyen van, FE tu roi ve mac dinh"


# ═══════════════════════════ 5. §20 — cách ly ══════════════════════════════


async def test_not_logged_in_is_401(client: AsyncClient) -> None:
    resp = await client.put(PATH, json={"default_model": one_enabled_model()})

    # `401` va chi `401`: nhanh danh tinh tam Phase 1 (`503`) chet o T-3.1c.
    assert resp.status_code == 401


async def test_one_users_write_does_not_touch_another(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Không có tham số nào trỏ sang người khác, nên phép đo duy nhất còn lại
    là: sau khi A ghi, cột của B vẫn nguyên (§20)."""
    user_a = await create_user(session_factory)
    user_b = await create_user(session_factory)
    login_resp(client, user_a)

    await client.put(PATH, json={"default_model": one_enabled_model()})

    assert await read_column(session_factory, user_b) is None


# ═══════════════════ helpers của T-S.5 (A3: tên lấy từ catalog) ═════════════


async def read_prefs_row(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> dict[str, Any] | None:
    """Đọc thẳng `user_settings.prefs_json` — `None` khi chưa có hàng."""
    async with session_factory() as session:
        stmt = select(UserSettings.prefs_json).where(UserSettings.user_id == user_id)
        return (await session.execute(stmt)).scalar_one_or_none()


async def read_display_name(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> str | None:
    async with session_factory() as session:
        stmt = select(User.display_name).where(User.id == user_id)
        return (await session.execute(stmt)).scalar_one()


def model_with_reasoning() -> tuple[str, str]:
    """`(model_id, level_id)` hợp lệ: model đang bật có khối `reasoning`, và
    một mức **khác** mức mặc định — để phép đo không trùng hợp với `default`."""
    for m in catalog.get_catalog().models:
        if m.enabled and m.reasoning is not None:
            others = [o.id for o in m.reasoning.options if o.id != m.reasoning.default]
            if others:
                return m.id, others[0]
    raise AssertionError("catalog phai co mot model bat voi it nhat hai muc suy luan")


def model_without_reasoning() -> str:
    found = [m.id for m in catalog.get_catalog().models if m.enabled and m.reasoning is None]
    assert found, "catalog phai co mot model bat KHONG co khoi reasoning"
    return found[0]


def level_missing_from(model_id: str) -> str:
    """Một mức thuộc bộ từ vựng S3b mà model này **không** khai."""
    model = catalog.get_model(model_id)
    assert model is not None and model.reasoning is not None
    declared = {o.id for o in model.reasoning.options}
    missing = [lv for lv in catalog.REASONING_LEVELS if lv not in declared]
    assert missing, f"{model_id} khai du moi muc — khong con muc nao de thu"
    return missing[0]


def full_body() -> dict[str, Any]:
    """Body đủ mọi trường của `PUT /settings` — thứ FE (T-S.11) luôn gửi."""
    model_id, level = model_with_reasoning()
    return {
        "default_model": one_enabled_model(),
        "display_name": "Nguyễn Thị Ánh",
        "avatar_color": "ruby-500",
        "reasoning_prefs": {model_id: level},
    }


# ═══════ 1b. Đủ mọi trường — PUT rồi /auth/me, hai lần đọc (T-S.5 DoD 1) ═════


async def test_full_body_round_trips_via_auth_me(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Mỗi trường đi ra `/auth/me` đúng giá trị đã gửi — và lần đọc thứ hai
    (F5) vẫn thế: giá trị nằm trong DB, không trong bộ nhớ của request nào."""
    user_id = await create_user(session_factory)
    login_resp(client, user_id)
    body = full_body()

    put = await client.put(PATH, json=body)
    first = (await client.get(ME_PATH)).json()
    again = (await client.get(ME_PATH)).json()

    assert put.status_code == 200, put.text
    assert put.json() == body
    for me in (first, again):
        assert {k: me[k] for k in body} == body
    assert await read_display_name(session_factory, user_id) == body["display_name"]
    assert await read_prefs_row(session_factory, user_id) == {
        "avatar_color": body["avatar_color"],
        "reasoning": body["reasoning_prefs"],
    }, "S14: khoa luu tru la reasoning, khong phai reasoning_prefs"


async def test_first_write_creates_the_user_settings_row(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Chưa từng lưu ⇒ không có hàng; lần ghi đầu tạo nó (T-S.5 Việc 2); lần
    ghi sau ghi đè chứ không nổ `UNIQUE`."""
    user_id = await create_user(session_factory)
    login_resp(client, user_id)

    assert await read_prefs_row(session_factory, user_id) is None
    first = await client.put(PATH, json=full_body())
    second = await client.put(PATH, json={**full_body(), "avatar_color": "jade"})

    assert (first.status_code, second.status_code) == (200, 200)
    row = await read_prefs_row(session_factory, user_id)
    assert row is not None and row["avatar_color"] == "jade"


# ══════ 6. PUT thay CẢ tài nguyên — hành vi CÓ CHỦ Ý (§18.4, S10, DoD 2) ══════


async def test_put_replaces_whole_resource(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`PUT {"display_name": "A"}` ⇒ `default_model` về `null` — **CÓ CHỦ Ý**.

    §18.4 và S10 chốt: `PUT /settings` thay **cả** tài nguyên, kể cả khi tài
    nguyên nở thêm trường. Không có luật "vắng mặt nghĩa là giữ nguyên". Hệ quả
    cho FE (T-S.11): mọi lần lưu — kể cả chỉ đổi tên — phải gửi **đủ** mọi
    trường, lấy từ `/auth/me`. Đừng "sửa" test này thành giữ nguyên: đổi ngữ
    nghĩa ấy là việc của một `PATCH` mới, không phải một luật lén trong `PUT`.
    """
    user_id = await create_user(session_factory)
    login_resp(client, user_id)
    await client.put(PATH, json=full_body())

    resp = await client.put(PATH, json={"display_name": "A"})
    me = (await client.get(ME_PATH)).json()

    assert resp.status_code == 200, resp.text
    expected = {
        "default_model": None,
        "display_name": "A",
        "avatar_color": None,
        "reasoning_prefs": {},
    }
    assert resp.json() == expected
    assert {k: me[k] for k in expected} == expected
    assert await read_column(session_factory, user_id) is None
    assert await read_prefs_row(session_factory, user_id) == {"reasoning": {}}


async def test_explicit_nulls_clear_every_field(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`null` tường minh ở mọi trường là một body hợp lệ — cách FE gửi "bỏ hết".

    Ca này bắt đúng một lỗi đã xảy ra khi viết task: `max_length` của
    `display_name` đặt trên `str | None` làm Pydantic áp nó lên `None` ⇒ `500`.
    """
    user_id = await create_user(session_factory)
    login_resp(client, user_id)
    await client.put(PATH, json=full_body())

    resp = await client.put(
        PATH,
        json={
            "default_model": None,
            "display_name": None,
            "avatar_color": None,
            "reasoning_prefs": {},
        },
    )

    assert resp.status_code == 200, resp.text
    assert await read_display_name(session_factory, user_id) is None
    assert await read_prefs_row(session_factory, user_id) == {"reasoning": {}}


async def test_misspelled_new_field_is_422_not_a_silent_wipe(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Với `PUT` thay cả tài nguyên, một khoá gõ sai mà được nhận thì còn tệ
    hơn "không tác dụng": trường gõ sai bị bỏ, mọi trường đúng tên bị xoá."""
    user_id = await create_user(session_factory)
    login_resp(client, user_id)
    await client.put(PATH, json=full_body())

    resp = await client.put(PATH, json={**full_body(), "avatarColor": "jade"})

    assert resp.status_code == 422
    assert await read_display_name(session_factory, user_id) == full_body()["display_name"]


# ═════ 7. Mức suy luận: kiểm lúc GHI, bỏ qua lúc ĐỌC (T-S.5 Việc 1, 4) ═══════


async def test_level_on_model_without_reasoning_is_400_reasoning_unsupported(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """DoD dòng 3, vế `400` (trên stack thật là `ol-qwen-small` + `high`).

    Body còn mang một `display_name` hợp lệ: `400` là **không ghi gì cả**,
    không phải ghi phần hợp lệ rồi từ chối phần kia.
    """
    user_id = await create_user(session_factory)
    login_resp(client, user_id)
    model_id = model_without_reasoning()

    resp = await client.put(PATH, json={"display_name": "B", "reasoning_prefs": {model_id: "high"}})

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == ApiErrorCode.REASONING_UNSUPPORTED.value
    assert resp.json()["error"]["details"] == {"model_id": model_id, "level": "high"}
    assert await read_display_name(session_factory, user_id) is None
    assert await read_prefs_row(session_factory, user_id) is None


async def test_level_the_model_does_not_declare_is_400(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Model **có** khối `reasoning` nhưng không khai mức này — kể cả một mức
    hợp lệ trong bộ từ vựng S3b. Luật là "model này có mức này", không phải
    "mức này tồn tại"."""
    user_id = await create_user(session_factory)
    login_resp(client, user_id)
    model_id, _ = model_with_reasoning()
    level = level_missing_from(model_id)

    resp = await client.put(PATH, json={"reasoning_prefs": {model_id: level}})

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == ApiErrorCode.REASONING_UNSUPPORTED.value


async def test_level_outside_vocabulary_is_400(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id = await create_user(session_factory)
    login_resp(client, user_id)
    model_id, _ = model_with_reasoning()

    resp = await client.put(PATH, json={"reasoning_prefs": {model_id: "ultra"}})

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == ApiErrorCode.REASONING_UNSUPPORTED.value


async def test_unknown_model_in_reasoning_prefs_is_400_model_unknown(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Model lạ ⇒ `MODEL_UNKNOWN`, cùng mã với `default_model` lạ: FE tải lại
    danh sách model, không phải danh sách mức."""
    user_id = await create_user(session_factory)
    login_resp(client, user_id)

    resp = await client.put(PATH, json={"reasoning_prefs": {"khong-ton-tai": "high"}})

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == ApiErrorCode.MODEL_UNKNOWN.value
    assert resp.json()["error"]["details"] == {"model_id": "khong-ton-tai"}


async def test_declared_level_is_200_and_remembered(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """DoD dòng 3, vế `200` (trên stack thật là `deepseek-flash` + `high`)."""
    user_id = await create_user(session_factory)
    login_resp(client, user_id)
    model_id, level = model_with_reasoning()

    resp = await client.put(PATH, json={"reasoning_prefs": {model_id: level}})

    assert resp.status_code == 200, resp.text
    assert (await client.get(ME_PATH)).json()["reasoning_prefs"] == {model_id: level}


async def test_level_removed_from_catalog_later_is_skipped_on_read(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Admin gỡ một mức khỏi catalog rồi reload ⇒ `/auth/me` **bỏ qua** cặp
    ấy, `200`, không lỗi (T-S.5 Việc 4, Cạm bẫy ③ của T-3.0). Cặp vẫn nằm
    trong DB: đọc không ghi, và admin bật lại thì lựa chọn cũ quay về."""
    user_id = await create_user(session_factory)
    login_resp(client, user_id)
    model_id, level = model_with_reasoning()
    await client.put(PATH, json={"reasoning_prefs": {model_id: level}})

    patched = catalog.get_catalog().model_copy(deep=True)
    entry = next(m for m in patched.models if m.id == model_id)
    assert entry.reasoning is not None
    entry.reasoning.options = [o for o in entry.reasoning.options if o.id != level]
    monkeypatch.setattr(catalog, "_catalog", patched)

    resp = await client.get(ME_PATH)

    assert resp.status_code == 200
    assert resp.json()["reasoning_prefs"] == {}
    row = await read_prefs_row(session_factory, user_id)
    assert row is not None and row["reasoning"] == {model_id: level}, "doc khong xoa"


async def test_model_removed_from_catalog_later_is_skipped_on_read(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = await create_user(session_factory)
    login_resp(client, user_id)
    model_id, level = model_with_reasoning()
    await client.put(PATH, json={"reasoning_prefs": {model_id: level}})
    monkeypatch.setattr(catalog, "get_model", lambda _id: None)

    resp = await client.get(ME_PATH)

    assert resp.status_code == 200
    assert resp.json()["reasoning_prefs"] == {}


async def test_garbage_in_prefs_json_does_not_break_auth_me(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`prefs_json` sửa tay trong `psql` thành sai kiểu ⇒ `/auth/me` vẫn `200`.

    `/auth/me` là endpoint FE dùng để định tuyến (T-3.1b): một ô tuỳ chọn hỏng
    không được khoá cả giao diện. Cặp hợp lệ đi cùng vẫn đọc ra."""
    user_id = await create_user(session_factory)
    login_resp(client, user_id)
    model_id, level = model_with_reasoning()
    async with session_factory() as session:
        await UserSettingsRepository(session).put_prefs(
            user_id,
            {
                "avatar_color": 7,
                "reasoning": {model_id: level, "khong-ton-tai": "high", "x": [1]},
            },
        )
        await session.commit()

    resp = await client.get(ME_PATH)

    assert resp.status_code == 200
    assert resp.json()["avatar_color"] is None
    assert resp.json()["reasoning_prefs"] == {model_id: level}


# ════════ 8. Tên hiển thị: rỗng ⇒ NULL, trần theo KÝ TỰ (Cạm bẫy ②, ③) ═══════


@pytest.mark.parametrize("blank", ["", "   ", "　\t "])
async def test_blank_display_name_is_stored_as_null(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], blank: str
) -> None:
    """Cạm bẫy ②: rỗng ⇒ `NULL`, không chuỗi rỗng — FE hiện nguyên email khi
    `NULL` (NQ-116), và chỉ có **một** cách viết "chưa đặt tên"."""
    user_id = await create_user(session_factory)
    login_resp(client, user_id)
    await client.put(PATH, json={"display_name": "Cu"})

    resp = await client.put(PATH, json={"display_name": blank})

    assert resp.status_code == 200, resp.text
    assert resp.json()["display_name"] is None
    assert await read_display_name(session_factory, user_id) is None


async def test_display_name_is_trimmed(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id = await create_user(session_factory)
    login_resp(client, user_id)

    resp = await client.put(PATH, json={"display_name": "  An  "})

    assert resp.json()["display_name"] == "An"
    assert await read_display_name(session_factory, user_id) == "An"


async def test_display_name_limit_counts_characters_not_bytes(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Cạm bẫy ③: đếm theo ký tự như `MESSAGE_MAX_CHARS`. `ệ` là 3 byte UTF-8,
    nên đúng trần bằng ký tự thì vượt trần xa nếu đếm byte. Khoảng trắng hai
    đầu bị cắt **trước** khi đếm."""
    user_id = await create_user(session_factory)
    login_resp(client, user_id)
    limit = settings.DISPLAY_NAME_MAX_CHARS

    at_limit = await client.put(PATH, json={"display_name": " " + "ệ" * limit + " "})
    over = await client.put(PATH, json={"display_name": "ệ" * (limit + 1)})

    assert at_limit.status_code == 200, at_limit.text
    assert over.status_code == 422
    assert await read_display_name(session_factory, user_id) == "ệ" * limit


@pytest.mark.parametrize("bad", ["An\x00", "Dòng một\nDòng hai", "tab\there", "del\x7f"])
async def test_control_characters_in_display_name_are_422(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], bad: str
) -> None:
    """NUL là lý do cứng: Postgres `TEXT` không nhận nó, nên lọt biên vào là
    `500` ở câu `UPDATE`. Xuống dòng/tab không có chỗ trên một dòng sidebar."""
    user_id = await create_user(session_factory)
    login_resp(client, user_id)

    resp = await client.put(PATH, json={"display_name": bad})

    assert resp.status_code == 422
    assert await read_display_name(session_factory, user_id) is None


async def test_display_name_markup_is_stored_verbatim(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Backend không escape, không lọc thẻ: dữ liệu lưu nguyên văn, và FE **không
    bao giờ** render nó như HTML (Cạm bẫy ③). Escape ở đây là escape hai lần
    ở FE — `&lt;b&gt;` hiện ra màn hình."""
    user_id = await create_user(session_factory)
    login_resp(client, user_id)
    name = "<b>An</b> & <img src=x>"

    await client.put(PATH, json={"display_name": name})

    assert (await client.get(ME_PATH)).json()["display_name"] == name


# ═══════════ 9. Tên màu avatar: chỉ hình dạng, không mã màu (A3) ════════════


@pytest.mark.parametrize("color", ["ruby", "slate-700", "a", "x" * 32])
async def test_avatar_color_name_shapes_accepted(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], color: str
) -> None:
    """Backend không biết bảng màu: tên hợp hình dạng mà FE không biết vẫn lưu
    được — FE rơi về màu mặc định (T-S.5 Việc 1)."""
    user_id = await create_user(session_factory)
    login_resp(client, user_id)

    resp = await client.put(PATH, json={"avatar_color": color})

    assert resp.status_code == 200, resp.text
    assert (await client.get(ME_PATH)).json()["avatar_color"] == color


@pytest.mark.parametrize("color", ["#ff0000", "rgb(1,2,3)", "Ruby", "ruby 500", "", "x" * 33, "đỏ"])
async def test_avatar_color_that_is_not_a_name_is_422(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], color: str
) -> None:
    """Mã màu, chữ hoa, khoảng trắng, rỗng, dài quá 32 ⇒ `422`. Lưu **tên** màu,
    không mã màu (A3, NQ-116): hình dạng hẹp là để trường này không bao giờ
    mang được một giá trị CSS."""
    user_id = await create_user(session_factory)
    login_resp(client, user_id)

    resp = await client.put(PATH, json={"avatar_color": color})

    assert resp.status_code == 422
    assert await read_prefs_row(session_factory, user_id) is None


# ════════════════════ 5b. §20 — cách ly, phần của T-S.5 ═════════════════════


async def test_one_users_profile_does_not_leak_to_another(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Sau khi A ghi đủ mọi trường, `/auth/me` của B vẫn trống — hai bảng, cả
    hai câu ghi lọc `user_id` trong SQL (§20)."""
    user_a = await create_user(session_factory)
    user_b = await create_user(session_factory)
    login_resp(client, user_a)
    await client.put(PATH, json=full_body())

    login_resp(client, user_b)
    me_b = (await client.get(ME_PATH)).json()

    assert (me_b["display_name"], me_b["avatar_color"], me_b["reasoning_prefs"]) == (
        None,
        None,
        {},
    )
    assert await read_prefs_row(session_factory, user_b) is None
