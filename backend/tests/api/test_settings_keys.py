"""BYOK CRUD — `/settings/keys` (§18.4, §10.5) — T-2.14.

Sáu dòng DoD của T-2.14 nằm rải trong sáu nhóm dưới đây, và mỗi nhóm được đặt
tên theo **thứ nó chặn** chứ không theo endpoint nó gọi:

1. **Bản rõ không được vào DB** (DoD 1) và **nonce riêng mỗi bản ghi**
   (DoD 2) — hai dòng này đo trên hàng Postgres THẬT, không qua response.
2. **Không bao giờ hiện lại** (DoD 3) — cả `GET` lẫn `PUT` chỉ trả chuỗi che.
3. **Khoá sai ⇒ 400, thông điệp không chứa khoá** (DoD 4) — C20.
4. **Đổi `MASTER_ENCRYPTION_KEY` ⇒ hỏng có kiểm soát** (DoD 6).
5. **Phân quyền và cách ly giữa hai người dùng** (§20).
6. **Catalog quyết định provider nào hợp lệ** (§9.2, C42).

Hạ tầng giống `test_account_states.py`: `httpx.ASGITransport`, `session_scope()`
trỏ về đúng kết nối của test, Redis giả (mọi request mang cookie phiên đều hỏi
blacklist từ T-2.4), và `MockTransport` cho chặng đi hỏi provider — không lần
chạy nào của bộ test này chạm Internet.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import catalog
from app.config.settings import settings
from app.core.access_token import encode_access_token
from app.core.deps import SESSION_COOKIE_NAME
from app.core.errors import ApiErrorCode
from app.core.security import hash_password
from app.db.models import User, UserProviderKey, UserRole, UserStatus
from app.db.repositories.users import UserRepository
from app.llm import byok_verify as verify_mod
from app.main import app

DUONG_DAN_DS = "/api/v1/settings/keys"
DUONG_DAN_MOT = "/api/v1/settings/keys/{}"

#: Không phải khoá của ai — đủ dài để `mask_secret` giữ tiền tố, và đúng hình
#: dạng mà grep của C20 bắt.
KHOA_GIA = "sk-khong-phai-khoa-that-cua-ai-4f2a"
KHOA_GIA_2 = "sk-mot-khoa-gia-khac-hoan-toan-9e71"

_MAT_KHAU = "mot-mat-khau-du-manh-cho-test-t214-123"


# ═══════════════════════════ hạ tầng của bộ test ════════════════════════════


class _RedisGia:
    """Blacklist rỗng — bộ test này đo BYOK, không đo §11.3."""

    async def mget(self, keys: list[str]) -> list[str | None]:
        return [None for _ in keys]

    async def incr(self, name: str) -> int:
        return 1

    async def expire(self, name: str, time: int, *, nx: bool = False) -> bool:
        return True


@pytest.fixture(autouse=True)
def redis_gia(monkeypatch: pytest.MonkeyPatch) -> _RedisGia:
    gia = _RedisGia()
    monkeypatch.setattr("app.core.deps.get_redis", lambda: gia)
    return gia


@pytest.fixture(autouse=True)
def _db_cua_test(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`session_scope()` trong handler trỏ vào ĐÚNG kết nối của test (NQ-17)."""
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: session_factory)


@pytest.fixture(autouse=True)
def provider_noi_dong_y(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    """Mặc định: provider trả `200`, tức mọi khoá đều "sống".

    Autouse vì quên nó nghĩa là một test đi gọi Internet thật — kiểu hỏng vừa
    chậm vừa phụ thuộc máy ai chạy.
    """
    return dat_transport(monkeypatch, lambda _r: httpx.Response(200, json={"data": []}))


def dat_transport(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> list[httpx.Request]:
    da_gui: list[httpx.Request] = []

    def _bat(request: httpx.Request) -> httpx.Response:
        da_gui.append(request)
        return handler(request)

    monkeypatch.setattr(
        verify_mod, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(_bat))
    )
    return da_gui


@pytest_asyncio.fixture
async def client(event_hooks: dict[str, Any]) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://localhost", event_hooks=event_hooks
    ) as http:
        yield http


def provider_byok() -> str:
    """Một provider `byok_supported` trong catalog — A3: không gõ tay tên."""
    ho_tro = [ten for ten, p in catalog.get_catalog().providers.items() if p.byok_supported]
    assert ho_tro, "catalog phải có ít nhất một provider hỗ trợ BYOK"
    return sorted(ho_tro)[0]


def provider_khong_byok() -> str | None:
    khong = [ten for ten, p in catalog.get_catalog().providers.items() if not p.byok_supported]
    return sorted(khong)[0] if khong else None


async def tao_user(
    session_factory: async_sessionmaker[AsyncSession],
    trang_thai: UserStatus = UserStatus.ACTIVE,
) -> uuid.UUID:
    email = f"{uuid.uuid4().hex}@scarlet.example"
    async with session_factory() as session:
        user = await UserRepository(session).create_pending_user(
            email=email, password_hash=await hash_password(_MAT_KHAU)
        )
        assert user is not None
        await session.execute(update(User).where(User.id == user.id).values(status=trang_thai))
        await session.commit()
        return user.id


def dang_nhap(
    client: AsyncClient, user_id: uuid.UUID, trang_thai: UserStatus = UserStatus.ACTIVE
) -> None:
    client.cookies.set(
        SESSION_COOKIE_NAME,
        encode_access_token(
            user_id=user_id,
            role=UserRole.USER,
            tier="free",
            status=trang_thai,
            ttl_minutes=15,
        ),
    )


@pytest_asyncio.fixture
async def user_da_dang_nhap(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> uuid.UUID:
    user_id = await tao_user(session_factory)
    dang_nhap(client, user_id)
    return user_id


async def hang_khoa(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> list[UserProviderKey]:
    async with session_factory() as session:
        stmt = select(UserProviderKey).where(UserProviderKey.user_id == user_id)
        return list((await session.execute(stmt)).scalars().all())


# ═══════ 1. Bản rõ KHÔNG vào DB (DoD 1) · nonce riêng mỗi bản ghi (DoD 2) ═══


async def test_key_cipher_khong_chua_ban_ro(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_da_dang_nhap: uuid.UUID,
) -> None:
    """DoD dòng 1, đo trên cột `key_cipher` THẬT của Postgres."""
    resp = await client.put(DUONG_DAN_MOT.format(provider_byok()), json={"key": KHOA_GIA})
    assert resp.status_code == 200, resp.text

    hang = await hang_khoa(session_factory, user_da_dang_nhap)
    assert len(hang) == 1
    assert KHOA_GIA.encode() not in hang[0].key_cipher
    assert KHOA_GIA not in hang[0].key_last4


async def test_khong_cot_nao_trong_bang_chua_ban_ro(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_da_dang_nhap: uuid.UUID,
) -> None:
    """Chặt hơn dòng trên một bậc: quét **cả hàng** dưới dạng chữ.

    Phép kiểm ở trên chỉ nhìn `key_cipher`; một bản vá vụng về có thể lưu
    thêm bản rõ vào một cột khác mà nó vẫn xanh.
    """
    await client.put(DUONG_DAN_MOT.format(provider_byok()), json={"key": KHOA_GIA})
    async with session_factory() as session:
        ca_hang = (
            await session.execute(text("SELECT user_provider_keys::text FROM user_provider_keys"))
        ).scalar_one()
    assert KHOA_GIA not in ca_hang


async def test_hai_user_cung_mot_khoa_cho_hai_ban_ma_khac_nhau(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """DoD dòng 2 — chứng minh nonce riêng mỗi bản ghi (cạm bẫy của task)."""
    provider = provider_byok()
    ban_ma: list[bytes] = []
    nonce: list[bytes] = []
    for _ in range(2):
        user_id = await tao_user(session_factory)
        dang_nhap(client, user_id)
        resp = await client.put(DUONG_DAN_MOT.format(provider), json={"key": KHOA_GIA})
        assert resp.status_code == 200, resp.text
        hang = await hang_khoa(session_factory, user_id)
        ban_ma.append(hang[0].key_cipher)
        nonce.append(hang[0].key_nonce)

    assert ban_ma[0] != ban_ma[1]
    assert nonce[0] != nonce[1]


async def test_put_lan_hai_ghi_de_ca_nonce(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_da_dang_nhap: uuid.UUID,
) -> None:
    """`UNIQUE (user_id, provider)` ⇒ đổi khoá là ghi đè, không phải hàng thứ hai.

    Và phải ghi đè **cả** `key_nonce`: giữ nonce cũ với bản mã mới là một hàng
    không giải mã được nữa.
    """
    provider = provider_byok()
    await client.put(DUONG_DAN_MOT.format(provider), json={"key": KHOA_GIA})
    truoc = (await hang_khoa(session_factory, user_da_dang_nhap))[0]
    cipher_truoc, nonce_truoc = truoc.key_cipher, truoc.key_nonce

    resp = await client.put(DUONG_DAN_MOT.format(provider), json={"key": KHOA_GIA_2})
    assert resp.status_code == 200

    sau = await hang_khoa(session_factory, user_da_dang_nhap)
    assert len(sau) == 1
    assert sau[0].key_cipher != cipher_truoc
    assert sau[0].key_nonce != nonce_truoc
    assert resp.json()["masked_key"].endswith(KHOA_GIA_2[-4:])


# ═════════════════ 2. Không bao giờ hiện lại (DoD 3, §10.5) ═════════════════


async def test_get_chi_tra_chuoi_che(client: AsyncClient, user_da_dang_nhap: uuid.UUID) -> None:
    """DoD dòng 3: `sk-...4f2a`, không bao giờ trả đủ."""
    await client.put(DUONG_DAN_MOT.format(provider_byok()), json={"key": KHOA_GIA})

    resp = await client.get(DUONG_DAN_DS)
    assert resp.status_code == 200
    assert KHOA_GIA not in resp.text

    khoa = resp.json()["keys"][0]
    assert khoa["masked_key"] == "sk-...4f2a"
    assert khoa["provider"] == provider_byok()
    assert khoa["usable"] is True
    assert khoa["verified_at"] is not None


async def test_put_cung_chi_tra_chuoi_che(
    client: AsyncClient, user_da_dang_nhap: uuid.UUID
) -> None:
    """Response của chính lần lưu cũng không được vọng lại khoá — nếu không,
    "không bao giờ hiển thị lại" chỉ đúng với `GET`."""
    resp = await client.put(DUONG_DAN_MOT.format(provider_byok()), json={"key": KHOA_GIA})
    assert KHOA_GIA not in resp.text
    assert resp.json()["masked_key"] == "sk-...4f2a"


async def test_get_khi_chua_co_khoa_nao_tra_danh_sach_rong(
    client: AsyncClient, user_da_dang_nhap: uuid.UUID
) -> None:
    resp = await client.get(DUONG_DAN_DS)
    assert resp.status_code == 200
    assert resp.json()["keys"] == []


async def test_get_liet_ke_moi_provider_nhan_khoa_rieng_theo_catalog(
    client: AsyncClient, user_da_dang_nhap: uuid.UUID
) -> None:
    """T-3.12 — trang Cài đặt chọn provider từ `byok_providers`, không từ một
    mảng gõ sẵn ở FE (A3). Đúng tập `byok_supported` của catalog, kể cả khi
    người này chưa có khoá nào; provider không nhận khoá riêng thì vắng mặt.
    `provider` là KHOÁ catalog — thứ `PUT /settings/keys/{provider}` nhận."""
    cat = catalog.get_catalog()

    body = (await client.get(DUONG_DAN_DS)).json()

    assert {p["provider"] for p in body["byok_providers"]} == {
        ten for ten, p in cat.providers.items() if p.byok_supported
    }
    for p in body["byok_providers"]:
        assert p["label"] == cat.providers[p["provider"]].label
    khong = provider_khong_byok()
    if khong is not None:
        assert khong not in {p["provider"] for p in body["byok_providers"]}


# ═══════════ 3. Khoá sai ⇒ 400, thông điệp KHÔNG chứa khoá (DoD 4) ══════════


@pytest.mark.parametrize("ma_upstream", [401, 403])
async def test_khoa_bi_provider_tu_choi_thi_400(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_da_dang_nhap: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    ma_upstream: int,
) -> None:
    """DoD dòng 4 — và khoá **không** được lưu (§10.5: kiểm TRƯỚC khi lưu)."""
    dat_transport(monkeypatch, lambda _r: httpx.Response(ma_upstream, json={"error": "nope"}))

    resp = await client.put(DUONG_DAN_MOT.format(provider_byok()), json={"key": KHOA_GIA})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == ApiErrorCode.PROVIDER_KEY_REJECTED
    assert KHOA_GIA not in resp.text
    assert await hang_khoa(session_factory, user_da_dang_nhap) == []


async def test_khong_hoi_duoc_provider_thi_503_chu_khong_400(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_da_dang_nhap: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ "Không biết" khác "khoá sai": nói với người dùng rằng khoá của họ hỏng
    khi thật ra mạng hỏng sẽ khiến họ đi tạo một khoá mới vô ích.

    Và khoá cũng KHÔNG được lưu: một sự cố tạm thời không được biến thành một
    hàng dữ liệu vĩnh viễn mang `verified_at IS NULL`.
    """

    def _no(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("khong noi duoc (gia lap)")

    dat_transport(monkeypatch, _no)

    resp = await client.put(DUONG_DAN_MOT.format(provider_byok()), json={"key": KHOA_GIA})
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == ApiErrorCode.SERVICE_UNAVAILABLE
    assert KHOA_GIA not in resp.text
    assert await hang_khoa(session_factory, user_da_dang_nhap) == []


async def test_body_thieu_key_thi_422_va_khong_vong_lai_gi(
    client: AsyncClient, user_da_dang_nhap: uuid.UUID
) -> None:
    """§20: `details` của 422 không mang `input` — ở route này `input` chính
    là khoá người dùng vừa dán."""
    resp = await client.put(DUONG_DAN_MOT.format(provider_byok()), json={"khong-phai-key": "x"})
    assert resp.status_code == 422
    assert "input" not in resp.text


async def test_key_rong_thi_422(client: AsyncClient, user_da_dang_nhap: uuid.UUID) -> None:
    resp = await client.put(DUONG_DAN_MOT.format(provider_byok()), json={"key": ""})
    assert resp.status_code == 422


# ══════════ 4. Đổi MASTER_ENCRYPTION_KEY ⇒ hỏng CÓ KIỂM SOÁT (DoD 6) ════════


async def test_doi_master_key_thi_usable_false_chu_khong_500(
    client: AsyncClient, user_da_dang_nhap: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DoD dòng 6. `GET` vẫn `200`, vẫn hiện chuỗi che, và nói rõ khoá không
    đọc được nữa để FE bảo người dùng nhập lại."""
    await client.put(DUONG_DAN_MOT.format(provider_byok()), json={"key": KHOA_GIA})

    monkeypatch.setattr(settings, "MASTER_ENCRYPTION_KEY", SecretStr("x" * 64))

    resp = await client.get(DUONG_DAN_DS)
    assert resp.status_code == 200
    khoa = resp.json()["keys"][0]
    assert khoa["usable"] is False
    assert khoa["masked_key"] == "sk-...4f2a"


async def test_doi_master_key_roi_nhap_lai_thi_usable_tro_lai(
    client: AsyncClient, user_da_dang_nhap: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "Báo user nhập lại" chỉ có nghĩa nếu nhập lại thật sự chữa được."""
    await client.put(DUONG_DAN_MOT.format(provider_byok()), json={"key": KHOA_GIA})
    monkeypatch.setattr(settings, "MASTER_ENCRYPTION_KEY", SecretStr("x" * 64))
    assert (await client.get(DUONG_DAN_DS)).json()["keys"][0]["usable"] is False

    await client.put(DUONG_DAN_MOT.format(provider_byok()), json={"key": KHOA_GIA})
    assert (await client.get(DUONG_DAN_DS)).json()["keys"][0]["usable"] is True


# ═════════════════ 5. Phân quyền và cách ly giữa hai user ═══════════════════


async def test_khong_dang_nhap_thi_khong_vao_duoc(client: AsyncClient) -> None:
    resp = await client.get(DUONG_DAN_DS)
    assert resp.status_code in (401, 503)


async def test_khoa_cua_nguoi_khac_khong_hien_ra(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """§20 — lọc `user_id` trong câu SQL."""
    nguoi_a = await tao_user(session_factory)
    dang_nhap(client, nguoi_a)
    await client.put(DUONG_DAN_MOT.format(provider_byok()), json={"key": KHOA_GIA})

    nguoi_b = await tao_user(session_factory)
    dang_nhap(client, nguoi_b)
    assert (await client.get(DUONG_DAN_DS)).json()["keys"] == []


async def test_khong_xoa_duoc_khoa_cua_nguoi_khac(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    nguoi_a = await tao_user(session_factory)
    dang_nhap(client, nguoi_a)
    await client.put(DUONG_DAN_MOT.format(provider_byok()), json={"key": KHOA_GIA})

    nguoi_b = await tao_user(session_factory)
    dang_nhap(client, nguoi_b)
    resp = await client.delete(DUONG_DAN_MOT.format(provider_byok()))
    assert resp.status_code == 404
    assert len(await hang_khoa(session_factory, nguoi_a)) == 1


async def test_pending_approval_them_duoc_khoa(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """§11.1 cho `pending_approval` chat bằng BYOK — cánh cửa đó chỉ mở khi họ
    **thêm được** khoá. Chặn ở đây là khoá vòng."""
    user_id = await tao_user(session_factory, UserStatus.PENDING_APPROVAL)
    dang_nhap(client, user_id, UserStatus.PENDING_APPROVAL)
    resp = await client.put(DUONG_DAN_MOT.format(provider_byok()), json={"key": KHOA_GIA})
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("trang_thai", [UserStatus.REJECTED, UserStatus.SUSPENDED])
async def test_tai_khoan_bi_khoa_khong_vao_duoc(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    trang_thai: UserStatus,
) -> None:
    """Router nằm trong `_CO_DANH_TINH`, tức cột "Xem UI" của §11.1."""
    user_id = await tao_user(session_factory, trang_thai)
    dang_nhap(client, user_id, trang_thai)
    resp = await client.get(DUONG_DAN_DS)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == ApiErrorCode.ACCOUNT_DISABLED


# ═══════════════ 6. Catalog quyết định provider nào hợp lệ ══════════════════


async def test_provider_la_thi_404(client: AsyncClient, user_da_dang_nhap: uuid.UUID) -> None:
    resp = await client.put(DUONG_DAN_MOT.format("provider-khong-ton-tai"), json={"key": KHOA_GIA})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == ApiErrorCode.PROVIDER_UNKNOWN


async def test_provider_khong_ho_tro_byok_thi_400(
    client: AsyncClient, user_da_dang_nhap: uuid.UUID
) -> None:
    ten = provider_khong_byok()
    assert ten is not None, "catalog phải có ít nhất một provider KHÔNG hỗ trợ BYOK"
    resp = await client.put(DUONG_DAN_MOT.format(ten), json={"key": KHOA_GIA})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == ApiErrorCode.BYOK_NOT_SUPPORTED


async def test_thieu_verify_path_thi_van_luu_nhung_chua_xac_minh(
    client: AsyncClient, user_da_dang_nhap: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C42 — và `verified_at` phải là `null`, không phải `now()`."""
    provider = provider_byok()
    goc = catalog.get_catalog().providers[provider]
    monkeypatch.setitem(
        catalog.get_catalog().providers, provider, goc.model_copy(update={"verify_path": None})
    )

    resp = await client.put(DUONG_DAN_MOT.format(provider), json={"key": KHOA_GIA})
    assert resp.status_code == 200
    assert resp.json()["verified_at"] is None


# ═══════════════════════════════ DELETE ═════════════════════════════════════


async def test_xoa_khoa(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_da_dang_nhap: uuid.UUID,
) -> None:
    provider = provider_byok()
    await client.put(DUONG_DAN_MOT.format(provider), json={"key": KHOA_GIA})

    resp = await client.delete(DUONG_DAN_MOT.format(provider))
    assert resp.status_code == 204
    assert await hang_khoa(session_factory, user_da_dang_nhap) == []


async def test_xoa_lan_hai_tra_404(client: AsyncClient, user_da_dang_nhap: uuid.UUID) -> None:
    provider = provider_byok()
    await client.put(DUONG_DAN_MOT.format(provider), json={"key": KHOA_GIA})
    assert (await client.delete(DUONG_DAN_MOT.format(provider))).status_code == 204

    resp = await client.delete(DUONG_DAN_MOT.format(provider))
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == ApiErrorCode.PROVIDER_KEY_NOT_FOUND


async def test_xoa_duoc_khoa_cua_provider_da_bi_go_khoi_catalog(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    user_da_dang_nhap: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`DELETE` cố ý KHÔNG hỏi catalog: một hàng mồ côi vẫn phải xoá được."""
    provider = provider_byok()
    await client.put(DUONG_DAN_MOT.format(provider), json={"key": KHOA_GIA})

    providers = dict(catalog.get_catalog().providers)
    del providers[provider]
    monkeypatch.setattr(catalog.get_catalog(), "providers", providers)

    assert (await client.delete(DUONG_DAN_MOT.format(provider))).status_code == 204
    assert await hang_khoa(session_factory, user_da_dang_nhap) == []
