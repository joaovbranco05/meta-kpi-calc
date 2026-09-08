"""FastAPI application factory."""

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from meta_kpi_calc.api.routes.health import router as health_router
from meta_kpi_calc.api.routes.rest import router as rest_router
from meta_kpi_calc.core.config import Settings, get_settings
from meta_kpi_calc.core.logging import configure_logging
from meta_kpi_calc.db.session import Database
from meta_kpi_calc.services.meta_client import MetaClient
from meta_kpi_calc.services.scheduler import create_scheduler
from meta_kpi_calc.services.sync_service import SyncService

logger = logging.getLogger(__name__)


def _meta_is_configured(settings: Settings) -> bool:
    token = settings.meta_access_token
    return bool(
        token is not None
        and token.get_secret_value().strip()
        and settings.meta_ad_account_id is not None
    )


def create_app(
    settings: Settings | None = None,
    *,
    http_client: httpx.Client | None = None,
) -> FastAPI:
    """Create an app whose dependencies can be replaced safely in tests."""
    app_settings = settings or get_settings()
    configure_logging(app_settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        owned_http_client: httpx.Client | None = None
        scheduler = None
        scheduler_started = False
        try:
            if not app_settings.demo_mode and _meta_is_configured(app_settings):
                active_http_client = http_client
                if active_http_client is None:
                    active_http_client = httpx.Client(follow_redirects=False)
                    owned_http_client = active_http_client
                token = app_settings.meta_access_token
                assert token is not None
                assert app_settings.meta_ad_account_id is not None
                meta_client = MetaClient(
                    active_http_client,
                    token=token.get_secret_value(),
                    ad_account_id=app_settings.meta_ad_account_id,
                    api_version=app_settings.meta_api_version,
                    lead_action_types=app_settings.meta_lead_action_types,
                )
                application.state.meta_client = meta_client
                application.state.sync_service = SyncService(
                    app_settings,
                    application.state.database.session_factory,
                    meta_client,
                )

            if app_settings.scheduler_enabled:
                scheduler = create_scheduler(
                    app_settings, application.state.sync_service
                )
                assert scheduler is not None
                application.state.scheduler = scheduler
                scheduler.start()
                scheduler_started = True
            yield
        finally:
            try:
                if scheduler is not None and (
                    scheduler_started or scheduler.running
                ):
                    scheduler.shutdown(wait=False)
            finally:
                if owned_http_client is not None:
                    owned_http_client.close()

    application = FastAPI(
        title=app_settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.settings = app_settings
    application.state.database = Database(app_settings)
    application.state.meta_client = None
    application.state.sync_service = None
    application.state.scheduler = None
    application.include_router(health_router)
    application.include_router(rest_router)

    @application.exception_handler(RequestValidationError)
    async def validation_error(
        _request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "code": "validation_error",
                    "message": "Request validation failed.",
                }
            },
        )

    @application.exception_handler(SQLAlchemyError)
    @application.exception_handler(OSError)
    async def database_error(_request: Request, _exc: Exception) -> JSONResponse:
        logger.error("Database request failed")
        return JSONResponse(
            status_code=503,
            content={
                "detail": {
                    "code": "database_unavailable",
                    "message": "Database request failed.",
                }
            },
        )

    @application.exception_handler(Exception)
    async def unexpected_error(_request: Request, _exc: Exception) -> JSONResponse:
        logger.error("Unexpected request failure")
        return JSONResponse(
            status_code=500,
            content={
                "detail": {
                    "code": "internal_error",
                    "message": "Unexpected request failure.",
                }
            },
        )
    return application


app = create_app()
