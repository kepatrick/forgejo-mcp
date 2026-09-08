# Releasing the MCP Server image

[繁體中文](releasing.zh-TW.md)

This process releases **Forgejo MCP's own version**, not a Forgejo version.
One MCP image may support multiple verified Forgejo versions. Each release must
list the versions actually tested; do not promise compatibility that has not been verified.

## Quick start: choose a version, then release manually

The same `scripts/release.py` now supports preparation and publication. Preparation
never creates a commit/tag or pushes anything. Publication only releases reviewed
metadata already merged into `main`.

### A. Prepare the next version locally

First commit the reviewed changes and write meaningful English and Traditional
Chinese notes under `[Unreleased]`. Preparation does not invent or translate release notes.
Then run from the repository root:

```bash
# Read-only preview: 0.1.0 -> 0.1.1
python3 scripts/release.py patch --prepare

# Apply the previewed changes to a clean working tree
python3 scripts/release.py patch --prepare --apply

# Alternatives: choose ONE, not all of these in sequence
python3 scripts/release.py minor --prepare       # 0.1.0 -> 0.2.0
python3 scripts/release.py major --prepare       # 0.1.0 -> 1.0.0
python3 scripts/release.py 0.3.0 --prepare        # explicit version
python3 scripts/release.py current --prepare    # initial release / already prepared version
```

Use `--date YYYY-MM-DD` to set the release date; the default is today's local date.
An existing prepared version keeps its reviewed date and notes. `current` is suitable
for the initial `0.1.0`, whose release section is already prepared. Once that version
is published, choose a higher version instead of reusing it.

`--apply` updates seven files: `pyproject.toml`, `uv.lock`, both frontend package files,
`deploy/compose.image.yaml`, and both changelogs. It moves Unreleased notes into the
new dated section while preserving historical sections. Dependency resolutions are
not changed; only root package version metadata is synchronized. Review deployment
documentation, compatibility promises, and migrations manually.

A dirty working tree, downgrade, missing translated notes, inconsistent source versions,
or a target release section conflicting with Unreleased notes stops preparation.
Preview works with uncommitted files; applying requires a clean tree. Review the diff,
run tests, and commit/merge the prepared changes to `main` through your usual review process.
Do not run a relative bump twice: `patch` always starts from the current project version.

### B. Publish through the GitHub UI (no local tag push needed)

After the workflow and prepared release commit are on the default branch:

1. Open **Actions → Release → Run workflow**.
2. Select branch **main**.
3. Enter the prepared version, such as `0.1.1` or `v0.1.1`.
4. Click **Run workflow**. This is an actual publication request, not a preview.
5. Wait for validation, CI, image upload, and GitHub Release publication.

The input must match committed release metadata; the UI does not bump versions or
commit changes. Manual runs on other branches are rejected. The workflow checks out
the triggering commit, tests it, and creates the annotated tag at that same commit,
even if main advances while tests are running. Existing tags pointing elsewhere are
rejected; matching tags can be reused for recovery without moving them.

The built-in `GITHUB_TOKEN` pushes the tag, which does **not** trigger a second tag
workflow. This manual run performs publication itself. Repository rules must allow
the workflow to create release tags; do not disable tag protections indiscriminately.

Alternatively, with the GitHub CLI installed and authenticated:

```bash
gh workflow run release.yml --ref main -f version=0.1.1
```

The existing local `python3 scripts/release.py 0.1.1 --publish` path remains supported.
Use either the UI/CLI trigger or the local tag push, not both for the same release.
Draft reservation and the recovery rules below apply to both paths.

## Artifacts and prerequisites

- Annotated Git tag: `vX.Y.Z`.
- GHCR image: `ghcr.io/<owner>/<repo>:X.Y.Z`, with the image name converted to lowercase.
- GitHub Release: combined English and Traditional Chinese notes from matching
  `CHANGELOG.md` and `CHANGELOG.zh-TW.md` sections, plus the image digest.
- Only stable SemVer versions and `linux/amd64` are currently published. There are no
  `latest` or floating minor image tags. The workflow also does not automatically mark
  a GitHub Release as Latest, so an older maintenance release cannot replace that pointer.
- Local requirements: Python 3.12+, Git, and permission to push repository tags.
- GitHub Actions must be enabled. Organization policies must allow the workflow to use
  `contents: write` and `packages: write`. Publishing uses the built-in `GITHUB_TOKEN`;
  no additional PAT is required.
- After the first publication, check the GHCR package visibility. Set it to public in
  package settings if anonymous downloads are intended. For an existing package, grant
  this repository's Actions access to it.
- Protect `main` and `v*` tags, prohibit modification/deletion of published versions,
  and restrict release permissions. Draft reservation prevents duplicate publication
  through this workflow; it is not registry-level immutable-tag enforcement.

## Where are releases published?

For this repository, `kepatrick/forgejo-mcp`, the destinations are:

| Artifact | Location |
| --- | --- |
| Git tag | The `vX.Y.Z` tag in the GitHub repository |
| Release notes and image digest | <https://github.com/kepatrick/forgejo-mcp/releases> |
| Docker image | `ghcr.io/kepatrick/forgejo-mcp:X.Y.Z` |
| Container package page | <https://github.com/users/kepatrick/packages/container/package/forgejo-mcp> |
| Release workflow status | <https://github.com/kepatrick/forgejo-mcp/actions/workflows/release.yml> |

In publish mode, the local script validates, creates, and pushes a Git tag; in
prepare mode, it only previews or updates local metadata. Manual Actions runs can
create the tag instead. The image is built
on a GitHub Actions runner and pushed to **GitHub Container Registry (GHCR)**,
not Docker Hub. The workflow does not publish a Python package to PyPI or update
any running deployment.
The image/package becomes available only after the first successful publication;
check public access for a new package. In a fork, the image path uses that fork's
owner and repository instead.

## 1. Prepare the release commit

Merge this workflow into `main` first. Before releasing:

1. Prefer `python3 scripts/release.py patch --prepare --apply` (or another version
   choice) to synchronize version files. If editing manually instead, update
   `[project].version`, run `uv lock`, and synchronize the frontend and image override.
   For the initial existing `0.1.0`, there is no need to bump just to publish it.
2. Move the changes being released into dated version sections in both
   `CHANGELOG.md` and `CHANGELOG.zh-TW.md`, retaining new `[Unreleased]` sections.
   Use the same version and actual release date in both languages.
3. Document Forgejo compatibility, environment variable changes, migrations,
   upgrade steps, and rollback limitations.
4. Review, commit, merge, and push to `origin/main`.

Changelog format (replace the date and content with the actual release details):

```markdown
## [Unreleased]

## [0.1.0] - YYYY-MM-DD

### Added
- Initial release.

### Compatibility
- Tested against Forgejo 16.0.2.

### Upgrade notes
- Back up PostgreSQL and credential encryption secrets before upgrading.
- Describe required migrations and rollback compatibility here.
```

Version/lockfile updates require explicit `--prepare --apply`. The script never
commits preparation changes for you. `--publish` only publishes committed metadata;
it does not implicitly bump a version.

### Initial v0.1.0 preparation checklist

The prepared release targets Forgejo 16.0.2 and does not include PR #3. Project,
lockfile, and frontend versions already match `0.1.0`; no version bump is needed.
The prepared changelog date is `2026-09-08`; update both languages if publishing later.

- [ ] Review both changelogs, especially compatibility and upgrade notes.
- [ ] Review `scripts/release.py`, its tests, both Actions workflows, and the image override.
- [ ] Confirm Actions/package write permissions; arrange public GHCR access after publication.
- [ ] Inspect the untracked nested `forgejo-mcp/` checkout locally. Preserve it outside this
      working tree if needed; do not add it to the release commit or delete it blindly.
- [ ] Run `python3 scripts/release.py 0.1.0 --check` and the test suite.
- [ ] Commit the reviewed release files and merge/push them to `main` using your review policy.
      Include both changelogs, `scripts/release.py`, `tests/unit/test_release_script.py`,
      `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `deploy/compose.image.yaml`,
      both releasing guides and both READMEs. Do not use `git add .` without reviewing untracked files.
- [ ] Confirm a clean working tree and local `main` matching remote `main`.
- [ ] Preview, then run `--publish` only when ready to publish publicly.
- [ ] Wait for the Release workflow, verify the GHCR digest/public access, and test an anonymous pull.

## 2. Preview, then explicitly publish

From the repository root:

```bash
python3 scripts/release.py 0.1.0
# Only after verifying the version, commit, and notes:
python3 scripts/release.py 0.1.0 --publish
```

The default mode only validates and previews; it does not create or push a tag.
Checks include matching project/lockfile versions, a nonempty release changelog,
a clean working tree (including untracked files), being on `main`, HEAD matching
the current remote main, and the tag not existing locally or remotely.
The script reads the remote with `git ls-remote`; it does not automatically fetch,
merge, or push a branch.

If there are untracked directories, inspect them first and move them outside the
repository or ignore them according to project policy. Do not run `git clean`
just to bypass the check.

To validate release metadata only (not a guarantee that publication is safe):

```bash
python3 scripts/release.py v0.1.0 --check
```

## 3. GitHub Actions workflow

Pushing a `v*` tag or using **Run workflow** starts `.github/workflows/release.yml`, which:

1. Validates the stable tag and metadata, and verifies the commit is included in remote main.
2. Reuses CI: Python lint/typechecking/PostgreSQL tests, frontend checks and build,
   and the existing full Docker E2E. Compatibility coverage depends on the CI
   configuration at that commit; it is not currently a multi-version matrix.
3. For manual runs, creates or verifies the tag at the tested commit. Checks that no
   GitHub Release, including a draft, exists for that tag, then creates a draft to reserve it.
4. Builds and pushes the versioned image with OCI version, revision, and source
   labels, provenance, and an SBOM.
5. Adds the image digest to the notes and publishes the GitHub Release.

Any test failure blocks the publish job. Pushing a tag does not mean publication
has completed; check the Actions result.

## Using a published image

The following instructions apply only after the specified version has actually
been published. Use that release's deployment files and upgrade instructions;
do not arbitrarily mix newer Compose files with older images. Example image path:

```text
ghcr.io/kepatrick/forgejo-mcp:0.1.0
```

The existing `deploy/compose.yaml` defaults to a local build. The included
`deploy/compose.image.yaml` selects `ghcr.io/kepatrick/forgejo-mcp:0.1.0` by default.
To select another published version, fork image, or digest, set `FMCP_IMAGE` in
`deploy/.env` (or export it in your shell):

```dotenv
FMCP_IMAGE=ghcr.io/kepatrick/forgejo-mcp:0.1.0
```

Retain your existing secrets/environment configuration and explicitly disable local builds:

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml -f deploy/compose.image.yaml pull app
docker compose --env-file deploy/.env -f deploy/compose.yaml -f deploy/compose.image.yaml up -d --no-build
```

For production, replace the image reference with `ghcr.io/...@sha256:...` from the
release notes. Database migrations are not necessarily backward compatible;
rollback may require more than selecting an older image. Back up the database
and credential encryption secrets before upgrading, and read the release's
rollback limitations.

## Failures and retries

**Do not force-push, move Git tags, or overwrite published images.**

- Local tag push fails: the script retains the annotated tag because a network
  error does not prove the remote rejected it. Check
  `git ls-remote origin refs/tags/vX.Y.Z` and Actions first. After confirming the
  remote does not have that tag, manually run `git push origin refs/tags/vX.Y.Z`;
  there is no need to recreate the tag.
- Validation or CI fails before a draft is created: rerun for transient failures.
  If code changes are needed, use a new commit/version rather than moving the
  existing tag to the fix.
- A draft exists but the image has not been pushed: the workflow refuses a direct
  rerun. Only after manually confirming that the versioned image **does not exist**
  in GHCR, delete the draft (not the Git tag) and rerun.
- The image was pushed but publishing the Release failed: do not rebuild the image.
  Verify its revision against the tag commit, obtain the digest using
  `docker buildx imagetools inspect ghcr.io/<owner>/<repo>:X.Y.Z`, add the image and
  digest to the existing draft, then publish that draft manually.
- The Release already exists: the script/workflow refuses duplicate publication.
  Ship fixes in a new patch version.
