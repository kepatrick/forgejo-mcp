from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import cast
from urllib.parse import quote, urlsplit

import httpx
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl, TypeAdapter
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forgejo_mcp.application.oauth_revocation import lock_oauth_family, revoke_oauth_family
from forgejo_mcp.auth.tokens import (
    hash_token,
    mcp_token_prefix,
    new_mcp_token,
    new_oauth_code,
    new_oauth_interaction_token,
    new_oauth_refresh_token,
)
from forgejo_mcp.config import Settings, normalize_http_origin
from forgejo_mcp.db.models import (
    Account,
    AccountRole,
    CredentialStatus,
    ForgejoCredential,
    ManagementAuditEvent,
    McpToken,
    McpTokenToolGrant,
    OAuthAccessToken,
    OAuthAuthorizationCode,
    OAuthAuthorizationRequest,
    OAuthClient,
    OAuthRefreshToken,
    OAuthTokenFamily,
    RecordStatus,
    ToolSetting,
    User,
    UserToolAllowance,
)

SessionFactoryProvider = Callable[[], async_sessionmaker[AsyncSession]]
AddressResolver = Callable[[str, int], set[str]]
OAUTH_SCOPE = "mcp:tools"
_PKCE_PATTERN = re.compile(r"[A-Za-z0-9_-]{43,128}\Z")
_REFRESH_RECOVERY_CACHE_MAX_ENTRIES = 1024


class StoredAuthorizationCode(AuthorizationCode):
    record_id: uuid.UUID
    client_record_id: uuid.UUID
    user_id: uuid.UUID


class StoredRefreshToken(RefreshToken):
    record_id: uuid.UUID
    client_record_id: uuid.UUID
    family_id: uuid.UUID
    user_id: uuid.UUID
    mcp_token_id: uuid.UUID | None


class StoredAccessToken(AccessToken):
    mcp_token_id: uuid.UUID
    client_record_id: uuid.UUID
    refresh_token_id: uuid.UUID
    family_id: uuid.UUID


@dataclass(frozen=True)
class ConsentDetails:
    client_name: str
    client_id: str
    redirect_uri: str
    scopes: tuple[str, ...]
    expires_at: datetime
    grant_ttl_options_days: tuple[int, ...]
    default_grant_ttl_days: int


@dataclass
class _RefreshRecoveryEntry:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    token: OAuthToken | None = None
    expires_at: datetime | None = None


class OAuthService(
    OAuthAuthorizationServerProvider[
        StoredAuthorizationCode,
        StoredRefreshToken,
        StoredAccessToken,
    ]
):
    def __init__(
        self,
        session_factory_provider: SessionFactoryProvider,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: AddressResolver | None = None,
    ) -> None:
        if not settings.oauth_enabled:
            raise ValueError("OAuth service requires OAuth to be enabled")
        assert settings.oauth_issuer_url is not None
        assert settings.oauth_resource_url is not None
        self.session_factory_provider = session_factory_provider
        self.settings = settings
        self.issuer_url = settings.oauth_issuer_url
        self.resource_url = settings.oauth_resource_url
        self.transport = transport
        self.resolver = resolver or _resolve_addresses
        self._refresh_recovery_entries: OrderedDict[uuid.UUID, _RefreshRecoveryEntry] = (
            OrderedDict()
        )
        self._refresh_recovery_guard = asyncio.Lock()

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        if not client_id or len(client_id) > 2048:
            return None
        async with self.session_factory_provider()() as session:
            record = await self._client_by_identifier(session, client_id)
            now = datetime.now(UTC)
            if record is not None and (
                record.source == "dcr"
                or (record.metadata_expires_at is not None and record.metadata_expires_at > now)
            ):
                return _client_info(record)

        if not self._is_allowed_cimd_url(client_id):
            return None
        try:
            info = await self._fetch_cimd(client_id)
        except RegistrationError:
            return None
        async with self.session_factory_provider()() as session:
            record = await self._store_cimd_client(session, info)
            return _client_info(record)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        validated = _validate_public_client(client_info, expected_client_id=client_info.client_id)
        if validated.client_id is None or validated.client_id.startswith(("http://", "https://")):
            raise RegistrationError("invalid_client_metadata", "DCR client ID is invalid")
        async with self.session_factory_provider()() as session:
            existing = await self._client_by_identifier(session, validated.client_id)
            if existing is not None:
                raise RegistrationError("invalid_client_metadata", "client ID already exists")
            session.add(
                OAuthClient(
                    client_id_hash=hash_token(validated.client_id),
                    client_id=validated.client_id,
                    source="dcr",
                    client_metadata=validated.model_dump(mode="json", exclude_none=True),
                    metadata_expires_at=None,
                )
            )
            await session.commit()

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        if client.client_id is None:
            raise AuthorizeError("invalid_request", "client ID is missing")
        if params.resource is not None and params.resource != self.resource_url:
            raise AuthorizeError("invalid_request", "resource must identify this MCP server")
        if not _PKCE_PATTERN.fullmatch(params.code_challenge):
            raise AuthorizeError("invalid_request", "PKCE S256 challenge is invalid")
        if params.state is not None and len(params.state) > 1024:
            raise AuthorizeError("invalid_request", "state is too large")
        scopes = _validated_scopes(params.scopes)
        interaction = new_oauth_interaction_token()
        now = datetime.now(UTC)
        async with self.session_factory_provider()() as session:
            client_record = await self._client_by_identifier(session, client.client_id)
            if client_record is None:
                raise AuthorizeError("unauthorized_client", "client is not registered")
            session.add(
                OAuthAuthorizationRequest(
                    request_token_hash=hash_token(interaction),
                    client_id=client_record.id,
                    redirect_uri=str(params.redirect_uri),
                    state=params.state,
                    code_challenge=params.code_challenge,
                    scopes=scopes,
                    resource=self.resource_url,
                    expires_at=now + timedelta(seconds=self.settings.oauth_interaction_ttl_seconds),
                )
            )
            session.add(
                ManagementAuditEvent(
                    action="oauth.authorization_requested",
                    target_type="oauth_client",
                    target_id=str(client_record.id),
                    details={"source": client_record.source, "scopes": scopes},
                )
            )
            await session.commit()
        return f"{self.issuer_url}/oauth/consent?request={quote(interaction, safe='')}"

    async def consent_details(self, interaction: str) -> ConsentDetails | None:
        if not _valid_interaction_format(interaction):
            return None
        async with self.session_factory_provider()() as session:
            record = await self._authorization_request(session, interaction)
            if not _pending_request(record):
                return None
            assert record is not None
            client = await session.get(OAuthClient, record.client_id)
            if client is None:
                return None
            metadata = _client_info(client)
            return ConsentDetails(
                client_name=(metadata.client_name or "MCP client")[:120],
                client_id=_safe_client_label(client.client_id),
                redirect_uri=record.redirect_uri,
                scopes=tuple(record.scopes),
                expires_at=record.expires_at,
                grant_ttl_options_days=self.settings.oauth_grant_ttl_options_days,
                default_grant_ttl_days=self.settings.oauth_refresh_token_ttl_days,
            )

    async def resolve_consent(
        self,
        *,
        interaction: str,
        account_id: uuid.UUID,
        approve: bool,
        grant_ttl_days: int | None = None,
    ) -> str:
        if not _valid_interaction_format(interaction):
            raise ValueError("authorization request is invalid or expired")
        now = datetime.now(UTC)
        async with self.session_factory_provider()() as session:
            record = await session.scalar(
                select(OAuthAuthorizationRequest)
                .where(OAuthAuthorizationRequest.request_token_hash == hash_token(interaction))
                .with_for_update()
            )
            if not _pending_request(record, now):
                raise ValueError("authorization request is invalid or expired")
            assert record is not None
            account = await session.get(Account, account_id)
            if (
                account is None
                or account.role != AccountRole.USER
                or account.user_id is None
                or account.status != RecordStatus.ACTIVE
                or account.must_change_password
            ):
                raise ValueError("a ready user account is required")
            client = await session.get(OAuthClient, record.client_id)
            if client is None:
                raise ValueError("OAuth client is unavailable")

            selected_grant_ttl_days = (
                self._validate_grant_ttl_days(grant_ttl_days) if approve else None
            )
            record.resolved_at = now
            if not approve:
                session.add(
                    ManagementAuditEvent(
                        actor_account_id=account.id,
                        action="oauth.authorization_denied",
                        target_type="oauth_client",
                        target_id=str(client.id),
                    )
                )
                await session.commit()
                return construct_redirect_uri(
                    record.redirect_uri,
                    error="access_denied",
                    state=record.state,
                    iss=self.issuer_url,
                )

            await self._require_authorizable_user(session, account.user_id)
            assert selected_grant_ttl_days is not None
            refresh_expires_at = now + timedelta(days=selected_grant_ttl_days)
            code = new_oauth_code()
            session.add(
                OAuthAuthorizationCode(
                    code_hash=hash_token(code),
                    client_id=client.id,
                    user_id=account.user_id,
                    redirect_uri=record.redirect_uri,
                    code_challenge=record.code_challenge,
                    scopes=record.scopes,
                    resource=record.resource,
                    expires_at=now
                    + timedelta(seconds=self.settings.oauth_authorization_code_ttl_seconds),
                    refresh_expires_at=refresh_expires_at,
                )
            )
            session.add(
                ManagementAuditEvent(
                    actor_account_id=account.id,
                    action="oauth.authorization_approved",
                    target_type="oauth_client",
                    target_id=str(client.id),
                    details={
                        "scopes": record.scopes,
                        "grant_expires_at": refresh_expires_at.isoformat(),
                    },
                )
            )
            await session.commit()
            return construct_redirect_uri(
                record.redirect_uri,
                code=code,
                state=record.state,
                iss=self.issuer_url,
            )

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> StoredAuthorizationCode | None:
        if client.client_id is None or not authorization_code.startswith("fmcp_ac_"):
            return None
        async with self.session_factory_provider()() as session:
            record = await session.scalar(
                select(OAuthAuthorizationCode).where(
                    OAuthAuthorizationCode.code_hash == hash_token(authorization_code),
                    OAuthAuthorizationCode.consumed_at.is_(None),
                )
            )
            if record is None:
                return None
            client_record = await session.get(OAuthClient, record.client_id)
            if client_record is None or client_record.client_id != client.client_id:
                return None
            return StoredAuthorizationCode(
                code=authorization_code,
                scopes=record.scopes,
                expires_at=record.expires_at.timestamp(),
                client_id=client.client_id,
                code_challenge=record.code_challenge,
                redirect_uri=TypeAdapter(AnyUrl).validate_python(record.redirect_uri),
                redirect_uri_provided_explicitly=True,
                resource=record.resource,
                subject=str(record.user_id),
                record_id=record.id,
                client_record_id=record.client_id,
                user_id=record.user_id,
            )

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: StoredAuthorizationCode,
    ) -> OAuthToken:
        async with self.session_factory_provider()() as session:
            record = await session.scalar(
                select(OAuthAuthorizationCode)
                .where(OAuthAuthorizationCode.id == authorization_code.record_id)
                .with_for_update()
            )
            now = datetime.now(UTC)
            if (
                record is None
                or record.consumed_at is not None
                or record.expires_at <= now
                or record.client_id != authorization_code.client_record_id
            ):
                raise TokenError("invalid_grant", "authorization code is invalid")
            client_record = await session.get(OAuthClient, record.client_id)
            if client_record is None or client_record.client_id != client.client_id:
                raise TokenError("invalid_grant", "authorization code is invalid")
            if record.resource != self.resource_url:
                raise TokenError("invalid_grant", "authorization code audience is invalid")
            record.consumed_at = now
            refresh_expires_at = record.refresh_expires_at or now + timedelta(
                days=self.settings.oauth_refresh_token_ttl_days
            )
            family_id = uuid.uuid4()
            session.add(OAuthTokenFamily(id=family_id))
            token = await self._issue_token_pair(
                session,
                client_record=client_record,
                user_id=record.user_id,
                scopes=record.scopes,
                resource=record.resource,
                family_id=family_id,
                refresh_expires_at=refresh_expires_at,
            )
            await session.commit()
            return token

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> StoredRefreshToken | None:
        if client.client_id is None or not refresh_token.startswith("fmcp_rt_"):
            return None
        async with self.session_factory_provider()() as session:
            record = await session.scalar(
                select(OAuthRefreshToken).where(
                    OAuthRefreshToken.token_hash == hash_token(refresh_token)
                )
            )
            if record is None:
                return None
            family = await session.get(OAuthTokenFamily, record.family_id)
            if family is None or family.revoked_at is not None:
                return None
            client_record = await session.get(OAuthClient, record.client_id)
            if client_record is None or client_record.client_id != client.client_id:
                return None
            return StoredRefreshToken(
                token=refresh_token,
                client_id=client.client_id,
                scopes=record.scopes,
                expires_at=int(record.expires_at.timestamp()),
                subject=str(record.user_id),
                record_id=record.id,
                client_record_id=record.client_id,
                family_id=record.family_id,
                user_id=record.user_id,
                mcp_token_id=record.mcp_token_id,
            )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: StoredRefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        recovery = await self._refresh_recovery_entry(refresh_token.record_id)
        async with recovery.lock:
            return await self._exchange_refresh_token_locked(
                client,
                refresh_token,
                scopes,
                recovery,
            )

    async def _exchange_refresh_token_locked(
        self,
        client: OAuthClientInformationFull,
        refresh_token: StoredRefreshToken,
        scopes: list[str],
        recovery: _RefreshRecoveryEntry,
    ) -> OAuthToken:
        async with self.session_factory_provider()() as session:
            family = await lock_oauth_family(session, refresh_token.family_id)
            if family is None or family.revoked_at is not None:
                raise TokenError("invalid_grant", "refresh token is invalid")
            record = await session.scalar(
                select(OAuthRefreshToken)
                .where(OAuthRefreshToken.id == refresh_token.record_id)
                .with_for_update()
            )
            now = datetime.now(UTC)
            if (
                record is None
                or record.family_id != refresh_token.family_id
                or record.expires_at <= now
            ):
                raise TokenError("invalid_grant", "refresh token is invalid")
            if record.revoked_at is not None:
                raise TokenError("invalid_grant", "refresh token is invalid")
            if record.resource != self.resource_url or not set(scopes) <= set(record.scopes):
                raise TokenError("invalid_scope", "refresh token scope or audience is invalid")
            client_record = await session.get(OAuthClient, record.client_id)
            if client_record is None or client_record.client_id != client.client_id:
                raise TokenError("invalid_grant", "refresh token is invalid")
            if record.rotated_at is not None:
                reuse_age_seconds = (now - record.rotated_at).total_seconds()
                grace_seconds = self.settings.oauth_refresh_token_reuse_grace_seconds
                if grace_seconds > 0 and reuse_age_seconds <= grace_seconds:
                    cached = (
                        recovery.token
                        if recovery.expires_at is not None and recovery.expires_at >= now
                        else None
                    )
                    session.add(
                        ManagementAuditEvent(
                            action=(
                                "oauth.concurrent_refresh_recovered"
                                if cached is not None
                                else "oauth.concurrent_refresh_rejected"
                            ),
                            target_type="oauth_client",
                            target_id=str(record.client_id),
                            details={
                                "family_id": str(record.family_id),
                                "user_id": str(record.user_id),
                                "refresh_token_id": str(record.id),
                                "grace_seconds": grace_seconds,
                                "cache_hit": cached is not None,
                            },
                        )
                    )
                    await session.commit()
                    if cached is None:
                        raise TokenError(
                            "invalid_grant",
                            "concurrent refresh recovery is unavailable",
                        )
                    return cached.model_copy(deep=True)
                await self._revoke_family(session, record.family_id, now)
                await session.commit()
                raise TokenError("invalid_grant", "refresh token reuse was detected")
            record.rotated_at = now
            if record.mcp_token_id is not None:
                await self._revoke_mcp_token(session, record.mcp_token_id, now)
            token = await self._issue_token_pair(
                session,
                client_record=client_record,
                user_id=record.user_id,
                scopes=scopes,
                resource=record.resource,
                family_id=record.family_id,
                refresh_expires_at=record.expires_at,
            )
            await session.commit()
            recovery.token = token.model_copy(deep=True)
            recovery.expires_at = now + timedelta(
                seconds=self.settings.oauth_refresh_token_reuse_grace_seconds
            )
            return token

    async def _refresh_recovery_entry(
        self,
        refresh_token_id: uuid.UUID,
    ) -> _RefreshRecoveryEntry:
        async with self._refresh_recovery_guard:
            now = datetime.now(UTC)
            for entry_id, entry in tuple(self._refresh_recovery_entries.items()):
                if (
                    entry.expires_at is not None
                    and entry.expires_at < now
                    and not entry.lock.locked()
                ):
                    self._refresh_recovery_entries.pop(entry_id, None)
            existing = self._refresh_recovery_entries.get(refresh_token_id)
            if existing is not None:
                self._refresh_recovery_entries.move_to_end(refresh_token_id)
                return existing
            if len(self._refresh_recovery_entries) >= _REFRESH_RECOVERY_CACHE_MAX_ENTRIES:
                for entry_id, entry in tuple(self._refresh_recovery_entries.items()):
                    if not entry.lock.locked():
                        self._refresh_recovery_entries.pop(entry_id, None)
                        break
            created = _RefreshRecoveryEntry()
            if len(self._refresh_recovery_entries) < _REFRESH_RECOVERY_CACHE_MAX_ENTRIES:
                self._refresh_recovery_entries[refresh_token_id] = created
            return created

    async def load_access_token(self, token: str) -> StoredAccessToken | None:
        if not token.startswith("fmcp_"):
            return None
        async with self.session_factory_provider()() as session:
            record = await session.scalar(
                select(McpToken).where(McpToken.token_hash == hash_token(token))
            )
            now = datetime.now(UTC)
            if (
                record is None
                or not record.enabled
                or record.revoked_at is not None
                or record.expires_at is None
                or record.expires_at <= now
            ):
                return None
            link = await session.get(OAuthAccessToken, record.id)
            if link is None or link.revoked_at is not None or link.resource != self.resource_url:
                return None
            refresh = await session.get(OAuthRefreshToken, link.refresh_token_id)
            client = await session.get(OAuthClient, link.client_id)
            family = (
                await session.get(OAuthTokenFamily, refresh.family_id)
                if refresh is not None
                else None
            )
            if (
                refresh is None
                or refresh.revoked_at is not None
                or client is None
                or family is None
                or family.revoked_at is not None
            ):
                return None
            return StoredAccessToken(
                token="",
                client_id=client.client_id,
                scopes=refresh.scopes,
                expires_at=int(record.expires_at.timestamp()),
                resource=link.resource,
                subject=str(record.user_id),
                claims={"iss": self.issuer_url, "mcp_token_id": str(record.id)},
                mcp_token_id=record.id,
                client_record_id=client.id,
                refresh_token_id=refresh.id,
                family_id=refresh.family_id,
            )

    async def revoke_token(self, token: StoredAccessToken | StoredRefreshToken) -> None:
        now = datetime.now(UTC)
        async with self.session_factory_provider()() as session:
            await self._revoke_family(session, token.family_id, now)
            session.add(
                ManagementAuditEvent(
                    action="oauth.token_family_revoked",
                    target_type="oauth_client",
                    target_id=str(token.client_record_id),
                )
            )
            await session.commit()

    async def _issue_token_pair(
        self,
        session: AsyncSession,
        *,
        client_record: OAuthClient,
        user_id: uuid.UUID,
        scopes: list[str],
        resource: str,
        family_id: uuid.UUID,
        refresh_expires_at: datetime,
    ) -> OAuthToken:
        await self._require_authorizable_user(session, user_id)
        tool_names = await self._effective_tool_names(session, user_id)
        if not tool_names:
            raise TokenError("invalid_grant", "user has no effective MCP tools")
        now = datetime.now(UTC)
        access_expires_at = min(
            now + timedelta(seconds=self.settings.oauth_access_token_ttl_seconds),
            refresh_expires_at,
        )
        expires_in = int((access_expires_at - now).total_seconds())
        if expires_in <= 0:
            raise TokenError("invalid_grant", "authorization has expired")
        access_plaintext = new_mcp_token()
        refresh_plaintext = new_oauth_refresh_token()
        access_record = McpToken(
            user_id=user_id,
            name=f"OAuth: {_client_name(client_record)}"[:120],
            description="OAuth 2.1 access token",
            token_prefix=mcp_token_prefix(access_plaintext),
            token_hash=hash_token(access_plaintext),
            kind="oauth",
            enabled=True,
            expires_at=access_expires_at,
        )
        session.add(access_record)
        await session.flush()
        session.add_all(
            McpTokenToolGrant(mcp_token_id=access_record.id, tool_name=name)
            for name in sorted(tool_names)
        )
        refresh_record = OAuthRefreshToken(
            token_hash=hash_token(refresh_plaintext),
            token_prefix=refresh_plaintext[:16],
            family_id=family_id,
            client_id=client_record.id,
            user_id=user_id,
            scopes=scopes,
            resource=resource,
            mcp_token_id=access_record.id,
            expires_at=refresh_expires_at,
        )
        session.add(refresh_record)
        await session.flush()
        assert access_record.expires_at is not None
        session.add(
            OAuthAccessToken(
                mcp_token_id=access_record.id,
                client_id=client_record.id,
                refresh_token_id=refresh_record.id,
                resource=resource,
            )
        )
        account_id = await session.scalar(select(Account.id).where(Account.user_id == user_id))
        session.add(
            ManagementAuditEvent(
                actor_account_id=account_id,
                action="oauth.token_issued",
                target_type="mcp_token",
                target_id=str(access_record.id),
                details={
                    "client_id": str(client_record.id),
                    "expires_at": access_record.expires_at.isoformat(),
                    "grant_expires_at": refresh_expires_at.isoformat(),
                    "tool_count": len(tool_names),
                },
            )
        )
        return OAuthToken(
            access_token=access_plaintext,
            token_type="Bearer",
            expires_in=expires_in,
            scope=" ".join(scopes),
            refresh_token=refresh_plaintext,
        )

    def _validate_grant_ttl_days(self, value: int | None) -> int:
        selected = self.settings.oauth_refresh_token_ttl_days if value is None else value
        if type(selected) is not int or selected not in self.settings.oauth_grant_ttl_options_days:
            raise ValueError("authorization lifetime is not allowed")
        return selected

    async def _require_authorizable_user(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
    ) -> None:
        user = await session.get(User, user_id)
        credential = await session.scalar(
            select(ForgejoCredential.id).where(
                ForgejoCredential.user_id == user_id,
                ForgejoCredential.status == CredentialStatus.ACTIVE,
                ForgejoCredential.revoked_at.is_(None),
            )
        )
        if user is None or user.status != RecordStatus.ACTIVE or credential is None:
            raise TokenError("invalid_grant", "user is not ready for MCP authorization")

    async def _effective_tool_names(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
    ) -> set[str]:
        names = await session.scalars(
            select(UserToolAllowance.tool_name)
            .join(ToolSetting, ToolSetting.tool_name == UserToolAllowance.tool_name)
            .where(UserToolAllowance.user_id == user_id, ToolSetting.enabled.is_(True))
        )
        return set(names.all())

    async def _revoke_mcp_token(
        self,
        session: AsyncSession,
        token_id: uuid.UUID,
        now: datetime,
    ) -> None:
        await session.execute(
            update(McpToken)
            .where(McpToken.id == token_id, McpToken.revoked_at.is_(None))
            .values(enabled=False, revoked_at=now)
        )
        await session.execute(
            update(OAuthAccessToken)
            .where(OAuthAccessToken.mcp_token_id == token_id)
            .values(revoked_at=now)
        )

    async def _revoke_family(
        self,
        session: AsyncSession,
        family_id: uuid.UUID,
        now: datetime,
    ) -> None:
        await revoke_oauth_family(session, family_id, now)

    async def _client_by_identifier(
        self,
        session: AsyncSession,
        client_id: str,
    ) -> OAuthClient | None:
        return cast(
            OAuthClient | None,
            await session.scalar(
                select(OAuthClient).where(OAuthClient.client_id_hash == hash_token(client_id))
            ),
        )

    async def _authorization_request(
        self,
        session: AsyncSession,
        interaction: str,
    ) -> OAuthAuthorizationRequest | None:
        return cast(
            OAuthAuthorizationRequest | None,
            await session.scalar(
                select(OAuthAuthorizationRequest).where(
                    OAuthAuthorizationRequest.request_token_hash == hash_token(interaction)
                )
            ),
        )

    async def _store_cimd_client(
        self,
        session: AsyncSession,
        info: OAuthClientInformationFull,
    ) -> OAuthClient:
        assert info.client_id is not None
        record = await self._client_by_identifier(session, info.client_id)
        expires_at = datetime.now(UTC) + timedelta(
            seconds=self.settings.oauth_client_metadata_cache_seconds
        )
        if record is not None:
            record.client_metadata = info.model_dump(mode="json", exclude_none=True)
            record.metadata_expires_at = expires_at
            await session.commit()
            return record
        record = OAuthClient(
            client_id_hash=hash_token(info.client_id),
            client_id=info.client_id,
            source="cimd",
            client_metadata=info.model_dump(mode="json", exclude_none=True),
            metadata_expires_at=expires_at,
        )
        session.add(record)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            existing = await self._client_by_identifier(session, info.client_id)
            if existing is None:
                raise
            return existing
        return record

    def _is_allowed_cimd_url(self, client_id: str) -> bool:
        try:
            parsed = urlsplit(client_id)
            origin = normalize_http_origin(f"{parsed.scheme}://{parsed.netloc}")
        except ValueError:
            return False
        return (
            parsed.scheme == "https"
            and parsed.hostname is not None
            and parsed.username is None
            and parsed.password is None
            and not parsed.fragment
            and not parsed.query
            and origin in self.settings.oauth_cimd_allowed_origins
        )

    async def _fetch_cimd(self, client_id: str) -> OAuthClientInformationFull:
        parsed = urlsplit(client_id)
        assert parsed.hostname is not None
        port = parsed.port or 443
        addresses = await asyncio.to_thread(self.resolver, parsed.hostname, port)
        if not addresses or any(
            not ipaddress.ip_address(address).is_global for address in addresses
        ):
            raise RegistrationError("invalid_client_metadata", "CIMD host is not public")
        timeout = httpx.Timeout(connect=5, read=5, write=5, pool=5)
        metadata_error: str | None = None
        body = bytearray()
        try:
            async with (
                httpx.AsyncClient(
                    timeout=timeout,
                    follow_redirects=False,
                    transport=self.transport,
                ) as client,
                client.stream(
                    "GET",
                    client_id,
                    headers={"Accept": "application/json"},
                ) as response,
            ):
                if response.status_code != 200 or response.is_redirect:
                    metadata_error = "CIMD endpoint did not return HTTP 200"
                elif "json" not in response.headers.get("content-type", "").lower():
                    metadata_error = "CIMD endpoint did not return JSON"
                else:
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > self.settings.oauth_client_metadata_max_bytes:
                            metadata_error = "CIMD document is too large"
                            break
        except httpx.HTTPError as error:
            raise RegistrationError(
                "invalid_client_metadata",
                "CIMD endpoint is unavailable",
            ) from error
        if metadata_error is not None:
            # RegistrationError is a frozen SDK dataclass. Raise it only after
            # httpx has exited its context managers, whose exception handling
            # otherwise attempts to assign to the exception traceback.
            raise RegistrationError("invalid_client_metadata", metadata_error)
        try:
            payload = json.loads(body)
            info = OAuthClientInformationFull.model_validate(payload)
        except (json.JSONDecodeError, ValueError) as error:
            raise RegistrationError(
                "invalid_client_metadata",
                "CIMD document is invalid",
            ) from error
        return _validate_public_client(info, expected_client_id=client_id)


def _client_info(record: OAuthClient) -> OAuthClientInformationFull:
    info = OAuthClientInformationFull.model_validate(record.client_metadata)
    if info.client_id != record.client_id:
        raise RuntimeError("stored OAuth client metadata is inconsistent")
    return info


def _validate_public_client(
    info: OAuthClientInformationFull,
    *,
    expected_client_id: str | None,
) -> OAuthClientInformationFull:
    if info.client_id is None or info.client_id != expected_client_id:
        raise RegistrationError("invalid_client_metadata", "client_id does not match metadata URL")
    if info.client_secret is not None or info.token_endpoint_auth_method not in {None, "none"}:
        raise RegistrationError("invalid_client_metadata", "only public PKCE clients are supported")
    if info.redirect_uris is None or not 1 <= len(info.redirect_uris) <= 10:
        raise RegistrationError("invalid_redirect_uri", "one to ten redirect URIs are required")
    for redirect_uri in info.redirect_uris:
        _validate_redirect_uri(str(redirect_uri))
    grants = set(info.grant_types)
    if grants != {"authorization_code", "refresh_token"}:
        raise RegistrationError(
            "invalid_client_metadata",
            "only authorization_code and refresh_token grants are supported",
        )
    if set(info.response_types) != {"code"}:
        raise RegistrationError(
            "invalid_client_metadata",
            "only the code response type is supported",
        )
    if info.scope not in {None, OAUTH_SCOPE}:
        raise RegistrationError("invalid_client_metadata", "only the mcp:tools scope is supported")
    info.token_endpoint_auth_method = "none"
    info.client_secret = None
    info.scope = OAUTH_SCOPE
    return info


def _validate_redirect_uri(value: str) -> None:
    if len(value) > 2048:
        raise RegistrationError("invalid_redirect_uri", "redirect URI is too large")
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as error:
        raise RegistrationError("invalid_redirect_uri", "redirect URI is invalid") from error
    loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if (
        parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or (parsed.scheme != "https" and not (parsed.scheme == "http" and loopback))
    ):
        raise RegistrationError(
            "invalid_redirect_uri",
            "redirect URI must use HTTPS or an HTTP loopback host",
        )


def _validated_scopes(scopes: list[str] | None) -> list[str]:
    resolved = scopes or [OAUTH_SCOPE]
    if set(resolved) != {OAUTH_SCOPE}:
        raise AuthorizeError("invalid_scope", "only the mcp:tools scope is supported")
    return [OAUTH_SCOPE]


def _pending_request(
    record: OAuthAuthorizationRequest | None,
    now: datetime | None = None,
) -> bool:
    resolved_now = now or datetime.now(UTC)
    return bool(
        record is not None and record.resolved_at is None and record.expires_at > resolved_now
    )


def _valid_interaction_format(value: str) -> bool:
    return value.startswith("fmcp_oi_") and 40 <= len(value) <= 80


def _safe_client_label(client_id: str) -> str:
    parsed = urlsplit(client_id)
    if parsed.scheme == "https" and parsed.hostname:
        return parsed.hostname
    return "dynamically registered client"


def _client_name(record: OAuthClient) -> str:
    info = _client_info(record)
    return (info.client_name or _safe_client_label(record.client_id))[:100]


def _resolve_addresses(hostname: str, port: int) -> set[str]:
    return {
        cast(str, item[4][0])
        for item in socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    }
