import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from forgejo_mcp.api.dependencies import ForgejoInstanceServiceDep
from forgejo_mcp.application.forgejo_oauth_config_service import ForgejoOAuthConfigService
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


class ForgejoOAuthSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    client_id: str = Field(default="", max_length=128)
    base_url: str = Field(min_length=1, max_length=2048)
    client_type: Literal["public", "confidential"] = "confidential"
    client_secret: SecretStr | None = None


class ForgejoOAuthSettingsResponse(BaseModel):
    enabled: bool
    client_id: str
    base_url: str
    redirect_url: str
    client_type: Literal["public", "confidential"]
    secret_configured: bool
    source: Literal["dashboard", "environment", "unconfigured"]


@router.get("/oauth", response_model=ForgejoOAuthSettingsResponse)
async def get_oauth_settings(
    response: Response,
    _admin: AdminSession,
    service: ForgejoInstanceServiceDep,
) -> ForgejoOAuthSettingsResponse:
    response.headers["Cache-Control"] = "no-store"
    result = await ForgejoOAuthConfigService(service.session, service.settings).public()
    return ForgejoOAuthSettingsResponse.model_validate(result, from_attributes=True)


@router.put("/oauth", response_model=ForgejoOAuthSettingsResponse)
async def save_oauth_settings(
    payload: ForgejoOAuthSettingsRequest,
    response: Response,
    admin: AdminCsrfSession,
    service: ForgejoInstanceServiceDep,
) -> ForgejoOAuthSettingsResponse:
    response.headers["Cache-Control"] = "no-store"
    result = await ForgejoOAuthConfigService(service.session, service.settings).save(
        actor_account_id=admin.account_id,
        enabled=payload.enabled,
        client_id=payload.client_id,
        base_url=payload.base_url,
        client_type=payload.client_type,
        client_secret=payload.client_secret,
    )
    return ForgejoOAuthSettingsResponse.model_validate(result, from_attributes=True)


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
