import asyncio
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_forgejo_oauth_link import cfg as _cfg
from test_forgejo_oauth_link import complete, login, start
from test_forgejo_oauth_link import provider as _provider
from test_oauth_flow import DATABASE_URL, ISSUER

from forgejo_mcp.application.forgejo_credential_service import ForgejoCredentialService
from forgejo_mcp.db.models import ForgejoCredential, ForgejoOAuthConfiguration, ManagementAuditEvent
from forgejo_mcp.main import create_app

cfg = _cfg
provider = _provider
pytestmark = pytest.mark.skipif(DATABASE_URL is None, reason="PostgreSQL not configured")
PATH = "/api/forgejo/instance/oauth"
SECRET = "admin-ui-client-secret"


def admin(client):
    login(client, username="admin", password="admin-password-for-testing")


def payload(**changes):
    return {
        "enabled": True,
        "client_id": "admin-ui-client",
        "base_url": ISSUER,
        "client_type": "confidential",
        "client_secret": SECRET,
        **changes,
    }


def save(client, data):
    return client.put(PATH, json=data, headers={"X-CSRF-Token": client.cookies.get("fmcp_csrf")})


async def stored_config():
    engine = create_async_engine(DATABASE_URL)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            return await session.scalar(select(ForgejoOAuthConfiguration))
    finally:
        await engine.dispose()


def test_admin_only_csrf_guard_and_secret_never_returned(cfg, provider, caplog):
    with TestClient(create_app(cfg), base_url=ISSUER) as client:
        assert client.get(PATH).status_code == 401
        assert client.put(PATH, json=payload()).status_code == 401
        login(client)
        assert client.get(PATH).status_code == 403
        assert save(client, payload()).status_code == 403
        admin(client)
        assert client.put(PATH, json=payload()).status_code == 403
        response = save(client, payload())
        assert response.status_code == 200, response.text
        assert response.json()["secret_configured"] is True
        assert response.json()["redirect_url"] == ISSUER + "/api/me/credential/oauth/callback"
        assert SECRET not in response.text and "client_secret" not in response.json()
        fetched = client.get(PATH)
        assert fetched.headers["cache-control"] == "no-store"
        assert SECRET not in fetched.text
        record = asyncio.run(stored_config())
        assert record.encrypted_secret and SECRET.encode() not in record.encrypted_secret
        assert record.nonce and record.key_version == 1
        assert SECRET not in caplog.text

        async def inspect_audit():
            engine = create_async_engine(DATABASE_URL)
            try:
                async with async_sessionmaker(engine)() as session:
                    events = list(
                        await session.scalars(
                            select(ManagementAuditEvent).where(
                                ManagementAuditEvent.action == "forgejo_oauth.configuration_updated"
                            )
                        )
                    )
                    assert len(events) == 1
                    assert SECRET not in repr(events[0].details)
            finally:
                await engine.dispose()

        asyncio.run(inspect_audit())


@pytest.mark.parametrize(
    "base",
    [
        ISSUER + "/custom/path",
        ISSUER + "?query=x",
        ISSUER + "#fragment",
        "https://user:password@mcp.example.test",
        "http://remote.example.test",
        "javascript:alert(1)",
    ],
)
def test_invalid_base_urls_do_not_persist(cfg, provider, base):
    with TestClient(create_app(cfg), base_url=ISSUER) as client:
        admin(client)
        assert save(client, payload(base_url=base)).status_code == 422
        assert asyncio.run(stored_config()) is None


def test_fixed_callback_normalizes_base_and_rejects_callback_override(cfg, provider):
    with TestClient(create_app(cfg), base_url=ISSUER) as client:
        admin(client)
        rejected = save(client, payload(redirect_url="https://attacker.example/callback"))
        assert rejected.status_code == 422
        saved = save(client, payload(base_url="HTTPS://MCP.EXAMPLE.TEST:443/"))
        assert saved.status_code == 200
        assert saved.json()["base_url"] == ISSUER
        assert saved.json()["redirect_url"] == ISSUER + "/api/me/credential/oauth/callback"


def test_secret_keep_rotate_clear_and_require_new_secret_for_changed_client(cfg, provider):
    with TestClient(create_app(cfg), base_url=ISSUER) as client:
        admin(client)
        assert save(client, payload()).status_code == 200
        first = asyncio.run(stored_config())
        assert save(client, payload(client_secret=None)).status_code == 200
        kept = asyncio.run(stored_config())
        assert kept.encrypted_secret == first.encrypted_secret
        assert kept.revision != first.revision
        assert (
            save(client, payload(client_id="other-client", client_secret=None)).status_code == 422
        )
        assert save(client, payload(client_secret="rotated-client-secret")).status_code == 200
        rotated = asyncio.run(stored_config())
        assert rotated.encrypted_secret != first.encrypted_secret
        assert save(client, payload(client_type="public", client_secret=None)).status_code == 200
        public = asyncio.run(stored_config())
        assert (
            public.encrypted_secret is None and public.nonce is None and public.key_version is None
        )
        assert save(client, payload(client_type="public")).status_code == 422


def test_database_disable_overrides_enabled_environment(cfg, provider):
    with TestClient(create_app(cfg), base_url=ISSUER) as client:
        admin(client)
        assert client.get(PATH).json()["source"] == "environment"
        assert save(client, payload(enabled=False, client_secret=None)).status_code == 200
        assert client.get(PATH).json()["source"] == "dashboard"
        login(client)
        assert client.get("/api/me/credential/oauth/status").json() == {"enabled": False}
        assert (
            client.post(
                "/api/me/credential/oauth/start",
                headers={"X-CSRF-Token": client.cookies.get("fmcp_csrf")},
            ).status_code
            == 503
        )
        assert not provider["exchanges"]


def test_dynamic_configuration_is_used_in_exchange_and_refresh(cfg, provider):
    with TestClient(create_app(cfg), base_url=ISSUER) as client:
        admin(client)
        assert save(client, payload()).status_code == 200
        login(client)
        params = start(client)
        assert params["client_id"] == ["admin-ui-client"]
        assert complete(client, params).headers["location"] == "/?forgejo_oauth=connected"
        assert provider["configurations"][0].client_secret.get_secret_value() == SECRET
        admin(client)
        assert save(client, payload(client_secret="new-secret-for-refresh")).status_code == 200

        async def expire_and_refresh():
            engine = create_async_engine(DATABASE_URL)
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                    record = await session.scalar(
                        select(ForgejoCredential).where(ForgejoCredential.status == "active")
                    )
                    assert record.oauth_client_id == "admin-ui-client"
                    user_id = record.user_id
                    await session.execute(
                        update(ForgejoCredential)
                        .where(ForgejoCredential.id == record.id)
                        .values(access_expires_at=datetime.now(UTC) - timedelta(seconds=1))
                    )
                    await session.commit()
                    token = await ForgejoCredentialService(session, cfg).decrypted_token_for_user(
                        user_id
                    )
                    assert token == "access-secret-2"
            finally:
                await engine.dispose()

        asyncio.run(expire_and_refresh())
        assert (
            provider["configurations"][-1].client_secret.get_secret_value()
            == "new-secret-for-refresh"
        )
        assert provider["configurations"][-1].client_id == "admin-ui-client"


def test_admin_changes_invalidate_pending_authorization(cfg, provider):
    with TestClient(create_app(cfg), base_url=ISSUER) as client:
        admin(client)
        assert save(client, payload()).status_code == 200
        login(client)
        params = start(client)
        # Use another admin browser; do not overwrite the user's session/cookies.
        with TestClient(create_app(cfg), base_url=ISSUER) as management:
            admin(management)
            assert (
                save(management, payload(base_url="https://new-mcp.example.test")).status_code
                == 200
            )
        assert complete(client, params).headers["location"] == "/?forgejo_oauth=failed"
        assert not provider["exchanges"]


def test_callback_url_is_derived_without_trusting_request_host(cfg, provider):
    with TestClient(create_app(cfg), base_url=ISSUER) as client:
        admin(client)
        assert save(client, payload(base_url="https://public-mcp.example.test")).status_code == 200
        login(client)
        response = client.post(
            "/api/me/credential/oauth/start",
            headers={
                "X-CSRF-Token": client.cookies.get("fmcp_csrf"),
                "X-Forwarded-Host": "attacker.example",
            },
        )
        assert response.status_code == 200
        params = parse_qs(urlsplit(response.json()["authorization_url"]).query)
        assert params["redirect_uri"] == [
            "https://public-mcp.example.test/api/me/credential/oauth/callback"
        ]


def test_invalid_secret_shape_is_redacted_and_oversized_body_is_bounded(cfg, provider):
    with TestClient(create_app(cfg), base_url=ISSUER) as client:
        admin(client)
        for changes in ({"client_secret": {"private": SECRET}}, {"unknown": {"private": SECRET}}):
            response = save(client, payload(**changes))
            assert response.status_code == 422
            assert SECRET not in response.text
            assert response.headers["cache-control"] == "no-store"
        assert save(client, payload(client_secret="x" * 100_000)).status_code == 413
        assert asyncio.run(stored_config()) is None


def test_configuration_change_during_exchange_keeps_existing_pat(cfg, provider):
    from forgejo_mcp.application.forgejo_oauth_config_service import ForgejoOAuthConfigService

    async def change_configuration():
        engine = create_async_engine(DATABASE_URL)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                service = ForgejoOAuthConfigService(session, cfg)
                record = await service.record()
                await service.save(
                    actor_account_id=record.updated_by_account_id,
                    enabled=True,
                    client_id=record.client_id,
                    base_url="https://changed-during-exchange.example.test",
                    client_type="confidential",
                    client_secret=None,
                )
        finally:
            await engine.dispose()

    with TestClient(create_app(cfg), base_url=ISSUER) as client:
        admin(client)
        assert save(client, payload()).status_code == 200
        login(client)
        params = start(client)
        provider["on_exchange"] = change_configuration
        assert complete(client, params).headers["location"] == "/?forgejo_oauth=failed"
        assert len(provider["exchanges"]) == 1

        async def check_pat():
            engine = create_async_engine(DATABASE_URL)
            try:
                async with async_sessionmaker(engine)() as session:
                    credentials = list(await session.scalars(select(ForgejoCredential)))
                    assert len(credentials) == 1
                    assert credentials[0].status == "active" and credentials[0].kind == "pat"
            finally:
                await engine.dispose()

        asyncio.run(check_pat())


def test_concurrent_configuration_readers_share_locks_while_admin_writes_wait(cfg, provider):
    from forgejo_mcp.application.forgejo_oauth_config_service import ForgejoOAuthConfigService

    with TestClient(create_app(cfg), base_url=ISSUER) as client:
        admin(client)
        assert save(client, payload()).status_code == 200

    async def exercise_locks():
        engine = create_async_engine(DATABASE_URL)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as left, factory() as right, factory() as writer:
                await ForgejoOAuthConfigService(left, cfg).resolve(lock=True)
                await asyncio.wait_for(
                    ForgejoOAuthConfigService(right, cfg).resolve(lock=True), timeout=3
                )
                record = await ForgejoOAuthConfigService(writer, cfg).record()
                task = asyncio.create_task(
                    ForgejoOAuthConfigService(writer, cfg).save(
                        actor_account_id=record.updated_by_account_id,
                        enabled=False,
                        client_id=record.client_id,
                        client_type="confidential",
                        base_url=ISSUER,
                        client_secret=None,
                    )
                )
                try:
                    await asyncio.sleep(0.1)
                    assert not task.done()
                    await left.rollback()
                    await asyncio.sleep(0.1)
                    assert not task.done()
                    await right.rollback()
                    await asyncio.wait_for(task, timeout=3)
                finally:
                    await left.rollback()
                    await right.rollback()
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        finally:
            await engine.dispose()

    asyncio.run(exercise_locks())


def test_legacy_confidential_secret_is_imported_once_and_not_read_after_save(
    cfg, provider, tmp_path
):
    secret_file = tmp_path / "legacy-client-secret"
    secret_file.write_text("legacy-file-secret\n")
    configured = cfg.model_copy(update={"forgejo_oauth_client_secret_file": secret_file})
    with TestClient(create_app(configured), base_url=ISSUER) as client:
        admin(client)
        current = client.get(PATH).json()
        assert current["source"] == "environment" and current["secret_configured"]
        response = save(client, payload(client_id="forgejo-client", client_secret=None))
        assert response.status_code == 200
        assert response.json()["source"] == "dashboard"
        assert "legacy-file-secret" not in response.text and str(secret_file) not in response.text
        secret_file.unlink()
        login(client)
        params = start(client)
        assert complete(client, params).headers["location"] == "/?forgejo_oauth=connected"
        assert (
            provider["configurations"][0].client_secret.get_secret_value() == "legacy-file-secret"
        )


def test_noop_configuration_save_also_invalidates_pending_revision(cfg, provider):
    with TestClient(create_app(cfg), base_url=ISSUER) as client:
        admin(client)
        assert save(client, payload()).status_code == 200
        login(client)
        params = start(client)
        with TestClient(create_app(cfg), base_url=ISSUER) as management:
            admin(management)
            assert save(management, payload(client_secret=None)).status_code == 200
        assert complete(client, params).headers["location"] == "/?forgejo_oauth=failed"
        assert not provider["exchanges"]


def test_production_forbids_even_loopback_http_callback(cfg, provider):
    production = cfg.model_copy(update={"environment": "production"})
    with TestClient(create_app(production), base_url=ISSUER) as client:
        admin(client)
        assert save(client, payload(base_url="http://127.0.0.1:8000")).status_code == 422
        assert asyncio.run(stored_config()) is None
