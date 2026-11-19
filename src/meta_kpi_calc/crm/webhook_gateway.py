"""Standalone Meta Lead Ads ingress backed directly by the durable inbox."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from meta_kpi_calc.core.config import Settings
from meta_kpi_calc.core.logging import configure_logging
from meta_kpi_calc.crm.webhook import router
from meta_kpi_calc.crm.webhook_logging import WEBHOOK_PATH, WebhookDiagnosticMiddleware
from meta_kpi_calc.db.session import Database

ALLOWED_METHODS = ("GET", "POST")


def create_webhook_gateway_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings()
    configure_logging(app_settings)
    database = Database(app_settings)

    @asynccontextmanager
    async def lifespan(_application: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            database.engine.dispose()

    application = FastAPI(
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        redirect_slashes=False,
        lifespan=lifespan,
    )
    application.state.settings = app_settings
    application.state.database = database
    application.include_router(router)

    @application.middleware("http")
    async def callback_only(request: Request, call_next):
        if (
            request.scope["path"] != WEBHOOK_PATH
            or request.scope.get("raw_path", WEBHOOK_PATH.encode()) != WEBHOOK_PATH.encode()
        ):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        if request.method not in ALLOWED_METHODS:
            return JSONResponse(
                {"detail": "Method Not Allowed"},
                status_code=405,
                headers={"Allow": ", ".join(ALLOWED_METHODS)},
            )
        return await call_next(request)

    @application.exception_handler(SQLAlchemyError)
    @application.exception_handler(OSError)
    async def database_error(_request: Request, _exc: Exception) -> JSONResponse:
        return JSONResponse(
            {"detail": {"code": "database_unavailable", "message": "Webhook persistence failed."}},
            status_code=503,
        )

    if app_settings.lead_ads_diagnostic_log_path is not None:
        application.add_middleware(
            WebhookDiagnosticMiddleware,
            path=app_settings.lead_ads_diagnostic_log_path,
            webhook_only=False,
        )
    return application


app = create_webhook_gateway_app()
