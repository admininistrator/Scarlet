"""Cloudflare Turnstile — lớp thứ ba trong bốn lớp của RR-1 (§11.6) — T-2.6.

KH tham chiếu: §11.6, §18.1, RR-1 · CLAUDE.md A3, A4 · tasks.md T-2.6.

RR-1 ("đăng ký mở → người lạ tiêu tiền của bạn") liệt kê **bốn** lớp:
`REGISTRATION_MODE=approval` · verify email · **Turnstile** · quota. Ba lớp kia
đã có từ T-2.1/T-2.2 và T-2.10+; file này là lớp còn thiếu, và nó là lớp duy
nhất chặn được *máy* trước khi máy đó kịp tạo một hàng trong `users` và một lá
thư đi ra khỏi SMTP.

┌──────────────────────────────────────────────────────────────────────────┐
│  CẠM BẪY CỦA T-2.6: bỏ qua ÂM THẦM                                       │
└──────────────────────────────────────────────────────────────────────────┘

"Bỏ qua âm thầm khi thiếu secret nghĩa là một ngày nào đó bạn deploy
production mà không có captcha và không biết."

Vì vậy `TURNSTILE_SECRET` rỗng có đúng MỘT nghĩa — tắt — và nó được nói ra ở
`Settings._warn_on_boot`, mỗi lần boot, kèm tên cả hai route đang mất lớp bảo
vệ. Cảnh báo ấy **không chạy trong container** cho tới hôm nay: `.env` cho
biến này một giá trị dài 52 ký tự bắt đầu bằng `#` (B-118), tức truthy. Đó là
lý do B-118 phải đóng **trước** file này — mọi dòng dưới đây đều đứng trên câu
hỏi "biến này có rỗng thật không".

┌──────────────────────────────────────────────────────────────────────────┐
│  KHÔNG HỎI ĐƯỢC CLOUDFLARE ⇒ 503, KHÔNG CHO QUA                          │
└──────────────────────────────────────────────────────────────────────────┘

Cùng lý lẽ đã chốt hai lần trong Phase 2: `core/deps.py` (Redis chết ⇒ 503,
không tha blacklist) và `core/ratelimit.py` (Redis chết ⇒ 503, không tha hạn
mức). Không hỏi được nghĩa là **không biết**, và cho qua khi không biết là gỡ
đúng lớp phòng thủ vào lúc hệ thống đang hỏng — tức lúc dễ bị lợi dụng nhất và
khó phát hiện nhất.

Cái giá: Cloudflare sập thì không ai đăng ký được. Với 15–20 người dùng và một
hàng đợi duyệt tay (§11.1), hoãn vài phút không mất gì; ngược lại, một lần
"fail open" là một cửa mở mà không dòng log nào phân biệt được với lưu lượng
thật.

┌──────────────────────────────────────────────────────────────────────────┐
│  THIẾU TOKEN THÌ KHÔNG GỌI CLOUDFLARE                                    │
└──────────────────────────────────────────────────────────────────────────┘

`400` ngay tại chỗ. Không phải để tiết kiệm một round-trip, mà vì đường ngược
lại biến endpoint thành một cách bắt server của mình gọi ra ngoài Internet với
mỗi request rác — chính thứ mà mọi lớp rate limit trong `core/ratelimit.py`
sinh ra để chặn.

`400` chứ không `422`: nếu `turnstile_token` là field **bắt buộc** của pydantic
thì thiếu nó ra `422 VALIDATION_ERROR`, trong khi DoD T-2.6 đòi `400`. Đó
không phải một chi tiết hình thức — `422` là "body sai kiểu, sửa client đi",
còn `400 TURNSTILE_FAILED` là "giải lại captcha", hai câu khác nhau cho hai
người đọc khác nhau. Vì vậy field khai là `str | None = None` và phép kiểm
nằm ở đây.

┌──────────────────────────────────────────────────────────────────────────┐
│  `error-codes` CỦA CLOUDFLARE ĐI VÀO LOG, KHÔNG VÀO RESPONSE             │
└──────────────────────────────────────────────────────────────────────────┘

`invalid-input-secret` (mình cấu hình sai) và `invalid-input-response` (người
gọi gửi token rác) là hai sự cố hoàn toàn khác nhau đối với **người vận hành**,
và không khác gì nhau đối với **người dùng** — cả hai đều chỉ có một việc để
làm: giải lại. Trả `error-codes` ra ngoài còn nói cho kẻ tấn công biết secret
của mình có hợp lệ hay không, đúng loại thông tin §20 không cho rò.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import status

from app.config.settings import settings
from app.core.errors import ApiError, ApiErrorCode

logger = logging.getLogger(__name__)

#: Câu trả lời DUY NHẤT cho mọi kiểu hỏng của Turnstile — xem docstring module.
_LOI_TURNSTILE = "xac minh captcha khong thanh cong, hay thu lai"

#: Tên field trong body `siteverify` (hợp đồng của Cloudflare, không phải lựa
#: chọn của mình — nên là hằng ở đây chứ không phải cấu hình, cùng lối
#: `ToolCall.to_wire()` với `"type": "function"` của §9.1).
_FIELD_SECRET = "secret"
_FIELD_RESPONSE = "response"
_FIELD_REMOTEIP = "remoteip"


def da_bat() -> bool:
    """Turnstile có đang bật không — `TURNSTILE_SECRET` khác rỗng (§11.6).

    Đọc `settings` lúc **gọi**, không lúc import: cùng lý do với `doc_gioi_han`
    của `core/ratelimit.py` — một test bật/tắt Turnstile phải thấy hiệu lực mà
    không cần nạp lại module.
    """
    return bool(settings.TURNSTILE_SECRET.get_secret_value().strip())


def _tao_client() -> httpx.AsyncClient:
    """Client cho MỘT lần gọi `siteverify`.

    Tách thành hàm riêng để test bơm `httpx.MockTransport` vào mà vẫn chạy qua
    **toàn bộ** đường thật: dựng form, gửi, đọc JSON, xử lý mã trạng thái. Một
    stub đặt ở tầng cao hơn (`_hoi_cloudflare` chẳng hạn) sẽ bỏ qua đúng phần
    dễ sai nhất.
    """
    return httpx.AsyncClient(timeout=settings.TURNSTILE_TIMEOUT_S)


async def _hoi_cloudflare(token: str, remote_ip: str | None) -> dict[str, Any]:
    """Gọi `siteverify`, trả về JSON đã parse. Ném `ApiError` 503 nếu không hỏi được."""
    form = {
        _FIELD_SECRET: settings.TURNSTILE_SECRET.get_secret_value(),
        _FIELD_RESPONSE: token,
    }
    if remote_ip is not None:
        # Tuỳ chọn của Cloudflare. Gửi khi biết vì nó cho phía kia đối chiếu
        # IP đã giải captcha với IP đang gửi token — một token bị chuyển sang
        # máy khác sẽ lộ ra ở đó.
        form[_FIELD_REMOTEIP] = remote_ip

    try:
        async with _tao_client() as client:
            resp = await client.post(settings.TURNSTILE_VERIFY_URL, data=form)
            resp.raise_for_status()
            ket_qua = resp.json()
    except Exception as loi:
        # KHÔNG log `form` — nó chứa `secret`.
        logger.exception("khong hoi duoc Turnstile siteverify")
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ApiErrorCode.SERVICE_UNAVAILABLE,
            "khong xac minh duoc captcha, hay thu lai",
        ) from loi

    if not isinstance(ket_qua, dict):
        # `raise_for_status` đã qua nhưng body không phải object — với một
        # proxy chen giữa thì chuyện này xảy ra được, và `ket_qua["success"]`
        # bên dưới sẽ nổ thành 500 thay vì một câu nói đúng việc.
        logger.error("Turnstile tra ve body khong phai JSON object: %s", type(ket_qua).__name__)
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ApiErrorCode.SERVICE_UNAVAILABLE,
            "khong xac minh duoc captcha, hay thu lai",
        )
    return ket_qua


async def kiem_turnstile(token: str | None, *, remote_ip: str | None = None) -> None:
    """Chặn request nếu Turnstile không qua. Không qua ⇒ raise, qua ⇒ trả `None`.

    Args:
        token: giá trị `cf-turnstile-response` do widget sinh ra ở FE. `None`
            hoặc chuỗi trắng đều là "không kèm token".
        remote_ip: IP người gọi (`core/ratelimit.py::dia_chi_ip`). Không bắt
            buộc; `None` thì bỏ trường `remoteip` đi.

    Raises:
        ApiError 400 `TURNSTILE_FAILED`: thiếu token, hoặc Cloudflare trả
            `success: false`.
        ApiError 503 `SERVICE_UNAVAILABLE`: không hỏi được Cloudflare — xem
            docstring module, mục vì sao không cho qua.
    """
    if not da_bat():
        # Cảnh báo đã kêu lúc boot (`Settings._warn_on_boot`), không lặp lại ở
        # mỗi request: một dòng log mỗi lần đăng ký sẽ làm chính nó thành nhiễu.
        return

    if token is None or not token.strip():
        raise ApiError(status.HTTP_400_BAD_REQUEST, ApiErrorCode.TURNSTILE_FAILED, _LOI_TURNSTILE)

    ket_qua = await _hoi_cloudflare(token.strip(), remote_ip)
    if ket_qua.get("success") is True:
        return

    # `error-codes` vào log, không vào response — xem docstring module.
    logger.warning(
        "Turnstile tu choi mot request tu %s: error-codes=%s",
        remote_ip or "khong ro",
        ket_qua.get("error-codes"),
    )
    raise ApiError(status.HTTP_400_BAD_REQUEST, ApiErrorCode.TURNSTILE_FAILED, _LOI_TURNSTILE)
