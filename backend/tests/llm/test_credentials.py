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
from app.config.catalog import ModelEntry, ReasoningOption
from app.config.settings import settings
from app.core.crypto import mask_secret, seal
from app.db.models import KeySource
from app.db.repositories import ProviderKeyRepository
from app.llm.credentials import (
    SYSTEM_CREDENTIAL,
    Credential,
    resolve_credential,
    resolve_key_source,
)

#: Ghép lúc chạy: một chuỗi khớp `sk-[a-zA-Z0-9]{20,}` nằm nguyên văn trong
#: repo làm `scripts/check_hardcode.sh` lệnh 4 đỏ vĩnh viễn (T-2.14).
FAKE_KEY = "sk-" + "0123456789abcdef" * 2


def _model_byok() -> ModelEntry:
    """Một model **có** BYOK — A3: hỏi catalog, không gõ tên model vào test."""
    cat = catalog.get_catalog()
    for model in cat.models:
        if cat.providers[model.provider].byok_supported:
            return model
    pytest.fail("catalog phải có ít nhất một model thuộc provider byok_supported")


def _model_without_byok() -> ModelEntry:
    """Một model thuộc provider `byok_supported: false`."""
    cat = catalog.get_catalog()
    for model in cat.models:
        if not cat.providers[model.provider].byok_supported:
            return model
    pytest.fail("catalog phải có ít nhất một model thuộc provider KHÔNG byok")


def _model_with_two_names() -> ModelEntry:
    """Model mà alias LiteLLM (`id`) KHÁC tên gốc của provider (`provider_model`).

    Không có model nào như vậy thì phép phân biệt của `Credential.model_name`
    không còn đo được — nên đó là một `fail`, không phải một `skip`.
    """
    cat = catalog.get_catalog()
    for model in cat.models:
        if model.id != model.provider_model and cat.providers[model.provider].byok_supported:
            return model
    pytest.fail("catalog phải có một model byok mà alias khác tên gốc của provider")


async def _save_key(session: AsyncSession, user_id: uuid.UUID, provider: str) -> None:
    await ProviderKeyRepository(session).upsert(
        user_id=user_id,
        provider=provider,
        sealed=seal(FAKE_KEY),
        masked=mask_secret(FAKE_KEY),
        verified_at=None,
    )
    await session.commit()


# ════════════════════════ bốn ngả lùi về system key ════════════════════════


async def test_no_row_means_system(session: AsyncSession, user_a: uuid.UUID) -> None:
    """Ca thường: chưa ai cấu hình BYOK ⇒ tiền của người vận hành ⇒ có quota."""
    model = _model_byok()

    assert await resolve_key_source(session, user_id=user_a, model=model) is KeySource.SYSTEM
    cred = await resolve_credential(session, user_id=user_a, model=model)
    assert cred.key_source is KeySource.SYSTEM
    assert cred.api_key is None
    assert cred.provider is None


async def test_deleting_key_returns_to_system(session: AsyncSession, user_a: uuid.UUID) -> None:
    """**DoD dòng 3 của T-2.15** ở mức đơn vị: không cần dọn gì thêm."""
    model = _model_byok()
    await _save_key(session, user_a, model.provider)
    assert await resolve_key_source(session, user_id=user_a, model=model) is KeySource.BYOK

    assert await ProviderKeyRepository(session).delete(user_id=user_a, provider=model.provider)
    await session.commit()

    assert await resolve_key_source(session, user_id=user_a, model=model) is KeySource.SYSTEM


async def test_key_for_OTHER_provider_does_not_count(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """B-140: "có khoá" không đủ — phải là khoá của provider model đang gọi."""
    cat = catalog.get_catalog()
    model = _model_byok()
    other = next(
        name for name in sorted(cat.providers) if name != model.provider and cat.providers[name]
    )
    await _save_key(session, user_a, other)

    assert await resolve_key_source(session, user_id=user_a, model=model) is KeySource.SYSTEM


async def test_provider_disabling_byok_invalidates_old_key(
    session: AsyncSession, user_a: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Người vận hành tắt `byok_supported` ⇒ hàng còn sót KHÔNG lật lại quyết định đó."""
    model = _model_byok()
    await _save_key(session, user_a, model.provider)
    assert await resolve_key_source(session, user_id=user_a, model=model) is KeySource.BYOK

    provider = catalog.get_catalog().providers[model.provider]
    monkeypatch.setattr(provider, "byok_supported", False)

    assert await resolve_key_source(session, user_id=user_a, model=model) is KeySource.SYSTEM


async def test_undecryptable_falls_back_to_system(
    session: AsyncSession, user_a: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`MASTER_ENCRYPTION_KEY` đã xoay ⇒ lùi, KHÔNG ném vào giữa lượt chat."""
    model = _model_byok()
    await _save_key(session, user_a, model.provider)
    monkeypatch.setattr(settings, "MASTER_ENCRYPTION_KEY", SecretStr("mot-master-key-khac-han"))

    assert await resolve_key_source(session, user_id=user_a, model=model) is KeySource.SYSTEM
    cred = await resolve_credential(session, user_id=user_a, model=model)
    assert cred.api_key is None


async def test_SOMEONE_ELSES_key_is_unusable(
    session: AsyncSession, user_a: uuid.UUID, user_b: uuid.UUID
) -> None:
    """§20 — `user_id` lọc **trong câu SQL**; đây là bảng chứa credential."""
    model = _model_byok()
    await _save_key(session, user_b, model.provider)

    assert await resolve_key_source(session, user_id=user_a, model=model) is KeySource.SYSTEM
    assert await resolve_key_source(session, user_id=user_b, model=model) is KeySource.BYOK


# ══════════════════════════ ngả BYOK: có đủ ba thứ ═════════════════════════


async def test_key_for_right_provider_gives_byok_with_plaintext_and_provider(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """Worker cần cả ba: nguồn, bản ghi provider (để có `base_url`), và khoá."""
    model = _model_byok()
    await _save_key(session, user_a, model.provider)

    cred = await resolve_credential(session, user_id=user_a, model=model)

    assert cred.key_source is KeySource.BYOK
    assert cred.api_key == FAKE_KEY
    assert cred.provider is catalog.get_catalog().providers[model.provider]


async def test_model_of_non_byok_provider_is_always_system(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    model = _model_without_byok()
    await _save_key(session, user_a, model.provider)

    assert await resolve_key_source(session, user_id=user_a, model=model) is KeySource.SYSTEM


# ═══════════════════ tên model gửi lên: alias hay tên gốc ══════════════════


async def test_system_model_name_is_litellm_alias(session: AsyncSession, user_a: uuid.UUID) -> None:
    """System đi qua LiteLLM ⇒ tên phải là alias trong `litellm.config.yaml`."""
    model = _model_byok()
    cred = await resolve_credential(session, user_id=user_a, model=model)

    assert cred.model_name(model) == model.id


async def test_byok_model_name_is_provider_native_name(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """BYOK gọi thẳng provider ⇒ alias của LiteLLM ở đó là `400 model not found`.

    Chọn một model mà hai tên **thật sự khác nhau**: `deepseek-flash` có alias
    trùng tên gốc, nên đo trên nó thì bỏ `provider_model` đi test vẫn xanh.
    """
    model = _model_with_two_names()
    await _save_key(session, user_a, model.provider)
    cred = await resolve_credential(session, user_id=user_a, model=model)

    assert cred.model_name(model) == model.provider_model != model.id


# ═════════════ hai đường vào, một lõi: không được trả lời khác ═════════════


@pytest.mark.parametrize("has_key", [False, True])
async def test_both_functions_always_agree_on_key_source(
    session: AsyncSession, user_a: uuid.UUID, has_key: bool
) -> None:
    """Lệch một lần là một lượt vừa được miễn quota vừa tiêu system key."""
    model = _model_byok()
    if has_key:
        await _save_key(session, user_a, model.provider)

    first = await resolve_key_source(session, user_id=user_a, model=model)
    second = (await resolve_credential(session, user_id=user_a, model=model)).key_source

    assert first is second


# ═══════════ T-S.6 — mức suy luận: tham số và tên nào cho đường nào ═══════════

_LEVEL = ReasoningOption(
    id="low",
    params={"thinking": {"type": "enabled", "budget_tokens": 1024}},
    byok_params={"native": {"effort": "low"}},
    alias="alias-cho-litellm",
)
_LEVEL_WITHOUT_BYOK = ReasoningOption(id="high", params={"reasoning_effort": "high"})


def _byok_credential() -> Credential:
    model = _model_byok()
    provider = catalog.get_catalog().providers[model.provider]
    return Credential(key_source=KeySource.BYOK, provider=provider, api_key=FAKE_KEY)


def test_system_path_sends_params_and_alias() -> None:
    model = _model_byok()

    assert SYSTEM_CREDENTIAL.reasoning_params(_LEVEL) == _LEVEL.params
    assert SYSTEM_CREDENTIAL.model_name(model, _LEVEL) == "alias-cho-litellm"


def test_byok_path_sends_byok_params_and_ignores_alias() -> None:
    """Alias là tên trong `litellm.config.yaml`; provider gọi thẳng không biết nó."""
    model = _model_byok()
    cred = _byok_credential()

    assert cred.reasoning_params(_LEVEL) == {"native": {"effort": "low"}}
    assert cred.model_name(model, _LEVEL) == model.provider_model


def test_byok_without_byok_params_falls_back_to_params() -> None:
    """Vắng `byok_params` ⇒ BYOK dùng `params` (T-S.2: `thinking` gốc chạy cả hai đường)."""
    assert _byok_credential().reasoning_params(_LEVEL_WITHOUT_BYOK) == {"reasoning_effort": "high"}


def test_no_level_means_no_params_and_plain_name() -> None:
    model = _model_byok()

    assert SYSTEM_CREDENTIAL.reasoning_params(None) == {}
    assert SYSTEM_CREDENTIAL.model_name(model, None) == model.id


def test_reasoning_params_is_a_deep_copy() -> None:
    """Sửa bản trả về không được chạm dict của catalog — dữ liệu dùng chung cả tiến trình."""
    sent = SYSTEM_CREDENTIAL.reasoning_params(_LEVEL)
    sent["thinking"]["budget_tokens"] = 1

    assert _LEVEL.params["thinking"]["budget_tokens"] == 1024
