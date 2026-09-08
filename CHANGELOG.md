# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project follows Semantic Versioning.

## [Unreleased]

### Fixed

- Decode compressed Forgejo response bodies exactly once while preserving decompressed-size limits for `gzip` and `deflate` responses.
- Serialize OAuth refresh rotation and family revocation in PostgreSQL so a concurrently issued replacement cannot survive completed family revocation.
- Make bounded concurrent OAuth refresh recovery idempotent so multi-session MCP clients such as Codex receive the same replacement pair instead of creating durable token-family forks.
- Revoke the complete OAuth refresh-token family when its active access token is revoked from the User or Admin Dashboard.
- Redact schemeless URL credentials at path boundaries and end-of-string while preserving ordinary time-like audit text.

### Added

- Optional OAuth 2.1 authorization-code server with PKCE S256, exact redirect registration, RFC 8707 resource binding, RFC 9728 metadata, public-client DCR, allowlisted CIMD, local login and explicit consent.
- Short-lived OAuth access tokens using the existing MCP permission engine, rotating refresh tokens with family-wide reuse detection/revocation, and one-time authorization codes.
- PostgreSQL OAuth integration and full Docker E2E coverage for discovery, DCR, login, consent, MCP `2025-06-18`, permission intersection, refresh rotation and revocation on Forgejo 16.0.2 and 16.0.3.
- Consent-time OAuth authorization lifetimes (1, 7, 30 or 90 days, deployment-capped) with an absolute expiry preserved across refresh rotation.
- Initial Python, React, PostgreSQL, Alembic, and Docker Compose engineering skeleton.
- Bootstrap Admin authentication with Argon2id passwords, server-side sessions, CSRF protection, login rate limiting, session management, and management audit events.
- React login and mandatory bootstrap-password change flow.
- Admin-managed external Forgejo instance connection, version validation, and optional local Forgejo 16 Compose profile.
- Per-user Forgejo PAT verification, AES-256-GCM encrypted persistence, rotation, cryptographic revocation, Admin status/revoke controls, and User self-service Dashboard.
- Admin User lifecycle, fixed admin/self authorization boundaries, short-lived one-time invitations, User activation, and immediate session revocation when a User is disabled.
- Admin User management and User invitation acceptance dashboard screens.
- PostgreSQL localhost development port mapping on `127.0.0.1:5433`.
- Application services and use-case-oriented repositories separating HTTP transport, business transactions, audit writes, and SQLAlchemy queries.
- User self-service show-once MCP tokens with optional expiry, hashed persistence, listing and revocation, plus Admin metadata listing and forced revocation.
- Static tool registry, global tool toggles, per-user ceilings, per-token grants, and deny-by-default layered authorization policy.
- Authenticated MCP Streamable HTTP endpoint with constant-time opaque token verification, session credential binding, filtered discovery, call-time authorization, and `forgejo_get_current_user`.
- Bounded repository listing/detail and branch listing tools with normalized outputs, strict schemas, pagination, response-size limits, and Forgejo error handling.
- Audited organization repository creation with bounded metadata, visibility and initialization options, Forgejo-side permission enforcement, and a dedicated security review.
- Commit listing/detail and ref comparison tools with normalized metadata, bounded file summaries, path/ref validation, and schema-validated MCP output.
- Immutable MCP invocation audit pipeline for allowed, denied, failed, and successful calls, with pre-persistence recursive redaction, bounded arguments, normalized targets, and content-free result summaries.
- Role-scoped invocation audit query/detail APIs and Dashboard filtering, with Users restricted to their own records and Admins able to review all records.
- Bounded issue and comment read/write tools with normalized users, labels, milestones, pagination, timestamp validation, and invocation event IDs for writes.
- Pull request read/write tools, bounded diff retrieval with SHA-256 summaries, and branch-based create/update contracts.
- Size-guarded repository file content retrieval with UTF-8 or base64 normalized output and content-free audit summaries.
- Forgejo API-backed repository contents, branch creation, and atomic multi-file commit tools.
- Pull-request changed-file, reviewer request/removal, review submission/listing, and merge tools.
- Combined commit status, workflow dispatch, tag creation, and release creation tools.
- Git tree, repository label/milestone, pull-request commit/review, and merged-status read tools, bringing the v1 catalog to 38 tools.
- Opt-in actual-Forgejo development-flow E2E coverage from repository setup and Issue work through review, merge, workflow dispatch, tag, and release.
- Full Docker Compose E2E automation covering Dashboard provisioning, PostgreSQL persistence, actual Forgejo PATs, MCP authorization, and the complete workflow through `POST /mcp`.
- Forgejo 16.0.2 image pin plus a checksum-locked OpenAPI operation contract covering all 38 registered tools.
- A privilege-dropping container entrypoint that safely stages read-only `0600` secret files for the unprivileged application process.
- Bounded MCP request and multi-file commit sizes, split Forgejo timeouts, safe-read retries, and per-token/per-user MCP rate limits.
- Graceful invocation draining with durable audit completion, PostgreSQL pool disposal, and local Docker restart coverage.
- Structured JSON request/invocation correlation plus Prometheus HTTP, MCP, Forgejo, rate-limit, and database-pool metrics.
- Dependency-aware readiness that reports PostgreSQL and MCP acceptance state.
- Pull-request CI matrix running the complete Docker E2E suite against Forgejo 16.0.2 and 16.0.3.
- E2E coverage for repository search and repository webhook create/list operations.
- Forgejo 16.0.3 compatibility report with complete Swagger, permission and security impact evidence.

### Changed

- Batch MCP tool-discovery authorization against one permission snapshot, eliminating repeated registry writes and per-tool SQL reloads without changing deny-by-default decisions.
- Treat an empty optional repository-content path as the repository root, avoiding repeated validation failures from MCP clients that serialize omitted strings as empty values.
- Defined Forgejo 16.0.3 as the minimum supported release; the locked 16.0.2 contract and E2E run remain comparison evidence only and do not extend the published support range.
- Add a permanent authenticated Dashboard control for changing the current account password, with confirmation and automatic revocation of other sessions.
- Support private Forgejo instances with signed-in-only API access by deriving the
  advertised version from the same-origin login page when, and only when, the
  unauthenticated version endpoint returns Forgejo's exact signed-in-only denial.
- Updated the development Forgejo image default from `16.0.2-rootless` to `16.0.3-rootless` while retaining a full 16.0.2 compatibility run.
- Locked both official Swagger checksums and added a reproducible structural comparison; the only 16.0.3 API schema change marks `IssueMeta.index`, `IssueMeta.owner` and `IssueMeta.repo` as required, with no endpoint impact.
- Replaced broad E2E Forgejo PATs with the explicit existing scope set (`read:user`, `write:organization`, `write:repository`, `write:issue`).
- Made MCP `2025-06-18` negotiation explicit in integration and Docker E2E coverage.
- Preserved single-resource OAuth client compatibility when RFC 8707 `resource` is omitted while continuing to reject every explicit resource other than the configured `/mcp` URL.
- Keep one-hour access tokens while allowing users to select the longer authorization lifetime that clients may refresh until.

### Security

- Persist OAuth family revocation state and fail closed on missing or revoked family linkage; the migration also disables descendants of any historically revoked family.
- Keep OAuth disabled by default; require exact issuer/resource configuration, public PKCE clients, bounded request/metadata bodies, no CIMD redirects, public DNS destinations, Same-Origin forms and CSRF tokens.
- Mark OAuth-created MCP tokens explicitly and delete them during migration downgrade so loss of OAuth linkage cannot turn them into valid static Bearer tokens.
- Bind all OAuth grants to the configured MCP resource, reject every conflicting explicit RFC 8707 resource, and reject confidential-client metadata instead of silently downgrading it to a public client.
- Re-serve the first rotated pair for duplicate refreshes inside the bounded concurrency grace; a missing recovery entry fails closed without creating a branch, while reuse outside the grace still revokes the family.
- Apply exact-allowlist MCP CORS for browser clients, including the required MCP request headers and exposed authentication/session response headers, without enabling credentialed wildcard access.
- Advertise CIMD client identification only when the deployment has configured an exact HTTPS CIMD origin.
- Declare read-only `contents` permissions explicitly in every GitHub Actions workflow.
- Move the PostgreSQL password and application database URL from Docker environment variables to read-only secret files.
- Pin production Forgejo base URLs out of band so Dashboard administration cannot redirect user PAT verification.
- Reject unsafe repository migration URLs and private/special migration hosts by default.
- Enforce an explicit browser `Origin` allowlist on the MCP endpoint and add no-store/CSP/browser hardening headers.
- Bound Forgejo response bodies while streaming, serialize invitation acceptance with a row lock, and redact credential patterns from all log formats.
- Upgrade `nanoid` and `cryptography` to patched releases identified by dependency auditing.
- Upgrade the development-only `pytest` and `pytest-asyncio` toolchain to releases that fix the UNIX temporary-directory advisory CVE-2025-71176.
- Reject exact `.` and `..` owner, organization, repository and ref segments in both MCP schemas and the Forgejo client so HTTP URL normalization cannot escape the authorized endpoint shape.
- Make an empty Forgejo base-URL allowlist deny every outbound Forgejo connection in every environment, while production continues to reject empty policy at startup.
- Require the deployment-level `FMCP_ALLOW_UNVERIFIED_FORGEJO_TLS` opt-in before the Dashboard can disable Forgejo certificate verification.
- Remove credentials embedded in remote URLs from invocation arguments and replace multi-file commit contents with byte counts and SHA-256 digests before audit persistence.
- Trust forwarded client IPs only from exact `FMCP_TRUSTED_PROXY_CIDRS`, resolve chains from right to left, disable Uvicorn's implicit proxy-header parsing in Compose, and bound/purge in-memory rate-limit key tables.
- Revalidate the unverified-TLS deployment policy before every PAT verification and tool connection so a stored legacy `verify_tls=false` value cannot bypass a later policy change.
- Redact and bound extracted invocation targets as well as full arguments, including camelCase secret keys and credential-bearing authorities without an explicit URL scheme.
- Reserve login and invitation rate-limit attempts atomically, and combine duplicate `X-Forwarded-For` lines before resolving the first untrusted hop.
- Disable implicit Uvicorn proxy-header parsing in the standalone image and reject redundant file-path dot segments in both MCP schemas and the Forgejo client.
- Redact slash-prefixed and `@`-containing credential authorities without a URL scheme while preserving ordinary `x:y@z` audit text, and align MCP dot-segment schemas with the client's Unicode whitespace normalization.
- Bind the reference App and test Forgejo host ports to loopback by default, with an explicit App bind-address override for reviewed deployments.
