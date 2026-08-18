import io
import zipfile

import httpx

from forgejo_mcp.forgejo.client import MAX_ACTION_LOG_BYTES, ForgejoClient


def action_run_payload() -> dict[str, object]:
    return {
        "id": 42,
        "index_in_repo": 7,
        "title": "CI",
        "event": "push",
        "status": "success",
        "workflow_id": "ci.yml",
        "commit_sha": "abc123",
        "prettyref": "main",
        "html_url": "https://git.example.test/patrick/repo/actions/runs/7",
        "created": "2026-08-18T10:00:00Z",
        "started": "2026-08-18T10:00:01Z",
        "stopped": "2026-08-18T10:01:00Z",
        "updated": "2026-08-18T10:01:00Z",
        "duration": 59,
    }


async def test_list_and_get_action_runs_normalize_v16_payloads() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/actions/runs"):
            assert request.url.params.multi_items() == [
                ("page", "2"),
                ("limit", "1"),
                ("event", "push"),
                ("event", "workflow_dispatch"),
                ("status", "success"),
                ("workflow_id", "ci.yml"),
                ("head_sha", "abc123"),
                ("ref", "main"),
                ("run_number", "7"),
            ]
            return httpx.Response(
                200, json={"total_count": 3, "workflow_runs": [action_run_payload()]}
            )
        assert request.url.path.endswith("/actions/runs/42")
        return httpx.Response(200, json=action_run_payload())

    client = ForgejoClient(connect_timeout_seconds=2, transport=httpx.MockTransport(handler))
    common = {
        "base_url": "https://git.example.test",
        "token": "pat",
        "verify_tls": True,
        "owner": "patrick",
        "repo": "repo",
    }
    runs = await client.list_action_runs(
        **common,
        event=["push", "workflow_dispatch"],
        status=["success"],
        workflow_id="ci.yml",
        run_number=7,
        head_sha="abc123",
        ref="main",
        page=2,
        limit=1,
    )
    run = await client.get_action_run(**common, run_id=42)

    assert runs["total_count"] == 3
    assert runs["has_more"] is True
    assert runs["items"][0]["run_number"] == 7
    assert run["head_sha"] == "abc123"
    assert run["completed_at"] == "2026-08-18T10:01:00Z"


async def test_list_action_jobs_and_artifacts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/jobs"):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 51,
                        "run_id": 42,
                        "name": "test",
                        "status": "success",
                        "attempt": 1,
                        "runs_on": ["docker"],
                        "needs": [],
                    }
                ],
            )
        assert request.url.path.endswith("/artifacts")
        assert dict(request.url.params) == {"page": "1", "limit": "30", "name": "coverage"}
        return httpx.Response(
            200,
            json=[
                {
                    "id": 61,
                    "run_id": 42,
                    "name": "coverage",
                    "size_in_bytes": 1234,
                    "expired": False,
                    "created_at": "2026-08-18T10:01:00Z",
                    "expires_at": None,
                    "updated_at": "2026-08-18T10:01:00Z",
                    "archive_download_url": "https://git.example.test/artifacts/61.zip",
                }
            ],
        )

    client = ForgejoClient(connect_timeout_seconds=2, transport=httpx.MockTransport(handler))
    common = {
        "base_url": "https://git.example.test",
        "token": "pat",
        "verify_tls": True,
        "owner": "patrick",
        "repo": "repo",
        "run_id": 42,
    }
    jobs = await client.list_action_run_jobs(**common)
    artifacts = await client.list_action_run_artifacts(**common, name="coverage", page=1, limit=30)

    assert jobs.items[0]["runner_labels"] == ["docker"]
    assert jobs.truncated is False
    assert artifacts.items[0]["size_in_bytes"] == 1234


async def test_action_logs_are_bounded_and_run_archive_is_extracted() -> None:
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("test-51-attempt-1.log", "tests passed\n")
        archive.writestr("lint-52-attempt-1.log", "lint passed\n")
    archive_bytes = archive_buffer.getvalue()
    oversized_log = b"x" * (MAX_ACTION_LOG_BYTES + 1)

    def handler(request: httpx.Request) -> httpx.Response:
        if "/actions/jobs/51/logs" in request.url.path:
            assert request.url.params["attempt"] == "2"
            assert request.headers["Accept"] == "text/plain"
            return httpx.Response(200, content=oversized_log)
        assert request.url.path.endswith("/actions/runs/42/logs")
        assert request.headers["Accept"] == "application/zip"
        return httpx.Response(200, content=archive_bytes)

    client = ForgejoClient(connect_timeout_seconds=2, transport=httpx.MockTransport(handler))
    common = {
        "base_url": "https://git.example.test",
        "token": "pat",
        "verify_tls": True,
        "owner": "patrick",
        "repo": "repo",
    }
    job_log = await client.get_action_job_log(**common, job_id=51, attempt=2)
    run_logs = await client.get_action_run_logs(**common, run_id=42)

    assert job_log["truncated"] is True
    assert len(job_log["content"]) == MAX_ACTION_LOG_BYTES
    assert [item["name"] for item in run_logs["files"]] == [
        "test-51-attempt-1.log",
        "lint-52-attempt-1.log",
    ]
    assert run_logs["files_truncated"] is False


async def test_cancel_and_delete_action_run_use_native_routes() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        return httpx.Response(204)

    client = ForgejoClient(connect_timeout_seconds=2, transport=httpx.MockTransport(handler))
    common = {
        "base_url": "https://git.example.test",
        "token": "pat",
        "verify_tls": True,
        "owner": "patrick",
        "repo": "repo",
        "run_id": 42,
    }
    await client.cancel_action_run(**common)
    await client.delete_action_run(**common)

    assert seen == [
        ("POST", "/api/v1/repos/patrick/repo/actions/runs/42/cancel"),
        ("DELETE", "/api/v1/repos/patrick/repo/actions/runs/42"),
    ]
