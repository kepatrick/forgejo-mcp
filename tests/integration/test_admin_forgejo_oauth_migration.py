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
    / "migrations/versions/20261001_0016_admin_forgejo_oauth_config.py"
)


async def test_upgrade_preserves_credentials_and_legacy_binding_fails_closed_on_rollback():
    spec = importlib.util.spec_from_file_location("admin_forgejo_oauth_migration", MIGRATION_PATH)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_async_engine(DATABASE_URL)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                schema = "admin_forgejo_oauth_test_" + uuid.uuid4().hex
                await connection.execute(text(f"CREATE SCHEMA {schema}"))
                await connection.execute(text(f"SET LOCAL search_path TO {schema}"))
                await connection.execute(text("CREATE TABLE accounts (id uuid PRIMARY KEY)"))
                await connection.execute(
                    text("CREATE TABLE forgejo_oauth_requests (id integer PRIMARY KEY)")
                )
                await connection.execute(text("INSERT INTO forgejo_oauth_requests VALUES (1)"))
                await connection.execute(
                    text(
                        "CREATE TABLE forgejo_credentials (id integer PRIMARY KEY, "
                        "kind varchar(20), "
                        "status varchar(20), encrypted_token bytea, nonce bytea, "
                        "encrypted_refresh_token bytea, refresh_nonce bytea, "
                        "revoked_at timestamptz)"
                    )
                )
                await connection.execute(
                    text(
                        "INSERT INTO forgejo_credentials VALUES "
                        "(1,'pat','active',decode('01','hex'),decode('02','hex'),NULL,NULL,NULL), "
                        "(2,'oauth','active',decode('03','hex'),decode('04','hex'), "
                        "decode('05','hex'),decode('06','hex'),NULL)"
                    )
                )

                def run(sync_connection, direction):
                    with Operations.context(MigrationContext.configure(sync_connection)):
                        getattr(migration, direction)()

                await connection.run_sync(run, "upgrade")
                assert (
                    await connection.scalar(
                        text("SELECT count(*) FROM forgejo_oauth_configurations")
                    )
                    == 0
                )
                assert (
                    await connection.scalar(
                        text("SELECT config_revision FROM forgejo_oauth_requests WHERE id=1")
                    )
                    == ""
                )
                assert (
                    await connection.scalar(
                        text("SELECT count(*) FROM forgejo_credentials WHERE status='active'")
                    )
                    == 2
                )
                assert (
                    await connection.scalar(
                        text("SELECT encrypted_refresh_token FROM forgejo_credentials WHERE id=2")
                    )
                    == b"\x05"
                )
                await connection.run_sync(run, "downgrade")
                assert (
                    await connection.scalar(text("SELECT count(*) FROM forgejo_oauth_requests"))
                    == 0
                )
                pat = (
                    await connection.execute(
                        text("SELECT status, encrypted_token FROM forgejo_credentials WHERE id=1")
                    )
                ).one()
                assert pat.status == "active" and pat.encrypted_token == b"\x01"
                oauth = (
                    await connection.execute(
                        text(
                            "SELECT status, encrypted_token, nonce, encrypted_refresh_token, "
                            "refresh_nonce, "
                            "revoked_at FROM forgejo_credentials WHERE id=2"
                        )
                    )
                ).one()
                assert oauth.status == "revoked" and oauth.revoked_at is not None
                assert oauth.encrypted_token is None and oauth.nonce is None
                assert oauth.encrypted_refresh_token is None and oauth.refresh_nonce is None
                await connection.run_sync(run, "upgrade")
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
