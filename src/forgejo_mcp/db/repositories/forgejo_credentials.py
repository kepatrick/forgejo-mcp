import uuid
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from forgejo_mcp.db.models import CredentialStatus, ForgejoCredential


class ForgejoCredentialRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def active_for_user(self, user_id: uuid.UUID) -> ForgejoCredential | None:
        return cast(
            ForgejoCredential | None,
            await self.session.scalar(
                select(ForgejoCredential).where(
                    ForgejoCredential.user_id == user_id,
                    ForgejoCredential.status == CredentialStatus.ACTIVE,
                )
            ),
        )

    def add(self, credential: ForgejoCredential) -> None:
        self.session.add(credential)
