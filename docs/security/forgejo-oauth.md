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
3. Sign in as **admin** and open **Forgejo OAuth settings**. Enable linking and
   enter the registered **Client ID**, matching **client type**, and **MCP public
   base URL** (for example `https://mcp.example.com`). This is the Dashboard URL,
   not the Forgejo instance URL. Only scheme and host/port are editable: paths,
   credentials, queries and fragments are rejected. The fixed callback path is
   `/api/me/credential/oauth/callback`; the adjacent read-only redirect URL can be
   copied into Forgejo. HTTP is permitted only for loopback, non-production testing.
4. For a confidential client, paste its **Client Secret** into the password field.
   It is stored encrypted, never returned by the API or populated back into the
   field. Blank keeps an existing secret; changing the Client ID requires a new
   secret. Public clients always use PKCE S256 and remove any stored client secret.
   Save to apply immediately, without editing deployment files or restarting.
   The configured Forgejo instance must still appear in the deployment's
   `FMCP_FORGEJO_ALLOWED_BASE_URLS`; this UI cannot widen that trusted egress list.
5. Preserve the credential encryption key, back up PostgreSQL, stop old application
   workers, apply `alembic upgrade head` (through migration 0016), and start this
   branch's application. Existing PAT and OAuth credentials remain unchanged.
   Pending attempts from before the upgrade must be started again.

### Optional deployment defaults

Existing deployment variables remain supported **only when no Dashboard OAuth
configuration has been saved**. Database configuration takes precedence, including
an explicit disabled setting. A saved public client never inherits a deployment
client secret. Confidential deployment defaults may be imported, encrypted, on the
first enabled Dashboard save when the Client ID remains the same. No secret-file
path is exposed by the settings API.

For deployment-only local testing use, for example:

```dotenv
FMCP_FORGEJO_OAUTH_CLIENT_ID=<registered-client-id>
FMCP_FORGEJO_OAUTH_REDIRECT_URL=http://127.0.0.1:8000/api/me/credential/oauth/callback
```

For confidential deployment defaults, put the secret in a protected file and
set `FMCP_FORGEJO_OAUTH_CLIENT_SECRET_FILE` to its container path. Compose users
can specify the host file path and add `-f deploy/compose.forgejo-oauth.yaml`, which
mounts it read-only and sets the container path. This is unnecessary when the
secret is configured through the Admin UI. Never put secrets in source control/chat.

The settings API (`GET`/`PUT /api/forgejo/instance/oauth`) is admin-only;
writes require Dashboard CSRF verification and are audited without secret values.
The stored client secret uses AES-GCM with configuration-ID-bound authenticated
associated data and the separate `oauth-client-secret` encryption purpose.

Do not point an older application's code at the upgraded database as a rollback
strategy. Migration downgrade revokes OAuth credentials instead of relabeling
expired OAuth tokens as PATs; existing PATs are preserved. Downgrading 0016 also
drops Dashboard client configuration and pending attempts. Unset deployment OAuth
defaults before rollback if linking must remain disabled.

## User flow

Sign in to the Dashboard as the invited **user**, open **My Forgejo credential**,
and choose **Connect with Forgejo OAuth**. Sign in and approve on Forgejo, then
return to the Dashboard. The returned token must match both the assigned Forgejo
username and the existing Forgejo numeric user ID before it replaces an old PAT or
OAuth credential. Denial, identity mismatch, and failed exchange leave the existing
credential intact. A lost/expired Dashboard session requires starting a new attempt.

Authorization attempts are one-use, expire in ten minutes, and are bound to the
exact Dashboard browser session, Forgejo instance, client ID, fixed callback and
configuration revision. Every Dashboard configuration save invalidates pending
attempts; users must restart them. Callback credential storage rechecks the
configuration after the network exchange before replacing any existing credential.
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
principal is checked before storing it. Shared configuration/instance read locks
allow concurrent users while preventing settings writes during protected token use.
Settings saves may briefly wait for in-flight operations. If refresh fails,
reconnect or use a PAT.
Changing the configured Forgejo URL or OAuth Client ID invalidates use of a stored
OAuth credential; it is never forwarded to the replacement destination. Rotating
only the client secret keeps stored grants and uses the new secret for subsequent
refreshes. Disabling linking also blocks use of OAuth credentials without deleting
PATs or locally stored grants; it does not revoke upstream Forgejo authorization.

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
and external log collectors to avoid logging callback queries as well. Never log
Admin settings request bodies; they may contain a new client secret.

Tests cover token response bounds, redirect rejection, secret-safe logging, PKCE,
session/state replay protection, identity mismatch, encrypted storage, revocation
and concurrent refresh, admin/CSRF enforcement, encrypted client-secret retention
and rotation, fixed callback derivation, configuration precedence and pending-flow
invalidation. Chromium tests the Admin settings form (including no secret echo)
and also checks a genuinely cross-site return while
Dashboard cookies remain Strict. The upstream token/principal endpoints are mocked in the
integration suite; real-instance testing requires a separately registered Forgejo
application and user consent.

References:
- https://forgejo.org/docs/v16.0/user/authentication/oauth2-provider/
- https://forgejo.org/docs/v16.0/user/api/usage/
