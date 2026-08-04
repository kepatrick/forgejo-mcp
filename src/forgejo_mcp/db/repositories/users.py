import uuid
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from forgejo_mcp.db.models import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self) -> list[User]:
        records = await self.session.scalars(
            select(User)
            .options(selectinload(User.account), selectinload(User.forgejo_credentials))
            .order_by(User.created_at)
        )
        return list(records.all())

    async def get(self, user_id: uuid.UUID) -> User | None:
        return cast(
            User | None,
            await self.session.scalar(
                select(User)
                .options(selectinload(User.account), selectinload(User.forgejo_credentials))
                .where(User.id == user_id)
            ),
        )

    def add(self, user: User) -> None:
        self.session.add(user)
