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
- Provide database credentials through the documented database/password files
  instead of embedding them in container environment variables. Keep files 0600.
- TLS verification remains enabled. `FMCP_ALLOW_UNVERIFIED_FORGEJO_TLS` is an
  explicit exception, not a recommended production setting.
- Private repository migration hosts require `FMCP_MIGRATION_ALLOW_PRIVATE_HOSTS`.
  Retain Forgejo-side migration policy and egress filtering against DNS rebinding.

## Behavioral changes

Unsafe path segments, embedded remote credentials and oversized responses are
rejected. Forgejo response decompression is bounded during decoding; gzip and
zlib-wrapped deflate are accepted, chained/unsupported encodings fail closed.
Bodyless 204/304/HEAD responses ignore compression metadata. Invitation acceptance
is serialized; login throttling is shared per client IP; logs redact credentials.

Audit free text uses heuristics, not a universal secret classifier. Clock-like
text, explicit numeric ratios and release-version notation remain readable; never
use free-text tool arguments as a secret transport.

No database migration is required by this PR. On rollback, restore the matching
configuration and application image without restoring or deleting database data.
Verify readiness, authenticated tools, refusal without a token and hostile-Origin
403 after rollout. Run the PostgreSQL suite and full Docker E2E before release.
