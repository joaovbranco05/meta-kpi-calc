"""Optional APScheduler configuration for Meta synchronization."""

from datetime import timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from meta_kpi_calc.core.config import Settings
from meta_kpi_calc.services.sync_service import SyncService, SyncServiceError


def create_scheduler(
    settings: Settings, sync_service: SyncService
) -> BackgroundScheduler | None:
    if not settings.scheduler_enabled:
        return None
    if settings.demo_mode:
        raise SyncServiceError(
            "Meta synchronization is unavailable in demo mode.", code="demo_mode"
        )
    token = settings.meta_access_token
    if (
        token is None
        or not token.get_secret_value().strip()
        or settings.meta_ad_account_id is None
    ):
        raise SyncServiceError(
            "Meta synchronization is not configured.", code="meta_not_configured"
        )

    scheduler = BackgroundScheduler(timezone=settings.app_timezone)

    def scheduled_sync() -> None:
        today = sync_service.today()
        date_start = today - timedelta(days=settings.sync_lookback_days - 1)
        sync_service.run_sync(date_start, today, active_only=True)

    scheduler.add_job(
        scheduled_sync,
        "interval",
        minutes=settings.sync_interval_minutes,
        id="meta-sync",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    return scheduler
