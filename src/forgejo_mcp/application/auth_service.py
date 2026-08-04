import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from forgejo_mcp.application.errors import AuthenticationFailed, NotFound, ValidationFailed
from forgejo_mcp.auth.passwords import (
    hash_password,
    normalize_username,
    validate_password,
    verify_password,
)
from forgejo_mcp.auth.tokens import hash_token, new_token
from forgejo_mcp.db.models import Account, RecordStatus, Session
from forgejo_mcp.db.repositories import (
    AccountRepository,
    AuditRepository,
    SessionRepository,
)

_dummy_password_hash = hash_password("not-a-real-account-password")


@dataclass(frozen=True)
class LoginResult:
    account: Account
    session: Session
    session_token: str
    csrf_token: str


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.accounts = AccountRepository(session)
        self.audit = AuditRepository(session)
        self.sessions = SessionRepository(session)

    async def admin_configured(self) -> bool:
        return await self.accounts.admin_id() is not None

    async def login(
        self,
        *,
        username: str,
        password: str,
        client_ip: str | None,
        user_agent: str | None,
        ttl_hours: int,
    ) -> LoginResult:
        account = await self.accounts.by_normalized_username(normalize_username(username))
        password_hash = account.password_hash if account is not None else _dummy_password_hash
        password_valid = verify_password(password_hash, password)
        if account is None or not password_valid or account.status != RecordStatus.ACTIVE:
            raise AuthenticationFailed("invalid username or password")

        session_token = new_token()
        csrf_token = new_token()
        now = datetime.now(UTC)
        record = Session(
            account_id=account.id,
            session_token_hash=hash_token(session_token),
            csrf_token_hash=hash_token(csrf_token),
            expires_at=now + timedelta(hours=ttl_hours),
            last_seen_at=now,
            client_ip=client_ip,
            user_agent=(user_agent or "")[:512] or None,
        )
        self.sessions.add(record)
        await self.session.flush()
        account.last_login_at = now
        self.audit.record(
            actor_account_id=account.id,
            action="account.login",
            target_type="session",
            target_id=str(record.id),
        )
        await self.session.commit()
        return LoginResult(account, record, session_token, csrf_token)

    async def change_password(
        self, current: Session, current_password: str, new_password: str
    ) -> Account:
        account = current.account
        if not verify_password(account.password_hash, current_password):
            raise ValidationFailed("current password is incorrect")
        try:
            validate_password(new_password)
        except ValueError as error:
            raise ValidationFailed(str(error)) from error
        if verify_password(account.password_hash, new_password):
            raise ValidationFailed("new password must be different")

        account.password_hash = hash_password(new_password)
        account.must_change_password = False
        await self.sessions.revoke_for_account(account.id, datetime.now(UTC), except_id=current.id)
        self.audit.record(
            actor_account_id=account.id,
            action="account.password_changed",
            target_type="account",
            target_id=str(account.id),
            details={"other_sessions_revoked": True},
        )
        await self.session.commit()
        return account

    async def logout(self, current: Session) -> None:
        current.revoked_at = datetime.now(UTC)
        self.audit.record(
            actor_account_id=current.account_id,
            action="account.logout",
            target_type="session",
            target_id=str(current.id),
        )
        await self.session.commit()

    async def list_sessions(self, current: Session) -> list[Session]:
        return await self.sessions.active_for_account(current.account_id)

    async def revoke_session(self, current: Session, session_id: uuid.UUID) -> bool:
        target = await self.sessions.get_for_account(session_id, current.account_id)
        if target is None:
            raise NotFound("session not found")
        is_current = target.id == current.id
        target.revoked_at = datetime.now(UTC)
        self.audit.record(
            actor_account_id=current.account_id,
            action="account.session_revoked",
            target_type="session",
            target_id=str(target.id),
            details={"current_session": is_current},
        )
        await self.session.commit()
        return is_current
