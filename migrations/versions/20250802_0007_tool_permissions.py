"""Add registry-backed layered tool permissions.

Revision ID: 20250802_0007
Revises: 20250802_0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20250802_0007"
down_revision: str | None = "20250802_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_settings",
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("registry_version", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("tool_name"),
    )
    op.create_table(
        "user_tool_allowances",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(["tool_name"], ["tool_settings.tool_name"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "tool_name"),
    )
    op.create_table(
        "mcp_token_tool_grants",
        sa.Column("mcp_token_id", sa.Uuid(), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["mcp_token_id"], ["mcp_tokens.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tool_name"], ["tool_settings.tool_name"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("mcp_token_id", "tool_name"),
    )


def downgrade() -> None:
    op.drop_table("mcp_token_tool_grants")
    op.drop_table("user_tool_allowances")
    op.drop_table("tool_settings")
