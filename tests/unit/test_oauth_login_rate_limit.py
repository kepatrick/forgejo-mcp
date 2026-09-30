from unittest.mock import AsyncMock, MagicMock

from starlette.applications import Starlette
from starlette.testclient import TestClient

from forgejo_mcp.api import oauth
from forgejo_mcp.application.errors import AuthenticationFailed
from forgejo_mcp.application.oauth_service import OAuthService
from forgejo_mcp.auth.oauth_rate_limit import LoginRateLimiter
from forgejo_mcp.config import Settings


def test_equivalent_usernames_share_oauth_login_limit(monkeypatch) -> None:
    issuer = "https://mcp.example.test"
    settings = Settings(
        oauth_enabled=True,
        oauth_issuer_url=issuer,
        oauth_resource_url=f"{issuer}/mcp",
    )
    service = MagicMock(spec=OAuthService)
    service.issuer_url = issuer
    service.resource_url = f"{issuer}/mcp"
    service.consent_details = AsyncMock(return_value=object())
    login = AsyncMock(side_effect=AuthenticationFailed("invalid credentials"))
    monkeypatch.setattr(oauth.AuthService, "login", login)
    monkeypatch.setattr(oauth, "_oauth_login_limiter", LoginRateLimiter())
    app = Starlette(routes=oauth.create_oauth_routes(service, settings))
    app.state.db_session_factory = MagicMock(return_value=AsyncMock())

    with TestClient(app, base_url=issuer) as client:
        client.cookies.set(oauth.OAUTH_CSRF_COOKIE, "test-csrf")

        def attempt(username: str) -> int:
            return client.post(
                "/oauth/login",
                headers={"Origin": issuer},
                data={
                    "request": "test-interaction",
                    "username": username,
                    "password": "wrong-password",
                    "csrf": "test-csrf",
                },
            ).status_code

        assert [attempt("oauth-user") for _ in range(5)] == [401] * 5
        for equivalent in (
            "oauth-user",
            " oauth-user",
            "oauth-user ",
            "OAUTH-USER",
            "ｏａｕｔｈ-user",
        ):
            assert attempt(equivalent) == 429
        assert login.await_count == 5  # Throttled aliases never reach password verification.
        assert attempt("different-user") == 401
        assert login.await_count == 6
