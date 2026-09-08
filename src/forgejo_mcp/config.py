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
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    bootstrap_admin_username: str = Field(default="admin", min_length=3, max_length=64)
    bootstrap_admin_password_file: Path | None = None
    session_ttl_hours: int = Field(default=8, ge=1, le=168)
    cookie_secure: bool | None = None
    allow_insecure_forgejo_http: bool = False
    trusted_proxy_cidrs: list[str] = Field(default_factory=list)
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
    oauth_enabled: bool = False
    oauth_issuer_url: str | None = None
    oauth_resource_url: str | None = None
    oauth_cimd_allowed_origins: list[str] = Field(default_factory=list)
    oauth_access_token_ttl_seconds: int = Field(default=3600, ge=300, le=86400)
    oauth_refresh_token_ttl_days: int = Field(default=30, ge=1, le=90)
    oauth_refresh_token_max_ttl_days: int = Field(default=90, ge=1, le=90)
    oauth_refresh_token_reuse_grace_seconds: int = Field(default=10, ge=0, le=60)
    oauth_authorization_code_ttl_seconds: int = Field(default=300, ge=60, le=600)
    oauth_interaction_ttl_seconds: int = Field(default=600, ge=120, le=1800)
    oauth_client_metadata_cache_seconds: int = Field(default=3600, ge=300, le=86400)
    oauth_client_metadata_max_bytes: int = Field(default=65536, ge=4096, le=262144)
    oauth_request_max_bytes: int = Field(default=65536, ge=4096, le=262144)
    oauth_registration_rate_limit_requests: int = Field(default=10, ge=1, le=1000)
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

    @field_validator("oauth_cimd_allowed_origins")
    @classmethod
    def validate_oauth_cimd_allowed_origins(cls, origins: list[str]) -> list[str]:
        normalized = [normalize_http_origin(origin) for origin in origins]
        if len(normalized) != len(set(normalized)):
            raise ValueError("OAuth CIMD allowed origins must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_oauth_settings(self) -> "Settings":
        if self.oauth_enabled:
            if self.oauth_refresh_token_ttl_days > self.oauth_refresh_token_max_ttl_days:
                raise ValueError(
                    "OAuth refresh token default TTL must not exceed the configured maximum"
                )
            if self.oauth_issuer_url is None or self.oauth_resource_url is None:
                raise ValueError("OAuth requires FMCP_OAUTH_ISSUER_URL and FMCP_OAUTH_RESOURCE_URL")
            self.oauth_issuer_url = _normalize_oauth_url(
                self.oauth_issuer_url,
                "OAuth issuer URL",
            )
            self.oauth_resource_url = _normalize_oauth_url(
                self.oauth_resource_url,
                "OAuth resource URL",
            )
            issuer = urlsplit(self.oauth_issuer_url)
            resource = urlsplit(self.oauth_resource_url)
            if issuer.path not in {"", "/"}:
                raise ValueError("OAuth issuer URL must be an origin without a path")
            if (
                normalize_http_origin(f"{resource.scheme}://{resource.netloc}")
                != self.oauth_issuer_url
                or resource.path != "/mcp"
            ):
                raise ValueError("OAuth resource URL must be the issuer origin followed by /mcp")
            if self.environment == "production":
                if not self.oauth_issuer_url.startswith("https://"):
                    raise ValueError("production OAuth issuer URL must use HTTPS")
                if not self.oauth_resource_url.startswith("https://"):
                    raise ValueError("production OAuth resource URL must use HTTPS")
                if any(
                    not origin.startswith("https://") for origin in self.oauth_cimd_allowed_origins
                ):
                    raise ValueError("production OAuth CIMD origins must use HTTPS")
        return self

    @property
    def use_secure_cookies(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.environment == "production"

    @property
    def oauth_grant_ttl_options_days(self) -> tuple[int, ...]:
        """Return exact consent choices bounded by deployment policy."""
        standard = {1, 7, 30, 90}
        standard.add(self.oauth_refresh_token_ttl_days)
        return tuple(
            sorted(days for days in standard if days <= self.oauth_refresh_token_max_ttl_days)
        )


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


def _normalize_oauth_url(value: str, label: str) -> str:
    try:
        parsed = urlsplit(value.strip())
        _ = parsed.port
    except ValueError as error:
        raise ValueError(f"{label} must be a valid HTTP URL") from error
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{label} must be a credential-free HTTP URL")
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, "", ""))
