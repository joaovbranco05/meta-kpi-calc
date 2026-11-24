"""Meta connection and synchronization endpoints."""

import logging

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from meta_kpi_calc.api.dependencies import get_session
from meta_kpi_calc.api.routes._shared import SessionDependency, _error
from meta_kpi_calc.api.schemas import (
    AccountResponse,
    ConnectionResponse,
    SyncRequest,
    SyncResponse,
    SyncStatusResponse,
)
from meta_kpi_calc.auth.dependencies import authenticate_session, lock_accounts, require_admin
from meta_kpi_calc.db.models import SyncRun, SyncStatus
from meta_kpi_calc.services.meta_client import MetaClientError
from meta_kpi_calc.services.sync_service import SyncAuthorizationError, SyncServiceError

logger = logging.getLogger(__name__)

router = APIRouter()


def _meta_configured(request: Request) -> bool:
    settings = request.app.state.settings
    token = settings.meta_access_token
    return bool(
        token is not None
        and token.get_secret_value().strip()
        and settings.meta_ad_account_id is not None
    )


@router.get("/meta/connection", response_model=ConnectionResponse)
def meta_connection(request: Request) -> ConnectionResponse:
    settings = request.app.state.settings
    configured = _meta_configured(request)
    if settings.demo_mode or not configured:
        return ConnectionResponse(
            mode=settings.mode,
            configured=configured,
            connected=False,
            account=None,
        )
    try:
        account = request.app.state.meta_client.get_account()
    except MetaClientError:
        logger.warning("Meta connection check failed")
        _error(502, "meta_connection_failed", "Meta connection check failed.")
    return ConnectionResponse(
        mode=settings.mode,
        configured=True,
        connected=True,
        account=AccountResponse(**vars(account)),
    )


@router.post("/meta/sync", response_model=SyncResponse)
def sync_meta(payload: SyncRequest, request: Request) -> SyncResponse:
    service = request.app.state.sync_service
    if service is None:
        _error(503, "meta_sync_unavailable", "Meta synchronization is unavailable.")
    def authorize_write(session: Session) -> None:
        try:
            lock_accounts(session, shared=True)
            require_admin(authenticate_session(request, session))
        except HTTPException as exc:
            raise SyncAuthorizationError(exc.status_code) from None

    try:
        result = service.run_sync(
            payload.date_start,
            payload.date_stop,
            active_only=payload.active_only,
            meta_campaign_id=payload.meta_campaign_id,
            authorize_write=authorize_write,
        )
    except SyncAuthorizationError as exc:
        raise HTTPException(exc.status_code, "Synchronization no longer authorized") from None
    except SyncServiceError as exc:
        if exc.code == "sync_in_progress":
            _error(409, "sync_in_progress", "A synchronization is already in progress.")
        if exc.code in {"demo_mode", "meta_not_configured"}:
            _error(503, "meta_sync_unavailable", "Meta synchronization is unavailable.")
        if exc.code in {
            "invalid_date_range",
            "future_date",
            "invalid_campaign_filter",
        }:
            _error(422, exc.code, "Synchronization request is invalid.")
        detail = {"sync_run_id": exc.sync_run_id} if exc.sync_run_id is not None else {}
        _error(502, "meta_sync_failed", "Meta synchronization failed.", **detail)
    return SyncResponse(**vars(result))


@router.get("/meta/sync/status", response_model=SyncStatusResponse)
def sync_status(session: SessionDependency) -> SyncStatusResponse:
    """Read the latest persisted synchronization state without calling Meta."""
    run = session.scalar(
        select(SyncRun).order_by(SyncRun.started_at.desc(), SyncRun.id.desc())
    )
    if run is None:
        return SyncStatusResponse(
            state="not_confirmed",
            started_at=None,
            finished_at=None,
            date_start=None,
            date_stop=None,
        )
    state = {
        SyncStatus.RUNNING: "running",
        SyncStatus.SUCCESS: "completed",
        SyncStatus.FAILED: "failed",
    }[run.status]
    return SyncStatusResponse(
        state=state,
        started_at=run.started_at,
        finished_at=run.finished_at,
        date_start=run.date_start,
        date_stop=run.date_stop,
    )
