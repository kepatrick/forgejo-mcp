import httpx
import pytest
from starlette.responses import Response

from forgejo_mcp.observability.middleware import SecurityHeadersMiddleware


@pytest.mark.parametrize(
    ("path", "method", "status", "origin", "expected"),
    [
        ("/oauth/consent", "GET", 200, "https://client.example", True),
        ("/oauth/consent", "GET", 200, "http://127.0.0.1:4321", True),
        ("/oauth/consent", "GET", 200, "http://[::1]:4321", True),
        ("/oauth/consent", "GET", 200, "https://client.example; script-src *", False),
        ("/oauth/consent", "GET", 200, "https://*.example", False),
        ("/oauth/consent", "GET", 200, None, False),
        ("/oauth/consent", "POST", 302, "https://client.example", False),
        ("/oauth/consent", "GET", 403, "https://client.example", False),
        ("/", "GET", 200, "https://client.example", False),
    ],
)
async def test_callback_csp_is_narrowly_scoped(path, method, status, origin, expected):
    async def endpoint(scope, receive, send):
        scope.setdefault("state", {})["oauth_consent_callback_origin"] = origin
        # Middleware must still override arbitrary endpoint CSP headers.
        await Response(status_code=status, headers={"Content-Security-Policy": "default-src *"})(
            scope, receive, send
        )

    app = SecurityHeadersMiddleware(endpoint)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="https://mcp.example"
    ) as client:
        response = await client.request(method, path)
    csp = response.headers["content-security-policy"]
    assert f"form-action 'self'{(' ' + origin) if expected else ''};" in csp
    assert "script-src 'self';" in csp
    assert "frame-ancestors 'none';" in csp
