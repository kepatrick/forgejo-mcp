# OAuth upgrade and lifecycle

This guide covers **MCP client → Forgejo MCP**, not the separate Forgejo account
linking flow. For Forgejo application registration, Admin configuration and
upstream permission limits, see [English](forgejo-oauth.md) or
[繁體中文](forgejo-oauth.zh-TW.md).

OAuth is opt-in (`FMCP_OAUTH_ENABLED=false` by default). Static MCP tokens continue
to work. No extra Forgejo PAT scopes or tool permissions are granted by OAuth:
global tool enablement, user allowances and the grant all remain enforced.

Back up PostgreSQL and preserve the credential encryption key and configuration.
Stop all application workers, run `alembic upgrade head`, then restart the matching
application. Migrations 0009–0012 add OAuth records, absolute grant expiry and token
families. 0012 also repairs historical Dashboard revocations on installations already
at 0011 without interpreting healthy access-token rotation as family revocation.
Migration 0013 records whether each authorization request explicitly supplied its
redirect URI. Legacy requests/codes default to `true` to retain their strict
exchange behavior; newly created requests preserve the actual presence flag.
Migration 0014 persists the user's explicit consent tool selection. Outstanding
pre-upgrade authorization codes have an empty selection and cannot be exchanged:
restart consent in the MCP client. Existing access/refresh tokens remain usable;
rotation preserves their existing stored token grants rather than granting all
currently available tools.

Configure an HTTPS issuer origin and resource equal to that origin plus `/mcp`.
Register only required browser origins; CIMD metadata destinations are separately
allowlisted. Native loopback callbacks and PKCE S256 are supported. Clients renew
short-lived access tokens using rotating refresh tokens until the consent grant's
absolute expiry (choices bounded by administrator policy, maximum 90 days).
After signing in, the user chooses that duration and selects at least one tool on
the consent page. No tools are preselected. **Select all** selects only the
currently offered tools; **Clear selection** clears them. These buttons do not
submit approval and do not modify existing tokens. Only globally enabled tools
inside the admin-defined user allowance appear. The authorization code stores that exact
selection; token exchange intersects it with current permissions. Each refresh
intersects the previous token's grants with current permissions, preserving token
permission tightening and never adding newly enabled/allowed tools or extending
the original expiry. A removed tool requires new consent to restore it. If no
selected tools remain available, exchange/refresh fails closed.

The bounded recovery cache is process-local: use a single application process.
Within grace a retry gets the same pair, not another branch; a cold-cache retry
fails closed. Outside grace (or with grace=0), reuse revokes the family. Dashboard
revocation, OAuth revocation and refresh all serialize on the family. A disabled
user cannot obtain a cached replacement or authenticate to MCP.

Revoking a Forgejo PAT/credential prevents Forgejo tools from running; it is not
equivalent to revoking an OAuth family. Use Dashboard/OAuth revocation for that.
If historical audit evidence and refresh history were manually deleted, a legacy
revocation can be indistinguishable from a healthy rotation; revoke affected grants
explicitly. Do not claim the backfill can reconstruct deleted history.

Migration 0012 downgrade deliberately does not resurrect tokens. Disabling OAuth
is preferable to schema rollback; 0009 downgrade deletes OAuth tokens/tables, so
requires a verified backup and planned client reauthorization. Never restore old
tokens merely to undo a revocation.

PostgreSQL CI covers full consent/PKCE/rotation, strict grace, disabled-user cache,
missing-family failure, both concurrency regressions, and legacy/healthy backfill
through real bearer/refresh services. Existing static-token lifecycle tests remain.

OAuth HTTP sessions are bound to a grant family, not an individual access token.
Refreshing preserves the session but each message uses the current HTTP request's
token ID for authorization and audit. Independently consented grants cannot share
sessions. Token-rate limits use the stable family identity so rotation cannot
reset their budget. Upgrading restarts the process, so existing in-memory MCP
sessions must be initialized again.

Consent pages allow only their persisted callback origin in CSP `form-action`.
OAuth forms use `Referrer-Policy: same-origin` so browser POSTs retain a verifiable
Origin without disclosing the interaction URL to external callbacks. Other pages
retain their default browser policy. Public clients may omit `client_secret` when
revoking access or refresh tokens.

CIMD servers must return uncompressed JSON. The fetcher requests `identity`, rejects
other content encodings before reading them, and counts raw bytes before extending
the bounded document buffer; it does not trust `Content-Length`.

To run the Chromium approval/denial regression tests locally, provision a migrated,
throwaway database (these integration tests reset its data), then run:

```sh
uv sync --frozen
npm ci --prefix frontend
npm run build --prefix frontend
uv run playwright install chromium
FMCP_TEST_BROWSER=1 FMCP_TEST_DATABASE_URL="$TEST_DATABASE_URL" \
  uv run pytest tests/integration/test_oauth_browser.py
```

`FMCP_TEST_CHROMIUM_EXECUTABLE` can select an existing Chromium binary. CI installs
Chromium and enables these tests alongside the PostgreSQL suite.

The OAuth branch is integrated with the current `main` security and compatibility
changes. Existing installations must also follow `docs/security/upgrade-hardening.md`
for database secret files and trusted Forgejo destinations. The supported Forgejo
version is 16.0.3; 16.0.2 remains a comparison baseline only. Shared Origin, proxy-IP,
throttling and log-redaction protections remain enabled alongside OAuth.
