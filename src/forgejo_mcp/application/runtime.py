import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from forgejo_mcp.observability.metrics import MCP_ACTIVE_INVOCATIONS


class ServiceShuttingDown(Exception):
    pass


class InvocationCoordinator:
    """Gate and drain MCP tool invocations during application shutdown."""

    def __init__(self) -> None:
        self._accepting = True
        self._active = 0
        self._condition = asyncio.Condition()

    @property
    def accepting(self) -> bool:
        return self._accepting

    @property
    def active(self) -> int:
        return self._active

    @asynccontextmanager
    async def invocation(self) -> AsyncIterator[None]:
        async with self._condition:
            if not self._accepting:
                raise ServiceShuttingDown
            self._active += 1
            MCP_ACTIVE_INVOCATIONS.inc()
        try:
            yield
        finally:
            async with self._condition:
                self._active -= 1
                MCP_ACTIVE_INVOCATIONS.dec()
                if self._active == 0:
                    self._condition.notify_all()

    async def begin_shutdown(self) -> None:
        async with self._condition:
            self._accepting = False
            if self._active == 0:
                self._condition.notify_all()

    async def wait_for_idle(self, timeout_seconds: float) -> bool:
        async def wait() -> None:
            async with self._condition:
                await self._condition.wait_for(lambda: self._active == 0)

        try:
            await asyncio.wait_for(wait(), timeout=timeout_seconds)
        except TimeoutError:
            return False
        return True
