import os
import socket
import threading
import time

import pytest
import uvicorn
from playwright.sync_api import expect, sync_playwright
from test_forgejo_oauth_link import cfg as _cfg
from test_oauth_flow import DATABASE_URL

from forgejo_mcp.main import create_app

cfg = _cfg
pytestmark = pytest.mark.skipif(
    DATABASE_URL is None or os.getenv("FMCP_TEST_BROWSER") != "1",
    reason="opt-in PostgreSQL/Chromium test",
)


def test_admin_can_save_oauth_in_ui_with_fixed_redirect_and_no_secret_echo(cfg):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    issuer = f"http://127.0.0.1:{listener.getsockname()[1]}"
    values = cfg.model_dump()
    values.update(
        oauth_enabled=False,
        cookie_secure=False,
        forgejo_oauth_redirect_url=issuer + "/api/me/credential/oauth/callback",
    )
    server = uvicorn.Server(uvicorn.Config(create_app(type(cfg)(**values)), log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        assert server.started
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.getenv("FMCP_TEST_CHROMIUM_EXECUTABLE")
            )
            try:
                page = browser.new_page()
                page.goto(issuer)
                page.get_by_role("heading", name="Sign in", exact=True).wait_for()
                page.get_by_label("Username", exact=True).fill("admin")
                page.get_by_label("Password", exact=True).fill("admin-password-for-testing")
                page.get_by_role("button", name="Sign in", exact=True).click()
                page.get_by_role("heading", name="Forgejo OAuth settings", exact=True).wait_for()
                button = page.get_by_role("button", name="Save Forgejo OAuth settings", exact=True)
                expect(button).to_be_enabled()
                page.get_by_label("Enable Forgejo OAuth linking").check()
                page.get_by_label("MCP public base URL", exact=True).fill(
                    "HTTPS://PUBLIC-MCP.EXAMPLE.TEST:443/"
                )
                redirect = page.get_by_label("Forgejo redirect URL", exact=True)
                expect(redirect).to_have_value(
                    "https://public-mcp.example.test/api/me/credential/oauth/callback"
                )
                assert redirect.get_attribute("readonly") is not None
                page.get_by_label("Forgejo OAuth Client ID", exact=True).fill(
                    "browser-admin-client"
                )
                page.get_by_label("OAuth client type", exact=True).select_option("confidential")
                secret = page.get_by_label("Forgejo OAuth Client Secret", exact=True)
                secret.fill("browser-admin-client-secret")
                button.click()
                page.get_by_text("Forgejo OAuth settings saved.", exact=False).wait_for()
                expect(secret).to_have_value("")
                page.reload()
                expect(page.get_by_label("Forgejo OAuth Client ID", exact=True)).to_have_value(
                    "browser-admin-client"
                )
                expect(page.get_by_label("Forgejo OAuth Client Secret", exact=True)).to_have_value(
                    ""
                )
                public = page.evaluate(
                    "async () => (await fetch('/api/forgejo/instance/oauth')).json()"
                )
                assert public["secret_configured"] is True
                assert "browser-admin-client-secret" not in str(public)
                assert "client_secret" not in public
                page.get_by_label("MCP public base URL", exact=True).fill(
                    "https://public-mcp.example.test/evil-path"
                )
                expect(redirect).to_have_value("")
                expect(button).to_be_disabled()
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
