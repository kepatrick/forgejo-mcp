import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from forgejo_mcp.db.base import Base


class AccountRole(enum.StrEnum):
    ADMIN = "admin"
    USER = "user"


class RecordStatus(enum.StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    DISABLED = "disabled"


class CredentialStatus(enum.StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class InvocationStatus(enum.StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    display_name: Mapped[str] = mapped_column(String(120))
    expected_forgejo_username: Mapped[str] = mapped_column(String(255))
    normalized_forgejo_username: Mapped[str] = mapped_column(String(255), unique=True)
    status: Mapped[str] = mapped_column(String(20), default=RecordStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    account: Mapped["Account | None"] = relationship(back_populates="user", uselist=False)
    invitations: Mapped[list["UserInvitation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    forgejo_credentials: Mapped[list["ForgejoCredential"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    mcp_tokens: Mapped[list["McpToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    username: Mapped[str] = mapped_column(String(64))
    normalized_username: Mapped[str] = mapped_column(String(64), unique=True)
    role: Mapped[str] = mapped_column(String(20))
    password_hash: Mapped[str] = mapped_column(String(512))
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default=RecordStatus.ACTIVE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User | None] = relationship(back_populates="account")
    sessions: Mapped[list["Session"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    session_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    client_ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))

    account: Mapped[Account] = relationship(back_populates="sessions")


class UserInvitation(Base):
    __tablename__ = "user_invitations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    purpose: Mapped[str] = mapped_column(String(30))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    created_by_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="invitations")


class ForgejoInstance(Base):
    __tablename__ = "forgejo_instances"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(32), unique=True, default="primary")
    display_name: Mapped[str] = mapped_column(String(120), default="Forgejo")
    base_url: Mapped[str] = mapped_column(String(2048))
    verify_tls: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[str] = mapped_column(String(120))
    configured_by_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ForgejoCredential(Base):
    __tablename__ = "forgejo_credentials"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    encrypted_token: Mapped[bytes | None] = mapped_column(LargeBinary)
    nonce: Mapped[bytes | None] = mapped_column(LargeBinary)
    key_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default=CredentialStatus.ACTIVE)
    forgejo_user_id: Mapped[int] = mapped_column(BigInteger)
    forgejo_username: Mapped[str] = mapped_column(String(255))
    normalized_forgejo_username: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="forgejo_credentials")


class McpToken(Base):
    __tablename__ = "mcp_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(String(500))
    token_prefix: Mapped[str] = mapped_column(String(20))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="mcp_tokens")


class ToolSetting(Base):
    __tablename__ = "tool_settings"

    tool_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    registry_version: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UserToolAllowance(Base):
    __tablename__ = "user_tool_allowances"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    tool_name: Mapped[str] = mapped_column(
        ForeignKey("tool_settings.tool_name", ondelete="CASCADE"), primary_key=True
    )


class McpTokenToolGrant(Base):
    __tablename__ = "mcp_token_tool_grants"

    mcp_token_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mcp_tokens.id", ondelete="CASCADE"), primary_key=True
    )
    tool_name: Mapped[str] = mapped_column(
        ForeignKey("tool_settings.tool_name", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ToolInvocation(Base):
    __tablename__ = "tool_invocations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    mcp_token_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mcp_tokens.id", ondelete="SET NULL"), index=True
    )
    user_display_name: Mapped[str] = mapped_column(String(120))
    token_name: Mapped[str] = mapped_column(String(120))
    forgejo_username: Mapped[str] = mapped_column(String(255))
    tool_name: Mapped[str] = mapped_column(String(100), index=True)
    tool_version: Mapped[int] = mapped_column(Integer)
    risk: Mapped[str] = mapped_column(String(30))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), index=True)
    authorization_allowed: Mapped[bool] = mapped_column(Boolean)
    denial_reason: Mapped[str | None] = mapped_column(String(80))
    redacted_arguments: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    target: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_type: Mapped[str | None] = mapped_column(String(80))
    forgejo_http_status: Mapped[int | None] = mapped_column(Integer)
    input_truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    result_truncated: Mapped[bool] = mapped_column(Boolean, default=False)


class ManagementAuditEvent(Base):
    __tablename__ = "management_audit_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    actor_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(100), index=True)
    target_type: Mapped[str | None] = mapped_column(String(50))
    target_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


Index("ix_sessions_active_lookup", Session.session_token_hash, Session.expires_at)
Index(
    "ix_forgejo_credentials_user_status",
    ForgejoCredential.user_id,
    ForgejoCredential.status,
)
Index("ix_mcp_tokens_user_created", McpToken.user_id, McpToken.created_at)
Index("ix_tool_invocations_user_started", ToolInvocation.user_id, ToolInvocation.started_at)
Index("ix_tool_invocations_token_started", ToolInvocation.mcp_token_id, ToolInvocation.started_at)
