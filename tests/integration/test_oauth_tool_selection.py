import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_oauth_flow import (
    DATABASE_URL,
    ISSUER,
    READ_TOOLS,
    RESOURCE,
    WRITE_TOOLS,
    approve_authorization,
    authorization_grant_expiry,
    exchange_code,
    issued_token_expiries,
    oauth_settings,
    prepare_oauth_database,
    register_client,
    start_authorization,
)

from forgejo_mcp.auth.tokens import hash_token
from forgejo_mcp.db.models import McpToken, McpTokenToolGrant, OAuthAuthorizationCode, ToolSetting
from forgejo_mcp.main import create_app

pytestmark = pytest.mark.skipif(DATABASE_URL is None, reason="PostgreSQL not configured")


async def stored_grants(access_token):
    engine = create_async_engine(DATABASE_URL)
    try:
        async with async_sessionmaker(engine)() as session:
            return set(
                await session.scalars(
                    select(McpTokenToolGrant.tool_name)
                    .join(McpToken)
                    .where(
                        McpToken.token_hash == hash_token(access_token),
                    ),
                )
            )
    finally:
        await engine.dispose()


async def change_permissions(*, enable=None, disable=None, remove_grant=None):
    engine = create_async_engine(DATABASE_URL)
    try:
        async with async_sessionmaker(engine)() as session:
            if enable:
                await session.execute(
                    update(ToolSetting)
                    .where(
                        ToolSetting.tool_name == enable,
                    )
                    .values(enabled=True)
                )
            if disable:
                await session.execute(
                    update(ToolSetting)
                    .where(
                        ToolSetting.tool_name == disable,
                    )
                    .values(enabled=False)
                )
            if remove_grant:
                await session.execute(
                    delete(McpTokenToolGrant).where(
                        McpTokenToolGrant.tool_name == remove_grant,
                    )
                )
            await session.commit()
    finally:
        await engine.dispose()


def refresh(client, cid, tokens):
    return client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "client_id": cid,
            "refresh_token": tokens["refresh_token"],
            "scope": "mcp:tools",
            "resource": RESOURCE,
        },
    )


@pytest.mark.parametrize("selection", [[], ["not_a_tool"], [WRITE_TOOLS[0]], [WRITE_TOOLS[1]]])
def test_empty_forged_or_unavailable_selection_can_be_corrected(selection):
    asyncio.run(prepare_oauth_database())
    with TestClient(create_app(oauth_settings()), base_url=ISSUER) as client:
        cid = register_client(client)
        interaction = start_authorization(client, cid, "v" * 64)
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
        page = client.get("/oauth/consent", params={"request": interaction})
        assert page.status_code == 200
        for name in READ_TOOLS:
            assert f"name='tool_names' value='{name}'" in page.text
        for name in WRITE_TOOLS:
            assert f"name='tool_names' value='{name}'" not in page.text
        assert "checked" not in page.text
        rejected = client.post(
            "/oauth/consent",
            headers={"Origin": ISSUER},
            data={
                "request": interaction,
                "action": "approve",
                "csrf": client.cookies.get("fmcp_csrf"),
                "grant_ttl_days": "7",
                "tool_names": selection,
            },
            follow_redirects=False,
        )
        assert rejected.status_code == 400
        assert "No access has been granted" in rejected.text
        assert "Return to authorization settings" in rejected.text
        # Rejection must not consume the interaction: select valid tools on the same request.
        selected = sorted(READ_TOOLS)[:1]
        code = approve_authorization(client, interaction, login=False, tool_names=selected)
        tokens = exchange_code(client, cid, "v" * 64, code)
        assert asyncio.run(stored_grants(tokens["access_token"])) == set(selected)


def test_selection_and_expiry_survive_refresh_without_permission_expansion():
    asyncio.run(prepare_oauth_database())
    selected = sorted(READ_TOOLS)[:2]
    with TestClient(create_app(oauth_settings()), base_url=ISSUER) as client:
        cid = register_client(client)
        interaction = start_authorization(client, cid, "v" * 64)
        code = approve_authorization(
            client,
            interaction,
            login=True,
            grant_ttl_days=7,
            tool_names=selected,
        )
        expiry = asyncio.run(authorization_grant_expiry(code))
        assert timedelta(days=6, hours=23) < expiry - datetime.now(UTC) <= timedelta(days=7)
        tokens = exchange_code(client, cid, "v" * 64, code)
        assert asyncio.run(stored_grants(tokens["access_token"])) == set(selected)
        # A previously globally disabled tool is now available to the user.
        asyncio.run(change_permissions(enable=WRITE_TOOLS[1]))
        rotated = refresh(client, cid, tokens)
        assert rotated.status_code == 200
        tokens = rotated.json()
        assert asyncio.run(stored_grants(tokens["access_token"])) == set(selected)
        _, refresh_expiry = asyncio.run(
            issued_token_expiries(
                tokens["access_token"],
                tokens["refresh_token"],
            )
        )
        assert refresh_expiry == expiry
        # Global removal shrinks the next token, and re-enabling does not restore it.
        asyncio.run(change_permissions(disable=selected[0]))
        rotated = refresh(client, cid, tokens)
        assert rotated.status_code == 200
        tokens = rotated.json()
        assert asyncio.run(stored_grants(tokens["access_token"])) == {selected[1]}
        asyncio.run(change_permissions(enable=selected[0]))
        rotated = refresh(client, cid, tokens)
        assert rotated.status_code == 200
        tokens = rotated.json()
        assert asyncio.run(stored_grants(tokens["access_token"])) == {selected[1]}
        # Dashboard token-grant tightening must also survive rotation.
        asyncio.run(change_permissions(remove_grant=selected[1]))
        assert refresh(client, cid, tokens).status_code == 400


def test_permission_change_between_consent_and_exchange_cannot_expand_grants():
    asyncio.run(prepare_oauth_database())
    selected = sorted(READ_TOOLS)[:2]
    with TestClient(create_app(oauth_settings()), base_url=ISSUER) as client:
        cid = register_client(client)
        interaction = start_authorization(client, cid, "v" * 64)
        code = approve_authorization(client, interaction, login=True, tool_names=selected)
        asyncio.run(change_permissions(disable=selected[0], enable=WRITE_TOOLS[1]))
        tokens = exchange_code(client, cid, "v" * 64, code)
        assert asyncio.run(stored_grants(tokens["access_token"])) == {selected[1]}


def test_legacy_code_without_explicit_selection_fails_closed():
    asyncio.run(prepare_oauth_database())
    with TestClient(create_app(oauth_settings()), base_url=ISSUER) as client:
        cid = register_client(client)
        interaction = start_authorization(client, cid, "v" * 64)
        code = approve_authorization(client, interaction, login=True)

        async def clear_legacy_selection():
            engine = create_async_engine(DATABASE_URL)
            try:
                async with async_sessionmaker(engine)() as session:
                    await session.execute(
                        update(OAuthAuthorizationCode)
                        .where(
                            OAuthAuthorizationCode.code_hash == hash_token(code),
                        )
                        .values(tool_names=[])
                    )
                    await session.commit()
            finally:
                await engine.dispose()

        asyncio.run(clear_legacy_selection())
        response = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": cid,
                "code": code,
                "redirect_uri": "https://client.example.test/oauth/callback",
                "code_verifier": "v" * 64,
                "resource": RESOURCE,
            },
        )
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_grant"
