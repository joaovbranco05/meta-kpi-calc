"""Local health check with no dependency on Meta credentials or network."""

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    mode: Literal["demo", "real"]
    database: Literal["ok"]
    scheduler: Literal["enabled", "disabled"]


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    database = request.app.state.database

    try:
        with database.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError):
        logger.error("Database health check failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "database_unavailable",
                "message": "Database health check failed",
            },
        ) from None

    return HealthResponse(
        status="ok",
        service=settings.app_name,
        mode=settings.mode,
        database="ok",
        scheduler="enabled" if settings.scheduler_enabled else "disabled",
    )

