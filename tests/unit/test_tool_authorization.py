import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import jsonschema
import pytest

from forgejo_mcp.application.tool_permission_service import ToolPermissionService
from forgejo_mcp.authorization.tools import ToolAuthorizationContext, authorize_tool
from forgejo_mcp.db.models import CredentialStatus, RecordStatus
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
        "forgejo_migrate_repository",
        "forgejo_update_repository",
        "forgejo_sync_mirror",
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
        "forgejo_list_action_runs",
        "forgejo_get_action_run",
        "forgejo_list_action_run_jobs",
        "forgejo_get_action_job_log",
        "forgejo_get_action_run_logs",
        "forgejo_list_action_run_artifacts",
        "forgejo_cancel_action_run",
        "forgejo_delete_action_run",
        "forgejo_dispatch_workflow",
        "forgejo_create_tag",
        "forgejo_create_release",
    ]
    assert get_tool("forgejo_get_current_user") is tools[0]
    assert tools[0].risk == "read"
    assert tools[0].input_schema["additionalProperties"] is False
    assert all(tool.output_schema["additionalProperties"] is False for tool in tools)
    assert get_tool("forgejo_update_repository").input_schema["minProperties"] == 3
    assert get_tool("forgejo_migrate_repository").risk == "write"
    assert get_tool("forgejo_sync_mirror").risk == "write"
    for tool in tools:
        jsonschema.Draft202012Validator.check_schema(tool.input_schema)
        jsonschema.Draft202012Validator.check_schema(tool.output_schema)


@pytest.mark.parametrize(
    "arguments",
    [
        {"owner": ".", "repo": "repo"},
        {"owner": "..", "repo": "repo"},
        {"owner": " .. ", "repo": "repo"},
        {"owner": "\u00a0..\u00a0", "repo": "repo"},
        {"owner": "\u3000.\u3000", "repo": "repo"},
        {"owner": "owner", "repo": "."},
        {"owner": "owner", "repo": ".."},
        {"owner": "owner", "repo": " . "},
        {"owner": "owner", "repo": "\u00a0..\u00a0"},
    ],
)
def test_repository_tool_schema_rejects_dot_segments(arguments: dict[str, str]) -> None:
    validator = jsonschema.Draft202012Validator(get_tool("forgejo_get_repository").input_schema)

    assert list(validator.iter_errors(arguments))


@pytest.mark.parametrize("sha", [".", "..", " . ", " .. ", "\u00a0..\u00a0", "\u3000.\u3000"])
def test_ref_tool_schema_rejects_dot_segments(sha: str) -> None:
    validator = jsonschema.Draft202012Validator(get_tool("forgejo_get_commit").input_schema)

    assert any(
        list(error.path) == ["sha"]
        for error in validator.iter_errors({"owner": "owner", "repo": "repo", "sha": sha})
    )


@pytest.mark.parametrize(
    "path",
    [
        ".",
        "..",
        "./README.md",
        "src/./module.py",
        "src/../secret",
        "\u00a0..\u00a0",
        "\u00a0../README.md",
        "src/..\u3000",
        "\u3000/absolute",
    ],
)
def test_file_path_tool_schema_rejects_dot_segments(path: str) -> None:
    validator = jsonschema.Draft202012Validator(get_tool("forgejo_get_file_content").input_schema)

    assert any(
        list(error.path) == ["path"]
        for error in validator.iter_errors({"owner": "owner", "repo": "repo", "path": path})
    )


def test_repository_root_listing_accepts_an_omitted_or_empty_path() -> None:
    validator = jsonschema.Draft202012Validator(
        get_tool("forgejo_list_repository_contents").input_schema
    )

    assert not list(validator.iter_errors({"owner": "owner", "repo": "repo"}))
    assert not list(
        validator.iter_errors({"owner": "owner", "repo": "repo", "path": ""})
    )
    file_validator = jsonschema.Draft202012Validator(
        get_tool("forgejo_get_file_content").input_schema
    )
    assert list(
        file_validator.iter_errors({"owner": "owner", "repo": "repo", "path": ""})
    )


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


def test_batch_tool_authorization_loads_one_permission_snapshot() -> None:
    async def exercise() -> None:
        token_id = uuid.uuid4()
        user_id = uuid.uuid4()
        names = [tool.name for tool in list_tools()]
        globally_disabled = names[-1]
        settings = {
            name: SimpleNamespace(enabled=True)
            for name in names
            if name != globally_disabled
        }
        permissions = SimpleNamespace(
            settings=AsyncMock(return_value=settings),
            allowance_names=AsyncMock(return_value=set(names)),
            grant_names=AsyncMock(return_value=set(names)),
        )
        tokens = SimpleNamespace(
            get=AsyncMock(
                return_value=SimpleNamespace(
                    id=token_id,
                    user_id=user_id,
                    enabled=True,
                    revoked_at=None,
                    expires_at=None,
                    user=SimpleNamespace(
                        status=RecordStatus.ACTIVE,
                        forgejo_credentials=[
                            SimpleNamespace(status=CredentialStatus.ACTIVE)
                        ],
                    ),
                )
            )
        )
        service = ToolPermissionService(MagicMock())
        service.permissions = permissions
        service.tokens = tokens

        decisions = await service.decisions(
            token_id=token_id,
            tool_names=(*names, "forgejo_unknown", names[0]),
        )

        assert decisions[names[0]].allowed is True
        assert decisions[globally_disabled].reason == "tool_globally_disabled"
        assert decisions["forgejo_unknown"].reason == "token_invalid"
        tokens.get.assert_awaited_once_with(token_id)
        permissions.settings.assert_awaited_once_with()
        permissions.allowance_names.assert_awaited_once_with(user_id)
        permissions.grant_names.assert_awaited_once_with(token_id)

    asyncio.run(exercise())
