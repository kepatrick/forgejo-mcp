# Connect a Forgejo credential with OAuth

This is **Forgejo MCP → Forgejo** authorization. It is independent of the optional
**MCP client → Forgejo MCP** OAuth server and works when `FMCP_OAUTH_ENABLED=false`.
PATs remain supported. This feature links an existing invited Dashboard user; it
is not anonymous login, account creation, or a bypass of administrator tool policy.

## Register and configure

1. Create an OAuth application in the trusted Forgejo account's **user settings →
   Applications** (`/user/settings/applications`). Prefer a confidential client.
   **Do not use `/admin/applications` instance-wide applications**: the Forgejo 16
   documentation warns that these can give application tokens administrative rights.
2. Register exactly `https://mcp.example.com/api/me/credential/oauth/callback` as the
   redirect URI. Use the externally visible Dashboard address, not a container URL.
   HTTPS is required in production. Direct localhost testing may use HTTP only in
   a non-production deployment.
3. Set `FMCP_FORGEJO_OAUTH_CLIENT_ID` and `FMCP_FORGEJO_OAUTH_REDIRECT_URL` to those
   registered values. The configured Dashboard Forgejo instance must still appear
   in `FMCP_FORGEJO_ALLOWED_BASE_URLS`. No destinations are accepted from the browser.
4. For a confidential client, put its client secret in a protected file, never in
   source control/chat. Set `FMCP_FORGEJO_OAUTH_CLIENT_SECRET_FILE` to its container
   path. Compose users can set it to the **host** secret-file path in their env file
   and add `-f deploy/compose.forgejo-oauth.yaml` alongside `deploy/compose.yaml`;
   the override mounts it read-only and sets the container path. A public client
   omits the secret file and always uses PKCE S256.
5. Preserve the credential encryption key, back up PostgreSQL, stop old application
   workers, apply `alembic upgrade head` (migration 0015), and start this branch's
   application. Existing PAT rows default to `kind=pat` and remain unchanged.

For local testing use, for example:

```dotenv
FMCP_FORGEJO_OAUTH_CLIENT_ID=<registered-client-id>
FMCP_FORGEJO_OAUTH_REDIRECT_URL=http://127.0.0.1:8000/api/me/credential/oauth/callback
```

Do not point an older application's code at the upgraded database as a rollback
strategy. Migration downgrade revokes OAuth credentials instead of relabeling
expired OAuth tokens as PATs; existing PATs are preserved.

## User flow

Sign in to the Dashboard as the invited **user**, open **My Forgejo credential**,
and choose **Connect with Forgejo OAuth**. Sign in and approve on Forgejo, then
return to the Dashboard. The returned token must match both the assigned Forgejo
username and the existing Forgejo numeric user ID before it replaces an old PAT or
OAuth credential. Denial, identity mismatch, and failed exchange leave the existing
credential intact. A lost/expired Dashboard session requires starting a new attempt.

Authorization attempts are one-use, expire in ten minutes, and are bound to the
exact Dashboard browser session, Forgejo instance, client ID and fixed callback.
State and a separate browser-binding secret are stored hashed. A ten-minute,
HttpOnly, callback-path-only `SameSite=Lax` cookie carries that binding secret,
not the Dashboard session token. The normal Dashboard cookies remain
`SameSite=Strict`; the callback checks the original server-side session is still
active. PKCE verifiers are encrypted and cleared when consumed. Starting a new
attempt replaces the previous pending attempt in that browser session.
Access and refresh tokens use encryption with user-bound authenticated associated
data and different encryption purposes. Tokens are never returned to the browser.
OAuth API requests use Bearer authentication; PAT authentication is unchanged.

An expiring token is refreshed lazily before a Forgejo tool request. A database row
lock serializes refresh across processes; refresh is not blindly retried because
Forgejo may have rotated the token even if the response was lost. A fresh token's
principal is checked before storing it. If refresh fails, reconnect or use a PAT.
Changing the configured Forgejo URL or OAuth client invalidates use of a stored
OAuth credential; it is never forwarded to the replacement destination.

Revoking, disabling the user, or changing its assigned Forgejo username clears
both local access and refresh secrets. **Local removal does not revoke upstream
Forgejo application authorization**. Also remove that authorization in Forgejo
settings, particularly when replacing an OAuth credential with a PAT.

## Permission warning

Forgejo 16's OAuth provider does **not** implement fine-grained API scopes; a
scoped PAT can provide a narrower upstream credential. MCP global tool settings,
admin-defined user allowances and per-MCP-token grants continue to be checked and
are not expanded by linking Forgejo OAuth. Never claim OAuth is equivalent to a
least-privilege PAT. Use a non-administrator Forgejo user where possible.

Callback responses disable caching/referrer disclosure, and the application
redacts callback query strings from Uvicorn access logs. Configure reverse proxies
and external log collectors to avoid logging callback queries as well.

Tests cover token response bounds, redirect rejection, secret-safe logging, PKCE,
session/state replay protection, identity mismatch, encrypted storage, revocation
and concurrent refresh. Chromium also checks a genuinely cross-site return while
Dashboard cookies remain Strict. The upstream token/principal endpoints are mocked in the
integration suite; real-instance testing requires a separately registered Forgejo
application and user consent.

References:
- https://forgejo.org/docs/v16.0/user/authentication/oauth2-provider/
- https://forgejo.org/docs/v16.0/user/api/usage/
