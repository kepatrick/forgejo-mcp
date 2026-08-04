import asyncio
import base64
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from mcp.shared.version import LATEST_PROTOCOL_VERSION
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from forgejo_mcp.application.mcp_token_service import McpTokenService
from forgejo_mcp.application.tool_permission_service import ToolPermissionService
from forgejo_mcp.auth.passwords import hash_password
from forgejo_mcp.config import Settings
from forgejo_mcp.credentials import CredentialCipher
from forgejo_mcp.db.models import (
    Account,
    AccountRole,
    CredentialStatus,
    ForgejoCredential,
    ForgejoInstance,
    RecordStatus,
    ToolInvocation,
    User,
)
from forgejo_mcp.forgejo.client import ForgejoClient, ForgejoUser, Page
from forgejo_mcp.forgejo.models import (
    BranchSummary,
    CommitDetail,
    CommitFileSummary,
    CommitStats,
    CommitSummary,
    CompareSummary,
    RepositorySummary,
)
from forgejo_mcp.main import create_app

DATABASE_URL = os.getenv("FMCP_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    DATABASE_URL is None, reason="integration PostgreSQL not configured"
)
TOOLS = {
    "forgejo_get_current_user",
    "forgejo_list_repositories",
    "forgejo_get_repository",
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
}
TOOL_NAME = "forgejo_get_current_user"


async def load_invocations() -> list[ToolInvocation]:
    assert DATABASE_URL is not None
    engine = create_async_engine(DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        records = list(
            (
                await session.scalars(select(ToolInvocation).order_by(ToolInvocation.started_at))
            ).all()
        )
    await engine.dispose()
    return records


async def remove_all_token_grants() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as connection:
        await connection.execute(text("DELETE FROM mcp_token_tool_grants"))
    await engine.dispose()


async def prepare_mcp_database(key_file: Path) -> str:
    assert DATABASE_URL is not None
    engine = create_async_engine(DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE mcp_token_tool_grants, user_tool_allowances, tool_settings, "
                "mcp_tokens, forgejo_credentials, forgejo_instances, management_audit_events, "
                "user_invitations, sessions, accounts, users RESTART IDENTITY CASCADE"
            )
        )
    async with factory() as session:
        admin = Account(
            username="admin",
            normalized_username="admin",
            role=AccountRole.ADMIN,
            password_hash=hash_password("admin-password-for-testing"),
            must_change_password=False,
            status=RecordStatus.ACTIVE,
        )
        user = User(
            display_name="Patrick",
            expected_forgejo_username="Patrick",
            normalized_forgejo_username="patrick",
            status=RecordStatus.ACTIVE,
        )
        account = Account(
            user=user,
            username="patrick",
            normalized_username="patrick",
            role=AccountRole.USER,
            password_hash=hash_password("user-password-for-testing"),
            must_change_password=False,
            status=RecordStatus.ACTIVE,
        )
        session.add_all([admin, user, account])
        await session.flush()
        now = datetime.now(UTC)
        encrypted = CredentialCipher.from_file(key_file, 1).encrypt("forgejo-test-pat", user.id)
        session.add_all(
            [
                ForgejoInstance(
                    slug="primary",
                    display_name="Test Forgejo",
                    base_url="https://git.example.test",
                    verify_tls=True,
                    version="16.0.2",
                    configured_by_account_id=admin.id,
                    last_checked_at=now,
                ),
                ForgejoCredential(
                    user_id=user.id,
                    encrypted_token=encrypted.ciphertext,
                    nonce=encrypted.nonce,
                    key_version=encrypted.key_version,
                    status=CredentialStatus.ACTIVE,
                    forgejo_user_id=42,
                    forgejo_username="Patrick",
                    normalized_forgejo_username="patrick",
                    verified_at=now,
                    activated_at=now,
                ),
            ]
        )
        await session.commit()
        created = await McpTokenService(session).create(
            actor_account_id=account.id,
            user_id=user.id,
            name="Protocol test",
            description=None,
            expires_at=None,
        )
        permissions = ToolPermissionService(session)
        for tool_name in TOOLS:
            await permissions.set_global_enabled(
                actor_account_id=admin.id, tool_name=tool_name, enabled=True
            )
        await permissions.replace_user_allowances(
            actor_account_id=admin.id, user_id=user.id, tool_names=TOOLS
        )
        await permissions.replace_token_grants(
            actor_account_id=account.id,
            user_id=user.id,
            token_id=created.record.id,
            tool_names=TOOLS,
        )
        plaintext = created.token
    await engine.dispose()
    return plaintext


def rpc(client: TestClient, token: str, payload: dict[str, Any], session_id: str | None = None):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    if session_id is not None:
        headers["MCP-Session-Id"] = session_id
        headers["MCP-Protocol-Version"] = LATEST_PROTOCOL_VERSION
    return client.post("/mcp", headers=headers, json=payload)


def test_mcp_initialize_list_and_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert DATABASE_URL is not None
    key_file = tmp_path / "credential_key"
    key_file.write_bytes(base64.b64encode(b"k" * 32))
    token = asyncio.run(prepare_mcp_database(key_file))

    async def fake_current_user(
        _self: ForgejoClient, *, base_url: str, token: str, verify_tls: bool
    ) -> ForgejoUser:
        assert base_url == "https://git.example.test"
        assert token == "forgejo-test-pat"
        assert verify_tls is True
        return ForgejoUser(id=42, username="Patrick")

    repository = RepositorySummary(
        id=7,
        owner="Patrick",
        name="forgejo-mcp",
        full_name="Patrick/forgejo-mcp",
        description="MCP server",
        private=True,
        fork=False,
        default_branch="main",
        archived=False,
        html_url="https://git.example.test/Patrick/forgejo-mcp",
        updated_at=datetime.now(UTC),
    )

    async def fake_list_repositories(_self: ForgejoClient, **_kwargs: object):
        return Page(items=[repository], page=1, limit=30, has_more=False)

    async def fake_get_repository(_self: ForgejoClient, **_kwargs: object):
        return repository

    async def fake_list_branches(_self: ForgejoClient, **_kwargs: object):
        return Page(
            items=[BranchSummary(name="main", commit_sha="abc123", protected=True)],
            page=1,
            limit=30,
            has_more=False,
        )

    commit = CommitSummary(
        sha="abc123",
        message="feat: test",
        html_url="https://git.example.test/commit/abc123",
        author_name="Patrick",
        author_email=None,
        authored_at=datetime.now(UTC),
        committer_name="Patrick",
        committed_at=datetime.now(UTC),
        parent_shas=["parent123"],
        stats=CommitStats(additions=3, deletions=1, total=4),
    )

    async def fake_list_commits(_self: ForgejoClient, **_kwargs: object):
        return Page(items=[commit], page=1, limit=30, has_more=False)

    async def fake_get_commit(_self: ForgejoClient, **_kwargs: object):
        return CommitDetail(
            **commit.model_dump(),
            files=[CommitFileSummary(path="README.md", status="modified")],
            files_truncated=False,
        )

    async def fake_compare_refs(_self: ForgejoClient, **_kwargs: object):
        return CompareSummary(
            base="main",
            head="feature/tool",
            total_commits=1,
            commits=[commit],
            files=[CommitFileSummary(path="README.md", status="modified")],
            commits_truncated=False,
            files_truncated=False,
        )

    monkeypatch.setattr(ForgejoClient, "get_current_user", fake_current_user)
    monkeypatch.setattr(ForgejoClient, "list_repositories", fake_list_repositories)
    monkeypatch.setattr(ForgejoClient, "get_repository", fake_get_repository)
    monkeypatch.setattr(ForgejoClient, "list_branches", fake_list_branches)
    monkeypatch.setattr(ForgejoClient, "list_commits", fake_list_commits)
    monkeypatch.setattr(ForgejoClient, "get_commit", fake_get_commit)
    monkeypatch.setattr(ForgejoClient, "compare_refs", fake_compare_refs)
    app = create_app(
        Settings(
            environment="test",
            database_url=DATABASE_URL,
            credential_encryption_key_file=key_file,
        )
    )
    with TestClient(app) as client:
        initialized = rpc(
            client,
            token,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": LATEST_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "integration-test", "version": "1.0"},
                },
            },
        )
        assert initialized.status_code == 200
        assert initialized.json()["result"]["serverInfo"]["name"] == "Forgejo MCP"
        session_id = initialized.headers["mcp-session-id"]

        notification = rpc(
            client,
            token,
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            session_id,
        )
        assert notification.status_code in {200, 202}

        listed = rpc(
            client,
            token,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            session_id,
        )
        assert listed.status_code == 200
        assert {tool["name"] for tool in listed.json()["result"]["tools"]} == TOOLS

        called = rpc(
            client,
            token,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": TOOL_NAME, "arguments": {}},
            },
            session_id,
        )
        assert called.status_code == 200
        result = called.json()["result"]
        assert result["isError"] is False
        assert result["structuredContent"] == {"id": 42, "username": "Patrick"}
        assert "forgejo-test-pat" not in called.text

        repositories = rpc(
            client,
            token,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "forgejo_list_repositories", "arguments": {}},
            },
            session_id,
        ).json()["result"]
        assert repositories["isError"] is False
        assert repositories["structuredContent"]["items"][0]["full_name"] == ("Patrick/forgejo-mcp")

        repository_result = rpc(
            client,
            token,
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "forgejo_get_repository",
                    "arguments": {"owner": "Patrick", "repo": "forgejo-mcp"},
                },
            },
            session_id,
        ).json()["result"]
        assert repository_result["isError"] is False
        assert repository_result["structuredContent"]["id"] == 7

        branches = rpc(
            client,
            token,
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {
                    "name": "forgejo_list_branches",
                    "arguments": {"owner": "Patrick", "repo": "forgejo-mcp"},
                },
            },
            session_id,
        ).json()["result"]
        assert branches["isError"] is False
        assert branches["structuredContent"]["items"][0]["commit_sha"] == "abc123"

        commits = rpc(
            client,
            token,
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {
                    "name": "forgejo_list_commits",
                    "arguments": {"owner": "Patrick", "repo": "forgejo-mcp"},
                },
            },
            session_id,
        ).json()["result"]
        assert commits["isError"] is False
        assert commits["structuredContent"]["items"][0]["sha"] == "abc123"

        commit_result = rpc(
            client,
            token,
            {
                "jsonrpc": "2.0",
                "id": 8,
                "method": "tools/call",
                "params": {
                    "name": "forgejo_get_commit",
                    "arguments": {
                        "owner": "Patrick",
                        "repo": "forgejo-mcp",
                        "sha": "abc123",
                    },
                },
            },
            session_id,
        ).json()["result"]
        assert commit_result["isError"] is False
        assert commit_result["structuredContent"]["files"][0]["path"] == "README.md"

        comparison = rpc(
            client,
            token,
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {
                    "name": "forgejo_compare_refs",
                    "arguments": {
                        "owner": "Patrick",
                        "repo": "forgejo-mcp",
                        "base": "main",
                        "head": "feature/tool",
                    },
                },
            },
            session_id,
        ).json()["result"]
        assert comparison["isError"] is False
        assert comparison["structuredContent"]["total_commits"] == 1

        invalid = rpc(
            client,
            token,
            {
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {
                    "name": "forgejo_list_branches",
                    "arguments": {"owner": "Patrick"},
                },
            },
            session_id,
        ).json()["result"]
        assert invalid["isError"] is True

        asyncio.run(remove_all_token_grants())
        hidden = rpc(
            client,
            token,
            {"jsonrpc": "2.0", "id": 11, "method": "tools/list", "params": {}},
            session_id,
        )
        assert hidden.json()["result"]["tools"] == []
        denied = rpc(
            client,
            token,
            {
                "jsonrpc": "2.0",
                "id": 12,
                "method": "tools/call",
                "params": {"name": TOOL_NAME, "arguments": {}},
            },
            session_id,
        )
        assert denied.json()["result"]["isError"] is True

    invocations = asyncio.run(load_invocations())
    assert [record.status for record in invocations].count("succeeded") == 7
    assert [record.status for record in invocations].count("failed") == 1
    assert [record.status for record in invocations].count("denied") == 1
    assert invocations[-1].denial_reason == "tool_not_granted_to_token"
    assert all(record.completed_at is not None for record in invocations)
    assert "forgejo-test-pat" not in repr(invocations)
