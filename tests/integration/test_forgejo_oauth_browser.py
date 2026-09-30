"""Cross-site Chromium callback with Strict Dashboard cookies left unchanged."""

import asyncio
import html
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
import uvicorn
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_forgejo_oauth_link import CALLBACK
from test_forgejo_oauth_link import cfg as _cfg
from test_oauth_flow import DATABASE_URL

from forgejo_mcp.db.models import ForgejoInstance
from forgejo_mcp.forgejo.client import ForgejoClient, ForgejoOAuthToken, ForgejoUser
from forgejo_mcp.forgejo.oauth import ForgejoOAuthClient, ForgejoOAuthTokens
from forgejo_mcp.main import create_app

# Re-export the shared database/settings fixture for this test module.
cfg = _cfg

pytestmark = pytest.mark.skipif(
    DATABASE_URL is None or os.getenv("FMCP_TEST_BROWSER") != "1",
    reason="opt-in PostgreSQL/Chromium test",
)


def test_forgejo_cross_site_callback_uses_only_short_lived_browser_binding(cfg, monkeypatch):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    issuer = f"http://127.0.0.1:{listener.getsockname()[1]}"
    seen = []

    class Provider(BaseHTTPRequestHandler):
        def do_GET(self):
            params = parse_qs(urlsplit(self.path).query)
            seen.append(params)
            callback = (
                issuer
                + CALLBACK
                + "?"
                + urlencode({"code": "browser-code", "state": params["state"][0]})
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                f'<a href="{html.escape(callback)}">Approve Forgejo connection</a>'.encode()
            )

        def log_message(self, *_args):
            pass

    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    provider_url = f"http://localhost:{provider.server_port}"
    provider_thread = threading.Thread(target=provider.serve_forever, daemon=True)
    provider_thread.start()

    async def configure():
        engine = create_async_engine(DATABASE_URL)
        try:
            async with async_sessionmaker(engine)() as session:
                await session.execute(update(ForgejoInstance).values(base_url=provider_url))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(configure())
    values = cfg.model_dump()
    values.update(
        oauth_enabled=False,
        cookie_secure=False,
        forgejo_allowed_base_urls=[provider_url],
        forgejo_oauth_redirect_url=issuer + CALLBACK,
        allow_insecure_forgejo_http=True,
    )
    settings = type(cfg)(**values)

    async def exchange(self, *, base_url, verify_tls, values):
        assert base_url == provider_url and values["code"] == "browser-code"
        return ForgejoOAuthTokens(
            access_token="browser-access",
            refresh_token="browser-refresh",
            token_type="Bearer",
            expires_in=3600,
        )

    async def principal(self, *, base_url, token, verify_tls):
        assert base_url == provider_url and isinstance(token, ForgejoOAuthToken)
        return ForgejoUser(42, "OAuthUser")

    monkeypatch.setattr(ForgejoOAuthClient, "exchange", exchange)
    monkeypatch.setattr(ForgejoClient, "get_current_user", principal)
    server = uvicorn.Server(uvicorn.Config(create_app(settings), log_level="warning"))
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
                page.on("dialog", lambda dialog: dialog.accept())
                page.goto(issuer)
                page.get_by_role("heading", name="Sign in", exact=True).wait_for()
                page.get_by_label("Username", exact=True).fill("oauth-user")
                page.get_by_label("Password", exact=True).fill("user-password-for-testing")
                page.get_by_role("button", name="Sign in", exact=True).click()
                button = page.get_by_role("button", name="Reconnect with Forgejo OAuth", exact=True)
                expect(button).to_be_enabled()
                button.click()
                page.get_by_role("link", name="Approve Forgejo connection").wait_for()
                assert page.url.startswith(provider_url)
                with page.expect_request(lambda r: CALLBACK in r.url) as callback:
                    page.get_by_role("link", name="Approve Forgejo connection").click()
                cookie = callback.value.all_headers().get("cookie", "")
                assert "fmcp_session=" not in cookie
                assert "fmcp_forgejo_oauth_session=" in cookie
                page.get_by_text(
                    "Forgejo OAuth credential verified, encrypted and saved", exact=True
                ).wait_for()
                cookies = {c["name"]: c for c in page.context.cookies()}
                assert cookies["fmcp_session"]["sameSite"] == "Strict"
                assert "fmcp_forgejo_oauth_session" not in cookies
                public = page.evaluate("async () => (await fetch('/api/me/credential')).json()")
                assert public["kind"] == "oauth"
                assert "browser-access" not in str(public) and "browser-refresh" not in str(public)
            finally:
                browser.close()
        assert len(seen) == 1
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
        provider.shutdown()
        provider.server_close()
        provider_thread.join(timeout=5)
