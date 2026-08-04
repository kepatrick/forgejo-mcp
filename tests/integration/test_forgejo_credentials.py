import asyncio
import base64
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from forgejo_mcp.application.forgejo_credential_service import ForgejoCredentialService
from forgejo_mcp.auth.passwords import hash_password
from forgejo_mcp.config import Settings
from forgejo_mcp.db.models import (
    Account,
    AccountRole,
    CredentialStatus,
    ForgejoCredential,
    ForgejoInstance,
    ManagementAuditEvent,
    RecordStatus,
    User,
)
from forgejo_mcp.forgejo.client import ForgejoClient

DATABASE_URL = os.getenv("FMCP_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    DATABASE_URL is None, reason="integration PostgreSQL not configured"
)


async def credential_lifecycle(key_file: Path) -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE forgejo_credentials, forgejo_instances, management_audit_events, "
                "user_invitations, sessions, accounts, users RESTART IDENTITY CASCADE"
            )
        )

    async with factory() as session:
        admin = Account(
            username="admin",
            normalized_username="admin",
            role=AccountRole.ADMIN,
            password_hash=hash_password("admin-password-for-testing"),
            must_change_password=False,
            status=RecordStatus.ACTIVE,
        )
        user = User(
            display_name="Patrick",
            expected_forgejo_username="Patrick",
            normalized_forgejo_username="patrick",
            status=RecordStatus.ACTIVE,
        )
        account = Account(
            user=user,
            username="patrick",
            normalized_username="patrick",
            role=AccountRole.USER,
            password_hash=hash_password("user-password-for-testing"),
            must_change_password=False,
            status=RecordStatus.ACTIVE,
        )
        session.add_all([admin, user, account])
        await session.flush()
        session.add(
            ForgejoInstance(
                slug="primary",
                display_name="Test Forgejo",
                base_url="https://git.example.test",
                verify_tls=True,
                version="16.0.2",
                configured_by_account_id=admin.id,
                last_checked_at=datetime.now(UTC),
            )
        )
        await session.commit()
        user_id = user.id
        account_id = account.id

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] in {
            "token first-secret-pat",
            "token rotated-secret-pat",
        }
        return httpx.Response(200, json={"id": 42, "login": "Patrick"})

    settings = Settings(
        environment="test",
        credential_encryption_key_file=key_file,
        credential_encryption_key_version=1,
    )
    async with factory() as session:
        service = ForgejoCredentialService(session, settings)
        service.client = ForgejoClient(
            connect_timeout_seconds=2,
            transport=httpx.MockTransport(handler),
        )
        first = await service.save(
            actor_account_id=account_id,
            user_id=user_id,
            token="first-secret-pat",
        )
        assert first.encrypted_token is not None
        assert b"first-secret-pat" not in first.encrypted_token
        assert await service.decrypted_token_for_user(user_id) == "first-secret-pat"

        second = await service.save(
            actor_account_id=account_id,
            user_id=user_id,
            token="rotated-secret-pat",
        )
        assert second.id != first.id
        assert first.status == CredentialStatus.REVOKED
        assert first.encrypted_token is None
        assert await service.decrypted_token_for_user(user_id) == "rotated-secret-pat"

        events = list(
            (
                await session.scalars(
                    select(ManagementAuditEvent).where(
                        ManagementAuditEvent.action.like("forgejo_credential.%")
                    )
                )
            ).all()
        )
        assert [event.action for event in events] == [
            "forgejo_credential.created",
            "forgejo_credential.rotated",
        ]
        assert "secret-pat" not in repr([event.details for event in events])

        await service.revoke(
            actor_account_id=account_id,
            user_id=user_id,
            forced_by_admin=False,
        )
        active = await session.scalar(
            select(ForgejoCredential).where(
                ForgejoCredential.user_id == user_id,
                ForgejoCredential.status == CredentialStatus.ACTIVE,
            )
        )
        assert active is None

    await engine.dispose()


def test_encrypted_credential_lifecycle(tmp_path: Path) -> None:
    key_file = tmp_path / "credential_key"
    key_file.write_bytes(base64.b64encode(b"k" * 32))

    asyncio.run(credential_lifecycle(key_file))
