from dataclasses import dataclass


@dataclass(frozen=True)
class ToolAuthorizationContext:
    token_valid: bool
    user_enabled: bool
    global_tool_enabled: bool
    user_allowed_tool: bool
    token_has_tool_grant: bool
    forgejo_credential_configured: bool


@dataclass(frozen=True)
class ToolAuthorizationDecision:
    allowed: bool
    reason: str


def authorize_tool(context: ToolAuthorizationContext) -> ToolAuthorizationDecision:
    checks = (
        (context.token_valid, "token_invalid"),
        (context.user_enabled, "user_disabled"),
        (context.global_tool_enabled, "tool_globally_disabled"),
        (context.user_allowed_tool, "tool_not_allowed_for_user"),
        (context.token_has_tool_grant, "tool_not_granted_to_token"),
        (context.forgejo_credential_configured, "forgejo_credential_missing"),
    )
    for passed, reason in checks:
        if not passed:
            return ToolAuthorizationDecision(allowed=False, reason=reason)
    return ToolAuthorizationDecision(allowed=True, reason="allowed")
