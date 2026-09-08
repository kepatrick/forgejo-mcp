import hmac
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from mcp.server.auth.provider import AccessToken
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forgejo_mcp.auth.tokens import hash_token, mcp_token_prefix
from forgejo_mcp.db.models import (
    McpToken,
    OAuthAccessToken,
    OAuthRefreshToken,
    OAuthTokenFamily,
    RecordStatus,
)
from forgejo_mcp.db.repositories import McpTokenRepository

_MCP_TOKEN_PATTERN = re.compile(r"fmcp_[A-Za-z0-9_-]{43}\Z")


@dataclass(frozen=True)
class AuthenticatedMcpToken:
    token_id: uuid.UUID
    user_id: uuid.UUID
    expires_at: datetime | None
    scopes: tuple[str, ...] = ()
    resource: str | None = None
    issuer: str | None = None


def valid_mcp_token_format(token: str) -> bool:
    return _MCP_TOKEN_PATTERN.fullmatch(token) is not None


class McpBearerAuthenticator:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.tokens = McpTokenRepository(session)

    async def authenticate(
        self,
        plaintext: str,
        *,
        oauth_resource_url: str | None = None,
        oauth_issuer_url: str | None = None,
    ) -> AuthenticatedMcpToken | None:
        if not valid_mcp_token_format(plaintext):
            return None

        expected_hash = hash_token(plaintext)
        candidates = await self.tokens.candidates_for_prefix(mcp_token_prefix(plaintext))
        matches = [
            candidate
            for candidate in candidates
            if hmac.compare_digest(candidate.token_hash, expected_hash)
        ]
        if len(matches) != 1:
            return None

        record = matches[0]
        now = datetime.now(UTC)
        if not _active(record, now):
            return None

        oauth_link = await self.session.get(OAuthAccessToken, record.id)
        scopes: tuple[str, ...] = ()
        resource = None
        issuer = None
        if record.kind == "oauth":
            if (
                oauth_link is None
                or oauth_resource_url is None
                or oauth_issuer_url is None
                or oauth_link.revoked_at is not None
                or oauth_link.resource != oauth_resource_url
            ):
                return None
            refresh = await self.session.get(OAuthRefreshToken, oauth_link.refresh_token_id)
            if refresh is None or refresh.revoked_at is not None:
                return None
            family = await self.session.get(OAuthTokenFamily, refresh.family_id)
            if family is None or family.revoked_at is not None:
                return None
            scopes = tuple(refresh.scopes)
            resource = oauth_link.resource
            issuer = oauth_issuer_url
        elif record.kind != "static" or oauth_link is not None:
            # Fail closed on unknown or internally inconsistent token records.
            return None

        record.last_used_at = now
        await self.session.commit()
        return AuthenticatedMcpToken(
            token_id=record.id,
            user_id=record.user_id,
            expires_at=record.expires_at,
            scopes=scopes,
            resource=resource,
            issuer=issuer,
        )


class ForgejoMcpTokenVerifier:
    """Adapt opaque Forgejo MCP tokens to the official SDK's bearer verifier."""

    def __init__(
        self,
        session_factory_provider: Callable[[], async_sessionmaker[AsyncSession]],
        *,
        oauth_resource_url: str | None = None,
        oauth_issuer_url: str | None = None,
    ) -> None:
        self.session_factory_provider = session_factory_provider
        self.oauth_resource_url = oauth_resource_url
        self.oauth_issuer_url = oauth_issuer_url

    async def verify_token(self, token: str) -> AccessToken | None:
        async with self.session_factory_provider()() as session:
            authenticated = await McpBearerAuthenticator(session).authenticate(
                token,
                oauth_resource_url=self.oauth_resource_url,
                oauth_issuer_url=self.oauth_issuer_url,
            )
        if authenticated is None:
            return None
        return AccessToken(
            token="",
            client_id=str(authenticated.token_id),
            scopes=list(authenticated.scopes),
            expires_at=(
                int(authenticated.expires_at.timestamp())
                if authenticated.expires_at is not None
                else None
            ),
            subject=str(authenticated.user_id),
            resource=authenticated.resource,
            claims={
                "mcp_token_id": str(authenticated.token_id),
                **({"iss": authenticated.issuer} if authenticated.issuer is not None else {}),
            },
        )


def _active(record: McpToken, now: datetime) -> bool:
    return (
        record.enabled
        and record.revoked_at is None
        and record.user.status == RecordStatus.ACTIVE
        and (record.expires_at is None or record.expires_at > now)
    )


def token_id_from_access_token(access_token: AccessToken) -> uuid.UUID:
    return uuid.UUID(access_token.client_id)


def user_id_from_access_token(access_token: AccessToken) -> uuid.UUID:
    if access_token.subject is None:
        raise ValueError("authenticated MCP token has no user subject")
    return uuid.UUID(access_token.subject)
