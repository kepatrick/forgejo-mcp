import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.responses import JSONResponse
from starlette.types import Message, Receive, Scope, Send

from forgejo_mcp.observability.context import reset_request_id, set_request_id
from forgejo_mcp.observability.metrics import (
    HTTP_DURATION,
    HTTP_REQUEST_BODY_REJECTED,
    HTTP_REQUESTS,
)

logger = logging.getLogger("forgejo_mcp.http")
AsgiApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class RequestBodyTooLarge(Exception):
    pass


class RequestBodyLimitMiddleware:
    def __init__(self, app: AsgiApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") != "/mcp":
            await self.app(scope, receive, send)
            return
        content_length = _content_length(scope)
        if content_length is not None and content_length > self.max_bytes:
            await self._reject(scope, receive, send)
            return
        consumed = 0

        async def limited_receive() -> Message:
            nonlocal consumed
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > self.max_bytes:
                    raise RequestBodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except RequestBodyTooLarge:
            await self._reject(scope, receive, send)

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        HTTP_REQUEST_BODY_REJECTED.labels(route="/mcp").inc()
        response = JSONResponse(
            {"detail": "MCP request body is too large"},
            status_code=413,
        )
        await response(scope, receive, send)


class RequestObservabilityMiddleware:
    def __init__(self, app: AsgiApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = _request_id(scope)
        context_token = set_request_id(request_id)
        method = str(scope.get("method", "UNKNOWN"))
        route = _route_group(str(scope.get("path", "")))
        started = time.monotonic()
        status_code = 500

        async def observed_send(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, observed_send)
        finally:
            duration = time.monotonic() - started
            HTTP_REQUESTS.labels(method=method, route=route, status=str(status_code)).inc()
            HTTP_DURATION.labels(method=method, route=route).observe(duration)
            logger.info(
                "http_request_completed",
                extra={
                    "http_method": method,
                    "http_route": route,
                    "http_status": status_code,
                    "duration_ms": round(duration * 1000, 3),
                },
            )
            reset_request_id(context_token)


def _content_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", []):
        if name.lower() == b"content-length":
            try:
                parsed = int(value)
            except ValueError:
                return None
            return max(parsed, 0)
    return None


def _request_id(scope: Scope) -> str:
    for name, value in scope.get("headers", []):
        if name.lower() == b"x-request-id":
            candidate: str = value.decode("ascii", errors="ignore")
            if 1 <= len(candidate) <= 64 and all(
                character.isalnum() or character in "-_." for character in candidate
            ):
                return candidate
    return str(uuid.uuid4())


def _route_group(path: str) -> str:
    if path == "/mcp":
        return "/mcp"
    if path in {"/health/live", "/health/ready", "/metrics"}:
        return path
    if path.startswith("/api/"):
        return "/api/*"
    return "/frontend"
