import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from forgejo_mcp.application.errors import InvalidOperation, NotFound, ValidationFailed
from forgejo_mcp.authorization.tools import (
    ToolAuthorizationContext,
    ToolAuthorizationDecision,
    authorize_tool,
)
from forgejo_mcp.db.models import CredentialStatus, McpToken, RecordStatus, ToolSetting
from forgejo_mcp.db.repositories import (
    AuditRepository,
    McpTokenRepository,
    ToolPermissionRepository,
    UserRepository,
)
from forgejo_mcp.tools import TOOL_REGISTRY, ToolSpec, get_tool, list_tools


class ToolPermissionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditRepository(session)
        self.permissions = ToolPermissionRepository(session)
        self.tokens = McpTokenRepository(session)
        self.users = UserRepository(session)

    async def catalog(self) -> list[tuple[ToolSpec, bool]]:
        await self._sync_registry()
        settings = await self.permissions.settings()
        return [(spec, _setting_enabled(settings, spec.name)) for spec in list_tools()]

    async def catalog_for_user(self, user_id: uuid.UUID) -> list[tuple[ToolSpec, bool, bool, bool]]:
        user = await self.users.get(user_id)
        if user is None:
            raise NotFound("user not found")
        catalog = await self.catalog()
        allowances = await self.permissions.allowance_names(user_id)
        credential_configured = any(
            credential.status == CredentialStatus.ACTIVE for credential in user.forgejo_credentials
        )
        return [
            (spec, globally_enabled, spec.name in allowances, credential_configured)
            for spec, globally_enabled in catalog
        ]

    async def set_global_enabled(
        self, *, actor_account_id: uuid.UUID, tool_name: str, enabled: bool
    ) -> None:
        self._require_tools({tool_name})
        await self._sync_registry()
        await self.permissions.set_global_enabled(tool_name, enabled)
        self.audit.record(
            actor_account_id=actor_account_id,
            action="tool.global_setting_updated",
            target_type="tool",
            target_id=tool_name,
            details={"enabled": enabled},
        )
        await self.session.commit()

    async def allowances_for_user(self, user_id: uuid.UUID) -> set[str]:
        await self._sync_registry()
        await self._require_user(user_id)
        return await self.permissions.allowance_names(user_id)

    async def replace_user_allowances(
        self,
        *,
        actor_account_id: uuid.UUID,
        user_id: uuid.UUID,
        tool_names: set[str],
    ) -> set[str]:
        await self._require_user(user_id)
        self._require_tools(tool_names)
        await self._sync_registry()
        await self.permissions.replace_allowances(user_id, tool_names)
        self.audit.record(
            actor_account_id=actor_account_id,
            action="tool.user_allowances_updated",
            target_type="user",
            target_id=str(user_id),
            details={"tool_names": sorted(tool_names)},
        )
        await self.session.commit()
        return tool_names

    async def grants_for_token(self, *, user_id: uuid.UUID, token_id: uuid.UUID) -> set[str]:
        await self._sync_registry()
        await self._owned_token(user_id, token_id)
        return await self.permissions.grant_names(token_id)

    async def replace_token_grants(
        self,
        *,
        actor_account_id: uuid.UUID,
        user_id: uuid.UUID,
        token_id: uuid.UUID,
        tool_names: set[str],
    ) -> set[str]:
        await self._owned_token(user_id, token_id)
        self._require_tools(tool_names)
        await self._sync_registry()
        allowances = await self.permissions.allowance_names(user_id)
        if not tool_names <= allowances:
            raise ValidationFailed("token grants must be a subset of the user tool allowance")
        await self.permissions.replace_grants(token_id, tool_names)
        self.audit.record(
            actor_account_id=actor_account_id,
            action="tool.token_grants_updated",
            target_type="mcp_token",
            target_id=str(token_id),
            details={"tool_names": sorted(tool_names)},
        )
        await self.session.commit()
        return tool_names

    async def decision(self, *, token_id: uuid.UUID, tool_name: str) -> ToolAuthorizationDecision:
        spec = get_tool(tool_name)
        await self._sync_registry()
        record = await self.tokens.get(token_id)
        if spec is None or record is None:
            return authorize_tool(_context(token_valid=False))
        settings = await self.permissions.settings()
        allowances = await self.permissions.allowance_names(record.user_id)
        grants = await self.permissions.grant_names(record.id)
        now = datetime.now(UTC)
        token_valid = (
            record.enabled
            and record.revoked_at is None
            and (record.expires_at is None or record.expires_at > now)
        )
        credential_configured = any(
            credential.status == CredentialStatus.ACTIVE
            for credential in record.user.forgejo_credentials
        )
        return authorize_tool(
            ToolAuthorizationContext(
                token_valid=token_valid,
                user_enabled=record.user.status == RecordStatus.ACTIVE,
                global_tool_enabled=_setting_enabled(settings, tool_name),
                user_allowed_tool=tool_name in allowances,
                token_has_tool_grant=tool_name in grants,
                forgejo_credential_configured=credential_configured,
            )
        )

    async def _sync_registry(self) -> None:
        await self.permissions.sync_registry(list_tools())

    async def _require_user(self, user_id: uuid.UUID) -> None:
        if await self.users.get(user_id) is None:
            raise NotFound("user not found")

    async def _owned_token(self, user_id: uuid.UUID, token_id: uuid.UUID) -> McpToken:
        record = await self.tokens.get_for_user(token_id, user_id)
        if record is None:
            raise NotFound("MCP token not found")
        if record.revoked_at is not None:
            raise InvalidOperation("cannot modify grants for a revoked MCP token")
        return record

    @staticmethod
    def _require_tools(tool_names: set[str]) -> None:
        unknown = tool_names - TOOL_REGISTRY.keys()
        if unknown:
            raise ValidationFailed(f"unknown tools: {', '.join(sorted(unknown))}")


def _setting_enabled(settings: dict[str, ToolSetting], tool_name: str) -> bool:
    setting = settings.get(tool_name)
    return setting.enabled if setting is not None else False


def _context(*, token_valid: bool) -> ToolAuthorizationContext:
    return ToolAuthorizationContext(
        token_valid=token_valid,
        user_enabled=False,
        global_tool_enabled=False,
        user_allowed_tool=False,
        token_has_tool_grant=False,
        forgejo_credential_configured=False,
    )
