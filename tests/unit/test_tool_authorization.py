import jsonschema
import pytest

from forgejo_mcp.authorization.tools import ToolAuthorizationContext, authorize_tool
from forgejo_mcp.tools import get_tool, list_tools


def allowed_context(**overrides: bool) -> ToolAuthorizationContext:
    values = {
        "token_valid": True,
        "user_enabled": True,
        "global_tool_enabled": True,
        "user_allowed_tool": True,
        "token_has_tool_grant": True,
        "forgejo_credential_configured": True,
    }
    values.update(overrides)
    return ToolAuthorizationContext(**values)


def test_registry_contains_stable_default_disabled_tool_spec() -> None:
    tools = list_tools()

    assert [tool.name for tool in tools] == [
        "forgejo_get_current_user",
        "forgejo_list_repositories",
        "forgejo_get_repository",
        "forgejo_create_organization_repository",
        "forgejo_list_branches",
        "forgejo_list_commits",
        "forgejo_get_commit",
        "forgejo_compare_refs",
        "forgejo_get_git_tree",
        "forgejo_list_labels",
        "forgejo_list_milestones",
        "forgejo_list_issues",
        "forgejo_get_issue",
        "forgejo_list_issue_comments",
        "forgejo_list_pull_requests",
        "forgejo_get_pull_request",
        "forgejo_list_pull_request_commits",
        "forgejo_get_pull_request_diff",
        "forgejo_get_file_content",
        "forgejo_create_issue",
        "forgejo_update_issue",
        "forgejo_comment_issue",
        "forgejo_create_pull_request",
        "forgejo_update_pull_request",
        "forgejo_list_repository_contents",
        "forgejo_create_branch",
        "forgejo_commit_changes",
        "forgejo_get_pull_request_files",
        "forgejo_request_pull_request_reviewers",
        "forgejo_remove_pull_request_reviewers",
        "forgejo_list_pull_request_reviews",
        "forgejo_get_pull_request_review",
        "forgejo_submit_pull_request_review",
        "forgejo_merge_pull_request",
        "forgejo_get_pull_request_merge_status",
        "forgejo_get_commit_status",
        "forgejo_dispatch_workflow",
        "forgejo_create_tag",
        "forgejo_create_release",
    ]
    assert get_tool("forgejo_get_current_user") is tools[0]
    assert tools[0].risk == "read"
    assert tools[0].input_schema["additionalProperties"] is False
    assert all(tool.output_schema["additionalProperties"] is False for tool in tools)
    for tool in tools:
        jsonschema.Draft202012Validator.check_schema(tool.input_schema)
        jsonschema.Draft202012Validator.check_schema(tool.output_schema)


@pytest.mark.parametrize(
    ("failed_check", "reason"),
    [
        ("token_valid", "token_invalid"),
        ("user_enabled", "user_disabled"),
        ("global_tool_enabled", "tool_globally_disabled"),
        ("user_allowed_tool", "tool_not_allowed_for_user"),
        ("token_has_tool_grant", "tool_not_granted_to_token"),
        ("forgejo_credential_configured", "forgejo_credential_missing"),
    ],
)
def test_tool_authorization_defaults_to_deny(failed_check: str, reason: str) -> None:
    decision = authorize_tool(allowed_context(**{failed_check: False}))

    assert decision.allowed is False
    assert decision.reason == reason


def test_tool_authorization_allows_only_when_every_layer_passes() -> None:
    decision = authorize_tool(allowed_context())

    assert decision.allowed is True
    assert decision.reason == "allowed"
