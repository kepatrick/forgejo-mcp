import asyncio
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from forgejo_mcp.application.errors import (
    ApplicationError,
    AuthenticationFailed,
    Conflict,
    ExternalServiceUnavailable,
    NotFound,
    ValidationFailed,
)
from forgejo_mcp.audit.redaction import extract_target, redact_arguments, summarize_result
from forgejo_mcp.authorization.tools import ToolAuthorizationDecision
from forgejo_mcp.db.models import CredentialStatus, InvocationStatus, ToolInvocation
from forgejo_mcp.db.repositories import McpTokenRepository, ToolInvocationRepository
from forgejo_mcp.tools import ToolSpec


class ToolInvocationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.invocations = ToolInvocationRepository(session)
        self.tokens = McpTokenRepository(session)

    async def list_invocations(
        self,
        *,
        user_id: uuid.UUID | None,
        token_id: uuid.UUID | None,
        tool_name: str | None,
        status: str | None,
        started_after: datetime | None,
        started_before: datetime | None,
        page: int,
        limit: int,
    ) -> list[ToolInvocation]:
        if page < 1 or limit < 1 or limit > 100:
            raise ValidationFailed("audit pagination is invalid")
        valid_statuses = {item.value for item in InvocationStatus}
        if status is not None and status not in valid_statuses:
            raise ValidationFailed("audit status is invalid")
        if started_after is not None and started_after.tzinfo is None:
            raise ValidationFailed("started_after must include a timezone")
        if started_before is not None and started_before.tzinfo is None:
            raise ValidationFailed("started_before must include a timezone")
        if (
            started_after is not None
            and started_before is not None
            and started_after > started_before
        ):
            raise ValidationFailed("started_after must not be later than started_before")
        return await self.invocations.list(
            user_id=user_id,
            token_id=token_id,
            tool_name=tool_name,
            status=status,
            started_after=started_after,
            started_before=started_before,
            page=page,
            limit=limit,
        )

    async def get_invocation(
        self, invocation_id: uuid.UUID, *, user_id: uuid.UUID | None
    ) -> ToolInvocation:
        invocation = (
            await self.invocations.get(invocation_id)
            if user_id is None
            else await self.invocations.get_for_user(invocation_id, user_id)
        )
        if invocation is None:
            raise NotFound("tool invocation not found")
        return invocation

    async def record_decision(
        self,
        *,
        token_id: uuid.UUID,
        tool_name: str,
        spec: ToolSpec | None,
        arguments: dict[str, Any],
        decision: ToolAuthorizationDecision,
    ) -> ToolInvocation:
        token = await self.tokens.get(token_id)
        if token is None:
            raise AuthenticationFailed("MCP token is no longer available")
        redacted = redact_arguments(arguments)
        now = datetime.now(UTC)
        credential = next(
            (
                item
                for item in token.user.forgejo_credentials
                if item.status == CredentialStatus.ACTIVE
            ),
            None,
        )
        invocation = ToolInvocation(
            user_id=token.user_id,
            mcp_token_id=token.id,
            user_display_name=token.user.display_name,
            token_name=token.name,
            forgejo_username=(
                credential.forgejo_username
                if credential is not None
                else token.user.expected_forgejo_username
            ),
            tool_name=tool_name[:100],
            tool_version=spec.version if spec is not None else 0,
            risk=spec.risk if spec is not None else "unknown",
            started_at=now,
            completed_at=now if not decision.allowed else None,
            duration_ms=0 if not decision.allowed else None,
            status=(InvocationStatus.PENDING if decision.allowed else InvocationStatus.DENIED),
            authorization_allowed=decision.allowed,
            denial_reason=None if decision.allowed else decision.reason,
            redacted_arguments=redacted.value,
            target=extract_target(arguments),
            result_summary={},
            input_truncated=redacted.truncated,
            result_truncated=False,
        )
        self.invocations.add(invocation)
        await self.session.commit()
        return invocation

    async def complete_success(self, invocation: ToolInvocation, result: dict[str, Any]) -> None:
        summary, truncated = summarize_result(result)
        completed_at = datetime.now(UTC)
        invocation.status = InvocationStatus.SUCCEEDED
        invocation.completed_at = completed_at
        invocation.duration_ms = _duration_ms(invocation.started_at, completed_at)
        invocation.result_summary = summary
        invocation.result_truncated = truncated
        await self.session.commit()

    async def complete_failure(
        self,
        invocation: ToolInvocation,
        error: BaseException,
    ) -> None:
        completed_at = datetime.now(UTC)
        invocation.status = InvocationStatus.FAILED
        invocation.completed_at = completed_at
        invocation.duration_ms = _duration_ms(invocation.started_at, completed_at)
        invocation.error_type = classify_error(error)
        invocation.result_summary = {}
        await self.session.commit()


def classify_error(error: BaseException) -> str:
    if isinstance(error, asyncio.CancelledError):
        return "cancelled"
    if isinstance(error, AuthenticationFailed):
        return "authentication_failed"
    if isinstance(error, ValidationFailed):
        return "validation_failed"
    if isinstance(error, NotFound):
        return "not_found"
    if isinstance(error, Conflict):
        return "conflict"
    if isinstance(error, ExternalServiceUnavailable):
        return "forgejo_unavailable"
    if isinstance(error, ApplicationError):
        return _snake_case(type(error).__name__)
    return "internal_error"


def _duration_ms(started_at: datetime, completed_at: datetime) -> int:
    return max(0, int((completed_at - started_at).total_seconds() * 1000))


def _snake_case(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()
