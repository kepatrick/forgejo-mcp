import asyncio
import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from forgejo_mcp.application.errors import ValidationFailed
from forgejo_mcp.application.mcp_token_service import McpTokenService
from forgejo_mcp.application.tool_permission_service import ToolPermissionService
from forgejo_mcp.auth.passwords import hash_password
from forgejo_mcp.db.models import (
    Account,
    AccountRole,
    CredentialStatus,
    ForgejoCredential,
    ManagementAuditEvent,
    RecordStatus,
    User,
)

DATABASE_URL = os.getenv("FMCP_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    DATABASE_URL is None, reason="integration PostgreSQL not configured"
)

TOOL_NAME = "forgejo_get_current_user"


async def tool_permission_lifecycle() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE mcp_token_tool_grants, user_tool_allowances, tool_settings, "
                "mcp_tokens, forgejo_credentials, forgejo_instances, management_audit_events, "
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
        now = datetime.now(UTC)
        credential = ForgejoCredential(
            user=user,
            encrypted_token=b"encrypted-test-token",
            nonce=b"test-nonce12",
            key_version=1,
            status=CredentialStatus.ACTIVE,
            forgejo_user_id=42,
            forgejo_username="Patrick",
            normalized_forgejo_username="patrick",
            verified_at=now,
            activated_at=now,
        )
        session.add_all([admin, user, account, credential])
        await session.commit()

        created = await McpTokenService(session).create(
            actor_account_id=account.id,
            user_id=user.id,
            name="Test client",
            description=None,
            expires_at=None,
        )
        service = ToolPermissionService(session)
        assert (await service.decision(token_id=created.record.id, tool_name=TOOL_NAME)).reason == (
            "tool_globally_disabled"
        )

        await service.set_global_enabled(
            actor_account_id=admin.id,
            tool_name=TOOL_NAME,
            enabled=True,
        )
        await service.replace_user_allowances(
            actor_account_id=admin.id,
            user_id=user.id,
            tool_names={TOOL_NAME},
        )
        await service.replace_token_grants(
            actor_account_id=account.id,
            user_id=user.id,
            token_id=created.record.id,
            tool_names={TOOL_NAME},
        )
        assert (await service.decision(token_id=created.record.id, tool_name=TOOL_NAME)).allowed

        with pytest.raises(ValidationFailed, match="unknown tools"):
            await service.replace_token_grants(
                actor_account_id=account.id,
                user_id=user.id,
                token_id=created.record.id,
                tool_names={"forgejo_unknown"},
            )

        await service.replace_user_allowances(
            actor_account_id=admin.id,
            user_id=user.id,
            tool_names=set(),
        )
        decision = await service.decision(token_id=created.record.id, tool_name=TOOL_NAME)
        assert decision.allowed is False
        assert decision.reason == "tool_not_allowed_for_user"
        assert await service.grants_for_token(user_id=user.id, token_id=created.record.id) == set()

        actions = list(
            (
                await session.scalars(
                    select(ManagementAuditEvent.action).where(
                        ManagementAuditEvent.action.like("tool.%")
                    )
                )
            ).all()
        )
        assert actions == [
            "tool.global_setting_updated",
            "tool.user_allowances_updated",
            "tool.token_grants_updated",
            "tool.user_allowances_updated",
        ]

    await engine.dispose()


def test_tool_permission_lifecycle() -> None:
    asyncio.run(tool_permission_lifecycle())
