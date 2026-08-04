import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from forgejo_mcp.application.errors import ValidationFailed
from forgejo_mcp.config import Settings
from forgejo_mcp.db.models import ForgejoInstance
from forgejo_mcp.db.repositories import AuditRepository, ForgejoInstanceRepository
from forgejo_mcp.forgejo.client import ForgejoClient, normalize_base_url


@dataclass(frozen=True)
class ForgejoConnectionResult:
    base_url: str
    version: str
    checked_at: datetime


class ForgejoInstanceService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.instances = ForgejoInstanceRepository(session)
        self.audit = AuditRepository(session)
        self.client = ForgejoClient(
            connect_timeout_seconds=settings.forgejo_connect_timeout_seconds
        )

    async def get(self) -> ForgejoInstance | None:
        return await self.instances.primary()

    async def check(self, *, base_url: str, verify_tls: bool) -> ForgejoConnectionResult:
        normalized_url = normalize_base_url(base_url)
        if (
            urlsplit(normalized_url).scheme == "http"
            and not self.settings.allow_insecure_forgejo_http
        ):
            raise ValidationFailed(
                "HTTP Forgejo URLs are disabled; use HTTPS or explicitly allow insecure HTTP"
            )
        result = await self.client.get_version(
            base_url=normalized_url,
            verify_tls=verify_tls,
        )
        return ForgejoConnectionResult(
            base_url=normalized_url,
            version=result.version,
            checked_at=datetime.now(UTC),
        )

    async def configure(
        self,
        *,
        actor_account_id: uuid.UUID,
        display_name: str,
        base_url: str,
        verify_tls: bool,
    ) -> ForgejoInstance:
        normalized_name = display_name.strip()
        if not normalized_name:
            raise ValidationFailed("display name cannot be blank")
        checked = await self.check(base_url=base_url, verify_tls=verify_tls)
        instance = await self.instances.primary()
        if instance is None:
            instance = ForgejoInstance(
                slug="primary",
                display_name=normalized_name,
                base_url=checked.base_url,
                verify_tls=verify_tls,
                version=checked.version,
                configured_by_account_id=actor_account_id,
                last_checked_at=checked.checked_at,
            )
            self.instances.add(instance)
            action = "forgejo_instance.created"
        else:
            instance.display_name = normalized_name
            instance.base_url = checked.base_url
            instance.verify_tls = verify_tls
            instance.version = checked.version
            instance.configured_by_account_id = actor_account_id
            instance.last_checked_at = checked.checked_at
            action = "forgejo_instance.updated"

        await self.session.flush()
        self.audit.record(
            actor_account_id=actor_account_id,
            action=action,
            target_type="forgejo_instance",
            target_id=str(instance.id),
            details={
                "base_url": instance.base_url,
                "verify_tls": instance.verify_tls,
                "version": instance.version,
            },
        )
        await self.session.commit()
        return instance
