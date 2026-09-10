"""initial schema

KH tham chiếu: §17, Phụ lục A. DDL chép nguyên văn từ Phụ lục A — không tự ý
đổi tên cột/bảng/index. Thứ tự tạo bảng tuân theo cạm bẫy vòng tròn của T-0.5:
``conversations.active_leaf_id`` tham chiếu ``messages`` nhưng ``messages``
tham chiếu ``conversations`` — tạo hai bảng trước, ``ALTER TABLE ADD
CONSTRAINT fk_active_leaf`` sau.

Revision ID: 0001
Revises:
Create Date: 2026-09-10
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "citext"')

    # ─────────────────────── Người dùng & quyền ───────────────────────
    op.execute(
        "CREATE TYPE user_status AS ENUM "
        "('pending_email','pending_approval','active','rejected','suspended')"
    )
    op.execute("CREATE TYPE user_role AS ENUM ('user','admin')")

    op.execute(
        """
        CREATE TABLE tiers (
            name                TEXT PRIMARY KEY,
            limit_5h_usd        NUMERIC(10,4) NOT NULL DEFAULT 0.50,
            limit_7d_usd        NUMERIC(10,4) NOT NULL DEFAULT 3.00,
            can_execute_skills  BOOLEAN NOT NULL DEFAULT FALSE,
            can_use_web         BOOLEAN NOT NULL DEFAULT TRUE,
            web_searches_per_day INT    NOT NULL DEFAULT 50,
            max_upload_mb       INT     NOT NULL DEFAULT 10,
            max_attachments     INT     NOT NULL DEFAULT 5,
            allowed_model_tags  TEXT[]  NOT NULL DEFAULT '{}',
            is_default          BOOLEAN NOT NULL DEFAULT FALSE
        )
        """
    )

    op.execute(
        """
        CREATE TABLE users (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email           CITEXT NOT NULL UNIQUE,
            password_hash   TEXT NOT NULL,
            display_name    TEXT,
            status          user_status NOT NULL DEFAULT 'pending_email',
            role            user_role   NOT NULL DEFAULT 'user',
            tier_name       TEXT NOT NULL REFERENCES tiers(name) DEFAULT 'free',
            limit_override_json JSONB,
            email_verified_at   TIMESTAMPTZ,
            approved_at         TIMESTAMPTZ,
            approved_by         UUID REFERENCES users(id),
            last_login_at       TIMESTAMPTZ,
            password_changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at      TIMESTAMPTZ
        )
        """
    )
    op.execute("CREATE INDEX ix_users_status ON users(status) WHERE deleted_at IS NULL")

    op.execute(
        """
        CREATE TABLE refresh_tokens (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            family_id   UUID NOT NULL,
            token_hash  TEXT NOT NULL UNIQUE,
            expires_at  TIMESTAMPTZ NOT NULL,
            used_at     TIMESTAMPTZ,
            revoked_at  TIMESTAMPTZ,
            user_agent  TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_refresh_family ON refresh_tokens(family_id)")

    op.execute(
        """
        CREATE TABLE email_tokens (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            purpose     TEXT NOT NULL CHECK (purpose IN ('verify','reset')),
            token_hash  TEXT NOT NULL UNIQUE,
            expires_at  TIMESTAMPTZ NOT NULL,
            used_at     TIMESTAMPTZ,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE user_provider_keys (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            provider     TEXT NOT NULL,
            key_cipher   BYTEA NOT NULL,
            key_nonce    BYTEA NOT NULL,
            key_last4    TEXT  NOT NULL,
            verified_at  TIMESTAMPTZ,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (user_id, provider)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE user_settings (
            user_id       UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            theme         TEXT NOT NULL DEFAULT 'system',
            default_model TEXT,
            prefs_json    JSONB NOT NULL DEFAULT '{}'::jsonb,
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    # ─────────────────────────── Hội thoại (CÂY) ───────────────────────────
    op.execute("CREATE TYPE message_role AS ENUM ('system','user','assistant','tool')")
    op.execute(
        "CREATE TYPE message_status AS ENUM "
        "('queued','streaming','completed','failed','cancelled')"
    )

    op.execute(
        """
        CREATE TABLE conversations (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title           TEXT,
            default_model   TEXT,
            system_prompt_override TEXT,
            active_leaf_id  UUID,
            pinned          BOOLEAN NOT NULL DEFAULT FALSE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at      TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_conv_user ON conversations(user_id, updated_at DESC) "
        "WHERE deleted_at IS NULL"
    )

    op.execute(
        """
        CREATE TABLE messages (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            parent_id       UUID REFERENCES messages(id),
            role            message_role   NOT NULL,
            status          message_status NOT NULL DEFAULT 'completed',
            content         TEXT NOT NULL DEFAULT '',
            reasoning       TEXT,
            model_id        TEXT,
            tool_calls      JSONB,
            tool_call_id    TEXT,
            finish_reason   TEXT,
            error_code      TEXT,
            prompt_tokens     INT,
            completion_tokens INT,
            heartbeat_at    TIMESTAMPTZ,
            raw_response    JSONB,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at      TIMESTAMPTZ
        )
        """
    )
    op.execute("CREATE INDEX ix_msg_conv_parent ON messages(conversation_id, parent_id)")
    op.execute("CREATE INDEX ix_msg_parent ON messages(parent_id)")
    op.execute(
        "CREATE INDEX ix_msg_streaming ON messages(heartbeat_at) WHERE status = 'streaming'"
    )

    op.execute(
        """
        ALTER TABLE conversations
          ADD CONSTRAINT fk_active_leaf FOREIGN KEY (active_leaf_id)
          REFERENCES messages(id) ON DELETE SET NULL
        """
    )

    # ─────────────────────────── File & artifact ───────────────────────────
    op.execute(
        """
        CREATE TABLE attachments (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            message_id      UUID REFERENCES messages(id) ON DELETE SET NULL,
            kind            TEXT NOT NULL,
            mime_type       TEXT NOT NULL,
            original_name   TEXT NOT NULL,
            size_bytes      BIGINT NOT NULL,
            storage_key     TEXT NOT NULL,
            width           INT,
            height          INT,
            extracted_text  TEXT,
            extract_status  TEXT NOT NULL DEFAULT 'none',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_att_user ON attachments(user_id, created_at DESC)")

    op.execute(
        """
        CREATE TABLE artifacts (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            message_id          UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
            parent_artifact_id  UUID REFERENCES artifacts(id),
            version             INT  NOT NULL DEFAULT 1,
            kind                TEXT NOT NULL,
            language            TEXT,
            title               TEXT NOT NULL,
            content             TEXT,
            storage_key         TEXT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_art_msg ON artifacts(message_id)")

    # ─────────────────────────── Chi phí & quota ───────────────────────────
    op.execute(
        """
        CREATE TABLE usage_events (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            message_id        UUID REFERENCES messages(id) ON DELETE SET NULL,
            model_id          TEXT NOT NULL,
            provider          TEXT NOT NULL,
            key_source        TEXT NOT NULL CHECK (key_source IN ('system','byok')),
            prompt_tokens     INT NOT NULL DEFAULT 0,
            completion_tokens INT NOT NULL DEFAULT 0,
            cached_tokens     INT NOT NULL DEFAULT 0,
            cost_usd          NUMERIC(12,6) NOT NULL DEFAULT 0,
            cost_confidence   TEXT NOT NULL DEFAULT 'exact'
                              CHECK (cost_confidence IN ('exact','low')),
            price_snapshot    JSONB NOT NULL,
            upstream_model_reported TEXT,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_usage_user_time ON usage_events(user_id, created_at DESC)")
    op.execute("CREATE INDEX ix_usage_time ON usage_events(created_at DESC)")

    # ─────────────────────────── Share, skill, vận hành ───────────────────
    op.execute(
        """
        CREATE TABLE shared_conversations (
            token           TEXT PRIMARY KEY,
            owner_id        UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
            snapshot_json   JSONB NOT NULL,
            view_count      INT NOT NULL DEFAULT 0,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            revoked_at      TIMESTAMPTZ
        )
        """
    )

    op.execute(
        """
        CREATE TABLE skills (
            name        TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            description TEXT NOT NULL,
            path        TEXT NOT NULL,
            requires_execution BOOLEAN NOT NULL DEFAULT FALSE,
            enabled     BOOLEAN NOT NULL DEFAULT TRUE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE user_skills (
            user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            skill_name TEXT NOT NULL REFERENCES skills(name) ON DELETE CASCADE,
            enabled    BOOLEAN NOT NULL DEFAULT TRUE,
            PRIMARY KEY (user_id, skill_name)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE feature_flags (
            key         TEXT PRIMARY KEY,
            enabled     BOOLEAN NOT NULL DEFAULT FALSE,
            description TEXT,
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE audit_logs (
            id          BIGSERIAL PRIMARY KEY,
            actor_id    UUID REFERENCES users(id) ON DELETE SET NULL,
            action      TEXT NOT NULL,
            target_type TEXT,
            target_id   TEXT,
            details     JSONB,
            ip          INET,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_audit_time ON audit_logs(created_at DESC)")

    # ─────────────────────────── Seed tối thiểu (T-0.5) ───────────────────
    op.execute(
        """
        INSERT INTO tiers (name, limit_5h_usd, limit_7d_usd, can_execute_skills, is_default)
        VALUES ('free', 0.50, 3.00, FALSE, TRUE),
               ('trusted', 2.00, 12.00, TRUE, FALSE)
        """
    )


def downgrade() -> None:
    for table in (
        "audit_logs",
        "feature_flags",
        "user_skills",
        "skills",
        "shared_conversations",
        "usage_events",
        "artifacts",
        "attachments",
        "messages",
        "conversations",
        "user_settings",
        "user_provider_keys",
        "email_tokens",
        "refresh_tokens",
        "users",
        "tiers",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")

    for enum_type in ("message_status", "message_role", "user_role", "user_status"):
        op.execute(f"DROP TYPE IF EXISTS {enum_type}")

    op.execute('DROP EXTENSION IF EXISTS "citext"')
    op.execute('DROP EXTENSION IF EXISTS "pgcrypto"')
