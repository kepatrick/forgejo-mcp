import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from forgejo_mcp.application.errors import Conflict, NotFound, ValidationFailed
from forgejo_mcp.auth.passwords import hash_password, normalize_username
from forgejo_mcp.auth.tokens import hash_token, new_token
from forgejo_mcp.db.models import (
    Account,
    AccountRole,
    CredentialStatus,
    RecordStatus,
    User,
    UserInvitation,
)
from forgejo_mcp.db.repositories import (
    AccountRepository,
    AuditRepository,
    ForgejoCredentialRepository,
    InvitationRepository,
    SessionRepository,
    UserRepository,
)

INVITATION_TTL_MINUTES = 30


@dataclass(frozen=True)
class InvitationResult:
    id: uuid.UUID
    path: str
    expires_at: datetime


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.accounts = AccountRepository(session)
        self.audit = AuditRepository(session)
        self.credentials = ForgejoCredentialRepository(session)
        self.invitations = InvitationRepository(session)
        self.sessions = SessionRepository(session)
        self.users = UserRepository(session)

    async def list_users(self) -> list[User]:
        return await self.users.list()

    async def get_user(self, user_id: uuid.UUID) -> User:
        user = await self.users.get(user_id)
        if user is None:
            raise NotFound("user not found")
        return user

    async def create_user(
        self,
        *,
        actor_account_id: uuid.UUID,
        display_name: str,
        username: str,
        forgejo_username: str,
    ) -> User:
        display_name = display_name.strip()
        username = username.strip()
        forgejo_username = forgejo_username.strip()
        if not display_name or not username or not forgejo_username:
            raise ValidationFailed("user fields cannot be blank")
        user = User(
            display_name=display_name,
            expected_forgejo_username=forgejo_username,
            normalized_forgejo_username=normalize_username(forgejo_username),
            status=RecordStatus.PENDING,
            forgejo_credentials=[],
        )
        account = Account(
            user=user,
            username=username,
            normalized_username=normalize_username(username),
            role=AccountRole.USER,
            password_hash=hash_password(new_token()),
            must_change_password=True,
            status=RecordStatus.PENDING,
        )
        self.users.add(user)
        self.accounts.add(account)
        try:
            await self.session.flush()
        except IntegrityError as error:
            await self.session.rollback()
            raise Conflict("dashboard or Forgejo username already exists") from error
        self.audit.record(
            actor_account_id=actor_account_id,
            action="user.created",
            target_type="user",
            target_id=str(user.id),
            details={"dashboard_username": username, "forgejo_username": forgejo_username},
        )
        await self.session.commit()
        return user

    async def update_user(
        self,
        *,
        actor_account_id: uuid.UUID,
        user_id: uuid.UUID,
        display_name: str,
        forgejo_username: str,
    ) -> User:
        user = await self.get_user(user_id)
        display_name = display_name.strip()
        forgejo_username = forgejo_username.strip()
        if not display_name or not forgejo_username:
            raise ValidationFailed("user fields cannot be blank")
        normalized_forgejo_username = normalize_username(forgejo_username)
        credential_revoked = False
        if normalized_forgejo_username != user.normalized_forgejo_username:
            credential = await self.credentials.active_for_user(user.id)
            if credential is not None:
                credential.status = CredentialStatus.REVOKED
                credential.encrypted_token = None
                credential.nonce = None
                credential.revoked_at = datetime.now(UTC)
                credential_revoked = True
        user.display_name = display_name
        user.expected_forgejo_username = forgejo_username
        user.normalized_forgejo_username = normalized_forgejo_username
        try:
            await self.session.flush()
        except IntegrityError as error:
            await self.session.rollback()
            raise Conflict("Forgejo username already exists") from error
        self.audit.record(
            actor_account_id=actor_account_id,
            action="user.updated",
            target_type="user",
            target_id=str(user.id),
            details={"credential_revoked": credential_revoked},
        )
        await self.session.commit()
        return user

    async def disable_user(self, *, actor_account_id: uuid.UUID, user_id: uuid.UUID) -> User:
        user = await self.get_user(user_id)
        now = datetime.now(UTC)
        user.status = RecordStatus.DISABLED
        user.disabled_at = now
        if user.account is not None:
            user.account.status = RecordStatus.DISABLED
            await self.sessions.revoke_for_account(user.account.id, now)
        await self.invitations.revoke_all_active(user.id, now)
        credential = await self.credentials.active_for_user(user.id)
        if credential is not None:
            credential.status = CredentialStatus.REVOKED
            credential.encrypted_token = None
            credential.nonce = None
            credential.revoked_at = now
        self.audit.record(
            actor_account_id=actor_account_id,
            action="user.disabled",
            target_type="user",
            target_id=str(user.id),
        )
        await self.session.commit()
        return user

    async def enable_user(self, *, actor_account_id: uuid.UUID, user_id: uuid.UUID) -> User:
        user = await self.get_user(user_id)
        if user.account is None:
            raise Conflict("user account is missing")
        next_status = (
            RecordStatus.PENDING if user.account.must_change_password else RecordStatus.ACTIVE
        )
        user.status = next_status
        user.account.status = next_status
        user.disabled_at = None
        self.audit.record(
            actor_account_id=actor_account_id,
            action="user.enabled",
            target_type="user",
            target_id=str(user.id),
            details={"status": next_status},
        )
        await self.session.commit()
        return user

    async def create_invitation(
        self, *, actor_account_id: uuid.UUID, user_id: uuid.UUID
    ) -> InvitationResult:
        user = await self.get_user(user_id)
        if user.status == RecordStatus.DISABLED:
            raise Conflict("disabled user cannot be invited")
        now = datetime.now(UTC)
        await self.invitations.revoke_active(user.id, "activation", now)
        raw_token = new_token()
        invitation = UserInvitation(
            user_id=user.id,
            token_hash=hash_token(raw_token),
            purpose="activation",
            expires_at=now + timedelta(minutes=INVITATION_TTL_MINUTES),
            attempt_count=0,
            created_by_account_id=actor_account_id,
        )
        self.invitations.add(invitation)
        await self.session.flush()
        self.audit.record(
            actor_account_id=actor_account_id,
            action="user.invitation_created",
            target_type="user",
            target_id=str(user.id),
            details={
                "invitation_id": str(invitation.id),
                "expires_at": invitation.expires_at.isoformat(),
            },
        )
        await self.session.commit()
        return InvitationResult(
            id=invitation.id,
            path=f"/#/invite?token={raw_token}",
            expires_at=invitation.expires_at,
        )

    async def revoke_invitation(
        self, *, actor_account_id: uuid.UUID, user_id: uuid.UUID, invitation_id: uuid.UUID
    ) -> None:
        invitation = await self.invitations.get_for_user(invitation_id, user_id)
        if invitation is None:
            raise NotFound("invitation not found")
        invitation.revoked_at = datetime.now(UTC)
        self.audit.record(
            actor_account_id=actor_account_id,
            action="user.invitation_revoked",
            target_type="user",
            target_id=str(user_id),
            details={"invitation_id": str(invitation.id)},
        )
        await self.session.commit()
