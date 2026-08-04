import asyncio
import os
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from forgejo_mcp.auth.passwords import hash_password
from forgejo_mcp.config import Settings
from forgejo_mcp.db.models import (
    Account,
    AccountRole,
    InvocationStatus,
    McpToken,
    RecordStatus,
    ToolInvocation,
    User,
)
from forgejo_mcp.main import create_app

DATABASE_URL = os.getenv("FMCP_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    DATABASE_URL is None, reason="integration PostgreSQL not configured"
)


async def prepare_audit_records() -> tuple[str, str]:
    assert DATABASE_URL is not None
    engine = create_async_engine(DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE tool_invocations, mcp_tokens, management_audit_events, "
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
        users: list[User] = []
        accounts: list[Account] = []
        for index in (1, 2):
            user = User(
                display_name=f"User {index}",
                expected_forgejo_username=f"forgejo-user-{index}",
                normalized_forgejo_username=f"forgejo-user-{index}",
                status=RecordStatus.ACTIVE,
            )
            account = Account(
                user=user,
                username=f"user-{index}",
                normalized_username=f"user-{index}",
                role=AccountRole.USER,
                password_hash=hash_password(f"user-{index}-password-for-testing"),
                must_change_password=False,
                status=RecordStatus.ACTIVE,
            )
            users.append(user)
            accounts.append(account)
        session.add_all([admin, *users, *accounts])
        await session.flush()
        invocation_ids: list[str] = []
        now = datetime.now(UTC)
        for index, user in enumerate(users, start=1):
            token = McpToken(
                user_id=user.id,
                name=f"Token {index}",
                token_prefix=f"fmcp_prefix{index}",
                token_hash=f"{index:064d}",
                enabled=True,
            )
            session.add(token)
            await session.flush()
            invocation = ToolInvocation(
                user_id=user.id,
                mcp_token_id=token.id,
                user_display_name=user.display_name,
                token_name=token.name,
                forgejo_username=user.expected_forgejo_username,
                tool_name="forgejo_get_current_user",
                tool_version=1,
                risk="read",
                started_at=now,
                completed_at=now,
                duration_ms=1,
                status=InvocationStatus.SUCCEEDED,
                authorization_allowed=True,
                redacted_arguments={},
                target={},
                result_summary={"response_bytes": 20},
                input_truncated=False,
                result_truncated=False,
            )
            session.add(invocation)
            await session.flush()
            invocation_ids.append(str(invocation.id))
        await session.commit()
    await engine.dispose()
    return invocation_ids[0], invocation_ids[1]


def test_audit_api_enforces_self_and_admin_boundaries() -> None:
    assert DATABASE_URL is not None
    own_id, other_id = asyncio.run(prepare_audit_records())
    app = create_app(Settings(environment="test", database_url=DATABASE_URL, cookie_secure=False))

    with TestClient(app) as client:
        assert (
            client.post(
                "/api/auth/login",
                json={"username": "user-1", "password": "user-1-password-for-testing"},
            ).status_code
            == 200
        )
        own_records = client.get("/api/me/audit/tool-invocations")
        assert own_records.status_code == 200
        assert [record["id"] for record in own_records.json()["items"]] == [own_id]
        assert client.get(f"/api/me/audit/tool-invocations/{other_id}").status_code == 404
        assert client.get("/api/audit/tool-invocations").status_code == 403

        assert (
            client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "admin-password-for-testing"},
            ).status_code
            == 200
        )
        all_records = client.get("/api/audit/tool-invocations")
        assert all_records.status_code == 200
        assert {record["id"] for record in all_records.json()["items"]} == {own_id, other_id}

        invalid_range = client.get(
            "/api/audit/tool-invocations",
            params={
                "started_after": "2026-08-03T01:00:00Z",
                "started_before": "2026-08-03T00:00:00Z",
            },
        )
        assert invalid_range.status_code == 422
        assert invalid_range.json()["detail"] == (
            "started_after must not be later than started_before"
        )
