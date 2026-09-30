import asyncio
import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_oauth_flow import (
    DATABASE_URL,
    ISSUER,
    READ_TOOLS,
    REDIRECT_URI,
    RESOURCE,
    approve_authorization,
    assert_mcp_unauthorized,
    exchange_code,
    initialize_mcp,
    issued_token_id,
    oauth_settings,
    prepare_oauth_database,
    register_client,
    rpc,
    start_authorization,
)

from forgejo_mcp.db.models import ToolInvocation
from forgejo_mcp.main import create_app

pytestmark = pytest.mark.skipif(
    DATABASE_URL is None, reason="integration PostgreSQL not configured"
)
VERIFIER = "a" * 64


def issue(client, client_id, *, login=False):
    interaction = start_authorization(client, client_id, VERIFIER)
    code = approve_authorization(client, interaction, login=login)
    return exchange_code(client, client_id, VERIFIER, code)


def test_refresh_preserves_session_but_not_other_grants(monkeypatch):
    asyncio.run(prepare_oauth_database())

    async def execute(*args, **kwargs):
        return {"id": 42, "username": "OAuthUser"}

    monkeypatch.setattr("forgejo_mcp.mcp.server._execute_tool", execute)
    with TestClient(create_app(oauth_settings()), base_url=ISSUER) as client:
        cid = register_client(client)
        first = issue(client, cid, login=True)
        sid = initialize_mcp(client, first["access_token"])
        refreshed = client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "client_id": cid,
                "refresh_token": first["refresh_token"],
                "resource": RESOURCE,
            },
        )
        assert refreshed.status_code == 200
        current = refreshed.json()["access_token"]
        assert_mcp_unauthorized(client, first["access_token"])
        listing = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        listed = rpc(client, current, listing, sid)
        assert listed.status_code == 200
        assert {tool["name"] for tool in listed.json()["result"]["tools"]} == READ_TOOLS
        called = rpc(
            client,
            current,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "forgejo_get_current_user", "arguments": {}},
            },
            sid,
        )
        assert called.status_code == 200
        assert not called.json()["result"].get("isError", False)

        async def audit_token():
            engine = create_async_engine(DATABASE_URL)
            try:
                async with async_sessionmaker(engine)() as session:
                    return await session.scalar(select(ToolInvocation.mcp_token_id))
            finally:
                await engine.dispose()

        assert asyncio.run(audit_token()) == asyncio.run(issued_token_id(current))
        # Even another consent by the SAME client and user is a different family.
        other = issue(client, cid)
        assert rpc(client, other["access_token"], listing, sid).status_code == 404
        other_client = register_client(client)
        separate = issue(client, other_client)
        assert rpc(client, separate["access_token"], listing, sid).status_code == 404
        token_id = asyncio.run(issued_token_id(current))
        revoked = client.delete(
            f"/api/me/mcp-tokens/{token_id}",
            headers={
                "X-CSRF-Token": client.cookies.get("fmcp_csrf"),
            },
        )
        assert revoked.status_code == 204
        assert rpc(client, current, listing, sid).status_code == 401


@pytest.mark.parametrize("secret", [None, ""])
@pytest.mark.parametrize("kind", ["access_token", "refresh_token"])
def test_public_client_revocation_does_not_require_secret(secret, kind):
    asyncio.run(prepare_oauth_database())
    with TestClient(create_app(oauth_settings()), base_url=ISSUER) as client:
        cid = register_client(client)
        tokens = issue(client, cid, login=True)
        other = register_client(client)
        data = {"client_id": cid, "token": tokens[kind], "token_type_hint": kind}
        if secret is not None:
            data["client_secret"] = secret
        # Do not disclose token ownership or revoke another client's grant.
        assert client.post("/revoke", data={**data, "client_id": other}).status_code == 200
        initialize_mcp(client, tokens["access_token"])
        assert client.post("/revoke", data=data).status_code == 200
        assert_mcp_unauthorized(client, tokens["access_token"])
        assert (
            client.post(
                "/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": cid,
                    "refresh_token": tokens["refresh_token"],
                },
            ).status_code
            == 400
        )
        assert client.post("/revoke", data=data).status_code == 200
        assert client.post("/revoke", data={**data, "token": "unknown"}).status_code == 200


@pytest.mark.parametrize("explicit", [False, True])
def test_redirect_uri_presence_round_trips(explicit):
    asyncio.run(prepare_oauth_database())
    with TestClient(create_app(oauth_settings()), base_url=ISSUER) as client:
        cid = register_client(client)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest())
            .decode()
            .rstrip("=")
        )
        params = {
            "response_type": "code",
            "client_id": cid,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": "mcp:tools",
            "state": "state-bound-to-client",
            "resource": RESOURCE,
        }
        if explicit:
            params["redirect_uri"] = REDIRECT_URI
        response = client.get("/authorize", params=params, follow_redirects=False)
        assert response.status_code == 302
        interaction = parse_qs(urlsplit(response.headers["location"]).query)["request"][0]
        code = approve_authorization(client, interaction, login=True)
        data = {
            "grant_type": "authorization_code",
            "client_id": cid,
            "code": code,
            "code_verifier": VERIFIER,
        }
        assert (
            client.post(
                "/token", data={**data, "redirect_uri": "https://attacker.example/callback"}
            ).status_code
            == 400
        )
        if explicit:
            assert client.post("/token", data=data).status_code == 400
            data["redirect_uri"] = REDIRECT_URI
        assert client.post("/token", data=data).status_code == 200

        registered = client.post(
            "/register",
            json={
                "redirect_uris": [REDIRECT_URI, "https://second.example/callback"],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            },
        )
        assert registered.status_code == 201
        params["client_id"] = registered.json()["client_id"]
        params.pop("redirect_uri", None)
        assert client.get("/authorize", params=params, follow_redirects=False).status_code == 400
