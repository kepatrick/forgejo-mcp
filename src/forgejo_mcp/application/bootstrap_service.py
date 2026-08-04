import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forgejo_mcp.auth.passwords import hash_password, normalize_username
from forgejo_mcp.config import Settings
from forgejo_mcp.db.models import Account, AccountRole, RecordStatus
from forgejo_mcp.db.repositories import AccountRepository, AuditRepository

logger = logging.getLogger(__name__)


async def bootstrap_admin(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> bool:
    """Create the first admin only when no admin exists and a secret file is configured."""
    async with session_factory() as session:
        accounts = AccountRepository(session)
        if await accounts.admin_id() is not None:
            return False

        password_file = settings.bootstrap_admin_password_file
        if password_file is None:
            logger.warning("No admin exists; configure FMCP_BOOTSTRAP_ADMIN_PASSWORD_FILE")
            return False

        password = password_file.read_text(encoding="utf-8").strip()
        username = settings.bootstrap_admin_username.strip()
        account = Account(
            username=username,
            normalized_username=normalize_username(username),
            role=AccountRole.ADMIN,
            password_hash=hash_password(password),
            must_change_password=True,
            status=RecordStatus.ACTIVE,
        )
        accounts.add(account)
        await session.flush()
        AuditRepository(session).record(
            actor_account_id=account.id,
            action="admin.bootstrap_created",
            target_type="account",
            target_id=str(account.id),
        )
        await session.commit()
        logger.info("Bootstrap admin account created")
        return True
