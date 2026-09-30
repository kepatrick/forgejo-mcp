"""Forgejo account linking, separate from the MCP OAuth authorization server."""

import base64
import hashlib
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from forgejo_mcp.application.errors import ConfigurationUnavailable, ValidationFailed
from forgejo_mcp.application.forgejo_credential_service import ForgejoCredentialService
from forgejo_mcp.auth.passwords import normalize_username
from forgejo_mcp.auth.tokens import hash_token
from forgejo_mcp.config import Settings
from forgejo_mcp.db.models import (
    Account,
    AccountRole,
    CredentialStatus,
    ForgejoCredential,
    ForgejoInstance,
    ForgejoOAuthRequest,
    RecordStatus,
    Session,
    User,
)
from forgejo_mcp.forgejo.client import ForgejoOAuthToken
from forgejo_mcp.forgejo.oauth import ForgejoOAuthClient

logger = logging.getLogger(__name__)


class ForgejoOAuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.credentials = ForgejoCredentialService(session, settings)
        self.client = ForgejoOAuthClient(settings)

    @staticmethod
    def reject(reason: str) -> None:
        logger.warning("forgejo_oauth_link_rejected", extra={"reason": reason})
        raise ValidationFailed("Forgejo authorization is unavailable; sign in and reconnect")

    async def configuration(self) -> ForgejoInstance:
        instance = await self.credentials.instances.primary()
        if (
            not self.settings.forgejo_oauth_client_id
            or not self.settings.forgejo_oauth_redirect_url
        ):
            logger.warning(
                "forgejo_oauth_configuration_unavailable", extra={"reason": "not_configured"}
            )
            raise ConfigurationUnavailable(
                "Forgejo OAuth is not configured; use a PAT or contact your administrator"
            )
        if instance is None or not self.settings.permits_forgejo_base_url(instance.base_url):
            logger.warning(
                "forgejo_oauth_configuration_unavailable", extra={"reason": "untrusted_instance"}
            )
            raise ConfigurationUnavailable("Forgejo OAuth requires an allowlisted Forgejo instance")
        if (
            not instance.base_url.startswith("https://")
            and not self.settings.allow_insecure_forgejo_http
        ) or (not instance.verify_tls and not self.settings.allow_unverified_forgejo_tls):
            logger.warning(
                "forgejo_oauth_configuration_unavailable", extra={"reason": "tls_policy"}
            )
            raise ConfigurationUnavailable("Forgejo OAuth requires a secure Forgejo connection")
        return instance

    async def require_session(self, current: Session) -> None:
        active = await self.session.scalar(
            select(Session.id)
            .join(Account, Session.account_id == Account.id)
            .join(User, Account.user_id == User.id)
            .where(
                Session.id == current.id,
                Session.revoked_at.is_(None),
                Session.expires_at > datetime.now(UTC),
                Account.role == AccountRole.USER,
                Account.status == RecordStatus.ACTIVE,
                Account.must_change_password.is_(False),
                User.status == RecordStatus.ACTIVE,
            )
        )
        if active is None:
            self.reject("session_unavailable")

    async def callback_session(self, state: str, browser_token: str | None) -> Session:
        if len(state) != 43 or browser_token is None or len(browser_token) != 43:
            self.reject("missing_callback_binding")
        assert browser_token is not None
        flow = await self.session.scalar(
            select(ForgejoOAuthRequest).where(
                ForgejoOAuthRequest.state_hash == hash_token(state),
                ForgejoOAuthRequest.browser_token_hash == hash_token(browser_token),
                ForgejoOAuthRequest.expires_at > datetime.now(UTC),
                ForgejoOAuthRequest.consumed_at.is_(None),
            )
        )
        if flow is None:
            self.reject("invalid_callback_binding")
        assert flow is not None
        current = await self.session.scalar(
            select(Session)
            .where(Session.id == flow.session_id)
            .options(
                selectinload(Session.account).selectinload(Account.user),
            )
        )
        if current is None:
            self.reject("callback_session_unavailable")
        assert current is not None
        await self.require_session(current)
        return current

    async def start(self, current: Session) -> tuple[str, str]:
        await self.require_session(current)
        instance = await self.configuration()
        assert current.account.user_id is not None
        state = secrets.token_urlsafe(32)
        browser_token = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        encrypted = self.credentials.cipher().encrypt(
            verifier,
            current.account.user_id,
            purpose="oauth-verifier",
        )
        # Bound pending storage and discard encrypted verifiers for stale attempts.
        await self.session.execute(
            delete(ForgejoOAuthRequest).where(
                or_(
                    ForgejoOAuthRequest.session_id == current.id,
                    ForgejoOAuthRequest.expires_at <= datetime.now(UTC),
                )
            )
        )
        self.session.add(
            ForgejoOAuthRequest(
                state_hash=hash_token(state),
                browser_token_hash=hash_token(browser_token),
                session_id=current.id,
                instance_id=instance.id,
                base_url=instance.base_url,
                client_id=self.settings.forgejo_oauth_client_id,
                redirect_url=self.settings.forgejo_oauth_redirect_url,
                encrypted_verifier=encrypted.ciphertext,
                nonce=encrypted.nonce,
                key_version=encrypted.key_version,
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
            )
        )
        await self.session.commit()
        url = (
            instance.base_url
            + "/login/oauth/authorize?"
            + urlencode(
                {
                    "response_type": "code",
                    "client_id": self.settings.forgejo_oauth_client_id,
                    "redirect_uri": self.settings.forgejo_oauth_redirect_url,
                    "state": state,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                }
            )
        )
        return url, browser_token

    async def complete(
        self, current: Session, *, state: str, code: str, denied: bool = False
    ) -> None:
        if (
            len(state) != 43
            or not state.isascii()
            or not all(c.isalnum() or c in "-_" for c in state)
        ):
            self.reject("invalid_state")
        await self.require_session(current)
        instance = await self.configuration()
        flow = await self.session.scalar(
            select(ForgejoOAuthRequest)
            .where(
                ForgejoOAuthRequest.state_hash == hash_token(state),
            )
            .with_for_update()
        )
        if (
            flow is None
            or flow.session_id != current.id
            or flow.consumed_at is not None
            or flow.expires_at <= datetime.now(UTC)
            or flow.instance_id != instance.id
            or flow.base_url != instance.base_url
            or flow.client_id != self.settings.forgejo_oauth_client_id
            or flow.redirect_url != self.settings.forgejo_oauth_redirect_url
        ):
            self.reject("expired_or_unbound_state")
        assert flow is not None and current.account.user_id is not None
        verifier = self.credentials.cipher().decrypt(
            ciphertext=flow.encrypted_verifier,
            nonce=flow.nonce,
            user_id=current.account.user_id,
            key_version=flow.key_version,
            purpose="oauth-verifier",
        )
        # Consume once before network IO. Never retry a potentially redeemed code.
        flow.consumed_at = datetime.now(UTC)
        flow.encrypted_verifier = b""
        flow.nonce = b""
        await self.session.commit()
        if denied:
            self.reject("provider_denied")
        if not code or len(code) > 2048 or not code.isascii() or any(ord(c) <= 32 for c in code):
            self.reject("invalid_code")
        tokens = await self.client.exchange(
            base_url=instance.base_url,
            verify_tls=instance.verify_tls,
            values={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.settings.forgejo_oauth_redirect_url or "",
                "code_verifier": verifier,
            },
        )
        await self.require_session(current)
        user = await self.credentials.get_user(current.account.user_id)
        await self.session.refresh(user)
        await self.credentials.save(
            actor_account_id=current.account_id,
            user_id=current.account.user_id,
            token=tokens.access_token.get_secret_value(),
            oauth_tokens=tokens,
        )
        logger.info("forgejo_oauth_link_completed", extra={"user_id": str(current.account.user_id)})

    async def access_token(self, user_id: uuid.UUID) -> ForgejoOAuthToken:
        instance = await self.configuration()
        credential = await self.session.scalar(
            select(ForgejoCredential)
            .where(
                ForgejoCredential.user_id == user_id,
                ForgejoCredential.status == CredentialStatus.ACTIVE,
                ForgejoCredential.revoked_at.is_(None),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            credential is None
            or credential.kind != "oauth"
            or (
                credential.oauth_base_url != instance.base_url
                or credential.oauth_client_id != self.settings.forgejo_oauth_client_id
                or credential.encrypted_token is None
                or credential.nonce is None
            )
        ):
            self.reject("credential_unavailable_or_instance_changed")
        assert (
            credential is not None
            and credential.encrypted_token is not None
            and credential.nonce is not None
        )
        user = await self.credentials.get_user(user_id)
        await self.session.refresh(user)
        if user.status != RecordStatus.ACTIVE:
            self.reject("user_disabled")
        cipher = self.credentials.cipher()
        if credential.access_expires_at is None:
            self.reject("missing_expiry")
        assert credential.access_expires_at is not None
        if credential.access_expires_at <= datetime.now(UTC) + timedelta(seconds=30):
            if credential.encrypted_refresh_token is None or credential.refresh_nonce is None:
                self.reject("refresh_unavailable")
            assert (
                credential.encrypted_refresh_token is not None
                and credential.refresh_nonce is not None
            )
            refresh = cipher.decrypt(
                ciphertext=credential.encrypted_refresh_token,
                nonce=credential.refresh_nonce,
                user_id=user_id,
                key_version=credential.key_version,
                purpose="oauth-refresh",
            )
            tokens = await self.client.exchange(
                base_url=instance.base_url,
                verify_tls=instance.verify_tls,
                values={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh,
                },
            )
            principal = await self.credentials.client.get_current_user(
                base_url=instance.base_url,
                verify_tls=instance.verify_tls,
                token=ForgejoOAuthToken(tokens.access_token.get_secret_value()),
            )
            if (
                principal.id != credential.forgejo_user_id
                or normalize_username(principal.username) != user.normalized_forgejo_username
            ):
                self.reject("refresh_principal_mismatch")
            access = cipher.encrypt(tokens.access_token.get_secret_value(), user_id)
            new_refresh = cipher.encrypt(
                tokens.refresh_token.get_secret_value(), user_id, purpose="oauth-refresh"
            )
            credential.encrypted_token, credential.nonce = access.ciphertext, access.nonce
            credential.encrypted_refresh_token, credential.refresh_nonce = (
                new_refresh.ciphertext,
                new_refresh.nonce,
            )
            credential.key_version = access.key_version
            credential.access_expires_at = datetime.now(UTC) + timedelta(seconds=tokens.expires_in)
            self.credentials.audit.record(
                actor_account_id=None,
                action="forgejo_credential.oauth_refreshed",
                target_type="forgejo_credential",
                target_id=str(credential.id),
            )
            logger.info("forgejo_oauth_refresh_completed", extra={"user_id": str(user_id)})
        token = cipher.decrypt(
            ciphertext=credential.encrypted_token,
            nonce=credential.nonce,
            user_id=user_id,
            key_version=credential.key_version,
        )
        await self.session.commit()
        return ForgejoOAuthToken(token)
