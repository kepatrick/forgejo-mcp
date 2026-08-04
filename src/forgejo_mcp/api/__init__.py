from forgejo_mcp.api.auth import router as auth_router
from forgejo_mcp.api.forgejo_credentials import admin_router as forgejo_credential_admin_router
from forgejo_mcp.api.forgejo_credentials import me_router as forgejo_credential_me_router
from forgejo_mcp.api.forgejo_instance import router as forgejo_instance_router
from forgejo_mcp.api.invitations import router as invitations_router
from forgejo_mcp.api.mcp_tokens import admin_router as mcp_token_admin_router
from forgejo_mcp.api.mcp_tokens import me_router as mcp_token_me_router
from forgejo_mcp.api.system import router as system_router
from forgejo_mcp.api.tool_invocations import admin_router as tool_invocations_admin_router
from forgejo_mcp.api.tool_invocations import me_router as tool_invocations_me_router
from forgejo_mcp.api.tools import admin_router as tools_admin_router
from forgejo_mcp.api.tools import me_router as tools_me_router
from forgejo_mcp.api.tools import user_allowance_router as tools_user_allowance_router
from forgejo_mcp.api.users import router as users_router

__all__ = [
    "auth_router",
    "forgejo_credential_admin_router",
    "forgejo_credential_me_router",
    "forgejo_instance_router",
    "invitations_router",
    "mcp_token_admin_router",
    "mcp_token_me_router",
    "system_router",
    "tool_invocations_admin_router",
    "tool_invocations_me_router",
    "tools_admin_router",
    "tools_me_router",
    "tools_user_allowance_router",
    "users_router",
]
