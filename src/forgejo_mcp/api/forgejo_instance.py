import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field

from forgejo_mcp.api.dependencies import ForgejoInstanceServiceDep
from forgejo_mcp.authorization.policies import AdminCsrfSession, AdminSession
from forgejo_mcp.db.models import ForgejoInstance

router = APIRouter(prefix="/api/forgejo/instance", tags=["forgejo-instance"])


class ForgejoConnectionRequest(BaseModel):
    base_url: str = Field(min_length=1, max_length=2048)
    verify_tls: bool = True


class ConfigureForgejoRequest(ForgejoConnectionRequest):
    display_name: str = Field(default="Forgejo", min_length=1, max_length=120)


class ForgejoConnectionResponse(BaseModel):
    base_url: str
    version: str
    checked_at: datetime


class ForgejoInstanceResponse(BaseModel):
    configured: bool
    id: uuid.UUID | None = None
    display_name: str | None = None
    base_url: str | None = None
    verify_tls: bool | None = None
    version: str | None = None
    last_checked_at: datetime | None = None


def instance_response(instance: ForgejoInstance | None) -> ForgejoInstanceResponse:
    if instance is None:
        return ForgejoInstanceResponse(configured=False)
    return ForgejoInstanceResponse(
        configured=True,
        id=instance.id,
        display_name=instance.display_name,
        base_url=instance.base_url,
        verify_tls=instance.verify_tls,
        version=instance.version,
        last_checked_at=instance.last_checked_at,
    )


@router.get("", response_model=ForgejoInstanceResponse)
async def get_instance(
    _admin: AdminSession, service: ForgejoInstanceServiceDep
) -> ForgejoInstanceResponse:
    return instance_response(await service.get())


@router.post("/test", response_model=ForgejoConnectionResponse)
async def test_connection(
    payload: ForgejoConnectionRequest,
    _admin: AdminCsrfSession,
    service: ForgejoInstanceServiceDep,
) -> ForgejoConnectionResponse:
    result = await service.check(base_url=payload.base_url, verify_tls=payload.verify_tls)
    return ForgejoConnectionResponse(
        base_url=result.base_url,
        version=result.version,
        checked_at=result.checked_at,
    )


@router.put("", response_model=ForgejoInstanceResponse)
async def configure_instance(
    payload: ConfigureForgejoRequest,
    admin: AdminCsrfSession,
    service: ForgejoInstanceServiceDep,
) -> ForgejoInstanceResponse:
    instance = await service.configure(
        actor_account_id=admin.account_id,
        display_name=payload.display_name,
        base_url=payload.base_url,
        verify_tls=payload.verify_tls,
    )
    return instance_response(instance)
