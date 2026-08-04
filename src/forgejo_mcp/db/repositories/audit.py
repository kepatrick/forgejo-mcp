import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from forgejo_mcp.db.models import ManagementAuditEvent


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def record(
        self,
        *,
        actor_account_id: uuid.UUID | None,
        action: str,
        target_type: str | None,
        target_id: str | None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.session.add(
            ManagementAuditEvent(
                actor_account_id=actor_account_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                details=details or {},
            )
        )
