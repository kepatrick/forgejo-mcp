import base64
import logging
import uuid
from urllib.parse import parse_qs

import httpx
import pytest

from forgejo_mcp.application.errors import (
    ConfigurationUnavailable,
    ExternalServiceUnavailable,
    ValidationFailed,
)
from forgejo_mcp.config import Settings
from forgejo_mcp.credentials import CredentialCipher, CredentialKeyError
from forgejo_mcp.forgejo.oauth import ForgejoOAuthClient
from forgejo_mcp.observability.logging import OAuthCallbackAccessFilter


def settings(**kwargs):
    return Settings(
        environment="test", forgejo_allowed_base_urls=["https://git.example.test"], **kwargs
    )


async def test_token_exchange_is_bounded_and_uses_secret_file(tmp_path):
    secret = tmp_path / "secret"
    secret.write_text("client-secret")
    cfg = settings(
        forgejo_oauth_client_id="client",
        forgejo_oauth_redirect_url="https://mcp.example/api/me/credential/oauth/callback",
        forgejo_oauth_client_secret_file=secret,
    )
    seen = []

    def handler(request):
        seen.append(request)
        body = parse_qs(request.content.decode())
        assert body["client_id"] == ["client"]
        assert body["client_secret"] == ["client-secret"]
        assert request.url.path == "/login/oauth/access_token"
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(
            200,
            stream=httpx.ByteStream(
                b'{"access_token":"access-secret","refresh_token":"refresh-secret","token_type":"Bearer","expires_in":3600}'
            ),
        )

    tokens = await ForgejoOAuthClient(cfg, transport=httpx.MockTransport(handler)).exchange(
        base_url="https://git.example.test",
        verify_tls=True,
        values={"grant_type": "refresh_token", "refresh_token": "old-secret"},
    )
    assert tokens.access_token.get_secret_value() == "access-secret"
    assert "access-secret" not in repr(tokens)
    assert len(seen) == 1


@pytest.mark.parametrize(
    "status,body,headers",
    [
        (302, b"", {"location": "https://attacker.example"}),
        (400, b'{"error":"secret-rejected"}', {}),
        (200, b"x" * 65537, {}),
        (200, b"invalid secret-body", {}),
        (200, b"gzip", {"content-encoding": "gzip"}),
        (
            200,
            b'{"access_token":"secret-access","refresh_token":"secret-refresh","token_type":"Bearer","expires_in":0}',
            {},
        ),
    ],
)
async def test_rejected_response_is_never_retried_or_logged(status, body, headers, caplog):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(status, stream=httpx.ByteStream(body), headers=headers)

    with pytest.raises((ExternalServiceUnavailable, ValidationFailed)):
        await ForgejoOAuthClient(settings(), transport=httpx.MockTransport(handler)).exchange(
            base_url="https://git.example.test",
            verify_tls=True,
            values={"code": "private-code"},
        )
    assert len(seen) == 1
    assert "secret-body" not in caplog.text and "private-code" not in caplog.text
    assert "secret-access" not in caplog.text and "secret-rejected" not in caplog.text


async def test_allowlist_prevents_network_access():
    def forbidden(request):
        pytest.fail("untrusted token destination was contacted")

    with pytest.raises(ConfigurationUnavailable):
        await ForgejoOAuthClient(settings(), transport=httpx.MockTransport(forbidden)).exchange(
            base_url="https://attacker.example",
            verify_tls=True,
            values={},
        )


def test_encryption_purposes_cannot_be_interchanged():
    cipher = CredentialCipher(base64.b64decode(base64.b64encode(b"k" * 32)), 1)
    user_id = uuid.uuid4()
    secret = cipher.encrypt("refresh-secret", user_id, purpose="oauth-refresh")
    with pytest.raises(CredentialKeyError):
        cipher.decrypt(
            ciphertext=secret.ciphertext, nonce=secret.nonce, user_id=user_id, key_version=1
        )


def test_uvicorn_callback_logs_never_include_query_credentials():
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s - "%s %s HTTP/%s" %s',
        (
            "client",
            "GET",
            "/api/me/credential/oauth/callback?code=private-code&state=private-state",
            "1.1",
            303,
        ),
        None,
    )
    OAuthCallbackAccessFilter().filter(record)
    assert "private-code" not in record.getMessage()
    assert "private-state" not in record.getMessage()
    assert "/api/me/credential/oauth/callback" in record.getMessage()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"forgejo_oauth_client_id": "client"},
        {"forgejo_oauth_redirect_url": "https://mcp.example/api/me/credential/oauth/callback"},
        {
            "forgejo_oauth_client_id": "client",
            "forgejo_oauth_redirect_url": "https://mcp.example/wrong",
        },
    ],
)
def test_partial_or_wrong_callback_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        settings(**kwargs)
