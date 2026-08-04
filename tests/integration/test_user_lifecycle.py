import asyncio
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from forgejo_mcp.config import Settings
from forgejo_mcp.main import create_app

DATABASE_URL = os.getenv("FMCP_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    DATABASE_URL is None, reason="integration PostgreSQL not configured"
)


async def reset_database() -> None:
    if DATABASE_URL is None:
        return
    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE management_audit_events, user_invitations, sessions, accounts, users "
                "RESTART IDENTITY CASCADE"
            )
        )
    await engine.dispose()


def csrf(client: TestClient) -> dict[str, str]:
    token = client.cookies.get("fmcp_csrf")
    assert token is not None
    return {"X-CSRF-Token": token}


def test_admin_invites_and_disables_user(tmp_path: Path) -> None:
    assert DATABASE_URL is not None
    asyncio.run(reset_database())
    password_file = tmp_path / "admin_password"
    password_file.write_text("bootstrap-password-for-testing", encoding="utf-8")
    app = create_app(
        Settings(
            environment="test",
            database_url=DATABASE_URL,
            bootstrap_admin_password_file=password_file,
            cookie_secure=False,
        )
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "bootstrap-password-for-testing"},
        )
        assert response.status_code == 200
        response = client.post(
            "/api/auth/change-password",
            headers=csrf(client),
            json={
                "current_password": "bootstrap-password-for-testing",
                "new_password": "changed-admin-password-for-testing",
            },
        )
        assert response.status_code == 200

        response = client.post(
            "/api/users",
            headers=csrf(client),
            json={
                "display_name": "Test User",
                "username": "test-user",
                "forgejo_username": "forgejo-test-user",
            },
        )
        assert response.status_code == 201
        user_id = response.json()["id"]

        response = client.post(f"/api/users/{user_id}/invitations", headers=csrf(client))
        assert response.status_code == 200
        invitation_token = response.json()["invitation_url"].split("token=", maxsplit=1)[1]

        response = client.post(
            "/api/auth/invitations/accept",
            json={"token": invitation_token, "password": "user-password-for-testing"},
        )
        assert response.status_code == 200
        reused = client.post(
            "/api/auth/invitations/accept",
            json={"token": invitation_token, "password": "another-password-for-testing"},
        )
        assert reused.status_code == 410

        admin_session = client.cookies.get("fmcp_session")
        admin_csrf = client.cookies.get("fmcp_csrf")
        assert admin_session is not None and admin_csrf is not None
        response = client.post(
            "/api/auth/login",
            json={"username": "test-user", "password": "user-password-for-testing"},
        )
        assert response.status_code == 200
        user_session = client.cookies.get("fmcp_session")
        user_csrf = client.cookies.get("fmcp_csrf")
        assert user_session is not None and user_csrf is not None
        assert client.get("/api/users").status_code == 403
        assert client.get("/api/auth/sessions").status_code == 200

        client.cookies.set("fmcp_session", admin_session)
        client.cookies.set("fmcp_csrf", admin_csrf)
        response = client.post(
            f"/api/users/{user_id}/disable",
            headers={"X-CSRF-Token": admin_csrf},
        )
        assert response.status_code == 200

        client.cookies.set("fmcp_session", user_session)
        client.cookies.set("fmcp_csrf", user_csrf)
        assert client.get("/api/auth/me").status_code == 401
