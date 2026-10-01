"""Admin-managed OAuth client configuration; database settings override environment."""

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, NoReturn
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from forgejo_mcp.application.errors import ConfigurationUnavailable, Conflict, ValidationFailed
from forgejo_mcp.config import Settings, normalize_http_origin
from forgejo_mcp.credentials import CredentialCipher, CredentialKeyError
from forgejo_mcp.db.models import ForgejoOAuthConfiguration
from forgejo_mcp.db.repositories import AuditRepository
from forgejo_mcp.forgejo.oauth import FORGEJO_OAUTH_CALLBACK_PATH, ForgejoOAuthClientConfiguration

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PublicForgejoOAuthConfiguration:
    enabled: bool
    client_id: str
    base_url: str
    redirect_url: str
    client_type: Literal["public", "confidential"]
    secret_configured: bool
    source: Literal["dashboard", "environment", "unconfigured"]


class ForgejoOAuthConfigService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def record(
        self, *, lock: bool = False, shared: bool = False
    ) -> ForgejoOAuthConfiguration | None:
        query = (
            select(ForgejoOAuthConfiguration)
            .where(ForgejoOAuthConfiguration.slug == "primary")
            .execution_options(populate_existing=True)
        )
        if lock:
            query = query.with_for_update(read=shared)
        result: ForgejoOAuthConfiguration | None = await self.session.scalar(query)
        return result

    def cipher(self) -> CredentialCipher:
        try:
            if self.settings.credential_encryption_key_file is None:
                raise CredentialKeyError("credential key unavailable")
            return CredentialCipher.from_file(
                self.settings.credential_encryption_key_file,
                self.settings.credential_encryption_key_version,
            )
        except CredentialKeyError as error:
            logger.warning(
                "forgejo_oauth_config_key_unavailable", extra={"error_type": type(error).__name__}
            )
            raise ConfigurationUnavailable(
                "OAuth client secret encryption key is unavailable"
            ) from error

    @staticmethod
    def reject(reason: str, message: str) -> NoReturn:
        logger.warning("forgejo_oauth_config_rejected", extra={"reason": reason})
        raise ValidationFailed(message)

    async def public(self) -> PublicForgejoOAuthConfiguration:
        record = await self.record()
        if record is not None:
            return PublicForgejoOAuthConfiguration(
                record.enabled,
                record.client_id,
                record.base_url,
                record.base_url + FORGEJO_OAUTH_CALLBACK_PATH,
                "confidential" if record.client_type == "confidential" else "public",
                record.encrypted_secret is not None
                and record.nonce is not None
                and record.key_version is not None,
                "dashboard",
            )
        redirect = self.settings.forgejo_oauth_redirect_url
        if self.settings.forgejo_oauth_client_id and redirect:
            parts = urlsplit(redirect)
            base_url = normalize_http_origin(f"{parts.scheme}://{parts.netloc}")
            return PublicForgejoOAuthConfiguration(
                True,
                self.settings.forgejo_oauth_client_id,
                base_url,
                redirect,
                "confidential" if self.settings.forgejo_oauth_client_secret_file else "public",
                self.settings.forgejo_oauth_client_secret_file is not None,
                "environment",
            )
        return PublicForgejoOAuthConfiguration(
            False, "", "", "", "confidential", False, "unconfigured"
        )

    @staticmethod
    def read_secret_file(path: Path) -> SecretStr:
        try:
            value = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as error:
            logger.warning(
                "forgejo_oauth_config_secret_unavailable",
                extra={"error_type": type(error).__name__},
            )
            raise ConfigurationUnavailable(
                "Forgejo OAuth client secret file is unavailable"
            ) from error
        if not value or len(value) > 4096:
            logger.warning(
                "forgejo_oauth_config_secret_unavailable", extra={"reason": "invalid_secret_file"}
            )
            raise ConfigurationUnavailable("Forgejo OAuth client secret file is invalid")
        return SecretStr(value)

    async def resolve(self, *, lock: bool = False) -> ForgejoOAuthClientConfiguration | None:
        # Share read locks between users; configuration writes remain exclusive.
        record = await self.record(lock=lock, shared=True)
        if record is not None:
            if not record.enabled:
                return None  # Explicit disable overrides even configured deployment variables.
            secret = None
            if record.client_type == "confidential":
                if (
                    record.encrypted_secret is None
                    or record.nonce is None
                    or record.key_version is None
                ):
                    logger.warning(
                        "forgejo_oauth_config_secret_unavailable",
                        extra={"reason": "missing_stored_secret"},
                    )
                    raise ConfigurationUnavailable("Forgejo OAuth client secret is not configured")
                try:
                    secret = SecretStr(
                        self.cipher().decrypt(
                            ciphertext=record.encrypted_secret,
                            nonce=record.nonce,
                            user_id=record.id,
                            key_version=record.key_version,
                            purpose="oauth-client-secret",
                        )
                    )
                except CredentialKeyError as error:
                    logger.warning(
                        "forgejo_oauth_config_secret_unavailable",
                        extra={"error_type": type(error).__name__},
                    )
                    raise ConfigurationUnavailable(
                        "Forgejo OAuth client secret cannot be decrypted"
                    ) from error
            return ForgejoOAuthClientConfiguration(
                record.client_id,
                record.base_url + FORGEJO_OAUTH_CALLBACK_PATH,
                secret,
                record.revision.hex,
            )
        if (
            not self.settings.forgejo_oauth_client_id
            or not self.settings.forgejo_oauth_redirect_url
        ):
            return None
        secret_file = self.settings.forgejo_oauth_client_secret_file
        return ForgejoOAuthClientConfiguration(
            self.settings.forgejo_oauth_client_id,
            self.settings.forgejo_oauth_redirect_url,
            self.read_secret_file(secret_file) if secret_file else None,
            "environment",
        )

    async def save(
        self,
        *,
        actor_account_id: uuid.UUID,
        enabled: bool,
        client_id: str,
        base_url: str,
        client_type: Literal["public", "confidential"],
        client_secret: SecretStr | None,
    ) -> PublicForgejoOAuthConfiguration:
        try:
            origin = str(httpx.URL(normalize_http_origin(base_url))).rstrip("/")
        except (ValueError, httpx.InvalidURL):
            self.reject(
                "invalid_base_url",
                "MCP public base URL must contain only scheme and host/port, "
                "with no path, credentials, query or fragment",
            )
        if origin.startswith("http://") and (
            self.settings.environment == "production"
            or urlsplit(origin).hostname not in {"localhost", "127.0.0.1", "::1"}
        ):
            self.reject(
                "insecure_base_url",
                "Use an HTTPS MCP public base URL; HTTP is allowed only "
                "for local non-production testing",
            )
        client_id = client_id.strip()
        if (enabled and not client_id) or (
            client_id
            and (not client_id.isascii() or any(ord(c) <= 32 or ord(c) >= 127 for c in client_id))
        ):
            self.reject(
                "invalid_client_id", "A valid Client ID is required to enable Forgejo OAuth"
            )
        secret = client_secret.get_secret_value() if client_secret else ""
        if len(secret) > 4096 or (
            secret and (not secret.isascii() or any(ord(c) <= 32 or ord(c) >= 127 for c in secret))
        ):
            self.reject("invalid_secret", "Client secret is invalid")
        if secret and not client_id:
            self.reject("invalid_client_id", "A Client ID is required when saving a client secret")
        if client_type == "public" and secret:
            self.reject("public_client_secret", "Public clients use PKCE without a client secret")
        record = await self.record(lock=True)
        current_id = record.client_id if record else self.settings.forgejo_oauth_client_id
        if (
            client_type == "confidential"
            and enabled
            and not secret
            and record is None
            and current_id == client_id
            and self.settings.forgejo_oauth_client_secret_file
        ):
            secret = self.read_secret_file(
                self.settings.forgejo_oauth_client_secret_file
            ).get_secret_value()
        if (
            client_type == "confidential"
            and enabled
            and not secret
            and (
                record is None
                or record.encrypted_secret is None
                or record.nonce is None
                or record.key_version is None
                or current_id != client_id
            )
        ):
            self.reject(
                "missing_secret",
                "Enter a client secret for this confidential Client ID, or choose public client",
            )
        if record is None:
            record = ForgejoOAuthConfiguration(
                id=uuid.uuid4(), slug="primary", updated_by_account_id=actor_account_id
            )
            self.session.add(record)
        if client_type == "public" or current_id != client_id:
            record.encrypted_secret = record.nonce = None
            record.key_version = None
        if secret:
            encrypted = self.cipher().encrypt(secret, record.id, purpose="oauth-client-secret")
            record.encrypted_secret, record.nonce, record.key_version = (
                encrypted.ciphertext,
                encrypted.nonce,
                encrypted.key_version,
            )
        record.enabled, record.client_id, record.base_url, record.client_type = (
            enabled,
            client_id,
            origin,
            client_type,
        )
        record.updated_by_account_id = actor_account_id
        record.revision = uuid.uuid4()
        AuditRepository(self.session).record(
            actor_account_id=actor_account_id,
            action="forgejo_oauth.configuration_updated",
            target_type="forgejo_oauth_configuration",
            target_id=str(record.id),
            details={
                "enabled": enabled,
                "client_type": client_type,
                "base_url": origin,
                "client_id_changed": current_id != client_id,
                "secret_replaced": bool(secret),
            },
        )
        try:
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            logger.warning(
                "forgejo_oauth_config_save_conflict", extra={"account_id": str(actor_account_id)}
            )
            raise Conflict(
                "OAuth configuration changed concurrently; reload and try again"
            ) from error
        logger.info(
            "forgejo_oauth_configuration_updated",
            extra={"account_id": str(actor_account_id), "enabled": enabled},
        )
        return await self.public()
