# Third-party review handoff

This document is the review entry point for branch `compat/forgejo-16.0.3`. Review the current branch HEAD rather than relying on an older report snapshot. Do not publish an upstream pull request until the independent reviewer has returned a disposition.

## Review scope

The branch must preserve:

- Forgejo 16.0.3 as the minimum supported release, with 16.0.2 retained only as a comparison baseline;
- MCP Streamable HTTP protocol `2025-06-18`;
- the existing 50-tool catalog and closed JSON Schemas;
- the existing Forgejo PAT scope set (`read:user`, `write:organization`, `write:repository`, `write:issue` in E2E);
- GitHub Actions read-only repository permissions;
- the global, user and token authorization intersection.

The 2026-09-02 follow-up specifically changes OAuth client compatibility, browser CORS, repository/ref/file segment validation, Forgejo URL/TLS deployment policy, audit redaction, trusted-proxy address handling, atomic rate-limit reservations and loopback Compose publishing.

## Evidence to read first

1. [External audit and remediation disposition](audit-externe-2026-09-02.fr.md)
2. [Primary security audit](security-audit-2026-08-31.md)
3. [OAuth 2.1 security and operations](oauth-2.1.md)
4. [Forgejo 16.0.3 compatibility report](../forgejo-16.0.3-compatibility.md)
5. [Known limitations](../known-limitations.md)

## High-priority review questions

- Can any owner, organization, repository, ref or file parameter cause HTTP URL normalization to reach a different Forgejo endpoint than the granted tool describes?
- Can a Dashboard administrator redirect a PAT-bearing request when the deployment allowlist is empty, stale or different from the stored instance?
- Can URL credentials, authorization values, commit content or file/diff content enter logs, full audit arguments, extracted audit targets, API responses or browser storage?
- Can an untrusted peer spoof single or duplicate `X-Forwarded-For` lines, or can a trusted-proxy chain select an attacker-provided leftmost address instead of the first untrusted hop from the right?
- Can `verify_tls=false` be selected or remain effective from stored state without a current deployment-owner decision?
- Do OAuth omission handling, CORS and Origin validation preserve resource binding, Same-Origin controls and native MCP clients?
- Did any change add a Forgejo PAT scope, MCP tool, tool grant, GitHub permission, redirect following or arbitrary outbound destination?

## Reproduction commands

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
npm audit --prefix frontend
npm run lint --prefix frontend
npm run typecheck --prefix frontend
npm run build --prefix frontend
uvx pip-audit
```

Run the full disposable stack against the minimum supported Forgejo 16.0.3 release. The second command is an optional non-supporting 16.0.2 regression reference:

```bash
./scripts/test-full-docker-e2e.sh
FORGEJO_IMAGE=data.forgejo.org/forgejo/forgejo:16.0.2-rootless \
  ./scripts/test-full-docker-e2e.sh
./scripts/test-forgejo-openapi-compatibility.sh
```

Also re-run the repository's Gitleaks and detect-secrets scans against both current tracked files and published history. Treat test-only reserved domains, synthetic passwords and checksums as fixtures only after inspecting each match.

## Residual risks requiring operator controls

- Forgejo performs final DNS resolution for repository migration. Keep its migration allowlist and network egress policy enabled.
- Rate limits and active MCP sessions are process-local; reservations are atomic within one process, but limiter state resets on restart and is not shared across replicas.
- Reference images and Actions use version tags instead of immutable digests/commit SHAs.
- Public TLS termination, metrics isolation, PostgreSQL backup/restore and encryption-key recovery remain operator responsibilities.
- Possession of both PostgreSQL data and the credential-encryption key can recover active PATs.

## Maintainer validation before handoff

- Python with PostgreSQL: 149 collected, 148 passed, 1 external-credential E2E skipped; without PostgreSQL, 140 passed and 9 database/external tests were skipped.
- Ruff check/format and strict MyPy: passed.
- Frontend ESLint, TypeScript and Vite production build: passed.
- `pip-audit` and `npm audit`: 0 known vulnerabilities.
- Bandit: 0 Medium, 0 High; 24 reviewed Low heuristic findings.
- Gitleaks: no leak in the current worktree or published history.
- Docker E2E: all 50 tools passed independently on Forgejo 16.0.2 and 16.0.3, including OAuth and MCP `2025-06-18`.
- OpenAPI comparison: 0 endpoint differences; only version metadata and `IssueMeta.required` changed.
- Docker Compose configuration: valid with loopback publishing and required Forgejo URL policy.

## Reviewer output requested

Return each finding with severity, exact file/function/line evidence, exploit preconditions, concrete impact, minimal patch recommendation and false-positive notes. State separately:

- whether both High findings in the external audit are closed;
- whether any Critical, High or Medium finding remains;
- whether Forgejo permissions increased;
- whether MCP `2025-06-18` or the supported Forgejo 16.0.3 release regressed, and separately whether the 16.0.2 comparison baseline still passes;
- whether the branch is suitable for an upstream pull request.
