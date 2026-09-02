import asyncio

import httpx
import pytest
from mcp.server.auth.provider import RegistrationError

from forgejo_mcp.application.oauth_service import OAuthService
from forgejo_mcp.config import Settings


def oauth_settings() -> Settings:
    return Settings(
        environment="test",
        oauth_enabled=True,
        oauth_issuer_url="https://mcp.example.test",
        oauth_resource_url="https://mcp.example.test/mcp",
        oauth_cimd_allowed_origins=["https://claude.ai"],
    )


def test_cimd_url_is_exactly_origin_allowlisted() -> None:
    service = OAuthService(lambda: None, oauth_settings())  # type: ignore[arg-type]
    assert service._is_allowed_cimd_url("https://claude.ai/oauth/client.json")
    assert not service._is_allowed_cimd_url("https://attacker.example/client.json")
    assert not service._is_allowed_cimd_url("https://claude.ai.attacker.example/client.json")
    assert not service._is_allowed_cimd_url("https://user@claude.ai/client.json")
    assert not service._is_allowed_cimd_url("https://claude.ai/client.json?redirect=evil")


async def fetch_cimd(response: httpx.Response):
    async def handler(_request: httpx.Request) -> httpx.Response:
        return response

    service = OAuthService(
        lambda: None,  # type: ignore[arg-type]
        oauth_settings(),
        transport=httpx.MockTransport(handler),
        resolver=lambda _host, _port: {"93.184.216.34"},
    )
    return await service._fetch_cimd("https://claude.ai/oauth/client.json")


def test_cimd_fetch_accepts_bounded_public_client_metadata() -> None:
    response = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        json={
            "client_id": "https://claude.ai/oauth/client.json",
            "client_name": "Claude",
            "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        },
    )
    client = asyncio.run(fetch_cimd(response))
    assert client.client_id == "https://claude.ai/oauth/client.json"
    assert client.token_endpoint_auth_method == "none"
    assert client.scope == "mcp:tools"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"location": "https://attacker.example/client.json"}),
        httpx.Response(200, headers={"content-type": "text/html"}, text="not json"),
        httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=b"x" * 70000,
        ),
    ],
)
def test_cimd_fetch_rejects_redirects_non_json_and_oversize(response: httpx.Response) -> None:
    with pytest.raises(RegistrationError):
        asyncio.run(fetch_cimd(response))


def test_cimd_fetch_rejects_private_dns_resolution() -> None:
    service = OAuthService(
        lambda: None,  # type: ignore[arg-type]
        oauth_settings(),
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={})),
        resolver=lambda _host, _port: {"127.0.0.1"},
    )
    with pytest.raises(RegistrationError, match="not public"):
        asyncio.run(service._fetch_cimd("https://claude.ai/oauth/client.json"))
