"""Persist revoked access-token identifiers until they expire.

Revision ID: 20260817_0004
Revises: 20260625_0003
Create Date: 2026-08-17
"""

from alembic import op
import sqlalchemy as sa


revision = "20260817_0004"
down_revision = "20260625_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "revoked_access_tokens",
        sa.Column("jti", sa.Text(), primary_key=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "idx_revoked_access_tokens_expires_at",
        "revoked_access_tokens",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_revoked_access_tokens_expires_at",
        table_name="revoked_access_tokens",
    )
    op.drop_table("revoked_access_tokens")
