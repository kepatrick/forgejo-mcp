"""Add opt-in Forgejo OAuth credentials and session-bound PKCE requests.

Revision ID: 20260930_0015
Revises: 20260930_0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260930_0015"
down_revision: str | None = "20260930_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "forgejo_credentials",
        sa.Column("kind", sa.String(20), nullable=False, server_default="pat"),
    )
    for name, type_ in (
        ("encrypted_refresh_token", sa.LargeBinary()),
        ("refresh_nonce", sa.LargeBinary()),
        ("access_expires_at", sa.DateTime(timezone=True)),
        ("oauth_base_url", sa.String(2048)),
        ("oauth_client_id", sa.String(128)),
    ):
        op.add_column("forgejo_credentials", sa.Column(name, type_, nullable=True))
    op.create_table(
        "forgejo_oauth_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("state_hash", sa.String(64), nullable=False),
        sa.Column("browser_token_hash", sa.String(64), nullable=False),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "instance_id",
            sa.Uuid(),
            sa.ForeignKey("forgejo_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("base_url", sa.String(2048), nullable=False),
        sa.Column("client_id", sa.String(128), nullable=False),
        sa.Column("redirect_url", sa.String(2048), nullable=False),
        sa.Column("encrypted_verifier", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_forgejo_oauth_requests_state_hash",
        "forgejo_oauth_requests",
        ["state_hash"],
        unique=True,
    )
    op.create_index(
        "ix_forgejo_oauth_requests_expires_at", "forgejo_oauth_requests", ["expires_at"]
    )


def downgrade() -> None:
    op.drop_table("forgejo_oauth_requests")
    # Never turn expired OAuth credentials into apparently valid PATs on rollback.
    op.execute(
        "UPDATE forgejo_credentials SET status='revoked', encrypted_token=NULL, nonce=NULL, "
        "revoked_at=COALESCE(revoked_at, CURRENT_TIMESTAMP) WHERE kind='oauth'"
    )
    for name in (
        "oauth_client_id",
        "oauth_base_url",
        "access_expires_at",
        "refresh_nonce",
        "encrypted_refresh_token",
        "kind",
    ):
        op.drop_column("forgejo_credentials", name)
