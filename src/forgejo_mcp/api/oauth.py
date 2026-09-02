from __future__ import annotations

import hmac
import secrets
import time
from html import escape
from typing import Any, cast
from urllib.parse import urlsplit

from fastapi import HTTPException
from mcp.server.auth.handlers.authorize import AuthorizationHandler
from mcp.server.auth.handlers.revoke import RevocationHandler
from mcp.server.auth.handlers.token import TokenHandler
from mcp.server.auth.json_response import PydanticJSONResponse
from mcp.server.auth.middleware.client_auth import ClientAuthenticator
from mcp.server.auth.provider import RegistrationError, TokenError
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata
from pydantic import ValidationError
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route, request_response
from starlette.types import ASGIApp

from forgejo_mcp.api.auth import set_auth_cookies
from forgejo_mcp.application.auth_service import AuthService
from forgejo_mcp.application.errors import AuthenticationFailed
from forgejo_mcp.application.oauth_service import OAUTH_SCOPE, OAuthService
from forgejo_mcp.auth.client_ip import get_client_ip
from forgejo_mcp.auth.rate_limit import LoginRateLimiter, MultiScopeRateLimiter
from forgejo_mcp.auth.session import CSRF_COOKIE, get_current_session
from forgejo_mcp.auth.tokens import hash_token, new_token
from forgejo_mcp.config import Settings, normalize_http_origin
from forgejo_mcp.db.models import AccountRole, RecordStatus

OAUTH_CSRF_COOKIE = "fmcp_oauth_csrf"
_oauth_login_limiter = LoginRateLimiter()


def create_oauth_routes(service: OAuthService, settings: Settings) -> list[Route]:
    client_authenticator = ClientAuthenticator(service)
    registration_limiter = MultiScopeRateLimiter(window_seconds=3600)
    token_handler = TokenHandler(service, client_authenticator)

    async def authorization_metadata(_request: Request) -> Response:
        issuer = service.issuer_url
        return JSONResponse(
            {
                "issuer": issuer,
                "authorization_endpoint": f"{issuer}/authorize",
                "token_endpoint": f"{issuer}/token",
                "registration_endpoint": f"{issuer}/register",
                "revocation_endpoint": f"{issuer}/revoke",
                "scopes_supported": [OAUTH_SCOPE],
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "token_endpoint_auth_methods_supported": ["none"],
                "revocation_endpoint_auth_methods_supported": ["none"],
                "code_challenge_methods_supported": ["S256"],
                "client_id_metadata_document_supported": bool(settings.oauth_cimd_allowed_origins),
                "authorization_response_iss_parameter_supported": True,
            },
            headers={"Cache-Control": "public, max-age=3600"},
        )

    async def protected_resource_metadata(_request: Request) -> Response:
        return JSONResponse(
            {
                "resource": service.resource_url,
                "authorization_servers": [service.issuer_url],
                "scopes_supported": [OAUTH_SCOPE],
                "bearer_methods_supported": ["header"],
                "resource_name": "Forgejo MCP",
            },
            headers={"Cache-Control": "public, max-age=3600"},
        )

    async def register(request: Request) -> Response:
        client_ip = get_client_ip(request, settings) or "unknown"
        decision = registration_limiter.check(
            [("oauth-registration", client_ip, settings.oauth_registration_rate_limit_requests)]
        )
        if not decision.allowed:
            return JSONResponse(
                {
                    "error": "invalid_client_metadata",
                    "error_description": "registration rate limit exceeded",
                },
                status_code=429,
                headers={"Retry-After": str(decision.retry_after_seconds)},
            )
        try:
            payload = await request.json()
            metadata = OAuthClientMetadata.model_validate(payload)
        except (ValidationError, ValueError):
            return _registration_error("client metadata is invalid")
        if metadata.token_endpoint_auth_method not in {None, "none"}:
            return _registration_error("only public PKCE clients are supported")
        if metadata.scope not in {None, OAUTH_SCOPE}:
            return _registration_error("only the mcp:tools scope is supported")
        metadata.token_endpoint_auth_method = "none"
        metadata.scope = OAUTH_SCOPE
        client_id = f"fmcp_client_{secrets.token_urlsafe(32)}"
        info = OAuthClientInformationFull(
            **metadata.model_dump(),
            client_id=client_id,
            client_id_issued_at=int(time.time()),
            client_secret=None,
            client_secret_expires_at=None,
        )
        try:
            await service.register_client(info)
        except RegistrationError as error:
            return _registration_error(error.error_description or "registration was rejected")
        return PydanticJSONResponse(content=info, status_code=201)

    async def token(request: Request) -> Response:
        # The SDK validates PKCE and grants but currently does not enforce the
        # RFC 8707 resource parameter at the token endpoint. Bind every issued
        # or refreshed access token to this exact MCP resource before exchange.
        form = await request.form()
        resource = form.get("resource")
        if resource is not None and (
            not isinstance(resource, str) or not hmac.compare_digest(resource, service.resource_url)
        ):
            return _token_error("resource must identify this MCP server")
        return cast(Response, await token_handler.handle(request))

    async def consent_page(request: Request) -> Response:
        interaction = request.query_params.get("request", "")
        details = await service.consent_details(interaction)
        if details is None:
            return _oauth_html(
                _message_page("Authorization request unavailable", "Start the connection again."),
                status_code=400,
            )
        current = None
        session_token = request.cookies.get("fmcp_session")
        if session_token:
            async with request.app.state.db_session_factory() as session:
                try:
                    current = await get_current_session(session, session_token)
                except HTTPException:
                    current = None
        oauth_csrf = new_token()
        if current is None:
            response = _oauth_html(_login_page(interaction, details.client_name, oauth_csrf))
        elif (
            current.account.role != AccountRole.USER
            or current.account.user_id is None
            or current.account.must_change_password
            or current.account.status != RecordStatus.ACTIVE
        ):
            response = _oauth_html(
                _message_page(
                    "User account required",
                    "Sign out of the Dashboard and sign in with the Forgejo MCP user account.",
                ),
                status_code=403,
            )
        else:
            csrf = request.cookies.get(CSRF_COOKIE)
            if csrf is None:
                response = _oauth_html(
                    _message_page(
                        "Session unavailable",
                        "Sign in again and restart authorization.",
                    ),
                    status_code=401,
                )
            else:
                response = _oauth_html(
                    _consent_page(
                        interaction=interaction,
                        csrf=csrf,
                        client_name=details.client_name,
                        client_id=details.client_id,
                        redirect_uri=details.redirect_uri,
                        username=current.account.username,
                        grant_ttl_options_days=details.grant_ttl_options_days,
                        default_grant_ttl_days=details.default_grant_ttl_days,
                    )
                )
        response.set_cookie(
            OAUTH_CSRF_COOKIE,
            oauth_csrf,
            httponly=True,
            secure=settings.use_secure_cookies,
            samesite="strict",
            path="/oauth",
            max_age=settings.oauth_interaction_ttl_seconds,
        )
        return response

    async def oauth_login(request: Request) -> Response:
        if not _same_origin(request, service.issuer_url):
            return _oauth_html(_message_page("Request rejected", "Origin validation failed."), 403)
        form = await request.form()
        interaction = _form_string(form, "request", 80)
        username = _form_string(form, "username", 64)
        password = _form_string(form, "password", 1024)
        csrf = _form_string(form, "csrf", 100)
        csrf_cookie = request.cookies.get(OAUTH_CSRF_COOKIE)
        if not csrf_cookie or not csrf or not hmac.compare_digest(csrf_cookie, csrf):
            return _oauth_html(_message_page("Request rejected", "CSRF validation failed."), 403)
        if not interaction or await service.consent_details(interaction) is None:
            return _oauth_html(
                _message_page("Authorization request unavailable", "Start the connection again."),
                400,
            )
        client_ip = get_client_ip(request, settings)
        rate_limit_key = f"{client_ip}:{username.casefold()}"
        lease = _oauth_login_limiter.check(rate_limit_key)
        async with request.app.state.db_session_factory() as session:
            auth = AuthService(session)
            try:
                result = await auth.login(
                    username=username,
                    password=password,
                    client_ip=client_ip,
                    user_agent=request.headers.get("user-agent"),
                    ttl_hours=settings.session_ttl_hours,
                )
            except AuthenticationFailed:
                _oauth_login_limiter.failure(lease)
                return _oauth_html(
                    _login_page(interaction, "MCP client", csrf, login_failed=True),
                    401,
                )
            _oauth_login_limiter.success(lease)
            if (
                result.account.role != AccountRole.USER
                or result.account.user_id is None
                or result.account.must_change_password
            ):
                await auth.logout(result.session)
                return _oauth_html(
                    _message_page(
                        "User account required",
                        "Use the Forgejo MCP user account, not the administrator account.",
                    ),
                    403,
                )
        response = RedirectResponse(
            f"/oauth/consent?request={interaction}",
            status_code=303,
        )
        set_auth_cookies(response, settings, result.session_token, result.csrf_token)
        response.delete_cookie(OAUTH_CSRF_COOKIE, path="/oauth")
        return response

    async def resolve_consent(request: Request) -> Response:
        if not _same_origin(request, service.issuer_url):
            return _oauth_html(_message_page("Request rejected", "Origin validation failed."), 403)
        form = await request.form()
        interaction = _form_string(form, "request", 80)
        action = _form_string(form, "action", 16)
        csrf = _form_string(form, "csrf", 100)
        grant_ttl_value = _form_string(form, "grant_ttl_days", 3)
        csrf_cookie = request.cookies.get(CSRF_COOKIE)
        session_token = request.cookies.get("fmcp_session")
        if not interaction or action not in {"approve", "deny"}:
            return _oauth_html(_message_page("Request rejected", "Consent is invalid."), 400)
        if action == "approve" and (
            not grant_ttl_value or not grant_ttl_value.isascii() or not grant_ttl_value.isdigit()
        ):
            return _oauth_html(
                _message_page("Request rejected", "Authorization lifetime is invalid."),
                400,
            )
        grant_ttl_days = int(grant_ttl_value) if action == "approve" else None
        if not csrf_cookie or not csrf or not hmac.compare_digest(csrf_cookie, csrf):
            return _oauth_html(_message_page("Request rejected", "CSRF validation failed."), 403)
        if session_token is None:
            return _oauth_html(_message_page("Authentication required", "Sign in again."), 401)
        async with request.app.state.db_session_factory() as session:
            try:
                current = await get_current_session(session, session_token)
            except HTTPException:
                return _oauth_html(_message_page("Authentication required", "Sign in again."), 401)
            if not hmac.compare_digest(hash_token(csrf), current.csrf_token_hash):
                return _oauth_html(
                    _message_page("Request rejected", "CSRF validation failed."),
                    403,
                )
            try:
                target = await service.resolve_consent(
                    interaction=interaction,
                    account_id=current.account_id,
                    approve=action == "approve",
                    grant_ttl_days=grant_ttl_days,
                )
            except (ValueError, RegistrationError, TokenError):
                return _oauth_html(
                    _message_page("Authorization failed", "Start the connection again."),
                    400,
                )
        response = RedirectResponse(target, status_code=302)
        response.delete_cookie(OAUTH_CSRF_COOKIE, path="/oauth")
        return response

    async def oauth_styles(_request: Request) -> Response:
        return Response(
            _OAUTH_CSS,
            media_type="text/css",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    resource_metadata_path = _resource_metadata_path(service.resource_url)
    return [
        Route(
            "/.well-known/oauth-authorization-server",
            endpoint=_cors(authorization_metadata, ["GET", "OPTIONS"]),
            methods=["GET", "OPTIONS"],
        ),
        Route(
            resource_metadata_path,
            endpoint=_cors(protected_resource_metadata, ["GET", "OPTIONS"]),
            methods=["GET", "OPTIONS"],
        ),
        Route("/authorize", endpoint=AuthorizationHandler(service).handle, methods=["GET", "POST"]),
        Route(
            "/token",
            endpoint=_cors(token, ["POST", "OPTIONS"]),
            methods=["POST", "OPTIONS"],
        ),
        Route(
            "/register",
            endpoint=_cors(register, ["POST", "OPTIONS"]),
            methods=["POST", "OPTIONS"],
        ),
        Route(
            "/revoke",
            endpoint=_cors(
                RevocationHandler(service, client_authenticator).handle,
                ["POST", "OPTIONS"],
            ),
            methods=["POST", "OPTIONS"],
        ),
        Route("/oauth/consent", endpoint=consent_page, methods=["GET"]),
        Route("/oauth/login", endpoint=oauth_login, methods=["POST"]),
        Route("/oauth/consent", endpoint=resolve_consent, methods=["POST"]),
        Route("/oauth/styles.css", endpoint=oauth_styles, methods=["GET"]),
    ]


def _cors(handler: Any, methods: list[str]) -> ASGIApp:
    return CORSMiddleware(
        request_response(handler),
        allow_origins=["*"],
        allow_methods=methods,
        allow_headers=["Authorization", "Content-Type", "MCP-Protocol-Version"],
        allow_credentials=False,
    )


def _registration_error(description: str) -> JSONResponse:
    return JSONResponse(
        {"error": "invalid_client_metadata", "error_description": description},
        status_code=400,
        headers={"Cache-Control": "no-store"},
    )


def _token_error(description: str) -> JSONResponse:
    return JSONResponse(
        {"error": "invalid_request", "error_description": description},
        status_code=400,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


def _resource_metadata_path(resource_url: str) -> str:
    path = urlsplit(resource_url).path
    suffix = "" if path in {"", "/"} else path
    return f"/.well-known/oauth-protected-resource{suffix}"


def _same_origin(request: Request, issuer_url: str) -> bool:
    origin = request.headers.get("origin")
    if origin is None:
        return False
    try:
        return normalize_http_origin(origin) == normalize_http_origin(issuer_url)
    except ValueError:
        return False


def _form_string(form: Any, name: str, maximum: int) -> str:
    value = form.get(name)
    return value if isinstance(value, str) and len(value) <= maximum else ""


def _oauth_html(content: str, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Forgejo MCP authorization</title>"
        "<link rel='stylesheet' href='/oauth/styles.css'></head>"
        f"<body><main>{content}</main></body></html>",
        status_code=status_code,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


def _login_page(
    interaction: str,
    client_name: str,
    csrf: str,
    *,
    login_failed: bool = False,
) -> str:
    error = "<p class='error'>Invalid username or password.</p>" if login_failed else ""
    return (
        "<section><p class='eyebrow'>Forgejo MCP</p><h1>Sign in to authorize</h1>"
        f"<p><strong>{escape(client_name)}</strong> is requesting access.</p>{error}"
        "<form method='post' action='/oauth/login'>"
        f"<input type='hidden' name='request' value='{escape(interaction)}'>"
        f"<input type='hidden' name='csrf' value='{escape(csrf)}'>"
        "<label>Dashboard username<input name='username' autocomplete='username' "
        "required maxlength='64'></label>"
        "<label>Password<input name='password' type='password' "
        "autocomplete='current-password' required maxlength='1024'></label>"
        "<button type='submit'>Sign in</button></form>"
        "<p class='hint'>Use the user account linked to your Forgejo identity, not an "
        "administrator account.</p></section>"
    )


def _consent_page(
    *,
    interaction: str,
    csrf: str,
    client_name: str,
    client_id: str,
    redirect_uri: str,
    username: str,
    grant_ttl_options_days: tuple[int, ...],
    default_grant_ttl_days: int,
) -> str:
    lifetime_options = "".join(
        "<option value='{days}'{selected}>{days} day{suffix}</option>".format(
            days=days,
            selected=" selected" if days == default_grant_ttl_days else "",
            suffix="" if days == 1 else "s",
        )
        for days in grant_ttl_options_days
    )
    return (
        "<section><p class='eyebrow'>Forgejo MCP</p><h1>Authorize MCP access?</h1>"
        f"<p><strong>{escape(client_name)}</strong> wants to connect as "
        f"<strong>{escape(username)}</strong>.</p>"
        "<dl>"
        f"<dt>Client</dt><dd>{escape(client_id)}</dd>"
        f"<dt>Callback</dt><dd>{escape(redirect_uri)}</dd>"
        "<dt>Permission boundary</dt><dd>Only tools already enabled and allowed for "
        "this account. OAuth cannot add permissions.</dd></dl>"
        "<form method='post' action='/oauth/consent'>"
        f"<input type='hidden' name='request' value='{escape(interaction)}'>"
        f"<input type='hidden' name='csrf' value='{escape(csrf)}'>"
        "<label>Authorization duration"
        f"<select name='grant_ttl_days' required>{lifetime_options}</select></label>"
        "<div class='actions'><button type='submit' name='action' "
        "value='approve'>Authorize</button>"
        "<button class='secondary' type='submit' name='action' value='deny'>Deny</button>"
        "</div></form><p class='hint'>Access tokens expire after one hour and are refreshed "
        "automatically until the selected authorization expiry. You can revoke access at any "
        "time.</p></section>"
    )


def _message_page(title: str, message: str) -> str:
    return (
        "<section><p class='eyebrow'>Forgejo MCP</p>"
        f"<h1>{escape(title)}</h1><p>{escape(message)}</p>"
        "<p><a href='/'>Return to the Dashboard</a></p></section>"
    )


_OAUTH_CSS = """
:root { color-scheme: light dark; font-family: system-ui, sans-serif; }
body { margin: 0; min-height: 100vh; display: grid; place-items: center;
  background: #111; color: #f5f5f5; }
main { width: min(92vw, 34rem); }
section { border: 1px solid #3b3b3b; border-radius: 1rem; padding: 2rem; background: #1b1b1b; }
h1 { margin: .25rem 0 1rem; font-size: 1.75rem; }
.eyebrow { color: #a8d5a2; font-weight: 700; text-transform: uppercase; letter-spacing: .08em; }
label { display: grid; gap: .4rem; margin: 1rem 0; }
input, select { border: 1px solid #555; border-radius: .5rem; padding: .75rem;
  background: #111; color: inherit; }
button { border: 0; border-radius: .5rem; padding: .75rem 1rem;
  background: #62a85a; color: #071006; font-weight: 700; cursor: pointer; }
button.secondary { background: #3b3b3b; color: #fff; }
.actions { display: flex; gap: .75rem; margin-top: 1.5rem; }
dl { display: grid; grid-template-columns: 7rem 1fr; gap: .6rem; overflow-wrap: anywhere; }
dt { color: #aaa; } dd { margin: 0; }
.hint { color: #aaa; font-size: .9rem; }
.error { color: #ff9898; }
a { color: #a8d5a2; }
""".strip()
