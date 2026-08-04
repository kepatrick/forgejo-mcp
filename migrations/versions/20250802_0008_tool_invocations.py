"""Add immutable MCP tool invocation audit records.

Revision ID: 20250802_0008
Revises: 20250802_0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20250802_0008"
down_revision: str | None = "20250802_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_invocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("mcp_token_id", sa.Uuid(), nullable=True),
        sa.Column("user_display_name", sa.String(length=120), nullable=False),
        sa.Column("token_name", sa.String(length=120), nullable=False),
        sa.Column("forgejo_username", sa.String(length=255), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("tool_version", sa.Integer(), nullable=False),
        sa.Column("risk", sa.String(length=30), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("authorization_allowed", sa.Boolean(), nullable=False),
        sa.Column("denial_reason", sa.String(length=80), nullable=True),
        sa.Column("redacted_arguments", sa.JSON(), nullable=False),
        sa.Column("target", sa.JSON(), nullable=False),
        sa.Column("result_summary", sa.JSON(), nullable=False),
        sa.Column("error_type", sa.String(length=80), nullable=True),
        sa.Column("forgejo_http_status", sa.Integer(), nullable=True),
        sa.Column("input_truncated", sa.Boolean(), nullable=False),
        sa.Column("result_truncated", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed', 'denied')",
            name="ck_tool_invocations_status",
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_tool_invocations_duration",
        ),
        sa.ForeignKeyConstraint(["mcp_token_id"], ["mcp_tokens.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tool_invocations_user_id", "tool_invocations", ["user_id"])
    op.create_index("ix_tool_invocations_mcp_token_id", "tool_invocations", ["mcp_token_id"])
    op.create_index("ix_tool_invocations_tool_name", "tool_invocations", ["tool_name"])
    op.create_index("ix_tool_invocations_started_at", "tool_invocations", ["started_at"])
    op.create_index("ix_tool_invocations_status", "tool_invocations", ["status"])
    op.create_index(
        "ix_tool_invocations_user_started", "tool_invocations", ["user_id", "started_at"]
    )
    op.create_index(
        "ix_tool_invocations_token_started",
        "tool_invocations",
        ["mcp_token_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_table("tool_invocations")
