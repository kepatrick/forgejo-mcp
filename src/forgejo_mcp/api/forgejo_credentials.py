import uuid
from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, SecretStr

from forgejo_mcp.api.dependencies import ForgejoCredentialServiceDep
from forgejo_mcp.authorization.policies import (
    AdminCsrfSession,
    UserCsrfSession,
    UserSession,
)
from forgejo_mcp.db.models import ForgejoCredential

me_router = APIRouter(prefix="/api/me/credential", tags=["forgejo-credential"])
admin_router = APIRouter(prefix="/api/users", tags=["forgejo-credential-admin"])


class CredentialRequest(BaseModel):
    token: SecretStr


class PrincipalResponse(BaseModel):
    forgejo_user_id: int
    forgejo_username: str


class CredentialResponse(BaseModel):
    configured: bool
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
        id=credential.id,
        status=credential.status,
        forgejo_user_id=credential.forgejo_user_id,
        forgejo_username=credential.forgejo_username,
        verified_at=credential.verified_at,
        activated_at=credential.activated_at,
    )


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
