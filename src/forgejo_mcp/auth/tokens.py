import hashlib
import secrets


def new_token() -> str:
    """Return a URL-safe token with at least 256 bits of entropy."""
    return secrets.token_urlsafe(32)


def new_mcp_token() -> str:
    """Return a recognizable MCP bearer token with 256 bits of random entropy."""
    return f"fmcp_{secrets.token_urlsafe(32)}"


def new_oauth_refresh_token() -> str:
    """Return an opaque, recognizable OAuth refresh token."""
    return f"fmcp_rt_{secrets.token_urlsafe(32)}"


def new_oauth_code() -> str:
    """Return a single-use OAuth authorization code with 256 bits of entropy."""
    return f"fmcp_ac_{secrets.token_urlsafe(32)}"


def new_oauth_interaction_token() -> str:
    """Return an opaque handle for the browser login and consent interaction."""
    return f"fmcp_oi_{secrets.token_urlsafe(32)}"


def mcp_token_prefix(token: str) -> str:
    """Return a non-secret display prefix without exposing the complete token."""
    return token[:13]


def hash_token(token: str) -> str:
    """Hash a high-entropy token before persistence."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
