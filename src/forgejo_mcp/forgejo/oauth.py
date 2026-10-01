"""Bounded, no-retry OAuth token exchange against the configured Forgejo only."""

import logging
from dataclasses import dataclass
from typing import Literal

import httpx
from pydantic import BaseModel, Field, SecretStr, ValidationError, field_validator

from forgejo_mcp.application.errors import (
    ConfigurationUnavailable,
    ExternalServiceUnavailable,
    ValidationFailed,
)
from forgejo_mcp.config import Settings

logger = logging.getLogger(__name__)
MAX_TOKEN_RESPONSE_BYTES = 64 * 1024
FORGEJO_OAUTH_CALLBACK_PATH = "/api/me/credential/oauth/callback"


@dataclass(frozen=True)
class ForgejoOAuthClientConfiguration:
    client_id: str
    redirect_url: str
    client_secret: SecretStr | None
    revision: str


class ForgejoOAuthTokens(BaseModel):
    access_token: SecretStr = Field(min_length=1, max_length=8192)
    refresh_token: SecretStr = Field(min_length=1, max_length=8192)
    token_type: Literal["bearer"]
    expires_in: int = Field(strict=True, ge=1, le=365 * 86400)

    @field_validator("token_type", mode="before")
    @classmethod
    def normalize_type(cls, value: object) -> object:
        return value.lower() if isinstance(value, str) else value

    @field_validator("access_token", "refresh_token")
    @classmethod
    def validate_token(cls, value: SecretStr) -> SecretStr:
        token = value.get_secret_value()
        if not token.isascii() or any(ord(c) <= 32 or ord(c) >= 127 for c in token):
            raise ValueError("invalid OAuth token encoding")
        return value


class ForgejoOAuthClient:
    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.settings = settings
        self.transport = transport

    async def exchange(
        self,
        *,
        base_url: str,
        verify_tls: bool,
        values: dict[str, str],
        configuration: ForgejoOAuthClientConfiguration | None = None,
    ) -> ForgejoOAuthTokens:
        if not self.settings.permits_forgejo_base_url(base_url):
            logger.warning(
                "forgejo_oauth_exchange_rejected", extra={"reason": "untrusted_instance"}
            )
            raise ConfigurationUnavailable("Forgejo OAuth instance is not allowlisted")
        if not verify_tls and not self.settings.allow_unverified_forgejo_tls:
            logger.warning("forgejo_oauth_exchange_rejected", extra={"reason": "tls_policy"})
            raise ConfigurationUnavailable("Forgejo OAuth requires verified TLS")
        if not base_url.startswith("https://") and not self.settings.allow_insecure_forgejo_http:
            logger.warning("forgejo_oauth_exchange_rejected", extra={"reason": "http_policy"})
            raise ConfigurationUnavailable("Forgejo OAuth requires HTTPS")
        data = {
            **values,
            "client_id": configuration.client_id
            if configuration
            else self.settings.forgejo_oauth_client_id or "",
        }
        if configuration is not None and configuration.client_secret is not None:
            data["client_secret"] = configuration.client_secret.get_secret_value()
        # Explicit database public-client settings must never inherit an environment secret.
        secret_file = (
            self.settings.forgejo_oauth_client_secret_file if configuration is None else None
        )
        if secret_file is not None:
            try:
                secret = secret_file.read_text(encoding="utf-8").strip()
            except OSError as error:
                logger.warning(
                    "forgejo_oauth_exchange_rejected", extra={"reason": "secret_unavailable"}
                )
                raise ConfigurationUnavailable(
                    "Forgejo OAuth client secret is unavailable"
                ) from error
            if not secret or len(secret) > 4096:
                logger.warning(
                    "forgejo_oauth_exchange_rejected", extra={"reason": "secret_invalid"}
                )
                raise ConfigurationUnavailable("Forgejo OAuth client secret is invalid")
            data["client_secret"] = secret
        timeout = httpx.Timeout(
            connect=self.settings.forgejo_connect_timeout_seconds,
            read=self.settings.forgejo_read_timeout_seconds,
            write=self.settings.forgejo_write_timeout_seconds,
            pool=self.settings.forgejo_pool_timeout_seconds,
        )
        try:
            async with (
                httpx.AsyncClient(
                    verify=verify_tls,
                    timeout=timeout,
                    follow_redirects=False,
                    trust_env=False,
                    transport=self.transport,
                ) as client,
                client.stream(
                    "POST",
                    base_url + "/login/oauth/access_token",
                    data=data,
                    headers={"Accept": "application/json", "Accept-Encoding": "identity"},
                ) as response,
            ):
                if response.status_code != 200:
                    logger.warning(
                        "forgejo_oauth_exchange_rejected",
                        extra={"status_code": response.status_code},
                    )
                    if response.status_code in {400, 401, 403}:
                        raise ValidationFailed(
                            "Forgejo authorization expired or was rejected; reconnect"
                        )
                    raise ExternalServiceUnavailable("Forgejo OAuth token endpoint is unavailable")
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise ValueError("compressed token response")
                body = bytearray()
                async for chunk in response.aiter_raw():
                    if len(body) + len(chunk) > MAX_TOKEN_RESPONSE_BYTES:
                        raise ValueError("token response too large")
                    body.extend(chunk)
                return ForgejoOAuthTokens.model_validate_json(body)
        except httpx.HTTPError as error:
            # HTTP error details may contain codes/tokens. Never log the exception body or URL.
            logger.warning(
                "forgejo_oauth_exchange_failed", extra={"error_type": type(error).__name__}
            )
            raise ExternalServiceUnavailable("Forgejo OAuth could not be reached") from error
        except (ValueError, ValidationError) as error:
            logger.warning(
                "forgejo_oauth_response_rejected", extra={"error_type": type(error).__name__}
            )
            # Pydantic's original exception can embed plaintext response tokens.
            raise ExternalServiceUnavailable(
                "Forgejo OAuth returned an invalid token response"
            ) from None
