# OAuth upgrade and lifecycle

OAuth is opt-in (`FMCP_OAUTH_ENABLED=false` by default). Static MCP tokens continue
to work. No extra Forgejo PAT scopes or tool permissions are granted by OAuth:
global tool enablement, user allowances and the grant all remain enforced.

Back up PostgreSQL and preserve the credential encryption key and configuration.
Stop all application workers, run `alembic upgrade head`, then restart the matching
application. Migrations 0009–0012 add OAuth records, absolute grant expiry and token
families. 0012 also repairs historical Dashboard revocations on installations already
at 0011 without interpreting healthy access-token rotation as family revocation.

Configure an HTTPS issuer origin and resource equal to that origin plus `/mcp`.
Register only required browser origins; CIMD metadata destinations are separately
allowlisted. Native loopback callbacks and PKCE S256 are supported. Clients renew
short-lived access tokens using rotating refresh tokens until the consent grant's
absolute expiry (choices bounded by administrator policy, maximum 90 days).

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

This standalone PR includes the Origin, proxy-IP, throttling and log-redaction
helpers required to expose OAuth safely. Those shared boundaries overlap the
security-hardening PR; it does not include Forgejo URL/path hardening, deployment
secret-file changes, password UI, compatibility changes or performance batching.
