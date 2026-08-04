import uuid
from datetime import datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from forgejo_mcp.db.models import ToolInvocation


class ToolInvocationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, invocation: ToolInvocation) -> None:
        self.session.add(invocation)

    async def list(
        self,
        *,
        user_id: uuid.UUID | None,
        token_id: uuid.UUID | None,
        tool_name: str | None,
        status: str | None,
        started_after: datetime | None,
        started_before: datetime | None,
        page: int,
        limit: int,
    ) -> list[ToolInvocation]:
        statement = select(ToolInvocation)
        if user_id is not None:
            statement = statement.where(ToolInvocation.user_id == user_id)
        if token_id is not None:
            statement = statement.where(ToolInvocation.mcp_token_id == token_id)
        if tool_name is not None:
            statement = statement.where(ToolInvocation.tool_name == tool_name)
        if status is not None:
            statement = statement.where(ToolInvocation.status == status)
        if started_after is not None:
            statement = statement.where(ToolInvocation.started_at >= started_after)
        if started_before is not None:
            statement = statement.where(ToolInvocation.started_at < started_before)
        records = await self.session.scalars(
            statement.order_by(ToolInvocation.started_at.desc())
            .offset((page - 1) * limit)
            .limit(limit + 1)
        )
        return list(records.all())

    async def get(self, invocation_id: uuid.UUID) -> ToolInvocation | None:
        return cast(
            ToolInvocation | None,
            await self.session.scalar(
                select(ToolInvocation).where(ToolInvocation.id == invocation_id)
            ),
        )

    async def get_for_user(
        self, invocation_id: uuid.UUID, user_id: uuid.UUID
    ) -> ToolInvocation | None:
        return cast(
            ToolInvocation | None,
            await self.session.scalar(
                select(ToolInvocation).where(
                    ToolInvocation.id == invocation_id,
                    ToolInvocation.user_id == user_id,
                )
            ),
        )
