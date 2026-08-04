import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

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
from forgejo_mcp.db.models import CredentialStatus, ForgejoCredential, User
from forgejo_mcp.db.repositories import (
    AuditRepository,
    ForgejoCredentialRepository,
    ForgejoInstanceRepository,
    UserRepository,
)
from forgejo_mcp.forgejo.client import ForgejoClient


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
    ) -> VerifiedForgejoPrincipal:
        normalized_token = token.strip()
        if not normalized_token or len(normalized_token) > 2048:
            raise ValidationFailed("personal access token is invalid")
        user = await self.get_user(user_id)
        instance = await self.instances.primary()
        if instance is None:
            raise Conflict("Forgejo instance is not configured")
        try:
            principal = await self.client.get_current_user(
                base_url=instance.base_url,
                token=normalized_token,
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
    ) -> ForgejoCredential:
        principal = await self.verify(
            actor_account_id=actor_account_id,
            user_id=user_id,
            token=token,
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
        credential.revoked_at = revoked_at
