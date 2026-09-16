"""`Mailer` interface + `SMTPMailer` (§11.5) — T-2.2.

KH tham chiếu: §11.5, R6, UC-01 · CLAUDE.md A3, A4.

┌──────────────────────────────────────────────────────────────────────────┐
│  VÌ SAO `smtplib` (thư viện chuẩn) QUA `asyncio.to_thread`, KHÔNG THÊM    │
│  MỘT DEPENDENCY SMTP-ASYNC MỚI                                            │
└──────────────────────────────────────────────────────────────────────────┘

`smtplib.SMTP.send_message` là I/O đồng bộ (connect/login/send chặn thread).
Codebase đã có đúng một tiền lệ cho "thư viện chặn nhưng phải chạy trong tiến
trình `api` dùng chung một event loop" — `core/security.py::hash_password`
bọc Argon2id (CPU-bound, chặn) bằng `asyncio.to_thread`. Gửi mail là cùng một
hình dạng vấn đề (I/O-bound thay vì CPU-bound, nhưng cùng một chỗ chặn event
loop), nên cùng một cách giải quyết — không có lý do mở thêm một thư viện
(`aiosmtplib`…) cho một endpoint gọi vài lần một ngày.

┌──────────────────────────────────────────────────────────────────────────┐
│  VÌ SAO SEND LỖI KHÔNG LÀM `POST /auth/register` TRẢ 500                 │
└──────────────────────────────────────────────────────────────────────────┘

`api/v1/auth.py::register` commit user + token TRƯỚC khi gọi `mailer.send()`.
Nếu SMTP chết giữa lúc đó, tài khoản đã tồn tại thật — trả 500 sẽ nói dối
("đăng ký thất bại") trong khi nó đã thành công, và pending_email vẫn dùng lại
được qua `resend-verification` (chính là lý do endpoint đó tồn tại). Router
bắt exception, log, và trả response CỐ ĐỊNH y như đường thành công — im lặng
với người dùng nhưng không im lặng với người vận hành (`logger.exception`).
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Protocol

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config.settings import settings

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "email"

_jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html"]),
)

#: Tiêu đề mail theo tên template — chuỗi hiển thị tiếng Việt, không phải loại
#: literal mà A3 cấm (tên model/giá/URL provider/hạn mức), nên nằm thẳng ở
#: đây thay vì một bảng cấu hình riêng.
_SUBJECTS: dict[str, str] = {
    "verify_email": "Xac thuc email - Scarlet",
    "reset_password": "Dat lai mat khau - Scarlet",
}


class Mailer(Protocol):
    """Interface duy nhất mà router được gọi — `app/api/` không biết SMTP."""

    async def send(self, *, template: str, to: str, ctx: dict[str, Any]) -> None: ...


class SMTPMailer:
    """Cài đặt bằng SMTP, cấu hình hoàn toàn bằng `.env` (§11.5).

    Dev trỏ vào Mailpit (`SMTP_HOST=mailpit`, không gửi ra ngoài thật); T-H8
    đổi bốn biến `SMTP_*` sang provider thật (Resend/Brevo/SendGrid) khi mời
    người thật vào, KHÔNG sửa file này.
    """

    def __init__(self) -> None:
        self._host = settings.SMTP_HOST
        self._port = settings.SMTP_PORT
        self._user = settings.SMTP_USER
        self._password = settings.SMTP_PASSWORD.get_secret_value()
        self._tls = settings.SMTP_TLS
        self._from = settings.MAIL_FROM
        self._timeout_s = settings.SMTP_TIMEOUT_S

    async def send(self, *, template: str, to: str, ctx: dict[str, Any]) -> None:
        """Render `{template}.html` + `{template}.txt`, gửi multipart/alternative."""
        message = EmailMessage()
        message["Subject"] = _SUBJECTS[template]
        message["From"] = self._from
        message["To"] = to
        message.set_content(_jinja_env.get_template(f"{template}.txt").render(**ctx))
        message.add_alternative(
            _jinja_env.get_template(f"{template}.html").render(**ctx), subtype="html"
        )
        await asyncio.to_thread(self._send_sync, message)

    def _send_sync(self, message: EmailMessage) -> None:
        with smtplib.SMTP(self._host, self._port, timeout=self._timeout_s) as smtp:
            if self._tls:
                smtp.starttls()
            if self._user:
                smtp.login(self._user, self._password)
            smtp.send_message(message)


#: Instance dùng chung — không có state theo request nên một instance module-
#: scope là đủ, cùng lối với `_hasher` của `core/security.py`.
mailer: Mailer = SMTPMailer()
