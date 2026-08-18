# Forgejo MCP

[繁體中文](README.zh-TW.md)

Forgejo MCP is a self-hosted [Model Context Protocol](https://modelcontextprotocol.io/) server and management Dashboard that gives organizations centrally governed, controlled and observable AI access to an existing Forgejo instance.

Users connect with their own scoped Forgejo personal access tokens (PATs). Administrators decide which MCP tools are enabled globally, available to each user and granted to each show-once MCP token.

> **v0.1.0 is the initial open-source release.** The core workflow is tested locally against Forgejo 16.0.2, while some production deployment capabilities are not yet complete. Review the [known limitations](docs/known-limitations.md) before production use.

## What it provides

- 47 tools for repositories, organization repository creation, git trees, branches, commits, labels, milestones, Issues, pull requests, reviews, Actions runs, jobs, logs and artifacts, tags and releases.
- Global, user and token-level tool authorization in addition to Forgejo's own permissions.
- Per-user Forgejo identity through a verified, scoped PAT.
- AES-256-GCM encryption for stored PATs and show-once MCP tokens.
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
MCP client ──Bearer token──> Forgejo MCP /mcp ──user PAT──> Forgejo API
                                  │
Web Dashboard ──admin/user──> permissions, credentials and audit records
                                  │
                              PostgreSQL
```

Forgejo MCP does not replace Forgejo authorization. A tool is available only when it is globally enabled, allowed for the user, granted to the MCP token, and permitted by the user's Forgejo account and PAT.

## Requirements

- An existing Forgejo instance compatible with the locked Forgejo 16.0.2 API contract
- Docker Engine with Docker Compose
- OpenSSL for generating local secrets

The supported v0.1.0 deployment builds the React Dashboard into the App image and starts the App and PostgreSQL together. Operators do not need separate frontend and backend processes.

## Quick start

From the repository root:

```bash
cp deploy/compose.example.env deploy/.env
# Edit deploy/.env and replace POSTGRES_PASSWORD before continuing.

mkdir -p deploy/secrets
openssl rand -base64 32 > deploy/secrets/admin_password
openssl rand -base64 32 > deploy/secrets/credential_key
chmod 600 deploy/secrets/admin_password deploy/secrets/credential_key

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

Forgejo MCP uses authenticated MCP Streamable HTTP:

```text
URL:           https://forgejo-mcp.example/mcp
Transport:     Streamable HTTP
Authorization: Bearer fmcp_...
```

The MCP token is shown only once. Store it in the client's secret storage; query-string tokens are rejected. See [MCP client configuration](docs/mcp-client-configuration.md) for the field mapping, connection checks and troubleshooting guidance.

## Documentation

| Need | Document |
| --- | --- |
| Install and start the service | [Getting started](docs/getting-started.md) |
| Configure Forgejo, users and permissions | [Administrator guide](docs/admin-guide.md) |
| Create a PAT and MCP token | [User guide](docs/user-guide.md) |
| Connect an MCP client | [MCP client configuration](docs/mcp-client-configuration.md) |
| Review current constraints | [Known limitations](docs/known-limitations.md) |
| Inspect tool inputs and behavior | [v1 tool catalog](docs/tools/v1-tool-catalog.md) |
| Review credential handling | [Credential security](docs/security/credentials.md) |

## Development and verification

Run the disposable full-stack App/PostgreSQL/Forgejo E2E test:

```bash
./scripts/test-full-docker-e2e.sh
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

Forgejo is pinned to `codeberg.org/forgejo/forgejo:16.0.2-rootless`. Verify another instance's Swagger contract with:

```bash
uv run python scripts/verify_forgejo_openapi.py https://forgejo.example/swagger.v1.json
```

## License

Copyright holders license this project under the [Apache License 2.0](LICENSE).
