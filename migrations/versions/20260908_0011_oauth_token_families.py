"""Serialize OAuth refresh rotation and family revocation.

Revision ID: 20260908_0011
Revises: 20260902_0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260908_0011"
down_revision: str | None = "20260902_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "oauth_token_families",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        """
        INSERT INTO oauth_token_families (id, revoked_at, created_at)
        SELECT
            family_id,
            MIN(revoked_at),
            COALESCE(MIN(created_at), now())
        FROM oauth_refresh_tokens
        GROUP BY family_id
        """
    )

    # Fail closed for a family affected by a revocation/rotation race before
    # this migration: one revoked member makes every descendant unusable.
    op.execute(
        """
        UPDATE oauth_refresh_tokens AS refresh
        SET revoked_at = family.revoked_at
        FROM oauth_token_families AS family
        WHERE refresh.family_id = family.id
          AND family.revoked_at IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE mcp_tokens AS token
        SET enabled = false, revoked_at = family.revoked_at
        FROM oauth_refresh_tokens AS refresh
        JOIN oauth_token_families AS family ON family.id = refresh.family_id
        WHERE token.id = refresh.mcp_token_id
          AND family.revoked_at IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE oauth_access_tokens AS access
        SET revoked_at = family.revoked_at
        FROM oauth_refresh_tokens AS refresh
        JOIN oauth_token_families AS family ON family.id = refresh.family_id
        WHERE access.refresh_token_id = refresh.id
          AND family.revoked_at IS NOT NULL
        """
    )
    op.create_foreign_key(
        "fk_oauth_refresh_tokens_family_id_oauth_token_families",
        "oauth_refresh_tokens",
        "oauth_token_families",
        ["family_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_oauth_refresh_tokens_family_id_oauth_token_families",
        "oauth_refresh_tokens",
        type_="foreignkey",
    )
    op.drop_table("oauth_token_families")
