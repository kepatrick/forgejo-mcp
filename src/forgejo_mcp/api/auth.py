import uuid
from datetime import datetime

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field

from forgejo_mcp.api.dependencies import AuthServiceDep
from forgejo_mcp.application.errors import AuthenticationFailed
from forgejo_mcp.auth.passwords import normalize_username
from forgejo_mcp.auth.rate_limit import LoginRateLimiter
from forgejo_mcp.auth.session import CSRF_COOKIE, SESSION_COOKIE, CsrfSession, CurrentSession
from forgejo_mcp.config import Settings
from forgejo_mcp.db.models import Account

router = APIRouter(prefix="/api/auth", tags=["authentication"])
_login_limiter = LoginRateLimiter()


class AuthStatusResponse(BaseModel):
    admin_configured: bool


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)


class AccountResponse(BaseModel):
    id: uuid.UUID
    username: str
    role: str
    must_change_password: bool


class SessionResponse(BaseModel):
    id: uuid.UUID
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime | None
    client_ip: str | None
    user_agent: str | None
    current: bool


def account_response(account: Account) -> AccountResponse:
    return AccountResponse(
        id=account.id,
        username=account.username,
        role=account.role,
        must_change_password=account.must_change_password,
    )


def set_auth_cookies(
    response: Response, settings: Settings, session_token: str, csrf_token: str
) -> None:
    max_age = settings.session_ttl_hours * 60 * 60
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        httponly=True,
        secure=settings.use_secure_cookies,
        samesite="strict",
        path="/",
        max_age=max_age,
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        httponly=False,
        secure=settings.use_secure_cookies,
        samesite="strict",
        path="/",
        max_age=max_age,
    )


def clear_auth_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        SESSION_COOKIE, path="/", secure=settings.use_secure_cookies, samesite="strict"
    )
    response.delete_cookie(
        CSRF_COOKIE, path="/", secure=settings.use_secure_cookies, samesite="strict"
    )


@router.get("/status", response_model=AuthStatusResponse)
async def auth_status(service: AuthServiceDep) -> AuthStatusResponse:
    return AuthStatusResponse(admin_configured=await service.admin_configured())


@router.post("/login", response_model=AccountResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    service: AuthServiceDep,
) -> AccountResponse:
    normalized = normalize_username(payload.username)
    client_ip = request.client.host if request.client else "unknown"
    rate_limit_key = f"{client_ip}:{normalized}"
    _login_limiter.check(rate_limit_key)
    try:
        result = await service.login(
            username=payload.username,
            password=payload.password,
            client_ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            ttl_hours=request.app.state.settings.session_ttl_hours,
        )
    except AuthenticationFailed:
        _login_limiter.failure(rate_limit_key)
        raise
    _login_limiter.success(rate_limit_key)
    set_auth_cookies(response, request.app.state.settings, result.session_token, result.csrf_token)
    return account_response(result.account)


@router.get("/me", response_model=AccountResponse)
async def me(current: CurrentSession) -> AccountResponse:
    return account_response(current.account)


@router.post("/change-password", response_model=AccountResponse)
async def change_password(
    payload: ChangePasswordRequest,
    current: CsrfSession,
    service: AuthServiceDep,
) -> AccountResponse:
    account = await service.change_password(current, payload.current_password, payload.new_password)
    return account_response(account)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    current: CsrfSession,
    service: AuthServiceDep,
) -> None:
    await service.logout(current)
    clear_auth_cookies(response, request.app.state.settings)


@router.get("/sessions", response_model=list[SessionResponse])
async def list_sessions(current: CurrentSession, service: AuthServiceDep) -> list[SessionResponse]:
    records = await service.list_sessions(current)
    return [
        SessionResponse(
            id=record.id,
            created_at=record.created_at,
            expires_at=record.expires_at,
            last_seen_at=record.last_seen_at,
            client_ip=record.client_ip,
            user_agent=record.user_agent,
            current=record.id == current.id,
        )
        for record in records
    ]


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    session_id: uuid.UUID,
    request: Request,
    response: Response,
    current: CsrfSession,
    service: AuthServiceDep,
) -> None:
    if await service.revoke_session(current, session_id):
        clear_auth_cookies(response, request.app.state.settings)
