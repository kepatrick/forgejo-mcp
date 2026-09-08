import uuid
from datetime import datetime
from typing import cast

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from forgejo_mcp.db.models import (
    McpToken,
    OAuthAccessToken,
    OAuthRefreshToken,
    OAuthTokenFamily,
)


async def lock_oauth_family(
    session: AsyncSession,
    family_id: uuid.UUID,
) -> OAuthTokenFamily | None:
    return cast(
        OAuthTokenFamily | None,
        await session.scalar(
            select(OAuthTokenFamily).where(OAuthTokenFamily.id == family_id).with_for_update()
        ),
    )


async def oauth_family_for_mcp_token(
    session: AsyncSession,
    token_id: uuid.UUID,
) -> uuid.UUID | None:
    return cast(
        uuid.UUID | None,
        await session.scalar(
            select(OAuthRefreshToken.family_id)
            .join(
                OAuthAccessToken,
                OAuthAccessToken.refresh_token_id == OAuthRefreshToken.id,
            )
            .where(OAuthAccessToken.mcp_token_id == token_id)
        ),
    )


async def revoke_oauth_family(
    session: AsyncSession,
    family_id: uuid.UUID,
    revoked_at: datetime,
) -> tuple[uuid.UUID, ...]:
    family = await lock_oauth_family(session, family_id)
    if family is None:
        return ()
    effective_revoked_at = family.revoked_at or revoked_at
    family.revoked_at = effective_revoked_at
    token_ids = tuple(
        token_id
        for token_id in (
            await session.scalars(
                select(OAuthRefreshToken.mcp_token_id).where(
                    OAuthRefreshToken.family_id == family_id,
                    OAuthRefreshToken.mcp_token_id.is_not(None),
                )
            )
        ).all()
        if token_id is not None
    )
    await session.execute(
        update(OAuthRefreshToken)
        .where(OAuthRefreshToken.family_id == family_id)
        .values(revoked_at=effective_revoked_at)
    )
    if token_ids:
        await session.execute(
            update(McpToken)
            .where(McpToken.id.in_(token_ids))
            .values(enabled=False, revoked_at=effective_revoked_at)
        )
        await session.execute(
            update(OAuthAccessToken)
            .where(OAuthAccessToken.mcp_token_id.in_(token_ids))
            .values(revoked_at=effective_revoked_at)
        )
    return token_ids
