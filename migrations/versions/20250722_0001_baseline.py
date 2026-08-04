"""Create the initial schema baseline.

Revision ID: 20250722_0001
Revises:
"""

revision: str = "20250722_0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Reserve the baseline; domain tables arrive in the account vertical slice."""


def downgrade() -> None:
    """Remove the baseline marker."""
