"""Add encrypted per-user Forgejo credentials.

Revision ID: 20250802_0005
Revises: 20250729_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20250802_0005"
down_revision: str | None = "20250729_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "forgejo_credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("encrypted_token", sa.LargeBinary(), nullable=True),
        sa.Column("nonce", sa.LargeBinary(), nullable=True),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("forgejo_user_id", sa.BigInteger(), nullable=False),
        sa.Column("forgejo_username", sa.String(length=255), nullable=False),
        sa.Column("normalized_forgejo_username", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('active', 'revoked')", name="ck_forgejo_credentials_status"),
        sa.CheckConstraint(
            "(status = 'active' AND encrypted_token IS NOT NULL AND nonce IS NOT NULL) "
            "OR (status = 'revoked' AND encrypted_token IS NULL AND nonce IS NULL)",
            name="ck_forgejo_credentials_secret_lifecycle",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_forgejo_credentials_user_id", "forgejo_credentials", ["user_id"])
    op.create_index(
        "ix_forgejo_credentials_user_status",
        "forgejo_credentials",
        ["user_id", "status"],
    )
    op.create_index(
        "uq_forgejo_credentials_one_active_per_user",
        "forgejo_credentials",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_table("forgejo_credentials")
