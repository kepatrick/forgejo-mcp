# Security hardening upgrade

This change is independent of Forgejo version validation and OAuth support. It
adds no OAuth routes, token tables, migrations, PAT scopes or MCP tools.

Before upgrading, back up the database, Compose configuration and encryption key.
Never commit the backup or print its credentials.

## Required configuration changes

- Set `FMCP_FORGEJO_ALLOWED_BASE_URLS` to the exact trusted Forgejo base URL(s).
  An empty list now denies PAT-bearing requests in every environment; production
  additionally refuses startup without this deployment pin.
- Configure `FMCP_MCP_ALLOWED_ORIGINS` only for browser clients that need it.
  Native clients without an Origin remain supported. CORS is not authentication.
- Configure `FMCP_TRUSTED_PROXY_CIDRS` only for trusted immediate proxies; leave
  Uvicorn proxy-header rewriting disabled when using this application-level chain.
  The supplied Compose command uses `--no-proxy-headers` for this reason.
- Provide database credentials through the documented database/password files
  instead of embedding them in container environment variables. Keep files 0600.
- TLS verification remains enabled. `FMCP_ALLOW_UNVERIFIED_FORGEJO_TLS` is an
  explicit exception, not a recommended production setting.
- Private repository migration hosts require `FMCP_MIGRATION_ALLOW_PRIVATE_HOSTS`.
  Retain Forgejo-side migration policy and egress filtering against DNS rebinding.

## Migrate an existing Compose installation

This is a credential-storage migration, **not a password rotation**. Do not run
the README's new-installation secret-generation commands against an existing
installation. PostgreSQL only uses `POSTGRES_PASSWORD_FILE` to initialize an
empty data directory; changing the file does not change an existing role's password.

1. Back up the database, existing configuration and secret files securely. Record
   the current Compose project name, database user/name and secret mount paths.
   Keep the existing `admin_password` and `credential_key` files unchanged.
2. Stop the stack using its existing Compose configuration (`docker compose ... down`),
   **without `-v`**. Preserve the project name and `postgres-data` volume when
   starting the upgraded stack. Do not copy `compose.example.env` over your existing
   `deploy/.env`; merge the required settings instead.
3. In a private directory (`umask 077`), create `deploy/secrets/postgres_password`
   containing the **currently working PostgreSQL password**, not a newly generated
   password. Use a secure editor or secret manager; do not place the password in
   command arguments, shell history, logs or commits.
4. Create `deploy/secrets/database_url` with the same credentials and existing
   database name:
   `postgresql+asyncpg://<encoded-user>:<encoded-password>@postgres:5432/<encoded-database>`.
   Percent-encode URL components (especially passwords containing `@`, `:`, `/`,
   `%`, `#` or `?`); the `postgres_password` file must contain the raw password,
   not the URL-encoded value. Keep `POSTGRES_USER` and `POSTGRES_DB` unchanged.
5. Set both new files to mode `0600`. If using custom paths, set
   `FMCP_POSTGRES_PASSWORD_FILE` and `FMCP_DATABASE_URL_SECRET_FILE` in `deploy/.env`.
   Preserve existing custom admin/encryption-key paths. Add the trusted Forgejo URL
   and any required proxy settings from the section above.
6. Start the upgraded stack with the same project name and volume. Check readiness,
   Dashboard login and an authenticated MCP tool call. If database authentication
   fails, check that the files contain the existing credentials; **do not delete the
   volume or regenerate the encryption key** to resolve it.
7. After validation, remove the obsolete `POSTGRES_PASSWORD` setting from the active
   `deploy/.env`. Retain the protected pre-upgrade configuration for rollback.

If password rotation is required, perform it separately by explicitly updating the
PostgreSQL role and both secret files together during a maintenance window.

## Behavioral changes

Unsafe path segments, embedded remote credentials and oversized responses are
rejected. Forgejo response decompression is bounded during decoding; gzip and
zlib-wrapped deflate are accepted, chained/unsupported encodings fail closed.
Bodyless 204/304/HEAD responses ignore compression metadata. Invitation acceptance
is serialized; login throttling is keyed by client IP and normalized username;
logs redact credentials.

Audit free text uses heuristics, not a universal secret classifier. Clock-like
text, explicit numeric ratios and release-version notation remain readable; never
use free-text tool arguments as a secret transport.

No database migration is required by this PR. On rollback, restore the matching
configuration and application image without restoring or deleting database data.
Verify readiness, authenticated tools, refusal without a token and hostile-Origin
403 after rollout. Run the PostgreSQL suite and full Docker E2E before release.
