from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
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
    mcp_request_max_bytes: int = Field(default=2 * 1024 * 1024, ge=1024, le=16 * 1024 * 1024)
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

    @property
    def use_secure_cookies(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
