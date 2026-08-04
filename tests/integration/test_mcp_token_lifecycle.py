import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from forgejo_mcp.application.errors import NotFound, ValidationFailed
from forgejo_mcp.application.mcp_token_service import McpTokenService
from forgejo_mcp.auth.mcp_bearer import ForgejoMcpTokenVerifier, McpBearerAuthenticator
from forgejo_mcp.auth.passwords import hash_password
from forgejo_mcp.db.models import (
    Account,
    AccountRole,
    ManagementAuditEvent,
    McpToken,
    RecordStatus,
    User,
)

DATABASE_URL = os.getenv("FMCP_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    DATABASE_URL is None, reason="integration PostgreSQL not configured"
)


async def mcp_token_lifecycle() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE mcp_tokens, forgejo_credentials, forgejo_instances, "
                "management_audit_events, user_invitations, sessions, accounts, users "
                "RESTART IDENTITY CASCADE"
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
        other_user = User(
            display_name="Someone Else",
            expected_forgejo_username="someone",
            normalized_forgejo_username="someone",
            status=RecordStatus.ACTIVE,
        )
        other_account = Account(
            user=other_user,
            username="someone",
            normalized_username="someone",
            role=AccountRole.USER,
            password_hash=hash_password("other-password-for-testing"),
            must_change_password=False,
            status=RecordStatus.ACTIVE,
        )
        session.add_all([admin, user, account, other_user, other_account])
        await session.commit()

        service = McpTokenService(session)
        created = await service.create(
            actor_account_id=account.id,
            user_id=user.id,
            name="Claude Desktop",
            description="Local client",
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )
        assert created.token.startswith("fmcp_")
        assert created.token not in created.record.token_hash
        assert created.record.token_prefix != created.token

        listed = await service.list_for_user(user.id)
        assert [record.id for record in listed] == [created.record.id]
        assert all(not hasattr(record, "token") for record in listed)

        authenticated = await McpBearerAuthenticator(session).authenticate(created.token)
        assert authenticated is not None
        assert authenticated.token_id == created.record.id
        assert authenticated.user_id == user.id
        assert created.record.last_used_at is not None
        assert await McpBearerAuthenticator(session).authenticate(f"{created.token}x") is None
        altered = f"{created.token[:-1]}{'A' if created.token[-1] != 'A' else 'B'}"
        assert await McpBearerAuthenticator(session).authenticate(altered) is None

        access_token = await ForgejoMcpTokenVerifier(lambda: factory).verify_token(created.token)
        assert access_token is not None
        assert access_token.token == ""
        assert access_token.client_id == str(created.record.id)
        assert access_token.subject == str(user.id)

        with pytest.raises(NotFound):
            await service.revoke_for_user(
                actor_account_id=other_account.id,
                user_id=other_user.id,
                token_id=created.record.id,
            )

        await service.revoke_as_admin(
            actor_account_id=admin.id,
            token_id=created.record.id,
        )
        assert created.record.enabled is False
        assert created.record.revoked_at is not None
        assert await McpBearerAuthenticator(session).authenticate(created.token) is None

        events = list(
            (
                await session.scalars(
                    select(ManagementAuditEvent).where(
                        ManagementAuditEvent.action.like("mcp_token.%")
                    )
                )
            ).all()
        )
        assert [event.action for event in events] == ["mcp_token.created", "mcp_token.revoked"]
        assert created.token not in repr([event.details for event in events])
        assert await session.scalar(select(McpToken).where(McpToken.id == created.record.id))

        with pytest.raises(ValidationFailed):
            await service.create(
                actor_account_id=account.id,
                user_id=user.id,
                name="Expired",
                description=None,
                expires_at=datetime.now(UTC) - timedelta(seconds=1),
            )

    await engine.dispose()


def test_mcp_token_lifecycle() -> None:
    asyncio.run(mcp_token_lifecycle())
