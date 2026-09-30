"""Add an absolute OAuth grant expiry to authorization codes.

Revision ID: 20260902_0010
Revises: 20260902_0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260902_0010"
down_revision: str | None = "20260902_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable keeps authorization codes created immediately before deployment
    # exchangeable; they receive the configured default lifetime at exchange.
    op.add_column(
        "oauth_authorization_codes",
        sa.Column("refresh_expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("oauth_authorization_codes", "refresh_expires_at")
