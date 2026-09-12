"""ORM model khớp DDL của KH Phụ lục A.

Phase 1 chỉ cần hai bảng của cây hội thoại (§8). `users`, `tiers`,
`usage_events`… đã có trong DB từ migration 0001 nhưng chưa có model — task
nào dùng tới thì task đó khai, không khai sẵn bảng chết.
"""

from app.db.models.base import Base
from app.db.models.conversation import Conversation
from app.db.models.message import Message, MessageRole, MessageStatus

__all__ = ["Base", "Conversation", "Message", "MessageRole", "MessageStatus"]
