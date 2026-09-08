"""Add OAuth 2.1 authorization server records.

Revision ID: 20260902_0009
Revises: 20250802_0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260902_0009"
down_revision: str | None = "20250802_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_tokens",
        sa.Column(
            "kind",
            sa.String(length=20),
            nullable=False,
            server_default="static",
        ),
    )
    op.create_check_constraint(
        "ck_mcp_tokens_kind",
        "mcp_tokens",
        "kind IN ('static', 'oauth')",
    )
    op.create_table(
        "oauth_clients",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("client_id_hash", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.String(length=2048), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("metadata_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.CheckConstraint("source IN ('cimd', 'dcr')", name="ck_oauth_clients_source"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id_hash", name="uq_oauth_clients_client_id_hash"),
    )
    op.create_index("ix_oauth_clients_client_id_hash", "oauth_clients", ["client_id_hash"])
    op.create_index("ix_oauth_clients_source_updated", "oauth_clients", ["source", "updated_at"])

    op.create_table(
        "oauth_authorization_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_token_hash", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("redirect_uri", sa.String(length=2048), nullable=False),
        sa.Column("state", sa.String(length=1024), nullable=True),
        sa.Column("code_challenge", sa.String(length=128), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("resource", sa.String(length=2048), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["client_id"], ["oauth_clients.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_token_hash", name="uq_oauth_authorization_requests_hash"),
    )
    op.create_index(
        "ix_oauth_authorization_requests_request_token_hash",
        "oauth_authorization_requests",
        ["request_token_hash"],
    )
    op.create_index(
        "ix_oauth_authorization_requests_client_id",
        "oauth_authorization_requests",
        ["client_id"],
    )
    op.create_index(
        "ix_oauth_authorization_requests_expires_at",
        "oauth_authorization_requests",
        ["expires_at"],
    )

    op.create_table(
        "oauth_authorization_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("redirect_uri", sa.String(length=2048), nullable=False),
        sa.Column("code_challenge", sa.String(length=128), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("resource", sa.String(length=2048), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["client_id"], ["oauth_clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash", name="uq_oauth_authorization_codes_hash"),
    )
    op.create_index(
        "ix_oauth_authorization_codes_code_hash",
        "oauth_authorization_codes",
        ["code_hash"],
    )
    op.create_index(
        "ix_oauth_authorization_codes_client_id",
        "oauth_authorization_codes",
        ["client_id"],
    )
    op.create_index(
        "ix_oauth_authorization_codes_user_id",
        "oauth_authorization_codes",
        ["user_id"],
    )
    op.create_index(
        "ix_oauth_authorization_codes_expires_at",
        "oauth_authorization_codes",
        ["expires_at"],
    )

    op.create_table(
        "oauth_refresh_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_prefix", sa.String(length=20), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("resource", sa.String(length=2048), nullable=False),
        sa.Column("mcp_token_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["client_id"], ["oauth_clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["mcp_token_id"], ["mcp_tokens.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_oauth_refresh_tokens_hash"),
    )
    op.create_index("ix_oauth_refresh_tokens_token_hash", "oauth_refresh_tokens", ["token_hash"])
    op.create_index("ix_oauth_refresh_tokens_family_id", "oauth_refresh_tokens", ["family_id"])
    op.create_index("ix_oauth_refresh_tokens_client_id", "oauth_refresh_tokens", ["client_id"])
    op.create_index("ix_oauth_refresh_tokens_user_id", "oauth_refresh_tokens", ["user_id"])
    op.create_index(
        "ix_oauth_refresh_tokens_mcp_token_id",
        "oauth_refresh_tokens",
        ["mcp_token_id"],
    )
    op.create_index("ix_oauth_refresh_tokens_expires_at", "oauth_refresh_tokens", ["expires_at"])

    op.create_table(
        "oauth_access_tokens",
        sa.Column("mcp_token_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("refresh_token_id", sa.Uuid(), nullable=False),
        sa.Column("resource", sa.String(length=2048), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["oauth_clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["mcp_token_id"], ["mcp_tokens.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["refresh_token_id"],
            ["oauth_refresh_tokens.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("mcp_token_id"),
        sa.UniqueConstraint("refresh_token_id", name="uq_oauth_access_tokens_refresh_token_id"),
    )
    op.create_index("ix_oauth_access_tokens_client_id", "oauth_access_tokens", ["client_id"])


def downgrade() -> None:
    # OAuth access tokens are stored in mcp_tokens so the existing MCP
    # authorization stack can enforce the same grants. Remove them before
    # dropping their OAuth linkage; otherwise they could become valid static
    # bearer tokens after a rollback.
    op.execute("DELETE FROM mcp_tokens WHERE kind = 'oauth'")
    op.drop_table("oauth_access_tokens")
    op.drop_table("oauth_refresh_tokens")
    op.drop_table("oauth_authorization_codes")
    op.drop_table("oauth_authorization_requests")
    op.drop_table("oauth_clients")
    op.drop_constraint("ck_mcp_tokens_kind", "mcp_tokens", type_="check")
    op.drop_column("mcp_tokens", "kind")
