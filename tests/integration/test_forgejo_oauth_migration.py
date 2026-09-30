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
MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "migrations/versions/20260930_0015_forgejo_oauth_client.py"
)


async def test_upgrade_preserves_pats_and_downgrade_does_not_resurrect_oauth():
    spec = importlib.util.spec_from_file_location("forgejo_oauth_migration", MIGRATION_PATH)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_async_engine(DATABASE_URL)
    try:
        async with engine.connect() as connection:
            tx = await connection.begin()
            try:
                schema = "forgejo_oauth_test_" + uuid.uuid4().hex
                await connection.execute(text(f"CREATE SCHEMA {schema}"))
                await connection.execute(text(f"SET LOCAL search_path TO {schema}"))
                for name in ("sessions", "forgejo_instances"):
                    await connection.execute(text(f"CREATE TABLE {name} (id uuid PRIMARY KEY)"))
                await connection.execute(
                    text(
                        "CREATE TABLE forgejo_credentials (id integer PRIMARY KEY, "
                        "status varchar(20), encrypted_token bytea, nonce bytea, "
                        "revoked_at timestamptz)"
                    )
                )
                await connection.execute(
                    text(
                        "INSERT INTO forgejo_credentials (id, status, encrypted_token, nonce) "
                        "VALUES (1,'active',decode('01','hex'),decode('02','hex'))"
                    )
                )

                def run(sync_connection, direction):
                    with Operations.context(MigrationContext.configure(sync_connection)):
                        getattr(migration, direction)()

                await connection.run_sync(run, "upgrade")
                assert (
                    await connection.scalar(text("SELECT kind FROM forgejo_credentials WHERE id=1"))
                    == "pat"
                )
                await connection.execute(
                    text(
                        "INSERT INTO forgejo_credentials (id, kind, status, "
                        "encrypted_token, nonce) "
                        "VALUES (2,'oauth','active',decode('03','hex'),decode('04','hex'))"
                    )
                )
                await connection.run_sync(run, "downgrade")
                pat = (
                    await connection.execute(
                        text("SELECT status, encrypted_token FROM forgejo_credentials WHERE id=1")
                    )
                ).one()
                assert pat.status == "active" and pat.encrypted_token == b"\x01"
                oauth = (
                    await connection.execute(
                        text(
                            "SELECT status, encrypted_token, nonce, revoked_at "
                            "FROM forgejo_credentials WHERE id=2"
                        )
                    )
                ).one()
                assert (
                    oauth.status == "revoked"
                    and oauth.encrypted_token is None
                    and oauth.nonce is None
                )
                assert oauth.revoked_at is not None
                await connection.run_sync(run, "upgrade")
            finally:
                await tx.rollback()
    finally:
        await engine.dispose()
