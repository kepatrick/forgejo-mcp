import hashlib

from forgejo_mcp.audit.redaction import extract_target, redact_arguments, summarize_result


def test_redaction_is_recursive_case_insensitive_and_pre_persistence() -> None:
    result = redact_arguments(
        {
            "owner": "patrick",
            "Authorization": "Bearer secret",
            "nested": {
                "api_token": "fmcp_secret",
                "PASSWORD": "password",
                "safe": "visible",
            },
        }
    )

    assert result.value == {
        "owner": "patrick",
        "Authorization": "[REDACTED]",
        "nested": {
            "api_token": "[REDACTED]",
            "PASSWORD": "[REDACTED]",
            "safe": "visible",
        },
    }
    assert "fmcp_secret" not in repr(result.value)
    assert result.truncated is False


def test_migration_credentials_are_redacted_but_upstream_remains_auditable() -> None:
    result = redact_arguments(
        {
            "clone_addr": "https://github.com/actions/checkout.git",
            "auth_username": "mirror-bot",
            "auth_password": "password-value",
            "auth_token": "token-value",
        }
    )

    assert result.value == {
        "clone_addr": "https://github.com/actions/checkout.git",
        "auth_username": "mirror-bot",
        "auth_password": "[REDACTED]",
        "auth_token": "[REDACTED]",
    }
    assert "password-value" not in repr(result.value)
    assert "token-value" not in repr(result.value)


def test_adverse_audit_credentials_are_redacted() -> None:
    for value, secret in (
        ("1234:5678@host/r", "5678"),
        ("git clone bot:ghp_secret@example.test:o/r.git", "ghp_secret"),
        ("(bot:ghp_leak@host)", "ghp_leak"),
        ('"bot:ghp_leak@host"', "ghp_leak"),
        ("see bot:ghp_leak@host.", "ghp_leak"),
        ("bot:pa/ss@host/r", "pa/ss"),
    ):
        assert secret not in repr(redact_arguments({"path": value}).value)
        assert secret not in repr(extract_target({"path": value}))


def test_credentials_embedded_in_remote_url_are_redacted_before_persistence() -> None:
    result = redact_arguments(
        {
            "clone_addr": "https://mirror-bot:super-secret@example.test/repo.git",
            "description": "mirror from ssh://deploy:private-value@example.test/repo.git",
            "multiple_at": "https://user@nested-secret@example.test/repo.git",
            "without_scheme": "mirror-bot:schemeless-secret@example.test/repo.git",
            "slash_prefixed": "/mirror-bot:slash-secret@example.test/repo.git",
            "remote_with_at": "mirror-bot:part@credential@example.test/repo.git",
            "many_at": f"mirror-bot:{'part@' * 256}many-at-secret@example.test/repo.git",
            "ordinary_text": "meet at 12:30@office",
            "nested_path": "dir/bot:ghp_leak@host/file",
            "without_trailing_slash": "user:secret@host",
            "ordinary_path": "12:30@office/room",
        }
    )

    assert result.value == {
        "clone_addr": "https://[REDACTED]@example.test/repo.git",
        "description": "mirror from ssh://[REDACTED]@example.test/repo.git",
        "multiple_at": "https://[REDACTED]@example.test/repo.git",
        "without_scheme": "[REDACTED]@example.test/repo.git",
        "slash_prefixed": "/[REDACTED]@example.test/repo.git",
        "remote_with_at": "[REDACTED]@example.test/repo.git",
        "many_at": "[REDACTED]@example.test/repo.git",
        "ordinary_text": "meet at 12:30@office",
        "nested_path": "dir/[REDACTED]@host/file",
        "without_trailing_slash": "[REDACTED]@host",
        "ordinary_path": "12:30@office/room",
    }
    assert "super-secret" not in repr(result.value)
    assert "private-value" not in repr(result.value)
    assert "nested-secret" not in repr(result.value)
    assert "schemeless-secret" not in repr(result.value)
    assert "slash-secret" not in repr(result.value)
    assert "part@credential" not in repr(result.value)
    assert "many-at-secret" not in repr(result.value)
    assert "ghp_leak" not in repr(result.value)
    assert "user:secret" not in repr(result.value)


def test_additional_credential_key_names_are_redacted_without_hiding_paths() -> None:
    result = redact_arguments(
        {
            "api_key": "api-secret",
            "private_key": "private-secret",
            "apiKey": "camel-api-secret",
            "privateKey": "camel-private-secret",
            "passwd": "password-secret",
            "path": "src/private_key_loader.py",
        }
    )

    assert result.value == {
        "api_key": "[REDACTED]",
        "private_key": "[REDACTED]",
        "apiKey": "[REDACTED]",
        "privateKey": "[REDACTED]",
        "passwd": "[REDACTED]",
        "path": "src/private_key_loader.py",
    }


def test_commit_change_content_is_replaced_by_size_and_digest() -> None:
    content = "FORGEJO_TOKEN=must-not-be-persisted\n"
    result = redact_arguments(
        {
            "owner": "patrick",
            "changes": [
                {"operation": "create", "path": ".env", "content": content},
                {"operation": "delete", "path": "old.txt"},
            ],
        }
    )

    assert result.value["changes"][0]["content"] == {
        "redacted": True,
        "bytes": len(content.encode("utf-8")),
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }
    assert "must-not-be-persisted" not in repr(result.value)
    assert result.truncated is True


def test_redaction_truncates_large_text_and_extracts_safe_target() -> None:
    arguments = {
        "owner": "patrick",
        "repo": "forgejo-mcp",
        "number": 42,
        "path": "README.md",
        "body": "x" * 20,
        "ignored": "value",
    }
    result = redact_arguments(arguments, text_limit=8)

    assert result.value["body"] == "xxxxxxxx…[TRUNCATED]"
    assert result.truncated is True
    assert extract_target(arguments) == {
        "owner": "patrick",
        "repo": "forgejo-mcp",
        "number": 42,
        "path": "README.md",
    }


def test_extract_target_includes_action_identifiers() -> None:
    assert extract_target(
        {
            "owner": "patrick",
            "repo": "forgejo-mcp",
            "run_id": 42,
            "job_id": 51,
            "attempt": 2,
            "workflow_id": "ci.yml",
        }
    ) == {
        "owner": "patrick",
        "repo": "forgejo-mcp",
        "run_id": 42,
        "job_id": 51,
        "attempt": 2,
        "workflow_id": "ci.yml",
    }


def test_extract_target_redacts_credentials_and_bounds_text() -> None:
    marker = "must-not-reach-target"
    target = extract_target(
        {
            "repo": f"https://mirror:{marker}@example.test/repo.git",
            "ref": f"/mirror:part@{marker}@example.test/repo.git",
            "path": "x" * 600,
        }
    )

    assert target["repo"] == "https://[REDACTED]@example.test/repo.git"
    assert target["ref"] == "/[REDACTED]@example.test/repo.git"
    assert marker not in repr(target)
    assert target["path"] == f"{'x' * 512}…[TRUNCATED]"


def test_extract_target_replays_original_redaction_witnesses() -> None:
    target = extract_target(
        {
            "repo": "dir/bot:ghp_leak@host/file",
            "ref": "user:secret@host",
            "path": "12:30@office/room",
        }
    )

    assert target == {
        "repo": "dir/[REDACTED]@host/file",
        "ref": "[REDACTED]@host",
        "path": "12:30@office/room",
    }


def test_result_summary_counts_git_tree_entries() -> None:
    summary, truncated = summarize_result({"entries": [{"path": "README.md"}], "truncated": False})

    assert summary["item_count"] == 1
    assert truncated is False


def test_result_summary_does_not_persist_content() -> None:
    summary, truncated = summarize_result(
        {
            "items": [{"id": 1}, {"id": 2}],
            "content": "private file contents",
            "files_truncated": True,
        }
    )

    assert summary["item_count"] == 2
    assert summary["content_bytes"] == len("private file contents")
    assert len(summary["content_sha256"]) == 64
    assert "private file contents" not in repr(summary)
    assert truncated is True
