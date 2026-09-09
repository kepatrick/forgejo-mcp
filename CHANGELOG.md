# Changelog

[繁體中文](CHANGELOG.zh-TW.md)

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project follows Semantic Versioning.

## [Unreleased]

### Compatibility

- Raise the minimum and only supported deployment target to Forgejo `16.0.3+gitea-1.22.0`; Forgejo 16.0.2 remains a comparative CI baseline and is not supported by this release.
- Lock the official 16.0.3 Swagger checksum. The only schema difference from 16.0.2 affects unused `IssueMeta` required fields, with no registered endpoint impact.
- Add a versioned compatibility matrix in `docs/compatibility.md` and a detailed Forgejo 16.0.3 report in `docs/forgejo-16.0.3-compatibility.md`.

### Added

- Add pull-request and release CI coverage for the OpenAPI comparison and complete Docker E2E against Forgejo 16.0.3 and the retained 16.0.2 baseline.
- Add E2E coverage for repository search and repository webhook create/list operations.
- Add a Dashboard password-change control that keeps the current session and revokes the account's other active sessions.
- Support version discovery for Forgejo instances that require sign-in for API version requests, using a bounded same-origin fallback without sending a PAT.

### Changed

- Change the default development Forgejo image from `16.0.2-rootless` to `16.0.3-rootless`.
- Replace broad E2E Forgejo PATs with the explicit scope set `read:user`, `write:organization`, `write:repository` and `write:issue`.
- Make MCP `2025-06-18` negotiation explicit in integration and Docker E2E coverage.

### Security

- Pin Forgejo destinations, validate remote/path inputs, bound decompression, redact credentials, serialize invitation acceptance and harden browser/proxy boundaries.
- Move Compose database credentials into protected files and require explicit trusted Forgejo destinations; see `docs/security/upgrade-hardening.md`.
- Preserve the existing token lifecycle and add targeted regression tests. No OAuth routes or migrations are included.
- Update `nanoid` to 3.3.18, `cryptography` to 50.0.1 and the development test stack to patched pytest 9 releases; current npm and Python dependency audits report no known vulnerabilities.

### Deployment and upgrade notes

- Existing installations must follow `docs/security/upgrade-hardening.md`; do not regenerate their PostgreSQL password or credential encryption key.
- This release requires new database credential files and trusted Forgejo URL configuration, but adds no database migration.
- Back up PostgreSQL, Compose configuration and credential encryption secrets before upgrading. Rollback requires the matching image and configuration; do not delete or recreate database data.

## [0.1.0] - 2026-09-08

### Compatibility

- Initial MCP Server release targeting the checksum-locked Forgejo 16.0.2 API contract. The release workflow runs the existing Forgejo 16.0.2 Docker E2E before publishing.
- Forgejo 16.0.3 compatibility and OAuth changes proposed in PR #3 are not included in this release.
- Container platform: `linux/amd64`. Python package, frontend, and MCP release version: `0.1.0`.

### Deployment and upgrade notes

- Versioned container image: `ghcr.io/kepatrick/forgejo-mcp:0.1.0`, available only after the release workflow completes and package access is configured. No `latest` image tag is published.
- Use the deployment files from tag `v0.1.0`. `deploy/compose.image.yaml` selects the published image while retaining the existing database, secrets, and startup migration configuration.
- Configure `POSTGRES_PASSWORD`, bootstrap admin and credential encryption secret files, and cookie/TLS settings before starting. This release does not introduce PR #3's OAuth or required Forgejo URL allowlist settings.
- Compose runs `alembic upgrade head` before starting the app; this release's schema head is `20250802_0008`. Back up existing PostgreSQL data and credential encryption secrets before upgrading an existing source deployment.
- Rolling back the image alone does not roll back the database. Verify schema compatibility or restore a coordinated backup. Never use `docker compose down -v` as a routine upgrade or rollback step.
- Review the known limitations before production use, including the single-process deployment constraint.

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
- Git tree, repository label/milestone, pull-request commit/review, and merged-status read tools, forming part of the 50-tool v1 catalog.
- Opt-in actual-Forgejo development-flow E2E coverage from repository setup and Issue work through review, merge, workflow dispatch, tag, and release.
- Full Docker Compose E2E automation covering Dashboard provisioning, PostgreSQL persistence, actual Forgejo PATs, MCP authorization, and the complete workflow through `POST /mcp`.
- Forgejo 16.0.2 image pin plus a checksum-locked OpenAPI operation contract for the registered tools.
- Actions run, job, log and artifact tools, plus repository migration and pull-mirror management, bringing the registry to 50 tools.
- Guarded release script with patch/minor/major or explicit-version preparation, read-only previews, and synchronized bilingual changelogs and package versions.
- Reusable CI, manual GitHub Actions release triggers, versioned GHCR image publishing, and GitHub Releases with bilingual notes and image digests.
- English and Traditional Chinese release documentation and a published-image Compose override.
- A privilege-dropping container entrypoint that safely stages read-only `0600` secret files for the unprivileged application process.
- Bounded MCP request and multi-file commit sizes, split Forgejo timeouts, safe-read retries, and per-token/per-user MCP rate limits.
- Graceful invocation draining with durable audit completion, PostgreSQL pool disposal, and local Docker restart coverage.
- Structured JSON request/invocation correlation plus Prometheus HTTP, MCP, Forgejo, rate-limit, and database-pool metrics.
- Dependency-aware readiness that reports PostgreSQL and MCP acceptance state.
