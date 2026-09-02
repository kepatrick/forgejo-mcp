import asyncio
import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.requests import Request

from forgejo_mcp.application.errors import (
    ConfigurationUnavailable,
    ExternalServiceUnavailable,
    ValidationFailed,
)
from forgejo_mcp.application.forgejo_credential_service import ForgejoCredentialService
from forgejo_mcp.application.forgejo_instance_service import ForgejoInstanceService
from forgejo_mcp.application.forgejo_tool_service import ForgejoToolService
from forgejo_mcp.application.runtime import InvocationCoordinator, ServiceShuttingDown
from forgejo_mcp.auth.client_ip import get_client_ip
from forgejo_mcp.auth.rate_limit import LoginRateLimiter, MultiScopeRateLimiter
from forgejo_mcp.config import Settings
from forgejo_mcp.forgejo import client as forgejo_client_module
from forgejo_mcp.forgejo.client import ForgejoClient
from forgejo_mcp.main import create_app
from forgejo_mcp.observability.context import reset_request_id, set_request_id
from forgejo_mcp.observability.logging import JsonFormatter


def test_mcp_request_body_limit_and_request_id() -> None:
    app = create_app(Settings(environment="test", mcp_request_max_bytes=1024))
    with TestClient(app) as client:
        rejected = client.post(
            "/mcp",
            content=b"x" * 1025,
            headers={"content-type": "application/json", "x-request-id": "request-123"},
        )
        live = client.get("/health/live", headers={"x-request-id": "request-456"})
    assert rejected.status_code == 413
    assert rejected.json() == {"detail": "MCP request body is too large"}
    assert rejected.headers["x-request-id"] == "request-123"
    assert live.headers["x-request-id"] == "request-456"


def test_production_requires_out_of_band_forgejo_url_allowlist() -> None:
    with pytest.raises(ValidationError, match="FMCP_FORGEJO_ALLOWED_BASE_URLS"):
        Settings(environment="production")
    settings = Settings(
        environment="production",
        forgejo_allowed_base_urls=["HTTPS://Git.Example.test/forgejo/"],
    )
    assert settings.forgejo_allowed_base_urls == ["https://git.example.test/forgejo"]
    assert settings.permits_forgejo_base_url("https://git.example.test/forgejo/")
    assert not settings.permits_forgejo_base_url("https://attacker.example")


@pytest.mark.parametrize("environment", ["development", "test"])
def test_empty_forgejo_allowlist_fails_closed_in_every_environment(environment: str) -> None:
    settings = Settings(environment=environment)  # type: ignore[arg-type]

    assert not settings.permits_forgejo_base_url("https://git.example.test")


def _request_from(peer: str, forwarded_for: str | None = None) -> Request:
    headers = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode("ascii")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
            "client": (peer, 12345),
        }
    )


def test_forwarded_client_ip_requires_a_trusted_direct_proxy() -> None:
    request = _request_from("10.0.0.10", "198.51.100.7")

    assert get_client_ip(request, Settings(environment="test")) == "10.0.0.10"
    assert (
        get_client_ip(
            request,
            Settings(environment="test", trusted_proxy_cidrs=["10.0.0.0/24"]),
        )
        == "198.51.100.7"
    )


def test_forwarded_client_ip_walks_right_to_left_and_rejects_invalid_chains() -> None:
    settings = Settings(
        environment="test",
        trusted_proxy_cidrs=["10.0.0.0/24", "192.0.2.0/24"],
    )

    assert (
        get_client_ip(
            _request_from("10.0.0.10", "198.51.100.7, 192.0.2.20"),
            settings,
        )
        == "198.51.100.7"
    )
    assert get_client_ip(_request_from("10.0.0.10", "invalid"), settings) == "10.0.0.10"


def test_forwarded_client_ip_combines_duplicate_header_lines() -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [
                (b"x-forwarded-for", b"203.0.113.9"),
                (b"x-forwarded-for", b"198.51.100.7"),
            ],
            "client": ("10.0.0.10", 12345),
        }
    )
    settings = Settings(
        environment="test",
        trusted_proxy_cidrs=["10.0.0.0/24"],
    )

    assert get_client_ip(request, settings) == "198.51.100.7"


def test_trusted_proxy_cidrs_are_normalized_and_validated() -> None:
    settings = Settings(environment="test", trusted_proxy_cidrs=["10.0.0.7/24"])
    assert settings.trusted_proxy_cidrs == ["10.0.0.0/24"]
    with pytest.raises(ValidationError, match="trusted proxy CIDRs"):
        Settings(environment="test", trusted_proxy_cidrs=["not-a-network"])


def test_production_oauth_requires_consistent_https_urls() -> None:
    with pytest.raises(ValidationError, match="OAUTH_ISSUER_URL"):
        Settings(
            environment="production",
            forgejo_allowed_base_urls=["https://git.example.test"],
            oauth_enabled=True,
        )
    with pytest.raises(ValidationError, match="must use HTTPS"):
        Settings(
            environment="production",
            forgejo_allowed_base_urls=["https://git.example.test"],
            oauth_enabled=True,
            oauth_issuer_url="http://mcp.example.test",
            oauth_resource_url="http://mcp.example.test/mcp",
            oauth_cimd_allowed_origins=["https://claude.ai"],
        )
    with pytest.raises(ValidationError, match="origin without a path"):
        Settings(
            environment="test",
            oauth_enabled=True,
            oauth_issuer_url="https://mcp.example.test/oauth",
            oauth_resource_url="https://mcp.example.test/mcp",
        )
    with pytest.raises(ValidationError, match="issuer origin followed by /mcp"):
        Settings(
            environment="test",
            oauth_enabled=True,
            oauth_issuer_url="https://mcp.example.test",
            oauth_resource_url="https://other.example.test/mcp",
        )
    with pytest.raises(ValidationError, match="CIMD origins must use HTTPS"):
        Settings(
            environment="production",
            forgejo_allowed_base_urls=["https://git.example.test"],
            oauth_enabled=True,
            oauth_issuer_url="https://mcp.example.test",
            oauth_resource_url="https://mcp.example.test/mcp",
            oauth_cimd_allowed_origins=["http://claude.ai"],
        )
    settings = Settings(
        environment="production",
        forgejo_allowed_base_urls=["https://git.example.test"],
        oauth_enabled=True,
        oauth_issuer_url="HTTPS://MCP.Example.test/",
        oauth_resource_url="HTTPS://MCP.Example.test/mcp/",
        oauth_cimd_allowed_origins=["https://CLAUDE.ai:443/"],
    )
    assert settings.oauth_issuer_url == "https://mcp.example.test"
    assert settings.oauth_resource_url == "https://mcp.example.test/mcp"
    assert settings.oauth_cimd_allowed_origins == ["https://claude.ai"]
    dcr_only = Settings(
        environment="production",
        forgejo_allowed_base_urls=["https://git.example.test"],
        oauth_enabled=True,
        oauth_issuer_url="https://mcp.example.test",
        oauth_resource_url="https://mcp.example.test/mcp",
        oauth_cimd_allowed_origins=[],
    )
    assert dcr_only.oauth_cimd_allowed_origins == []


def test_database_url_file_overrides_environment_value(tmp_path: Path) -> None:
    database_url_file = tmp_path / "database_url"
    database_url_file.write_text(
        "postgresql+asyncpg://app:file-secret@postgres/app\n",
        encoding="utf-8",
    )

    settings = Settings(
        environment="test",
        database_url="postgresql+asyncpg://app:environment-secret@postgres/app",
        database_url_file=database_url_file,
    )

    assert settings.database_url == "postgresql+asyncpg://app:file-secret@postgres/app"


def test_database_url_file_must_be_readable_and_nonempty(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unable to read"):
        Settings(environment="test", database_url_file=tmp_path / "missing")

    empty_file = tmp_path / "empty"
    empty_file.write_text("\n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty or too large"):
        Settings(environment="test", database_url_file=empty_file)


async def test_forgejo_instance_policy_rejects_untrusted_url_before_network() -> None:
    service = ForgejoInstanceService(
        session=None,  # type: ignore[arg-type]
        settings=Settings(
            environment="test",
            forgejo_allowed_base_urls=["https://git.example.test"],
        ),
    )
    with pytest.raises(ValidationFailed, match="deployment policy"):
        await service.check(base_url="https://attacker.example", verify_tls=True)


async def test_unverified_forgejo_tls_requires_deployment_opt_in() -> None:
    service = ForgejoInstanceService(
        session=None,  # type: ignore[arg-type]
        settings=Settings(
            environment="test",
            forgejo_allowed_base_urls=["https://git.example.test"],
        ),
    )

    with pytest.raises(ValidationFailed, match="unverified Forgejo TLS"):
        await service.check(base_url="https://git.example.test", verify_tls=False)


async def test_inherited_unverified_tls_is_rejected_before_pat_verification() -> None:
    user_id = uuid.uuid4()

    class FakeUsers:
        async def get(self, _user_id: uuid.UUID) -> SimpleNamespace:
            return SimpleNamespace(id=user_id, normalized_forgejo_username="patrick")

    class FakeInstances:
        async def primary(self) -> SimpleNamespace:
            return SimpleNamespace(base_url="https://git.example.test", verify_tls=False)

    class UnexpectedClient:
        async def get_current_user(self, **_kwargs: object) -> None:
            raise AssertionError("the PAT must not be sent when TLS verification is forbidden")

    service = object.__new__(ForgejoCredentialService)
    service.settings = Settings(
        environment="test",
        forgejo_allowed_base_urls=["https://git.example.test"],
    )
    service.users = FakeUsers()  # type: ignore[assignment]
    service.instances = FakeInstances()  # type: ignore[assignment]
    service.client = UnexpectedClient()  # type: ignore[assignment]

    with pytest.raises(ConfigurationUnavailable, match="unverified TLS"):
        await service.verify(
            actor_account_id=uuid.uuid4(),
            user_id=user_id,
            token="synthetic-pat",
        )


async def test_inherited_unverified_tls_is_rejected_before_pat_decryption() -> None:
    class FakeInstances:
        async def primary(self) -> SimpleNamespace:
            return SimpleNamespace(base_url="https://git.example.test", verify_tls=False)

    class UnexpectedCredentials:
        async def decrypted_token_for_user(self, _user_id: uuid.UUID) -> str:
            raise AssertionError("the PAT must not be decrypted when TLS verification is forbidden")

    service = object.__new__(ForgejoToolService)
    service.settings = Settings(
        environment="test",
        forgejo_allowed_base_urls=["https://git.example.test"],
    )
    service.instances = FakeInstances()  # type: ignore[assignment]
    service.credentials = UnexpectedCredentials()  # type: ignore[assignment]

    with pytest.raises(ConfigurationUnavailable, match="unverified TLS"):
        await service._connection(uuid.uuid4())


def test_mcp_rejects_browser_origins_unless_explicitly_allowed() -> None:
    default_app = create_app(Settings(environment="test"))
    allowed_app = create_app(
        Settings(environment="test", mcp_allowed_origins=["https://CLIENT.example:443/"])
    )
    with TestClient(default_app) as client:
        rejected = client.post("/mcp", headers={"Origin": "https://client.example"}, json={})
    with TestClient(allowed_app) as client:
        authenticated_later = client.post(
            "/mcp", headers={"Origin": "https://client.example"}, json={}
        )
        preflight = client.options(
            "/mcp",
            headers={
                "Origin": "https://client.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": (
                    "authorization,content-type,mcp-protocol-version,mcp-session-id"
                ),
            },
        )
    assert rejected.status_code == 403
    assert rejected.headers["vary"] == "Origin"
    assert authenticated_later.status_code == 401
    assert authenticated_later.headers["access-control-allow-origin"] == ("https://client.example")
    assert "Origin" in authenticated_later.headers["vary"]
    assert authenticated_later.headers["access-control-expose-headers"] == (
        "WWW-Authenticate, MCP-Session-Id"
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "https://client.example"
    assert "POST" in preflight.headers["access-control-allow-methods"]
    assert "authorization" in preflight.headers["access-control-allow-headers"].lower()
    assert "mcp-session-id" in preflight.headers["access-control-allow-headers"].lower()


def test_security_headers_disable_caching_and_browser_embedding() -> None:
    app = create_app(Settings(environment="test"))
    with TestClient(app) as client:
        response = client.get("/api/auth/me")
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_metrics_endpoint_exposes_service_and_database_metrics() -> None:
    app = create_app(Settings(environment="test"))
    with TestClient(app) as client:
        response = client.get("/metrics")
    assert response.status_code == 200
    assert "forgejo_mcp_http_requests_total" in response.text
    assert "forgejo_mcp_db_pool_checked_out_connections" in response.text


def test_multi_scope_rate_limiter_rejects_without_charging_other_scope() -> None:
    limiter = MultiScopeRateLimiter(window_seconds=60)
    assert limiter.check([("token", "a", 1), ("user", "u", 2)]).allowed
    denied = limiter.check([("token", "a", 1), ("user", "u", 2)])
    assert denied.allowed is False
    assert denied.scope == "token"
    assert denied.retry_after_seconds >= 1
    assert limiter.check([("token", "b", 1), ("user", "u", 2)]).allowed


def test_rate_limiters_bound_key_storage_and_reserve_attempts() -> None:
    login_limiter = LoginRateLimiter(max_keys=2)
    first = login_limiter.check("a")
    second = login_limiter.check("b")
    login_limiter.failure(first)
    login_limiter.failure(second)
    with pytest.raises(HTTPException, match="capacity exceeded"):
        login_limiter.check("c")
    login_limiter.success(first)
    assert login_limiter.check("c").key == "c"

    multi_limiter = MultiScopeRateLimiter(window_seconds=60, max_keys=2)
    assert multi_limiter.check([("ip", "a", 5)]).allowed
    assert multi_limiter.check([("ip", "b", 5)]).allowed
    decision = multi_limiter.check([("ip", "c", 5)])
    assert decision.allowed is False
    assert decision.scope == "capacity"


def test_login_rate_limiter_reserves_concurrent_attempts_atomically() -> None:
    limiter = LoginRateLimiter(attempts=5)

    def attempt(_index: int) -> bool:
        try:
            limiter.check("same-key")
        except HTTPException:
            return False
        return True

    with ThreadPoolExecutor(max_workers=10) as pool:
        accepted = list(pool.map(attempt, range(10)))

    assert sum(accepted) == 5


async def test_invocation_coordinator_drains_and_rejects_new_work() -> None:
    coordinator = InvocationCoordinator()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def invocation() -> None:
        async with coordinator.invocation():
            entered.set()
            await release.wait()

    task = asyncio.create_task(invocation())
    await entered.wait()
    await coordinator.begin_shutdown()
    assert coordinator.accepting is False
    assert await coordinator.wait_for_idle(0.01) is False
    with pytest.raises(ServiceShuttingDown):
        async with coordinator.invocation():
            pass
    release.set()
    await task
    assert await coordinator.wait_for_idle(0.1) is True


async def test_forgejo_retries_safe_requests_but_not_writes() -> None:
    get_attempts = 0

    def safe_handler(_request: httpx.Request) -> httpx.Response:
        nonlocal get_attempts
        get_attempts += 1
        if get_attempts < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"version": "16.0.2"})

    safe_client = ForgejoClient(
        connect_timeout_seconds=1,
        safe_retry_attempts=2,
        retry_max_delay_seconds=0,
        transport=httpx.MockTransport(safe_handler),
    )
    assert (
        await safe_client.get_version(base_url="https://git.example.test", verify_tls=True)
    ).version == "16.0.2"
    assert get_attempts == 3

    write_attempts = 0

    def write_handler(_request: httpx.Request) -> httpx.Response:
        nonlocal write_attempts
        write_attempts += 1
        return httpx.Response(503)

    write_client = ForgejoClient(
        connect_timeout_seconds=1,
        safe_retry_attempts=3,
        retry_max_delay_seconds=0,
        transport=httpx.MockTransport(write_handler),
    )
    with pytest.raises(ExternalServiceUnavailable, match="HTTP 503"):
        await write_client.create_issue(
            base_url="https://git.example.test",
            token="pat",
            verify_tls=True,
            owner="owner",
            repo="repo",
            title="Issue",
            body=None,
            assignees=None,
            label_ids=None,
            milestone_id=None,
        )
    assert write_attempts == 1


async def test_forgejo_retries_rate_limits_and_read_timeouts_for_get_only() -> None:
    responses: list[str] = ["timeout", "rate_limit", "success"]

    def handler(request: httpx.Request) -> httpx.Response:
        response = responses.pop(0)
        if response == "timeout":
            raise httpx.ReadTimeout("slow Forgejo", request=request)
        if response == "rate_limit":
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"version": "16.0.2"})

    client = ForgejoClient(
        connect_timeout_seconds=1,
        read_timeout_seconds=2,
        write_timeout_seconds=3,
        pool_timeout_seconds=4,
        safe_retry_attempts=2,
        retry_max_delay_seconds=0,
        transport=httpx.MockTransport(handler),
    )
    assert (
        await client.get_version(base_url="https://git.example.test", verify_tls=True)
    ).version == "16.0.2"
    assert responses == []
    assert client.timeout.connect == 1
    assert client.timeout.read == 2
    assert client.timeout.write == 3
    assert client.timeout.pool == 4


async def test_forgejo_response_is_bounded_while_streaming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(forgejo_client_module, "MAX_FORGEJO_RESPONSE_BYTES", 16)
    client = ForgejoClient(
        connect_timeout_seconds=1,
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=b"x" * 17)),
    )
    with pytest.raises(ExternalServiceUnavailable, match="too large"):
        await client.get_version(base_url="https://git.example.test", verify_tls=True)


async def test_commit_changes_enforces_file_count_and_combined_size() -> None:
    client = ForgejoClient(
        connect_timeout_seconds=1,
        commit_max_files=2,
        commit_max_total_bytes=5,
        transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
    )
    common = {
        "base_url": "https://git.example.test",
        "token": "pat",
        "verify_tls": True,
        "owner": "owner",
        "repo": "repo",
        "branch": "main",
        "new_branch": None,
        "message": "change",
        "signoff": False,
    }
    with pytest.raises(ValidationFailed, match="between 1 and 2"):
        await client.commit_changes(
            **common,
            changes=[
                {"operation": "create", "path": f"{index}.txt", "content": "x"}
                for index in range(3)
            ],
        )
    with pytest.raises(ValidationFailed, match="combined"):
        await client.commit_changes(
            **common,
            changes=[{"operation": "create", "path": "a.txt", "content": "123456"}],
        )


def test_json_logs_include_correlation_fields() -> None:
    formatter = JsonFormatter()
    token = set_request_id("request-123")
    try:
        payload = json.loads(
            formatter.format(
                logging.LogRecord(
                    name="test",
                    level=logging.INFO,
                    pathname=__file__,
                    lineno=1,
                    msg="completed",
                    args=(),
                    exc_info=None,
                )
            )
        )
    finally:
        reset_request_id(token)
    assert payload["message"] == "completed"
    assert payload["request_id"] == "request-123"
    assert payload["user_id"] is None
    assert payload["invocation_id"] is None


def test_json_logs_redact_credentials_in_messages_and_nested_extras() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=(
            "failed Bearer fmcp_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQ "
            "postgresql://user:database-password@db.example/test"
        ),
        args=(),
        exc_info=None,
    )
    record.context = {
        "authorization": "token forgejo-pat-value",
        "nested": {"database_url": "postgresql://user:secret@db/test"},
    }
    rendered = formatter.format(record)
    assert "database-password" not in rendered
    assert "forgejo-pat-value" not in rendered
    assert "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQ" not in rendered
    payload = json.loads(rendered)
    assert payload["context"]["authorization"] == "[REDACTED]"
    assert payload["context"]["nested"]["database_url"] == "[REDACTED]"
