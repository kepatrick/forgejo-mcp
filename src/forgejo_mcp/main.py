import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from forgejo_mcp.api import (
    auth_router,
    forgejo_credential_admin_router,
    forgejo_credential_me_router,
    forgejo_instance_router,
    invitations_router,
    mcp_token_admin_router,
    mcp_token_me_router,
    system_router,
    tool_invocations_admin_router,
    tool_invocations_me_router,
    tools_admin_router,
    tools_me_router,
    tools_user_allowance_router,
    users_router,
)
from forgejo_mcp.api.errors import application_error_handler
from forgejo_mcp.application.bootstrap_service import bootstrap_admin
from forgejo_mcp.application.errors import ApplicationError
from forgejo_mcp.application.runtime import InvocationCoordinator
from forgejo_mcp.config import Settings, get_settings
from forgejo_mcp.db.session import create_engine, create_session_factory
from forgejo_mcp.mcp.server import build_mcp_runtime
from forgejo_mcp.observability import configure_logging
from forgejo_mcp.observability.middleware import (
    RequestBodyLimitMiddleware,
    RequestObservabilityMiddleware,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    engine = create_engine(settings)
    app.state.db_engine = engine
    app.state.db_session_factory = create_session_factory(engine)
    if settings.bootstrap_admin_password_file is not None:
        await bootstrap_admin(settings, app.state.db_session_factory)
    try:
        async with app.state.mcp_runtime.manager.run():
            try:
                yield
            finally:
                coordinator: InvocationCoordinator = app.state.invocation_coordinator
                await coordinator.begin_shutdown()
                drained = await coordinator.wait_for_idle(settings.shutdown_grace_period_seconds)
                logger.info(
                    "application_shutdown_drain_completed",
                    extra={
                        "drained": drained,
                        "remaining_invocations": coordinator.active,
                    },
                )
    finally:
        await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level, resolved_settings.log_format)

    application = FastAPI(
        title="Forgejo MCP",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs" if resolved_settings.environment != "production" else None,
        redoc_url=None,
    )
    application.state.settings = resolved_settings
    application.state.invocation_coordinator = InvocationCoordinator()
    application.state.mcp_runtime = build_mcp_runtime(
        lambda: application.state.db_session_factory,
        resolved_settings,
        application.state.invocation_coordinator,
    )
    application.add_middleware(
        RequestBodyLimitMiddleware,
        max_bytes=resolved_settings.mcp_request_max_bytes,
    )
    application.add_middleware(RequestObservabilityMiddleware)
    application.add_exception_handler(ApplicationError, application_error_handler)
    application.include_router(auth_router)
    application.include_router(forgejo_credential_admin_router)
    application.include_router(forgejo_credential_me_router)
    application.include_router(forgejo_instance_router)
    application.include_router(invitations_router)
    application.include_router(mcp_token_admin_router)
    application.include_router(mcp_token_me_router)
    application.include_router(tools_admin_router)
    application.include_router(tools_me_router)
    application.include_router(tools_user_allowance_router)
    application.include_router(users_router)
    application.include_router(system_router)
    application.include_router(tool_invocations_admin_router)
    application.include_router(tool_invocations_me_router)
    application.router.routes.append(application.state.mcp_runtime.route)

    frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if frontend_dist.is_dir():
        application.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

    return application


app = create_app()
