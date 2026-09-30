"""Persist tools explicitly selected at OAuth consent.

Revision ID: 20260930_0014
Revises: 20260929_0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260930_0014"
down_revision: str | None = "20260929_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Pending legacy codes have no evidence of an explicit tool selection.
    # Keep their selection empty: code exchange fails closed and clients must
    # restart consent. Existing refresh tokens retain their stored token grants.
    op.add_column(
        "oauth_authorization_codes",
        sa.Column("tool_names", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )


def downgrade() -> None:
    op.drop_column("oauth_authorization_codes", "tool_names")
