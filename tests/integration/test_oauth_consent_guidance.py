import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_oauth_flow import (
    DATABASE_URL,
    ISSUER,
    oauth_settings,
    prepare_oauth_database,
    register_client,
    start_authorization,
)

from forgejo_mcp.db.models import (
    ForgejoCredential,
    OAuthAuthorizationRequest,
    ToolSetting,
)
from forgejo_mcp.main import create_app

pytestmark = pytest.mark.skipif(DATABASE_URL is None, reason="PostgreSQL not configured")


async def change_readiness(scenario):
    engine = create_async_engine(DATABASE_URL)
    try:
        async with async_sessionmaker(engine)() as session:
            if scenario == "credential":
                await session.execute(
                    update(ForgejoCredential).values(revoked_at=datetime.now(UTC))
                )
            elif scenario == "tools":
                await session.execute(update(ToolSetting).values(enabled=False))
            elif scenario == "expired":
                await session.execute(
                    update(OAuthAuthorizationRequest).values(
                        expires_at=datetime.now(UTC) - timedelta(seconds=1),
                    )
                )
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    "scenario, expected",
    [
        ("credential", "Set up your Forgejo credential"),
        ("tools", "Tool access is required"),
        ("expired", "Authorization request unavailable"),
    ],
)
def test_get_guidance_and_stale_consent_post_both_fail_closed(scenario, expected):
    asyncio.run(prepare_oauth_database())
    with TestClient(create_app(oauth_settings()), base_url=ISSUER) as client:
        cid = register_client(client)
        interaction = start_authorization(client, cid, "v" * 64)
        login = client.post(
            "/api/auth/login",
            json={
                "username": "oauth-user",
                "password": "user-password-for-testing",
            },
        )
        assert login.status_code == 200
        ready = client.get("/oauth/consent", params={"request": interaction})
        assert ready.status_code == 200 and "value='approve'" in ready.text
        asyncio.run(change_readiness(scenario))
        page = client.get("/oauth/consent", params={"request": interaction})
        assert page.status_code in {400, 403}
        assert expected in page.text
        assert "value='approve'" not in page.text
        assert "Return to the Dashboard" in page.text
        rejected = client.post(
            "/oauth/consent",
            headers={"Origin": ISSUER},
            data={
                "request": interaction,
                "csrf": client.cookies.get("fmcp_csrf"),
                "action": "approve",
                "grant_ttl_days": "30",
            },
            follow_redirects=False,
        )
        assert rejected.status_code == 400
        assert expected in rejected.text
        assert "location" not in rejected.headers


def test_admin_guidance_and_denial_without_credential():
    asyncio.run(prepare_oauth_database())
    with TestClient(create_app(oauth_settings()), base_url=ISSUER) as client:
        cid = register_client(client)
        interaction = start_authorization(client, cid, "v" * 64)
        assert (
            client.post(
                "/api/auth/login",
                json={
                    "username": "admin",
                    "password": "admin-password-for-testing",
                },
            ).status_code
            == 200
        )
        page = client.get("/oauth/consent", params={"request": interaction})
        assert page.status_code == 403
        assert "Administrator accounts cannot authorize MCP access" in page.text
        assert (
            client.post(
                "/api/auth/login",
                json={
                    "username": "oauth-user",
                    "password": "user-password-for-testing",
                },
            ).status_code
            == 200
        )
        asyncio.run(change_readiness("credential"))
        # Missing setup must not prevent an authenticated user from denying.
        denied = client.post(
            "/oauth/consent",
            headers={"Origin": ISSUER},
            data={
                "request": interaction,
                "csrf": client.cookies.get("fmcp_csrf"),
                "action": "deny",
            },
            follow_redirects=False,
        )
        assert denied.status_code == 302
        assert "error=access_denied" in denied.headers["location"]
