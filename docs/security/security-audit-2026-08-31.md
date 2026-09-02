# Security audit — 2026-08-31

## Executive summary

> The optional OAuth 2.1 extension was reviewed separately on 2026-09-02. Its findings, fixes, rollback control and current validation evidence are documented in [OAuth 2.1 security and operations](oauth-2.1.md).

> The current branch disclosure scan, privacy review, final validation commands and independent-review checklist are maintained in the [third-party review handoff](third-party-review.md).

> An independent Claude review on 2026-09-02 challenged two conclusions in this document and found additional audit/deployment weaknesses. Its original evidence, adverse counter-audit and remediation dispositions are preserved in the [external audit report](audit-externe-2026-09-02.fr.md). The follow-up rejects dot segments across repository/ref/file parameters, redacts both arguments and extracted targets before persistence, and revalidates TLS policy at every PAT-bearing boundary.

The audit covered commit `d29d13bb21431fe307aca9fef7c0cd96749cd2b6` and the security patch prepared on branch `compat/forgejo-16.0.3`. It found no Critical issue, two High issues, three Medium issues, and three Low issues. All eight findings are fixed by the patch documented here.

The most important issue was a trust-boundary bypass: a local Dashboard administrator could change the Forgejo base URL to a server they controlled and then receive a user's PAT during credential verification. The second High issue allowed a token explicitly granted the repository-migration tool to ask Forgejo to connect to unsafe or local sources.

The fixes do not add Forgejo PAT scopes, GitHub permissions, MCP tools, or MCP grants. MCP protocol `2025-06-18` remains the negotiated contract.

## Scope and method

Reviewed surfaces:

- FastAPI routes, session/CSRF authentication and role policies;
- MCP Streamable HTTP authentication, session ownership, JSON-RPC dispatch, schemas, tool discovery and call-time authorization;
- every outbound `httpx` request and redirect policy;
- repository, ref, file path, migration URL and nested option validation;
- PAT encryption, MCP/session/invitation token persistence and revocation;
- audit records, application logs and browser storage/rendering;
- PostgreSQL transaction boundaries and concurrent one-time operations;
- Docker/Compose secrets, GitHub Actions permissions and dependency lockfiles.

Automated checks included the full Python test suite, Ruff, MyPy, frontend lint/typecheck/build, `npm audit`, `pip-audit`, secret-pattern scanning, Docker Compose validation and the existing Forgejo 16.0.2/16.0.3 E2E matrix.

## Findings

### SEC-001 — High — Forgejo PAT exfiltration through mutable trusted base URL

**Baseline evidence.** `ForgejoInstanceService.check()` accepted any syntactically valid HTTP(S) URL selected through the admin-only route. `ForgejoCredentialService.verify()` subsequently sent the user's PAT to that saved URL. Because an attacker-controlled endpoint can spoof `/api/v1/user`, the username check did not protect the PAT. This contradicted the stated boundary that administrators cannot retrieve PAT plaintext.

**Impact.** A compromised or malicious Dashboard administrator could redirect future PAT tests/rotations and steal Forgejo credentials, potentially gaining all repositories and actions permitted by those PATs.

**Fix.** Production now requires `FMCP_FORGEJO_ALLOWED_BASE_URLS`, normalized and made mandatory at startup in `src/forgejo_mcp/config.py:31-74`. The check occurs before the connection test in `src/forgejo_mcp/application/forgejo_instance_service.py:35-38`, before PAT verification in `src/forgejo_mcp/application/forgejo_credential_service.py:85-96`, and before every MCP tool decrypts or sends a PAT in `src/forgejo_mcp/application/forgejo_tool_service.py:387-396`. This also fails closed if a pre-upgrade database contains an unpinned URL. The exact scheme, authority, port and subpath are pinned outside the Dashboard.

**Mitigation/operations.** Store the production environment file with infrastructure-level access controls. Include only the canonical HTTPS Forgejo URL. Changing the pin is a deployment change and should require the same review as rotating the credential-encryption key.

**False-positive notes.** The vulnerable route required an authenticated admin and CSRF token, but that does not negate the finding: the documented design deliberately keeps PAT plaintext outside administrator visibility.

### SEC-002 — High — SSRF and local-source access through repository migration

**Baseline evidence.** `_clone_address()` accepted any bounded string and only rejected whitespace or embedded URL credentials. Values such as `file:///...`, localhost/private IP URLs and non-URL scp syntax reached Forgejo's migration endpoint. The tool is a write tool protected by global enablement, user allowance and token grant, but a granted user could still target services reachable from the Forgejo host.

**Impact.** Depending on Forgejo migration policy, an attacker could probe internal services, access local sources, or make Forgejo connect to sensitive private endpoints.

**Fix.** `src/forgejo_mcp/forgejo/client.py:2066-2103` now requires a hosted `http`, `https`, `ssh` or `git` URL, rejects URL credentials/query/fragment, and blocks localhost, single-label/private suffixes and non-global IP literals. Private migration hosts are disabled by default and require the explicit `FMCP_MIGRATION_ALLOW_PRIVATE_HOSTS=true` opt-in wired at `src/forgejo_mcp/forgejo/client.py:152-177`.

**Mitigation/operations.** Keep Forgejo's own migration allow/deny settings restrictive. The application-side check cannot fully eliminate DNS rebinding because final resolution happens in the Forgejo process; production egress filtering and a Forgejo domain allowlist remain recommended.

**False-positive notes.** Explicit MCP grants reduce attacker population but are not network-target authorization. Forgejo's default policy may block some payloads, so exploitability depends on its deployment configuration.

### SEC-003 — Medium — Missing browser Origin validation on `/mcp`

**Baseline evidence.** The MCP route had bearer authentication and session-owner binding but no `Origin` check before authentication. MCP's HTTP security guidance requires validating browser origins to mitigate DNS rebinding and unintended cross-origin invocation.

**Impact.** A browser environment holding or injecting an MCP bearer credential could be induced to issue requests from an untrusted origin. The absence of permissive CORS and the bearer requirement limited ordinary drive-by exploitation, but did not satisfy the MCP transport boundary.

**Fix.** `McpOriginValidationMiddleware` runs before bearer authentication in `src/forgejo_mcp/mcp/server.py`. Origin normalization and exact matching are implemented in the same module and `src/forgejo_mcp/config.py`. Requests without `Origin` remain valid for native MCP clients; browser clients require an explicit `FMCP_MCP_ALLOWED_ORIGINS` entry. The adjacent CORS middleware permits only the configured origins, MCP methods and request headers, exposes only the authentication and MCP session response headers, and keeps credentials mode disabled. Wildcards are unsupported.

**False-positive notes.** This is defense in depth for the current native-client use case, not evidence of a leaked bearer token.

### SEC-004 — Medium — Response-size checks occurred after unbounded buffering

**Baseline evidence.** `httpx.AsyncClient.request()` buffered the complete response before endpoint-specific `len(response.content)` checks. An oversized or compressed response from a malicious configured endpoint or compromised Forgejo could therefore consume memory before validation.

**Impact.** Remote denial of service of the Forgejo MCP process, with risk increasing under concurrent MCP calls.

**Fix.** All Forgejo responses are now streamed and capped at 10 MiB before buffering in `src/forgejo_mcp/forgejo/client.py:1801-1837` and `src/forgejo_mcp/forgejo/client.py:2106-2126`. Smaller endpoint-specific limits remain in force after the global cap.

**False-positive notes.** A normal Forgejo is trusted infrastructure, but the admin connection-test route and SEC-001 made attacker-controlled responses reachable. The cap also protects against accidental oversized responses.

### SEC-005 — Medium — Concurrent invitation acceptance was not serialized

**Baseline evidence.** Invitation validity was read and later marked used without a row lock. Two transactions could both pass the one-time check and race to set different passwords.

**Impact.** A party that obtained an invitation token could race the intended recipient and potentially control the new local account even when both requests appeared successful.

**Fix.** Acceptance selects the invitation with `FOR UPDATE` at `src/forgejo_mcp/db/repositories/invitations.py:19-32`; `src/forgejo_mcp/application/invitation_service.py:53-73` holds that lock through password update and commit. Context preview remains a non-locking read.

**False-positive notes.** Exploitation requires possession of the high-entropy invitation token and concurrent timing, but the operation is documented as one-time and must be atomic.

### SEC-006 — Low — Log formatter lacked credential-safe fallback redaction

**Baseline evidence.** Structured log extras and formatted exceptions were emitted verbatim. Current first-party log calls did not intentionally include PATs or bearer headers, but a future diagnostic extra or third-party exception could persist a credential.

**Impact.** Accidental PAT, MCP token, session cookie or database password disclosure to log readers and log aggregation systems.

**Fix.** `src/forgejo_mcp/observability/logging.py:9-21` defines sensitive keys and credential patterns. JSON extras, messages and exceptions plus text-format output are recursively redacted at `src/forgejo_mcp/observability/logging.py:24-82`.

**Mitigation.** Continue to avoid logging request headers and bodies. Pattern redaction is a last line of defense and cannot recognize every opaque Forgejo PAT value when it appears without a sensitive key or authorization prefix.

**False-positive notes.** No committed real secret and no confirmed credential-bearing production log statement was found.

### SEC-007 — Low — Sensitive responses lacked explicit no-store/browser hardening headers

**Baseline evidence.** The show-once MCP token response and authenticated management APIs relied on default cache behavior. The frontend had no server-provided CSP, frame denial or referrer policy.

**Impact.** Misconfigured intermediaries or browser extensions could retain sensitive responses; framing increased UI-redress risk. POST responses are rarely cached, so practical exposure was limited.

**Fix.** `src/forgejo_mcp/observability/middleware.py:104-135` adds `Cache-Control: no-store` and `Pragma: no-cache` to `/api/*` and `/mcp`, plus CSP, `frame-ancestors 'none'`, `X-Frame-Options: DENY`, `nosniff` and `Referrer-Policy: no-referrer` globally.

**False-positive notes.** MCP and Forgejo PAT plaintext were not found in browser persistent storage; the frontend keeps show-once values only in React memory.

### SEC-008 — Low — Patched transitive dependency versions were not selected

**Baseline evidence.** `npm audit` reported GHSA-2v37-7h3g-55p8 in `nanoid` 3.3.16. `pip-audit` reported CVE-2026-69247 / GHSA-g6cj-pr64-35w5 in `cryptography` 49.0.0.

**Impact.** The nanoid issue affects a custom generator called with size zero; no such application call exists. The cryptography oracle affects attacker-controlled PKCS#7 decryption; this project uses AES-GCM and never calls the affected PKCS#7 APIs. Application reachability is therefore Low even though upstream advisory ratings are higher.

**Fix.** `frontend/package-lock.json:2158-2161` selects nanoid 3.3.18. `pyproject.toml` now requires cryptography 50.x and `uv.lock` selects 50.0.1. Post-fix `npm audit` and `pip-audit` report zero known vulnerabilities.

**False-positive notes.** Both advisories were unreachable in reviewed first-party code, but upgrading avoids future reachability and clears supply-chain policy.

## Requested attack-class disposition

| Attack class | Result |
| --- | --- |
| SSRF / remote URL validation | SEC-001 and SEC-002 fixed; redirect and egress residuals documented |
| Forgejo PAT leakage | SEC-001 fixed; encrypted AES-256-GCM storage remains at `src/forgejo_mcp/credentials/cipher.py:26-76` |
| MCP token leakage | No plaintext persistence found; hashed storage/show-once design retained; SEC-006/007 add defense in depth |
| Permission bypass | The six call-time checks remain fail-closed; the external audit found a URL-normalization bypass of endpoint granularity through exact `.`/`..` parameters, now rejected in both MCP schemas and the Forgejo client |
| Path traversal | The earlier conclusion was incomplete: file paths rejected `..`, but owner/repository/ref segments did not. Exact dot segments are now rejected before URL construction; ZIP entries are never extracted |
| JSON-RPC injection | No injection found; SDK parsing plus closed JSON Schemas and manual call-time validation reject unknown fields/types |
| MCP tool attacks | SEC-003/004 fixed; body limits, per-token/user rate limits, session credential binding and output bounds retained |
| FollowRedirect | Safe: `follow_redirects=False` at `src/forgejo_mcp/forgejo/client.py:1822-1827`, with explicit redirect rejection at line 1865 |
| Same-Origin | SEC-003 fixed with exact allowlist before bearer authentication |
| Deserialization | SEC-004 fixed; JSON and ZIP inputs are bounded, ZIP content stays in memory and is never written/extracted |
| Race conditions | SEC-005 fixed; login/invitation attempts are reserved atomically before authentication; in-flight MCP calls retain normal start-time authorization semantics |
| Secret storage | No defect found: PAT AES-GCM nonces/AAD, hashed high-entropy MCP/session/invitation tokens, and read-only secret mounts are appropriate |
| Credential logging | SEC-006 fixed; follow-up redaction removes URL user-info from arguments and bounded targets, recognizes camelCase secret keys, and replaces `changes[].content` with size plus SHA-256 before audit persistence |

## Residual risks and deployment requirements

- DNS names used for repository migration resolve in Forgejo, not necessarily in the MCP container. Keep Forgejo migration policy and network egress controls enabled.
- `FMCP_MIGRATION_ALLOW_PRIVATE_HOSTS=true` weakens SEC-002's application-side protection and must be restricted to the disposable E2E profile or a reviewed internal source.
- `FMCP_ALLOW_INSECURE_FORGEJO_HTTP=true` permits interception of PAT-bearing requests and is not suitable for production. `verify_tls=false` additionally requires `FMCP_ALLOW_UNVERIFIED_FORGEJO_TLS=true`; prefer installing the correct CA instead.
- Rate-limit state is bounded and purged but remains process-local, resets on restart and is not shared across replicas. Forwarded IPs are accepted only from `FMCP_TRUSTED_PROXY_CIDRS`.
- Reference images and GitHub Actions are pinned by version tags rather than immutable digests/commit SHAs; higher-assurance deployments should apply organization provenance and pinning policy.
- Possession of both PostgreSQL data and the credential-encryption key can recover active PATs. Back up and authorize those assets separately.
- Revoking a token or grant does not cancel a Forgejo request already in flight; it prevents subsequent authenticated requests.

## Validation evidence

- Python unit/integration suite: 135 collected, 134 passed; the separate external-credential E2E was skipped as designed.
- Ruff check/format and strict MyPy: pass.
- Frontend ESLint, TypeScript and production build: pass.
- `npm audit`: 0 vulnerabilities after lock update.
- `pip-audit`: 0 vulnerabilities after lock update.
- Docker Compose configuration: valid with the required production URL pin.
- Forgejo E2E: all 50 tools against 16.0.2 and 16.0.3, including login, repositories, branches, commits, pull requests, issues, releases, files, search, webhooks, Actions, OAuth and MCP `2025-06-18`.
- Secrets: Gitleaks found no leak in the worktree or published history; detect-secrets candidates were reviewed as fixtures, placeholders, examples or checksums.
- Permissions: no new PAT scopes; GitHub Actions remains `contents: read`; no new MCP capability or grant.
