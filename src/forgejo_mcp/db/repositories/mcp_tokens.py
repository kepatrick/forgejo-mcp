import uuid
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from forgejo_mcp.db.models import McpToken, User


class McpTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, token: McpToken) -> None:
        self.session.add(token)

    async def get(self, token_id: uuid.UUID) -> McpToken | None:
        return cast(
            McpToken | None,
            await self.session.scalar(
                select(McpToken)
                .where(McpToken.id == token_id)
                .options(
                    selectinload(McpToken.user).selectinload(User.account),
                    selectinload(McpToken.user).selectinload(User.forgejo_credentials),
                )
            ),
        )

    async def candidates_for_prefix(self, token_prefix: str) -> list[McpToken]:
        records = await self.session.scalars(
            select(McpToken)
            .where(McpToken.token_prefix == token_prefix)
            .options(selectinload(McpToken.user))
        )
        return list(records.all())

    async def get_for_user(self, token_id: uuid.UUID, user_id: uuid.UUID) -> McpToken | None:
        return cast(
            McpToken | None,
            await self.session.scalar(
                select(McpToken).where(McpToken.id == token_id, McpToken.user_id == user_id)
            ),
        )

    async def list_for_user(self, user_id: uuid.UUID) -> list[McpToken]:
        return list(
            (
                await self.session.scalars(
                    select(McpToken)
                    .where(McpToken.user_id == user_id)
                    .order_by(McpToken.created_at.desc())
                )
            ).all()
        )

    async def list_all(self) -> list[McpToken]:
        return list(
            (
                await self.session.scalars(
                    select(McpToken)
                    .options(joinedload(McpToken.user).joinedload(User.account))
                    .order_by(McpToken.created_at.desc())
                )
            )
            .unique()
            .all()
        )
