"""Lỗi của tầng repository.

Vì sao là exception chứ không phải `return None`: ba hàm đọc
(`get_conversation`, `get_message`, …) trả `None` khi không thấy — đó là câu
trả lời hợp lệ cho "user này có thấy tài nguyên kia không" và là cách API trả
**404** thay vì 403 (§20, mục IDOR). Còn `create_message` thì không có "kết quả
rỗng" nào hợp lý: gọi nó với một `parent_id` thuộc hội thoại khác là một lỗi
lập trình ở tầng trên, phải nổ to chứ không được im lặng tạo message mồ côi.

Thông điệp chỉ chứa UUID, không chứa nội dung message (§20).
"""

from __future__ import annotations

import uuid


class RepositoryError(Exception):
    """Gốc cho mọi lỗi do repository phát hiện."""


class ConversationNotFoundError(RepositoryError):
    """Hội thoại không tồn tại, đã xoá mềm, hoặc KHÔNG thuộc `user_id`.

    Gộp ba trường hợp vào một lỗi là cố ý: tầng API map nó thành 404 cho cả ba,
    nên kẻ dò không phân biệt được "không có" với "có nhưng của người khác".
    """

    def __init__(self, conversation_id: uuid.UUID, user_id: uuid.UUID) -> None:
        super().__init__(
            f"conversation {conversation_id} không tồn tại, đã xoá, hoặc không thuộc user {user_id}"
        )
        self.conversation_id = conversation_id
        self.user_id = user_id


class MessageNotInConversationError(RepositoryError):
    """`parent_id` / `active_leaf_id` không nằm trong hội thoại đang thao tác.

    FK `messages.parent_id` chỉ bảo đảm message cha TỒN TẠI, không bảo đảm nó
    cùng hội thoại — nên phép kiểm này là lớp duy nhất chặn việc nối hai cây
    của hai hội thoại khác nhau làm một.
    """

    def __init__(self, message_id: uuid.UUID, conversation_id: uuid.UUID) -> None:
        super().__init__(
            f"message {message_id} không thuộc conversation {conversation_id} (hoặc đã bị xoá mềm)"
        )
        self.message_id = message_id
        self.conversation_id = conversation_id
