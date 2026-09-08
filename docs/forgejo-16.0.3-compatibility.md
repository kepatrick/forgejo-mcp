# Forgejo 16.0.3 compatibility report

## Executive summary

Forgejo MCP officially supports Forgejo 16.0.3 as its minimum release. Forgejo 16.0.2 is retained only as the pre-upgrade OpenAPI and non-regression comparison baseline; successful comparison results do not make 16.0.2 a supported deployment target. Later Forgejo releases require compatibility verification before use.

The official Forgejo 16.0.2 and 16.0.3 Swagger documents contain no endpoint-level difference: every path, method, operation ID, parameter, request body and response used by the 50-tool MCP catalog is unchanged.

The only functional schema change is that Forgejo 16.0.3 marks `index`, `owner` and `repo` as required in `IssueMeta`. Forgejo MCP does not consume or emit `IssueMeta`, so no endpoint adapter or generated client change is required.

MCP Streamable HTTP compatibility remains locked by integration and full-stack E2E initialization with protocol version `2025-06-18`. The optional OAuth 2.1 flow is exercised end to end on the minimum supported Forgejo 16.0.3 release without changing Forgejo PAT scopes; the 16.0.2 run remains comparison evidence only.

## Tested artifacts

| Release | Official rootless image | Image digest | Swagger version | Swagger SHA-256 |
| --- | --- | --- | --- | --- |
| 16.0.2 | `data.forgejo.org/forgejo/forgejo:16.0.2-rootless` | `sha256:23ccc146e6dc2cd1f5c5435909baae64db873201717f1726490dae649283e6cd` | `16.0.2+gitea-1.22.0` | `9e94799decc739c31fa68d8dc1b2d7f392e810a088f10b032c9962665398612b` |
| 16.0.3 | `data.forgejo.org/forgejo/forgejo:16.0.3-rootless` | `sha256:214f4ae63ee78be1e445e58573c88dc7215e72091210852e0df94eaac1a25685` | `16.0.3+gitea-1.22.0` | `f638c2ad8ec38f7f53b5e34ce24506fd142d16c4234bde996a52a1b9ac213b0a` |

Image digests are evidence for the images tested while preparing this report. The 16.0.2 row is a comparison artifact, not a support declaration. Runtime verification remains checksum-based on the served Swagger document because registry tags can be republished.

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

The transport regression reported during upstream review was version-independent but relevant to real Forgejo deployments: HTTPX had already decoded a compressed stream before the bounded response was reconstructed with the original `Content-Encoding`. The reconstruction now removes encoding and wire-length headers after decoded-size enforcement. Regression tests cover both `gzip` and `deflate`; no endpoint contract or Forgejo permission changes.

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
- The compatibility-specific endpoint behavior is unchanged. A subsequent full-project security audit added version-independent hardening for trusted Forgejo URL pinning, migration sources, MCP browser origins, streamed response bounds, invitation concurrency and log redaction.
- The new GitHub workflow declares only `contents: read` and receives no repository secrets.
- Swagger downloads are limited to operator/CI-supplied sources, use a 30-second timeout and are checksum-verified before compatibility is accepted.
- The comparison and E2E scripts use disposable containers and temporary directories; no credentials are written to the repository.

Security regression summary: no critical, high, medium or low regression was introduced by the Forgejo 16.0.3 compatibility diff. The independent audit and fixes are documented in [Security audit — 2026-08-31](security/security-audit-2026-08-31.md).

### Resolved pre-existing frontend build dependency advisory

- **Original severity:** High according to `npm audit`; not introduced by Forgejo compatibility work.
- **Location:** `frontend/package-lock.json`, `node_modules/nanoid` and the PostCSS dependency declaration.
- **Evidence:** the baseline lockfile resolved `vite -> postcss -> nanoid@3.3.16`; `npm audit` reported GHSA-2v37-7h3g-55p8.
- **Impact:** affected custom nanoid generators can loop indefinitely when invoked with a zero size. The package is a transitive frontend build dependency here; no direct application import was found.
- **Fix:** the security patch selects nanoid 3.3.18 in the committed lockfile; `npm audit`, frontend checks and both E2E versions pass.
- **False-positive notes:** no direct application import or reachable zero-size custom generator was found.

## Validation results

Validated on 2026-08-31:

- `scripts/test-forgejo-openapi-compatibility.sh`: passed against both official images; 2 locked differences and 0 endpoint changes.
- Complete Docker E2E with Forgejo 16.0.2: passed; OAuth 2.1 and all 50 registered MCP tools executed.
- Complete Docker E2E with Forgejo 16.0.3: passed; OAuth 2.1 and all 50 registered MCP tools executed.
- PostgreSQL-backed suite: 104 passed, 1 opt-in external-Forgejo test skipped.
- Ruff lint and format, mypy, ESLint, TypeScript typecheck and React production build: passed.
- MCP SDK 1.28.1 reports `2025-06-18` among its supported protocol versions, and both integration and E2E initialization succeed with that exact version.

Revalidated on 2026-09-08 after the compressed-response and OAuth family-serialization fixes:

- automatic Swagger comparison: passed with the same 2 locked structural differences and 0 endpoint differences;
- complete Docker E2E on the minimum Forgejo 16.0.3 release: all 50 tools and OAuth/MCP `2025-06-18` passed;
- complete Docker E2E on the Forgejo 16.0.2 comparison baseline: all 50 tools and OAuth/MCP `2025-06-18` passed;
- Python with PostgreSQL: 151 passed and the opt-in external-credential test was skipped.

## Continuous verification

On every pull request, `.github/workflows/forgejo-e2e.yml` runs:

1. the automatic 16.0.2 versus 16.0.3 Swagger comparison;
2. the complete Docker E2E suite against Forgejo 16.0.2 as a non-supporting regression reference;
3. the complete Docker E2E suite against the minimum supported Forgejo 16.0.3 release.

The Compose development default and minimum supported release are Forgejo 16.0.3. Set `FORGEJO_IMAGE=data.forgejo.org/forgejo/forgejo:16.0.2-rootless` only to reproduce the historical comparison baseline.
