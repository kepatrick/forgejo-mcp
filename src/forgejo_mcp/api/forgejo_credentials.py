import hmac
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, SecretStr
from starlette.responses import JSONResponse, RedirectResponse

from forgejo_mcp.api.dependencies import ForgejoCredentialServiceDep
from forgejo_mcp.application.errors import ApplicationError
from forgejo_mcp.application.forgejo_oauth_service import ForgejoOAuthService
from forgejo_mcp.auth.session import SESSION_COOKIE
from forgejo_mcp.auth.tokens import hash_token
from forgejo_mcp.authorization.policies import (
    AdminCsrfSession,
    UserCsrfSession,
    UserSession,
)
from forgejo_mcp.credentials import CredentialKeyError
from forgejo_mcp.db.models import ForgejoCredential

logger = logging.getLogger(__name__)
FORGEJO_OAUTH_SESSION_COOKIE = "fmcp_forgejo_oauth_session"
FORGEJO_OAUTH_CALLBACK_PATH = "/api/me/credential/oauth/callback"

me_router = APIRouter(prefix="/api/me/credential", tags=["forgejo-credential"])
admin_router = APIRouter(prefix="/api/users", tags=["forgejo-credential-admin"])


class CredentialRequest(BaseModel):
    token: SecretStr


class PrincipalResponse(BaseModel):
    forgejo_user_id: int
    forgejo_username: str


class CredentialResponse(BaseModel):
    configured: bool
    kind: str | None = None
    access_expires_at: datetime | None = None
    id: uuid.UUID | None = None
    status: str | None = None
    forgejo_user_id: int | None = None
    forgejo_username: str | None = None
    verified_at: datetime | None = None
    activated_at: datetime | None = None


def credential_response(credential: ForgejoCredential | None) -> CredentialResponse:
    if credential is None:
        return CredentialResponse(configured=False)
    return CredentialResponse(
        configured=True,
        kind=credential.kind,
        access_expires_at=credential.access_expires_at,
        id=credential.id,
        status=credential.status,
        forgejo_user_id=credential.forgejo_user_id,
        forgejo_username=credential.forgejo_username,
        verified_at=credential.verified_at,
        activated_at=credential.activated_at,
    )


@me_router.get("/oauth/status")
async def forgejo_oauth_status(
    current: UserSession, service: ForgejoCredentialServiceDep
) -> dict[str, bool]:
    instance = await service.instances.primary()
    settings = service.settings
    return {
        "enabled": bool(
            settings.forgejo_oauth_client_id
            and settings.forgejo_oauth_redirect_url
            and instance
            and settings.permits_forgejo_base_url(instance.base_url)
        )
    }


@me_router.post("/oauth/start")
async def start_forgejo_oauth(
    current: UserCsrfSession, service: ForgejoCredentialServiceDep
) -> JSONResponse:
    try:
        url, browser_token = await ForgejoOAuthService(service.session, service.settings).start(
            current
        )
    except (ApplicationError, CredentialKeyError) as error:
        logger.warning(
            "forgejo_oauth_start_failed",
            extra={"error_type": type(error).__name__, "account_id": str(current.account_id)},
        )
        raise
    response = JSONResponse({"authorization_url": url}, headers={"Cache-Control": "no-store"})
    # Keep Dashboard cookies Strict. This separate one-use browser binding is
    # accepted only at the callback and cannot authenticate to other endpoints.
    response.set_cookie(
        FORGEJO_OAUTH_SESSION_COOKIE,
        browser_token,
        httponly=True,
        secure=service.settings.use_secure_cookies,
        samesite="lax",
        path=FORGEJO_OAUTH_CALLBACK_PATH,
        max_age=600,
    )
    return response


@me_router.get("/oauth/callback")
async def complete_forgejo_oauth(
    request: Request,
    service: ForgejoCredentialServiceDep,
    state: str = "",
    code: str = "",
    error: str | None = None,
) -> RedirectResponse:
    account_id = None
    outcome = "connected"
    try:
        oauth = ForgejoOAuthService(service.session, service.settings)
        current = await oauth.callback_session(
            state, request.cookies.get(FORGEJO_OAUTH_SESSION_COOKIE)
        )
        dashboard = request.cookies.get(SESSION_COOKIE)
        if dashboard is not None and not hmac.compare_digest(
            hash_token(dashboard), current.session_token_hash
        ):
            ForgejoOAuthService.reject("callback_session_mismatch")
        account_id = str(current.account_id)
        await ForgejoOAuthService(service.session, service.settings).complete(
            current,
            state=state,
            code=code,
            denied=error is not None,
        )
    except (ApplicationError, CredentialKeyError, HTTPException) as failure:
        await service.session.rollback()
        logger.warning(
            "forgejo_oauth_callback_failed",
            extra={"error_type": type(failure).__name__, "account_id": account_id},
        )
        outcome = "failed"
    response = RedirectResponse(
        f"/?forgejo_oauth={outcome}",
        status_code=303,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )
    response.delete_cookie(
        FORGEJO_OAUTH_SESSION_COOKIE,
        path=FORGEJO_OAUTH_CALLBACK_PATH,
        secure=service.settings.use_secure_cookies,
        httponly=True,
        samesite="lax",
    )
    return response


@me_router.get("", response_model=CredentialResponse)
async def get_my_credential(
    current: UserSession,
    service: ForgejoCredentialServiceDep,
) -> CredentialResponse:
    assert current.account.user_id is not None
    return credential_response(await service.active_for_user(current.account.user_id))


@me_router.post("/test", response_model=PrincipalResponse)
async def test_my_credential(
    payload: CredentialRequest,
    current: UserCsrfSession,
    service: ForgejoCredentialServiceDep,
) -> PrincipalResponse:
    assert current.account.user_id is not None
    principal = await service.verify(
        actor_account_id=current.account_id,
        user_id=current.account.user_id,
        token=payload.token.get_secret_value(),
    )
    return PrincipalResponse(
        forgejo_user_id=principal.user_id,
        forgejo_username=principal.username,
    )


@me_router.put("", response_model=CredentialResponse)
async def save_my_credential(
    payload: CredentialRequest,
    current: UserCsrfSession,
    service: ForgejoCredentialServiceDep,
) -> CredentialResponse:
    assert current.account.user_id is not None
    credential = await service.save(
        actor_account_id=current.account_id,
        user_id=current.account.user_id,
        token=payload.token.get_secret_value(),
    )
    return credential_response(credential)


@me_router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_my_credential(
    current: UserCsrfSession,
    service: ForgejoCredentialServiceDep,
) -> None:
    assert current.account.user_id is not None
    await service.revoke(
        actor_account_id=current.account_id,
        user_id=current.account.user_id,
        forced_by_admin=False,
    )


@admin_router.delete("/{user_id}/credential", status_code=status.HTTP_204_NO_CONTENT)
async def admin_revoke_credential(
    user_id: uuid.UUID,
    admin: AdminCsrfSession,
    service: ForgejoCredentialServiceDep,
) -> None:
    await service.revoke(
        actor_account_id=admin.account_id,
        user_id=user_id,
        forced_by_admin=True,
    )
