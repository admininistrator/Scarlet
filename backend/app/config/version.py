"""Số phiên bản của backend, đọc từ `pyproject.toml` — T-2.20.

KH tham chiếu: §16.3 (màn "Hệ thống"), §19.1 · CLAUDE.md A3 · tasks.md T-2.20,
B-70.

§16.3 đòi màn hình "Hệ thống" hiển thị *"phiên bản"*, và câu hỏi duy nhất đáng
bàn là **đọc nó ở đâu**. Con số ấy đã tồn tại đúng một chỗ — dòng `version =`
của `pyproject.toml` — nên mọi cách trả lời khác đều là dựng thêm một nguồn sự
thật thứ hai, thứ sẽ lệch vào đúng ngày phát hành mà ai đó chỉ sửa một trong
hai.

**Vì sao KHÔNG `importlib.metadata.version()`.** Đó là cách đúng cho một package
đã cài, và nó chạy tốt trong `.venv` của dev (`pip install -e .`). Trong
container thì **không**: B-70 đã cố ý bỏ `pip install .` khỏi `Dockerfile` vì
nó tạo ra hai bản `app/` mà một bản định vị `config/` sai, nên image không có
metadata của phân phối nào cả. Đo được: `PackageNotFoundError: No package
metadata was found for scarlet-backend`, và nó nổ **lúc chạy**, trên đúng màn
hình mà người ta mở ra khi hệ thống đang có vấn đề.

**Đọc lúc import, không đọc mỗi request.** File này không đổi khi tiến trình
đang sống, nên đọc lại mỗi lần là một lần chạm đĩa cho một chuỗi bất biến. Hệ
quả cố ý: thiếu `pyproject.toml` thì app **không boot** kèm đường dẫn nó đã tìm
— cùng lối fail-fast của §19.2, và ngược với ngả trả về `"unknown"`, thứ biến
một lỗi đóng gói thành một dòng chữ mờ trên màn hình quản trị.

`parents[2]` chứ không `parents[3]` của `catalog.py`: hai file cùng nằm trong
`app/config/` nhưng trỏ tới hai thứ khác nhau. `config/` là thư mục **mount
riêng** ở gốc (`/config` trong container, `<repo>/config` trên host), còn
`pyproject.toml` nằm cạnh `app/` (`/app/pyproject.toml`, `backend/pyproject.toml`)
— xem dòng `COPY` tương ứng trong `backend/Dockerfile`.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

#: `pyproject.toml` nằm cạnh `app/`: `/app/pyproject.toml` trong container,
#: `backend/pyproject.toml` trên host. Cùng một `parents[2]` cho cả hai.
PYPROJECT_PATH = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _doc_phien_ban() -> str:
    if not PYPROJECT_PATH.is_file():
        raise RuntimeError(
            f"khong tim thay {PYPROJECT_PATH} — image thieu dong COPY pyproject.toml "
            "(xem backend/Dockerfile), hoac cay thu muc da doi"
        )
    return str(tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))["project"]["version"])


#: Phiên bản đang chạy. `GET /admin/system` trả về đúng chuỗi này.
APP_VERSION = _doc_phien_ban()
