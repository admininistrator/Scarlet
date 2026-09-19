"""`llm/credentials.py` — ai trả tiền cho một lượt sinh (§10.5) — T-2.15.

Đây là hàm mà **cả hai** tiến trình hỏi (api để bỏ qua cửa quota, worker để
chọn adapter), nên thứ phải kiểm không chỉ là "nó trả đúng gì" mà còn là "hai
đường vào không bao giờ trả lời khác nhau" — nhóm cuối cùng của file này.

Bốn ngả lùi về system key (docstring `llm/credentials.py`) đều có một test,
và cả bốn đều là những ngả mà nếu đọc sai thì hậu quả là **tiền**: lùi nhầm
thì người dùng bị trừ quota cho khoá của chính họ; không lùi thì một lượt
sinh bằng system key được miễn cửa chặn §10.2.

Postgres thật (NQ-17): bảng `user_provider_keys` có UNIQUE `(user_id,
provider)` và một cột BYTEA, và đó đúng là hai thứ một stub sẽ bỏ qua.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import catalog
from app.config.catalog import ModelEntry
from app.config.settings import settings
from app.core.crypto import mask_secret, seal
from app.db.models import KeySource
from app.db.repositories import ProviderKeyRepository
from app.llm.credentials import resolve_credential, resolve_key_source

#: Ghép lúc chạy: một chuỗi khớp `sk-[a-zA-Z0-9]{20,}` nằm nguyên văn trong
#: repo làm `scripts/check_hardcode.sh` lệnh 4 đỏ vĩnh viễn (T-2.14).
KHOA_GIA = "sk-" + "0123456789abcdef" * 2


def _model_byok() -> ModelEntry:
    """Một model **có** BYOK — A3: hỏi catalog, không gõ tên model vào test."""
    cat = catalog.get_catalog()
    for model in cat.models:
        if cat.providers[model.provider].byok_supported:
            return model
    pytest.fail("catalog phải có ít nhất một model thuộc provider byok_supported")


def _model_khong_byok() -> ModelEntry:
    """Một model thuộc provider `byok_supported: false`."""
    cat = catalog.get_catalog()
    for model in cat.models:
        if not cat.providers[model.provider].byok_supported:
            return model
    pytest.fail("catalog phải có ít nhất một model thuộc provider KHÔNG byok")


def _model_hai_ten_khac_nhau() -> ModelEntry:
    """Model mà alias LiteLLM (`id`) KHÁC tên gốc của provider (`provider_model`).

    Không có model nào như vậy thì phép phân biệt của `Credential.model_name`
    không còn đo được — nên đó là một `fail`, không phải một `skip`.
    """
    cat = catalog.get_catalog()
    for model in cat.models:
        if model.id != model.provider_model and cat.providers[model.provider].byok_supported:
            return model
    pytest.fail("catalog phải có một model byok mà alias khác tên gốc của provider")


async def _luu_khoa(session: AsyncSession, user_id: uuid.UUID, provider: str) -> None:
    await ProviderKeyRepository(session).upsert(
        user_id=user_id,
        provider=provider,
        sealed=seal(KHOA_GIA),
        masked=mask_secret(KHOA_GIA),
        verified_at=None,
    )
    await session.commit()


# ════════════════════════ bốn ngả lùi về system key ════════════════════════


async def test_khong_co_hang_nao_thi_system(session: AsyncSession, user_a: uuid.UUID) -> None:
    """Ca thường: chưa ai cấu hình BYOK ⇒ tiền của người vận hành ⇒ có quota."""
    model = _model_byok()

    assert await resolve_key_source(session, user_id=user_a, model=model) is KeySource.SYSTEM
    cred = await resolve_credential(session, user_id=user_a, model=model)
    assert cred.key_source is KeySource.SYSTEM
    assert cred.api_key is None
    assert cred.provider is None


async def test_xoa_khoa_thi_quay_ve_system(session: AsyncSession, user_a: uuid.UUID) -> None:
    """**DoD dòng 3 của T-2.15** ở mức đơn vị: không cần dọn gì thêm."""
    model = _model_byok()
    await _luu_khoa(session, user_a, model.provider)
    assert await resolve_key_source(session, user_id=user_a, model=model) is KeySource.BYOK

    assert await ProviderKeyRepository(session).delete(user_id=user_a, provider=model.provider)
    await session.commit()

    assert await resolve_key_source(session, user_id=user_a, model=model) is KeySource.SYSTEM


async def test_khoa_cua_provider_KHAC_khong_tinh(session: AsyncSession, user_a: uuid.UUID) -> None:
    """B-140: "có khoá" không đủ — phải là khoá của provider model đang gọi."""
    cat = catalog.get_catalog()
    model = _model_byok()
    khac = next(
        ten for ten in sorted(cat.providers) if ten != model.provider and cat.providers[ten]
    )
    await _luu_khoa(session, user_a, khac)

    assert await resolve_key_source(session, user_id=user_a, model=model) is KeySource.SYSTEM


async def test_provider_tat_byok_thi_khoa_cu_khong_con_hieu_luc(
    session: AsyncSession, user_a: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Người vận hành tắt `byok_supported` ⇒ hàng còn sót KHÔNG lật lại quyết định đó."""
    model = _model_byok()
    await _luu_khoa(session, user_a, model.provider)
    assert await resolve_key_source(session, user_id=user_a, model=model) is KeySource.BYOK

    provider = catalog.get_catalog().providers[model.provider]
    monkeypatch.setattr(provider, "byok_supported", False)

    assert await resolve_key_source(session, user_id=user_a, model=model) is KeySource.SYSTEM


async def test_khong_giai_ma_duoc_thi_lui_ve_system(
    session: AsyncSession, user_a: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`MASTER_ENCRYPTION_KEY` đã xoay ⇒ lùi, KHÔNG ném vào giữa lượt chat."""
    model = _model_byok()
    await _luu_khoa(session, user_a, model.provider)
    monkeypatch.setattr(settings, "MASTER_ENCRYPTION_KEY", SecretStr("mot-master-key-khac-han"))

    assert await resolve_key_source(session, user_id=user_a, model=model) is KeySource.SYSTEM
    cred = await resolve_credential(session, user_id=user_a, model=model)
    assert cred.api_key is None


async def test_khoa_cua_NGUOI_KHAC_khong_dung_duoc(
    session: AsyncSession, user_a: uuid.UUID, user_b: uuid.UUID
) -> None:
    """§20 — `user_id` lọc **trong câu SQL**; đây là bảng chứa credential."""
    model = _model_byok()
    await _luu_khoa(session, user_b, model.provider)

    assert await resolve_key_source(session, user_id=user_a, model=model) is KeySource.SYSTEM
    assert await resolve_key_source(session, user_id=user_b, model=model) is KeySource.BYOK


# ══════════════════════════ ngả BYOK: có đủ ba thứ ═════════════════════════


async def test_co_khoa_dung_provider_thi_byok_kem_ban_ro_va_provider(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """Worker cần cả ba: nguồn, bản ghi provider (để có `base_url`), và khoá."""
    model = _model_byok()
    await _luu_khoa(session, user_a, model.provider)

    cred = await resolve_credential(session, user_id=user_a, model=model)

    assert cred.key_source is KeySource.BYOK
    assert cred.api_key == KHOA_GIA
    assert cred.provider is catalog.get_catalog().providers[model.provider]


async def test_model_cua_provider_khong_ho_tro_byok_luon_la_system(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    model = _model_khong_byok()
    await _luu_khoa(session, user_a, model.provider)

    assert await resolve_key_source(session, user_id=user_a, model=model) is KeySource.SYSTEM


# ═══════════════════ tên model gửi lên: alias hay tên gốc ══════════════════


async def test_model_name_system_la_alias_litellm(session: AsyncSession, user_a: uuid.UUID) -> None:
    """System đi qua LiteLLM ⇒ tên phải là alias trong `litellm.config.yaml`."""
    model = _model_byok()
    cred = await resolve_credential(session, user_id=user_a, model=model)

    assert cred.model_name(model) == model.id


async def test_model_name_byok_la_ten_goc_cua_provider(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """BYOK gọi thẳng provider ⇒ alias của LiteLLM ở đó là `400 model not found`.

    Chọn một model mà hai tên **thật sự khác nhau**: `deepseek-flash` có alias
    trùng tên gốc, nên đo trên nó thì bỏ `provider_model` đi test vẫn xanh.
    """
    model = _model_hai_ten_khac_nhau()
    await _luu_khoa(session, user_a, model.provider)
    cred = await resolve_credential(session, user_id=user_a, model=model)

    assert cred.model_name(model) == model.provider_model != model.id


# ═════════════ hai đường vào, một lõi: không được trả lời khác ═════════════


@pytest.mark.parametrize("co_khoa", [False, True])
async def test_hai_ham_luon_dong_y_ve_key_source(
    session: AsyncSession, user_a: uuid.UUID, co_khoa: bool
) -> None:
    """Lệch một lần là một lượt vừa được miễn quota vừa tiêu system key."""
    model = _model_byok()
    if co_khoa:
        await _luu_khoa(session, user_a, model.provider)

    mot = await resolve_key_source(session, user_id=user_a, model=model)
    hai = (await resolve_credential(session, user_id=user_a, model=model)).key_source

    assert mot is hai
