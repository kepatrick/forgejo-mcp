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
- An immediately duplicated refresh receives the exact first replacement pair from a bounded, ephemeral in-memory recovery entry. A missing entry rejects the duplicate without creating a branch or revoking the successful rotation. Reuse after the grace remains an anti-replay signal and revokes the entire family.
- Refresh rotation and revocation serialize on a persisted family row. Revoking an active OAuth access record from either Dashboard revokes its complete refresh-token family, including a replacement created by a concurrent refresh.
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

**Fix.** A duplicated refresh inside the deployment-bounded grace receives the exact access/refresh pair produced by the first rotation. The plaintext pair exists only in a bounded in-process recovery cache for the configured grace and is never persisted or logged. A cache miss, including another replica or a process restart, rejects the duplicate without creating a token branch or revoking the successful rotation. Reuse after the grace retains family-wide revocation. PostgreSQL integration coverage launches two refreshes against the same row and proves that both responses are identical, the absolute expiry is unchanged, a cold-cache duplicate fails closed and replay after the grace revokes the family. Credential-free recovery/rejection audit events include the family, user and refresh-record identifiers.

### OAUTH-006 — Medium — Dashboard revocation did not revoke the refresh family

**Impact.** Revoking the currently displayed OAuth access record disabled that short-lived token, but its refresh token remained valid and could immediately issue a new access token. This contradicted the consent-page revocation promise.

**Fix.** User and Admin Dashboard token revocation now resolves the OAuth family and atomically revokes every refresh and access record in that family. PostgreSQL integration coverage proves that both the displayed access token and its refresh path are rejected afterward.

### OAUTH-007 — High — Concurrent refresh and revocation could leave a replacement valid

**Impact.** Revocation could begin while refresh rotation held the current refresh row. PostgreSQL then waited for that row but retained a statement snapshot that did not include the newly committed replacement, allowing its access and refresh tokens to survive a completed family revocation.

**Fix.** Every OAuth family now has a persisted lock/state row. Rotation locks and verifies that row before the current refresh record; every revocation takes the same lock before enumerating descendants. Whichever transaction wins is authoritative: revocation either sees and disables the committed replacement, or rotation resumes after revocation and fails closed. Migration `20260908_0011` backfills existing families and revokes every descendant of any family with prior revocation evidence. A deterministic PostgreSQL regression test waits for real lock contention and proves that the replacement cannot authenticate after revocation.

No unresolved Critical, High or Medium OAuth finding is known after these patches.

## Residual risks

- CIMD destination validation occurs before the HTTP client's own DNS connection. Exact origin allowlisting substantially limits exposure, but network egress policy remains the final defense against DNS rebinding. Keep the allowlist empty unless CIMD is required.
- The concurrency grace lets a duplicate holder obtain the same replacement pair during its short configured window. It cannot create an independent branch. Keep the grace as short as approved clients permit, set it to `0` for strict replay handling, retain endpoint rate limits and review `oauth.concurrent_refresh_recovered` and `oauth.concurrent_refresh_rejected` events. Family rotation/revocation is serialized in PostgreSQL across processes, but duplicate-response recovery remains process-local; multi-replica deployments are not supported.
- Reverse proxies and bot controls can distinguish machine clients even when OAuth browser authorization looks identical. Diagnose discovery, DCR, consent and token exchange separately; see [OAuth client and reverse-proxy troubleshooting](../oauth-client-edge-troubleshooting.md).
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
- Test suite without PostgreSQL: 142 pass and 10 database/external tests are skipped.
- PostgreSQL suite: 151 pass, with one opt-in external Forgejo test skipped.
- Alembic upgrade through `20260908_0011`, downgrade to `20260902_0010`, and re-upgrade: pass.
- Docker E2E Forgejo 16.0.2: selectable OAuth lifetime, idempotent concurrent refresh recovery, Dashboard family revocation and all 50 tools pass (comparison baseline only).
- Docker E2E Forgejo 16.0.3: selectable OAuth lifetime, idempotent concurrent refresh recovery, Dashboard family revocation and all 50 tools pass (minimum supported release).
- MCP protocol negotiated in integration and Docker E2E: `2025-06-18`.
- Forgejo PAT scopes remain `read:user`, `write:organization`, `write:repository` and `write:issue`; OAuth adds none.
