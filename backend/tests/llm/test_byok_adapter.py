"""`ByokAdapter` dựng request đúng hợp đồng §9.1, không gọi mạng — T-2.15.

KH tham chiếu: §9.1 (bảng hai adapter), §10.5, §9.2, B-166 · CLAUDE.md A3, A9.

Cạm bẫy của T-2.15 là *"hai code path streaming khác nhau cho hai adapter"*,
nên phép kiểm nặng nhất ở đây **không** phải một assert về header mà là nhóm
cuối: hai adapter phải cùng đi qua **một** thân `stream()`. Một bản sao lặng
lẽ sẽ làm mọi test khác trong file này vẫn xanh.

Ba thứ còn lại là ba thứ chỉ sai một lần là đủ đắt: `base_url` lấy nhầm
(khoá của người dùng gửi tới LiteLLM ⇒ `401`, hoặc tệ hơn: gửi tới đúng chỗ
nhưng với credential hệ thống), `extra_headers` rơi mất (B-166 ⇒ provider trả
`400` giữa lượt chat), và `max_retries` > 0 (một câu trả lời tính tiền **của
người dùng** hai lần).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from test_system_adapter import FakeCompletions, FakeStream, load_sdk_chunks

from app.config import catalog
from app.config.catalog import Provider
from app.config.settings import Settings
from app.llm.adapters import openai_compat
from app.llm.adapters.byok import ByokAdapter
from app.llm.adapters.system import SystemAdapter

KHOA_GIA = "sk-" + "fedcba9876543210" * 2


def _provider(**ghi_de: Any) -> Provider:
    """Bản ghi provider dựng từ catalog thật rồi ghi đè đúng thứ đang đo."""
    goc = next(p for p in catalog.get_catalog().providers.values() if p.byok_supported)
    return goc.model_copy(update=ghi_de)


def _adapter_gia(provider: Provider) -> tuple[ByokAdapter, FakeCompletions]:
    adapter = ByokAdapter.for_provider(provider, api_key=KHOA_GIA)
    completions = FakeCompletions(FakeStream(load_sdk_chunks("nr-gemini-flash.text.jsonl")))
    adapter._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))  # type: ignore[assignment]
    return adapter, completions


async def _drain(adapter: ByokAdapter, **ghi_de: Any) -> list[Any]:
    kwargs: dict[str, Any] = {
        "model": "ten-goc-cua-provider",
        "messages": [{"role": "user", "content": "xin chào"}],
        "tools": None,
        "max_tokens": 128,
        "temperature": 0.0,
        "extra": {},
    }
    kwargs.update(ghi_de)
    return [chunk async for chunk in await adapter.stream(**kwargs)]


# ═════════════════ địa chỉ và credential: hàng 2 của bảng §9.1 ═════════════


def test_base_url_lay_tu_catalog_khong_phai_litellm() -> None:
    """§9.1: `ByokAdapter` trỏ `provider.base_url`. Trỏ nhầm LiteLLM là gửi
    khoá của người dùng tới một cổng xác thực bằng khoá của mình."""
    provider = _provider()
    adapter = ByokAdapter.for_provider(provider, api_key=KHOA_GIA)

    assert str(adapter._client.base_url).rstrip("/") == provider.base_url.rstrip("/")


def test_dung_khoa_cua_user_chu_khong_phai_khoa_he_thong() -> None:
    adapter = ByokAdapter.for_provider(_provider(), api_key=KHOA_GIA)

    assert adapter._client.api_key == KHOA_GIA


def test_timeout_la_cua_luot_sinh_chu_khong_phai_cua_nut_luu_khoa() -> None:
    """`LLM_REQUEST_TIMEOUT_S`, không phải `BYOK_VERIFY_TIMEOUT_S`."""
    config = Settings()
    adapter = ByokAdapter.for_provider(_provider(), api_key=KHOA_GIA, config=config)

    assert adapter._client.timeout == float(config.LLM_REQUEST_TIMEOUT_S)
    assert adapter._client.timeout != float(config.BYOK_VERIFY_TIMEOUT_S)


def test_khong_tu_retry() -> None:
    """Thử lại một lượt đã sinh dở là tính tiền **của người dùng** lần hai."""
    assert ByokAdapter.for_provider(_provider(), api_key=KHOA_GIA)._client.max_retries == 0


# ══════════════════ B-166 — `extra_headers` đi cả đường GỌI ════════════════


def test_extra_headers_cua_catalog_di_vao_moi_request() -> None:
    """Thiếu chúng thì provider trả `400` giữa lượt chat, không phải lúc lưu khoá."""
    provider = _provider(extra_headers={"x-mot-header-bat-buoc": "gia-tri"})
    adapter = ByokAdapter.for_provider(provider, api_key=KHOA_GIA)

    assert adapter._client.default_headers["x-mot-header-bat-buoc"] == "gia-tri"


def test_khong_co_extra_headers_thi_khong_gan_gi() -> None:
    adapter = ByokAdapter.for_provider(_provider(extra_headers={}), api_key=KHOA_GIA)

    assert "x-mot-header-bat-buoc" not in adapter._client.default_headers


def test_extra_headers_KHONG_de_len_duoc_header_xac_thuc() -> None:
    """`Provider.extra_headers` không được mang credential — và không đè được nó.

    SDK dựng `Authorization` từ `api_key` ở mỗi request, **sau** khối
    `default_headers`, nên một `Authorization` gõ nhầm vào catalog không thay
    được khoá đang dùng. Cùng tính chất mà `byok_verify._headers_for` giữ
    bằng thứ tự merge.
    """
    provider = _provider(extra_headers={"Authorization": "Bearer khoa-cua-nguoi-khac"})
    adapter = ByokAdapter.for_provider(provider, api_key=KHOA_GIA)

    assert adapter._client.auth_headers == {"Authorization": f"Bearer {KHOA_GIA}"}


# ══════════════ cạm bẫy T-2.15: MỘT thân stream, không phải hai ════════════


def test_hai_adapter_dung_CHUNG_mot_than_stream() -> None:
    """Chép `stream()` ra bản thứ hai là chép luôn năm quyết định của nó."""
    assert ByokAdapter.stream is openai_compat.OpenAICompatAdapter.stream
    assert SystemAdapter.stream is openai_compat.OpenAICompatAdapter.stream


async def test_luon_bat_include_usage() -> None:
    """C40 — quên cờ này trên đường BYOK là `cost_usd = 0` cho mọi lượt."""
    adapter, completions = _adapter_gia(_provider())
    await _drain(adapter)

    assert completions.kwargs["stream_options"] == {"include_usage": True}
    assert completions.kwargs["stream"] is True


async def test_gui_dung_ten_model_duoc_truyen_vao() -> None:
    """Adapter KHÔNG tra catalog: `Credential.model_name` đã chọn tên rồi."""
    adapter, completions = _adapter_gia(_provider())
    await _drain(adapter, model="ten-goc-123")

    assert completions.kwargs["model"] == "ten-goc-123"


async def test_parser_chung_cho_ra_chunk_chuan_hoa() -> None:
    """ADR-04: cùng parser ⇒ worker không biết adapter nào đang chạy."""
    adapter, _ = _adapter_gia(_provider())
    chunks = await _drain(adapter)

    assert [c.kind for c in chunks][-1] == "done"
    assert any(c.kind == "delta" for c in chunks)


async def test_close_dong_pool() -> None:
    """Vòng đời một lượt: không đóng là để kết nối MANG KHOÁ nằm treo."""
    da_dong = False

    class _ClientGia:
        async def close(self) -> None:
            nonlocal da_dong
            da_dong = True

    adapter = ByokAdapter.for_provider(_provider(), api_key=KHOA_GIA)
    adapter._client = _ClientGia()  # type: ignore[assignment]
    await adapter.close()

    assert da_dong


def test_khong_co_instance_toan_cuc_o_tang_module() -> None:
    """`AsyncOpenAI` gắn với event loop; một instance module-level là một pool chết."""
    import app.llm.adapters.byok as mod

    assert not [
        ten
        for ten, gia_tri in vars(mod).items()
        if isinstance(gia_tri, ByokAdapter)  # pragma: no cover - phòng hồi quy
    ]


@pytest.mark.parametrize("tools", [None, []])
async def test_khong_co_tool_thi_khong_gui_khoa_tools(tools: list[Any] | None) -> None:
    """§9.4/C18 — luật này phải áp cho **cả hai** adapter, không chỉ system."""
    from openai import omit

    adapter, completions = _adapter_gia(_provider())
    await _drain(adapter, tools=tools)

    assert completions.kwargs["tools"] is omit
