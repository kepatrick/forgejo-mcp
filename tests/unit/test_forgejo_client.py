import httpx
import pytest

from forgejo_mcp.application.errors import ExternalServiceUnavailable, NotFound, ValidationFailed
from forgejo_mcp.forgejo.client import ForgejoClient, normalize_base_url


def test_normalize_base_url() -> None:
    assert normalize_base_url(" HTTPS://Git.Example.test/forgejo/ ") == (
        "https://git.example.test/forgejo"
    )


@pytest.mark.parametrize(
    "value",
    [
        "git.example.test",
        "ftp://git.example.test",
        "https://user:secret@git.example.test",
        "https://git.example.test?token=secret",
        "https://git.example.test/#fragment",
    ],
)
def test_reject_invalid_base_url(value: str) -> None:
    with pytest.raises(ValidationFailed):
        normalize_base_url(value)


async def test_get_version() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://git.example.test/api/v1/version"
        return httpx.Response(200, json={"version": "16.0.1+gitea-1.22"})

    client = ForgejoClient(
        connect_timeout_seconds=2,
        transport=httpx.MockTransport(handler),
    )

    result = await client.get_version(base_url="https://git.example.test", verify_tls=True)

    assert result.version == "16.0.1+gitea-1.22"


async def test_reject_redirect() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(302, headers={"location": "https://other.test"})
    )
    client = ForgejoClient(connect_timeout_seconds=2, transport=transport)

    with pytest.raises(ExternalServiceUnavailable, match="redirect"):
        await client.get_version(base_url="https://git.example.test", verify_tls=True)


async def test_get_current_user_uses_pat_without_returning_it() -> None:
    token = "private-forgejo-pat"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://git.example.test/api/v1/user"
        assert request.headers["Authorization"] == f"token {token}"
        return httpx.Response(200, json={"id": 42, "login": "patrick"})

    client = ForgejoClient(
        connect_timeout_seconds=2,
        transport=httpx.MockTransport(handler),
    )

    principal = await client.get_current_user(
        base_url="https://git.example.test",
        token=token,
        verify_tls=True,
    )

    assert principal.id == 42
    assert principal.username == "patrick"
    assert token not in repr(principal)


async def test_reject_invalid_pat() -> None:
    client = ForgejoClient(
        connect_timeout_seconds=2,
        transport=httpx.MockTransport(lambda _request: httpx.Response(401)),
    )

    with pytest.raises(ValidationFailed, match="rejected"):
        await client.get_current_user(
            base_url="https://git.example.test",
            token="invalid-token",
            verify_tls=True,
        )


def repository_payload() -> dict[str, object]:
    return {
        "id": 7,
        "owner": {"login": "patrick"},
        "name": "forgejo-mcp",
        "full_name": "patrick/forgejo-mcp",
        "description": "MCP server",
        "private": True,
        "fork": False,
        "default_branch": "main",
        "archived": False,
        "html_url": "https://git.example.test/patrick/forgejo-mcp",
        "updated_at": "2025-08-02T12:00:00Z",
        "stars_count": 3,
        "forks_count": 1,
        "open_issues_count": 2,
        "permissions": {"admin": True, "pull": True, "push": True},
    }


async def test_list_repositories_uses_bounded_pagination_and_normalizes_output() -> None:
    token = "private-forgejo-pat"

    def handler(request: httpx.Request) -> httpx.Response:
        assert dict(request.url.params) == {
            "page": "2",
            "limit": "1",
            "order_by": "recentupdate",
        }
        assert request.headers["Authorization"] == f"token {token}"
        return httpx.Response(200, json=[repository_payload()])

    client = ForgejoClient(connect_timeout_seconds=2, transport=httpx.MockTransport(handler))
    result = await client.list_repositories(
        base_url="https://git.example.test",
        token=token,
        verify_tls=True,
        page=2,
        limit=1,
        order_by="recentupdate",
    )

    assert result.page == 2
    assert result.has_more is True
    assert result.items[0].full_name == "patrick/forgejo-mcp"
    assert token not in repr(result)


async def test_get_repository_and_list_branches_encode_paths() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/branches"):
            return httpx.Response(
                200,
                json=[{"name": "main", "commit": {"id": "abc123"}, "protected": True}],
            )
        assert request.url.path == "/api/v1/repos/patrick/forgejo-mcp"
        return httpx.Response(200, json=repository_payload())

    client = ForgejoClient(connect_timeout_seconds=2, transport=httpx.MockTransport(handler))
    repository = await client.get_repository(
        base_url="https://git.example.test",
        token="pat",
        verify_tls=True,
        owner="patrick",
        repo="forgejo-mcp",
    )
    branches = await client.list_branches(
        base_url="https://git.example.test",
        token="pat",
        verify_tls=True,
        owner="patrick",
        repo="forgejo-mcp",
        page=1,
        limit=30,
    )

    assert repository.id == 7
    assert branches.items[0].commit_sha == "abc123"
    assert branches.items[0].protected is True


async def test_create_organization_repository_posts_bounded_options() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/orgs/platform team/repos"
        assert request.url.raw_path == b"/api/v1/orgs/platform%20team/repos"
        assert request.read().decode() == (
            '{"name":"new-repo","private":true,"auto_init":true,'
            '"description":"Service repository","default_branch":"main"}'
        )
        payload = repository_payload()
        payload.update(
            {
                "owner": {"login": "platform team"},
                "name": "new-repo",
                "full_name": "platform team/new-repo",
            }
        )
        return httpx.Response(201, json=payload)

    client = ForgejoClient(connect_timeout_seconds=2, transport=httpx.MockTransport(handler))
    repository = await client.create_organization_repository(
        base_url="https://git.example.test",
        token="pat",
        verify_tls=True,
        organization="platform team",
        name="new-repo",
        description="Service repository",
        private=True,
        auto_init=True,
        default_branch="main",
    )

    assert repository.full_name == "platform team/new-repo"


async def test_create_organization_repository_validates_input() -> None:
    client = ForgejoClient(
        connect_timeout_seconds=2,
        transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
    )

    with pytest.raises(ValidationFailed, match="organization"):
        await client.create_organization_repository(
            base_url="https://git.example.test",
            token="pat",
            verify_tls=True,
            organization="bad/org",
            name="repo",
            description=None,
            private=False,
            auto_init=False,
            default_branch=None,
        )


def commit_payload(sha: str = "abc123") -> dict[str, object]:
    return {
        "sha": sha,
        "html_url": f"https://git.example.test/commit/{sha}",
        "commit": {
            "message": "feat: add tool",
            "author": {
                "name": "Patrick",
                "email": "patrick@example.test",
                "date": "2025-08-02T12:00:00Z",
            },
            "committer": {"name": "Patrick", "date": "2025-08-02T12:01:00Z"},
        },
        "parents": [{"sha": "parent123"}],
        "stats": {"additions": 10, "deletions": 2, "total": 12},
        "files": [{"filename": "src/tool.py", "status": "modified"}],
    }


async def test_commit_tools_normalize_and_bound_responses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/commits"):
            assert request.url.params["sha"] == "main"
            assert request.url.params["path"] == "src/tool.py"
            assert request.url.params["files"] == "false"
            return httpx.Response(200, json=[commit_payload()])
        if "/git/commits/" in request.url.path:
            assert request.url.params["files"] == "true"
            payload = commit_payload()
            payload["files"] = [
                {"filename": f"file-{index}.txt", "status": "modified"} for index in range(101)
            ]
            return httpx.Response(200, json=payload)
        assert request.url.raw_path.endswith(b"/compare/main...feature%2Ftool")
        return httpx.Response(
            200,
            json={
                "total_commits": 1,
                "commits": [commit_payload()],
                "files": [{"filename": "src/tool.py", "status": "modified"}],
            },
        )

    client = ForgejoClient(connect_timeout_seconds=2, transport=httpx.MockTransport(handler))
    commits = await client.list_commits(
        base_url="https://git.example.test",
        token="pat",
        verify_tls=True,
        owner="patrick",
        repo="forgejo-mcp",
        ref="main",
        path="src/tool.py",
        page=1,
        limit=30,
    )
    commit = await client.get_commit(
        base_url="https://git.example.test",
        token="pat",
        verify_tls=True,
        owner="patrick",
        repo="forgejo-mcp",
        sha="abc123",
    )
    comparison = await client.compare_refs(
        base_url="https://git.example.test",
        token="pat",
        verify_tls=True,
        owner="patrick",
        repo="forgejo-mcp",
        base="main",
        head="feature/tool",
    )

    assert commits.items[0].stats is not None
    assert commits.items[0].stats.total == 12
    assert commits.items[0].parent_shas == ["parent123"]
    assert len(commit.files) == 100
    assert commit.files_truncated is True
    assert comparison.total_commits == 1
    assert comparison.files[0].path == "src/tool.py"


async def test_repository_requests_reject_invalid_inputs_and_not_found() -> None:
    client = ForgejoClient(
        connect_timeout_seconds=2,
        transport=httpx.MockTransport(lambda _request: httpx.Response(404)),
    )

    with pytest.raises(ValidationFailed, match="owner"):
        await client.get_repository(
            base_url="https://git.example.test",
            token="pat",
            verify_tls=True,
            owner="bad/owner",
            repo="repo",
        )
    with pytest.raises(ValidationFailed, match="limit"):
        await client.list_repositories(
            base_url="https://git.example.test",
            token="pat",
            verify_tls=True,
            page=1,
            limit=101,
            order_by="name",
        )
    with pytest.raises(ValidationFailed, match="path"):
        await client.list_commits(
            base_url="https://git.example.test",
            token="pat",
            verify_tls=True,
            owner="patrick",
            repo="repo",
            ref=None,
            path="../secret",
            page=1,
            limit=30,
        )
    with pytest.raises(NotFound, match="repository"):
        await client.get_repository(
            base_url="https://git.example.test",
            token="pat",
            verify_tls=True,
            owner="patrick",
            repo="missing",
        )


async def test_reject_invalid_version_payload() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={"name": "Forgejo"}))
    client = ForgejoClient(connect_timeout_seconds=2, transport=transport)

    with pytest.raises(ExternalServiceUnavailable, match="invalid version"):
        await client.get_version(base_url="https://git.example.test", verify_tls=True)
