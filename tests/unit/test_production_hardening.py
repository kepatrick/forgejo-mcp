import asyncio
import json
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from forgejo_mcp.application.errors import ExternalServiceUnavailable, ValidationFailed
from forgejo_mcp.application.runtime import InvocationCoordinator, ServiceShuttingDown
from forgejo_mcp.auth.rate_limit import MultiScopeRateLimiter
from forgejo_mcp.config import Settings
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
