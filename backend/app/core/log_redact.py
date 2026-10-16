"""Redact secret khỏi MỌI log record — cạm bẫy C20 — T-2.14.

KH tham chiếu: §10.5 (C20), §14 bảng "BYOK", §15 bảng "Log" · tasks.md T-2.14.

C20: *"key của user hiện trong log hoặc trong thông báo lỗi. Nguyên nhân: log
cả object request hoặc để exception của SDK nổi lên nguyên văn. Kiểm:
`grep -rE "sk-[a-zA-Z0-9]{20,}" logs/` phải rỗng; có một **middleware redact
chạy trên mọi log record**."*

┌──────────────────────────────────────────────────────────────────────────┐
│  VÌ SAO LÀ RECORD FACTORY, KHÔNG PHẢI MIDDLEWARE ASGI, KHÔNG PHẢI FILTER │
└──────────────────────────────────────────────────────────────────────────┘

Cùng kiểu đọc mà `core/deps.py` đã dùng cho chữ "middleware" của §11.3: §10.5
mô tả một **tính chất** ("chạy trên mọi log record"), và chỗ đúng để có tính
chất ấy trong Python là `logging.setLogRecordFactory`.

* **Middleware ASGI sai chỗ.** Nó chỉ thấy request/response của tiến trình
  `api`. Dòng log nguy hiểm nhất lại đến từ nơi khác: `httpx` in URL, một
  `logger.exception` trong `app/llm/`, và cả tiến trình `worker` — nơi không
  có ASGI nào cả.
* **`logging.Filter` gắn vào logger thì lọt.** Filter của một logger chỉ chạy
  cho record được log **trực tiếp** trên logger đó, không chạy cho record
  truyền lên từ logger con (`logging` gọi `filter()` ở `Logger.handle` của
  logger gốc phát ra record, rồi `callHandlers` đi lên cây mà **không** hỏi
  filter của logger cha). Gắn vào từng handler thì phủ đủ, nhưng handler là
  thứ uvicorn/arq dựng **sau** khi app import, nên sẽ có một cửa sổ không ai
  che — và mỗi handler mới thêm sau này là một chỗ để quên.
* **Record factory là nút cổ chai duy nhất.** Mọi `LogRecord` trong tiến trình
  đều đi qua nó, bất kể logger nào, handler nào, thư viện nào — kể cả
  `httpx`, `openai`, `sqlalchemy`, `uvicorn.access`, `arq`.

┌──────────────────────────────────────────────────────────────────────────┐
│  CHE CÁI GÌ                                                              │
└──────────────────────────────────────────────────────────────────────────┘

Ba mẫu, và phạm vi của chúng được nói thẳng ra ở đây thay vì để người đọc sau
tưởng file này che được mọi thứ:

1. `sk-…` — đúng họ mẫu mà C20 lấy làm phép kiểm, và là dạng khoá của **cả
   hai** provider `byok_supported` trong catalog hôm nay.
2. `Bearer <token>` — bắt theo **vị trí**, không theo hình dạng khoá, nên nó
   phủ được cả provider có khoá không bắt đầu bằng `sk-`. Đây là mẫu quan
   trọng nhất: đường rò thật của C20 là ai đó log nguyên một object request,
   và trong object đó khoá luôn nằm sau chữ `Bearer`.
3. `x-api-key: …` / `api_key=…` / `authorization: …` — cùng ý với (2) cho
   những kiểu xác thực còn lại của catalog (`AuthStyle`).

**Cái nó KHÔNG che:** một khoá trần, không tiền tố, không tên trường đi kèm —
ví dụ `logger.info(key)`. Không mẫu nào phân biệt được chuỗi ấy với một
`message_id`, một Redis Stream ID hay một hash; một mẫu "chuỗi dài ngẫu nhiên"
sẽ ăn hết log và biến file này thành thứ người ta tắt đi. Lớp phòng thủ cho ca
đó là luật ở tầng trên: bản rõ chỉ tồn tại trong `app/core/crypto.py` và trong
đúng một biến cục bộ của `api/v1/settings.py`, và không chỗ nào log nó.

┌──────────────────────────────────────────────────────────────────────────┐
│  `exc_text` — NỬA CÒN LẠI CỦA C20                                        │
└──────────────────────────────────────────────────────────────────────────┘

C20 nói hai đường: "log cả object request" **và** "để exception của SDK nổi
lên nguyên văn". Đường thứ hai không nằm trong `record.msg` — nó nằm trong
traceback, thứ `Formatter` mới dựng ra lúc ghi. Chặn nó bằng cách dựng traceback
**ngay tại đây**, che, rồi gán vào `record.exc_text`: `logging.Formatter.format`
dùng lại `exc_text` khi nó đã có sẵn thay vì tự format lần nữa.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

#: Thay cho phần bí mật. Giữ lại phần nhận dạng phía trước (`sk-`, `Bearer `,
#: tên header) để dòng log còn nói được *cái gì* đã bị che.
REDACTED = "[REDACTED]"

#: (mẫu, chuỗi thay). Thứ tự không quan trọng — các mẫu không lồng nhau.
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # 1. Khoá dạng `sk-…`. Ngưỡng 16 (C20 dùng 20) để chặt hơn phép kiểm, chứ
    #    không vừa khít nó: một khoá 18 ký tự lọt qua grep của C20 vẫn là một
    #    khoá bị rò.
    (re.compile(r"sk-[A-Za-z0-9_-]{16,}"), f"sk-{REDACTED}"),
    # 2. `Bearer <token>`. `\S+` chứ không một bảng ký tự: token của provider
    #    nào cũng là "phần còn lại tới khoảng trắng".
    (re.compile(r"(?i)\bBearer\s+\S+"), f"Bearer {REDACTED}"),
    # 3. Tên trường mang bí mật, ở cả hai lối viết (`header: value` của HTTP và
    #    `key=value`/`'key': 'value'` của một dict Python được `repr`).
    #    Nhóm 1 giữ nguyên (tên + dấu phân cách + dấu nháy mở nếu có), phần
    #    giá trị bị thay. `[^\s,}\]]+` dừng ở dấu phân cách của dict/JSON, nên
    #    một `repr(dict)` chỉ mất đúng giá trị của trường ấy.
    (
        re.compile(
            r"(?i)((?:x-api-key|api[_-]?key|authorization)['\"]?\s*[:=]\s*['\"]?)[^\s,}\]]+"
        ),
        rf"\1{REDACTED}",
    ),
)

#: Đặt một lần cho mỗi tiến trình. Gọi lại là không làm gì — nếu không, mỗi
#: lần gọi sẽ bọc thêm một lớp factory quanh lớp trước và `_scrub` chạy n lần
#: trên cùng một record.
_installed = False


def redact(text: str) -> str:
    """Che mọi bí mật nhận ra được trong một chuỗi. Xem docstring module."""
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _redact_any(value: Any) -> Any:
    """Che nếu là chuỗi, giữ nguyên **kiểu** nếu không.

    Không ép `dict`/`list`/object sang `str` để che: `%`-format dựng chuỗi cuối
    bằng `%s`/`%r` của chính chúng, nên ép sớm ở đây sẽ đổi kết quả của những
    dòng log dùng `%d`/`%.2f`/`%r`. Ca "khoá nằm trong một dict đem đi log" vì
    vậy che ở lối vào khác: `record.msg` khi msg **là** object đó, và
    `record.exc_text` khi nó đi trong một exception.

    **Trừ exception** (T-9.5a): `logger.warning("… %s", mid, error)` — chữ lỗi
    của SDK/provider (có thể nhại lại khoá) nằm trong `str(error)`, thứ `%s`
    dựng lúc ghi, sau mọi lớp che. Ép sang `str` chỉ đổi `%r` của nó.
    """
    if isinstance(value, BaseException):
        return redact(str(value))
    return redact(value) if isinstance(value, str) else value


def _scrub(record: logging.LogRecord) -> None:
    """Che tại chỗ ba nguồn chữ của một record: `msg`, `args`, traceback."""
    if isinstance(record.msg, str):
        record.msg = redact(record.msg)
    else:
        # `logger.info(some_object)` — `getMessage()` sẽ gọi `str()` lên nó,
        # tức đây là chỗ duy nhất còn chặn được nếu object ấy là một dict
        # request có khoá bên trong. `args` giữ nguyên: `%`-format (nếu có)
        # vẫn chạy y như trước, chỉ trên một chuỗi đã che.
        record.msg = redact(str(record.msg))

    if isinstance(record.args, tuple):
        record.args = tuple(_redact_any(v) for v in record.args)
    elif isinstance(record.args, dict):
        # `logger.info("%(k)s", {"k": v})` — `LogRecord.__init__` giữ nguyên
        # dict làm nguồn cho `%`-format theo tên.
        record.args = {k: _redact_any(v) for k, v in record.args.items()}

    if record.exc_info is not None and not record.exc_text:
        # Dựng traceback ở đây để che được nó — xem docstring module.
        record.exc_text = redact(logging.Formatter().formatException(record.exc_info))

    if record.stack_info:
        record.stack_info = redact(record.stack_info)


def install_log_redaction() -> None:
    """Cài `_scrub` vào record factory của tiến trình. Idempotent.

    Gọi ở **cả ba** entrypoint của backend — `app/main.py` (api),
    `app/workers/main.py` (worker), `app/cli.py` (lệnh vận hành) — vì mỗi cái
    là một tiến trình riêng với một record factory riêng.
    """
    global _installed
    if _installed:
        return
    previous: Callable[..., logging.LogRecord] = logging.getLogRecordFactory()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        _scrub(record)
        return record

    logging.setLogRecordFactory(factory)
    _installed = True
