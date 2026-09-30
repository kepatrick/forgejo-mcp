"""Verify fail-closed legacy selections and reversible schema changes in isolation."""

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
pytestmark = pytest.mark.skipif(DATABASE_URL is None, reason="PostgreSQL not configured")
MIGRATION_PATH = Path(__file__).resolve().parents[2] / (
    "migrations/versions/20260930_0014_oauth_selected_tools.py"
)


async def test_tool_selection_migration_defaults_legacy_codes_to_no_grants():
    spec = importlib.util.spec_from_file_location("oauth_selected_tools", MIGRATION_PATH)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_async_engine(DATABASE_URL)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                schema = "selection_test_" + uuid.uuid4().hex
                await connection.execute(text(f"CREATE SCHEMA {schema}"))
                await connection.execute(text(f"SET LOCAL search_path TO {schema}"))
                await connection.execute(
                    text(
                        "CREATE TABLE oauth_authorization_codes (id integer PRIMARY KEY)",
                    )
                )
                await connection.execute(text("INSERT INTO oauth_authorization_codes VALUES (1)"))

                def run(sync_connection, direction):
                    with Operations.context(MigrationContext.configure(sync_connection)):
                        getattr(migration, direction)()

                await connection.run_sync(run, "upgrade")
                assert (
                    await connection.scalar(
                        text(
                            "SELECT tool_names FROM oauth_authorization_codes WHERE id=1",
                        )
                    )
                    == []
                )
                await connection.execute(
                    text(
                        "INSERT INTO oauth_authorization_codes (id, tool_names) "
                        "VALUES (2, '[\"forgejo_get_repository\"]')",
                    )
                )
                assert await connection.scalar(
                    text(
                        "SELECT tool_names FROM oauth_authorization_codes WHERE id=2",
                    )
                ) == ["forgejo_get_repository"]
                await connection.run_sync(run, "downgrade")
                assert (
                    await connection.scalar(
                        text(
                            "SELECT count(*) FROM oauth_authorization_codes",
                        )
                    )
                    == 2
                )
                await connection.run_sync(run, "upgrade")
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
