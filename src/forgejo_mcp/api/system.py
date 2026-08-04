from typing import Any

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from forgejo_mcp import __version__
from forgejo_mcp.application.runtime import InvocationCoordinator
from forgejo_mcp.observability.metrics import DB_POOL_CHECKED_OUT, DB_POOL_SIZE

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: str


class ReadinessResponse(BaseModel):
    status: str
    dependencies: dict[str, str]
    accepting_mcp_requests: bool


class VersionResponse(BaseModel):
    name: str
    version: str


@router.get("/health/live", response_model=HealthResponse)
async def liveness() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/health/ready", response_model=ReadinessResponse)
async def readiness(request: Request) -> ReadinessResponse | JSONResponse:
    engine: AsyncEngine = request.app.state.db_engine
    coordinator: InvocationCoordinator = request.app.state.invocation_coordinator
    database_status = "ok"
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        database_status = "unavailable"
    content = {
        "status": "ok" if database_status == "ok" and coordinator.accepting else "unavailable",
        "dependencies": {"database": database_status},
        "accepting_mcp_requests": coordinator.accepting,
    }
    if content["status"] != "ok":
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=content)
    return ReadinessResponse(**content)  # type: ignore[arg-type]


@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    _update_pool_metrics(request.app.state.db_engine)
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/api/system/version", response_model=VersionResponse)
async def version() -> VersionResponse:
    return VersionResponse(name="forgejo-mcp", version=__version__)


def _update_pool_metrics(engine: AsyncEngine) -> None:
    pool: Any = engine.pool
    checkedout = getattr(pool, "checkedout", None)
    size = getattr(pool, "size", None)
    if callable(checkedout):
        DB_POOL_CHECKED_OUT.set(checkedout())
    if callable(size):
        DB_POOL_SIZE.set(size())
