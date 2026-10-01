# Connect a Forgejo credential with OAuth

[繁體中文配置與權限指南](forgejo-oauth.zh-TW.md)

This is **Forgejo MCP → Forgejo** authorization. It is independent of the optional
**MCP client → Forgejo MCP** OAuth server and works when `FMCP_OAUTH_ENABLED=false`.
PATs remain supported. This feature links an existing invited Dashboard user; it
is not anonymous login, account creation, or a bypass of administrator tool policy.

## Two independent OAuth connections

| Connection | Purpose | Application / callback |
|---|---|---|
| MCP client → Forgejo MCP | Authorize an AI client to call selected MCP tools | The MCP server's OAuth endpoints, normally dynamic `/register`; callback belongs to the MCP client |
| Forgejo MCP → Forgejo | Link each invited user's Forgejo API credential | One application registered in Forgejo; fixed Dashboard callback `/api/me/credential/oauth/callback` |

The Forgejo Client ID/Secret are shared **application configuration**, not a shared
Forgejo user credential. Register the application once per deployment, not once
per user. Each invited user approves it separately and receives their own encrypted
upstream credential. The application owner does not choose the user identity:
the Forgejo account signed in during consent must match the invited user's assigned
identity. Dashboard admins configure the application; invited Dashboard users link
credentials and authorize MCP clients.

## Register and configure

Before using the new UI, preserve encryption keys, back up PostgreSQL, stop old
workers and upgrade through migration 0016 with `alembic upgrade head`. Restart
the matching application. Existing PAT/OAuth credentials remain unchanged; old
pending Forgejo authorization attempts must be started again. The supported
Forgejo baseline is **16.0.3**; behavior observed on older versions is not a support
guarantee.

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
5. Save and verify that **Enable Forgejo OAuth linking** remains checked. Merely
   entering a Client ID/base URL does not enable linking. Refresh the invited
   user's Dashboard before starting a new authorization attempt.

Match the Forgejo application and Dashboard modes exactly:

| Forgejo application | Dashboard client type | Client Secret |
|---|---|---|
| Confidential Client checked | Confidential | Required; paste the generated secret into the Admin UI |
| Confidential Client unchecked | Public | None; PKCE S256 is still required and always used |

The local callback example is
`http://127.0.0.1:8000/api/me/credential/oauth/callback`, with base URL
`http://127.0.0.1:8000`. It works only when the browser can reach that same local
machine. `localhost` and `127.0.0.1`, different ports and trailing callback slashes
are not interchangeable registered values. For other users, use a reachable HTTPS
Dashboard origin. The base URL field controls **this Forgejo callback only**: it
does not configure the separate MCP OAuth issuer/resource or widen Forgejo egress
allowlists.

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

### Effective permissions and their limits

A tool operation must pass all of these checks:

1. Admin globally enables the tool.
2. Admin allows that tool for the invited user.
3. The current MCP token grants that tool.
4. The user's Forgejo credential/account can perform the operation on the requested resource.

On MCP OAuth consent, nothing is selected by default. **Select all** selects only
the tools currently shown within the admin-defined boundary; **Clear selection**
clears them. Neither button submits consent. The user must choose a duration and
press **Authorize**. New tools or increased allowances do not expand an existing
MCP grant automatically; refresh can only retain or narrow grants, not extend the
original consent expiry. Restart MCP consent to request a broader selection.

MCP policy is **tool-level**, not a separate repository/path allowlist. For an
allowed repository tool, the caller can name any repository the linked Forgejo
account can access. To restrict repositories, change Forgejo repository/team
membership or use a dedicated account. To narrow upstream API operations, use a
scoped PAT. An OAuth credential does not make write/admin permissions disappear
upstream simply because only read tools were selected in MCP: MCP enforces that
selection at its own boundary, not inside a stolen Forgejo token. Treat backend
and encryption-key compromise as compromise of the stored upstream credentials.

For example, `forgejo_get_repository` can return Forgejo metadata containing
`permissions.admin=true` and `push=true` while the MCP token grants only that
read tool. Those metadata flags do **not** authorize other MCP write/admin tools.
Conversely, selecting a write tool cannot override missing Forgejo write rights.

### Disable and revoke the correct connection

| Action | Effect | Does not do |
|---|---|---|
| Disable Forgejo OAuth linking in Admin settings | Blocks linking/use of OAuth credentials | Revoke upstream Forgejo application approval, delete PATs or revoke MCP token families |
| Revoke saved Forgejo credential / disable user / change assigned username | Clears local access/refresh secrets as applicable | Revoke upstream Forgejo approval |
| Revoke an MCP token/grant in Dashboard | Stops the corresponding client authorization | Revoke the linked Forgejo application approval |
| Remove an MCP client's local configuration or stop this server | Disconnects that local setup | Revoke server-side grants, erase database volumes or revoke Forgejo approval |

For full removal, separately revoke MCP grants and remove the application's
approval in the authorizing user's Forgejo settings. There is no automatic
upstream revocation promise. Forgejo token expiry and MCP consent expiry are
separate lifecycles; automatic Forgejo refresh does not extend MCP consent.

## Troubleshooting

| Symptom | Check |
|---|---|
| “Forgejo OAuth linking is not enabled” | Admin enable checkbox, saved configuration, configured Forgejo instance and deployment allowlist. Refresh the user's page; configuration saved with `enabled=false` overrides environment defaults. |
| Callback says denied/expired/unverified | This is a generic message, not proof of account mismatch. Use secret-safe server event names/status codes to identify the failed stage. |
| `forgejo_oauth_exchange_rejected`, HTTP 400 | First check Public vs Confidential on both sides, Client ID/Secret, and exact registered redirect URI. A reused/expired code or changed pending configuration also requires starting again. The current log records status, not the provider error body; 400 alone does not identify one exact cause. |
| Account verification fails | Sign in to Forgejo as the assigned invited-user account; both username and existing numeric identity must match. |
| OAuth linked but MCP consent cannot proceed | Admin must globally enable tools and grant user allowances; select at least one offered tool. Linking itself grants no tools. |
| MCP exposes only a few tools | Check global settings, user allowances, this token's consent selection and client tool exposure/cache. A Forgejo admin permission flag does not bypass them. |
| Repository “not found” | Check owner/name and the Forgejo account's repository visibility. A private-resource 404 does not by itself prove OAuth authentication failed. |
| Refresh fails | Reconnect or use a PAT; do not repeatedly replay a potentially rotated refresh token. |

Never publish codes, states, tokens, passwords or client secrets when reporting
errors. The real upstream token/principal endpoints are mocked in automated
integration tests. A manual successful read verifies that particular identity and
resource; it does not certify all write tools or an unsupported Forgejo release.

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
