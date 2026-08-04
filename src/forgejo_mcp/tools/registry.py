from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

ToolRisk = Literal["read", "read-sensitive", "write"]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    title: str
    description: str
    risk: ToolRisk
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    version: int = 1


def _object_schema(
    properties: dict[str, Any], required: list[str], *, additional: bool = False
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": additional,
    }


def _repository_schema() -> dict[str, Any]:
    properties: dict[str, Any] = {
        "id": {"type": "integer"},
        "owner": {"type": "string"},
        "name": {"type": "string"},
        "full_name": {"type": "string"},
        "description": {"type": "string"},
        "private": {"type": "boolean"},
        "fork": {"type": "boolean"},
        "default_branch": {"type": "string"},
        "archived": {"type": "boolean"},
        "html_url": {"type": "string"},
        "updated_at": {"type": ["string", "null"], "format": "date-time"},
        "stars_count": {"type": ["integer", "null"]},
        "forks_count": {"type": ["integer", "null"]},
        "open_issues_count": {"type": ["integer", "null"]},
        "permissions": {
            "type": ["object", "null"],
            "properties": {
                "admin": {"type": "boolean"},
                "pull": {"type": "boolean"},
                "push": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
    }
    return _object_schema(
        properties,
        [
            "id",
            "owner",
            "name",
            "full_name",
            "description",
            "private",
            "fork",
            "default_branch",
            "archived",
            "html_url",
            "updated_at",
            "stars_count",
            "forks_count",
            "open_issues_count",
            "permissions",
        ],
    )


def _page_schema(item_schema: dict[str, Any]) -> dict[str, Any]:
    return _object_schema(
        {
            "items": {"type": "array", "items": item_schema},
            "page": {"type": "integer", "minimum": 1},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            "has_more": {"type": "boolean"},
        },
        ["items", "page", "limit", "has_more"],
    )


_OWNER = {"type": "string", "minLength": 1, "maxLength": 255, "pattern": r"^[^/\x00-\x1f\x7f]+$"}
_REPO = {"type": "string", "minLength": 1, "maxLength": 255, "pattern": r"^[^/\x00-\x1f\x7f]+$"}
_PAGE = {"type": "integer", "minimum": 1, "maximum": 100000, "default": 1}
_LIMIT = {"type": "integer", "minimum": 1, "maximum": 100, "default": 30}
_BRANCH_SCHEMA = _object_schema(
    {
        "name": {"type": "string"},
        "commit_sha": {"type": "string"},
        "protected": {"type": "boolean"},
    },
    ["name", "commit_sha", "protected"],
)
_STATS_SCHEMA = _object_schema(
    {
        "additions": {"type": "integer", "minimum": 0},
        "deletions": {"type": "integer", "minimum": 0},
        "total": {"type": "integer", "minimum": 0},
    },
    ["additions", "deletions", "total"],
)
_FILE_SUMMARY_SCHEMA = _object_schema(
    {
        "path": {"type": "string"},
        "status": {"type": "string"},
        "additions": {"type": ["integer", "null"], "minimum": 0},
        "deletions": {"type": ["integer", "null"], "minimum": 0},
        "changes": {"type": ["integer", "null"], "minimum": 0},
    },
    ["path", "status", "additions", "deletions", "changes"],
)
_COMMIT_PROPERTIES: dict[str, Any] = {
    "sha": {"type": "string"},
    "message": {"type": "string"},
    "html_url": {"type": ["string", "null"]},
    "author_name": {"type": ["string", "null"]},
    "author_email": {"type": ["string", "null"]},
    "authored_at": {"type": ["string", "null"], "format": "date-time"},
    "committer_name": {"type": ["string", "null"]},
    "committed_at": {"type": ["string", "null"], "format": "date-time"},
    "parent_shas": {"type": "array", "items": {"type": "string"}},
    "stats": {"anyOf": [_STATS_SCHEMA, {"type": "null"}]},
}
_COMMIT_REQUIRED = list(_COMMIT_PROPERTIES)
_COMMIT_SCHEMA = _object_schema(_COMMIT_PROPERTIES, _COMMIT_REQUIRED)
_COMMIT_DETAIL_SCHEMA = _object_schema(
    {
        **_COMMIT_PROPERTIES,
        "files": {"type": "array", "items": _FILE_SUMMARY_SCHEMA, "maxItems": 100},
        "files_truncated": {"type": "boolean"},
    },
    [*_COMMIT_REQUIRED, "files", "files_truncated"],
)
_REF = {"type": "string", "minLength": 1, "maxLength": 255}
_FILE_PATH = {"type": "string", "minLength": 1, "maxLength": 1024}
_NUMBER = {"type": "integer", "minimum": 1}
_TIMESTAMP = {"type": "string", "format": "date-time"}
_TITLE = {"type": "string", "minLength": 1, "maxLength": 255}
_BODY = {"type": ["string", "null"], "maxLength": 65536}
_COMMENT_BODY = {"type": "string", "minLength": 1, "maxLength": 32768}
_USER_SCHEMA = _object_schema(
    {
        "id": {"type": "integer"},
        "username": {"type": "string"},
        "display_name": {"type": ["string", "null"]},
        "avatar_url": {"type": ["string", "null"]},
    },
    ["id", "username", "display_name", "avatar_url"],
)
_LABEL_SCHEMA = _object_schema(
    {"id": {"type": "integer"}, "name": {"type": "string"}, "color": {"type": "string"}},
    ["id", "name", "color"],
)
_REPOSITORY_LABEL_SCHEMA = _object_schema(
    {
        "id": {"type": "integer"},
        "name": {"type": "string"},
        "color": {"type": "string"},
        "description": {"type": "string"},
        "exclusive": {"type": "boolean"},
        "archived": {"type": "boolean"},
    },
    ["id", "name", "color", "description", "exclusive", "archived"],
)
_REPOSITORY_MILESTONE_SCHEMA = _object_schema(
    {
        "id": {"type": "integer"},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "state": {"type": "string", "enum": ["open", "closed"]},
        "open_issues": {"type": "integer", "minimum": 0},
        "closed_issues": {"type": "integer", "minimum": 0},
        "created_at": _TIMESTAMP,
        "updated_at": _TIMESTAMP,
        "due_on": {"type": ["string", "null"], "format": "date-time"},
        "closed_at": {"type": ["string", "null"], "format": "date-time"},
    },
    [
        "id",
        "title",
        "description",
        "state",
        "open_issues",
        "closed_issues",
        "created_at",
        "updated_at",
        "due_on",
        "closed_at",
    ],
)
_GIT_TREE_ENTRY_SCHEMA = _object_schema(
    {
        "path": {"type": "string"},
        "mode": {"type": "string"},
        "type": {"type": "string"},
        "size": {"type": "integer", "minimum": 0},
        "sha": {"type": "string"},
    },
    ["path", "mode", "type", "size", "sha"],
)
_ISSUE_SCHEMA = _object_schema(
    {
        "number": _NUMBER,
        "title": {"type": "string"},
        "body": _BODY,
        "state": {"type": "string", "enum": ["open", "closed"]},
        "html_url": {"type": "string"},
        "user": _USER_SCHEMA,
        "assignees": {"type": "array", "items": _USER_SCHEMA},
        "labels": {"type": "array", "items": _LABEL_SCHEMA},
        "milestone": {
            "anyOf": [
                _object_schema(
                    {"id": {"type": "integer"}, "title": {"type": "string"}}, ["id", "title"]
                ),
                {"type": "null"},
            ]
        },
        "comments_count": {"type": "integer", "minimum": 0},
        "created_at": _TIMESTAMP,
        "updated_at": _TIMESTAMP,
        "closed_at": {"type": ["string", "null"], "format": "date-time"},
    },
    [
        "number",
        "title",
        "body",
        "state",
        "html_url",
        "user",
        "assignees",
        "labels",
        "milestone",
        "comments_count",
        "created_at",
        "updated_at",
        "closed_at",
    ],
)
_COMMENT_SCHEMA = _object_schema(
    {
        "id": {"type": "integer"},
        "body": {"type": "string"},
        "html_url": {"type": ["string", "null"]},
        "user": _USER_SCHEMA,
        "created_at": _TIMESTAMP,
        "updated_at": _TIMESTAMP,
    },
    ["id", "body", "html_url", "user", "created_at", "updated_at"],
)
_PULL_REF_SCHEMA = _object_schema(
    {"ref": {"type": "string"}, "sha": {"type": "string"}, "repository": {"type": "string"}},
    ["ref", "sha", "repository"],
)
_PR_SCHEMA = _object_schema(
    {
        "number": _NUMBER,
        "title": {"type": "string"},
        "body": _BODY,
        "state": {"type": "string", "enum": ["open", "closed"]},
        "draft": {"type": "boolean"},
        "mergeable": {"type": ["boolean", "null"]},
        "merged": {"type": "boolean"},
        "html_url": {"type": "string"},
        "user": _USER_SCHEMA,
        "base": _PULL_REF_SCHEMA,
        "head": _PULL_REF_SCHEMA,
        "labels": {"type": "array", "items": _LABEL_SCHEMA},
        "created_at": _TIMESTAMP,
        "updated_at": _TIMESTAMP,
        "closed_at": {"type": ["string", "null"], "format": "date-time"},
        "merged_at": {"type": ["string", "null"], "format": "date-time"},
        "commits_count": {"type": ["integer", "null"]},
        "additions": {"type": ["integer", "null"]},
        "deletions": {"type": ["integer", "null"]},
        "changed_files": {"type": ["integer", "null"]},
    },
    [
        "number",
        "title",
        "body",
        "state",
        "draft",
        "mergeable",
        "merged",
        "html_url",
        "user",
        "base",
        "head",
        "labels",
        "created_at",
        "updated_at",
        "closed_at",
        "merged_at",
        "commits_count",
        "additions",
        "deletions",
        "changed_files",
    ],
)

_CONTENT_ENTRY_SCHEMA = _object_schema(
    {
        "name": {"type": "string"},
        "path": {"type": "string"},
        "sha": {"type": "string"},
        "type": {"type": "string", "enum": ["file", "dir", "symlink", "submodule"]},
        "size": {"type": "integer", "minimum": 0},
        "html_url": {"type": ["string", "null"]},
    },
    ["name", "path", "sha", "type", "size", "html_url"],
)
_CHANGED_FILE_SCHEMA = _object_schema(
    {
        "path": {"type": "string"},
        "previous_path": {"type": ["string", "null"]},
        "status": {"type": "string"},
        "additions": {"type": "integer", "minimum": 0},
        "deletions": {"type": "integer", "minimum": 0},
        "changes": {"type": "integer", "minimum": 0},
    },
    ["path", "previous_path", "status", "additions", "deletions", "changes"],
)
_REVIEW_SCHEMA = _object_schema(
    {
        "id": {"type": "integer"},
        "user": {"type": "string"},
        "state": {"type": "string"},
        "body": {"type": ["string", "null"]},
        "commit_id": {"type": ["string", "null"]},
        "submitted_at": {"type": ["string", "null"]},
        "stale": {"type": "boolean"},
        "dismissed": {"type": "boolean"},
        "comments_count": {"type": "integer", "minimum": 0},
    },
    [
        "id",
        "user",
        "state",
        "body",
        "commit_id",
        "submitted_at",
        "stale",
        "dismissed",
        "comments_count",
    ],
)
_REVIEWERS = {
    "type": "array",
    "items": {"type": "string", "minLength": 1, "maxLength": 255},
    "maxItems": 20,
}
_AUDIT = {"type": "string"}

_TOOL_SPECS = (
    ToolSpec(
        name="forgejo_get_current_user",
        title="Get current Forgejo user",
        description="Return the Forgejo principal associated with the token owner's PAT.",
        risk="read",
        input_schema=_object_schema({}, []),
        output_schema=_object_schema(
            {"id": {"type": "integer"}, "username": {"type": "string"}},
            ["id", "username"],
        ),
    ),
    ToolSpec(
        name="forgejo_list_repositories",
        title="List repositories",
        description="List repositories visible to the token owner's Forgejo PAT.",
        risk="read",
        input_schema=_object_schema(
            {
                "page": _PAGE,
                "limit": _LIMIT,
                "order_by": {
                    "type": "string",
                    "enum": [
                        "name",
                        "id",
                        "newest",
                        "oldest",
                        "recentupdate",
                        "leastupdate",
                        "alphabetically",
                        "reversealphabetically",
                        "size",
                        "reversesize",
                        "moststars",
                        "feweststars",
                        "mostforks",
                        "fewestforks",
                    ],
                    "default": "recentupdate",
                },
            },
            [],
        ),
        output_schema=_page_schema(_repository_schema()),
    ),
    ToolSpec(
        name="forgejo_get_repository",
        title="Get repository",
        description="Return normalized metadata for a Forgejo repository.",
        risk="read",
        input_schema=_object_schema({"owner": _OWNER, "repo": _REPO}, ["owner", "repo"]),
        output_schema=_repository_schema(),
    ),
    ToolSpec(
        name="forgejo_list_branches",
        title="List branches",
        description="List branches in a Forgejo repository.",
        risk="read",
        input_schema=_object_schema(
            {"owner": _OWNER, "repo": _REPO, "page": _PAGE, "limit": _LIMIT},
            ["owner", "repo"],
        ),
        output_schema=_page_schema(_BRANCH_SCHEMA),
    ),
    ToolSpec(
        name="forgejo_list_commits",
        title="List commits",
        description="List commits for a repository, optionally filtered by ref and path.",
        risk="read",
        input_schema=_object_schema(
            {
                "owner": _OWNER,
                "repo": _REPO,
                "ref": _REF,
                "path": _FILE_PATH,
                "page": _PAGE,
                "limit": _LIMIT,
            },
            ["owner", "repo"],
        ),
        output_schema=_page_schema(_COMMIT_SCHEMA),
    ),
    ToolSpec(
        name="forgejo_get_commit",
        title="Get commit",
        description="Return normalized commit metadata, statistics, and changed file summaries.",
        risk="read",
        input_schema=_object_schema(
            {
                "owner": _OWNER,
                "repo": _REPO,
                "sha": {"type": "string", "minLength": 1, "maxLength": 64},
            },
            ["owner", "repo", "sha"],
        ),
        output_schema=_COMMIT_DETAIL_SCHEMA,
    ),
    ToolSpec(
        name="forgejo_compare_refs",
        title="Compare refs",
        description="Compare two repository refs and return bounded commit and file summaries.",
        risk="read-sensitive",
        input_schema=_object_schema(
            {"owner": _OWNER, "repo": _REPO, "base": _REF, "head": _REF},
            ["owner", "repo", "base", "head"],
        ),
        output_schema=_object_schema(
            {
                "base": {"type": "string"},
                "head": {"type": "string"},
                "total_commits": {"type": "integer", "minimum": 0},
                "commits": {"type": "array", "items": _COMMIT_SCHEMA, "maxItems": 100},
                "files": {
                    "type": "array",
                    "items": _FILE_SUMMARY_SCHEMA,
                    "maxItems": 100,
                },
                "commits_truncated": {"type": "boolean"},
                "files_truncated": {"type": "boolean"},
            },
            [
                "base",
                "head",
                "total_commits",
                "commits",
                "files",
                "commits_truncated",
                "files_truncated",
            ],
        ),
    ),
    ToolSpec(
        name="forgejo_get_git_tree",
        title="Get git tree",
        description="Return a bounded page of git tree entries for a commit SHA or ref.",
        risk="read-sensitive",
        input_schema=_object_schema(
            {
                "owner": _OWNER,
                "repo": _REPO,
                "sha": _REF,
                "recursive": {"type": "boolean", "default": False},
                "page": _PAGE,
                "limit": _LIMIT,
            },
            ["owner", "repo", "sha"],
        ),
        output_schema=_object_schema(
            {
                "sha": {"type": "string"},
                "entries": {
                    "type": "array",
                    "items": _GIT_TREE_ENTRY_SCHEMA,
                    "maxItems": 100,
                },
                "page": {"type": "integer", "minimum": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                "total_count": {"type": "integer", "minimum": 0},
                "truncated": {"type": "boolean"},
            },
            ["sha", "entries", "page", "limit", "total_count", "truncated"],
        ),
    ),
    ToolSpec(
        name="forgejo_list_labels",
        title="List repository labels",
        description="List labels defined in a repository.",
        risk="read",
        input_schema=_object_schema(
            {
                "owner": _OWNER,
                "repo": _REPO,
                "sort": {
                    "type": "string",
                    "enum": ["mostissues", "leastissues", "reversealphabetically"],
                },
                "page": _PAGE,
                "limit": _LIMIT,
            },
            ["owner", "repo"],
        ),
        output_schema=_page_schema(_REPOSITORY_LABEL_SCHEMA),
    ),
    ToolSpec(
        name="forgejo_list_milestones",
        title="List repository milestones",
        description="List repository milestones by state and optional name filter.",
        risk="read",
        input_schema=_object_schema(
            {
                "owner": _OWNER,
                "repo": _REPO,
                "state": {"type": "string", "enum": ["open", "closed", "all"], "default": "open"},
                "name": {"type": "string", "minLength": 1, "maxLength": 256},
                "page": _PAGE,
                "limit": _LIMIT,
            },
            ["owner", "repo"],
        ),
        output_schema=_page_schema(_REPOSITORY_MILESTONE_SCHEMA),
    ),
    ToolSpec(
        name="forgejo_list_issues",
        title="List issues",
        description="List repository issues.",
        risk="read",
        input_schema=_object_schema(
            {
                "owner": _OWNER,
                "repo": _REPO,
                "state": {"type": "string", "enum": ["open", "closed", "all"], "default": "open"},
                "labels": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 255},
                    "maxItems": 50,
                },
                "milestones": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 255},
                    "maxItems": 50,
                },
                "query": {"type": "string", "maxLength": 256},
                "since": _TIMESTAMP,
                "before": _TIMESTAMP,
                "sort": {
                    "type": "string",
                    "enum": [
                        "relevance",
                        "latest",
                        "oldest",
                        "recentupdate",
                        "leastupdate",
                        "mostcomment",
                        "leastcomment",
                    ],
                    "default": "latest",
                },
                "page": _PAGE,
                "limit": _LIMIT,
            },
            ["owner", "repo"],
        ),
        output_schema=_page_schema(_ISSUE_SCHEMA),
    ),
    ToolSpec(
        name="forgejo_get_issue",
        title="Get issue",
        description="Return a repository issue.",
        risk="read-sensitive",
        input_schema=_object_schema(
            {"owner": _OWNER, "repo": _REPO, "number": _NUMBER}, ["owner", "repo", "number"]
        ),
        output_schema=_ISSUE_SCHEMA,
    ),
    ToolSpec(
        name="forgejo_list_issue_comments",
        title="List issue comments",
        description="Return bounded issue or pull request comments.",
        risk="read-sensitive",
        input_schema=_object_schema(
            {
                "owner": _OWNER,
                "repo": _REPO,
                "number": _NUMBER,
                "since": _TIMESTAMP,
                "before": _TIMESTAMP,
            },
            ["owner", "repo", "number"],
        ),
        output_schema=_object_schema(
            {
                "items": {"type": "array", "items": _COMMENT_SCHEMA, "maxItems": 100},
                "truncated": {"type": "boolean"},
            },
            ["items", "truncated"],
        ),
    ),
    ToolSpec(
        name="forgejo_list_pull_requests",
        title="List pull requests",
        description="List repository pull requests.",
        risk="read",
        input_schema=_object_schema(
            {
                "owner": _OWNER,
                "repo": _REPO,
                "state": {"type": "string", "enum": ["open", "closed", "all"], "default": "open"},
                "base": _REF,
                "head": _REF,
                "label_ids": {"type": "array", "items": _NUMBER, "maxItems": 50},
                "milestone_id": _NUMBER,
                "sort": {
                    "type": "string",
                    "enum": [
                        "oldest",
                        "recentupdate",
                        "recentclose",
                        "leastupdate",
                        "mostcomment",
                        "leastcomment",
                        "priority",
                    ],
                    "default": "recentupdate",
                },
                "page": _PAGE,
                "limit": _LIMIT,
            },
            ["owner", "repo"],
        ),
        output_schema=_page_schema(_PR_SCHEMA),
    ),
    ToolSpec(
        name="forgejo_get_pull_request",
        title="Get pull request",
        description="Return a repository pull request.",
        risk="read-sensitive",
        input_schema=_object_schema(
            {"owner": _OWNER, "repo": _REPO, "number": _NUMBER}, ["owner", "repo", "number"]
        ),
        output_schema=_PR_SCHEMA,
    ),
    ToolSpec(
        name="forgejo_list_pull_request_commits",
        title="List pull request commits",
        description="List normalized commits included in a pull request.",
        risk="read",
        input_schema=_object_schema(
            {
                "owner": _OWNER,
                "repo": _REPO,
                "number": _NUMBER,
                "page": _PAGE,
                "limit": _LIMIT,
            },
            ["owner", "repo", "number"],
        ),
        output_schema=_page_schema(_COMMIT_SCHEMA),
    ),
    ToolSpec(
        name="forgejo_get_pull_request_diff",
        title="Get pull request diff",
        description="Return a bounded pull request diff.",
        risk="read-sensitive",
        input_schema=_object_schema(
            {"owner": _OWNER, "repo": _REPO, "number": _NUMBER}, ["owner", "repo", "number"]
        ),
        output_schema=_object_schema(
            {
                "number": _NUMBER,
                "format": {"const": "diff"},
                "size": {"type": "integer", "minimum": 0},
                "sha256": {"type": "string"},
                "content": {"type": "string"},
            },
            ["number", "format", "size", "sha256", "content"],
        ),
    ),
    ToolSpec(
        name="forgejo_get_file_content",
        title="Get file content",
        description="Return bounded repository file content.",
        risk="read-sensitive",
        input_schema=_object_schema(
            {"owner": _OWNER, "repo": _REPO, "path": _FILE_PATH, "ref": _REF},
            ["owner", "repo", "path"],
        ),
        output_schema=_object_schema(
            {
                "path": {"type": "string"},
                "name": {"type": "string"},
                "sha": {"type": "string"},
                "ref": {"type": ["string", "null"]},
                "size": {"type": "integer", "minimum": 0},
                "encoding": {"type": "string", "enum": ["utf-8", "base64"]},
                "content": {"type": "string"},
                "html_url": {"type": ["string", "null"]},
            },
            ["path", "name", "sha", "ref", "size", "encoding", "content", "html_url"],
        ),
    ),
    ToolSpec(
        name="forgejo_create_issue",
        title="Create issue",
        description="Create a repository issue.",
        risk="write",
        input_schema=_object_schema(
            {
                "owner": _OWNER,
                "repo": _REPO,
                "title": _TITLE,
                "body": {"type": "string", "maxLength": 65536},
                "assignees": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 255},
                    "maxItems": 20,
                },
                "label_ids": {"type": "array", "items": _NUMBER, "maxItems": 50},
                "milestone_id": _NUMBER,
            },
            ["owner", "repo", "title"],
        ),
        output_schema=_object_schema(
            {"issue": _ISSUE_SCHEMA, "audit_event_id": {"type": "string"}},
            ["issue", "audit_event_id"],
        ),
    ),
    ToolSpec(
        name="forgejo_update_issue",
        title="Update issue",
        description="Update declared fields on a repository issue.",
        risk="write",
        input_schema={
            **_object_schema(
                {
                    "owner": _OWNER,
                    "repo": _REPO,
                    "number": _NUMBER,
                    "title": _TITLE,
                    "body": _BODY,
                    "state": {"type": "string", "enum": ["open", "closed"]},
                    "assignees": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1, "maxLength": 255},
                        "maxItems": 20,
                    },
                    "label_ids": {"type": "array", "items": _NUMBER, "maxItems": 50},
                    "milestone_id": {"type": ["integer", "null"], "minimum": 1},
                },
                ["owner", "repo", "number"],
            ),
            "minProperties": 4,
        },
        output_schema=_object_schema(
            {"issue": _ISSUE_SCHEMA, "audit_event_id": {"type": "string"}},
            ["issue", "audit_event_id"],
        ),
    ),
    ToolSpec(
        name="forgejo_comment_issue",
        title="Comment on issue",
        description="Create an issue or pull request conversation comment.",
        risk="write",
        input_schema=_object_schema(
            {"owner": _OWNER, "repo": _REPO, "number": _NUMBER, "body": _COMMENT_BODY},
            ["owner", "repo", "number", "body"],
        ),
        output_schema=_object_schema(
            {"comment": _COMMENT_SCHEMA, "audit_event_id": {"type": "string"}},
            ["comment", "audit_event_id"],
        ),
    ),
    ToolSpec(
        name="forgejo_create_pull_request",
        title="Create pull request",
        description="Create a pull request from existing branches.",
        risk="write",
        input_schema=_object_schema(
            {
                "owner": _OWNER,
                "repo": _REPO,
                "title": _TITLE,
                "head": _REF,
                "base": _REF,
                "body": {"type": "string", "maxLength": 65536},
                "draft": {"type": "boolean"},
            },
            ["owner", "repo", "title", "head", "base"],
        ),
        output_schema=_object_schema(
            {"pull_request": _PR_SCHEMA, "audit_event_id": {"type": "string"}},
            ["pull_request", "audit_event_id"],
        ),
    ),
    ToolSpec(
        name="forgejo_update_pull_request",
        title="Update pull request",
        description="Update declared fields on a pull request.",
        risk="write",
        input_schema={
            **_object_schema(
                {
                    "owner": _OWNER,
                    "repo": _REPO,
                    "number": _NUMBER,
                    "title": _TITLE,
                    "body": _BODY,
                    "state": {"type": "string", "enum": ["open", "closed"]},
                    "base": _REF,
                },
                ["owner", "repo", "number"],
            ),
            "minProperties": 4,
        },
        output_schema=_object_schema(
            {"pull_request": _PR_SCHEMA, "audit_event_id": {"type": "string"}},
            ["pull_request", "audit_event_id"],
        ),
    ),
    ToolSpec(
        name="forgejo_list_repository_contents",
        title="List repository contents",
        description="List files and directories at a repository path and ref.",
        risk="read",
        input_schema=_object_schema(
            {"owner": _OWNER, "repo": _REPO, "path": _FILE_PATH, "ref": _REF}, ["owner", "repo"]
        ),
        output_schema=_object_schema(
            {
                "items": {"type": "array", "items": _CONTENT_ENTRY_SCHEMA, "maxItems": 100},
                "truncated": {"type": "boolean"},
            },
            ["items", "truncated"],
        ),
    ),
    ToolSpec(
        name="forgejo_create_branch",
        title="Create branch",
        description="Create a repository branch from an optional branch, tag, or commit.",
        risk="write",
        input_schema=_object_schema(
            {"owner": _OWNER, "repo": _REPO, "branch": _REF, "from_ref": _REF},
            ["owner", "repo", "branch"],
        ),
        output_schema=_object_schema(
            {"branch": _BRANCH_SCHEMA, "audit_event_id": _AUDIT}, ["branch", "audit_event_id"]
        ),
    ),
    ToolSpec(
        name="forgejo_commit_changes",
        title="Commit file changes",
        description=(
            "Create one commit containing multiple create, update, delete, or move operations."
        ),
        risk="write",
        input_schema=_object_schema(
            {
                "owner": _OWNER,
                "repo": _REPO,
                "branch": _REF,
                "new_branch": _REF,
                "message": {"type": "string", "minLength": 1, "maxLength": 65536},
                "signoff": {"type": "boolean", "default": False},
                "changes": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 100,
                    "items": _object_schema(
                        {
                            "operation": {"type": "string", "enum": ["create", "update", "delete"]},
                            "path": _FILE_PATH,
                            "from_path": _FILE_PATH,
                            "sha": {"type": "string", "minLength": 1, "maxLength": 64},
                            "content": {"type": "string", "maxLength": 1500000},
                            "encoding": {
                                "type": "string",
                                "enum": ["utf-8", "base64"],
                                "default": "utf-8",
                            },
                        },
                        ["operation", "path"],
                    ),
                },
            },
            ["owner", "repo", "message", "changes"],
        ),
        output_schema=_object_schema(
            {
                "commit_sha": {"type": "string"},
                "files": {"type": "array", "items": _CONTENT_ENTRY_SCHEMA, "maxItems": 100},
                "audit_event_id": _AUDIT,
            },
            ["commit_sha", "files", "audit_event_id"],
        ),
    ),
    ToolSpec(
        name="forgejo_get_pull_request_files",
        title="Get pull request files",
        description="List normalized files changed by a pull request.",
        risk="read-sensitive",
        input_schema=_object_schema(
            {"owner": _OWNER, "repo": _REPO, "number": _NUMBER}, ["owner", "repo", "number"]
        ),
        output_schema=_object_schema(
            {
                "items": {"type": "array", "items": _CHANGED_FILE_SCHEMA, "maxItems": 100},
                "truncated": {"type": "boolean"},
            },
            ["items", "truncated"],
        ),
    ),
    ToolSpec(
        name="forgejo_request_pull_request_reviewers",
        title="Request pull request reviewers",
        description="Request user or team reviews for a pull request.",
        risk="write",
        input_schema={
            **_object_schema(
                {
                    "owner": _OWNER,
                    "repo": _REPO,
                    "number": _NUMBER,
                    "reviewers": _REVIEWERS,
                    "team_reviewers": _REVIEWERS,
                },
                ["owner", "repo", "number"],
            ),
            "minProperties": 4,
        },
        output_schema=_object_schema(
            {"reviewers": _REVIEWERS, "team_reviewers": _REVIEWERS, "audit_event_id": _AUDIT},
            ["reviewers", "team_reviewers", "audit_event_id"],
        ),
    ),
    ToolSpec(
        name="forgejo_remove_pull_request_reviewers",
        title="Remove pull request reviewers",
        description="Remove requested user or team reviewers from a pull request.",
        risk="write",
        input_schema={
            **_object_schema(
                {
                    "owner": _OWNER,
                    "repo": _REPO,
                    "number": _NUMBER,
                    "reviewers": _REVIEWERS,
                    "team_reviewers": _REVIEWERS,
                },
                ["owner", "repo", "number"],
            ),
            "minProperties": 4,
        },
        output_schema=_object_schema(
            {"reviewers": _REVIEWERS, "team_reviewers": _REVIEWERS, "audit_event_id": _AUDIT},
            ["reviewers", "team_reviewers", "audit_event_id"],
        ),
    ),
    ToolSpec(
        name="forgejo_list_pull_request_reviews",
        title="List pull request reviews",
        description="List bounded reviews submitted for a pull request.",
        risk="read-sensitive",
        input_schema=_object_schema(
            {"owner": _OWNER, "repo": _REPO, "number": _NUMBER}, ["owner", "repo", "number"]
        ),
        output_schema=_object_schema(
            {
                "items": {"type": "array", "items": _REVIEW_SCHEMA, "maxItems": 100},
                "truncated": {"type": "boolean"},
            },
            ["items", "truncated"],
        ),
    ),
    ToolSpec(
        name="forgejo_get_pull_request_review",
        title="Get pull request review",
        description="Return one normalized pull request review by review ID.",
        risk="read-sensitive",
        input_schema=_object_schema(
            {
                "owner": _OWNER,
                "repo": _REPO,
                "number": _NUMBER,
                "review_id": _NUMBER,
            },
            ["owner", "repo", "number", "review_id"],
        ),
        output_schema=_REVIEW_SCHEMA,
    ),
    ToolSpec(
        name="forgejo_submit_pull_request_review",
        title="Submit pull request review",
        description="Approve, request changes, or comment with optional inline comments.",
        risk="write",
        input_schema=_object_schema(
            {
                "owner": _OWNER,
                "repo": _REPO,
                "number": _NUMBER,
                "event": {"type": "string", "enum": ["APPROVED", "REQUEST_CHANGES", "COMMENT"]},
                "body": {"type": "string", "maxLength": 32768},
                "commit_id": {"type": "string", "minLength": 1, "maxLength": 64},
                "comments": {
                    "type": "array",
                    "maxItems": 100,
                    "items": _object_schema(
                        {
                            "path": _FILE_PATH,
                            "body": _COMMENT_BODY,
                            "old_position": {"type": "integer", "minimum": 0},
                            "new_position": {"type": "integer", "minimum": 0},
                        },
                        ["path", "body"],
                    ),
                },
            },
            ["owner", "repo", "number", "event"],
        ),
        output_schema=_object_schema(
            {"review": _REVIEW_SCHEMA, "audit_event_id": _AUDIT}, ["review", "audit_event_id"]
        ),
    ),
    ToolSpec(
        name="forgejo_merge_pull_request",
        title="Merge pull request",
        description="Merge a pull request using merge, squash, or rebase strategy.",
        risk="write",
        input_schema=_object_schema(
            {
                "owner": _OWNER,
                "repo": _REPO,
                "number": _NUMBER,
                "method": {
                    "type": "string",
                    "enum": ["merge", "rebase", "rebase-merge", "squash", "manually-merged"],
                },
                "title": _TITLE,
                "message": {"type": "string", "maxLength": 65536},
                "head_sha": {"type": "string", "minLength": 1, "maxLength": 64},
                "delete_branch": {"type": "boolean", "default": False},
            },
            ["owner", "repo", "number", "method"],
        ),
        output_schema=_object_schema(
            {"merged": {"const": True}, "audit_event_id": _AUDIT}, ["merged", "audit_event_id"]
        ),
    ),
    ToolSpec(
        name="forgejo_get_pull_request_merge_status",
        title="Get pull request merge status",
        description="Check whether a pull request has already been merged.",
        risk="read",
        input_schema=_object_schema(
            {"owner": _OWNER, "repo": _REPO, "number": _NUMBER},
            ["owner", "repo", "number"],
        ),
        output_schema=_object_schema(
            {"number": _NUMBER, "merged": {"type": "boolean"}},
            ["number", "merged"],
        ),
    ),
    ToolSpec(
        name="forgejo_get_commit_status",
        title="Get commit status",
        description="Return the combined commit status and bounded individual statuses.",
        risk="read",
        input_schema=_object_schema(
            {"owner": _OWNER, "repo": _REPO, "ref": _REF}, ["owner", "repo", "ref"]
        ),
        output_schema=_object_schema(
            {
                "sha": {"type": "string"},
                "state": {"type": "string"},
                "total_count": {"type": "integer", "minimum": 0},
                "statuses": {
                    "type": "array",
                    "maxItems": 100,
                    "items": _object_schema(
                        {
                            "context": {"type": "string"},
                            "state": {"type": "string"},
                            "description": {"type": ["string", "null"]},
                            "target_url": {"type": ["string", "null"]},
                        },
                        ["context", "state", "description", "target_url"],
                    ),
                },
                "truncated": {"type": "boolean"},
            },
            ["sha", "state", "total_count", "statuses", "truncated"],
        ),
    ),
    ToolSpec(
        name="forgejo_dispatch_workflow",
        title="Dispatch workflow",
        description="Trigger a workflow_dispatch workflow for a repository ref.",
        risk="write",
        input_schema=_object_schema(
            {
                "owner": _OWNER,
                "repo": _REPO,
                "workflow": _REF,
                "ref": _REF,
                "inputs": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "maxProperties": 50,
                },
            },
            ["owner", "repo", "workflow", "ref"],
        ),
        output_schema=_object_schema(
            {"dispatched": {"const": True}, "audit_event_id": _AUDIT},
            ["dispatched", "audit_event_id"],
        ),
    ),
    ToolSpec(
        name="forgejo_create_tag",
        title="Create tag",
        description="Create a repository tag.",
        risk="write",
        input_schema=_object_schema(
            {
                "owner": _OWNER,
                "repo": _REPO,
                "tag": _REF,
                "target": _REF,
                "message": {"type": "string", "maxLength": 65536},
            },
            ["owner", "repo", "tag"],
        ),
        output_schema=_object_schema(
            {
                "tag": _object_schema(
                    {
                        "name": {"type": "string"},
                        "id": {"type": ["string", "null"]},
                        "commit_sha": {"type": "string"},
                        "message": {"type": ["string", "null"]},
                    },
                    ["name", "id", "commit_sha", "message"],
                ),
                "audit_event_id": _AUDIT,
            },
            ["tag", "audit_event_id"],
        ),
    ),
    ToolSpec(
        name="forgejo_create_release",
        title="Create release",
        description="Create a repository release for a tag.",
        risk="write",
        input_schema=_object_schema(
            {
                "owner": _OWNER,
                "repo": _REPO,
                "tag": _REF,
                "target": _REF,
                "name": _TITLE,
                "body": {"type": "string", "maxLength": 65536},
                "draft": {"type": "boolean", "default": False},
                "prerelease": {"type": "boolean", "default": False},
            },
            ["owner", "repo", "tag"],
        ),
        output_schema=_object_schema(
            {
                "release": _object_schema(
                    {
                        "id": {"type": "integer"},
                        "tag_name": {"type": "string"},
                        "name": {"type": "string"},
                        "html_url": {"type": ["string", "null"]},
                        "draft": {"type": "boolean"},
                        "prerelease": {"type": "boolean"},
                    },
                    ["id", "tag_name", "name", "html_url", "draft", "prerelease"],
                ),
                "audit_event_id": _AUDIT,
            },
            ["release", "audit_event_id"],
        ),
    ),
)

TOOL_REGISTRY = MappingProxyType({spec.name: spec for spec in _TOOL_SPECS})


def get_tool(name: str) -> ToolSpec | None:
    return TOOL_REGISTRY.get(name)


def list_tools() -> tuple[ToolSpec, ...]:
    return _TOOL_SPECS
