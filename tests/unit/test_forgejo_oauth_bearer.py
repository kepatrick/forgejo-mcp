import httpx
import pytest

from forgejo_mcp.forgejo.client import ForgejoClient, ForgejoOAuthToken


@pytest.mark.parametrize(
    "token,scheme", [("pat-secret", "token"), (ForgejoOAuthToken("oauth-secret"), "Bearer")]
)
async def test_forgejo_client_uses_correct_authentication_scheme(token, scheme):
    def handler(request):
        assert request.headers["Authorization"] == f"{scheme} {token}"
        return httpx.Response(200, json={"id": 42, "login": "OAuthUser"})

    client = ForgejoClient(connect_timeout_seconds=2, transport=httpx.MockTransport(handler))
    principal = await client.get_current_user(
        base_url="https://git.example.test", token=token, verify_tls=True
    )
    assert principal.id == 42
