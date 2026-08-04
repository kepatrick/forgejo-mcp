from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from forgejo_mcp.application.errors import Conflict, Gone, NotFound
from forgejo_mcp.auth.passwords import hash_password
from forgejo_mcp.auth.tokens import hash_token
from forgejo_mcp.db.models import RecordStatus, UserInvitation
from forgejo_mcp.db.repositories import AuditRepository, InvitationRepository, SessionRepository


@dataclass(frozen=True)
class InvitationContext:
    display_name: str
    username: str
    forgejo_username: str
    expires_at: datetime


class InvitationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditRepository(session)
        self.invitations = InvitationRepository(session)
        self.sessions = SessionRepository(session)

    async def _load_valid(self, token: str) -> UserInvitation:
        invitation = await self.invitations.by_token_hash(hash_token(token))
        now = datetime.now(UTC)
        if invitation is None:
            raise NotFound("invitation is invalid or expired")
        if invitation.used_at is not None:
            raise Gone("invitation has already been used")
        if invitation.revoked_at is not None or invitation.expires_at <= now:
            raise Gone("invitation is invalid or expired")
        if invitation.user.status == RecordStatus.DISABLED:
            raise Gone("invitation is invalid or expired")
        return invitation

    async def context(self, token: str) -> InvitationContext:
        invitation = await self._load_valid(token)
        account = invitation.user.account
        if account is None:
            raise Conflict("invitation account is unavailable")
        return InvitationContext(
            display_name=invitation.user.display_name,
            username=account.username,
            forgejo_username=invitation.user.expected_forgejo_username,
            expires_at=invitation.expires_at,
        )

    async def accept(self, token: str, password: str) -> str:
        invitation = await self._load_valid(token)
        account = invitation.user.account
        if account is None:
            raise Conflict("invitation account is unavailable")
        now = datetime.now(UTC)
        account.password_hash = hash_password(password)
        account.must_change_password = False
        account.status = RecordStatus.ACTIVE
        invitation.user.status = RecordStatus.ACTIVE
        invitation.user.disabled_at = None
        invitation.used_at = now
        await self.sessions.revoke_for_account(account.id, now)
        self.audit.record(
            actor_account_id=account.id,
            action="user.invitation_accepted",
            target_type="user",
            target_id=str(invitation.user_id),
            details={"invitation_id": str(invitation.id)},
        )
        await self.session.commit()
        return account.username
