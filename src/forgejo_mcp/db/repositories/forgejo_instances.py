from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from forgejo_mcp.db.models import ForgejoInstance


class ForgejoInstanceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def primary(self) -> ForgejoInstance | None:
        return cast(
            ForgejoInstance | None,
            await self.session.scalar(
                select(ForgejoInstance).where(ForgejoInstance.slug == "primary")
            ),
        )

    def add(self, instance: ForgejoInstance) -> None:
        self.session.add(instance)
