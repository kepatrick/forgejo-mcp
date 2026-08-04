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
