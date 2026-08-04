from typing import Annotated

from fastapi import Depends, Request

from forgejo_mcp.application.auth_service import AuthService
from forgejo_mcp.application.forgejo_credential_service import ForgejoCredentialService
from forgejo_mcp.application.forgejo_instance_service import ForgejoInstanceService
from forgejo_mcp.application.invitation_service import InvitationService
from forgejo_mcp.application.mcp_token_service import McpTokenService
from forgejo_mcp.application.tool_invocation_service import ToolInvocationService
from forgejo_mcp.application.tool_permission_service import ToolPermissionService
from forgejo_mcp.application.user_service import UserService
from forgejo_mcp.db.dependencies import DbSession


def get_auth_service(db: DbSession) -> AuthService:
    return AuthService(db)


def get_forgejo_credential_service(request: Request, db: DbSession) -> ForgejoCredentialService:
    return ForgejoCredentialService(db, request.app.state.settings)


def get_forgejo_instance_service(request: Request, db: DbSession) -> ForgejoInstanceService:
    return ForgejoInstanceService(db, request.app.state.settings)


def get_invitation_service(db: DbSession) -> InvitationService:
    return InvitationService(db)


def get_mcp_token_service(db: DbSession) -> McpTokenService:
    return McpTokenService(db)


def get_tool_invocation_service(db: DbSession) -> ToolInvocationService:
    return ToolInvocationService(db)


def get_tool_permission_service(db: DbSession) -> ToolPermissionService:
    return ToolPermissionService(db)


def get_user_service(db: DbSession) -> UserService:
    return UserService(db)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
ForgejoCredentialServiceDep = Annotated[
    ForgejoCredentialService, Depends(get_forgejo_credential_service)
]
ForgejoInstanceServiceDep = Annotated[ForgejoInstanceService, Depends(get_forgejo_instance_service)]
InvitationServiceDep = Annotated[InvitationService, Depends(get_invitation_service)]
McpTokenServiceDep = Annotated[McpTokenService, Depends(get_mcp_token_service)]
ToolInvocationServiceDep = Annotated[ToolInvocationService, Depends(get_tool_invocation_service)]
ToolPermissionServiceDep = Annotated[ToolPermissionService, Depends(get_tool_permission_service)]
UserServiceDep = Annotated[UserService, Depends(get_user_service)]
