"""Add encrypted, admin-managed Forgejo OAuth settings and bind pending flows.

Revision ID: 20261001_0016
Revises: 20260930_0015
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261001_0016"
down_revision: str | None = "20260930_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "forgejo_oauth_configurations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("slug", sa.String(32), nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("client_id", sa.String(128), nullable=False),
        sa.Column("client_type", sa.String(20), nullable=False),
        sa.Column("base_url", sa.String(2048), nullable=False),
        sa.Column("encrypted_secret", sa.LargeBinary()),
        sa.Column("nonce", sa.LargeBinary()),
        sa.Column("key_version", sa.Integer()),
        sa.Column("revision", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_by_account_id",
            sa.Uuid(),
            sa.ForeignKey("accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    # Legacy pending attempts lack a configuration binding: restart authorization.
    op.add_column(
        "forgejo_oauth_requests",
        sa.Column("config_revision", sa.String(64), nullable=False, server_default=""),
    )


def downgrade() -> None:
    # Do not resurrect stored OAuth grants through deployment fallback after rollback.
    op.execute(
        "UPDATE forgejo_credentials SET status='revoked', encrypted_token=NULL, nonce=NULL, "
        "encrypted_refresh_token=NULL, refresh_nonce=NULL, "
        "revoked_at=COALESCE(revoked_at, CURRENT_TIMESTAMP) WHERE kind='oauth'"
    )
    op.execute("DELETE FROM forgejo_oauth_requests")
    op.drop_column("forgejo_oauth_requests", "config_revision")
    op.drop_table("forgejo_oauth_configurations")
