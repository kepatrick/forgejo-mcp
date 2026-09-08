"""Backfill historical Dashboard revocations without revoking healthy rotations.

Revision ID: 20260908_0012
Revises: 20260908_0011
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260908_0012"
down_revision: str | None = "20260908_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Rotation also revokes MCP access tokens. Only explicit Dashboard audit
    # evidence or revocation of an unrotated member establishes this backfill.
    op.execute("""
        UPDATE oauth_token_families AS family
        SET revoked_at = evidence.revoked_at
        FROM (
            SELECT refresh.family_id, MIN(token.revoked_at) AS revoked_at
            FROM oauth_refresh_tokens AS refresh
            JOIN mcp_tokens AS token ON token.id = refresh.mcp_token_id
            WHERE token.revoked_at IS NOT NULL
              AND (refresh.rotated_at IS NULL OR EXISTS (
                SELECT 1 FROM management_audit_events AS audit
                WHERE audit.action = 'mcp_token.revoked'
                  AND audit.target_type = 'mcp_token'
                  AND audit.target_id = CAST(token.id AS VARCHAR)
              ))
            GROUP BY refresh.family_id
        ) AS evidence
        WHERE family.id = evidence.family_id AND family.revoked_at IS NULL
    """)
    op.execute("""
        UPDATE oauth_refresh_tokens AS refresh
        SET revoked_at = family.revoked_at
        FROM oauth_token_families AS family
        WHERE refresh.family_id = family.id AND family.revoked_at IS NOT NULL
          AND refresh.revoked_at IS NULL
    """)
    op.execute("""
        UPDATE mcp_tokens AS token
        SET enabled = false, revoked_at = COALESCE(token.revoked_at, family.revoked_at)
        FROM oauth_refresh_tokens AS refresh
        JOIN oauth_token_families AS family ON family.id = refresh.family_id
        WHERE token.id = refresh.mcp_token_id AND family.revoked_at IS NOT NULL
    """)
    op.execute("""
        UPDATE oauth_access_tokens AS access
        SET revoked_at = family.revoked_at
        FROM oauth_refresh_tokens AS refresh
        JOIN oauth_token_families AS family ON family.id = refresh.family_id
        WHERE access.refresh_token_id = refresh.id AND family.revoked_at IS NOT NULL
          AND access.revoked_at IS NULL
    """)


def downgrade() -> None:
    # Never resurrect revoked credentials on rollback.
    pass
