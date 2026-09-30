"""Preserve whether the authorization request explicitly supplied redirect_uri.

Revision ID: 20260929_0013
Revises: 20260908_0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260929_0013"
down_revision: str | None = "20260908_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Legacy rows lack this evidence. Preserve their previous strict behavior
    # rather than guessing that the client omitted redirect_uri.
    for table in ("oauth_authorization_requests", "oauth_authorization_codes"):
        op.add_column(
            table,
            sa.Column(
                "redirect_uri_provided_explicitly",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
        )


def downgrade() -> None:
    for table in ("oauth_authorization_codes", "oauth_authorization_requests"):
        op.drop_column(table, "redirect_uri_provided_explicitly")
