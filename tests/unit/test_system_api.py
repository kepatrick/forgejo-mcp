from fastapi.testclient import TestClient

from forgejo_mcp.config import Settings
from forgejo_mcp.main import create_app


def test_liveness() -> None:
    app = create_app(Settings(environment="test"))
    with TestClient(app) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_mcp_endpoint_requires_bearer_auth_without_redirecting() -> None:
    app = create_app(Settings(environment="test"))
    with TestClient(app) as client:
        response = client.post(
            "/mcp?token=fmcp_not-accepted",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            follow_redirects=False,
        )

    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")
    assert response.url.path == "/mcp"


def test_version() -> None:
    app = create_app(Settings(environment="test"))
    with TestClient(app) as client:
        response = client.get("/api/system/version")

    assert response.status_code == 200
    assert response.json() == {"name": "forgejo-mcp", "version": "0.1.0"}
