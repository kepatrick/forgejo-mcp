import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from forgejo_mcp.api.dependencies import McpTokenServiceDep
from forgejo_mcp.authorization.policies import (
    AdminCsrfSession,
    AdminSession,
    UserCsrfSession,
    UserSession,
)
from forgejo_mcp.db.models import McpToken

me_router = APIRouter(prefix="/api/me/mcp-tokens", tags=["mcp-tokens"])
admin_router = APIRouter(prefix="/api/mcp-tokens", tags=["mcp-tokens-admin"])


class CreateMcpTokenRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    expires_at: datetime | None = None


class McpTokenResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    description: str | None
    token_prefix: str
    status: str
    expires_at: datetime | None
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class CreatedMcpTokenResponse(McpTokenResponse):
    token: str


class AdminMcpTokenResponse(McpTokenResponse):
    user_display_name: str
    username: str


def token_status(record: McpToken) -> str:
    if record.revoked_at is not None:
        return "revoked"
    if not record.enabled:
        return "disabled"
    if record.expires_at is not None and record.expires_at <= datetime.now(UTC):
        return "expired"
    return "active"


def token_response(record: McpToken) -> McpTokenResponse:
    return McpTokenResponse(
        id=record.id,
        user_id=record.user_id,
        name=record.name,
        description=record.description,
        token_prefix=record.token_prefix,
        status=token_status(record),
        expires_at=record.expires_at,
        created_at=record.created_at,
        last_used_at=record.last_used_at,
        revoked_at=record.revoked_at,
    )


@me_router.get("", response_model=list[McpTokenResponse])
async def list_my_tokens(
    current: UserSession, service: McpTokenServiceDep
) -> list[McpTokenResponse]:
    assert current.account.user_id is not None
    return [
        token_response(record) for record in await service.list_for_user(current.account.user_id)
    ]


@me_router.post("", response_model=CreatedMcpTokenResponse, status_code=status.HTTP_201_CREATED)
async def create_my_token(
    payload: CreateMcpTokenRequest,
    current: UserCsrfSession,
    service: McpTokenServiceDep,
) -> CreatedMcpTokenResponse:
    assert current.account.user_id is not None
    created = await service.create(
        actor_account_id=current.account_id,
        user_id=current.account.user_id,
        name=payload.name,
        description=payload.description,
        expires_at=payload.expires_at,
    )
    response = token_response(created.record)
    return CreatedMcpTokenResponse(**response.model_dump(), token=created.token)


@me_router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_my_token(
    token_id: uuid.UUID,
    current: UserCsrfSession,
    service: McpTokenServiceDep,
) -> None:
    assert current.account.user_id is not None
    await service.revoke_for_user(
        actor_account_id=current.account_id,
        user_id=current.account.user_id,
        token_id=token_id,
    )


@admin_router.get("", response_model=list[AdminMcpTokenResponse])
async def list_all_tokens(
    _admin: AdminSession, service: McpTokenServiceDep
) -> list[AdminMcpTokenResponse]:
    responses: list[AdminMcpTokenResponse] = []
    for record in await service.list_all():
        if record.user.account is None:
            raise RuntimeError("MCP token user account relationship was not loaded")
        response = token_response(record)
        responses.append(
            AdminMcpTokenResponse(
                **response.model_dump(),
                user_display_name=record.user.display_name,
                username=record.user.account.username,
            )
        )
    return responses


@admin_router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_revoke_token(
    token_id: uuid.UUID,
    admin: AdminCsrfSession,
    service: McpTokenServiceDep,
) -> None:
    await service.revoke_as_admin(
        actor_account_id=admin.account_id,
        token_id=token_id,
    )
