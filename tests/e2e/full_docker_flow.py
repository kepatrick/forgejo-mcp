#!/usr/bin/env python3
import os
import subprocess
import sys
import time
from typing import Any

import httpx
from mcp.shared.version import LATEST_PROTOCOL_VERSION

from forgejo_mcp.tools import list_tools

APP_URL = os.getenv("FMCP_E2E_APP_URL", "http://127.0.0.1:3800").rstrip("/")
FORGEJO_URL = os.getenv("FMCP_E2E_FORGEJO_URL", "http://127.0.0.1:3300").rstrip("/")
FORGEJO_INTERNAL_URL = os.getenv("FMCP_E2E_FORGEJO_INTERNAL_URL", "http://forgejo:3000").rstrip("/")
ADMIN_PASSWORD = os.environ["FMCP_E2E_ADMIN_PASSWORD"]
DEVELOPER_PASSWORD = os.environ["FMCP_E2E_DEVELOPER_PASSWORD"]
REVIEWER_PASSWORD = os.environ["FMCP_E2E_REVIEWER_PASSWORD"]


def checked(response: httpx.Response, label: str) -> httpx.Response:
    if response.status_code not in {200, 201, 202, 204}:
        raise RuntimeError(f"{label}: HTTP {response.status_code}: {response.text[:500]}")
    return response


def csrf(client: httpx.Client) -> dict[str, str]:
    token = client.cookies.get("fmcp_csrf")
    if token is None:
        raise RuntimeError("Dashboard did not set a CSRF cookie")
    return {"X-CSRF-Token": token}


def forgejo_request(
    path: str,
    *,
    method: str = "GET",
    username: str | None = None,
    password: str | None = None,
    token: str | None = None,
    body: dict[str, Any] | None = None,
) -> Any:
    headers: dict[str, str] = {}
    authentication = (username, password) if username is not None and password is not None else None
    if token is not None:
        headers["Authorization"] = f"token {token}"
    with httpx.Client(timeout=30) as client:
        response = client.request(
            method,
            f"{FORGEJO_URL}/api/v1{path}",
            auth=authentication,
            headers=headers,
            json=body,
        )
    checked(response, f"Forgejo {method} {path}")
    return response.json() if response.content else None


def create_forgejo_resources() -> dict[str, str]:
    suffix = str(time.time_ns())
    developer = forgejo_request(
        "/users/developer/tokens",
        method="POST",
        username="developer",
        password=DEVELOPER_PASSWORD,
        body={"name": f"full-e2e-developer-{suffix}", "scopes": ["all"]},
    )["sha1"]
    reviewer = forgejo_request(
        "/users/reviewer/tokens",
        method="POST",
        username="reviewer",
        password=REVIEWER_PASSWORD,
        body={"name": f"full-e2e-reviewer-{suffix}", "scopes": ["all"]},
    )["sha1"]
    forgejo_request(
        "/orgs",
        method="POST",
        token=developer,
        body={
            "username": "full-workflow-org",
            "full_name": "Full Workflow Organization",
        },
    )
    forgejo_request(
        "/user/repos",
        method="POST",
        token=developer,
        body={
            "name": "full-workflow",
            "default_branch": "main",
            "auto_init": True,
            "private": False,
        },
    )
    forgejo_request(
        "/repos/developer/full-workflow/collaborators/reviewer",
        method="PUT",
        token=developer,
        body={"permission": "write"},
    )
    forgejo_request(
        "/repos/developer/full-workflow/labels",
        method="POST",
        token=developer,
        body={"name": "feature", "color": "00aabb", "description": "New feature"},
    )
    forgejo_request(
        "/repos/developer/full-workflow/milestones",
        method="POST",
        token=developer,
        body={"title": "v1", "description": "First release"},
    )
    print("PASS Forgejo users, PATs, repository, collaborator, label, and milestone")
    return {"developer": developer, "reviewer": reviewer}


def provision_dashboard(forgejo_tokens: dict[str, str]) -> dict[str, str]:
    admin = httpx.Client(base_url=APP_URL, timeout=30)
    checked(
        admin.post(
            "/api/auth/login",
            json={"username": "admin", "password": ADMIN_PASSWORD},
        ),
        "Admin login",
    )
    changed_password = f"{ADMIN_PASSWORD}-changed"
    checked(
        admin.post(
            "/api/auth/change-password",
            headers=csrf(admin),
            json={"current_password": ADMIN_PASSWORD, "new_password": changed_password},
        ),
        "Admin password change",
    )
    checked(
        admin.put(
            "/api/forgejo/instance",
            headers=csrf(admin),
            json={
                "display_name": "Docker Forgejo",
                "base_url": FORGEJO_INTERNAL_URL,
                "verify_tls": False,
            },
        ),
        "Forgejo instance configuration",
    )

    tool_names = [tool.name for tool in list_tools()]
    for tool_name in tool_names:
        checked(
            admin.put(
                f"/api/tools/{tool_name}",
                headers=csrf(admin),
                json={"enabled": True},
            ),
            f"Enable {tool_name}",
        )
    print(f"PASS Dashboard bootstrap and {len(tool_names)} global tool settings")

    mcp_tokens: dict[str, str] = {}
    users = (
        ("developer-local", "Developer", "developer", "Developer-local-pass-123!"),
        ("reviewer-local", "Reviewer", "reviewer", "Reviewer-local-pass-123!"),
    )
    for local_username, display_name, forgejo_username, local_password in users:
        created = checked(
            admin.post(
                "/api/users",
                headers=csrf(admin),
                json={
                    "display_name": display_name,
                    "username": local_username,
                    "forgejo_username": forgejo_username,
                },
            ),
            f"Create {local_username}",
        ).json()
        user_id = created["id"]
        invitation = checked(
            admin.post(f"/api/users/{user_id}/invitations", headers=csrf(admin)),
            f"Invite {local_username}",
        ).json()
        invitation_token = invitation["invitation_url"].split("token=", maxsplit=1)[1]
        checked(
            httpx.post(
                f"{APP_URL}/api/auth/invitations/accept",
                timeout=30,
                json={"token": invitation_token, "password": local_password},
            ),
            f"Accept {local_username} invitation",
        )

        user = httpx.Client(base_url=APP_URL, timeout=30)
        checked(
            user.post(
                "/api/auth/login",
                json={"username": local_username, "password": local_password},
            ),
            f"Login {local_username}",
        )
        checked(
            user.put(
                "/api/me/credential",
                headers=csrf(user),
                json={"token": forgejo_tokens[forgejo_username]},
            ),
            f"Save {local_username} Forgejo credential",
        )
        checked(
            admin.put(
                f"/api/users/{user_id}/tools",
                headers=csrf(admin),
                json={"tool_names": tool_names},
            ),
            f"Set {local_username} tool allowance",
        )
        created_token = checked(
            user.post(
                "/api/me/mcp-tokens",
                headers=csrf(user),
                json={
                    "name": "Full Docker E2E",
                    "description": "Disposable full-stack test",
                    "expires_at": None,
                },
            ),
            f"Create {local_username} MCP token",
        ).json()
        checked(
            user.put(
                f"/api/me/mcp-tokens/{created_token['id']}/tools",
                headers=csrf(user),
                json={"tool_names": tool_names},
            ),
            f"Set {local_username} token grants",
        )
        mcp_tokens[forgejo_username] = created_token["token"]
        print(f"PASS {local_username} invitation, PAT, allowance, and MCP grants")
    return mcp_tokens


class McpClient:
    def __init__(self, token: str) -> None:
        self.token = token
        self.session_id: str | None = None
        self.request_id = 0
        self.called_tools: set[str] = set()
        self.client = httpx.Client(base_url=APP_URL, timeout=60)

    def request(self, payload: dict[str, Any]) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self.session_id is not None:
            headers["MCP-Session-Id"] = self.session_id
            headers["MCP-Protocol-Version"] = LATEST_PROTOCOL_VERSION
        return checked(self.client.post("/mcp", headers=headers, json=payload), "MCP request")

    def initialize(self) -> None:
        self.request_id += 1
        response = self.request(
            {
                "jsonrpc": "2.0",
                "id": self.request_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": LATEST_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "full-docker-e2e", "version": "1.0"},
                },
            }
        )
        self.session_id = response.headers["mcp-session-id"]
        self.request({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def list_tools(self) -> list[dict[str, Any]]:
        self.request_id += 1
        return self.request(
            {
                "jsonrpc": "2.0",
                "id": self.request_id,
                "method": "tools/list",
                "params": {},
            }
        ).json()["result"]["tools"]

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.request_id += 1
        payload = self.request(
            {
                "jsonrpc": "2.0",
                "id": self.request_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        ).json()
        if "error" in payload:
            raise RuntimeError(f"{name} RPC error: {payload['error']}")
        result = payload["result"]
        if result.get("isError"):
            raise RuntimeError(f"{name} failed: {result.get('content')}")
        self.called_tools.add(name)
        return result["structuredContent"]


def run_mcp_flow(mcp_tokens: dict[str, str]) -> None:
    developer = McpClient(mcp_tokens["developer"])
    reviewer = McpClient(mcp_tokens["reviewer"])
    developer.initialize()
    reviewer.initialize()
    expected_tools = {tool.name for tool in list_tools()}
    assert {tool["name"] for tool in developer.list_tools()} == expected_tools
    assert {tool["name"] for tool in reviewer.list_tools()} == expected_tools
    print(f"PASS MCP initialize and tools/list ({len(expected_tools)} tools)")

    developer_user = developer.call("forgejo_get_current_user", {})
    reviewer_user = reviewer.call("forgejo_get_current_user", {})
    assert developer_user["username"] == "developer"
    assert reviewer_user["username"] == "reviewer"

    repository = {"owner": "developer", "repo": "full-workflow"}
    organization_repository = developer.call(
        "forgejo_create_organization_repository",
        {
            "organization": "full-workflow-org",
            "name": "mcp-created",
            "description": "Created through the Forgejo MCP E2E flow",
            "auto_init": True,
            "default_branch": "main",
        },
    )["repository"]
    assert organization_repository["full_name"] == "full-workflow-org/mcp-created"
    assert organization_repository["default_branch"] == "main"
    repositories = developer.call("forgejo_list_repositories", {"limit": 100})
    assert any(item["full_name"] == "developer/full-workflow" for item in repositories["items"])
    repository_metadata = developer.call("forgejo_get_repository", repository)
    assert repository_metadata["name"] == "full-workflow"
    assert repository_metadata["default_branch"] == "main"
    branches = developer.call("forgejo_list_branches", {**repository, "limit": 100})
    assert any(item["name"] == "main" for item in branches["items"])
    labels = developer.call("forgejo_list_labels", {**repository, "limit": 100})
    assert any(item["name"] == "feature" for item in labels["items"])
    milestones = developer.call(
        "forgejo_list_milestones",
        {**repository, "state": "all", "limit": 100},
    )
    assert any(item["title"] == "v1" for item in milestones["items"])
    print("PASS MCP principals, repository metadata, branches, labels, and milestones")

    root = developer.call("forgejo_list_repository_contents", {**repository, "ref": "main"})
    readme = next(item for item in root["items"] if item["path"] == "README.md")
    main_commit = developer.call(
        "forgejo_commit_changes",
        {
            **repository,
            "branch": "main",
            "message": "ci: add workflow",
            "changes": [
                {
                    "operation": "update",
                    "path": "README.md",
                    "sha": readme["sha"],
                    "content": "# Full Docker MCP E2E\n",
                },
                {
                    "operation": "create",
                    "path": ".forgejo/workflows/ci.yml",
                    "content": (
                        "name: CI\non:\n  workflow_dispatch:\n"
                        "jobs:\n  test:\n    runs-on: docker\n"
                        "    steps:\n      - run: echo ok\n"
                    ),
                },
            ],
        },
    )
    readme_content = developer.call(
        "forgejo_get_file_content",
        {**repository, "path": "README.md", "ref": "main"},
    )
    assert readme_content["encoding"] == "utf-8"
    assert readme_content["content"] == "# Full Docker MCP E2E\n"
    commits = developer.call(
        "forgejo_list_commits",
        {**repository, "ref": "main", "limit": 100},
    )
    assert any(item["sha"] == main_commit["commit_sha"] for item in commits["items"])
    loaded_commit = developer.call(
        "forgejo_get_commit",
        {**repository, "sha": main_commit["commit_sha"]},
    )
    assert loaded_commit["sha"] == main_commit["commit_sha"]

    branch = developer.call(
        "forgejo_create_branch",
        {**repository, "branch": "feature/full-e2e", "from_ref": "main"},
    )["branch"]
    feature = developer.call(
        "forgejo_commit_changes",
        {
            **repository,
            "branch": branch["name"],
            "message": "feat: add greeting",
            "signoff": True,
            "changes": [
                {
                    "operation": "create",
                    "path": "src/greeting.py",
                    "content": 'def greeting() -> str:\n    return "hello"\n',
                },
                {
                    "operation": "create",
                    "path": "tests/test_greeting.py",
                    "content": (
                        "from src.greeting import greeting\n\n"
                        'def test_greeting():\n    assert greeting() == "hello"\n'
                    ),
                },
            ],
        },
    )
    tree = developer.call(
        "forgejo_get_git_tree",
        {
            **repository,
            "sha": feature["commit_sha"],
            "recursive": True,
            "limit": 100,
        },
    )
    assert {item["path"] for item in tree["entries"]} >= {
        "src/greeting.py",
        "tests/test_greeting.py",
    }
    comparison = developer.call(
        "forgejo_compare_refs",
        {**repository, "base": "main", "head": branch["name"]},
    )
    assert comparison["total_commits"] >= 1
    assert {item["path"] for item in comparison["files"]} == {
        "src/greeting.py",
        "tests/test_greeting.py",
    }
    print("PASS MCP contents, file read, commits, git tree, branch, and ref comparison")

    issue = developer.call(
        "forgejo_create_issue",
        {**repository, "title": "Add greeting", "body": "Implement greeting"},
    )["issue"]
    developer.call(
        "forgejo_comment_issue",
        {**repository, "number": issue["number"], "body": "Ready for review"},
    )
    issues = developer.call(
        "forgejo_list_issues",
        {**repository, "state": "open", "limit": 100},
    )
    assert any(item["number"] == issue["number"] for item in issues["items"])
    loaded_issue = developer.call("forgejo_get_issue", {**repository, "number": issue["number"]})
    assert loaded_issue["title"] == "Add greeting"
    comments = developer.call(
        "forgejo_list_issue_comments",
        {**repository, "number": issue["number"]},
    )
    assert [item["body"] for item in comments["items"]] == ["Ready for review"]
    updated_issue = developer.call(
        "forgejo_update_issue",
        {
            **repository,
            "number": issue["number"],
            "title": "Add friendly greeting",
        },
    )["issue"]
    assert updated_issue["title"] == "Add friendly greeting"
    print("PASS MCP Issue create, list, read, comment, and update")

    pull = developer.call(
        "forgejo_create_pull_request",
        {
            **repository,
            "title": "Add greeting",
            "head": branch["name"],
            "base": "main",
            "body": f"Closes #{issue['number']}",
        },
    )["pull_request"]
    pull_commits = developer.call(
        "forgejo_list_pull_request_commits",
        {**repository, "number": pull["number"], "limit": 100},
    )
    assert any(item["sha"] == feature["commit_sha"] for item in pull_commits["items"])
    merge_status = developer.call(
        "forgejo_get_pull_request_merge_status",
        {**repository, "number": pull["number"]},
    )
    assert merge_status == {"number": pull["number"], "merged": False}
    pulls = developer.call(
        "forgejo_list_pull_requests",
        {**repository, "state": "open", "limit": 100},
    )
    assert any(item["number"] == pull["number"] for item in pulls["items"])
    updated_pull = developer.call(
        "forgejo_update_pull_request",
        {
            **repository,
            "number": pull["number"],
            "title": "Add reviewed greeting",
        },
    )["pull_request"]
    assert updated_pull["title"] == "Add reviewed greeting"
    diff = developer.call(
        "forgejo_get_pull_request_diff",
        {**repository, "number": pull["number"]},
    )
    assert diff["format"] == "diff"
    assert "src/greeting.py" in diff["content"]
    assert "tests/test_greeting.py" in diff["content"]
    files = developer.call(
        "forgejo_get_pull_request_files",
        {**repository, "number": pull["number"]},
    )
    assert {item["path"] for item in files["items"]} == {
        "src/greeting.py",
        "tests/test_greeting.py",
    }
    reviewers = {**repository, "number": pull["number"], "reviewers": ["reviewer"]}
    developer.call("forgejo_request_pull_request_reviewers", reviewers)
    developer.call("forgejo_remove_pull_request_reviewers", reviewers)
    developer.call("forgejo_request_pull_request_reviewers", reviewers)
    review = reviewer.call(
        "forgejo_submit_pull_request_review",
        {
            **repository,
            "number": pull["number"],
            "event": "APPROVED",
            "body": "Looks good",
            "commit_id": feature["commit_sha"],
            "comments": [
                {
                    "path": "src/greeting.py",
                    "body": "Clear implementation",
                    "new_position": 2,
                }
            ],
        },
    )["review"]
    assert review["state"] == "APPROVED"
    loaded_review = developer.call(
        "forgejo_get_pull_request_review",
        {
            **repository,
            "number": pull["number"],
            "review_id": review["id"],
        },
    )
    assert loaded_review["id"] == review["id"]
    assert loaded_review["state"] == "APPROVED"
    reviews = developer.call(
        "forgejo_list_pull_request_reviews",
        {**repository, "number": pull["number"]},
    )
    assert any(item["state"] == "APPROVED" for item in reviews["items"])
    print("PASS MCP PR list, update, diff, files, reviewers, inline review, and approval")

    status = developer.call(
        "forgejo_get_commit_status",
        {**repository, "ref": feature["commit_sha"]},
    )
    assert status["state"] in {"pending", "success", "failure", "error", "warning"}
    developer.call(
        "forgejo_merge_pull_request",
        {
            **repository,
            "number": pull["number"],
            "method": "squash",
            "title": "Add greeting",
            "message": "Reviewed and merged",
            "head_sha": feature["commit_sha"],
            "delete_branch": True,
        },
    )
    merged = developer.call("forgejo_get_pull_request", {**repository, "number": pull["number"]})
    assert merged["merged"] is True
    merged_status = developer.call(
        "forgejo_get_pull_request_merge_status",
        {**repository, "number": pull["number"]},
    )
    assert merged_status == {"number": pull["number"], "merged": True}
    developer.call(
        "forgejo_dispatch_workflow",
        {**repository, "workflow": "ci.yml", "ref": "main", "inputs": {}},
    )
    tag = developer.call(
        "forgejo_create_tag",
        {
            **repository,
            "tag": "v0.2.0-e2e",
            "target": "main",
            "message": "Full-stack E2E",
        },
    )["tag"]
    release = developer.call(
        "forgejo_create_release",
        {
            **repository,
            "tag": tag["name"],
            "target": "main",
            "name": "Full-stack E2E",
            "body": "Validated through MCP",
            "prerelease": True,
        },
    )["release"]
    assert release["tag_name"] == tag["name"]
    print("PASS MCP status, merge, workflow dispatch, tag, and release")

    called_tools = developer.called_tools | reviewer.called_tools
    assert called_tools == expected_tools, (
        f"MCP E2E tool coverage mismatch; missing={sorted(expected_tools - called_tools)}, "
        f"unexpected={sorted(called_tools - expected_tools)}"
    )
    print(f"PASS all {len(expected_tools)} registered MCP tools executed successfully")


def main() -> None:
    subprocess.run(
        [
            sys.executable,
            "scripts/verify_forgejo_openapi.py",
            f"{FORGEJO_URL}/swagger.v1.json",
        ],
        check=True,
    )
    forgejo_tokens = create_forgejo_resources()
    mcp_tokens = provision_dashboard(forgejo_tokens)
    run_mcp_flow(mcp_tokens)
    print("FULL DOCKER MCP DEVELOPMENT FLOW PASSED")


if __name__ == "__main__":
    main()
