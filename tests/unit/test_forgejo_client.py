import json

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


async def test_get_version_from_private_instance_login_page() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert "Authorization" not in request.headers
        if request.url.path == "/api/v1/version":
            assert request.headers["Accept"] == "application/json"
            return httpx.Response(
                403,
                json={"message": "Only signed in user is allowed to call APIs."},
            )
        assert request.url.path == "/user/login"
        assert request.headers["Accept"] == "text/html"
        return httpx.Response(
            200,
            text="assetVersionEncoded: encodeURIComponent('16.0.3~gitea-1.22.0')",
        )

    client = ForgejoClient(
        connect_timeout_seconds=2,
        transport=httpx.MockTransport(handler),
    )

    result = await client.get_version(base_url="https://git.example.test", verify_tls=True)

    assert result.version == "16.0.3+gitea-1.22.0"
    assert [request.url.path for request in requests] == [
        "/api/v1/version",
        "/user/login",
    ]


async def test_private_version_rejects_unexpected_denial() -> None:
    client = ForgejoClient(
        connect_timeout_seconds=2,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(403, json={"message": "forbidden"})
        ),
    )

    with pytest.raises(ExternalServiceUnavailable, match="unexpected"):
        await client.get_version(base_url="https://git.example.test", verify_tls=True)


async def test_private_version_rejects_invalid_login_marker() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/version":
            return httpx.Response(
                403,
                json={"message": "Only signed in user is allowed to call APIs."},
            )
        return httpx.Response(
            200,
            text="assetVersionEncoded: encodeURIComponent('not-a-version')",
        )

    client = ForgejoClient(
        connect_timeout_seconds=2,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ExternalServiceUnavailable, match="version"):
        await client.get_version(base_url="https://git.example.test", verify_tls=True)


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


async def test_repository_migration_update_and_mirror_sync() -> None:
    requests: list[tuple[str, str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        requests.append((request.method, request.url.path, body))
        if request.url.path == "/api/v1/repos/migrate":
            payload = repository_payload()
            payload.update({"name": "checkout", "full_name": "actions/checkout"})
            return httpx.Response(201, json=payload)
        if request.url.path == "/api/v1/repos/actions/checkout":
            return httpx.Response(200, json=repository_payload())
        if request.url.path == "/api/v1/repos/actions/checkout/mirror-sync":
            return httpx.Response(200)
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    client = ForgejoClient(connect_timeout_seconds=2, transport=httpx.MockTransport(handler))
    migrated = await client.migrate_repository(
        base_url="https://git.example.test",
        token="pat",
        verify_tls=True,
        clone_addr="https://github.com/actions/checkout.git",
        repo_name="checkout",
        repo_owner="actions",
        mirror=True,
        mirror_interval="8h0m0s",
        auth_token="upstream-token",
    )
    updated = await client.update_repository(
        base_url="https://git.example.test",
        token="pat",
        verify_tls=True,
        owner="actions",
        repo="checkout",
        mirror_interval="12h0m0s",
        enable_prune=True,
        has_actions=True,
        default_merge_style="fast-forward-only",
        external_wiki={"external_wiki_url": "https://example.test/wiki"},
    )
    await client.sync_mirror(
        base_url="https://git.example.test",
        token="pat",
        verify_tls=True,
        owner="actions",
        repo="checkout",
    )

    assert migrated.full_name == "actions/checkout"
    assert updated.id == 7
    assert requests == [
        (
            "POST",
            "/api/v1/repos/migrate",
            {
                "clone_addr": "https://github.com/actions/checkout.git",
                "repo_name": "checkout",
                "repo_owner": "actions",
                "mirror": True,
                "mirror_interval": "8h0m0s",
                "auth_token": "upstream-token",
            },
        ),
        (
            "PATCH",
            "/api/v1/repos/actions/checkout",
            {
                "mirror_interval": "12h0m0s",
                "enable_prune": True,
                "has_actions": True,
                "default_merge_style": "fast-forward-only",
                "external_wiki": {"external_wiki_url": "https://example.test/wiki"},
            },
        ),
        ("POST", "/api/v1/repos/actions/checkout/mirror-sync", None),
    ]


async def test_repository_migration_and_update_validate_sensitive_options() -> None:
    client = ForgejoClient(
        connect_timeout_seconds=2,
        transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
    )

    with pytest.raises(ValidationFailed, match="must not contain credentials"):
        await client.migrate_repository(
            base_url="https://git.example.test",
            token="pat",
            verify_tls=True,
            clone_addr="https://user:secret@example.test/repo.git",
            repo_name="repo",
        )
    with pytest.raises(ValidationFailed, match="at least one setting"):
        await client.update_repository(
            base_url="https://git.example.test",
            token="pat",
            verify_tls=True,
            owner="actions",
            repo="checkout",
        )


@pytest.mark.parametrize(
    "clone_addr",
    [
        "file:///etc/passwd",
        "https://localhost/repo.git",
        "http://127.0.0.1/repo.git",
        "http://[::1]/repo.git",
        "https://git.example.test/repo.git?access_token=secret",
        "git@example.test:owner/repo.git",
    ],
)
async def test_repository_migration_rejects_unsafe_remote_addresses(clone_addr: str) -> None:
    client = ForgejoClient(
        connect_timeout_seconds=2,
        transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
    )
    with pytest.raises(ValidationFailed):
        await client.migrate_repository(
            base_url="https://git.example.test",
            token="pat",
            verify_tls=True,
            clone_addr=clone_addr,
            repo_name="repo",
        )


async def test_repository_migration_private_host_requires_explicit_opt_in() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json=repository_payload())

    client = ForgejoClient(
        connect_timeout_seconds=2,
        migration_allow_private_hosts=True,
        transport=httpx.MockTransport(handler),
    )
    result = await client.migrate_repository(
        base_url="https://git.example.test",
        token="pat",
        verify_tls=True,
        clone_addr="http://forgejo:3000/owner/repo.git",
        repo_name="repo",
    )
    assert result.id == 7


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
    for owner, repo in (
        (".", "repo"),
        ("..", "repo"),
        ("\u00a0..\u00a0", "repo"),
        ("patrick", "."),
        ("patrick", ".."),
        ("patrick", "\u3000.\u3000"),
    ):
        with pytest.raises(ValidationFailed):
            await client.get_repository(
                base_url="https://git.example.test",
                token="pat",
                verify_tls=True,
                owner=owner,
                repo=repo,
            )
    for sha in (".", "..", "\u00a0..\u00a0", "\u3000.\u3000"):
        with pytest.raises(ValidationFailed, match="commit SHA"):
            await client.get_commit(
                base_url="https://git.example.test",
                token="pat",
                verify_tls=True,
                owner="patrick",
                repo="repo",
                sha=sha,
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
    for invalid_path in (
        "../secret",
        "./README.md",
        "src/./module.py",
        "\u00a0..\u00a0",
        "\u00a0../secret",
        "src/..\u3000",
    ):
        with pytest.raises(ValidationFailed, match="path"):
            await client.list_commits(
                base_url="https://git.example.test",
                token="pat",
                verify_tls=True,
                owner="patrick",
                repo="repo",
                ref=None,
                path=invalid_path,
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
