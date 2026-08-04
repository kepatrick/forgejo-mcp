import uuid
from types import SimpleNamespace
from typing import Any

from forgejo_mcp.application.forgejo_tool_service import ForgejoToolService


async def test_generic_client_dispatch_does_not_collide_with_method_argument() -> None:
    received: dict[str, Any] = {}

    class FakeClient:
        async def merge_pull_request(self, **kwargs: Any) -> None:
            received.update(kwargs)

    class FakeInstances:
        async def primary(self) -> SimpleNamespace:
            return SimpleNamespace(
                base_url="https://git.example.test",
                verify_tls=True,
            )

    class FakeCredentials:
        client = FakeClient()

        async def decrypted_token_for_user(self, _user_id: uuid.UUID) -> str:
            return "pat"

    service = object.__new__(ForgejoToolService)
    service.instances = FakeInstances()  # type: ignore[assignment]
    service.credentials = FakeCredentials()  # type: ignore[assignment]

    await service.merge_pull_request(
        uuid.uuid4(),
        owner="patrick",
        repo="repo",
        number=7,
        method="squash",
        title=None,
        message=None,
        head_sha="abc123",
        delete_branch=True,
    )

    assert received["method"] == "squash"
    assert received["owner"] == "patrick"
    assert received["token"] == "pat"
