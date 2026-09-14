"""T-1.4 — `app/llm/context.py`: dựng ngữ cảnh từ cây, cắt theo ngân sách token.

KH tham chiếu: §9.6, §8.3, §19.1, C11, C15, C12 · B-33.

Bốn dòng DoD của task nằm ở các test có chữ **DoD** trong docstring:

- `test_chi_gui_duong_di_cua_mot_nhanh` — cây 3 nhánh, build từ nhánh 2 (C11)
- `test_cat_theo_ngan_sach_tren_hoi_thoai_200_message` — `context_window=8000`
- `test_cat_khong_bao_gio_de_lai_tool_result_mo_coi` — nhát cắt rơi vào giữa
  một cặp tool (C15)
- (dòng "≥ 10 case xanh" là cả file này)

Cây dùng trong bộ này là cây **thật trong Postgres**, đi qua đúng
`MessageRepository.get_path` mà T-1.2 viết (xem docstring của
`tests/conftest.py`). Dựng một danh sách message chép tay rồi kiểm sẽ bỏ lọt
đúng thứ C11 nói tới: `get_path` mới là chỗ quyết định nhánh nào bị bỏ.

Hai phép kiểm quan trọng nhất ở đây không phải "hàm trả về đúng" mà **"hàm
không trả về thứ nó không được trả"**: không có message của nhánh khác (C11),
và không có `tool_result` mồ côi (C15). Cả hai đều xanh với một cài đặt sai
theo cách hiển nhiên, nên chúng được viết dưới dạng so với *toàn bộ cây*, không
phải so với một danh sách chép tay.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.catalog import ModelEntry
from app.config.settings import settings
from app.db.models import Conversation, Message, MessageRole, MessageStatus
from app.db.repositories import ConversationRepository, MessageRepository
from app.llm import context
from app.llm.context import (
    BudgetTooSmallError,
    EmptyPathError,
    build,
    render_system_prompt,
    token_budget,
)
from app.llm.tokens import count_message, count_messages

#: Model giả lập. Không phải model OpenAI ⇒ đi đúng nhánh "xấp xỉ" của §9.6.
MODEL_ID = "model-thu-nghiem"
TEN_HIEN_THI = "Model Thử Nghiệm"

#: Hình dạng của DoD dòng 2: ba nhánh tách nhau ngay từ gốc, mỗi nhánh sâu 4.
SO_NHANH = 3
SO_TANG = 4

#: DoD dòng 3.
SO_MESSAGE_200 = 200
CONTEXT_WINDOW_8000 = 8000
MAX_OUTPUT_8000 = 1024

#: Nhãn đủ dài để 200 message chắc chắn KHÔNG cùng vừa ngân sách ở trên
#: (≈ 5976 token). Nhãn ngắn thì bộ test xanh mà chẳng cắt gì — đúng loại xanh
#: giả mà DoD này sinh ra để bắt.
NHAN_DAI = (
    "Đây là một message đủ dài để hai trăm cái như nó không thể cùng vừa trong một cửa sổ "
    "ngữ cảnh tám nghìn token, nên bộ dựng ngữ cảnh buộc phải cắt bớt phần quá khứ đi"
)


def _model(
    *, context_window: int = 128_000, max_output: int = 4096, model_id: str = MODEL_ID
) -> ModelEntry:
    """`model_meta` tối thiểu — chỉ ba trường mà §9.6 thực sự đọc."""
    return ModelEntry(
        id=model_id,
        display_name=TEN_HIEN_THI,
        provider="thu-nghiem",
        upstream_model="thu-nghiem/model-v1",
        context_window=context_window,
        max_output=max_output,
        pricing_mode="unmetered",
    )


async def _hoi_thoai(session: AsyncSession, user_id: uuid.UUID) -> Conversation:
    return await ConversationRepository(session).create_conversation(user_id=user_id)


async def _them(
    session: AsyncSession,
    conversation: Conversation,
    user_id: uuid.UUID,
    *,
    role: MessageRole,
    parent: Message | None = None,
    content: str = "",
    status: MessageStatus | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    tool_call_id: str | None = None,
    reasoning: str | None = None,
) -> Message:
    """Thêm một node. `tool_calls`/`reasoning` đặt thẳng vì repository chưa nhận.

    `MessageRepository.create_message` (T-1.1) cố ý chỉ nhận các trường mà
    đường ghi của §7.2 dùng tới. Hai cột này do T-1.6 ghi, nên ở đây đặt trực
    tiếp rồi `flush` — vẫn là dữ liệu đi qua Postgres thật.
    """
    message = await MessageRepository(session).create_message(
        conversation_id=conversation.id,
        user_id=user_id,
        role=role,
        parent_id=parent.id if parent is not None else None,
        content=content,
        status=status,
        tool_call_id=tool_call_id,
    )
    if tool_calls is not None:
        message.tool_calls = tool_calls
    if reasoning is not None:
        message.reasoning = reasoning
    if tool_calls is not None or reasoning is not None:
        await session.flush()
    return message


async def _day_thang(
    session: AsyncSession,
    conversation: Conversation,
    user_id: uuid.UUID,
    *,
    sau: int,
    nhan: str,
    goc: Message | None = None,
) -> list[Message]:
    """Một dây thẳng `sau` tầng, xen kẽ user/assistant."""
    day: list[Message] = []
    cha = goc
    for tang in range(sau):
        cha = await _them(
            session,
            conversation,
            user_id,
            role=MessageRole.USER if tang % 2 == 0 else MessageRole.ASSISTANT,
            parent=cha,
            content=f"{nhan}-t{tang}",
        )
        day.append(cha)
    return day


def _goi_tool(call_id: str, *, ten: str = "web_search") -> dict[str, Any]:
    """Đúng hình dạng khối `tool_calls` của dây OpenAI — hợp đồng ở `_to_wire`."""
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": ten, "arguments": '{"query":"thời tiết Hà Nội"}'},
    }


def _khong_co_mo_coi(messages: list[dict[str, Any]]) -> None:
    """Bất biến của C15: mọi `tool_result` phải có `tool_call` khai nó phía trên.

    Kiểm cả chiều ngược lại: mọi `tool_call` phải có `tool_result` trả lời.
    Hai chiều là hai cách khác nhau để ăn `400 invalid request`.
    """
    da_khai: set[str] = set()
    da_tra_loi: set[str] = set()
    for message in messages:
        if message["role"] == MessageRole.TOOL.value:
            assert message["tool_call_id"] in da_khai, (
                f"tool_result mồ côi: {message['tool_call_id']!r} không có tool_call nào khai"
            )
            da_tra_loi.add(message["tool_call_id"])
        for call in message.get("tool_calls") or ():
            da_khai.add(call["id"])
    assert da_khai == da_tra_loi, f"tool_call không có tool_result: {da_khai - da_tra_loi}"


def _noi_dung(messages: list[dict[str, Any]]) -> list[str]:
    return [m["content"] for m in messages]


# ───────────────────────── system prompt (§19.1) ─────────────────────────


def test_system_prompt_dung_dau_va_khong_rong() -> None:
    noi_dung = render_system_prompt(model_display_name=TEN_HIEN_THI)
    assert noi_dung.strip()
    assert "{{" not in noi_dung, "template chưa được render"


def test_system_prompt_mang_ten_hien_thi_cua_model() -> None:
    """Biến duy nhất mà `system.jinja` khai — hợp đồng giữa file và code."""
    assert TEN_HIEN_THI in render_system_prompt(model_display_name=TEN_HIEN_THI)


def test_system_prompt_cache_60_giay() -> None:
    """§19.1: sửa file có hiệu lực trong 60 s, và giữa hai lần thì KHÔNG chạm đĩa.

    Đếm số lần `get_template` — đó là lần duy nhất Jinja đọc file. Chạm vào
    `context._ENV` là cố ý: thứ cần kiểm chính là "có đọc lại hay không", và
    không có cách nào quan sát nó từ bên ngoài.
    """
    context.reload_system_prompt()
    that = context._ENV.get_template
    dem: list[str] = []

    def dem_roi_goi(name: str) -> Any:
        dem.append(name)
        return that(name)

    context._ENV.get_template = dem_roi_goi  # type: ignore[method-assign]
    try:
        render_system_prompt(model_display_name=TEN_HIEN_THI)
        render_system_prompt(model_display_name=TEN_HIEN_THI)
        assert len(dem) == 1, "lần thứ hai trong TTL vẫn đọc đĩa"

        assert context._cached_template is not None
        context._cached_template.loaded_at -= context.SYSTEM_PROMPT_TTL_S + 1
        render_system_prompt(model_display_name=TEN_HIEN_THI)
        assert len(dem) == 2, "quá TTL mà vẫn dùng bản cache — sửa file sẽ không có hiệu lực"
    finally:
        context._ENV.get_template = that  # type: ignore[method-assign]
        context.reload_system_prompt()


# ───────────────────────────── ngân sách (§9.6) ────────────────────────────


def test_token_budget_dung_cong_thuc_9_6() -> None:
    model_meta = _model(context_window=CONTEXT_WINDOW_8000, max_output=MAX_OUTPUT_8000)
    assert token_budget(model_meta) == (
        CONTEXT_WINDOW_8000 - MAX_OUTPUT_8000 - settings.RESERVE_TOKENS
    )


def test_context_window_cap_ham_model_khai_cua_so_khong_lo() -> None:
    """`CONTEXT_WINDOW_CAP` là chỗ chặn hoá đơn, không phải chặn kỹ thuật."""
    khong_lo = _model(context_window=settings.CONTEXT_WINDOW_CAP * 10, max_output=1000)
    assert token_budget(khong_lo) == (settings.CONTEXT_WINDOW_CAP - 1000 - settings.RESERVE_TOKENS)


# ─────────────────────────── đường đi & nhánh (C11) ────────────────────────


async def test_chi_gui_duong_di_cua_mot_nhanh(session: AsyncSession, user_a: uuid.UUID) -> None:
    """**DoD**: cây 3 nhánh × 4 tầng, build từ nhánh 2 → số message = độ dài đường đi.

    Đây là C11 viết thành số: 12 message trong hội thoại, đường đi dài 4. Một
    cài đặt gom theo `conversation_id` sẽ trả 12 và test đỏ ngay.
    """
    conversation = await _hoi_thoai(session, user_a)
    nhanh = [
        await _day_thang(session, conversation, user_a, sau=SO_TANG, nhan=f"n{so}")
        for so in range(SO_NHANH)
    ]

    tong_message = await session.scalar(
        select(func.count()).select_from(Message).where(Message.conversation_id == conversation.id)
    )
    assert tong_message == SO_NHANH * SO_TANG

    ket_qua = await build(session, nhanh[1][-1].id, _model(), user_id=user_a)

    # 1 system prompt + đúng độ dài đường đi.
    assert len(ket_qua) == 1 + SO_TANG
    assert ket_qua[0]["role"] == MessageRole.SYSTEM.value
    assert _noi_dung(ket_qua[1:]) == [f"n1-t{tang}" for tang in range(SO_TANG)]
    assert not [c for c in _noi_dung(ket_qua[1:]) if c.startswith(("n0-", "n2-"))]


async def test_thu_tu_la_goc_truoc_la_sau(session: AsyncSession, user_a: uuid.UUID) -> None:
    conversation = await _hoi_thoai(session, user_a)
    day = await _day_thang(session, conversation, user_a, sau=6, nhan="x")
    ket_qua = await build(session, day[-1].id, _model(), user_id=user_a)
    assert _noi_dung(ket_qua[1:]) == [f"x-t{tang}" for tang in range(6)]


async def test_to_tien_bi_xoa_mem_cat_duong_di(session: AsyncSession, user_a: uuid.UUID) -> None:
    """C12: message đã xoá mềm không được lỏn vào ngữ cảnh, và cắt luôn phần trên nó."""
    conversation = await _hoi_thoai(session, user_a)
    day = await _day_thang(session, conversation, user_a, sau=5, nhan="x")
    await MessageRepository(session).soft_delete_message(day[1].id, user_id=user_a)

    ket_qua = await build(session, day[-1].id, _model(), user_id=user_a)
    assert _noi_dung(ket_qua[1:]) == ["x-t2", "x-t3", "x-t4"]


async def test_leaf_cua_user_khac_thi_raise(
    session: AsyncSession, user_a: uuid.UUID, user_b: uuid.UUID
) -> None:
    """IDOR (§20): lọc `user_id` nằm trong SQL của `get_path`, không phải ở đây."""
    conversation = await _hoi_thoai(session, user_a)
    day = await _day_thang(session, conversation, user_a, sau=3, nhan="x")

    with pytest.raises(EmptyPathError):
        await build(session, day[-1].id, _model(), user_id=user_b)


async def test_leaf_khong_ton_tai_thi_raise(session: AsyncSession, user_a: uuid.UUID) -> None:
    with pytest.raises(EmptyPathError):
        await build(session, uuid.uuid4(), _model(), user_id=user_a)


# ──────────────────────── trạng thái message (§7.2) ────────────────────────


async def test_message_assistant_dang_queued_o_la_khong_vao_context(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """§7.2 ③: `leaf_id` chính là message `queued` mà worker sắp viết vào.

    Nó phải tự rụng, nếu không mọi request đều kết thúc bằng một lượt assistant
    rỗng — thứ mà một phần provider từ chối thẳng.
    """
    conversation = await _hoi_thoai(session, user_a)
    cau_hoi = await _them(session, conversation, user_a, role=MessageRole.USER, content="câu hỏi")
    cho_sinh = await _them(
        session,
        conversation,
        user_a,
        role=MessageRole.ASSISTANT,
        parent=cau_hoi,
        status=MessageStatus.QUEUED,
    )

    ket_qua = await build(session, cho_sinh.id, _model(), user_id=user_a)
    assert _noi_dung(ket_qua[1:]) == ["câu hỏi"]


async def test_message_cancelled_van_vao_context(session: AsyncSession, user_a: uuid.UUID) -> None:
    """§7.5 lưu phần đã sinh; người dùng đã đọc nó, nên model cũng phải thấy nó."""
    conversation = await _hoi_thoai(session, user_a)
    cau_hoi = await _them(session, conversation, user_a, role=MessageRole.USER, content="hỏi")
    da_huy = await _them(
        session,
        conversation,
        user_a,
        role=MessageRole.ASSISTANT,
        parent=cau_hoi,
        content="trả lời dở dang",
        status=MessageStatus.CANCELLED,
    )

    ket_qua = await build(session, da_huy.id, _model(), user_id=user_a)
    assert _noi_dung(ket_qua[1:]) == ["hỏi", "trả lời dở dang"]


async def test_trang_thai_chua_xong_bi_loai_ke_ca_khi_DA_CO_chu(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """`failed`/`streaming` bị loại vì TRẠNG THÁI, không phải vì rỗng.

    Phân biệt này có thật: reaper (§7.6) đặt `status='failed'` trên một message
    có thể đã kịp ghi một phần chữ, và FE hiện nút Retry cho nó chứ không coi
    nó là câu trả lời. Gửi nó lên model là để model tiếp lời một câu trả lời mà
    người dùng đã bị báo là hỏng.

    Viết với `content` KHÁC RỖNG là cố ý: nếu hai message này để rỗng thì luật
    "bỏ message rỗng" sẽ che mất luật trạng thái, và nới `USABLE_STATUSES` ra
    cả năm giá trị vẫn xanh — đúng kiểu phép kiểm vô dụng.
    """
    conversation = await _hoi_thoai(session, user_a)
    cau_hoi = await _them(session, conversation, user_a, role=MessageRole.USER, content="hỏi")
    that_bai = await _them(
        session,
        conversation,
        user_a,
        role=MessageRole.ASSISTANT,
        parent=cau_hoi,
        content="một phần chữ đã kịp ghi trước khi worker chết",
        status=MessageStatus.FAILED,
    )
    dang_sinh = await _them(
        session,
        conversation,
        user_a,
        role=MessageRole.ASSISTANT,
        parent=that_bai,
        content="chữ của một lượt CHƯA chốt",
        status=MessageStatus.STREAMING,
    )
    tiep = await _them(
        session, conversation, user_a, role=MessageRole.USER, parent=dang_sinh, content="hỏi lại"
    )

    ket_qua = await build(session, tiep.id, _model(), user_id=user_a)
    assert _noi_dung(ket_qua[1:]) == ["hỏi", "hỏi lại"]


async def test_reasoning_khong_bao_gio_gui_lai(session: AsyncSession, user_a: uuid.UUID) -> None:
    """B-33: `deepseek-flash` sinh 333 chunk reasoning cho một lượt. Gửi lại = nhân đôi hoá đơn."""
    conversation = await _hoi_thoai(session, user_a)
    cau_hoi = await _them(session, conversation, user_a, role=MessageRole.USER, content="hỏi")
    tra_loi = await _them(
        session,
        conversation,
        user_a,
        role=MessageRole.ASSISTANT,
        parent=cau_hoi,
        content="đáp án là 42",
        reasoning="ĐÂY LÀ PHẦN SUY NGHĨ KHÔNG ĐƯỢC GỬI LẠI",
    )

    ket_qua = await build(session, tra_loi.id, _model(), user_id=user_a)
    assert not [m for m in ket_qua if "SUY NGHĨ" in str(m.get("content"))]
    assert not [m for m in ket_qua if "reasoning" in m]


# ──────────────────────────── cắt theo ngân sách ───────────────────────────


async def test_cat_theo_ngan_sach_tren_hoi_thoai_200_message(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """**DoD**: 200 message, `context_window=8000` → kết quả ≤ 8000 − max_output − RESERVE."""
    conversation = await _hoi_thoai(session, user_a)
    day = await _day_thang(session, conversation, user_a, sau=SO_MESSAGE_200, nhan=NHAN_DAI)

    model_meta = _model(context_window=CONTEXT_WINDOW_8000, max_output=MAX_OUTPUT_8000)
    ket_qua = await build(session, day[-1].id, model_meta, user_id=user_a)

    ngan_sach = CONTEXT_WINDOW_8000 - MAX_OUTPUT_8000 - settings.RESERVE_TOKENS
    assert token_budget(model_meta) == ngan_sach
    assert count_messages(ket_qua, model_id=MODEL_ID) <= ngan_sach
    # Có cắt thật (không phải "vừa hết"), và vẫn còn hội thoại để trả lời.
    assert 1 < len(ket_qua) < 1 + SO_MESSAGE_200


async def test_cat_thi_giu_lai_phan_moi_nhat(session: AsyncSession, user_a: uuid.UUID) -> None:
    """§9.6: "message mới nhất → lùi dần về quá khứ" — giữ đoạn CUỐI, không phải đoạn đầu."""
    conversation = await _hoi_thoai(session, user_a)
    day = await _day_thang(session, conversation, user_a, sau=SO_MESSAGE_200, nhan=NHAN_DAI)

    ket_qua = await build(
        session,
        day[-1].id,
        _model(context_window=CONTEXT_WINDOW_8000, max_output=MAX_OUTPUT_8000),
        user_id=user_a,
    )
    noi_dung = _noi_dung(ket_qua[1:])
    assert noi_dung[-1].endswith(f"-t{SO_MESSAGE_200 - 1}")
    assert not noi_dung[0].endswith("-t0")


async def test_khong_co_lo_o_giua_khi_cat(session: AsyncSession, user_a: uuid.UUID) -> None:
    """Dừng ở khối đầu tiên không vừa, KHÔNG nhảy qua nó để nhặt khối cũ hơn.

    Nhảy qua tạo ra một lỗ giữa hội thoại, và model sẽ bịa ra đoạn nối.
    """
    conversation = await _hoi_thoai(session, user_a)
    day = await _day_thang(session, conversation, user_a, sau=SO_MESSAGE_200, nhan=NHAN_DAI)

    ket_qua = await build(
        session,
        day[-1].id,
        _model(context_window=CONTEXT_WINDOW_8000, max_output=MAX_OUTPUT_8000),
        user_id=user_a,
    )
    so_tang = [int(c.rsplit("-t", 1)[1]) for c in _noi_dung(ket_qua[1:])]
    assert so_tang[0] > 0, "không cắt gì thì phép kiểm này vô nghĩa"
    assert so_tang == list(range(so_tang[0], SO_MESSAGE_200))


async def test_ngan_sach_qua_nho_thi_raise(session: AsyncSession, user_a: uuid.UUID) -> None:
    """Thà nổ còn hơn gửi một request chắc chắn bị provider từ chối."""
    conversation = await _hoi_thoai(session, user_a)
    cau_hoi = await _them(session, conversation, user_a, role=MessageRole.USER, content="hỏi")

    chat_hep = _model(context_window=settings.RESERVE_TOKENS + 2, max_output=1)
    with pytest.raises(BudgetTooSmallError):
        await build(session, cau_hoi.id, chat_hep, user_id=user_a)


# ─────────────────────────── cặp tool nguyên tử (C15) ──────────────────────


async def _cay_co_cap_tool(
    session: AsyncSession, user_a: uuid.UUID, *, call_id: str = "call_1"
) -> tuple[Conversation, list[Message]]:
    """user → assistant(tool_call) → tool(result) → assistant(đáp) → user.

    Kết quả của tool cố ý DÀI, còn lời gọi tool thì ngắn: nhờ chênh lệch đó mới
    đặt được một ngân sách vừa đúng chỗ khiến nhát cắt rơi vào giữa cặp.
    """
    conversation = await _hoi_thoai(session, user_a)
    q1 = await _them(session, conversation, user_a, role=MessageRole.USER, content="thời tiết?")
    goi = await _them(
        session,
        conversation,
        user_a,
        role=MessageRole.ASSISTANT,
        parent=q1,
        tool_calls=[_goi_tool(call_id)],
    )
    ket_qua_tool = await _them(
        session,
        conversation,
        user_a,
        role=MessageRole.TOOL,
        parent=goi,
        tool_call_id=call_id,
        content="KẾT QUẢ TOOL " + ("rất dài " * 200),
    )
    dap = await _them(
        session,
        conversation,
        user_a,
        role=MessageRole.ASSISTANT,
        parent=ket_qua_tool,
        content="Hà Nội hôm nay nắng.",
    )
    q2 = await _them(
        session, conversation, user_a, role=MessageRole.USER, parent=dap, content="còn mai?"
    )
    return conversation, [q1, goi, ket_qua_tool, dap, q2]


async def test_cap_tool_di_qua_nguyen_ven_khi_du_cho(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """Hình dạng khối `tool_calls` đi lên dây NGUYÊN VĂN — hợp đồng của cột JSONB."""
    _, day = await _cay_co_cap_tool(session, user_a)
    ket_qua = await build(session, day[-1].id, _model(), user_id=user_a)

    _khong_co_mo_coi(ket_qua)
    goi = [m for m in ket_qua if m.get("tool_calls")]
    assert len(goi) == 1
    assert goi[0]["tool_calls"] == [_goi_tool("call_1")]
    assert goi[0]["tool_calls"][0]["function"]["arguments"] == '{"query":"thời tiết Hà Nội"}'


async def test_cat_khong_bao_gio_de_lai_tool_result_mo_coi(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """**DoD**: nhát cắt rơi vào GIỮA một cặp tool → không có `tool_result` mồ côi.

    Ngân sách được tính ra từ chính chi phí đo được, để nhát cắt rơi đúng vào
    khe giữa `tool_call` và `tool_result`: vừa đủ cho `tool_result` nhưng
    **không** đủ cho cả cặp. Một cài đặt cắt theo từng message sẽ nhặt
    `tool_result` vào rồi bỏ lại `tool_call` — và ăn `400 invalid request`.
    """
    _, day = await _cay_co_cap_tool(session, user_a)
    q1, goi, ket_qua_tool, dap, q2 = day

    do = _model()
    he_thong = count_messages(
        [
            {
                "role": MessageRole.SYSTEM.value,
                "content": render_system_prompt(model_display_name=TEN_HIEN_THI),
            }
        ],
        model_id=MODEL_ID,
    )
    duoi = count_message({"role": "user", "content": "còn mai?"}, model_id=MODEL_ID)
    duoi += count_message(
        {"role": "assistant", "content": "Hà Nội hôm nay nắng."}, model_id=MODEL_ID
    )
    gia_tool_result = count_message(
        {"role": "tool", "tool_call_id": "call_1", "content": ket_qua_tool.content},
        model_id=MODEL_ID,
    )

    # Vừa đúng chỗ: đủ cho `tool_result`, thiếu cho `tool_call` đi kèm nó.
    ngan_sach = he_thong + duoi + gia_tool_result
    cua_so = ngan_sach + do.max_output + settings.RESERVE_TOKENS
    chat = _model(context_window=cua_so, max_output=do.max_output)

    ket_qua = await build(session, q2.id, chat, user_id=user_a)

    _khong_co_mo_coi(ket_qua)
    assert not [m for m in ket_qua if m["role"] == MessageRole.TOOL.value]
    assert not [m for m in ket_qua if m.get("tool_calls")]
    assert _noi_dung(ket_qua[1:]) == ["Hà Nội hôm nay nắng.", "còn mai?"]
    assert q1.content not in _noi_dung(ket_qua)
    assert goi.id != dap.id  # cả hai node vẫn còn nguyên trong cây


async def test_tool_result_mo_coi_trong_du_lieu_bi_bo(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """Một `tool` không có `tool_call` nào khai nó — dữ liệu hỏng, không được gửi đi."""
    conversation = await _hoi_thoai(session, user_a)
    q1 = await _them(session, conversation, user_a, role=MessageRole.USER, content="hỏi")
    mo_coi = await _them(
        session,
        conversation,
        user_a,
        role=MessageRole.TOOL,
        parent=q1,
        tool_call_id="call_khong_ai_khai",
        content="kết quả của một lời gọi không tồn tại",
    )
    q2 = await _them(
        session, conversation, user_a, role=MessageRole.USER, parent=mo_coi, content="hỏi tiếp"
    )

    ket_qua = await build(session, q2.id, _model(), user_id=user_a)

    _khong_co_mo_coi(ket_qua)
    assert _noi_dung(ket_qua[1:]) == ["hỏi", "hỏi tiếp"]


async def test_tool_call_thieu_tool_result_thi_go_tool_calls_nhung_giu_chu(
    session: AsyncSession, user_a: uuid.UUID
) -> None:
    """Nửa còn lại của C15: `tool_call` không ai trả lời cũng là `400`.

    Xảy ra mỗi khi một lượt sinh chết sau lúc model khai tool, trước lúc tool
    trả lời. Phần chữ của lượt đó người dùng đã thấy nên phải giữ.
    """
    conversation = await _hoi_thoai(session, user_a)
    q1 = await _them(session, conversation, user_a, role=MessageRole.USER, content="hỏi")
    goi = await _them(
        session,
        conversation,
        user_a,
        role=MessageRole.ASSISTANT,
        parent=q1,
        content="Để tôi tra cứu đã.",
        tool_calls=[_goi_tool("call_khong_bao_gio_tra_loi")],
    )
    q2 = await _them(
        session, conversation, user_a, role=MessageRole.USER, parent=goi, content="hỏi tiếp"
    )

    ket_qua = await build(session, q2.id, _model(), user_id=user_a)

    _khong_co_mo_coi(ket_qua)
    assert _noi_dung(ket_qua[1:]) == ["hỏi", "Để tôi tra cứu đã.", "hỏi tiếp"]
    assert not [m for m in ket_qua if m.get("tool_calls")]
