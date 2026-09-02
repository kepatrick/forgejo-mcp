# OAuth 2.1 security and operations

## Status and compatibility

OAuth is optional and disabled by default. Static `Authorization: Bearer fmcp_...` authentication remains compatible and unchanged. Both modes negotiate MCP Streamable HTTP `2025-06-18` and ultimately use the same token grants and call-time authorization engine.

The implementation supports authorization code with PKCE S256, exact redirect URI registration, RFC 8707 resource binding, RFC 9728 protected-resource discovery, authorization-server metadata, public-client Dynamic Client Registration (DCR), allowlisted Client ID Metadata Documents (CIMD), explicit local login/consent, short-lived access tokens and rotating refresh tokens with an absolute consent-selected authorization expiry.

## Permission boundary

OAuth never requests a Forgejo permission and never changes a user's PAT. At issuance, the access token receives exactly:

```text
globally enabled tools ∩ user tool allowance
```

The ordinary MCP checks still require an active user, active Forgejo credential, active token, global enablement, user allowance and token grant on every tool call. Forgejo then enforces the user's account permissions and existing PAT scopes.

## Security controls

- Public clients only; client secrets and confidential authentication methods are rejected.
- PKCE method is fixed to S256 and verifier challenges are bounded.
- Registered redirect URIs must use HTTPS, except HTTP loopback callbacks, and are compared exactly by the MCP SDK.
- An explicit RFC 8707 resource on authorization and code/refresh exchanges must match the exact configured `/mcp` resource. Clients that omit it are bound to that same resource because this server exposes exactly one OAuth resource.
- Authorization codes and browser interaction handles are high-entropy, hashed at rest, short-lived and single-use.
- Access tokens are opaque, hashed at rest and short-lived. Refresh tokens are opaque, hashed at rest and rotate on use without extending the consent-selected absolute expiry.
- An immediately duplicated refresh receives an independent rotated token pair inside a bounded concurrency grace. Reuse after that grace remains an anti-replay signal and revokes the entire family.
- Login and consent require an exact issuer `Origin`, SameSite cookies and CSRF validation. Administrator accounts cannot authorize user MCP access.
- OAuth bodies and remote metadata responses are bounded. CIMD accepts only explicitly allowlisted HTTPS origins, rejects credentials/query/fragment, validates public DNS results and never follows redirects.
- CIMD capability metadata is advertised only when at least one exact CIMD origin is configured; DCR-only deployments do not advertise an unavailable client-identification mode.
- Browser MCP requests require an exact configured origin. The CORS response policy permits only that allowlist, the MCP methods and headers, and exposes only `WWW-Authenticate` and `MCP-Session-Id`; credentials mode and wildcard origins remain disabled.
- Token values, codes, refresh tokens, passwords, cookies and PATs are excluded from audit details and request logs. Sensitive responses use `no-store`.
- OAuth tokens carry an explicit database kind. Missing/inconsistent OAuth linkage fails closed. Downgrade deletes every OAuth-created MCP token before removing OAuth tables.

## Security review findings fixed before publication

### OAUTH-001 — High — OAuth tokens could survive a schema rollback as static tokens

**Impact.** Dropping only the OAuth linkage tables could leave an OAuth-created row in `mcp_tokens`; the historical verifier could then interpret it as an ordinary static token with its existing grants.

**Fix.** OAuth issuance marks the record as `kind="oauth"` in `src/forgejo_mcp/application/oauth_service.py:521`. Authentication fails closed on missing or inconsistent linkage in `src/forgejo_mcp/auth/mcp_bearer.py:66-83`. The downgrade deletes OAuth token records before dropping linkage and removes the discriminator only afterward in `migrations/versions/20260902_0009_oauth21.py:180-187`.

### OAUTH-002 — Medium — Token exchange did not enforce the submitted resource

**Impact.** The upstream SDK validated the resource during authorization but ignored the `resource` form field during code and refresh exchange. In this single-resource server, issued tokens remained internally bound to the correct resource, but the endpoint did not meet the intended confused-deputy boundary.

**Fix.** `src/forgejo_mcp/api/oauth.py` rejects every explicit RFC 8707 resource other than the configured MCP URL before delegating to the SDK token handler. Omitted values are safely resolved to the server's single configured resource for client compatibility; attacker-controlled values and omission are covered by PostgreSQL integration tests.

### OAUTH-003 — Low — Confidential client metadata was silently converted to public

**Impact.** A client requesting secret-based authentication could receive a public registration instead, creating a security expectation mismatch even though PKCE remained required.

**Fix.** `src/forgejo_mcp/api/oauth.py:97-101` rejects confidential methods and non-MCP scopes. Stored DCR/CIMD metadata is restricted to exactly authorization-code plus refresh grants and the code response type.

### OAUTH-004 — Low — Frozen SDK errors could mask hostile CIMD responses

**Impact.** Rejecting a redirect, non-JSON document or oversized document from inside the HTTP stream context raised an internal frozen-dataclass error instead of the intended registration error, creating a narrow availability and diagnostics defect.

**Fix.** `src/forgejo_mcp/application/oauth_service.py:720-773` records the rejection while streaming and raises the SDK error only after the HTTP context exits. Redirect, media-type and size cases have regression tests.

### OAUTH-005 — Medium — Concurrent refreshes could revoke a healthy authorization

**Impact.** Two simultaneous MCP calls could submit the same valid refresh token. The first request rotated it; the second was then classified as a replay and revoked the newly issued token plus the complete family. A normal client could therefore lose its connection after an access-token refresh even though the authorization was configured for 30 days.

**Fix.** A duplicated refresh inside the deployment-bounded grace receives an independent rotated token pair in the same family, allowing clients with concurrent connection managers to converge without sharing a replacement token. The old token remains unusable after the grace, and later reuse retains family-wide revocation. PostgreSQL integration coverage launches two refreshes against the same row and proves that both receive distinct tokens, the absolute expiry is unchanged and replay after the grace revokes both branches. The recovery emits a credential-free `oauth.concurrent_refresh_recovered` audit event.

No unresolved Critical, High or Medium OAuth finding is known after these patches.

## Residual risks

- CIMD destination validation occurs before the HTTP client's own DNS connection. Exact origin allowlisting substantially limits exposure, but network egress policy remains the final defense against DNS rebinding. Keep the allowlist empty unless CIMD is required.
- The concurrency grace trades immediate family revocation for availability only during its short configured window. A stolen old refresh token could obtain one independently rotated branch during that window; keep the grace as short as the approved clients permit, retain endpoint rate limits and review `oauth.concurrent_refresh_recovered` audit events.
- Login/registration rate limits are in-memory because the supported deployment is a single application replica. Multi-replica operation requires a shared limiter before it is supported.
- Client implementations and redirect URIs evolve independently. Re-run a live authorization test after a client or proxy upgrade.

## Production configuration

```dotenv
FMCP_OAUTH_ENABLED=true
FMCP_OAUTH_ISSUER_URL=https://forge-mcp.example.com
FMCP_OAUTH_RESOURCE_URL=https://forge-mcp.example.com/mcp
FMCP_OAUTH_CIMD_ALLOWED_ORIGINS=[]
FMCP_OAUTH_ACCESS_TOKEN_TTL_SECONDS=3600
FMCP_OAUTH_REFRESH_TOKEN_TTL_DAYS=30
FMCP_OAUTH_REFRESH_TOKEN_MAX_TTL_DAYS=90
FMCP_OAUTH_REFRESH_TOKEN_REUSE_GRACE_SECONDS=10
FMCP_OAUTH_REQUEST_MAX_BYTES=65536
```

The issuer must be the public HTTPS origin without a path. The resource must be that exact origin followed by `/mcp`. `FMCP_OAUTH_REFRESH_TOKEN_TTL_DAYS` is the default consent choice; the maximum bounds all choices offered by the server. Access tokens remain short-lived and can never outlive the selected authorization. Do not place credentials, codes or access tokens in configuration URLs.

## Validation evidence

- Ruff, format and strict MyPy: pass.
- Unit tests: 139 pass.
- PostgreSQL suite: 147 pass, with one opt-in external Forgejo test skipped.
- Alembic upgrade through `20260902_0010`, downgrade to `20260902_0009`, and re-upgrade: pass.
- Docker E2E Forgejo 16.0.2: selectable OAuth lifetime, bounded concurrent refresh recovery and all 50 tools pass (comparison baseline only).
- Docker E2E Forgejo 16.0.3: selectable OAuth lifetime, bounded concurrent refresh recovery and all 50 tools pass (minimum supported release).
- MCP protocol negotiated in integration and Docker E2E: `2025-06-18`.
- Forgejo PAT scopes remain `read:user`, `write:organization`, `write:repository` and `write:issue`; OAuth adds none.
