import re

from forgejo_mcp.auth.mcp_bearer import valid_mcp_token_format
from forgejo_mcp.auth.tokens import hash_token, mcp_token_prefix, new_mcp_token


def test_mcp_token_has_recognizable_prefix_and_256_bits_of_entropy() -> None:
    first = new_mcp_token()
    second = new_mcp_token()

    assert first.startswith("fmcp_")
    assert re.fullmatch(r"fmcp_[A-Za-z0-9_-]{43}", first)
    assert first != second


def test_mcp_token_storage_values_do_not_reveal_plaintext() -> None:
    token = new_mcp_token()

    assert mcp_token_prefix(token) == token[:13]
    assert len(hash_token(token)) == 64
    assert token not in hash_token(token)


def test_mcp_bearer_format_is_strict() -> None:
    token = new_mcp_token()

    assert valid_mcp_token_format(token)
    assert not valid_mcp_token_format(f" {token}")
    assert not valid_mcp_token_format(token.removeprefix("fmcp_"))
    assert not valid_mcp_token_format(f"{token}extra")
