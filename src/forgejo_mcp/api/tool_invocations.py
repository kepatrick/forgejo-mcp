import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from forgejo_mcp.api.dependencies import ToolInvocationServiceDep
from forgejo_mcp.authorization.policies import AdminSession, UserSession
from forgejo_mcp.db.models import ToolInvocation

admin_router = APIRouter(prefix="/api/audit/tool-invocations", tags=["audit"])
me_router = APIRouter(prefix="/api/me/audit/tool-invocations", tags=["audit"])


class ToolInvocationResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    mcp_token_id: uuid.UUID | None
    user_display_name: str
    token_name: str
    forgejo_username: str
    tool_name: str
    tool_version: int
    risk: str
    started_at: datetime
    completed_at: datetime | None
    duration_ms: int | None
    status: str
    authorization_allowed: bool
    denial_reason: str | None
    redacted_arguments: dict[str, Any]
    target: dict[str, Any]
    result_summary: dict[str, Any]
    error_type: str | None
    forgejo_http_status: int | None
    input_truncated: bool
    result_truncated: bool


class ToolInvocationPageResponse(BaseModel):
    items: list[ToolInvocationResponse]
    page: int
    limit: int
    has_more: bool


PageQuery = Annotated[int, Query(ge=1, le=100_000)]
LimitQuery = Annotated[int, Query(ge=1, le=100)]


def invocation_response(record: ToolInvocation) -> ToolInvocationResponse:
    return ToolInvocationResponse(
        id=record.id,
        user_id=record.user_id,
        mcp_token_id=record.mcp_token_id,
        user_display_name=record.user_display_name,
        token_name=record.token_name,
        forgejo_username=record.forgejo_username,
        tool_name=record.tool_name,
        tool_version=record.tool_version,
        risk=record.risk,
        started_at=record.started_at,
        completed_at=record.completed_at,
        duration_ms=record.duration_ms,
        status=record.status,
        authorization_allowed=record.authorization_allowed,
        denial_reason=record.denial_reason,
        redacted_arguments=record.redacted_arguments,
        target=record.target,
        result_summary=record.result_summary,
        error_type=record.error_type,
        forgejo_http_status=record.forgejo_http_status,
        input_truncated=record.input_truncated,
        result_truncated=record.result_truncated,
    )


async def _list(
    service: ToolInvocationServiceDep,
    *,
    user_id: uuid.UUID | None,
    token_id: uuid.UUID | None,
    tool_name: str | None,
    status: str | None,
    started_after: datetime | None,
    started_before: datetime | None,
    page: int,
    limit: int,
) -> ToolInvocationPageResponse:
    records = await service.list_invocations(
        user_id=user_id,
        token_id=token_id,
        tool_name=tool_name,
        status=status,
        started_after=started_after,
        started_before=started_before,
        page=page,
        limit=limit,
    )
    return ToolInvocationPageResponse(
        items=[invocation_response(record) for record in records[:limit]],
        page=page,
        limit=limit,
        has_more=len(records) > limit,
    )


@admin_router.get("", response_model=ToolInvocationPageResponse)
async def list_all_invocations(
    _admin: AdminSession,
    service: ToolInvocationServiceDep,
    user_id: uuid.UUID | None = None,
    token_id: uuid.UUID | None = None,
    tool_name: str | None = Query(default=None, max_length=100),
    status: str | None = None,
    started_after: datetime | None = None,
    started_before: datetime | None = None,
    page: PageQuery = 1,
    limit: LimitQuery = 30,
) -> ToolInvocationPageResponse:
    return await _list(
        service,
        user_id=user_id,
        token_id=token_id,
        tool_name=tool_name,
        status=status,
        started_after=started_after,
        started_before=started_before,
        page=page,
        limit=limit,
    )


@admin_router.get("/{invocation_id}", response_model=ToolInvocationResponse)
async def get_any_invocation(
    invocation_id: uuid.UUID,
    _admin: AdminSession,
    service: ToolInvocationServiceDep,
) -> ToolInvocationResponse:
    return invocation_response(await service.get_invocation(invocation_id, user_id=None))


@me_router.get("", response_model=ToolInvocationPageResponse)
async def list_my_invocations(
    current: UserSession,
    service: ToolInvocationServiceDep,
    token_id: uuid.UUID | None = None,
    tool_name: str | None = Query(default=None, max_length=100),
    status: str | None = None,
    started_after: datetime | None = None,
    started_before: datetime | None = None,
    page: PageQuery = 1,
    limit: LimitQuery = 30,
) -> ToolInvocationPageResponse:
    assert current.account.user_id is not None
    return await _list(
        service,
        user_id=current.account.user_id,
        token_id=token_id,
        tool_name=tool_name,
        status=status,
        started_after=started_after,
        started_before=started_before,
        page=page,
        limit=limit,
    )


@me_router.get("/{invocation_id}", response_model=ToolInvocationResponse)
async def get_my_invocation(
    invocation_id: uuid.UUID,
    current: UserSession,
    service: ToolInvocationServiceDep,
) -> ToolInvocationResponse:
    assert current.account.user_id is not None
    return invocation_response(
        await service.get_invocation(invocation_id, user_id=current.account.user_id)
    )
