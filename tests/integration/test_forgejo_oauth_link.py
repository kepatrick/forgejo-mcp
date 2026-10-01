import asyncio
import base64
import hashlib
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_oauth_flow import DATABASE_URL, ISSUER, oauth_settings, prepare_oauth_database

from forgejo_mcp.application.forgejo_credential_service import ForgejoCredentialService
from forgejo_mcp.application.forgejo_oauth_service import ForgejoOAuthService
from forgejo_mcp.config import Settings
from forgejo_mcp.db.models import Account, ForgejoCredential, ForgejoInstance, ForgejoOAuthRequest
from forgejo_mcp.forgejo.client import ForgejoClient, ForgejoOAuthToken, ForgejoUser
from forgejo_mcp.forgejo.oauth import ForgejoOAuthClient, ForgejoOAuthTokens
from forgejo_mcp.main import create_app

pytestmark = pytest.mark.skipif(DATABASE_URL is None, reason="PostgreSQL not configured")
BASE = "https://git.example.test"
CALLBACK = "/api/me/credential/oauth/callback"


@pytest.fixture
def cfg(tmp_path):
    asyncio.run(prepare_oauth_database())
    key = tmp_path / "credential_key"
    key.write_bytes(base64.b64encode(b"k" * 32))

    async def configure():
        engine = create_async_engine(DATABASE_URL)
        try:
            async with async_sessionmaker(engine)() as session:
                admin_id = await session.scalar(
                    select(Account.id).where(Account.username == "admin")
                )
                session.add(
                    ForgejoInstance(
                        base_url=BASE,
                        verify_tls=True,
                        version="16.0.3",
                        configured_by_account_id=admin_id,
                        last_checked_at=datetime.now(UTC),
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(configure())
    values = oauth_settings().model_dump()
    values.update(
        credential_encryption_key_file=key,
        forgejo_allowed_base_urls=[BASE],
        forgejo_oauth_client_id="forgejo-client",
        forgejo_oauth_redirect_url=ISSUER + CALLBACK,
    )
    return Settings(**values)


@pytest.fixture
def provider(monkeypatch):
    seen = {"exchanges": [], "identity": "OAuthUser", "principals": [], "configurations": []}

    async def exchange(self, *, base_url, verify_tls, values, configuration=None):
        assert base_url == BASE and verify_tls is True
        seen["exchanges"].append(values)
        seen["configurations"].append(configuration)
        if seen.get("on_exchange"):
            await seen["on_exchange"]()
        if values["grant_type"] == "refresh_token":
            await asyncio.sleep(0.05)
        n = len(seen["exchanges"])
        return ForgejoOAuthTokens(
            access_token=f"access-secret-{n}",
            refresh_token=f"refresh-secret-{n}",
            token_type="Bearer",
            expires_in=3600,
        )

    async def principal(self, *, base_url, token, verify_tls):
        assert base_url == BASE and isinstance(token, ForgejoOAuthToken)
        seen["principals"].append(token)
        return ForgejoUser(id=42, username=seen["identity"])

    monkeypatch.setattr(ForgejoOAuthClient, "exchange", exchange)
    monkeypatch.setattr(ForgejoClient, "get_current_user", principal)
    return seen


def login(client, *, username="oauth-user", password="user-password-for-testing"):
    assert (
        client.post(
            "/api/auth/login", json={"username": username, "password": password}
        ).status_code
        == 200
    )


def start(client):
    response = client.post(
        "/api/me/credential/oauth/start", headers={"X-CSRF-Token": client.cookies.get("fmcp_csrf")}
    )
    assert response.status_code == 200, response.text
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Max-Age=600" in cookie
    assert f"Path={CALLBACK}" in cookie
    assert client.cookies.get("fmcp_forgejo_oauth_session") != client.cookies.get("fmcp_session")
    url = urlsplit(response.json()["authorization_url"])
    assert url.scheme + "://" + url.netloc == BASE
    assert url.path == "/login/oauth/authorize"
    params = parse_qs(url.query)
    assert params["code_challenge_method"] == ["S256"]
    assert params["redirect_uri"] == [ISSUER + CALLBACK]
    return params


def complete(client, params, **kwargs):
    return client.get(
        CALLBACK,
        params={"state": params["state"][0], "code": "provider-code", **kwargs},
        follow_redirects=False,
    )


async def active_credential():
    engine = create_async_engine(DATABASE_URL)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            return await session.scalar(
                select(ForgejoCredential).where(ForgejoCredential.status == "active")
            )
    finally:
        await engine.dispose()


def test_full_link_binds_pkce_identity_and_encrypts_both_tokens(cfg, provider, caplog):
    with TestClient(create_app(cfg), base_url=ISSUER) as client:
        login(client)
        assert client.get("/api/me/credential/oauth/status").json() == {"enabled": True}
        params = start(client)
        response = complete(client, params)
        assert (
            response.status_code == 303
            and response.headers["location"] == "/?forgejo_oauth=connected"
        )
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["cache-control"] == "no-store"
        verifier = provider["exchanges"][0]["code_verifier"]
        assert (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
            == params["code_challenge"][0]
        )
        credential = asyncio.run(active_credential())
        assert credential.kind == "oauth" and credential.oauth_base_url == BASE
        assert credential.encrypted_refresh_token and credential.encrypted_token
        assert b"access-secret" not in credential.encrypted_token
        assert b"refresh-secret" not in credential.encrypted_refresh_token
        public = client.get("/api/me/credential").text
        assert "access-secret" not in public and "refresh-secret" not in public
        assert "oauth" in public
        assert complete(client, params).headers["location"] == "/?forgejo_oauth=failed"
        assert len(provider["exchanges"]) == 1
        assert "provider-code" not in caplog.text and verifier not in caplog.text
        revoked = client.delete(
            "/api/me/credential", headers={"X-CSRF-Token": client.cookies.get("fmcp_csrf")}
        )
        assert revoked.status_code == 204
        assert asyncio.run(active_credential()) is None


@pytest.mark.parametrize(
    "failure", ["state", "expired", "denied", "instance", "identity", "session"]
)
def test_failed_link_does_not_replace_existing_pat(cfg, provider, failure):
    with TestClient(create_app(cfg), base_url=ISSUER) as client:
        login(client)
        params = start(client)
        kwargs = {}
        if failure == "state":
            kwargs["state"] = "x" * 43
        elif failure == "denied":
            kwargs["error"] = "access_denied"
        elif failure == "identity":
            provider["identity"] = "SomeoneElse"
        elif failure == "session":
            # Same user but a different browser session must not redeem the request.
            client.cookies.clear()
            login(client)
        else:

            async def mutate():
                engine = create_async_engine(DATABASE_URL)
                try:
                    async with async_sessionmaker(engine)() as session:
                        if failure == "expired":
                            await session.execute(
                                update(ForgejoOAuthRequest).values(
                                    expires_at=datetime.now(UTC) - timedelta(seconds=1)
                                )
                            )
                        else:
                            await session.execute(
                                update(ForgejoOAuthRequest).values(
                                    base_url="https://attacker.example"
                                )
                            )
                        await session.commit()
                finally:
                    await engine.dispose()

            asyncio.run(mutate())
        response = complete(client, params, **kwargs)
        assert response.headers["location"] == "/?forgejo_oauth=failed"
        assert asyncio.run(active_credential()).kind == "pat"
        assert len(provider["exchanges"]) == (1 if failure == "identity" else 0)


def test_start_requires_user_session_and_csrf(cfg, provider):
    with TestClient(create_app(cfg), base_url=ISSUER) as client:
        assert client.post("/api/me/credential/oauth/start").status_code == 401
        login(client)
        assert client.post("/api/me/credential/oauth/start").status_code == 403
        login(client, username="admin", password="admin-password-for-testing")
        assert (
            client.post(
                "/api/me/credential/oauth/start",
                headers={"X-CSRF-Token": client.cookies.get("fmcp_csrf")},
            ).status_code
            == 403
        )
        assert not provider["exchanges"]


def test_concurrent_refresh_is_serialized_and_client_change_fails_closed(cfg, provider):
    with TestClient(create_app(cfg), base_url=ISSUER) as client:
        login(client)
        assert complete(client, start(client)).headers["location"] == "/?forgejo_oauth=connected"
        credential = asyncio.run(active_credential())

        async def refresh_concurrently():
            engine = create_async_engine(DATABASE_URL)
            factory = async_sessionmaker(engine, expire_on_commit=False)
            try:
                async with factory() as session:
                    await session.execute(
                        update(ForgejoCredential)
                        .where(ForgejoCredential.id == credential.id)
                        .values(access_expires_at=datetime.now(UTC) - timedelta(seconds=1))
                    )
                    await session.commit()

                async def refresh_one():
                    async with factory() as session:
                        return await ForgejoCredentialService(
                            session, cfg
                        ).decrypted_token_for_user(credential.user_id)

                tokens = await asyncio.gather(refresh_one(), refresh_one())
                assert tokens == ["access-secret-2", "access-secret-2"]
                assert all(isinstance(t, ForgejoOAuthToken) for t in tokens)
                async with factory() as session:
                    changed = cfg.model_copy(update={"forgejo_oauth_client_id": "different-client"})
                    with pytest.raises(Exception, match="reconnect"):
                        await ForgejoOAuthService(session, changed).access_token(credential.user_id)
            finally:
                await engine.dispose()

        asyncio.run(refresh_concurrently())
        assert len(provider["exchanges"]) == 2
        assert provider["exchanges"][1]["refresh_token"] == "refresh-secret-1"


@pytest.mark.parametrize("action", ["revoke", "disable", "rename"])
def test_all_local_revocation_paths_erase_refresh_secrets(cfg, provider, action):
    with TestClient(create_app(cfg), base_url=ISSUER) as client:
        login(client)
        assert complete(client, start(client)).headers["location"] == "/?forgejo_oauth=connected"
        credential = asyncio.run(active_credential())
        csrf = {"X-CSRF-Token": client.cookies.get("fmcp_csrf")}
        if action == "revoke":
            assert client.delete("/api/me/credential", headers=csrf).status_code == 204
        else:
            login(client, username="admin", password="admin-password-for-testing")
            csrf = {"X-CSRF-Token": client.cookies.get("fmcp_csrf")}
            if action == "disable":
                assert (
                    client.post(
                        f"/api/users/{credential.user_id}/disable", headers=csrf
                    ).status_code
                    == 200
                )
            else:
                assert (
                    client.patch(
                        f"/api/users/{credential.user_id}",
                        headers=csrf,
                        json={
                            "display_name": "Renamed",
                            "forgejo_username": "AnotherIdentity",
                        },
                    ).status_code
                    == 200
                )

        async def check_secrets():
            engine = create_async_engine(DATABASE_URL)
            try:
                async with async_sessionmaker(engine)() as session:
                    old = await session.get(ForgejoCredential, credential.id)
                    assert old.status == "revoked"
                    assert old.encrypted_token is None and old.nonce is None
                    assert old.encrypted_refresh_token is None and old.refresh_nonce is None
            finally:
                await engine.dispose()

        asyncio.run(check_secrets())
