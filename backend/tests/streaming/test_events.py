"""T-1.6 — `app/streaming/events.py`: chín loại event của §7.4.

KH tham chiếu: §7.4, C10, C40 · NQ-23.

Bộ này canh **hợp đồng với trình duyệt**, không canh cài đặt. Ba thứ nó không
cho phép đổi lặng lẽ:

1. Đủ **chín** loại, mỗi loại một `type` khác nhau (bảng §7.4).
2. Khoá payload đúng chữ §7.4 — `delta` là `{"t": …}`, `usage` là
   `{"in": …, "out": …}`. Đổi một tên khoá ở đây là đổi thứ `sse.ts` đọc.
3. `None` của `Usage` **biến mất khỏi payload**, không thành `0` (NQ-23, C40).
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from app.llm.client import Usage
from app.streaming.events import (
    ALL_EVENT_TYPES,
    ArtifactEvent,
    DeltaEvent,
    DoneEvent,
    ErrorCode,
    ErrorEvent,
    ReasoningEvent,
    StartEvent,
    ToolCallEvent,
    ToolResultEvent,
    UsageEvent,
)

#: Đúng chín dòng của bảng §7.4.
TEN_EVENT_CUA_KE_HOACH = {
    "start",
    "delta",
    "reasoning",
    "tool_call",
    "tool_result",
    "artifact",
    "usage",
    "done",
    "error",
}


def _mot_cai_moi_loai() -> list[object]:
    usage = Usage(prompt_tokens=12, completion_tokens=34, total_tokens=46)
    return [
        StartEvent(message_id="m1", model_id="model-x"),
        DeltaEvent(text="xin chào"),
        ReasoningEvent(text="đang nghĩ"),
        ToolCallEvent(call_id="c_1", name="web_search", arguments='{"query":"x"}'),
        ToolResultEvent(call_id="c_1", name="web_search", ok=True, result={"n": 1}),
        ArtifactEvent(artifact_id="a1", version=2),
        UsageEvent(usage=usage),
        DoneEvent(finish_reason="stop", usage=usage),
        ErrorEvent(code=ErrorCode.UPSTREAM_ERROR, message="đứt"),
    ]


def test_du_chin_loai_va_khong_trung_ten() -> None:
    """DoD gián tiếp: tasks.md đòi "dataclass cho 9 loại event ở §7.4"."""
    ten = [cls.TYPE for cls in ALL_EVENT_TYPES]  # type: ignore[attr-defined]
    assert len(ALL_EVENT_TYPES) == 9
    assert set(ten) == TEN_EVENT_CUA_KE_HOACH
    assert len(set(ten)) == len(ten), f"có hai loại trùng `type`: {ten}"


def test_moi_event_json_hoa_duoc() -> None:
    """C10: payload nào cũng phải qua `json.dumps` được, không có object lạ."""
    for event in _mot_cai_moi_loai():
        lai = json.loads(json.dumps(event.data(), ensure_ascii=False))  # type: ignore[attr-defined]
        assert lai == event.data()  # type: ignore[attr-defined]


def test_khoa_payload_dung_chu_cua_ke_hoach() -> None:
    assert DeltaEvent(text="a").data() == {"t": "a"}
    assert ReasoningEvent(text="a").data() == {"t": "a"}
    assert StartEvent(message_id="m1", model_id="mx").data() == {
        "message_id": "m1",
        "model_id": "mx",
    }
    # §7.4: {"name":"web_search","args":{"query":"..."},"call_id":"c_1"}
    assert ToolCallEvent(call_id="c_1", name="web_search", arguments='{"q":1}').data() == {
        "call_id": "c_1",
        "name": "web_search",
        "args": {"q": 1},
    }


@pytest.mark.parametrize("arguments", ["khong-phai-json", "[1,2]", '"chuoi"'])
def test_args_hong_van_giu_nguyen_ban_tho(arguments: str) -> None:
    """Không bỏ im lặng: `args` rỗng nhưng chuỗi gốc đi kèm ở `args_raw`."""
    data = ToolCallEvent(call_id="c", name="n", arguments=arguments).data()
    assert data["args"] == {}
    assert data["args_raw"] == arguments


def test_args_rong_la_object_rong_khong_phai_loi() -> None:
    """Tool không có tham số là chuyện bình thường, không phải JSON hỏng."""
    data = ToolCallEvent(call_id="c", name="n", arguments="").data()
    assert data["args"] == {}
    assert "args_raw" not in data


def test_usage_bo_khoa_khi_provider_khong_bao() -> None:
    """NQ-23/C40: `None` ≠ `0`. Không báo thì khoá **vắng mặt**."""
    data = UsageEvent(usage=Usage(prompt_tokens=100, completion_tokens=7, total_tokens=107)).data()
    assert data == {"in": 100, "out": 7}


def test_usage_mang_reasoning_va_cached_khi_co() -> None:
    data = UsageEvent(
        usage=Usage(
            prompt_tokens=100,
            completion_tokens=7,
            total_tokens=107,
            reasoning_tokens=0,
            cached_prompt_tokens=64,
        )
    ).data()
    # `reasoning_tokens=0` là "báo và bằng 0" ⇒ PHẢI có mặt.
    assert data == {"in": 100, "out": 7, "reasoning": 0, "cached": 64}


def test_done_mang_finish_reason_va_usage() -> None:
    """NQ-23: §7.4 viết `{"finish_reason":"stop","usage":{...}}`."""
    data = DoneEvent(
        finish_reason="stop",
        usage=Usage(prompt_tokens=1204, completion_tokens=389, total_tokens=1593),
    ).data()
    assert data == {"finish_reason": "stop", "usage": {"in": 1204, "out": 389}}


def test_done_khong_dung_usage_gia_khi_provider_im_lang() -> None:
    assert DoneEvent().data() == {"finish_reason": None, "usage": None}


# ─────────────── `cost_usd` trên event `done` — B-78, §7.4 (T-2.12) ───────────


def test_cost_usd_nam_TRONG_khoi_usage_chu_khong_canh_no() -> None:
    """§7.4 viết thẳng hình dạng ấy:

        data: {"finish_reason":"stop","usage":{"in":1204,"out":389,"cost_usd":0.00231}}

    Đặt nó cạnh `usage` thay vì trong đó sẽ làm `sse.ts` của T-1.14 đọc một hợp
    đồng khác hợp đồng đã dán cho FE ở Phụ lục F.
    """
    data = DoneEvent(
        finish_reason="stop",
        usage=Usage(prompt_tokens=1204, completion_tokens=389, total_tokens=1593),
        cost_usd=Decimal("0.002310"),
    ).data()
    assert data == {
        "finish_reason": "stop",
        "usage": {"in": 1204, "out": 389, "cost_usd": 0.00231},
    }


def test_provider_im_lang_ma_meter_van_dem_duoc_thi_usage_chi_co_cost_usd() -> None:
    """Ca huỷ giữa chừng (B-94): không có token nào của provider, nhưng có tiền.

    Hai khoá token **vắng mặt** chứ không bằng 0 — cùng luật với `UsageEvent`
    (NQ-23), và đó là thứ cho FE phân biệt "chưa đo được" với "đã đo và bằng 0".
    """
    data = DoneEvent(finish_reason="cancelled", cost_usd=Decimal("0.000079")).data()
    assert data == {"finish_reason": "cancelled", "usage": {"cost_usd": 7.9e-05}}


def test_ghi_so_hong_thi_khoa_cost_usd_VANG_MAT_chu_khong_bang_0() -> None:
    """`0` nghĩa là "lượt chat này miễn phí" — một câu khác hẳn "chưa ghi sổ được"."""
    data = DoneEvent(
        finish_reason="stop",
        usage=Usage(prompt_tokens=10, completion_tokens=2, total_tokens=12),
    ).data()
    assert "cost_usd" not in data["usage"]


def test_usage_giua_chung_KHONG_bao_gio_mang_cost_usd() -> None:
    """Khác biệt duy nhất giữa `usage` và `done` — xem docstring `UsageEvent`.

    Giá chỉ chốt được khi lượt sinh đã khép (A7); một con số tiền tạm ở giữa
    stream là nguồn sự thật thứ hai cho hoá đơn, và là một thanh quota nhảy lùi
    khi `done` tới với con số thật.
    """
    data = UsageEvent(usage=Usage(prompt_tokens=100, completion_tokens=7, total_tokens=107)).data()
    assert "cost_usd" not in data


def test_error_luon_co_ma() -> None:
    """DoD dòng 3: bản ghi cuối là `error` **có mã lỗi**, không phải im lặng."""
    data = ErrorEvent(code=ErrorCode.UPSTREAM_ERROR, message="connection reset").data()
    assert data["code"] == "UPSTREAM_ERROR"
    assert data["message"] == "connection reset"


def test_ma_loi_khong_trung_gia_tri() -> None:
    gia_tri = [c.value for c in ErrorCode]
    assert len(set(gia_tri)) == len(gia_tri)


def test_emoji_va_xuong_dong_qua_duoc_json() -> None:
    """DoD dòng 6, nửa thuần tuý: `json.dumps` → `json.loads` giữ nguyên chuỗi."""
    chu = "Dòng một 🎉\nDòng hai 😀\r\nkết thúc"
    day = json.dumps(DeltaEvent(text=chu).data(), ensure_ascii=False)
    assert "\n" not in day, "xuống dòng thật lọt vào `data:` sẽ cắt đôi khung SSE (C10)"
    assert json.loads(day)["t"] == chu
