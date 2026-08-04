import hashlib
import secrets


def new_token() -> str:
    """Return a URL-safe token with at least 256 bits of entropy."""
    return secrets.token_urlsafe(32)


def new_mcp_token() -> str:
    """Return a recognizable MCP bearer token with 256 bits of random entropy."""
    return f"fmcp_{secrets.token_urlsafe(32)}"


def mcp_token_prefix(token: str) -> str:
    """Return a non-secret display prefix without exposing the complete token."""
    return token[:13]


def hash_token(token: str) -> str:
    """Hash a high-entropy token before persistence."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
