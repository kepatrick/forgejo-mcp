# Getting started with Forgejo MCP

[繁體中文版](getting-started.zh-TW.md)

This guide starts the v0.1.0 Docker Compose deployment from a source checkout. It runs the Forgejo MCP App, built-in Dashboard and PostgreSQL. An existing Forgejo instance is required for normal use.

> v0.1.0 is an early self-hosted open-source release and is not yet fully production-ready. Read the [known limitations](known-limitations.md) before production use or exposure outside a protected environment.

## 1. Prerequisites

Install:

- Docker Engine;
- Docker Compose v2 (`docker compose`);
- OpenSSL;
- a shell capable of running the commands below.

You also need an existing Forgejo 16.0.3 instance compatible with the locked API contract. Forgejo 16.0.3 is the minimum supported release; later releases require compatibility verification before use. The App container must be able to reach its HTTPS API URL.

Run every command in this guide from the repository root.

## 2. Create the deployment configuration

Copy the example environment file:

```bash
cp deploy/compose.example.env deploy/.env
```

For direct access through `http://127.0.0.1:8000`, keep:

```dotenv
FMCP_COOKIE_SECURE=false
```

Set it to `true` when the App is served behind HTTPS. Keep both `FMCP_ALLOW_INSECURE_FORGEJO_HTTP=false` and `FMCP_ALLOW_UNVERIFIED_FORGEJO_TLS=false` for a normal deployment. The reference Compose binds the host port to `FMCP_BIND_ADDRESS=127.0.0.1`; change that address only when the network design requires it and TLS/network controls are already in place.

Do not commit `deploy/.env`.

## 3. Generate the required secrets

```bash
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
```

- `admin_password` is the initial Dashboard administrator password.
- `credential_key` encrypts stored Forgejo PATs.
- `postgres_password` is read by PostgreSQL through `POSTGRES_PASSWORD_FILE`.
- `database_url` is staged for the unprivileged App without exposing it through Docker environment inspection.

Do not commit, share or casually replace these files. Replacing the credential key makes existing encrypted PATs unusable. The container stages the read-only secret mounts and then runs the application as the unprivileged `app` user.

## 4. Start the service

Start in the background:

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml up --build -d
```

The first build may take several minutes. Compose starts PostgreSQL, runs the Alembic migrations and then starts the App with the Dashboard included.

To run in the foreground instead, omit `-d`.

## 5. Confirm that startup succeeded

Check container state:

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml ps
```

Check readiness:

```bash
curl http://127.0.0.1:8000/health/ready
```

The App should be reachable at <http://127.0.0.1:8000>. If readiness fails, inspect the logs:

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml logs -f app
```

Press `Ctrl+C` to stop following logs; background containers continue running.

## 6. Sign in for the first time

The default bootstrap username is `admin`, unless `FMCP_BOOTSTRAP_ADMIN_USERNAME` was changed in `deploy/.env`.

Read the generated password from `deploy/secrets/admin_password`, sign in to the Dashboard and change the password immediately.

If the login succeeds but the browser returns to the login page on direct localhost HTTP, confirm that `FMCP_COOKIE_SECURE=false`, then restart the App.

## 7. Connect the existing Forgejo instance

In the Dashboard:

1. enter the Forgejo base URL;
2. verify the connection;
3. enable the required tools globally;
4. create and invite users.

Use an HTTPS base URL without embedded credentials, a query string or a fragment. The App verifies Forgejo through `/api/v1/version`. Signed-in-only Forgejo instances are supported through a bounded, same-origin login-page version fallback that sends no PAT. Continue with the [administrator guide](admin-guide.md).

Before starting a production deployment, set `FMCP_FORGEJO_ALLOWED_BASE_URLS` in `deploy/.env` to a JSON list containing this exact URL. The value is an out-of-band security boundary, not a discovery list. An empty list permits no Forgejo connection, including in development and test.

If Traefik or another reverse proxy forwards the real client address, set `FMCP_TRUSTED_PROXY_CIDRS` to a JSON list containing only that proxy's exact IPv4/IPv6 networks. Leave it as `[]` when the source IP is not needed. Never trust all networks: untrusted `X-Forwarded-For` values must not control login or OAuth rate-limit keys.

## 8. Stop or restart

Stop and remove the containers while retaining PostgreSQL data:

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml down
```

Start them again:

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d
```

Rebuild after source or image changes:

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml up --build -d
```

## 9. Reset local data

> **Destructive:** this removes the Compose PostgreSQL data and any data created by the optional local Forgejo profile.

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml down -v
```

Secret files and `deploy/.env` remain on disk. Delete them separately only when you intentionally want new credentials.

## 10. Optional local Forgejo profile

Forgejo is not part of the normal deployment stack. For local testing only, set this value in `deploy/.env`:

```dotenv
FMCP_ALLOW_INSECURE_FORGEJO_HTTP=true
```

Then start the test profile:

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml --profile test-forgejo up --build -d
```

The test Forgejo endpoint is <http://127.0.0.1:3000>. From the App container its base URL is `http://forgejo:3000`.

This profile starts a local Forgejo service but does not represent a supported company deployment or automatically provide production-ready users, repositories and PATs. The full automated integration fixture is `./scripts/test-full-docker-e2e.sh`.

## Common startup problems

### A secret mount fails

Confirm that these files exist:

```text
deploy/secrets/admin_password
deploy/secrets/credential_key
deploy/secrets/database_url
deploy/secrets/postgres_password
```

If custom absolute secret paths are configured in `deploy/.env`, ensure Docker can read them.

### Port 8000 or 5433 is already in use

Change `FMCP_HTTP_PORT` or `POSTGRES_HOST_PORT` in `deploy/.env`, then recreate the stack. When changing the HTTP port, use that port for the Dashboard and health URLs.

### PostgreSQL is healthy but the App is not ready

Inspect App logs for migration or configuration errors:

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml logs app
```

### Forgejo verification rejects HTTP

Normal deployments require HTTPS. Use HTTP only for the local test profile and only when `FMCP_ALLOW_INSECURE_FORGEJO_HTTP=true`.

### Forgejo verification rejects disabled TLS verification

Keep certificate verification enabled. A reviewed private-CA exception requires the deployment owner to set `FMCP_ALLOW_UNVERIFIED_FORGEJO_TLS=true` in addition to the Dashboard choice; prefer installing the correct CA trust instead.

## Next steps

- [Administrator guide](admin-guide.md)
- [User guide](user-guide.md)
- [MCP client configuration](mcp-client-configuration.md)
- [Known limitations](known-limitations.md)
