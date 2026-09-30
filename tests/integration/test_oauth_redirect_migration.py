"""Check legacy defaults and rollback without modifying the shared test schema."""

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
    "migrations/versions/20260929_0013_oauth_redirect_uri_presence.py"
)


async def test_redirect_presence_migration_preserves_legacy_strictness():
    spec = importlib.util.spec_from_file_location("redirect_presence", MIGRATION_PATH)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_async_engine(DATABASE_URL)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                schema = "redirect_test_" + uuid.uuid4().hex
                await connection.execute(text(f"CREATE SCHEMA {schema}"))
                await connection.execute(text(f"SET LOCAL search_path TO {schema}"))
                tables = ("oauth_authorization_requests", "oauth_authorization_codes")
                for table in tables:
                    await connection.execute(text(f"CREATE TABLE {table} (id integer PRIMARY KEY)"))
                    await connection.execute(text(f"INSERT INTO {table} VALUES (1)"))

                def run(sync_connection, direction):
                    with Operations.context(MigrationContext.configure(sync_connection)):
                        getattr(migration, direction)()

                await connection.run_sync(run, "upgrade")
                for table in tables:
                    assert (
                        await connection.scalar(
                            text(f"SELECT redirect_uri_provided_explicitly FROM {table} WHERE id=1")
                        )
                        is True
                    )
                    await connection.execute(
                        text(
                            f"INSERT INTO {table} (id, redirect_uri_provided_explicitly) "
                            "VALUES (2, false)"
                        )
                    )
                    assert (
                        await connection.scalar(
                            text(f"SELECT redirect_uri_provided_explicitly FROM {table} WHERE id=2")
                        )
                        is False
                    )
                await connection.run_sync(run, "downgrade")
                for table in tables:
                    assert await connection.scalar(text(f"SELECT count(*) FROM {table}")) == 2
                await connection.run_sync(run, "upgrade")
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
