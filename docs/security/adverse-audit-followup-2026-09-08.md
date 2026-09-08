# Adverse audit follow-up — 2026-09-08

This is a scoped correction record, not a new comprehensive security certification.
The original external audit is preserved unchanged by this patch series.

## Medium: compressed response amplification

The Forgejo client reads raw HTTP response bytes and limits both wire bytes and
decoded output to 10 MiB. zlib output is bounded during decompression, rather than
after HTTPX has allocated the decoded body. The client advertises gzip and deflate;
identity, single gzip and standard zlib-wrapped deflate are supported. Chained and
unsupported encodings, trailing compressed members/data and truncated streams fail
closed. Decoded responses have their encoding and wire-length headers removed.

Preloaded responses supplied by custom/test transports are already decoded outside
this boundary: their final size is checked, but prior allocations in that transport
cannot be bounded here. The production HTTPX streaming path uses the raw-byte limit.

Regression tests use a 1 MiB limit and a 16 MiB expanded body for gzip and deflate;
each must fail with a traced allocation peak below 5 MiB. No GiB-sized bomb is needed.
Existing compressed-response success tests are retained.

## Medium: historical Dashboard revocations

Migration `20260908_0012` repairs families missed by `0011`. It recognizes explicit
`mcp_token.revoked` Dashboard audit evidence, plus revoked access tokens whose refresh
record was never rotated. It propagates family revocation to refresh/access/MCP rows.
It does not mistake ordinary revocation of an old access token during healthy refresh
rotation for voluntary family revocation.

PostgreSQL regression fixtures cover healthy rotation, historical Dashboard evidence,
unrotated revocation and an already partially revoked family, including idempotence.
If audit history and original refresh records have been deleted, historical intent
may no longer be reconstructible. Review affected grants and revoke them explicitly;
do not claim that migration can reconstruct deleted evidence.

### Upgrade

1. Back up the database and retain the matching application image/configuration.
2. Stop all application workers before applying migrations.
3. Run `alembic upgrade head` with the deployment's database configuration.
4. Restart workers with the matching corrected application version.
5. Verify that a revoked grant cannot refresh, while an active grant still works.

Migration `0012` also applies to installations already at `0011`. Its downgrade does
not resurrect credentials. Rollback is not a mechanism for undoing security revocations.

## Low: audit-text redaction witnesses

Numeric credentials such as `1234:5678@host/r`, scp-like destinations, parentheses,
quotes, terminal punctuation and passwords containing `/` are now covered in both
argument redaction and target extraction tests. Existing URL-redaction tests remain.

This heuristic is not a universal secret detector. Clock-like text (`12:30@office`)
is deliberately retained for compatibility and is indistinguishable from some short
numeric credentials. Arbitrary `name:value@host` prose can still be over-redacted.
Never intentionally place credentials in free-text tool arguments or log fields.

## Validation and remaining work

- PostgreSQL-backed Python suite: 161 passed, 1 external-Forgejo E2E skipped.
- Fresh Alembic upgrade through `0012`: passed.
- Ruff and MyPy: passed.
- No new full Docker Forgejo E2E run or production deployment is claimed here.
- The lower-severity bearer/revocation timing and disabled-user recovery-cache
  findings still need dedicated corrections and concurrency regression tests.
- The maintainer's requested split into compatibility, security/deployment and
  OAuth PRs is not performed by these three correction commits.

Publishing and deployment must be verified separately; local test success is not
evidence that a remote PR or running service contains these changes.

## Subsequent fifth-audit corrections

The preceding status is historical. The fifth external counter-audit identified
remaining defects; its text is preserved in the external audit document.

- Conditional bearer `last_used_at` UPDATE rechecks token revocation after waiting
  on a PostgreSQL row lock; a deterministic test observes the lock before commit.
- Revocation of a missing family raises explicitly instead of reporting success.
- Warm refresh recovery revalidates user/Forgejo-credential readiness.
- Dedicated `grace=0` coverage verifies replay revokes the replacement family.
- Backfill tests additionally use the real Alembic schema and bearer/refresh
  services for legacy Dashboard revocation and healthy rotation.
- HTTP 204/304/HEAD responses do not decode nonexistent bodies.
- Parenthesized passwords and additional authority terminators are redacted;
  explicit ratio and release-version prose has regression coverage.

The integrated Docker E2E passed Forgejo 16.0.3 with OAuth and all 50 tools.
Scope-specific replacement branches are based on current upstream rather than
shipping unrelated release-automation deletions from the old integrated branch.
Their individual tests and publishing/deployment state are recorded separately.

At the start of this follow-up, PR #3 still pointed at `cf40e9b` and carried the
known high-severity refresh/revocation bug. It was explicitly returned to draft
while replacement PRs were prepared; the old readiness comment is superseded.
