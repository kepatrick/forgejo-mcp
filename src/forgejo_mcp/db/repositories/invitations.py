import uuid
from datetime import datetime
from typing import cast

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from forgejo_mcp.db.models import User, UserInvitation


class InvitationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, invitation: UserInvitation) -> None:
        self.session.add(invitation)

    async def by_token_hash(self, token_hash: str) -> UserInvitation | None:
        return cast(
            UserInvitation | None,
            await self.session.scalar(
                select(UserInvitation)
                .options(selectinload(UserInvitation.user).selectinload(User.account))
                .where(UserInvitation.token_hash == token_hash)
            ),
        )

    async def get_for_user(
        self, invitation_id: uuid.UUID, user_id: uuid.UUID
    ) -> UserInvitation | None:
        return cast(
            UserInvitation | None,
            await self.session.scalar(
                select(UserInvitation).where(
                    UserInvitation.id == invitation_id,
                    UserInvitation.user_id == user_id,
                )
            ),
        )

    async def revoke_active(self, user_id: uuid.UUID, purpose: str, revoked_at: datetime) -> None:
        await self.session.execute(
            update(UserInvitation)
            .where(
                UserInvitation.user_id == user_id,
                UserInvitation.purpose == purpose,
                UserInvitation.used_at.is_(None),
                UserInvitation.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
        )

    async def revoke_all_active(self, user_id: uuid.UUID, revoked_at: datetime) -> None:
        await self.session.execute(
            update(UserInvitation)
            .where(
                UserInvitation.user_id == user_id,
                UserInvitation.used_at.is_(None),
                UserInvitation.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
        )
