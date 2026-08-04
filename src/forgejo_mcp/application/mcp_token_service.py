import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from forgejo_mcp.application.errors import InvalidOperation, NotFound, ValidationFailed
from forgejo_mcp.auth.tokens import hash_token, mcp_token_prefix, new_mcp_token
from forgejo_mcp.db.models import McpToken, RecordStatus
from forgejo_mcp.db.repositories import AuditRepository, McpTokenRepository, UserRepository


@dataclass(frozen=True)
class CreatedMcpToken:
    record: McpToken
    token: str


class McpTokenService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditRepository(session)
        self.tokens = McpTokenRepository(session)
        self.users = UserRepository(session)

    async def create(
        self,
        *,
        actor_account_id: uuid.UUID,
        user_id: uuid.UUID,
        name: str,
        description: str | None,
        expires_at: datetime | None,
    ) -> CreatedMcpToken:
        user = await self.users.get(user_id)
        if user is None:
            raise NotFound("user not found")
        if user.status != RecordStatus.ACTIVE:
            raise InvalidOperation("MCP tokens require an active user")

        normalized_name = name.strip()
        if not normalized_name:
            raise ValidationFailed("token name is required")
        normalized_description = description.strip() if description else None
        if normalized_description == "":
            normalized_description = None

        now = datetime.now(UTC)
        if expires_at is not None:
            if expires_at.tzinfo is None:
                raise ValidationFailed("token expiry must include a timezone")
            expires_at = expires_at.astimezone(UTC)
            if expires_at <= now:
                raise ValidationFailed("token expiry must be in the future")

        plaintext = new_mcp_token()
        record = McpToken(
            user_id=user_id,
            name=normalized_name,
            description=normalized_description,
            token_prefix=mcp_token_prefix(plaintext),
            token_hash=hash_token(plaintext),
            enabled=True,
            expires_at=expires_at,
        )
        self.tokens.add(record)
        try:
            await self.session.flush()
        except IntegrityError as error:
            await self.session.rollback()
            raise InvalidOperation("could not issue a unique MCP token") from error

        self.audit.record(
            actor_account_id=actor_account_id,
            action="mcp_token.created",
            target_type="mcp_token",
            target_id=str(record.id),
            details={"name": record.name, "expires_at": _isoformat(record.expires_at)},
        )
        await self.session.commit()
        return CreatedMcpToken(record=record, token=plaintext)

    async def list_for_user(self, user_id: uuid.UUID) -> list[McpToken]:
        return await self.tokens.list_for_user(user_id)

    async def list_all(self) -> list[McpToken]:
        return await self.tokens.list_all()

    async def revoke_for_user(
        self,
        *,
        actor_account_id: uuid.UUID,
        user_id: uuid.UUID,
        token_id: uuid.UUID,
    ) -> None:
        record = await self.tokens.get_for_user(token_id, user_id)
        if record is None:
            raise NotFound("MCP token not found")
        await self._revoke(record, actor_account_id=actor_account_id, forced_by_admin=False)

    async def revoke_as_admin(
        self,
        *,
        actor_account_id: uuid.UUID,
        token_id: uuid.UUID,
    ) -> None:
        record = await self.tokens.get(token_id)
        if record is None:
            raise NotFound("MCP token not found")
        await self._revoke(record, actor_account_id=actor_account_id, forced_by_admin=True)

    async def _revoke(
        self,
        record: McpToken,
        *,
        actor_account_id: uuid.UUID,
        forced_by_admin: bool,
    ) -> None:
        if record.revoked_at is not None:
            raise InvalidOperation("MCP token is already revoked")
        record.enabled = False
        record.revoked_at = datetime.now(UTC)
        self.audit.record(
            actor_account_id=actor_account_id,
            action="mcp_token.revoked",
            target_type="mcp_token",
            target_id=str(record.id),
            details={
                "name": record.name,
                "user_id": str(record.user_id),
                "forced_by_admin": forced_by_admin,
            },
        )
        await self.session.commit()


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
