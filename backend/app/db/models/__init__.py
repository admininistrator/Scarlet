"""ORM model khớp DDL của KH Phụ lục A.

`tiers`, `usage_events`… đã có trong DB từ migration 0001 nhưng chưa có model
— task nào dùng tới thì task đó khai, không khai sẵn bảng chết. `users` ra
đời ở T-2.1 (§11.1, §11.6).
"""

from app.db.models.base import Base
from app.db.models.conversation import Conversation
from app.db.models.email_token import EmailToken, EmailTokenPurpose
from app.db.models.message import Message, MessageRole, MessageStatus
from app.db.models.user import User, UserRole, UserStatus

__all__ = [
    "Base",
    "Conversation",
    "EmailToken",
    "EmailTokenPurpose",
    "Message",
    "MessageRole",
    "MessageStatus",
    "User",
    "UserRole",
    "UserStatus",
]
