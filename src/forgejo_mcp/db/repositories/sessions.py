import uuid
from datetime import datetime
from typing import cast

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from forgejo_mcp.db.models import Account, Session


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, record: Session) -> None:
        self.session.add(record)

    async def by_token_hash(self, token_hash: str) -> Session | None:
        return cast(
            Session | None,
            await self.session.scalar(
                select(Session)
                .options(selectinload(Session.account).selectinload(Account.user))
                .where(Session.session_token_hash == token_hash)
            ),
        )

    async def active_for_account(self, account_id: uuid.UUID) -> list[Session]:
        records = await self.session.scalars(
            select(Session)
            .where(Session.account_id == account_id, Session.revoked_at.is_(None))
            .order_by(Session.created_at.desc())
        )
        return list(records.all())

    async def revoke_for_account(
        self, account_id: uuid.UUID, revoked_at: datetime, except_id: uuid.UUID | None = None
    ) -> None:
        statement = update(Session).where(
            Session.account_id == account_id, Session.revoked_at.is_(None)
        )
        if except_id is not None:
            statement = statement.where(Session.id != except_id)
        await self.session.execute(statement.values(revoked_at=revoked_at))

    async def get_for_account(self, session_id: uuid.UUID, account_id: uuid.UUID) -> Session | None:
        return cast(
            Session | None,
            await self.session.scalar(
                select(Session).where(Session.id == session_id, Session.account_id == account_id)
            ),
        )
