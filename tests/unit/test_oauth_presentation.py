from importlib.resources import files

import pytest

from forgejo_mcp.api.oauth import (
    _OAUTH_CSS,
    _consent_guidance,
    _consent_page,
    _login_page,
    _oauth_html,
)


def test_oauth_styles_are_the_dashboard_single_source_of_truth():
    dashboard_css = files("forgejo_mcp").joinpath("static/dashboard.css").read_text()
    assert dashboard_css == _OAUTH_CSS
    assert ".shell" in _OAUTH_CSS
    assert ".authCard" in _OAUTH_CSS
    assert "color-scheme: light dark" not in _OAUTH_CSS


def test_login_uses_shared_card_and_escapes_inputs():
    html = _oauth_html(_login_page("<interaction>", "<script>alert(1)</script>", "<csrf>"))
    body = html.body.decode()
    assert "class='shell'" in body
    assert "class='card authCard'" in body
    assert "class='form'" in body
    assert "<script>" not in body
    assert "&lt;script&gt;" in body
    assert "&lt;interaction&gt;" in body
    assert "Forgejo PAT" in body
    assert "administrator account" in body


def test_consent_uses_shared_card_and_keeps_safety_details():
    body = _consent_page(
        interaction="test",
        csrf="test",
        client_name="<client>",
        client_id="<id>",
        redirect_uri="https://client.example/callback?x=<x>",
        username="<user>",
        grant_ttl_options_days=(1, 7, 30),
        default_grant_ttl_days=30,
        tool_names=("<tool>",),
    )
    assert "class='card authCard oauthConsent'" in body
    assert "class='form'" in body
    assert "OAuth cannot add permissions" in body
    assert "value='approve'" in body and "value='deny'" in body
    assert "&lt;client&gt;" in body and "&lt;user&gt;" in body
    assert "&lt;x&gt;" in body
    assert "name='tool_names' value='&lt;tool&gt;'" in body
    assert "checked" not in body
    assert "Nothing is selected by default" in body


@pytest.mark.parametrize(
    "reason, message",
    [
        ("credential_required", "verified Forgejo credential"),
        ("tools_required", "tool allowance"),
        ("account_required", "Administrator accounts cannot"),
        ("user_unavailable", "not active"),
        ("request_expired", "already used"),
        ("client_unavailable", "registration"),
    ],
)
def test_guidance_explains_next_step_and_logs_safe_reason(reason, message, caplog):
    response = _consent_guidance(reason)
    body = response.body.decode()
    assert response.status_code == 400
    assert message in body
    assert "/mcp-auth &lt;server-name&gt;" in body
    assert "Return to the Dashboard" in body
    assert response.headers["cache-control"] == "no-store"
    record = caplog.records[-1]
    assert record.message == "oauth_consent_rejected"
    assert record.reason == reason
