#!/usr/bin/env python3
"""Prepare or publish a stable release. Defaults to a read-only preview."""

import argparse
import difflib
import json
import re
import subprocess
import sys
import tomllib
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.compile(r"v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")


class ReleaseError(Exception):
    pass


def normalize_version(value: str) -> str:
    if not VERSION.fullmatch(value):
        raise ReleaseError("use a stable version such as 0.1.0 or v0.1.0")
    return value.removeprefix("v")


def release_notes(changelog: str, version: str) -> str:
    heading = re.search(
        rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}\s*$",
        changelog,
        re.MULTILINE,
    )
    if heading is None:
        raise ReleaseError(f"CHANGELOG.md needs a dated '## [{version}] - YYYY-MM-DD' section")
    remainder = changelog[heading.end() :]
    notes = re.split(r"^## ", remainder, maxsplit=1, flags=re.MULTILINE)[0].strip()
    if not notes:
        raise ReleaseError("the release changelog section must not be empty")
    return notes + "\n"


def validate_metadata(root: Path, version: str) -> str:
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    if project["version"] != version:
        raise ReleaseError(f"pyproject.toml version is {project['version']}, expected {version}")
    lock = tomllib.loads((root / "uv.lock").read_text())
    packages = [p for p in lock["package"] if p["name"] == project["name"]]
    if len(packages) != 1 or packages[0]["version"] != version:
        raise ReleaseError("uv.lock project version differs; run uv lock and commit the result")
    english = release_notes((root / "CHANGELOG.md").read_text(encoding="utf-8"), version)
    chinese_path = root / "CHANGELOG.zh-TW.md"
    if not chinese_path.is_file():
        raise ReleaseError("CHANGELOG.zh-TW.md is required for bilingual release notes")
    try:
        chinese = release_notes(chinese_path.read_text(encoding="utf-8"), version)
    except ReleaseError as error:
        raise ReleaseError(f"CHANGELOG.zh-TW.md: {error}") from error
    return f"## English\n\n{english}\n## 繁體中文\n\n{chinese}"


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise ReleaseError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def validate_git(root: Path, tag: str) -> str:
    if git(root, "status", "--porcelain", "--untracked-files=all"):
        raise ReleaseError("working tree must be clean, including untracked files")
    if git(root, "branch", "--show-current") != "main":
        raise ReleaseError("release from main, not a feature branch or detached HEAD")
    if git(root, "tag", "--list", tag):
        raise ReleaseError(f"local tag {tag} already exists; release tags must not be overwritten")
    commit = git(root, "rev-parse", "HEAD")
    refs = git(root, "ls-remote", "origin", "refs/heads/main", f"refs/tags/{tag}")
    remote = dict(line.split()[::-1] for line in refs.splitlines())
    if f"refs/tags/{tag}" in remote:
        raise ReleaseError(f"remote tag {tag} already exists")
    if remote.get("refs/heads/main") != commit:
        raise ReleaseError("HEAD must equal origin's current main; merge/push your changes first")
    return commit


def next_version(current: str, choice: str) -> str:
    current = normalize_version(current)
    parts = [int(part) for part in current.split(".")]
    if choice in {"major", "minor", "patch"}:
        index = {"major": 0, "minor": 1, "patch": 2}[choice]
        parts[index] += 1
        parts[index + 1 :] = [0] * (2 - index)
        return ".".join(map(str, parts))
    target = current if choice == "current" else normalize_version(choice)
    if tuple(map(int, target.split("."))) < tuple(parts):
        raise ReleaseError("cannot prepare a version older than the current project version")
    return target


def replace_version_field(text: str, old: str, new: str) -> str:
    updated, count = re.subn(
        rf'(?m)^(version\s*=\s*"){re.escape(old)}("\s*)$',
        lambda match: f"{match[1]}{new}{match[2]}",
        text,
    )
    if count != 1:
        raise ReleaseError("expected exactly one matching version field in the project block")
    return updated


def prepare_changelog(text: str, version: str, release_date: str) -> str:
    headings = list(re.finditer(r"(?m)^## \[Unreleased\][ \t]*$", text))
    if len(headings) != 1:
        raise ReleaseError("each changelog needs exactly one [Unreleased] section")
    heading = headings[0]
    body = text[heading.end() :]
    unreleased = re.split(r"(?m)^## ", body, maxsplit=1)[0].strip()
    if re.search(rf"(?m)^## \[{re.escape(version)}\]", text):
        if unreleased:
            raise ReleaseError(
                "target changelog section already exists but Unreleased is not empty"
            )
        release_notes(text, version)
        return text  # Already prepared; preserve the reviewed date and release notes.
    if not unreleased or not any(
        line.strip() and not line.lstrip().startswith("#") for line in unreleased.splitlines()
    ):
        raise ReleaseError("write nonempty English and Chinese Unreleased notes before preparing")
    return text[: heading.end()] + f"\n\n## [{version}] - {release_date}" + body


def preparation_plan(root: Path, choice: str, release_date: str) -> tuple[str, dict[Path, str]]:
    if date.fromisoformat(release_date).isoformat() != release_date:
        raise ReleaseError("release date must use YYYY-MM-DD")
    project_path = root / "pyproject.toml"
    project_text = project_path.read_text(encoding="utf-8")
    project = tomllib.loads(project_text)["project"]
    current = normalize_version(project["version"])
    target = next_version(current, choice)
    block = re.search(r"(?ms)^\[project\]\n.*?(?=^\[|\Z)", project_text)
    if block is None:
        raise ReleaseError("missing [project] table")
    changes = {
        project_path: project_text[: block.start()]
        + replace_version_field(block[0], current, target)
        + project_text[block.end() :]
    }
    # Change only the root package identity; keep every dependency resolution intact.
    lock_path = root / "uv.lock"
    blocks = re.split(r"(?m)(?=^\[\[package\]\])", lock_path.read_text(encoding="utf-8"))
    matches = 0
    for index, entry in enumerate(blocks):
        if not entry.startswith("[[package]]"):
            continue
        package = tomllib.loads(entry)["package"][0]
        if package["name"] == project["name"]:
            if package["version"] != current:
                raise ReleaseError("uv.lock root version differs from pyproject.toml")
            blocks[index] = replace_version_field(entry, current, target)
            matches += 1
    if matches != 1:
        raise ReleaseError("expected exactly one root package in uv.lock")
    changes[lock_path] = "".join(blocks)
    for name in ("package.json", "package-lock.json"):
        path = root / "frontend" / name
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload["version"] != current:
            raise ReleaseError(f"frontend/{name} version differs from pyproject.toml")
        payload["version"] = target
        if name == "package-lock.json":
            if payload["packages"][""]["version"] != current:
                raise ReleaseError("frontend lockfile root package version is inconsistent")
            payload["packages"][""]["version"] = target
        changes[path] = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    image_path = root / "deploy/compose.image.yaml"
    image_text = image_path.read_text(encoding="utf-8")
    pattern = rf"(image: \$\{{FMCP_IMAGE:-ghcr\.io/[^\s}}]+:){re.escape(current)}(\}})"
    image_text, count = re.subn(pattern, lambda m: f"{m[1]}{target}{m[2]}", image_text)
    if count != 1:
        raise ReleaseError("Compose default image version differs from pyproject.toml")
    changes[image_path] = image_text
    for name in ("CHANGELOG.md", "CHANGELOG.zh-TW.md"):
        path = root / name
        try:
            changes[path] = prepare_changelog(
                path.read_text(encoding="utf-8"), target, release_date
            )
        except ReleaseError as error:
            raise ReleaseError(f"{name}: {error}") from error
    return target, changes


def prepare(root: Path, choice: str, release_date: str, *, apply: bool) -> None:
    if apply and git(root, "status", "--porcelain", "--untracked-files=all"):
        raise ReleaseError(
            "commit reviewed changes first; preparation requires a clean working tree"
        )
    version, changes = preparation_plan(root, choice, release_date)
    originals = {path: path.read_text(encoding="utf-8") for path in changes}
    changed = {path: text for path, text in changes.items() if text != originals[path]}
    print(f"Prepare v{version}: {len(changed)} files change", flush=True)
    for path, text in changed.items():
        name = str(path.relative_to(root))
        print(
            "".join(
                difflib.unified_diff(
                    originals[path].splitlines(keepends=True),
                    text.splitlines(keepends=True),
                    fromfile=name,
                    tofile=name,
                )
            ),
            end="",
        )
    if not apply:
        print("Preview only. Repeat with --prepare --apply to update local files.")
        return
    try:
        for path, text in changed.items():
            path.write_text(text, encoding="utf-8")
        validate_metadata(root, version)
    except Exception:
        for path in changed:
            path.write_text(originals[path], encoding="utf-8")
        raise
    print("Prepared locally. Review the diff, commit and merge to main, then publish.")
    print("No branch, commit, tag, or remote publication was created.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "version", help="X.Y.Z; with --prepare also patch, minor, major, or current"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--publish", action="store_true", help="create and push an annotated tag")
    mode.add_argument("--check", action="store_true", help="check release metadata only (for CI)")
    mode.add_argument(
        "--prepare", action="store_true", help="preview version and changelog updates"
    )
    parser.add_argument(
        "--apply", action="store_true", help="write local updates (requires --prepare)"
    )
    parser.add_argument(
        "--date", help="release date YYYY-MM-DD (requires --prepare; default: today)"
    )
    parser.add_argument("--notes-file", type=Path, help="write release notes (requires --check)")
    args = parser.parse_args(argv)
    if args.notes_file and not args.check:
        parser.error("--notes-file requires --check")
    if (args.apply or args.date) and not args.prepare:
        parser.error("--apply and --date require --prepare")
    try:
        if args.prepare:
            prepare(ROOT, args.version, args.date or date.today().isoformat(), apply=args.apply)
            return 0
        version = normalize_version(args.version)
        tag = f"v{version}"
        notes = validate_metadata(ROOT, version)
        if args.check:
            if args.notes_file:
                args.notes_file.write_text(notes, encoding="utf-8")
            print(f"Release metadata valid: {tag}")
            return 0
        commit = validate_git(ROOT, tag)
        print(f"Release: {tag}\nCommit:  {commit}\nRemote:  origin\n\n{notes}", flush=True)
        if not args.publish:
            print("Preview only. No tag created or pushed. Repeat with --publish to release.")
            return 0
        git(ROOT, "tag", "-a", tag, commit, "-m", f"Release {tag}")
        try:
            git(ROOT, "push", "origin", f"refs/tags/{tag}:refs/tags/{tag}")
        except ReleaseError as error:
            raise ReleaseError(
                f"{error}\nLocal tag {tag} was retained. Check the remote before retrying; "
                "do not force-push or move a published tag."
            ) from error
        print(f"Pushed {tag}. GitHub Actions will test, publish the image, and create the release.")
        return 0
    except (ReleaseError, OSError, KeyError, ValueError) as error:
        print(f"Release aborted: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
