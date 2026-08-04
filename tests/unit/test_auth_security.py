import pytest

from forgejo_mcp.auth.passwords import (
    hash_password,
    normalize_username,
    validate_password,
    verify_password,
)
from forgejo_mcp.auth.tokens import hash_token, new_token


def test_password_hash_round_trip() -> None:
    encoded = hash_password("a-long-bootstrap-password")

    assert encoded != "a-long-bootstrap-password"
    assert verify_password(encoded, "a-long-bootstrap-password")
    assert not verify_password(encoded, "wrong-password")


def test_short_password_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least 12"):
        validate_password("too-short")


def test_username_normalization() -> None:
    assert normalize_username("  Ａdmin  ") == "admin"


def test_tokens_are_random_and_hashable() -> None:
    first = new_token()
    second = new_token()

    assert first != second
    assert len(hash_token(first)) == 64
    assert hash_token(first) != first
