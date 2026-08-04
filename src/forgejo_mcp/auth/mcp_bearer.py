import hmac
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from mcp.server.auth.provider import AccessToken
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forgejo_mcp.auth.tokens import hash_token, mcp_token_prefix
from forgejo_mcp.db.models import McpToken, RecordStatus
from forgejo_mcp.db.repositories import McpTokenRepository

_MCP_TOKEN_PATTERN = re.compile(r"fmcp_[A-Za-z0-9_-]{43}\Z")


@dataclass(frozen=True)
class AuthenticatedMcpToken:
    token_id: uuid.UUID
    user_id: uuid.UUID
    expires_at: datetime | None


def valid_mcp_token_format(token: str) -> bool:
    return _MCP_TOKEN_PATTERN.fullmatch(token) is not None


class McpBearerAuthenticator:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.tokens = McpTokenRepository(session)

    async def authenticate(self, plaintext: str) -> AuthenticatedMcpToken | None:
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

        record.last_used_at = now
        await self.session.commit()
        return AuthenticatedMcpToken(
            token_id=record.id,
            user_id=record.user_id,
            expires_at=record.expires_at,
        )


class ForgejoMcpTokenVerifier:
    """Adapt opaque Forgejo MCP tokens to the official SDK's bearer verifier."""

    def __init__(
        self,
        session_factory_provider: Callable[[], async_sessionmaker[AsyncSession]],
    ) -> None:
        self.session_factory_provider = session_factory_provider

    async def verify_token(self, token: str) -> AccessToken | None:
        async with self.session_factory_provider()() as session:
            authenticated = await McpBearerAuthenticator(session).authenticate(token)
        if authenticated is None:
            return None
        return AccessToken(
            token="",
            client_id=str(authenticated.token_id),
            scopes=[],
            expires_at=(
                int(authenticated.expires_at.timestamp())
                if authenticated.expires_at is not None
                else None
            ),
            subject=str(authenticated.user_id),
            claims={"mcp_token_id": str(authenticated.token_id)},
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
