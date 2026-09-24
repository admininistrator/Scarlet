"""Hình dạng của `user_settings.prefs_json` (§24.2b·S4, S10, S14) — T-S.5.

Hai khoá, đúng chữ hàng "Dữ liệu" của S14:

- `avatar_color` — **tên** một màu trong bảng token của T-HD1-v2, không phải
  mã màu (A3, NQ-116). Backend không biết bảng màu: nó chỉ kiểm hình dạng tên
  (`api/v1/settings.py`), còn FE gặp tên lạ thì rơi về màu mặc định.
- `reasoning` — `{model_id: level_id}`, mức suy luận người này đã chọn cho từng
  model. Trên dây nó tên là `reasoning_prefs` (`PUT /settings`, `/auth/me`);
  trong JSON lưu trữ nó là `reasoning`, chữ của S14.

┌──────────────────────────────────────────────────────────────────────────┐
│  KIỂM LÚC GHI, BỎ QUA LÚC ĐỌC                                            │
└──────────────────────────────────────────────────────────────────────────┘

`PUT /settings` từ chối một cặp mà catalog không khai (`400`). Nhưng catalog là
file sửa nóng (§19.1): một cặp hợp lệ hôm qua có thể hết hợp lệ sau một lần
`POST /admin/catalog/reload`. `read_prefs` vì vậy **bỏ qua** cặp ấy thay vì ném
— cùng lý lẽ Cạm bẫy ③ của T-3.0 cho `default_model`: một dòng cấu hình admin
vừa sửa không được ném lỗi vào mặt một người không làm gì cả.

Cặp bị bỏ qua **không** bị xoá khỏi DB lúc đọc (đọc không ghi). Nó biến mất ở
lần `PUT` kế tiếp, vì FE gửi lại đúng thứ `/auth/me` đã đưa cho nó — và nếu
admin bật lại mức ấy trước đó thì lựa chọn cũ của người dùng quay về nguyên vẹn.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.config import catalog

#: Khoá trong `prefs_json` — tên cột dữ liệu đã lưu, không đổi tên được như
#: một định danh Python (S2: "khoá lưu trữ là dữ liệu").
KEY_AVATAR_COLOR = "avatar_color"
KEY_REASONING = "reasoning"


@dataclass(frozen=True, slots=True)
class UserPrefs:
    """Tuỳ chọn cá nhân sống trong `prefs_json` — không phải cột của `users`."""

    #: `None` = chưa chọn ⇒ FE dùng màu mặc định.
    avatar_color: str | None = None
    #: `model_id → level_id`. Rỗng = chưa nhớ mức nào ⇒ `reasoning.default`
    #: của catalog (thứ tự thắng của S4: body › đã nhớ › mặc định).
    reasoning: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        """JSON để ghi **đè cả** `prefs_json` — `PUT` thay cả tài nguyên (§18.4).

        `avatar_color: None` thì vắng khoá, không lưu `null`: "chưa chọn" chỉ có
        một cách viết trong DB.
        """
        out: dict[str, Any] = {KEY_REASONING: dict(self.reasoning)}
        if self.avatar_color is not None:
            out[KEY_AVATAR_COLOR] = self.avatar_color
        return out


def read_prefs(raw: Mapping[str, Any] | None) -> UserPrefs:
    """`prefs_json` → `UserPrefs`, bỏ qua mọi cặp suy luận không còn hợp lệ.

    `None` (người chưa từng lưu, chưa có hàng `user_settings`) đọc như `{}`.
    Giá trị sai kiểu — chỉ có thể đến từ một lần sửa tay trong `psql` — cũng
    bị bỏ qua chứ không nổ: đây là đường của `/auth/me`, endpoint FE dùng để
    định tuyến (T-3.1b), và nó không được hỏng vì một ô tuỳ chọn.

    Một cặp hợp lệ khi model còn trong catalog, còn `enabled`, và còn khai mức
    ấy (`catalog.supports_reasoning`, cùng luật với lúc ghi).
    """
    raw = raw or {}

    color = raw.get(KEY_AVATAR_COLOR)
    avatar_color = color if isinstance(color, str) else None

    stored = raw.get(KEY_REASONING)
    reasoning: dict[str, str] = {}
    if isinstance(stored, Mapping):
        for model_id, level in stored.items():
            if not isinstance(level, str):
                continue
            model = catalog.get_model(model_id)
            if model is not None and catalog.supports_reasoning(model, level):
                reasoning[model_id] = level

    return UserPrefs(avatar_color=avatar_color, reasoning=reasoning)
