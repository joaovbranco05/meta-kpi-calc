"""FastAPI application factory."""

from fastapi import FastAPI

from meta_kpi_calc.api.routes.health import router as health_router
from meta_kpi_calc.core.config import Settings, get_settings
from meta_kpi_calc.core.logging import configure_logging
from meta_kpi_calc.db.session import Database


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an app whose dependencies can be replaced safely in tests."""
    app_settings = settings or get_settings()
    configure_logging(app_settings)

    application = FastAPI(title=app_settings.app_name, version="0.1.0")
    application.state.settings = app_settings
    application.state.database = Database(app_settings)
    application.include_router(health_router)
    return application


app = create_app()

