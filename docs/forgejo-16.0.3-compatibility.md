# Forgejo 16.0.3 compatibility report

## Executive summary

Forgejo MCP is compatible with both Forgejo 16.0.2 and 16.0.3. The official Swagger documents contain no endpoint-level difference: every path, method, operation ID, parameter, request body and response used by the 50-tool MCP catalog is unchanged.

The only functional schema change is that Forgejo 16.0.3 marks `index`, `owner` and `repo` as required in `IssueMeta`. Forgejo MCP does not consume or emit `IssueMeta`, so no endpoint adapter or generated client change is required.

MCP Streamable HTTP compatibility remains locked by integration and full-stack E2E initialization with protocol version `2025-06-18`.

## Tested artifacts

| Release | Official rootless image | Image digest | Swagger version | Swagger SHA-256 |
| --- | --- | --- | --- | --- |
| 16.0.2 | `data.forgejo.org/forgejo/forgejo:16.0.2-rootless` | `sha256:23ccc146e6dc2cd1f5c5435909baae64db873201717f1726490dae649283e6cd` | `16.0.2+gitea-1.22.0` | `9e94799decc739c31fa68d8dc1b2d7f392e810a088f10b032c9962665398612b` |
| 16.0.3 | `data.forgejo.org/forgejo/forgejo:16.0.3-rootless` | `sha256:214f4ae63ee78be1e445e58573c88dc7215e72091210852e0df94eaac1a25685` | `16.0.3+gitea-1.22.0` | `f638c2ad8ec38f7f53b5e34ce24506fd142d16c4234bde996a52a1b9ac213b0a` |

Image digests are evidence for the images tested while preparing this report. Runtime verification remains checksum-based on the served Swagger document because registry tags can be republished.

## Complete Swagger difference list

The recursive JSON comparison reports exactly two structural differences:

| Change | JSON pointer | 16.0.2 | 16.0.3 | Impact |
| --- | --- | --- | --- | --- |
| Added | `/definitions/IssueMeta/required` | absent | `["index", "owner", "repo"]` | Schema metadata only; `IssueMeta` is not used by a registered MCP tool |
| Changed | `/info/version` | `16.0.2+gitea-1.22.0` | `16.0.3+gitea-1.22.0` | Expected release identifier change |

Summary: 2 total changes, 1 schema change, 1 metadata change, 0 endpoint changes.

The locked machine-readable result is in `tests/contracts/forgejo-16.0.2-to-16.0.3-openapi-diff.json`. `scripts/test-forgejo-openapi-compatibility.sh` launches both official images, verifies each Swagger checksum, performs the complete comparison and fails if the result drifts or if any endpoint changes.

## Endpoint impact assessment

No endpoint adapter was changed. The existing hand-written bounded HTTP client remains the correct implementation; this repository does not contain a generated OpenAPI client to regenerate.

| Required area | E2E route or MCP operation | 16.0.2 | 16.0.3 | Adapter change |
| --- | --- | --- | --- | --- |
| Login | Forgejo Basic authentication for PAT creation; Dashboard session login | Covered | Covered | None |
| Repositories | Repository create/list/read/update/migrate/mirror MCP operations | Covered | Covered | None |
| Branches | Branch list/create MCP operations | Covered | Covered | None |
| Commits | Commit list/read/create/compare/tree/status MCP operations | Covered | Covered | None |
| Pull requests | Create/read/update/review/merge/files/diff MCP operations | Covered | Covered | None |
| Issues | Create/read/update/comment/list MCP operations | Covered | Covered | None |
| Releases | Tag and release creation MCP operations | Covered | Covered | None |
| Files | Contents list/read and atomic multi-file commit MCP operations | Covered | Covered | None |
| Search | `GET /api/v1/repos/search` against the created repository | Covered | Covered | None; endpoint is intentionally outside the v1 MCP catalog |
| Webhooks | `POST` and `GET /api/v1/repos/{owner}/{repo}/hooks` | Covered | Covered | None; endpoint is intentionally outside the v1 MCP catalog |

The full E2E also executes every registered MCP tool and fails on any missing or unexpected tool coverage.

## Permissions and security review

No additional Forgejo or GitHub permission is introduced.

- The E2E PATs use the same explicit least-privilege scope set on both releases: `read:user`, `write:organization`, `write:repository` and `write:issue`. The previous broad `all` scope is no longer used.
- The MCP permission registry, global enablement, user allowances, token grants and tool risk classifications are unchanged.
- No application route, authentication flow, authorization decision, outbound-request destination rule, response-size bound or secret-handling path changed.
- The new GitHub workflow declares only `contents: read` and receives no repository secrets.
- Swagger downloads are limited to operator/CI-supplied sources, use a 30-second timeout and are checksum-verified before compatibility is accepted.
- The comparison and E2E scripts use disposable containers and temporary directories; no credentials are written to the repository.

Security regression summary: no critical, high, medium or low regression was identified in the compatibility diff. Existing documented deployment limitations remain unchanged.

### SEC-001: Pre-existing frontend build dependency advisory

- **Severity:** High according to `npm audit`; not introduced by this change.
- **Location:** `frontend/package-lock.json`, `node_modules/nanoid` and the PostCSS dependency declaration.
- **Evidence:** the unchanged lockfile resolves `vite -> postcss -> nanoid@3.3.16`; `npm audit --audit-level=high` reports GHSA-2v37-7h3g-55p8, fixed in nanoid 3.3.18.
- **Impact:** affected custom nanoid generators can loop indefinitely when invoked with a zero size. The package is a transitive frontend build dependency here; no direct application import was found.
- **Fix:** update the compatible PostCSS/nanoid dependency chain in a dedicated dependency change and run the complete frontend and E2E suites.
- **Mitigation:** CI uses the committed lockfile through `npm ci`; this compatibility change modifies neither `frontend/package.json` nor `frontend/package-lock.json`.
- **False-positive notes:** production reachability through the current Vite/PostCSS build path should be reassessed with the dependency update; the npm advisory severity is retained rather than downgraded here.

## Validation results

Validated on 2026-08-31:

- `scripts/test-forgejo-openapi-compatibility.sh`: passed against both official images; 2 locked differences and 0 endpoint changes.
- Complete Docker E2E with Forgejo 16.0.2: passed; all 50 registered MCP tools executed.
- Complete Docker E2E with Forgejo 16.0.3: passed; all 50 registered MCP tools executed.
- PostgreSQL-backed suite: 77 passed, 1 opt-in external-Forgejo test skipped.
- Ruff lint and format, mypy, ESLint, TypeScript typecheck and React production build: passed.
- MCP SDK 1.28.1 reports `2025-06-18` among its supported protocol versions, and both integration and E2E initialization succeed with that exact version.

## Continuous verification

On every pull request, `.github/workflows/forgejo-e2e.yml` runs:

1. the automatic 16.0.2 versus 16.0.3 Swagger comparison;
2. the complete Docker E2E suite against Forgejo 16.0.2;
3. the complete Docker E2E suite against Forgejo 16.0.3.

The Compose development default is Forgejo 16.0.3. Set `FORGEJO_IMAGE=data.forgejo.org/forgejo/forgejo:16.0.2-rootless` to reproduce the compatibility baseline.
