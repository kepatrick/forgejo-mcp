from fastapi import Request, status
from fastapi.responses import JSONResponse

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
