import os
import uuid

import httpx
import pytest

from forgejo_mcp.forgejo.client import ForgejoClient

FORGEJO_URL = os.getenv("FMCP_E2E_FORGEJO_URL")
DEVELOPER_TOKEN = os.getenv("FMCP_E2E_DEVELOPER_TOKEN")
REVIEWER_TOKEN = os.getenv("FMCP_E2E_REVIEWER_TOKEN")
DEVELOPER = os.getenv("FMCP_E2E_DEVELOPER", "developer")
REVIEWER = os.getenv("FMCP_E2E_REVIEWER", "reviewer")

pytestmark = pytest.mark.skipif(
    not all((FORGEJO_URL, DEVELOPER_TOKEN, REVIEWER_TOKEN)),
    reason="actual Forgejo E2E credentials are not configured",
)


def _connection(token: str, repo: str) -> dict[str, object]:
    assert FORGEJO_URL is not None
    return {
        "base_url": FORGEJO_URL.rstrip("/"),
        "token": token,
        "verify_tls": FORGEJO_URL.startswith("https://"),
        "owner": DEVELOPER,
        "repo": repo,
    }


async def _api(
    method: str,
    path: str,
    *,
    token: str,
    body: dict[str, object] | None = None,
) -> httpx.Response:
    assert FORGEJO_URL is not None
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.request(
            method,
            f"{FORGEJO_URL.rstrip('/')}/api/v1{path}",
            headers={"Authorization": f"token {token}"},
            json=body,
        )
    response.raise_for_status()
    return response


async def test_actual_forgejo_development_flow() -> None:
    assert DEVELOPER_TOKEN is not None
    assert REVIEWER_TOKEN is not None
    repo = f"forgejo-mcp-e2e-{uuid.uuid4().hex[:10]}"
    client = ForgejoClient(connect_timeout_seconds=20)
    developer = _connection(DEVELOPER_TOKEN, repo)
    reviewer = _connection(REVIEWER_TOKEN, repo)

    await _api(
        "POST",
        "/user/repos",
        token=DEVELOPER_TOKEN,
        body={"name": repo, "default_branch": "main", "auto_init": True, "private": True},
    )
    try:
        await _api(
            "PUT",
            f"/repos/{DEVELOPER}/{repo}/collaborators/{REVIEWER}",
            token=DEVELOPER_TOKEN,
            body={"permission": "write"},
        )

        contents = await client.list_repository_contents(
            **developer,
            path=None,
            ref="main",  # type: ignore[arg-type]
        )
        readme = next(item for item in contents.items if item["path"] == "README.md")

        await client.commit_changes(
            **developer,  # type: ignore[arg-type]
            branch="main",
            new_branch=None,
            message="ci: add Forgejo workflow",
            signoff=False,
            changes=[
                {
                    "operation": "create",
                    "path": ".forgejo/workflows/ci.yml",
                    "content": (
                        "name: CI\non:\n  workflow_dispatch:\n"
                        "jobs:\n  test:\n    runs-on: docker\n"
                        "    steps:\n      - run: echo ok\n"
                    ),
                },
                {
                    "operation": "update",
                    "path": "README.md",
                    "sha": readme["sha"],
                    "content": "# Forgejo MCP E2E\n",
                },
            ],
        )
        branch = await client.create_branch(
            **developer,
            branch="feature/e2e",
            from_ref="main",  # type: ignore[arg-type]
        )
        commit = await client.commit_changes(
            **developer,  # type: ignore[arg-type]
            branch=branch.name,
            new_branch=None,
            message="feat: add greeting",
            signoff=True,
            changes=[
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
        )

        issue = await client.create_issue(
            **developer,  # type: ignore[arg-type]
            title="Add greeting",
            body="Implement the greeting function",
            assignees=[DEVELOPER],
            label_ids=None,
            milestone_id=None,
        )
        await client.comment_issue(
            **developer,  # type: ignore[arg-type]
            number=issue.number,
            body="Implementation is ready for review.",
        )
        comments = await client.list_issue_comments(
            **developer,  # type: ignore[arg-type]
            number=issue.number,
            since=None,
            before=None,
        )
        assert len(comments.items) == 1

        pull = await client.create_pull_request(
            **developer,  # type: ignore[arg-type]
            title="Add greeting",
            head=branch.name,
            base="main",
            body=f"Closes #{issue.number}",
            draft=False,
        )
        files = await client.list_pull_request_files(
            **developer,
            number=pull.number,  # type: ignore[arg-type]
        )
        assert {item["path"] for item in files.items} == {
            "src/greeting.py",
            "tests/test_greeting.py",
        }

        reviewer_arguments = {
            "number": pull.number,
            "reviewers": [REVIEWER],
            "team_reviewers": None,
        }
        await client.change_pull_request_reviewers(
            **developer,
            **reviewer_arguments,
            remove=False,  # type: ignore[arg-type]
        )
        await client.change_pull_request_reviewers(
            **developer,
            **reviewer_arguments,
            remove=True,  # type: ignore[arg-type]
        )
        await client.change_pull_request_reviewers(
            **developer,
            **reviewer_arguments,
            remove=False,  # type: ignore[arg-type]
        )

        review = await client.submit_pull_request_review(
            **reviewer,  # type: ignore[arg-type]
            number=pull.number,
            event="APPROVED",
            body="Looks good.",
            commit_id=commit["commit_sha"],
            comments=[
                {
                    "path": "src/greeting.py",
                    "body": "Clear implementation.",
                    "new_position": 2,
                }
            ],
        )
        assert review["state"] == "APPROVED"
        reviews = await client.list_pull_request_reviews(
            **developer,
            number=pull.number,  # type: ignore[arg-type]
        )
        assert any(item["state"] == "APPROVED" for item in reviews.items)

        status = await client.get_commit_status(
            **developer,
            ref=commit["commit_sha"],  # type: ignore[arg-type]
        )
        assert status["state"] in {"pending", "success", "failure", "error"}
        await client.merge_pull_request(
            **developer,  # type: ignore[arg-type]
            number=pull.number,
            method="squash",
            title="Add greeting",
            message="Merge reviewed greeting implementation",
            head_sha=commit["commit_sha"],
            delete_branch=True,
        )
        merged = await client.get_pull_request(
            **developer,
            number=pull.number,  # type: ignore[arg-type]
        )
        assert merged.merged is True

        await client.dispatch_workflow(
            **developer,  # type: ignore[arg-type]
            workflow="ci.yml",
            ref="main",
            inputs={},
        )

        tag = await client.create_tag(
            **developer,  # type: ignore[arg-type]
            tag="v0.1.0-e2e",
            target="main",
            message="E2E release",
        )
        assert tag["name"] == "v0.1.0-e2e"
        release = await client.create_release(
            **developer,  # type: ignore[arg-type]
            tag="v0.1.0-e2e",
            target="main",
            name="E2E release",
            body="Validated development workflow.",
            draft=False,
            prerelease=True,
        )
        assert release["tag_name"] == "v0.1.0-e2e"
    finally:
        await _api(
            "DELETE",
            f"/repos/{DEVELOPER}/{repo}",
            token=DEVELOPER_TOKEN,
        )
