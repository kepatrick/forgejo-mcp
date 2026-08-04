# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project follows Semantic Versioning.

## [Unreleased]

### Added

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
