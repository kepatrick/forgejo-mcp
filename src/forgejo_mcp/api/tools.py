import uuid

from fastapi import APIRouter
from pydantic import BaseModel

from forgejo_mcp.api.dependencies import ToolPermissionServiceDep
from forgejo_mcp.authorization.policies import (
    AdminCsrfSession,
    AdminSession,
    UserCsrfSession,
    UserSession,
)
from forgejo_mcp.tools import ToolSpec

admin_router = APIRouter(prefix="/api/tools", tags=["tools-admin"])
user_allowance_router = APIRouter(prefix="/api/users", tags=["tools-admin"])
me_router = APIRouter(prefix="/api/me", tags=["tools"])


class ToolSettingRequest(BaseModel):
    enabled: bool


class ToolNamesRequest(BaseModel):
    tool_names: set[str]


class ToolResponse(BaseModel):
    name: str
    title: str
    description: str
    risk: str
    version: int
    input_schema: dict[str, object]
    globally_enabled: bool
    user_allowed: bool | None = None
    effective: bool | None = None


class ToolNamesResponse(BaseModel):
    tool_names: list[str]


def tool_response(
    spec: ToolSpec,
    globally_enabled: bool,
    *,
    user_allowed: bool | None = None,
    credential_configured: bool = False,
) -> ToolResponse:
    effective = None
    if user_allowed is not None:
        effective = globally_enabled and user_allowed and credential_configured
    return ToolResponse(
        name=spec.name,
        title=spec.title,
        description=spec.description,
        risk=spec.risk,
        version=spec.version,
        input_schema=spec.input_schema,
        globally_enabled=globally_enabled,
        user_allowed=user_allowed,
        effective=effective,
    )


@admin_router.get("", response_model=list[ToolResponse])
async def list_global_tools(
    _admin: AdminSession, service: ToolPermissionServiceDep
) -> list[ToolResponse]:
    return [tool_response(spec, enabled) for spec, enabled in await service.catalog()]


@admin_router.put("/{tool_name}", response_model=ToolResponse)
async def set_global_tool(
    tool_name: str,
    payload: ToolSettingRequest,
    admin: AdminCsrfSession,
    service: ToolPermissionServiceDep,
) -> ToolResponse:
    await service.set_global_enabled(
        actor_account_id=admin.account_id,
        tool_name=tool_name,
        enabled=payload.enabled,
    )
    for spec, enabled in await service.catalog():
        if spec.name == tool_name:
            return tool_response(spec, enabled)
    raise RuntimeError("updated tool disappeared from registry")


@user_allowance_router.get("/{user_id}/tools", response_model=ToolNamesResponse)
async def get_user_tool_allowances(
    user_id: uuid.UUID,
    _admin: AdminSession,
    service: ToolPermissionServiceDep,
) -> ToolNamesResponse:
    names = await service.allowances_for_user(user_id)
    return ToolNamesResponse(tool_names=sorted(names))


@user_allowance_router.put("/{user_id}/tools", response_model=ToolNamesResponse)
async def set_user_tool_allowances(
    user_id: uuid.UUID,
    payload: ToolNamesRequest,
    admin: AdminCsrfSession,
    service: ToolPermissionServiceDep,
) -> ToolNamesResponse:
    names = await service.replace_user_allowances(
        actor_account_id=admin.account_id,
        user_id=user_id,
        tool_names=payload.tool_names,
    )
    return ToolNamesResponse(tool_names=sorted(names))


@me_router.get("/tools", response_model=list[ToolResponse])
async def list_my_tools(
    current: UserSession, service: ToolPermissionServiceDep
) -> list[ToolResponse]:
    assert current.account.user_id is not None
    catalog = await service.catalog_for_user(current.account.user_id)
    return [
        tool_response(
            spec,
            globally_enabled,
            user_allowed=user_allowed,
            credential_configured=credential_configured,
        )
        for spec, globally_enabled, user_allowed, credential_configured in catalog
    ]


@me_router.get("/mcp-tokens/{token_id}/tools", response_model=ToolNamesResponse)
async def get_my_token_grants(
    token_id: uuid.UUID,
    current: UserSession,
    service: ToolPermissionServiceDep,
) -> ToolNamesResponse:
    assert current.account.user_id is not None
    names = await service.grants_for_token(
        user_id=current.account.user_id,
        token_id=token_id,
    )
    return ToolNamesResponse(tool_names=sorted(names))


@me_router.put("/mcp-tokens/{token_id}/tools", response_model=ToolNamesResponse)
async def set_my_token_grants(
    token_id: uuid.UUID,
    payload: ToolNamesRequest,
    current: UserCsrfSession,
    service: ToolPermissionServiceDep,
) -> ToolNamesResponse:
    assert current.account.user_id is not None
    names = await service.replace_token_grants(
        actor_account_id=current.account_id,
        user_id=current.account.user_id,
        token_id=token_id,
        tool_names=payload.tool_names,
    )
    return ToolNamesResponse(tool_names=sorted(names))
