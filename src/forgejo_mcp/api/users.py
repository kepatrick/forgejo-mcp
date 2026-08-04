import uuid
from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from forgejo_mcp.api.dependencies import UserServiceDep
from forgejo_mcp.authorization.policies import AdminCsrfSession, AdminSession
from forgejo_mcp.db.models import CredentialStatus, User

router = APIRouter(prefix="/api/users", tags=["users"])


class CreateUserRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    username: str = Field(min_length=3, max_length=64)
    forgejo_username: str = Field(min_length=1, max_length=255)


class UpdateUserRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    forgejo_username: str = Field(min_length=1, max_length=255)


class UserResponse(BaseModel):
    id: uuid.UUID
    display_name: str
    username: str
    forgejo_username: str
    status: str
    credential_status: str
    created_at: datetime


class InvitationResponse(BaseModel):
    id: uuid.UUID
    invitation_url: str
    expires_at: datetime


def user_response(user: User) -> UserResponse:
    if user.account is None:
        raise RuntimeError("user account relationship was not loaded")
    credential_status = (
        "configured"
        if any(
            credential.status == CredentialStatus.ACTIVE for credential in user.forgejo_credentials
        )
        else "not_configured"
    )
    return UserResponse(
        id=user.id,
        display_name=user.display_name,
        username=user.account.username,
        forgejo_username=user.expected_forgejo_username,
        status=user.status,
        credential_status=credential_status,
        created_at=user.created_at,
    )


@router.get("", response_model=list[UserResponse])
async def list_users(_admin: AdminSession, service: UserServiceDep) -> list[UserResponse]:
    return [user_response(user) for user in await service.list_users()]


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: CreateUserRequest, admin: AdminCsrfSession, service: UserServiceDep
) -> UserResponse:
    user = await service.create_user(
        actor_account_id=admin.account_id,
        display_name=payload.display_name,
        username=payload.username,
        forgejo_username=payload.forgejo_username,
    )
    return user_response(user)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: uuid.UUID, _admin: AdminSession, service: UserServiceDep
) -> UserResponse:
    return user_response(await service.get_user(user_id))


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    payload: UpdateUserRequest,
    admin: AdminCsrfSession,
    service: UserServiceDep,
) -> UserResponse:
    user = await service.update_user(
        actor_account_id=admin.account_id,
        user_id=user_id,
        display_name=payload.display_name,
        forgejo_username=payload.forgejo_username,
    )
    return user_response(user)


@router.post("/{user_id}/disable", response_model=UserResponse)
async def disable_user(
    user_id: uuid.UUID, admin: AdminCsrfSession, service: UserServiceDep
) -> UserResponse:
    return user_response(
        await service.disable_user(actor_account_id=admin.account_id, user_id=user_id)
    )


@router.post("/{user_id}/enable", response_model=UserResponse)
async def enable_user(
    user_id: uuid.UUID, admin: AdminCsrfSession, service: UserServiceDep
) -> UserResponse:
    return user_response(
        await service.enable_user(actor_account_id=admin.account_id, user_id=user_id)
    )


@router.post("/{user_id}/invitations", response_model=InvitationResponse)
async def create_invitation(
    user_id: uuid.UUID, admin: AdminCsrfSession, service: UserServiceDep
) -> InvitationResponse:
    result = await service.create_invitation(actor_account_id=admin.account_id, user_id=user_id)
    return InvitationResponse(
        id=result.id, invitation_url=result.path, expires_at=result.expires_at
    )


@router.delete("/{user_id}/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(
    user_id: uuid.UUID,
    invitation_id: uuid.UUID,
    admin: AdminCsrfSession,
    service: UserServiceDep,
) -> None:
    await service.revoke_invitation(
        actor_account_id=admin.account_id,
        user_id=user_id,
        invitation_id=invitation_id,
    )
