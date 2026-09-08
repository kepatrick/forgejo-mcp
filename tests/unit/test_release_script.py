"""Exercise release safety using temporary local Git repositories only."""

import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType

import pytest


@pytest.fixture
def release() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / "release.py"
    spec = importlib.util.spec_from_file_location("release_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def command(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


@pytest.fixture
def repo(tmp_path: Path, release: ModuleType, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "work"
    root.mkdir()
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    command(root, "init", "-b", "main")
    command(root, "config", "user.name", "Release Test")
    command(root, "config", "user.email", "release@example.test")
    command(root, "config", "commit.gpgsign", "false")
    command(root, "config", "tag.gpgsign", "false")
    command(root, "remote", "add", "origin", str(remote))
    (root / "pyproject.toml").write_text('[project]\nname = "forgejo-mcp"\nversion = "0.1.0"\n')
    (root / "uv.lock").write_text('[[package]]\nname = "forgejo-mcp"\nversion = "0.1.0"\n')
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n## [0.1.0] - 2026-01-01\n\n"
        "### Added\n- First release.\n\n## [0.0.1] - 2025-01-01\n\n- Old notes.\n"
    )
    (root / "CHANGELOG.zh-TW.md").write_text(
        "# 變更紀錄\n\n## [Unreleased]\n\n## [0.1.0] - 2026-01-01\n\n### 新增\n- 第一個版本。\n",
        encoding="utf-8",
    )
    (root / "frontend").mkdir()
    (root / "frontend/package.json").write_text(
        json.dumps({"name": "dashboard", "version": "0.1.0"}, indent=2) + "\n"
    )
    (root / "frontend/package-lock.json").write_text(
        json.dumps({"version": "0.1.0", "packages": {"": {"version": "0.1.0"}}}, indent=2) + "\n"
    )
    (root / "deploy").mkdir()
    (root / "deploy/compose.image.yaml").write_text(
        "services:\n  app:\n    image: ${FMCP_IMAGE:-ghcr.io/example/forgejo-mcp:0.1.0}\n"
    )
    command(root, "add", ".")
    command(root, "commit", "-m", "Initial release metadata")
    command(root, "push", "origin", "main")
    monkeypatch.setattr(release, "ROOT", root)
    return root


@pytest.mark.parametrize("value", ["1.2.3", "v1.2.3", "0.0.0"])
def test_stable_versions(release: ModuleType, value: str) -> None:
    assert release.normalize_version(value) == value.removeprefix("v")


@pytest.mark.parametrize("value", ["01.2.3", "v1.2", "1.2.3-rc.1", "1.2.3+build", "v1.2.3\n"])
def test_invalid_versions(release: ModuleType, value: str) -> None:
    with pytest.raises(release.ReleaseError):
        release.normalize_version(value)


def test_preview_has_no_git_writes(repo: Path, release: ModuleType) -> None:
    assert release.main(["0.1.0"]) == 0
    assert command(repo, "tag", "--list") == ""
    assert command(repo, "ls-remote", "origin", "refs/tags/*") == ""


def test_publish_annotated_tag(repo: Path, release: ModuleType) -> None:
    assert release.main(["v0.1.0", "--publish"]) == 0
    assert command(repo, "cat-file", "-t", "v0.1.0") == "tag"
    assert command(repo, "rev-parse", "v0.1.0^{}") == command(repo, "rev-parse", "HEAD")
    assert "refs/tags/v0.1.0" in command(repo, "ls-remote", "origin", "refs/tags/*")
    assert release.main(["0.1.0", "--publish"]) == 1


def test_metadata_check_can_export_notes_without_clean_tree(
    repo: Path, release: ModuleType, tmp_path: Path
) -> None:
    (repo / "untracked").touch()
    notes = tmp_path / "notes.md"
    assert release.main(["0.1.0", "--check", "--notes-file", str(notes)]) == 0
    assert notes.read_text(encoding="utf-8") == (
        "## English\n\n### Added\n- First release.\n\n## 繁體中文\n\n### 新增\n- 第一個版本。\n"
    )


@pytest.mark.parametrize("file", ["pyproject.toml", "uv.lock"])
def test_version_mismatch_rejected(repo: Path, release: ModuleType, file: str) -> None:
    path = repo / file
    path.write_text(path.read_text().replace('version = "0.1.0"', 'version = "0.2.0"'))
    assert release.main(["0.1.0", "--check"]) == 1


@pytest.mark.parametrize("notes", ["## [Unreleased]\n- Something.\n", "## [0.1.0] - 2026-01-01\n"])
def test_missing_release_notes_rejected(repo: Path, release: ModuleType, notes: str) -> None:
    (repo / "CHANGELOG.md").write_text(notes)
    assert release.main(["0.1.0", "--check"]) == 1


@pytest.mark.parametrize("content", [None, "## [Unreleased]\n- 尚未發布。\n"])
def test_missing_chinese_release_rejected(
    repo: Path, release: ModuleType, content: str | None
) -> None:
    path = repo / "CHANGELOG.zh-TW.md"
    if content is None:
        path.unlink()
    else:
        path.write_text(content, encoding="utf-8")
    assert release.main(["0.1.0", "--check"]) == 1


def test_dirty_tree_rejected(repo: Path, release: ModuleType) -> None:
    (repo / "untracked").touch()
    assert release.main(["0.1.0", "--publish"]) == 1
    assert command(repo, "tag", "--list") == ""


def test_feature_branch_rejected(repo: Path, release: ModuleType) -> None:
    command(repo, "checkout", "-b", "feature/test")
    assert release.main(["0.1.0", "--publish"]) == 1


def test_unpushed_commit_rejected(repo: Path, release: ModuleType) -> None:
    command(repo, "commit", "--allow-empty", "-m", "Unpushed")
    assert release.main(["0.1.0", "--publish"]) == 1


def test_existing_remote_tag_rejected(repo: Path, release: ModuleType) -> None:
    command(repo, "tag", "v0.1.0")
    command(repo, "push", "origin", "v0.1.0")
    command(repo, "tag", "-d", "v0.1.0")
    assert release.main(["0.1.0", "--publish"]) == 1
    assert command(repo, "tag", "--list") == ""


def test_failed_push_retains_tag(
    repo: Path, release: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = release.git

    def failing_push(root: Path, *args: str) -> str:
        if args[0] == "push":
            raise release.ReleaseError("simulated push failure")
        return str(original(root, *args))

    monkeypatch.setattr(release, "git", failing_push)
    assert release.main(["0.1.0", "--publish"]) == 1
    assert command(repo, "tag", "--list") == "v0.1.0"
    assert command(repo, "ls-remote", "origin", "refs/tags/*") == ""


@pytest.mark.parametrize(
    ("current", "choice", "expected"),
    [
        ("0.1.9", "patch", "0.1.10"),
        ("0.1.9", "minor", "0.2.0"),
        ("0.1.9", "major", "1.0.0"),
        ("0.1.9", "v2.3.4", "2.3.4"),
        ("0.1.9", "current", "0.1.9"),
    ],
)
def test_next_version(release: ModuleType, current: str, choice: str, expected: str) -> None:
    assert release.next_version(current, choice) == expected


def test_preparation_rejects_downgrade(release: ModuleType) -> None:
    with pytest.raises(release.ReleaseError):
        release.next_version("1.2.0", "1.1.9")


def add_unreleased(repo: Path) -> None:
    for name, note in [("CHANGELOG.md", "Fix a bug."), ("CHANGELOG.zh-TW.md", "修正錯誤。")]:
        path = repo / name
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "## [Unreleased]", f"## [Unreleased]\n\n- {note}"
            ),
            encoding="utf-8",
        )
    command(repo, "add", "CHANGELOG.md", "CHANGELOG.zh-TW.md")
    command(repo, "commit", "-m", "Document unreleased changes")


def test_preparation_preview_and_apply(repo: Path, release: ModuleType) -> None:
    add_unreleased(repo)
    before = command(repo, "rev-parse", "HEAD")
    args = ["patch", "--prepare", "--date", "2026-02-01"]
    assert release.main(args) == 0
    assert command(repo, "status", "--porcelain") == ""
    assert release.main([*args, "--apply"]) == 0
    assert release.main(["0.1.1", "--check"]) == 0
    assert command(repo, "rev-parse", "HEAD") == before
    assert command(repo, "tag", "--list") == ""
    assert command(repo, "ls-remote", "origin", "refs/tags/*") == ""
    assert len(command(repo, "diff", "--name-only").splitlines()) == 7
    assert "0.1.1}" in (repo / "deploy/compose.image.yaml").read_text()
    for name in ("package.json", "package-lock.json"):
        payload = json.loads((repo / "frontend" / name).read_text())
        assert payload["version"] == "0.1.1"
        if "packages" in payload:
            assert payload["packages"][""]["version"] == "0.1.1"
    for name in ("CHANGELOG.md", "CHANGELOG.zh-TW.md"):
        content = (repo / name).read_text(encoding="utf-8")
        assert "## [Unreleased]\n\n## [0.1.1] - 2026-02-01" in content
        assert "## [0.1.0] - 2026-01-01" in content


def test_preparation_requires_notes_in_both_languages(repo: Path, release: ModuleType) -> None:
    path = repo / "CHANGELOG.md"
    path.write_text(path.read_text().replace("## [Unreleased]", "## [Unreleased]\n\n- Fix."))
    command(repo, "add", "CHANGELOG.md")
    command(repo, "commit", "-m", "English notes only")
    assert release.main(["minor", "--prepare", "--apply"]) == 1
    assert command(repo, "status", "--porcelain") == ""


def test_preparation_refuses_dirty_apply(repo: Path, release: ModuleType) -> None:
    add_unreleased(repo)
    (repo / "untracked").touch()
    assert release.main(["patch", "--prepare", "--apply"]) == 1
    assert command(repo, "diff") == ""


def test_preparation_current_is_idempotent(repo: Path, release: ModuleType) -> None:
    assert release.main(["current", "--prepare", "--apply"]) == 0
    assert command(repo, "status", "--porcelain") == ""


def test_preparation_does_not_append_to_existing_release(repo: Path, release: ModuleType) -> None:
    add_unreleased(repo)
    assert release.main(["current", "--prepare", "--apply"]) == 1
    assert command(repo, "status", "--porcelain") == ""


def test_preparation_rolls_back_validation_failure(
    repo: Path, release: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_unreleased(repo)

    def fail(*args: object) -> str:
        raise release.ReleaseError("simulated validation failure")

    monkeypatch.setattr(release, "validate_metadata", fail)
    assert release.main(["patch", "--prepare", "--apply"]) == 1
    assert command(repo, "status", "--porcelain") == ""


def test_preparation_preserves_dependency_versions(repo: Path, release: ModuleType) -> None:
    add_unreleased(repo)
    path = repo / "uv.lock"
    path.write_text(path.read_text() + '\n[[package]]\nname = "dependency"\nversion = "0.1.0"\n')
    command(repo, "add", "uv.lock")
    command(repo, "commit", "-m", "Add dependency fixture")
    assert release.main(["minor", "--prepare", "--apply"]) == 0
    assert 'name = "dependency"\nversion = "0.1.0"' in path.read_text()


@pytest.mark.parametrize("value", ["20260201", "2026-02-30", "not-a-date"])
def test_preparation_rejects_invalid_date(repo: Path, release: ModuleType, value: str) -> None:
    add_unreleased(repo)
    assert release.main(["patch", "--prepare", "--apply", "--date", value]) == 1
    assert command(repo, "status", "--porcelain") == ""


@pytest.mark.parametrize("args", [["patch", "--apply"], ["patch", "--prepare", "--publish"]])
def test_incompatible_modes_rejected(release: ModuleType, args: list[str]) -> None:
    with pytest.raises(SystemExit):
        release.main(args)
