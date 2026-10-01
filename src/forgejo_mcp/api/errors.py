import logging

from fastapi import Request, status
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from forgejo_mcp.application.errors import (
    ApplicationError,
    AuthenticationFailed,
    ConfigurationUnavailable,
    Conflict,
    ExternalServiceUnavailable,
    Gone,
    InvalidOperation,
    NotFound,
    ValidationFailed,
)

logger = logging.getLogger(__name__)


async def request_validation_error_handler(request: Request, error: Exception) -> Response:
    assert isinstance(error, RequestValidationError)
    if request.scope.get("path") == "/api/forgejo/instance/oauth":
        # Pydantic's error inputs can contain raw secrets, even in malformed/extra fields.
        logger.warning(
            "forgejo_oauth_configuration_validation_failed",
            extra={"reason": "invalid_request_shape"},
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": "Invalid Forgejo OAuth settings request"},
            headers={"Cache-Control": "no-store"},
        )
    return await request_validation_exception_handler(request, error)


_STATUS_BY_ERROR: list[tuple[type[ApplicationError], int]] = [
    (AuthenticationFailed, status.HTTP_401_UNAUTHORIZED),
    (NotFound, status.HTTP_404_NOT_FOUND),
    (Conflict, status.HTTP_409_CONFLICT),
    (InvalidOperation, status.HTTP_409_CONFLICT),
    (Gone, status.HTTP_410_GONE),
    (ValidationFailed, status.HTTP_422_UNPROCESSABLE_CONTENT),
    (ExternalServiceUnavailable, status.HTTP_502_BAD_GATEWAY),
    (ConfigurationUnavailable, status.HTTP_503_SERVICE_UNAVAILABLE),
]


async def application_error_handler(_request: Request, error: Exception) -> JSONResponse:
    response_status = status.HTTP_500_INTERNAL_SERVER_ERROR
    for error_type, mapped_status in _STATUS_BY_ERROR:
        if isinstance(error, error_type):
            response_status = mapped_status
            break
    return JSONResponse(status_code=response_status, content={"detail": str(error)})
