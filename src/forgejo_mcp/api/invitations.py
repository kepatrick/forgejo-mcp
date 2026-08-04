from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from forgejo_mcp.api.dependencies import InvitationServiceDep
from forgejo_mcp.application.errors import ApplicationError
from forgejo_mcp.auth.rate_limit import LoginRateLimiter
from forgejo_mcp.auth.tokens import hash_token

router = APIRouter(prefix="/api/auth/invitations", tags=["invitations"])
_invitation_limiter = LoginRateLimiter(attempts=10, window_seconds=300)


class InvitationTokenRequest(BaseModel):
    token: str = Field(min_length=32, max_length=256)


class AcceptInvitationRequest(InvitationTokenRequest):
    password: str = Field(min_length=12, max_length=1024)


class InvitationContextResponse(BaseModel):
    display_name: str
    username: str
    forgejo_username: str
    expires_at: datetime


class InvitationAcceptedResponse(BaseModel):
    username: str


def rate_limit_key(request: Request, token: str) -> str:
    client_ip = request.client.host if request.client else "unknown"
    return f"{client_ip}:{hash_token(token)}"


@router.post("/context", response_model=InvitationContextResponse)
async def invitation_context(
    payload: InvitationTokenRequest, request: Request, service: InvitationServiceDep
) -> InvitationContextResponse:
    key = rate_limit_key(request, payload.token)
    _invitation_limiter.check(key)
    try:
        context = await service.context(payload.token)
    except ApplicationError:
        _invitation_limiter.failure(key)
        raise
    return InvitationContextResponse(
        display_name=context.display_name,
        username=context.username,
        forgejo_username=context.forgejo_username,
        expires_at=context.expires_at,
    )


@router.post("/accept", response_model=InvitationAcceptedResponse)
async def accept_invitation(
    payload: AcceptInvitationRequest, request: Request, service: InvitationServiceDep
) -> InvitationAcceptedResponse:
    key = rate_limit_key(request, payload.token)
    _invitation_limiter.check(key)
    try:
        username = await service.accept(payload.token, payload.password)
    except ApplicationError:
        _invitation_limiter.failure(key)
        raise
    _invitation_limiter.success(key)
    return InvitationAcceptedResponse(username=username)
