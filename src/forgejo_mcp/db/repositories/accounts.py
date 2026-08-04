import uuid
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from forgejo_mcp.db.models import Account, AccountRole


class AccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def admin_id(self) -> uuid.UUID | None:
        return cast(
            uuid.UUID | None,
            await self.session.scalar(select(Account.id).where(Account.role == AccountRole.ADMIN)),
        )

    async def by_normalized_username(self, username: str) -> Account | None:
        return cast(
            Account | None,
            await self.session.scalar(
                select(Account).where(Account.normalized_username == username)
            ),
        )

    def add(self, account: Account) -> None:
        self.session.add(account)
