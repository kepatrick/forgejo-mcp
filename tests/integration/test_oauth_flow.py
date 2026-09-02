import asyncio
import base64
import hashlib
import json
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from mcp.server.auth.provider import TokenError
from mcp.shared.auth import OAuthToken
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from forgejo_mcp.application.oauth_service import OAuthService
from forgejo_mcp.application.tool_permission_service import ToolPermissionService
from forgejo_mcp.auth.passwords import hash_password
from forgejo_mcp.auth.tokens import hash_token
from forgejo_mcp.config import Settings
from forgejo_mcp.db.models import (
    Account,
    AccountRole,
    CredentialStatus,
    ForgejoCredential,
    ManagementAuditEvent,
    McpToken,
    OAuthAuthorizationCode,
    OAuthRefreshToken,
    RecordStatus,
    User,
)
from forgejo_mcp.main import create_app
from forgejo_mcp.tools import list_tools

DATABASE_URL = os.getenv("FMCP_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    DATABASE_URL is None, reason="integration PostgreSQL not configured"
)

ISSUER = "https://mcp.example.test"
RESOURCE = f"{ISSUER}/mcp"
REDIRECT_URI = "https://client.example.test/oauth/callback"
MCP_PROTOCOL_VERSION = "2025-06-18"
READ_TOOLS = {spec.name for spec in list_tools() if spec.risk == "read"}
WRITE_TOOLS = sorted(spec.name for spec in list_tools() if spec.risk == "write")


def oauth_settings() -> Settings:
    assert DATABASE_URL is not None
    return Settings(
        environment="test",
        database_url=DATABASE_URL,
        oauth_enabled=True,
        oauth_issuer_url=ISSUER,
        oauth_resource_url=RESOURCE,
        oauth_cimd_allowed_origins=["https://claude.ai"],
        cookie_secure=True,
    )


async def prepare_oauth_database() -> None:
    assert DATABASE_URL is not None
    assert len(READ_TOOLS) == 18
    assert len(WRITE_TOOLS) >= 2
    engine = create_async_engine(DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE oauth_access_tokens, oauth_refresh_tokens, "
                "oauth_authorization_codes, oauth_authorization_requests, oauth_clients, "
                "mcp_token_tool_grants, user_tool_allowances, tool_settings, mcp_tokens, "
                "forgejo_credentials, forgejo_instances, management_audit_events, "
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
            display_name="OAuth User",
            expected_forgejo_username="OAuthUser",
            normalized_forgejo_username="oauthuser",
            status=RecordStatus.ACTIVE,
        )
        account = Account(
            user=user,
            username="oauth-user",
            normalized_username="oauth-user",
            role=AccountRole.USER,
            password_hash=hash_password("user-password-for-testing"),
            must_change_password=False,
            status=RecordStatus.ACTIVE,
        )
        session.add_all([admin, user, account])
        await session.flush()
        now = datetime.now(UTC)
        session.add(
            ForgejoCredential(
                user_id=user.id,
                encrypted_token=b"encrypted-test-token",
                nonce=b"test-nonce12",
                key_version=1,
                status=CredentialStatus.ACTIVE,
                forgejo_user_id=42,
                forgejo_username="OAuthUser",
                normalized_forgejo_username="oauthuser",
                verified_at=now,
                activated_at=now,
            )
        )
        await session.commit()

        permissions = ToolPermissionService(session)
        # The two deliberately mismatched write tools prove that OAuth grants
        # exactly the intersection, never the union, of both permission layers.
        for tool_name in READ_TOOLS | {WRITE_TOOLS[0]}:
            await permissions.set_global_enabled(
                actor_account_id=admin.id,
                tool_name=tool_name,
                enabled=True,
            )
        await permissions.replace_user_allowances(
            actor_account_id=admin.id,
            user_id=user.id,
            tool_names=READ_TOOLS | {WRITE_TOOLS[1]},
        )
    await engine.dispose()


def register_client(client: TestClient) -> str:
    confidential = client.post(
        "/register",
        json={
            "redirect_uris": [REDIRECT_URI],
            "token_endpoint_auth_method": "client_secret_post",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        },
    )
    assert confidential.status_code == 400
    assert confidential.json()["error"] == "invalid_client_metadata"

    unsupported_grant = client.post(
        "/register",
        json={
            "redirect_uris": [REDIRECT_URI],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token", "client_credentials"],
            "response_types": ["code"],
        },
    )
    assert unsupported_grant.status_code == 400
    assert unsupported_grant.json()["error"] == "invalid_client_metadata"

    response = client.post(
        "/register",
        json={
            "client_name": "OAuth integration client",
            "redirect_uris": [REDIRECT_URI],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        },
    )
    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload.get("client_secret") is None
    assert payload["token_endpoint_auth_method"] == "none"
    return str(payload["client_id"])


def start_authorization(
    client: TestClient,
    client_id: str,
    verifier: str,
    *,
    include_resource: bool = True,
) -> str:
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode()
    challenge = challenge.rstrip("=")
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "state-bound-to-client",
        "scope": "mcp:tools",
    }
    if include_resource:
        params["resource"] = RESOURCE
    response = client.get(
        "/authorize",
        params=params,
        follow_redirects=False,
    )
    assert response.status_code == 302
    location = urlsplit(response.headers["location"])
    assert f"{location.scheme}://{location.netloc}" == ISSUER
    assert location.path == "/oauth/consent"
    interaction = parse_qs(location.query)["request"][0]
    assert interaction.startswith("fmcp_oi_")
    return interaction


def approve_authorization(
    client: TestClient,
    interaction: str,
    *,
    login: bool,
    grant_ttl_days: int = 30,
) -> str:
    response = client.get("/oauth/consent", params={"request": interaction})
    assert response.status_code == 200
    if login:
        oauth_csrf = client.cookies.get("fmcp_oauth_csrf")
        assert oauth_csrf is not None
        rejected_origin = client.post(
            "/oauth/login",
            headers={"Origin": "https://attacker.example"},
            data={
                "request": interaction,
                "username": "oauth-user",
                "password": "user-password-for-testing",
                "csrf": oauth_csrf,
            },
            follow_redirects=False,
        )
        assert rejected_origin.status_code == 403
        response = client.post(
            "/oauth/login",
            headers={"Origin": ISSUER},
            data={
                "request": interaction,
                "username": "oauth-user",
                "password": "user-password-for-testing",
                "csrf": oauth_csrf,
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        response = client.get("/oauth/consent", params={"request": interaction})
        assert response.status_code == 200
    csrf = client.cookies.get("fmcp_csrf")
    assert csrf is not None
    assert "OAuth cannot add permissions" in response.text
    assert "name='grant_ttl_days'" in response.text
    assert "value='1'" in response.text
    assert "value='7'" in response.text
    assert "value='30' selected" in response.text
    assert "value='90'" in response.text
    rejected_origin = client.post(
        "/oauth/consent",
        headers={"Origin": "https://attacker.example"},
        data={
            "request": interaction,
            "action": "approve",
            "csrf": csrf,
            "grant_ttl_days": str(grant_ttl_days),
        },
        follow_redirects=False,
    )
    assert rejected_origin.status_code == 403
    rejected_csrf = client.post(
        "/oauth/consent",
        headers={"Origin": ISSUER},
        data={
            "request": interaction,
            "action": "approve",
            "csrf": "invalid-csrf",
            "grant_ttl_days": str(grant_ttl_days),
        },
        follow_redirects=False,
    )
    assert rejected_csrf.status_code == 403
    rejected_lifetime = client.post(
        "/oauth/consent",
        headers={"Origin": ISSUER},
        data={
            "request": interaction,
            "action": "approve",
            "csrf": csrf,
            "grant_ttl_days": "2",
        },
        follow_redirects=False,
    )
    assert rejected_lifetime.status_code == 400
    response = client.post(
        "/oauth/consent",
        headers={"Origin": ISSUER},
        data={
            "request": interaction,
            "action": "approve",
            "csrf": csrf,
            "grant_ttl_days": str(grant_ttl_days),
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    callback = urlsplit(response.headers["location"])
    assert f"{callback.scheme}://{callback.netloc}{callback.path}" == REDIRECT_URI
    callback_parameters = parse_qs(callback.query)
    assert callback_parameters["state"] == ["state-bound-to-client"]
    assert callback_parameters["iss"] == [ISSUER]
    return callback_parameters["code"][0]


def exchange_code(
    client: TestClient,
    client_id: str,
    verifier: str,
    code: str,
    *,
    include_resource: bool = True,
) -> dict[str, Any]:
    data = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": verifier,
    }
    if include_resource:
        data["resource"] = RESOURCE
    response = client.post(
        "/token",
        data=data,
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["token_type"] == "Bearer"
    assert payload["scope"] == "mcp:tools"
    assert payload["access_token"].startswith("fmcp_")
    assert payload["refresh_token"].startswith("fmcp_rt_")
    return payload


def rpc(
    client: TestClient,
    token: str,
    payload: dict[str, Any],
    session_id: str | None = None,
):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    if session_id is not None:
        headers["MCP-Session-Id"] = session_id
        headers["MCP-Protocol-Version"] = MCP_PROTOCOL_VERSION
    return client.post("/mcp", headers=headers, json=payload)


def initialize_mcp(client: TestClient, token: str) -> str:
    response = rpc(
        client,
        token,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "oauth-integration", "version": "1.0"},
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION
    return response.headers["mcp-session-id"]


def assert_mcp_unauthorized(client: TestClient, token: str) -> None:
    response = rpc(
        client,
        token,
        {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "revoked", "version": "1.0"},
            },
        },
    )
    assert response.status_code == 401


async def audit_payloads() -> str:
    assert DATABASE_URL is not None
    engine = create_async_engine(DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        events = list((await session.scalars(select(ManagementAuditEvent))).all())
        serialized = json.dumps(
            [{"action": event.action, "details": event.details} for event in events],
            sort_keys=True,
        )
    await engine.dispose()
    return serialized


async def authorization_grant_expiry(code: str) -> datetime:
    assert DATABASE_URL is not None
    engine = create_async_engine(DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        expiry = await session.scalar(
            select(OAuthAuthorizationCode.refresh_expires_at).where(
                OAuthAuthorizationCode.code_hash == hash_token(code)
            )
        )
        assert expiry is not None
    await engine.dispose()
    return expiry


async def issued_token_expiries(access_token: str, refresh_token: str) -> tuple[datetime, datetime]:
    assert DATABASE_URL is not None
    engine = create_async_engine(DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        access_expiry = await session.scalar(
            select(McpToken.expires_at).where(McpToken.token_hash == hash_token(access_token))
        )
        refresh_expiry = await session.scalar(
            select(OAuthRefreshToken.expires_at).where(
                OAuthRefreshToken.token_hash == hash_token(refresh_token)
            )
        )
        assert access_expiry is not None
        assert refresh_expiry is not None
    await engine.dispose()
    return access_expiry, refresh_expiry


async def concurrent_refresh(client_id: str, refresh_token: str) -> tuple[str, str]:
    assert DATABASE_URL is not None
    engine = create_async_engine(DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    service = OAuthService(lambda: factory, oauth_settings())
    client = await service.get_client(client_id)
    assert client is not None
    first = await service.load_refresh_token(client, refresh_token)
    second = await service.load_refresh_token(client, refresh_token)
    assert first is not None
    assert second is not None
    results = await asyncio.gather(
        service.exchange_refresh_token(client, first, ["mcp:tools"]),
        service.exchange_refresh_token(client, second, ["mcp:tools"]),
        return_exceptions=True,
    )
    successes = [result for result in results if isinstance(result, OAuthToken)]
    failures = [result for result in results if isinstance(result, BaseException)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], TokenError)
    assert failures[0].error == "invalid_grant"
    issued = successes[0]
    assert issued.refresh_token is not None
    await engine.dispose()
    return issued.access_token, issued.refresh_token


async def age_rotated_refresh_token(refresh_token: str, age_seconds: int) -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        record = await session.scalar(
            select(OAuthRefreshToken).where(
                OAuthRefreshToken.token_hash == hash_token(refresh_token)
            )
        )
        assert record is not None
        assert record.rotated_at is not None
        record.rotated_at = datetime.now(UTC) - timedelta(seconds=age_seconds)
        await session.commit()
    await engine.dispose()


def test_complete_oauth21_flow_enforces_permissions_and_rotation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    asyncio.run(prepare_oauth_database())
    app = create_app(oauth_settings())
    verifier = "oauth-pkce-verifier-which-is-long-enough-0123456789"
    with caplog.at_level(logging.INFO), TestClient(app, base_url=ISSUER) as client:
        metadata = client.get("/.well-known/oauth-authorization-server")
        assert metadata.status_code == 200
        assert metadata.json()["code_challenge_methods_supported"] == ["S256"]
        resource_metadata = client.get("/.well-known/oauth-protected-resource/mcp")
        assert resource_metadata.status_code == 200
        assert resource_metadata.json()["resource"] == RESOURCE

        client_id = register_client(client)
        interaction = start_authorization(client, client_id, verifier, include_resource=False)
        code = approve_authorization(client, interaction, login=True, grant_ttl_days=7)
        grant_expiry = asyncio.run(authorization_grant_expiry(code))
        remaining_grant = grant_expiry - datetime.now(UTC)
        assert timedelta(days=6, hours=23) < remaining_grant <= timedelta(days=7)
        replayed_consent = client.post(
            "/oauth/consent",
            headers={"Origin": ISSUER},
            data={
                "request": interaction,
                "action": "approve",
                "csrf": client.cookies.get("fmcp_csrf"),
            },
            follow_redirects=False,
        )
        assert replayed_consent.status_code == 400

        wrong_resource = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "code_verifier": verifier,
                "resource": "https://attacker.example/mcp",
            },
        )
        assert wrong_resource.status_code == 400
        assert wrong_resource.json()["error"] == "invalid_request"
        tokens = exchange_code(client, client_id, verifier, code, include_resource=False)

        replay = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "code_verifier": verifier,
                "resource": RESOURCE,
            },
        )
        assert replay.status_code == 400
        assert replay.json()["error"] == "invalid_grant"

        first_access = str(tokens["access_token"])
        first_refresh = str(tokens["refresh_token"])
        first_access_expiry, first_refresh_expiry = asyncio.run(
            issued_token_expiries(first_access, first_refresh)
        )
        assert first_refresh_expiry == grant_expiry
        assert first_access_expiry < first_refresh_expiry
        assert timedelta(minutes=59) < first_access_expiry - datetime.now(UTC) <= timedelta(hours=1)
        session_id = initialize_mcp(client, first_access)
        listed = rpc(
            client,
            first_access,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            session_id,
        )
        assert listed.status_code == 200
        assert {tool["name"] for tool in listed.json()["result"]["tools"]} == READ_TOOLS

        wrong_refresh_resource = client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": first_refresh,
                "scope": "mcp:tools",
                "resource": "https://attacker.example/mcp",
            },
        )
        assert wrong_refresh_resource.status_code == 400
        assert wrong_refresh_resource.json()["error"] == "invalid_request"

        second_access, second_refresh = asyncio.run(concurrent_refresh(client_id, first_refresh))
        assert second_access != first_access
        assert_mcp_unauthorized(client, first_access)
        initialize_mcp(client, second_access)
        _, second_refresh_expiry = asyncio.run(issued_token_expiries(second_access, second_refresh))
        assert second_refresh_expiry == grant_expiry

        asyncio.run(
            age_rotated_refresh_token(
                first_refresh,
                oauth_settings().oauth_refresh_token_reuse_grace_seconds + 1,
            )
        )
        reused = client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": first_refresh,
                "scope": "mcp:tools",
                "resource": RESOURCE,
            },
        )
        assert reused.status_code == 400
        assert reused.json()["error"] == "invalid_grant"
        assert_mcp_unauthorized(client, second_access)

        second_interaction = start_authorization(client, client_id, verifier)
        second_code = approve_authorization(client, second_interaction, login=False)
        revocable = exchange_code(client, client_id, verifier, second_code)
        revocable_access = str(revocable["access_token"])
        initialize_mcp(client, revocable_access)
        revoked = client.post(
            "/revoke",
            data={
                "client_id": client_id,
                "client_secret": "",
                "token": revocable_access,
                "token_type_hint": "access_token",
            },
        )
        assert revoked.status_code == 200
        assert_mcp_unauthorized(client, revocable_access)

        disable_interaction = start_authorization(client, client_id, verifier)
        disable_code = approve_authorization(client, disable_interaction, login=False)
        disabled_oauth = exchange_code(client, client_id, verifier, disable_code)
        disabled_oauth_access = str(disabled_oauth["access_token"])
        initialize_mcp(client, disabled_oauth_access)

    disabled_app = create_app(
        Settings(
            environment="test",
            database_url=DATABASE_URL,
            oauth_enabled=False,
        )
    )
    with TestClient(disabled_app, base_url=ISSUER) as disabled_client:
        assert_mcp_unauthorized(disabled_client, disabled_oauth_access)

    audit_text = asyncio.run(audit_payloads())
    for secret in {
        code,
        first_access,
        first_refresh,
        second_access,
        second_refresh,
        second_code,
        revocable_access,
        str(revocable["refresh_token"]),
        disable_code,
        disabled_oauth_access,
        str(disabled_oauth["refresh_token"]),
    }:
        assert secret not in audit_text
        assert secret not in caplog.text


def test_cimd_client_metadata_is_fetched_without_redirects_and_persisted() -> None:
    asyncio.run(prepare_oauth_database())
    assert DATABASE_URL is not None
    client_id = "https://claude.ai/oauth/client.json"

    async def scenario() -> None:
        engine = create_async_engine(DATABASE_URL)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url) == client_id
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={
                    "client_id": client_id,
                    "client_name": "Anthropic Claude",
                    "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
                    "token_endpoint_auth_method": "none",
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                },
            )

        service = OAuthService(
            lambda: factory,
            oauth_settings(),
            transport=httpx.MockTransport(handler),
            resolver=lambda _host, _port: {"93.184.216.34"},
        )
        loaded = await service.get_client(client_id)
        assert loaded is not None
        assert loaded.client_name == "Anthropic Claude"
        assert loaded.client_secret is None
        cached = await service.get_client(client_id)
        assert cached is not None
        await engine.dispose()

    asyncio.run(scenario())
