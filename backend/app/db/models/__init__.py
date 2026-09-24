"""ORM model khớp DDL của KH Phụ lục A.

Bảng nào chưa có task nào dùng tới thì chưa có model — không khai sẵn bảng
chết. `users` ra đời ở T-2.1 (§11.1, §11.6), `tiers` ở T-2.10 (§10.4),
`usage_events` ở T-2.12 (§10.2, A7), `user_provider_keys` ở T-2.14 (§10.5),
`audit_logs` ở T-2.16 (§16.3, §20), `user_settings` ở T-S.5 (§24.2b·S14).
"""

from app.db.models.audit_log import (
    TARGET_CATALOG,
    TARGET_TIER,
    TARGET_USER,
    AuditAction,
    AuditLog,
)
from app.db.models.base import Base
from app.db.models.conversation import Conversation
from app.db.models.email_token import EmailToken, EmailTokenPurpose
from app.db.models.message import Message, MessageFeedback, MessageRole, MessageStatus
from app.db.models.refresh_token import RefreshToken
from app.db.models.tier import Tier
from app.db.models.usage_event import CostConfidence, KeySource, UsageEvent
from app.db.models.user import User, UserRole, UserStatus
from app.db.models.user_provider_key import UserProviderKey
from app.db.models.user_settings import UserSettings

__all__ = [
    "TARGET_CATALOG",
    "TARGET_TIER",
    "TARGET_USER",
    "AuditAction",
    "AuditLog",
    "Base",
    "Conversation",
    "CostConfidence",
    "EmailToken",
    "EmailTokenPurpose",
    "KeySource",
    "Message",
    "MessageFeedback",
    "MessageRole",
    "MessageStatus",
    "RefreshToken",
    "Tier",
    "UsageEvent",
    "User",
    "UserProviderKey",
    "UserRole",
    "UserSettings",
    "UserStatus",
]
