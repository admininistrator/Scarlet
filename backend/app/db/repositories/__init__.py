"""Repository — chỗ DUY NHẤT viết câu SQL cho `conversations` và `messages`.

Tầng api/worker không tự dựng `select()`: gom SQL về một chỗ là cách duy nhất
để phép kiểm "có lọc `user_id` trong câu SQL không" (§20) rà được bằng mắt
trong vài phút thay vì đi khắp repo.
"""

from app.db.repositories.audit_logs import AuditLogRepository
from app.db.repositories.conversations import ConversationRepository
from app.db.repositories.errors import (
    ConversationNotFoundError,
    MessageNotInConversationError,
    RepositoryError,
)
from app.db.repositories.messages import (
    GenerationStates,
    MessageRepository,
    OwnedMessage,
    PathNode,
    path_statement,
)
from app.db.repositories.provider_keys import ProviderKeyRepository
from app.db.repositories.usage_events import (
    CostSplit,
    LedgerEntry,
    UsageBucket,
    UsageEventRepository,
)
from app.db.repositories.users import UserRepository

__all__ = [
    "AuditLogRepository",
    "ConversationNotFoundError",
    "ConversationRepository",
    "CostSplit",
    "GenerationStates",
    "LedgerEntry",
    "MessageNotInConversationError",
    "MessageRepository",
    "OwnedMessage",
    "PathNode",
    "ProviderKeyRepository",
    "RepositoryError",
    "UsageBucket",
    "UsageEventRepository",
    "UserRepository",
    "path_statement",
]
