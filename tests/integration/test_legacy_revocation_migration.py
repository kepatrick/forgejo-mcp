"""Exercise the data backfill against PostgreSQL in a rolled-back schema."""

import importlib.util
import os
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL = os.getenv("FMCP_TEST_DATABASE_URL")
MIGRATION_PATH = Path(__file__).resolve().parents[2] / (
    "migrations/versions/20260908_0012_legacy_dashboard_revocations.py"
)
pytestmark = pytest.mark.skipif(DATABASE_URL is None, reason="PostgreSQL not configured")


async def test_legacy_revocations_preserve_healthy_rotation() -> None:
    assert DATABASE_URL is not None
    spec = importlib.util.spec_from_file_location("legacy_revocations", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_async_engine(DATABASE_URL)
    try:
        async with engine.connect() as conn:
            transaction = await conn.begin()
            try:
                schema = "backfill_" + uuid.uuid4().hex
                await conn.execute(text(f"CREATE SCHEMA {schema}"))
                await conn.execute(text(f"SET LOCAL search_path TO {schema}"))
                for ddl in (
                    "CREATE TABLE oauth_token_families (id uuid, revoked_at timestamptz)",
                    "CREATE TABLE mcp_tokens (id uuid, enabled bool, revoked_at timestamptz)",
                    "CREATE TABLE oauth_refresh_tokens (id uuid, family_id uuid, "
                    "mcp_token_id uuid, rotated_at timestamptz, revoked_at timestamptz)",
                    "CREATE TABLE oauth_access_tokens (refresh_token_id uuid, "
                    "revoked_at timestamptz)",
                    "CREATE TABLE management_audit_events (action text, target_type text, "
                    "target_id text)",
                ):
                    await conn.execute(text(ddl))
                families = {}
                for scenario in ("healthy_rotation", "dashboard", "unrotated", "partial"):
                    family = uuid.uuid4()
                    families[scenario] = family
                    await conn.execute(
                        text(
                            "INSERT INTO oauth_token_families VALUES (:id, "
                            "CASE WHEN :partial THEN now() ELSE NULL END)"
                        ),
                        {"id": family, "partial": scenario == "partial"},
                    )
                    for old in (True, False):
                        token, refresh = uuid.uuid4(), uuid.uuid4()
                        params = {
                            "token": token,
                            "refresh": refresh,
                            "family": family,
                            "old": old,
                            "rotated": old and scenario != "unrotated",
                        }
                        await conn.execute(
                            text(
                                "INSERT INTO mcp_tokens VALUES (:token, NOT :old, "
                                "CASE WHEN :old THEN now() ELSE NULL END)"
                            ),
                            params,
                        )
                        await conn.execute(
                            text(
                                "INSERT INTO oauth_refresh_tokens VALUES "
                                "(:refresh, :family, :token, CASE WHEN :rotated THEN now() "
                                "ELSE NULL END, NULL)"
                            ),
                            params,
                        )
                        await conn.execute(
                            text("INSERT INTO oauth_access_tokens VALUES (:refresh, NULL)"), params
                        )
                        if old and scenario == "dashboard":
                            await conn.execute(
                                text(
                                    "INSERT INTO management_audit_events VALUES "
                                    "('mcp_token.revoked', 'mcp_token', :id)"
                                ),
                                {"id": str(token)},
                            )

                def run(sync_conn):
                    with Operations.context(MigrationContext.configure(sync_conn)):
                        migration.upgrade()
                        migration.upgrade()  # Idempotent data repair.

                await conn.run_sync(run)
                for scenario, family in families.items():
                    expected = scenario != "healthy_rotation"
                    assert (
                        await conn.scalar(
                            text(
                                "SELECT revoked_at IS NOT NULL FROM oauth_token_families "
                                "WHERE id=:id"
                            ),
                            {"id": family},
                        )
                        is expected
                    )
                    assert (
                        await conn.scalar(
                            text(
                                "SELECT bool_and(revoked_at IS NOT NULL) FROM oauth_refresh_tokens "
                                "WHERE family_id=:id"
                            ),
                            {"id": family},
                        )
                        is expected
                    )
                    assert (
                        await conn.scalar(
                            text(
                                "SELECT bool_and(NOT t.enabled) FROM mcp_tokens t "
                                "JOIN oauth_refresh_tokens r ON t.id=r.mcp_token_id "
                                "WHERE r.family_id=:id"
                            ),
                            {"id": family},
                        )
                        is expected
                    )
                    assert (
                        await conn.scalar(
                            text(
                                "SELECT bool_and(a.revoked_at IS NOT NULL) "
                                "FROM oauth_access_tokens a "
                                "JOIN oauth_refresh_tokens r ON r.id=a.refresh_token_id "
                                "WHERE r.family_id=:id"
                            ),
                            {"id": family},
                        )
                        is expected
                    )
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
