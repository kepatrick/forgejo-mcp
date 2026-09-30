from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from html import escape
from importlib.resources import files
from typing import Any, cast
from urllib.parse import urlsplit

from fastapi import HTTPException
from mcp.server.auth.handlers.authorize import AuthorizationHandler
from mcp.server.auth.handlers.revoke import RevocationRequest
from mcp.server.auth.handlers.token import TokenHandler
from mcp.server.auth.json_response import PydanticJSONResponse
from mcp.server.auth.middleware.client_auth import AuthenticationError, ClientAuthenticator
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
from forgejo_mcp.application.oauth_service import OAUTH_SCOPE, ConsentUnavailable, OAuthService
from forgejo_mcp.auth.client_ip import get_client_ip
from forgejo_mcp.auth.oauth_rate_limit import LoginRateLimiter, MultiScopeRateLimiter
from forgejo_mcp.auth.passwords import normalize_username
from forgejo_mcp.auth.session import CSRF_COOKIE, get_current_session
from forgejo_mcp.auth.tokens import hash_token, new_token
from forgejo_mcp.config import Settings, normalize_http_origin
from forgejo_mcp.db.models import AccountRole, RecordStatus
from forgejo_mcp.tools.registry import get_tool

OAUTH_CSRF_COOKIE = "fmcp_oauth_csrf"
_oauth_login_limiter = LoginRateLimiter()
logger = logging.getLogger(__name__)


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

    async def revoke(request: Request) -> Response:
        # SDK 1.28's RevocationRequest makes the nullable client_secret field
        # required. Supply its missing default for public clients, without
        # weakening client authentication or token ownership checks.
        try:
            client = await client_authenticator.authenticate_request(request)
        except AuthenticationError as error:
            return JSONResponse(
                {"error": "unauthorized_client", "error_description": error.message},
                status_code=401,
                headers={"Cache-Control": "no-store"},
            )
        try:
            payload: dict[str, Any] = dict(await request.form())
            payload.setdefault("client_secret", None)
            revocation = RevocationRequest.model_validate(payload)
        except ValidationError:
            return JSONResponse(
                {"error": "invalid_request", "error_description": "invalid revocation request"},
                status_code=400,
                headers={"Cache-Control": "no-store"},
            )
        # A hint changes lookup order only; it must not prevent revocation of
        # an otherwise valid token of the other type (RFC 7009).
        kinds = ["access_token", "refresh_token"]
        if revocation.token_type_hint == "refresh_token":
            kinds.reverse()
        for kind in kinds:
            stored = (
                await service.load_access_token(revocation.token)
                if kind == "access_token"
                else await service.load_refresh_token(client, revocation.token)
            )
            if stored is not None:
                if stored.client_id == client.client_id:
                    await service.revoke_token(stored)
                break
        return Response(
            status_code=200, headers={"Cache-Control": "no-store", "Pragma": "no-cache"}
        )

    async def consent_page(request: Request) -> Response:
        interaction = request.query_params.get("request", "")
        details = await service.consent_details(interaction)
        if details is None:
            return _consent_guidance("request_expired")
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
            response = _consent_guidance("account_required", status_code=403)
        else:
            readiness = await service.consent_readiness(current.account.user_id)
            csrf = request.cookies.get(CSRF_COOKIE)
            if readiness is not None:
                response = _consent_guidance(readiness, status_code=403)
            elif csrf is None:
                response = _oauth_html(
                    _message_page(
                        "Session unavailable",
                        "Sign in again and restart authorization.",
                    ),
                    status_code=401,
                )
            else:
                # Only the persisted, registration-validated callback may
                # widen this page's form-action for the post-consent redirect.
                callback = urlsplit(details.redirect_uri)
                request.state.oauth_consent_callback_origin = normalize_http_origin(
                    f"{callback.scheme}://{callback.netloc}"
                )
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
                        tool_names=await service.consent_tool_names(current.account.user_id),
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
            return _consent_guidance("request_expired")
        client_ip = get_client_ip(request, settings)
        rate_limit_key = f"{client_ip}:{normalize_username(username)}"
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
                return _consent_guidance("account_required", status_code=403)
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
        submitted_tools = form.getlist("tool_names") if action == "approve" else []
        if len(submitted_tools) > 100 or any(
            not isinstance(name, str) or not name or len(name) > 100 for name in submitted_tools
        ):
            return _consent_guidance("tools_selection_invalid", interaction=interaction)
        tool_names = cast(list[str], submitted_tools)
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
                    tool_names=tool_names,
                )
            except ConsentUnavailable as error:
                return _consent_guidance(error.reason, interaction=interaction)
            except (ValueError, RegistrationError, TokenError) as error:
                # Do not render SDK descriptions, request values or secrets.
                logger.warning(
                    "oauth_consent_rejected",
                    extra={"reason": "invalid_consent", "error_type": type(error).__name__},
                )
                return _oauth_html(
                    _message_page(
                        "Authorization could not be completed",
                        "Choose one of the offered authorization durations. If the request is "
                        "no longer available, start a new connection from your MCP client.",
                        retry_interaction=interaction,
                    ),
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
            endpoint=_cors(revoke, ["POST", "OPTIONS"]),
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
        f"<link rel='stylesheet' href='/oauth/styles.css?v={_OAUTH_CSS_VERSION}'></head>"
        f"<body><main class='shell'>{content}</main></body></html>",
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
    error = (
        "<p class='error' role='alert'>Invalid username or password. "
        "Use your Dashboard user account, not your Forgejo password.</p>"
        if login_failed
        else ""
    )
    return (
        "<section class='card authCard'><p class='eyebrow'>Forgejo MCP · Secure authorization</p>"
        "<h1>Sign in to authorize</h1>"
        f"<p class='description'><strong>{escape(client_name)}</strong> is requesting access.</p>"
        "<form class='form' method='post' action='/oauth/login'>"
        f"<input type='hidden' name='request' value='{escape(interaction)}'>"
        f"<input type='hidden' name='csrf' value='{escape(csrf)}'>"
        "<label>Dashboard username<input name='username' autocomplete='username' "
        "required maxlength='64'></label>"
        "<label>Password<input name='password' type='password' "
        "autocomplete='current-password' required maxlength='1024'></label>"
        f"{error}<button type='submit'>Sign in</button></form>"
        "<p class='description'>Use the Dashboard user account linked to your Forgejo identity, "
        "not an administrator account. First accept your invitation, connect with Forgejo OAuth "
        "or verify your Forgejo PAT in the Dashboard, and ask your administrator to enable "
        "your tools.</p>"
        "<p><a href='/'>Open Dashboard</a></p></section>"
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
    tool_names: tuple[str, ...],
) -> str:
    lifetime_options = "".join(
        "<option value='{days}'{selected}>{days} day{suffix}</option>".format(
            days=days,
            selected=" selected" if days == default_grant_ttl_days else "",
            suffix="" if days == 1 else "s",
        )
        for days in grant_ttl_options_days
    )
    tool_options = "".join(_tool_choice(name) for name in tool_names)
    return (
        "<section class='card authCard oauthConsent'>"
        "<p class='eyebrow'>Forgejo MCP · Secure authorization</p>"
        "<h1>Authorize MCP access?</h1>"
        f"<p class='description'><strong>{escape(client_name)}</strong> wants to connect as "
        f"<strong>{escape(username)}</strong>.</p>"
        "<dl class='oauthDetails credentialSummary'>"
        f"<dt>Client</dt><dd>{escape(client_id)}</dd>"
        f"<dt>Callback</dt><dd>{escape(redirect_uri)}</dd>"
        "<dt>Permission boundary</dt><dd>Only tools already enabled and allowed for "
        "this account. OAuth cannot add permissions.</dd></dl>"
        "<form class='form' method='post' action='/oauth/consent'>"
        f"<input type='hidden' name='request' value='{escape(interaction)}'>"
        f"<input type='hidden' name='csrf' value='{escape(csrf)}'>"
        "<label>Authorization duration"
        f"<select name='grant_ttl_days' required>{lifetime_options}</select></label>"
        "<fieldset class='oauthTools'><legend>Token tool permissions</legend>"
        "<p class='description'>Choose at least one tool for this connection. Nothing is "
        "selected by default. Only tools enabled and allowed by your administrator appear; "
        "your Forgejo account permissions and credential may further limit access.</p>"
        f"<div class='tokenToolGrid'>{tool_options}</div></fieldset>"
        "<div class='actions'><button type='submit' name='action' "
        "value='approve'>Authorize</button>"
        "<button class='secondary' type='submit' name='action' value='deny'>Deny</button>"
        "</div></form><p class='description'>Short-lived access tokens are refreshed "
        "automatically until the selected authorization expiry. You can revoke this connection "
        "in the Dashboard's MCP tokens section at any time. Refresh will not add unselected "
        "tools or extend the chosen authorization duration. Deny returns to your MCP client "
        "without granting access.</p></section>"
    )


def _tool_choice(name: str) -> str:
    spec = get_tool(name)
    title = spec.title if spec else name
    description = spec.description if spec else ""
    risk = spec.risk if spec else "unknown"
    return (
        "<label class='toolChoice'>"
        f"<input type='checkbox' name='tool_names' value='{escape(name, quote=True)}'>"
        f"<span><strong>{escape(title)}</strong><small>{escape(name)} · {escape(risk)}</small>"
        f"<small>{escape(description)}</small></span></label>"
    )


def _message_page(title: str, message: str, *, retry_interaction: str | None = None) -> str:
    retry = (
        f"<p><a href='{escape('/oauth/consent?request=' + retry_interaction, quote=True)}'>"
        "Return to authorization settings</a></p>"
        if retry_interaction
        else ""
    )
    return (
        "<section class='card authCard'><p class='eyebrow'>Forgejo MCP · Secure authorization</p>"
        f"<h1>{escape(title)}</h1><p class='description' role='alert'>{escape(message)}</p>{retry}"
        "<p><a href='/'>Return to the Dashboard</a></p>"
        "<p class='description'>After completing setup, return to your MCP client and start "
        "authorization again. In Pi, run <code>/mcp-auth forgejo-local-oauth</code> for the "
        "local test connection, or <code>/mcp-auth &lt;server-name&gt;</code> "
        "for another connection. "
        "Do not reuse an expired authorization link.</p></section>"
    )


def _consent_guidance(
    reason: str,
    status_code: int = 400,
    *,
    interaction: str | None = None,
) -> HTMLResponse:
    guidance = {
        "tools_selection_required": (
            "Select tools for this token",
            "Choose at least one tool on the authorization settings page, "
            "then submit again. No access has been granted.",
        ),
        "tools_selection_invalid": (
            "Tool selection is no longer available",
            "One or more selected tools are not allowed or enabled for your user. "
            "Return to authorization settings to reload the available tools and choose again. "
            "No access has been granted.",
        ),
        "credential_required": (
            "Set up your Forgejo credential",
            "Your Dashboard account does not have an active, verified Forgejo credential. "
            "Open the Dashboard as this user and connect with Forgejo OAuth, or submit and "
            "verify a PAT in the Forgejo credential section. Then restart MCP authorization. "
            "Never paste your PAT into Pi chat.",
        ),
        "tools_required": (
            "Tool access is required",
            "No enabled tools are currently allowed for your user. Ask your administrator "
            "to enable the required tools globally and grant your user a tool allowance, "
            "then restart authorization. OAuth cannot add permissions.",
        ),
        "account_required": (
            "Use a ready user account",
            "Administrator accounts cannot authorize MCP access. Sign out of the Dashboard "
            "and sign in with your invited user account. Complete invitation acceptance and "
            "any required password change first. Contact your administrator if it is disabled.",
        ),
        "user_unavailable": (
            "User account unavailable",
            "Your linked user account is not active. Ask your administrator to check its "
            "status before restarting authorization.",
        ),
        "request_expired": (
            "Authorization request unavailable",
            "This request is expired, already used, or invalid. Return to your MCP client "
            "and start a new authorization request. Refreshing this page does not renew it.",
        ),
        "client_unavailable": (
            "MCP client unavailable",
            "This client's registration is no longer available. Reconnect or register the "
            "MCP client again before starting authorization.",
        ),
    }
    title, message = guidance.get(
        reason,
        (
            "Authorization could not be completed",
            "Return to the Dashboard to check your user setup, "
            "then start a new authorization request.",
        ),
    )
    logger.warning(
        "oauth_consent_rejected", extra={"reason": reason if reason in guidance else "unknown"}
    )
    retry = (
        interaction if reason in {"tools_selection_required", "tools_selection_invalid"} else None
    )
    return _oauth_html(_message_page(title, message, retry_interaction=retry), status_code)


# One stylesheet is packaged for both the Vite Dashboard and backend OAuth pages.
_OAUTH_CSS = files("forgejo_mcp").joinpath("static/dashboard.css").read_text(encoding="utf-8")
_OAUTH_CSS_VERSION = hashlib.sha256(_OAUTH_CSS.encode()).hexdigest()[:12]
