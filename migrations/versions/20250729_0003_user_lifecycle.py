"""Add pending users and invitation revocation.

Revision ID: 20250729_0003
Revises: 20250722_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20250729_0003"
down_revision: str | None = "20250722_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("normalized_forgejo_username", sa.String(255)))
    op.execute(
        "UPDATE users SET normalized_forgejo_username = lower(trim(expected_forgejo_username))"
    )
    op.alter_column("users", "normalized_forgejo_username", nullable=False)
    op.drop_constraint("users_expected_forgejo_username_key", "users", type_="unique")
    op.create_unique_constraint(
        "uq_users_normalized_forgejo_username", "users", ["normalized_forgejo_username"]
    )
    op.drop_constraint("ck_users_status", "users", type_="check")
    op.create_check_constraint(
        "ck_users_status", "users", "status IN ('pending', 'active', 'disabled')"
    )
    op.drop_constraint("ck_accounts_status", "accounts", type_="check")
    op.create_check_constraint(
        "ck_accounts_status", "accounts", "status IN ('pending', 'active', 'disabled')"
    )
    op.add_column(
        "user_invitations", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("user_invitations", "revoked_at")
    op.execute("UPDATE accounts SET status = 'disabled' WHERE status = 'pending'")
    op.execute("UPDATE users SET status = 'disabled' WHERE status = 'pending'")
    op.drop_constraint("ck_accounts_status", "accounts", type_="check")
    op.create_check_constraint("ck_accounts_status", "accounts", "status IN ('active', 'disabled')")
    op.drop_constraint("ck_users_status", "users", type_="check")
    op.create_check_constraint("ck_users_status", "users", "status IN ('active', 'disabled')")
    op.drop_constraint("uq_users_normalized_forgejo_username", "users", type_="unique")
    op.create_unique_constraint(
        "users_expected_forgejo_username_key", "users", ["expected_forgejo_username"]
    )
    op.drop_column("users", "normalized_forgejo_username")
