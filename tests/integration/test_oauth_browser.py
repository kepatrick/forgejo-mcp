"""Real Chromium form submission: TestClient alone cannot enforce browser CSP.

Run with FMCP_TEST_BROWSER=1 and FMCP_TEST_DATABASE_URL against a migrated,
throwaway PostgreSQL database. Build the Dashboard with
`npm ci --prefix frontend && npm run build --prefix frontend` and install Chromium
with `playwright install chromium`.
FMCP_TEST_CHROMIUM_EXECUTABLE optionally selects an existing Chromium binary.
"""

import base64
import hashlib
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest
import uvicorn
from playwright.sync_api import sync_playwright
from test_oauth_flow import DATABASE_URL, prepare_oauth_database

from forgejo_mcp.config import Settings
from forgejo_mcp.main import create_app

pytestmark = pytest.mark.skipif(
    DATABASE_URL is None or os.getenv("FMCP_TEST_BROWSER") != "1",
    reason="opt-in PostgreSQL/Chromium browser test",
)


@pytest.mark.parametrize("action", ["approve", "deny"])
def test_consent_cross_origin_callback_in_chromium(action):
    import asyncio

    dashboard = Path(__file__).resolve().parents[2] / "frontend/dist/index.html"
    assert dashboard.is_file(), (
        "Build the Dashboard before running Chromium tests: "
        "npm ci --prefix frontend && npm run build --prefix frontend"
    )
    asyncio.run(prepare_oauth_database())
    callbacks = []
    callback_referrers = []

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self):
            callbacks.append(self.path)
            callback_referrers.append(self.headers.get("Referer"))
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<p>OAuth callback received</p>")

        def log_message(self, *args):
            pass

    callback = ThreadingHTTPServer(("127.0.0.1", 0), Callback)
    callback_thread = threading.Thread(target=callback.serve_forever, daemon=True)
    callback_thread.start()
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    issuer = f"http://127.0.0.1:{sock.getsockname()[1]}"
    redirect_uri = f"http://127.0.0.1:{callback.server_port}/callback"
    settings = Settings(
        environment="test",
        database_url=DATABASE_URL,
        oauth_enabled=True,
        oauth_issuer_url=issuer,
        oauth_resource_url=f"{issuer}/mcp",
        cookie_secure=False,
    )
    server = uvicorn.Server(uvicorn.Config(create_app(settings), log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        with httpx.Client(base_url=issuer) as http:
            registration = http.post(
                "/register",
                json={
                    "client_name": "Browser regression client",
                    "redirect_uris": [redirect_uri],
                    "token_endpoint_auth_method": "none",
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                },
            )
            assert registration.status_code == 201
            cid = registration.json()["client_id"]
            verifier = "v" * 64
            challenge = (
                base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                .decode()
                .rstrip("=")
            )
            params = {
                "client_id": cid,
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "browser-test",
            }
            # Callback widening must never make an unregistered callback valid.
            assert (
                http.get(
                    "/authorize", params={**params, "redirect_uri": "https://attacker.example/"}
                ).status_code
                == 400
            )
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    executable_path=os.getenv("FMCP_TEST_CHROMIUM_EXECUTABLE"),
                )
                try:
                    page = browser.new_page()
                    page.goto(issuer)
                    # Wait for the React auth lookup/loading shell to settle.
                    page.get_by_role("heading", name="Sign in", exact=True).wait_for()
                    dashboard_color = page.locator(".shell").evaluate(
                        "element => getComputedStyle(element).backgroundColor"
                    )
                    dashboard_card = page.locator(".authCard").evaluate(
                        "element => getComputedStyle(element).borderRadius"
                    )
                    page.goto(f"{issuer}/authorize?{urlencode(params)}")
                    assert (
                        page.locator(".shell").evaluate(
                            "element => getComputedStyle(element).backgroundColor"
                        )
                        == dashboard_color
                    )
                    assert (
                        page.locator(".authCard").evaluate(
                            "element => getComputedStyle(element).borderRadius"
                        )
                        == dashboard_card
                    )
                    page.locator('input[name="username"]').fill("oauth-user")
                    page.locator('input[name="password"]').fill("user-password-for-testing")
                    with page.expect_response(lambda r: r.url.endswith("/oauth/login")) as login:
                        page.get_by_role("button", name="Sign in", exact=True).click()
                    assert login.value.status == 303, (
                        login.value.text(),
                        login.value.request.headers.get("origin"),
                    )
                    page.get_by_role("heading", name="Authorize MCP access?").wait_for()
                    tools = page.locator('input[name="tool_names"]')
                    assert tools.count() == 18
                    assert page.locator('input[name="tool_names"]:checked').count() == 0
                    if action == "approve":
                        page.locator('select[name="grant_ttl_days"]').select_option("7")
                        tools.first.check()
                    # Deny must work with no tools selected.
                    with page.expect_navigation():
                        page.locator(f'button[value="{action}"]').click()
                    assert page.url.startswith(redirect_uri + "?")
                finally:
                    browser.close()
            assert len(callbacks) == 1
            assert callback_referrers == [None]
            query = parse_qs(urlsplit(callbacks[0]).query)
            assert query["state"] == ["browser-test"]
            assert query["iss"] == [issuer]
            if action == "deny":
                assert query["error"] == ["access_denied"]
                assert "code" not in query
            else:
                exchanged = http.post(
                    "/token",
                    data={
                        "grant_type": "authorization_code",
                        "client_id": cid,
                        "code": query["code"][0],
                        "code_verifier": verifier,
                        "redirect_uri": redirect_uri,
                    },
                )
                assert exchanged.status_code == 200
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        callback.shutdown()
        callback.server_close()
        callback_thread.join(timeout=5)
