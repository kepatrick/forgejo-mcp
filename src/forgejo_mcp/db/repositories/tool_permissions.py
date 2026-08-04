import uuid
from collections.abc import Iterable

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from forgejo_mcp.db.models import (
    McpToken,
    McpTokenToolGrant,
    ToolSetting,
    UserToolAllowance,
)
from forgejo_mcp.tools import ToolSpec


class ToolPermissionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def sync_registry(self, specs: Iterable[ToolSpec]) -> None:
        for spec in specs:
            statement = (
                insert(ToolSetting)
                .values(tool_name=spec.name, enabled=False, registry_version=spec.version)
                .on_conflict_do_update(
                    index_elements=[ToolSetting.tool_name],
                    set_={"registry_version": spec.version},
                )
            )
            await self.session.execute(statement)

    async def settings(self) -> dict[str, ToolSetting]:
        records = await self.session.scalars(select(ToolSetting))
        return {record.tool_name: record for record in records.all()}

    async def set_global_enabled(self, tool_name: str, enabled: bool) -> None:
        await self.session.execute(
            update(ToolSetting).where(ToolSetting.tool_name == tool_name).values(enabled=enabled)
        )

    async def allowance_names(self, user_id: uuid.UUID) -> set[str]:
        records = await self.session.scalars(
            select(UserToolAllowance.tool_name).where(UserToolAllowance.user_id == user_id)
        )
        return set(records.all())

    async def replace_allowances(self, user_id: uuid.UUID, tool_names: set[str]) -> None:
        await self.session.execute(
            delete(McpTokenToolGrant).where(
                McpTokenToolGrant.mcp_token_id.in_(
                    select(McpToken.id).where(McpToken.user_id == user_id)
                ),
                McpTokenToolGrant.tool_name.not_in(tool_names),
            )
        )
        await self.session.execute(
            delete(UserToolAllowance).where(UserToolAllowance.user_id == user_id)
        )
        self.session.add_all(
            UserToolAllowance(user_id=user_id, tool_name=name) for name in sorted(tool_names)
        )

    async def grant_names(self, token_id: uuid.UUID) -> set[str]:
        records = await self.session.scalars(
            select(McpTokenToolGrant.tool_name).where(McpTokenToolGrant.mcp_token_id == token_id)
        )
        return set(records.all())

    async def replace_grants(self, token_id: uuid.UUID, tool_names: set[str]) -> None:
        await self.session.execute(
            delete(McpTokenToolGrant).where(McpTokenToolGrant.mcp_token_id == token_id)
        )
        self.session.add_all(
            McpTokenToolGrant(mcp_token_id=token_id, tool_name=name) for name in sorted(tool_names)
        )
