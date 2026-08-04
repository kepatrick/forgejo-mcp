import base64
import json
from datetime import UTC

import httpx
import pytest

from forgejo_mcp.application.errors import ExternalServiceUnavailable, ValidationFailed
from forgejo_mcp.forgejo.client import MAX_DIFF_BYTES, ForgejoClient


def user_payload() -> dict[str, object]:
    return {
        "id": 42,
        "login": "patrick",
        "full_name": "Patrick",
        "avatar_url": "https://git.example.test/avatar.png",
    }


def issue_payload() -> dict[str, object]:
    return {
        "number": 7,
        "title": "Tool request",
        "body": "Please add it",
        "state": "open",
        "html_url": "https://git.example.test/patrick/repo/issues/7",
        "user": user_payload(),
        "assignees": [user_payload()],
        "labels": [{"id": 1, "name": "feature", "color": "00ff00"}],
        "milestone": {"id": 2, "title": "v1"},
        "comments": 1,
        "created_at": "2025-08-02T12:00:00Z",
        "updated_at": "2025-08-02T13:00:00Z",
        "closed_at": None,
    }


def comment_payload() -> dict[str, object]:
    return {
        "id": 9,
        "body": "Implemented",
        "html_url": "https://git.example.test/patrick/repo/issues/7#issuecomment-9",
        "user": user_payload(),
        "created_at": "2025-08-02T14:00:00Z",
        "updated_at": "2025-08-02T14:00:00Z",
    }


def pull_payload() -> dict[str, object]:
    return {
        "number": 8,
        "title": "Add tool",
        "body": "Details",
        "state": "open",
        "draft": False,
        "mergeable": True,
        "merged": False,
        "html_url": "https://git.example.test/patrick/repo/pulls/8",
        "user": user_payload(),
        "base": {"ref": "main", "sha": "aaa", "repo": {"full_name": "patrick/repo"}},
        "head": {"ref": "feature", "sha": "bbb", "repo": {"full_name": "patrick/repo"}},
        "labels": [],
        "created_at": "2025-08-02T12:00:00Z",
        "updated_at": "2025-08-02T13:00:00Z",
        "closed_at": None,
        "merged_at": None,
        "commits": 2,
        "additions": 12,
        "deletions": 3,
        "changed_files": 4,
    }


async def test_issue_and_pull_read_tools_normalize_and_bound_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/issues"):
            assert request.url.params["type"] == "issues"
            assert request.url.params["q"] == "tool"
            return httpx.Response(200, json=[issue_payload()])
        if path.endswith("/issues/7/comments"):
            assert "limit" not in request.url.params
            return httpx.Response(200, json=[comment_payload()])
        if path.endswith("/issues/7"):
            return httpx.Response(200, json=issue_payload())
        if path.endswith("/pulls"):
            assert request.url.params.get_list("labels") == ["1", "2"]
            return httpx.Response(200, json=[pull_payload()])
        if path.endswith("/pulls/8"):
            return httpx.Response(200, json=pull_payload())
        raise AssertionError(path)

    client = ForgejoClient(connect_timeout_seconds=2, transport=httpx.MockTransport(handler))
    common = {
        "base_url": "https://git.example.test",
        "token": "pat",
        "verify_tls": True,
        "owner": "patrick",
        "repo": "repo",
    }
    issues = await client.list_issues(
        **common,
        state="open",
        labels=["feature"],
        milestones=None,
        query="tool",
        since="2025-08-01T00:00:00Z",
        before=None,
        sort="latest",
        page=1,
        limit=30,
    )
    issue = await client.get_issue(**common, number=7)
    comments = await client.list_issue_comments(**common, number=7, since=None, before=None)
    pulls = await client.list_pull_requests(
        **common,
        state="open",
        base="main",
        head=None,
        label_ids=[1, 2],
        milestone_id=None,
        sort="recentupdate",
        page=1,
        limit=30,
    )
    pull = await client.get_pull_request(**common, number=8)

    assert issues.items[0].user.username == "patrick"
    assert issue.created_at.tzinfo == UTC
    assert comments.items[0].body == "Implemented"
    assert comments.truncated is False
    assert pulls.items[0].head.sha == "bbb"
    assert pull.changed_files == 4


async def test_additional_repository_and_pull_read_tools_normalize_results() -> None:
    review = {
        "id": 3,
        "user": user_payload(),
        "state": "APPROVED",
        "body": "ok",
        "commit_id": "head-sha",
        "submitted_at": "2025-08-03T12:00:00Z",
        "stale": False,
        "dismissed": False,
        "comments_count": 0,
    }
    commit = {
        "sha": "head-sha",
        "commit": {"message": "feat: tool", "author": None, "committer": None},
        "parents": [],
        "stats": None,
        "files": None,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/git/trees/" in path:
            assert request.url.params["recursive"] == "true"
            assert request.url.params["per_page"] == "25"
            return httpx.Response(
                200,
                json={
                    "sha": "tree-sha",
                    "page": 1,
                    "total_count": 1,
                    "truncated": False,
                    "tree": [
                        {
                            "path": "src/tool.py",
                            "mode": "100644",
                            "type": "blob",
                            "size": 42,
                            "sha": "blob-sha",
                        }
                    ],
                },
            )
        if path.endswith("/labels"):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 1,
                        "name": "feature",
                        "color": "00ff00",
                        "description": "New feature",
                        "exclusive": False,
                        "is_archived": False,
                    }
                ],
            )
        if path.endswith("/milestones"):
            assert request.url.params["state"] == "all"
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 2,
                        "title": "v1",
                        "description": "First release",
                        "state": "open",
                        "open_issues": 1,
                        "closed_issues": 0,
                        "created_at": "2025-08-01T00:00:00Z",
                        "updated_at": "2025-08-02T00:00:00Z",
                        "due_on": None,
                        "closed_at": None,
                    }
                ],
            )
        if path.endswith("/pulls/8/commits"):
            assert request.url.params["files"] == "false"
            return httpx.Response(200, json=[commit])
        if path.endswith("/pulls/8/reviews/3"):
            return httpx.Response(200, json=review)
        if path.endswith("/pulls/8/merge"):
            return httpx.Response(404)
        if path.endswith("/pulls/8"):
            return httpx.Response(200, json=pull_payload())
        raise AssertionError(path)

    client = ForgejoClient(connect_timeout_seconds=2, transport=httpx.MockTransport(handler))
    common = {
        "base_url": "https://git.example.test",
        "token": "pat",
        "verify_tls": True,
        "owner": "patrick",
        "repo": "repo",
    }
    tree = await client.get_git_tree(**common, sha="main", recursive=True, page=1, limit=25)
    labels = await client.list_labels(**common, sort="mostissues", page=1, limit=30)
    milestones = await client.list_milestones(**common, state="all", name=None, page=1, limit=30)
    commits = await client.list_pull_request_commits(**common, number=8, page=1, limit=30)
    loaded_review = await client.get_pull_request_review(**common, number=8, review_id=3)
    merged = await client.get_pull_request_merge_status(**common, number=8)

    assert tree.entries[0].path == "src/tool.py"
    assert labels.items[0].description == "New feature"
    assert milestones.items[0].created_at.tzinfo == UTC
    assert commits.items[0].sha == "head-sha"
    assert loaded_review["state"] == "APPROVED"
    assert merged is False


async def test_file_and_diff_tools_enforce_content_contracts() -> None:
    raw = "hello 世界\n".encode()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/pulls/8.diff"):
            assert request.url.params["binary"] == "false"
            return httpx.Response(200, content=b"diff --git a/a b/a\n")
        assert request.url.raw_path.endswith(b"/contents/docs/readme.md?ref=main")
        return httpx.Response(
            200,
            json={
                "name": "readme.md",
                "sha": "abc",
                "size": len(raw),
                "encoding": "base64",
                "content": base64.b64encode(raw).decode(),
                "html_url": "https://git.example.test/patrick/repo/src/main/docs/readme.md",
            },
        )

    client = ForgejoClient(connect_timeout_seconds=2, transport=httpx.MockTransport(handler))
    common = {
        "base_url": "https://git.example.test",
        "token": "pat",
        "verify_tls": True,
        "owner": "patrick",
        "repo": "repo",
    }
    file = await client.get_file_content(**common, path="docs/readme.md", ref="main")
    diff = await client.get_pull_request_diff(**common, number=8)

    assert file.encoding == "utf-8"
    assert file.content == raw.decode()
    assert diff.size == len(diff.content.encode())
    assert len(diff.sha256) == 64

    oversized = ForgejoClient(
        connect_timeout_seconds=2,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, content=b"x" * (MAX_DIFF_BYTES + 1))
        ),
    )
    with pytest.raises(ExternalServiceUnavailable, match="too large"):
        await oversized.get_pull_request_diff(**common, number=8)


async def test_issue_and_pull_write_tools_send_only_declared_fields() -> None:
    requests: list[tuple[str, str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append((request.method, request.url.path, body))
        if request.url.path.endswith("/comments"):
            return httpx.Response(201, json=comment_payload())
        if "/pulls" in request.url.path:
            return httpx.Response(201, json=pull_payload())
        return httpx.Response(201, json=issue_payload())

    client = ForgejoClient(connect_timeout_seconds=2, transport=httpx.MockTransport(handler))
    common = {
        "base_url": "https://git.example.test",
        "token": "pat",
        "verify_tls": True,
        "owner": "patrick",
        "repo": "repo",
    }
    await client.create_issue(
        **common,
        title=" Tool request ",
        body="Details",
        assignees=["patrick"],
        label_ids=[1],
        milestone_id=2,
    )
    await client.update_issue(**common, number=7, changes={"state": "closed"})
    await client.comment_issue(**common, number=7, body="Done")
    await client.create_pull_request(
        **common,
        title="Add tool",
        head="feature",
        base="main",
        body=None,
        draft=False,
    )
    await client.update_pull_request(**common, number=8, changes={"base": "release"})

    assert requests[0][2] == {
        "title": "Tool request",
        "body": "Details",
        "assignees": ["patrick"],
        "labels": [1],
        "milestone": 2,
    }
    assert requests[1][2] == {"state": "closed"}
    assert requests[2][2] == {"body": "Done"}
    assert requests[3][2] == {
        "title": "Add tool",
        "head": "feature",
        "base": "main",
        "draft": False,
    }
    assert requests[4][2] == {"base": "release"}

    with pytest.raises(ValidationFailed, match="fields"):
        await client.update_issue(**common, number=7, changes={})


async def test_development_workflow_tools_use_supported_forgejo_endpoints() -> None:
    seen: list[tuple[str, str, dict[str, object] | None]] = []
    content = {
        "name": "README.md",
        "path": "README.md",
        "sha": "file-sha",
        "type": "file",
        "size": 4,
        "html_url": "https://git.example.test/readme",
    }
    review = {
        "id": 3,
        "user": user_payload(),
        "state": "APPROVED",
        "body": "ok",
        "commit_id": "head-sha",
        "submitted_at": "2025-08-03T12:00:00Z",
        "stale": False,
        "dismissed": False,
        "comments_count": 0,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        seen.append((request.method, request.url.path, body))
        path = request.url.path
        if path.endswith("/contents") and request.method == "GET":
            return httpx.Response(200, json=[content])
        if path.endswith("/branches"):
            return httpx.Response(
                201, json={"name": "feature", "commit": {"id": "head-sha"}, "protected": False}
            )
        if path.endswith("/contents"):
            return httpx.Response(201, json={"commit": {"sha": "commit-sha"}, "files": [content]})
        if path.endswith("/pulls/8/files"):
            return httpx.Response(
                200,
                json=[
                    {
                        "filename": "README.md",
                        "status": "modified",
                        "additions": 1,
                        "deletions": 0,
                        "changes": 1,
                    }
                ],
            )
        if path.endswith("/requested_reviewers"):
            return httpx.Response(204)
        if path.endswith("/reviews") and request.method == "GET":
            return httpx.Response(200, json=[review])
        if path.endswith("/reviews"):
            return httpx.Response(200, json=review)
        if path.endswith("/merge"):
            return httpx.Response(200)
        if path.endswith("/status"):
            return httpx.Response(
                200,
                json={
                    "sha": "head-sha",
                    "state": "success",
                    "total_count": 1,
                    "statuses": [
                        {
                            "context": "ci",
                            "status": "success",
                            "description": "passed",
                            "target_url": "https://ci.example.test",
                        }
                    ],
                },
            )
        if path.endswith("/dispatches"):
            return httpx.Response(204)
        if path.endswith("/tags"):
            return httpx.Response(
                201,
                json={
                    "name": "v1.0.0",
                    "id": "tag-id",
                    "commit": {"sha": "head-sha"},
                    "message": "release",
                },
            )
        if path.endswith("/releases"):
            return httpx.Response(
                201,
                json={
                    "id": 4,
                    "tag_name": "v1.0.0",
                    "name": "v1",
                    "html_url": "https://git.example.test/release",
                    "draft": False,
                    "prerelease": False,
                },
            )
        raise AssertionError(path)

    client = ForgejoClient(connect_timeout_seconds=2, transport=httpx.MockTransport(handler))
    common = {
        "base_url": "https://git.example.test",
        "token": "pat",
        "verify_tls": True,
        "owner": "patrick",
        "repo": "repo",
    }
    assert (await client.list_repository_contents(**common, path=None, ref="main")).items[0][
        "path"
    ] == "README.md"
    assert (
        await client.create_branch(**common, branch="feature", from_ref="main")
    ).name == "feature"
    commit = await client.commit_changes(
        **common,
        branch="feature",
        new_branch=None,
        message="feat: update",
        changes=[
            {"operation": "update", "path": "README.md", "sha": "file-sha", "content": "next"}
        ],
        signoff=False,
    )
    assert commit["commit_sha"] == "commit-sha"
    assert (await client.list_pull_request_files(**common, number=8)).items[0]["changes"] == 1
    await client.change_pull_request_reviewers(
        **common, number=8, reviewers=["reviewer"], team_reviewers=None, remove=False
    )
    await client.change_pull_request_reviewers(
        **common, number=8, reviewers=["reviewer"], team_reviewers=None, remove=True
    )
    assert (await client.list_pull_request_reviews(**common, number=8)).items[0][
        "state"
    ] == "APPROVED"
    submitted = await client.submit_pull_request_review(
        **common, number=8, event="APPROVED", body="ok", commit_id="head-sha", comments=None
    )
    assert submitted["user"] == "patrick"
    await client.merge_pull_request(
        **common,
        number=8,
        method="squash",
        title=None,
        message=None,
        head_sha="head-sha",
        delete_branch=True,
    )
    assert (await client.get_commit_status(**common, ref="head-sha"))["state"] == "success"
    await client.dispatch_workflow(
        **common, workflow="ci.yml", ref="main", inputs={"target": "test"}
    )
    assert (await client.create_tag(**common, tag="v1.0.0", target="main", message="release"))[
        "name"
    ] == "v1.0.0"
    assert (
        await client.create_release(
            **common,
            tag="v1.0.0",
            target="main",
            name="v1",
            body="notes",
            draft=False,
            prerelease=False,
        )
    )["id"] == 4

    methods_and_paths = {(method, path) for method, path, _body in seen}
    assert ("POST", "/api/v1/repos/patrick/repo/contents") in methods_and_paths
    assert ("POST", "/api/v1/repos/patrick/repo/pulls/8/merge") in methods_and_paths


async def test_empty_combined_status_normalizes_to_pending() -> None:
    client = ForgejoClient(
        connect_timeout_seconds=2,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={"sha": "head-sha", "state": "", "statuses": None, "total_count": 0},
            )
        ),
    )
    status = await client.get_commit_status(
        base_url="https://git.example.test",
        token="pat",
        verify_tls=True,
        owner="patrick",
        repo="repo",
        ref="head-sha",
    )
    assert status == {
        "sha": "head-sha",
        "state": "pending",
        "total_count": 0,
        "statuses": [],
        "truncated": False,
    }
