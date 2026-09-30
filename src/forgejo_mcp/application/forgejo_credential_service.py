import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from forgejo_mcp.application.errors import (
    ConfigurationUnavailable,
    Conflict,
    NotFound,
    ValidationFailed,
)
from forgejo_mcp.auth.passwords import normalize_username
from forgejo_mcp.config import Settings
from forgejo_mcp.credentials import CredentialCipher, CredentialKeyError
from forgejo_mcp.db.models import CredentialStatus, ForgejoCredential, RecordStatus, User
from forgejo_mcp.db.repositories import (
    AuditRepository,
    ForgejoCredentialRepository,
    ForgejoInstanceRepository,
    UserRepository,
)
from forgejo_mcp.forgejo.client import ForgejoClient, ForgejoOAuthToken
from forgejo_mcp.forgejo.oauth import ForgejoOAuthTokens

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VerifiedForgejoPrincipal:
    user_id: int
    username: str


class ForgejoCredentialService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.audit = AuditRepository(session)
        self.credentials = ForgejoCredentialRepository(session)
        self.instances = ForgejoInstanceRepository(session)
        self.users = UserRepository(session)
        self.client = ForgejoClient(
            connect_timeout_seconds=settings.forgejo_connect_timeout_seconds,
            read_timeout_seconds=settings.forgejo_read_timeout_seconds,
            write_timeout_seconds=settings.forgejo_write_timeout_seconds,
            pool_timeout_seconds=settings.forgejo_pool_timeout_seconds,
            safe_retry_attempts=settings.forgejo_safe_retry_attempts,
            retry_max_delay_seconds=settings.forgejo_retry_max_delay_seconds,
            commit_max_files=settings.commit_max_files,
            commit_max_total_bytes=settings.commit_max_total_bytes,
            migration_allow_private_hosts=settings.migration_allow_private_hosts,
        )

    def cipher(self) -> CredentialCipher:
        key_file = self.settings.credential_encryption_key_file
        if key_file is None:
            raise ConfigurationUnavailable("credential encryption key is not configured")
        try:
            return CredentialCipher.from_file(
                key_file,
                self.settings.credential_encryption_key_version,
            )
        except CredentialKeyError as error:
            raise ConfigurationUnavailable(str(error)) from error

    async def get_user(self, user_id: uuid.UUID) -> User:
        user = await self.users.get(user_id)
        if user is None:
            raise NotFound("user not found")
        return user

    async def active_for_user(self, user_id: uuid.UUID) -> ForgejoCredential | None:
        return await self.credentials.active_for_user(user_id)

    async def verify(
        self,
        *,
        actor_account_id: uuid.UUID,
        user_id: uuid.UUID,
        token: str,
        oauth: bool = False,
    ) -> VerifiedForgejoPrincipal:
        normalized_token = token.strip()
        if not normalized_token or len(normalized_token) > (8192 if oauth else 2048):
            raise ValidationFailed("Forgejo credential is invalid")
        user = await self.get_user(user_id)
        if user.status != RecordStatus.ACTIVE:
            logger.warning(
                "forgejo_credential_verification_rejected",
                extra={"reason": "user_inactive", "user_id": str(user_id)},
            )
            raise ValidationFailed("active user account required")
        instance = await self.instances.primary()
        if instance is None:
            raise Conflict("Forgejo instance is not configured")
        if not self.settings.permits_forgejo_base_url(instance.base_url):
            raise ConfigurationUnavailable(
                "configured Forgejo base URL is not permitted by deployment policy"
            )
        if not instance.verify_tls and not self.settings.allow_unverified_forgejo_tls:
            raise ConfigurationUnavailable(
                "configured Forgejo instance requires unverified TLS, which is disabled "
                "by deployment policy"
            )
        try:
            principal = await self.client.get_current_user(
                base_url=instance.base_url,
                token=ForgejoOAuthToken(normalized_token) if oauth else normalized_token,
                verify_tls=instance.verify_tls,
            )
        except ValidationFailed:
            await self._record_verification_failure(
                actor_account_id=actor_account_id,
                user=user,
                reason="token_rejected",
            )
            raise

        normalized_principal = normalize_username(principal.username)
        if normalized_principal != user.normalized_forgejo_username:
            await self._record_verification_failure(
                actor_account_id=actor_account_id,
                user=user,
                reason="principal_mismatch",
                actual_username=principal.username,
            )
            raise ValidationFailed("Forgejo token belongs to a different user")

        current = await self.credentials.active_for_user(user.id)
        if current is not None and current.forgejo_user_id != principal.id:
            await self._record_verification_failure(
                actor_account_id=actor_account_id,
                user=user,
                reason="principal_id_mismatch",
                actual_username=principal.username,
            )
            raise ValidationFailed("Forgejo user identity changed; revoke the old credential first")
        return VerifiedForgejoPrincipal(principal.id, principal.username)

    async def save(
        self,
        *,
        actor_account_id: uuid.UUID,
        user_id: uuid.UUID,
        token: str,
        oauth_tokens: ForgejoOAuthTokens | None = None,
    ) -> ForgejoCredential:
        principal = await self.verify(
            actor_account_id=actor_account_id,
            user_id=user_id,
            token=token,
            oauth=oauth_tokens is not None,
        )
        cipher = self.cipher()
        encrypted = cipher.encrypt(token.strip(), user_id)
        now = datetime.now(UTC)
        current = await self.credentials.active_for_user(user_id)
        action = "forgejo_credential.created"
        if current is not None:
            self._revoke_secret(current, now)
            action = "forgejo_credential.rotated"

        credential = ForgejoCredential(
            user_id=user_id,
            encrypted_token=encrypted.ciphertext,
            nonce=encrypted.nonce,
            key_version=encrypted.key_version,
            status=CredentialStatus.ACTIVE,
            forgejo_user_id=principal.user_id,
            forgejo_username=principal.username,
            normalized_forgejo_username=normalize_username(principal.username),
            verified_at=now,
            activated_at=now,
        )
        if oauth_tokens is not None:
            instance = await self.instances.primary()
            assert instance is not None
            refresh = cipher.encrypt(
                oauth_tokens.refresh_token.get_secret_value(),
                user_id,
                purpose="oauth-refresh",
            )
            credential.kind = "oauth"
            credential.encrypted_refresh_token = refresh.ciphertext
            credential.refresh_nonce = refresh.nonce
            credential.access_expires_at = now + timedelta(seconds=oauth_tokens.expires_in)
            credential.oauth_base_url = instance.base_url
            credential.oauth_client_id = self.settings.forgejo_oauth_client_id
        self.credentials.add(credential)
        try:
            await self.session.flush()
        except IntegrityError as error:
            await self.session.rollback()
            raise Conflict("an active Forgejo credential already exists") from error
        self.audit.record(
            actor_account_id=actor_account_id,
            action=action,
            target_type="forgejo_credential",
            target_id=str(credential.id),
            details={
                "forgejo_user_id": principal.user_id,
                "forgejo_username": principal.username,
            },
        )
        await self.session.commit()
        return credential

    async def revoke(
        self,
        *,
        actor_account_id: uuid.UUID,
        user_id: uuid.UUID,
        forced_by_admin: bool,
    ) -> None:
        await self.get_user(user_id)
        current = await self.credentials.active_for_user(user_id)
        if current is None:
            raise NotFound("active Forgejo credential not found")
        self._revoke_secret(current, datetime.now(UTC))
        self.audit.record(
            actor_account_id=actor_account_id,
            action="forgejo_credential.revoked",
            target_type="forgejo_credential",
            target_id=str(current.id),
            details={
                "forgejo_user_id": current.forgejo_user_id,
                "forgejo_username": current.forgejo_username,
                "forced_by_admin": forced_by_admin,
            },
        )
        await self.session.commit()

    async def decrypted_token_for_user(self, user_id: uuid.UUID) -> str:
        credential = await self.credentials.active_for_user(user_id)
        if credential is not None and credential.kind == "oauth":
            # Imported locally because the linking service reuses PAT verification/storage.
            from forgejo_mcp.application.forgejo_oauth_service import ForgejoOAuthService

            return await ForgejoOAuthService(self.session, self.settings).access_token(user_id)
        if credential is None or credential.encrypted_token is None or credential.nonce is None:
            raise NotFound("active Forgejo credential not found")
        return self.cipher().decrypt(
            ciphertext=credential.encrypted_token,
            nonce=credential.nonce,
            user_id=user_id,
            key_version=credential.key_version,
        )

    async def _record_verification_failure(
        self,
        *,
        actor_account_id: uuid.UUID,
        user: User,
        reason: str,
        actual_username: str | None = None,
    ) -> None:
        details: dict[str, object] = {
            "reason": reason,
            "expected_forgejo_username": user.expected_forgejo_username,
        }
        if actual_username is not None:
            details["actual_forgejo_username"] = actual_username
        self.audit.record(
            actor_account_id=actor_account_id,
            action="forgejo_credential.verification_failed",
            target_type="user",
            target_id=str(user.id),
            details=details,
        )
        await self.session.commit()

    @staticmethod
    def _revoke_secret(credential: ForgejoCredential, revoked_at: datetime) -> None:
        credential.status = CredentialStatus.REVOKED
        credential.encrypted_token = None
        credential.nonce = None
        credential.encrypted_refresh_token = None
        credential.refresh_nonce = None
        credential.revoked_at = revoked_at
