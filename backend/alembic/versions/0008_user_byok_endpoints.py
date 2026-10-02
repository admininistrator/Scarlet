"""user_byok_endpoints — endpoint BYOK do người dùng tự nhập (NQ-134 ②)

KH tham chiếu: §10.5, §12.2, C43 · tasks.md T-S.19b · NQ-134.

Cùng khuôn `user_provider_keys` (0001): khoá mã hoá AES-256-GCM, nonce riêng
mỗi hàng, `ON DELETE CASCADE` theo user (§10.5 "xoá cứng"). Khác ở chỗ khoá
tra cứu là `label` người dùng đặt, và hàng mang luôn `base_url` + danh sách
model.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE user_byok_endpoints (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            label        TEXT NOT NULL,
            base_url     TEXT NOT NULL,
            key_cipher   BYTEA NOT NULL,
            key_nonce    BYTEA NOT NULL,
            key_last4    TEXT NOT NULL,
            models       TEXT[] NOT NULL DEFAULT '{}',
            verified_at  TIMESTAMPTZ,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (user_id, label)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_byok_endpoints")
