# Forgejo MCP

[繁體中文](README.zh-TW.md)

Forgejo MCP is a self-hosted [Model Context Protocol](https://modelcontextprotocol.io/) server and management Dashboard that gives organizations centrally governed, controlled and observable AI access to an existing Forgejo instance.

Users connect with their own scoped Forgejo personal access tokens (PATs). Administrators decide which MCP tools are enabled globally, available to each user and granted to each show-once MCP token.

> **v0.1.0 is the initial open-source release.** The minimum supported Forgejo release is 16.0.3. Forgejo 16.0.2 remains a test-only comparison baseline and is not part of the published support range. Some production deployment capabilities are not yet complete; review the [known limitations](docs/known-limitations.md) before production use.

## What it provides

- 50 tools for repositories, organization repository creation, migration and pull-mirror management, git trees, branches, commits, labels, milestones, Issues, pull requests, reviews, Actions runs, jobs, logs and artifacts, tags and releases.
- Global, user and token-level tool authorization in addition to Forgejo's own permissions.
- Per-user Forgejo identity through a verified, scoped PAT.
- Optional OAuth 2.1 authorization-code login with PKCE S256, selectable 1/7/30/90-day consent, short-lived access tokens, rotating refresh tokens, DCR and allowlisted CIMD.
- AES-256-GCM encryption for stored PATs, with high-entropy MCP tokens shown once and stored only as hashes.
- A web Dashboard for Forgejo configuration, users, permissions and audit records.
- Redacted invocation auditing, structured logs, health endpoints and Prometheus metrics.

## Governance for company use

Forgejo MCP is designed as a governance layer between company AI clients and Forgejo—not merely as another API wrapper.

- **Manageable permissions:** administrators centrally control which tools are enabled globally, available to each user and granted to each MCP token.
- **Controlled operations:** AI clients never receive an unrestricted shared Forgejo token. Every operation remains bounded by the user's PAT scopes, Forgejo repository permissions and server-side input limits.
- **Traceable identity:** each MCP token belongs to a specific user and client, so activity is not hidden behind a shared service account.
- **Auditable behavior:** tool, user, target, authorization decision, status, duration and correlation identifiers are recorded with sensitive values redacted.
- **Observable service:** structured logs, health checks, Prometheus metrics and request/user/invocation correlation support operational inspection.
- **Revocable access:** administrators can revoke one client token, remove selected tool grants, deactivate a Forgejo credential or suspend a user.
- **Credential isolation:** MCP tokens and Forgejo PATs are separate credentials. An MCP token neither contains nor reveals the PAT; if only an MCP token is exposed, it can be revoked without rotating the Forgejo PAT.

## How it works

```text
MCP client ──OAuth 2.1 or static Bearer──> Forgejo MCP /mcp ──user PAT──> Forgejo API
                                                │
Web Dashboard ──admin/user login + consent──> permissions, credentials and audit records
                                                │
                                            PostgreSQL
```

Forgejo MCP does not replace Forgejo authorization. A tool is available only when it is globally enabled, allowed for the user, granted to the MCP token, and permitted by the user's Forgejo account and PAT.

## Requirements

- An existing Forgejo 16.0.3 instance compatible with the locked API contract. Later Forgejo releases require compatibility verification before use.
- Docker Engine with Docker Compose
- OpenSSL for generating local secrets

The supported v0.1.0 deployment builds the React Dashboard into the App image and starts the App and PostgreSQL together. Operators do not need separate frontend and backend processes.

## Quick start

From the repository root:

```bash
cp deploy/compose.example.env deploy/.env

mkdir -p deploy/secrets
openssl rand -base64 32 > deploy/secrets/admin_password
openssl rand -base64 32 > deploy/secrets/credential_key
postgres_password="$(openssl rand -hex 32)"
printf '%s\n' "$postgres_password" > deploy/secrets/postgres_password
printf 'postgresql+asyncpg://forgejo_mcp:%s@postgres:5432/forgejo_mcp\n' \
  "$postgres_password" > deploy/secrets/database_url
unset postgres_password
chmod 600 deploy/secrets/admin_password deploy/secrets/credential_key \
  deploy/secrets/postgres_password deploy/secrets/database_url

docker compose --env-file deploy/.env -f deploy/compose.yaml up --build -d
```

Verify that the service is ready:

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml ps
curl http://127.0.0.1:8000/health/ready
```

Open <http://127.0.0.1:8000> and sign in with:

- Username: `admin` (or `FMCP_BOOTSTRAP_ADMIN_USERNAME`)
- Password: the value in `deploy/secrets/admin_password`

Change the bootstrap password immediately. Direct localhost HTTP requires `FMCP_COOKIE_SECURE=false`; secure cookies should remain enabled behind HTTPS.

Production startup also requires `FMCP_FORGEJO_ALLOWED_BASE_URLS`, a JSON list containing the exact trusted Forgejo base URL (for example `["https://git.example.com"]`). An empty list permits no Forgejo connection in any environment. This out-of-band pin prevents a Dashboard administrator from redirecting user PAT verification to another server. Keep `FMCP_ALLOW_UNVERIFIED_FORGEJO_TLS=false`; disabling certificate verification requires a separate deployment opt-in. Browser-based MCP clients must add their exact origins to `FMCP_MCP_ALLOWED_ORIGINS`; regular MCP clients do not send an `Origin` header.

The reference Compose publishes the App on `127.0.0.1` by default. Terminate public TLS at a trusted reverse proxy. If proxy-derived client IPs are needed for rate limiting, set `FMCP_TRUSTED_PROXY_CIDRS` to only the exact proxy network; forwarded headers are otherwise ignored.

OAuth is disabled by default. Enabling it is a separate deployment decision and does not request or add any Forgejo PAT scope. Set the public HTTPS issuer origin and its exact `/mcp` resource URL; keep the CIMD allowlist empty unless a client actually identifies itself with an HTTPS metadata URL.

For logs, shutdown, clean reset, common startup errors and the optional local Forgejo profile, see [Getting started](docs/getting-started.md).

## First-time setup

After signing in:

1. Change the bootstrap administrator password.
2. Configure and verify the Forgejo base URL.
3. Enable the required tools globally.
4. Create a user with their expected Forgejo username and send a one-time invitation.
5. Set the user's tool allowance.
6. Have the user verify a scoped Forgejo PAT and create an MCP token.
7. Grant the required tools to that token.
8. Connect an MCP client to `POST /mcp`.

See the [administrator guide](docs/admin-guide.md) and [user guide](docs/user-guide.md) for the complete workflow.

## MCP connection

Forgejo MCP uses authenticated MCP Streamable HTTP. Clients supporting OAuth 2.1 can connect to the `/mcp` URL and discover the authorization server automatically. Static Bearer tokens remain fully supported:

```text
URL:           https://forgejo-mcp.example/mcp
Transport:     Streamable HTTP
Authorization: Bearer fmcp_...
```

OAuth clients use local Forgejo MCP login and explicit time-bounded consent; they never receive the Forgejo PAT. The static MCP token is shown only once and belongs in the client's secret storage; query-string access tokens are rejected. See [MCP client configuration](docs/mcp-client-configuration.md) for both connection modes.

## Documentation

| Need | Document |
| --- | --- |
| Install and start the service | [Getting started](docs/getting-started.md) |
| Configure Forgejo, users and permissions | [Administrator guide](docs/admin-guide.md) |
| Create a PAT and MCP token | [User guide](docs/user-guide.md) |
| Connect an MCP client | [MCP client configuration](docs/mcp-client-configuration.md) |
| Enable and review OAuth 2.1 | [OAuth 2.1 security and operations](docs/security/oauth-2.1.md) |
| Review current constraints | [Known limitations](docs/known-limitations.md) |
| Inspect tool inputs and behavior | [v1 tool catalog](docs/tools/v1-tool-catalog.md) |
| Review credential handling | [Credential security](docs/security/credentials.md) |
| Review Forgejo 16.0.3 evidence | [Forgejo 16.0.3 compatibility report](docs/forgejo-16.0.3-compatibility.md) |
| Read the independent security audit and remediation | [External audit, 2026-09-02 (French)](docs/security/audit-externe-2026-09-02.fr.md) |
| Prepare an independent review | [Third-party review handoff](docs/security/third-party-review.md) |

## Development and verification

Run the disposable full-stack App/PostgreSQL/Forgejo E2E test:

```bash
./scripts/test-full-docker-e2e.sh
```

The default development image and minimum supported release are Forgejo 16.0.3. The 16.0.2 command below is retained only to reproduce the historical non-regression comparison; it does not extend the supported range:

```bash
FORGEJO_IMAGE=data.forgejo.org/forgejo/forgejo:16.0.2-rootless ./scripts/test-full-docker-e2e.sh
```

Run the individual quality checks:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
npm run lint --prefix frontend
npm run typecheck --prefix frontend
npm run build --prefix frontend
```

Forgejo defaults to the official mirror `data.forgejo.org/forgejo/forgejo:16.0.3-rootless`. The supported 16.0.3 Swagger checksum and the 16.0.2 comparison checksum are locked. Verify an instance contract with:

```bash
uv run python scripts/verify_forgejo_openapi.py https://forgejo.example/swagger.v1.json
```

Launch the 16.0.2 reference and the minimum supported 16.0.3 release to reproduce the complete Swagger comparison with:

```bash
./scripts/test-forgejo-openapi-compatibility.sh
```

The integration and full-stack suites negotiate MCP Streamable HTTP protocol version `2025-06-18` explicitly.

## License

Copyright holders license this project under the [Apache License 2.0](LICENSE).
