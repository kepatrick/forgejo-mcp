# Releasing the MCP Server image

[繁體中文](releasing.zh-TW.md)

This process releases **Forgejo MCP's own version**, not a Forgejo version. Forgejo compatibility is recorded separately in the [version compatibility matrix](compatibility.md) and in each release's changelog.

## Recommended flow: release from the GitHub UI

Before starting, merge all reviewed application, documentation, compatibility and upgrade notes into `main`. Both `CHANGELOG.md` and `CHANGELOG.zh-TW.md` must contain meaningful matching content under `[Unreleased]`.

1. Open **Actions → Release → Run workflow**.
2. Select branch **main**.
3. Enter the new stable MCP SemVer, with or without `v` (for example `X.Y.Z` or `vX.Y.Z`). Do not enter `patch`, `minor`, a Forgejo version, or a prerelease version.
4. Click **Run workflow**. This is a real release request, not a preview.
5. Wait for preparation, validation, all tests, image publication and GitHub Release publication.

The manual workflow performs the mechanical version bump itself:

1. It requires the workflow to start from the current `origin/main` and rejects an invalid, older or conflicting version.
2. It runs `python scripts/release.py X.Y.Z --prepare --apply`.
3. If preparation changes files, it creates `chore(release): prepare vX.Y.Z` and pushes that commit to `main`.
4. It pins the generated commit SHA. Standard CI, the locked OpenAPI comparison and the complete Forgejo E2E matrix all checkout and test that exact commit.
5. Only after all checks pass, it creates an annotated tag on that SHA, reserves a draft GitHub Release, builds the versioned GHCR image with provenance and an SBOM, appends the digest and publishes the Release.

Preparation changes exactly these seven files:

- `pyproject.toml`;
- `uv.lock` root package metadata;
- `frontend/package.json`;
- `frontend/package-lock.json` root package metadata;
- `deploy/compose.image.yaml`;
- `CHANGELOG.md`;
- `CHANGELOG.zh-TW.md`.

Dependency resolutions are not changed during release preparation. The reviewed `[Unreleased]` notes are moved to a dated version section, and a new empty `[Unreleased]` section remains.

The built-in `GITHUB_TOKEN` commit and tag pushes do not trigger duplicate workflows. The running Release workflow performs all required tests and publication itself.

### Repository settings required for automatic preparation

GitHub Actions and organization/repository rules must allow the Release workflow to:

- push its generated release commit to `main` with `contents: write`;
- create protected `v*` tags and GitHub Releases with `contents: write`;
- publish packages with `packages: write`.

If `main` requires pull requests, signed commits or checks that the workflow cannot bypass, the automatic commit push fails before any tag or image is created. Grant only the Release workflow the narrow bypass it needs, or use the reviewed local preparation path below instead of weakening branch protection globally.

A concurrent update to `main` causes the release commit push to fail rather than overwriting the newer commit.

### GitHub CLI equivalent

```bash
gh workflow run release.yml --ref main -f version=X.Y.Z
```

Use the UI or CLI dispatch once for a release; do not start both.

## What must be reviewed before pressing Run workflow

- Both changelogs describe the actual changes in English and Traditional Chinese.
- Compatibility notes distinguish supported Forgejo versions from comparison baselines.
- Required environment variables, secret-file changes, database migrations and rollback limitations are documented.
- The compatibility matrix and detailed evidence match the release promise.
- Pull-request CI is green.
- PostgreSQL and credential-encryption secrets have a tested backup plan before an operator upgrade.

For the v0.2.0 release line, existing installations must follow the [security hardening upgrade guide](security/upgrade-hardening.md). Forgejo 16.0.3 is supported; Forgejo 16.0.2 is retained only as a comparison baseline. No database or OAuth migration is introduced.

## Optional local preparation and tag publication

The script remains available for maintainers whose repository rules require a reviewed release commit instead of an automated push.

Preview or apply a version bump from a clean working tree:

```bash
python3 scripts/release.py patch --prepare
python3 scripts/release.py patch --prepare --apply

# Alternatives: choose one
python3 scripts/release.py minor --prepare
python3 scripts/release.py major --prepare
python3 scripts/release.py X.Y.Z --prepare
```

`--apply` does not create a commit or push. Review and commit the seven generated files, merge them into `main`, and then either run the manual workflow with the same version or publish the tag locally:

```bash
python3 scripts/release.py X.Y.Z
python3 scripts/release.py X.Y.Z --publish
```

Local publication requires a clean `main`, `HEAD` equal to the current `origin/main`, matching release metadata, and no conflicting local or remote tag. Use only one publication path for a release.

To check prepared metadata without checking Git state:

```bash
python3 scripts/release.py X.Y.Z --check
```

The check verifies the Python project and lockfile version, frontend package and lockfile versions, Compose image version, and nonempty dated release sections in both changelogs.

## Release artifacts

- Annotated Git tag: `vX.Y.Z`.
- GHCR image: `ghcr.io/<owner>/<repo>:X.Y.Z`, normalized to lowercase.
- GitHub Release: combined English and Traditional Chinese changelog notes plus the image digest.
- Platform: `linux/amd64`.
- OCI source, version and tested commit revision labels, minimal provenance and an SBOM.

The workflow does not publish `latest` or floating minor tags, does not automatically mark a GitHub Release as Latest, does not publish to PyPI or Docker Hub, and does not update running deployments.

For this repository:

| Artifact | Location |
| --- | --- |
| Releases | <https://github.com/kepatrick/forgejo-mcp/releases> |
| Container image | `ghcr.io/kepatrick/forgejo-mcp:X.Y.Z` |
| Container package | <https://github.com/users/kepatrick/packages/container/package/forgejo-mcp> |
| Workflow runs | <https://github.com/kepatrick/forgejo-mcp/actions/workflows/release.yml> |

Confirm the GHCR package is public if anonymous pulls are intended. Existing packages must grant this repository's Actions access.

## Using a published image

Use the deployment files and upgrade instructions from the same release tag. Do not mix newer Compose files with an older image without review.

```dotenv
FMCP_IMAGE=ghcr.io/kepatrick/forgejo-mcp:X.Y.Z
```

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml -f deploy/compose.image.yaml pull app
docker compose --env-file deploy/.env -f deploy/compose.yaml -f deploy/compose.image.yaml up -d --no-build
```

For production, prefer the digest-pinned reference from the release notes: `ghcr.io/...@sha256:...`. Back up PostgreSQL and credential-encryption secrets before upgrading. Rolling back an image does not automatically roll back database schema or configuration.

## Failures and retries

**Never force-push or move a release tag, and never overwrite a published image.**

- **Automatic release commit push rejected:** no tag or image exists. Fix the repository rule or use local preparation through a reviewed PR, then retry with the same version.
- **Preparation commit pushed, validation or CI failed before a tag exists:** transient failures may be rerun with the same version; the already prepared metadata is reused. If code or changelog changes are required, prepare a new patch version rather than appending changes to the prepared version section.
- **Local tag push failed:** check `git ls-remote origin refs/tags/vX.Y.Z` and Actions. The local annotated tag is intentionally retained. If the remote has no tag, push that existing tag; do not recreate or move it.
- **Draft exists but no image was pushed:** verify GHCR has no versioned image, delete the draft but not the tag, then rerun.
- **Image was pushed but Release publication failed:** do not rebuild. Verify the image revision against the tag commit, obtain its digest with `docker buildx imagetools inspect`, add the image and digest to the existing draft, and publish it manually.
- **Release already exists:** publish fixes under a new patch version.
