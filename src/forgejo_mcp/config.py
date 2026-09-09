from functools import lru_cache
from ipaddress import ip_network
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated runtime settings."""

    model_config = SettingsConfigDict(
        env_prefix="FMCP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+asyncpg://forgejo_mcp:change-me@localhost:5432/forgejo_mcp"
    database_url_file: Path | None = None
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    bootstrap_admin_username: str = Field(default="admin", min_length=3, max_length=64)
    bootstrap_admin_password_file: Path | None = None
    session_ttl_hours: int = Field(default=8, ge=1, le=168)
    cookie_secure: bool | None = None
    allow_insecure_forgejo_http: bool = False
    allow_unverified_forgejo_tls: bool = False
    trusted_proxy_cidrs: list[str] = Field(default_factory=list)
    forgejo_allowed_base_urls: list[str] = Field(default_factory=list)
    migration_allow_private_hosts: bool = False
    mcp_request_max_bytes: int = Field(default=2 * 1024 * 1024, ge=1024, le=16 * 1024 * 1024)
    mcp_allowed_origins: list[str] = Field(default_factory=list)
    commit_max_files: int = Field(default=100, ge=1, le=100)
    commit_max_total_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)
    forgejo_connect_timeout_seconds: float = Field(default=5.0, ge=0.1, le=30.0)
    forgejo_read_timeout_seconds: float = Field(default=30.0, ge=0.1, le=120.0)
    forgejo_write_timeout_seconds: float = Field(default=30.0, ge=0.1, le=120.0)
    forgejo_pool_timeout_seconds: float = Field(default=5.0, ge=0.1, le=30.0)
    forgejo_safe_retry_attempts: int = Field(default=2, ge=0, le=5)
    forgejo_retry_max_delay_seconds: float = Field(default=2.0, ge=0.0, le=30.0)
    mcp_rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    mcp_token_rate_limit_requests: int = Field(default=120, ge=1, le=10000)
    mcp_user_rate_limit_requests: int = Field(default=240, ge=1, le=20000)
    shutdown_grace_period_seconds: float = Field(default=30.0, ge=0.1, le=300.0)
    credential_encryption_key_file: Path | None = None
    credential_encryption_key_version: int = Field(default=1, ge=1)

    @field_validator("mcp_allowed_origins")
    @classmethod
    def validate_mcp_allowed_origins(cls, origins: list[str]) -> list[str]:
        return [normalize_http_origin(origin) for origin in origins]

    @field_validator("trusted_proxy_cidrs")
    @classmethod
    def validate_trusted_proxy_cidrs(cls, cidrs: list[str]) -> list[str]:
        try:
            normalized = [str(ip_network(cidr.strip(), strict=False)) for cidr in cidrs]
        except ValueError as error:
            raise ValueError("trusted proxy CIDRs must be valid IPv4 or IPv6 networks") from error
        if len(normalized) != len(set(normalized)):
            raise ValueError("trusted proxy CIDRs must be unique")
        return normalized

    @field_validator("forgejo_allowed_base_urls")
    @classmethod
    def validate_forgejo_allowed_base_urls(cls, base_urls: list[str]) -> list[str]:
        return [_normalize_external_base_url(base_url) for base_url in base_urls]

    @model_validator(mode="after")
    def require_production_forgejo_allowlist(self) -> "Settings":
        if self.database_url_file is not None:
            try:
                database_url = self.database_url_file.read_text(encoding="utf-8").strip()
            except OSError as error:
                raise ValueError("unable to read FMCP_DATABASE_URL_FILE") from error
            if not database_url or len(database_url) > 4096:
                raise ValueError("FMCP_DATABASE_URL_FILE is empty or too large")
            self.database_url = database_url
        if self.environment == "production" and not self.forgejo_allowed_base_urls:
            raise ValueError("production requires FMCP_FORGEJO_ALLOWED_BASE_URLS")
        return self

    def permits_forgejo_base_url(self, base_url: str) -> bool:
        """Enforce the deployment pin at every PAT-bearing network boundary."""
        if not self.forgejo_allowed_base_urls:
            return False
        try:
            normalized = _normalize_external_base_url(base_url)
        except ValueError:
            return False
        return normalized in self.forgejo_allowed_base_urls

    @property
    def use_secure_cookies(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def normalize_http_origin(value: str) -> str:
    """Return a canonical HTTP origin without accepting URL components beyond the authority."""
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError as error:
        raise ValueError("MCP allowed origins must be valid HTTP origins") from error
    scheme = parsed.scheme.lower()
    hostname = parsed.hostname
    if (
        scheme not in {"http", "https"}
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("MCP allowed origins must contain only an HTTP scheme and authority")
    default_port = 80 if scheme == "http" else 443
    host = f"[{hostname.lower()}]" if ":" in hostname else hostname.lower()
    netloc = host if port in {None, default_port} else f"{host}:{port}"
    return urlunsplit((scheme, netloc, "", "", ""))


def _normalize_external_base_url(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
        _ = parsed.port
    except ValueError as error:
        raise ValueError("Forgejo allowed base URLs must be valid HTTP URLs") from error
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Forgejo allowed base URLs must be credential-free HTTP URLs")
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            "",
            "",
        )
    )
