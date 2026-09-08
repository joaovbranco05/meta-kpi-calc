"""Atomic persistence of campaigns and insights fetched from Meta."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from threading import Lock
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from meta_kpi_calc.core.config import Settings
from meta_kpi_calc.db.models import Campaign, CampaignInsight, SyncRun, SyncStatus
from meta_kpi_calc.services.meta_client import MetaCampaign, MetaClient, MetaInsight

_SYNC_LOCK = Lock()
_FAILED_MESSAGE = "Meta synchronization failed."


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SyncServiceError(Exception):
    """Sanitized synchronization failure."""

    def __init__(
        self, message: str, *, code: str, sync_run_id: int | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.sync_run_id = sync_run_id


@dataclass(frozen=True)
class SyncResult:
    sync_run_id: int
    status: SyncStatus
    date_start: date
    date_stop: date
    campaign_count: int
    record_count: int
    is_partial: bool


class SyncService:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        meta_client: MetaClient,
        *,
        now: Callable[[], datetime] = _utc_now,
        lock: Lock | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._meta_client = meta_client
        self._now = now
        self._lock = lock or _SYNC_LOCK

    def today(self) -> date:
        timezone = ZoneInfo(self._settings.app_timezone)
        return self._current_time().astimezone(timezone).date()

    def run_sync(
        self,
        date_start: date,
        date_stop: date,
        *,
        active_only: bool = True,
        meta_campaign_id: str | None = None,
    ) -> SyncResult:
        requested_campaign_id = self._validate_request(
            date_start, date_stop, meta_campaign_id
        )
        started_at = self._current_time()
        today = started_at.astimezone(ZoneInfo(self._settings.app_timezone)).date()
        if date_stop > today:
            raise SyncServiceError(
                "Synchronization dates cannot be in the future.",
                code="future_date",
            )
        self._validate_configuration()

        if not self._lock.acquire(blocking=False):
            raise SyncServiceError(
                "A synchronization is already in progress.",
                code="sync_in_progress",
            )

        sync_run_id: int | None = None
        try:
            sync_run_id = self._start_run(date_start, date_stop, started_at)
            campaigns = self._select_campaigns(active_only, requested_campaign_id)
            insights = self._select_insights(campaigns, date_start, date_stop)
            completed_at = self._current_time()
            self._persist_data(campaigns, insights, completed_at)
            self._finish_run(
                sync_run_id,
                SyncStatus.SUCCESS,
                completed_at,
                campaign_count=len(campaigns),
                record_count=len(insights),
            )
            return SyncResult(
                sync_run_id=sync_run_id,
                status=SyncStatus.SUCCESS,
                date_start=date_start,
                date_stop=date_stop,
                campaign_count=len(campaigns),
                record_count=len(insights),
                is_partial=date_stop == today,
            )
        except Exception:
            if sync_run_id is not None:
                try:
                    failed_at = self._current_time()
                except Exception:
                    failed_at = started_at
                try:
                    self._finish_run(
                        sync_run_id,
                        SyncStatus.FAILED,
                        failed_at,
                        campaign_count=0,
                        record_count=0,
                    )
                except Exception:
                    pass
            raise SyncServiceError(
                _FAILED_MESSAGE,
                code="sync_failed",
                sync_run_id=sync_run_id,
            ) from None
        finally:
            self._lock.release()

    def _current_time(self) -> datetime:
        current = self._now()
        if not isinstance(current, datetime) or current.tzinfo is None:
            raise SyncServiceError(
                "Synchronization clock is invalid.", code="invalid_date_range"
            )
        if current.utcoffset() is None:
            raise SyncServiceError(
                "Synchronization clock is invalid.", code="invalid_date_range"
            )
        return current.astimezone(UTC)

    def _validate_request(
        self,
        date_start: date,
        date_stop: date,
        meta_campaign_id: str | None,
    ) -> str | None:
        if (
            not isinstance(date_start, date)
            or isinstance(date_start, datetime)
            or not isinstance(date_stop, date)
            or isinstance(date_stop, datetime)
            or date_start > date_stop
        ):
            raise SyncServiceError(
                "Synchronization date range is invalid.", code="invalid_date_range"
            )
        inclusive_days = (date_stop - date_start).days + 1
        if inclusive_days > min(self._settings.max_sync_days, 31):
            raise SyncServiceError(
                "Synchronization date range is invalid.", code="invalid_date_range"
            )
        if meta_campaign_id is None:
            return None
        if not isinstance(meta_campaign_id, str) or not meta_campaign_id.strip():
            raise SyncServiceError(
                "Campaign filter is invalid.", code="invalid_campaign_filter"
            )
        return meta_campaign_id.strip()

    def _validate_configuration(self) -> None:
        if self._settings.demo_mode:
            raise SyncServiceError(
                "Meta synchronization is unavailable in demo mode.",
                code="demo_mode",
            )
        token = self._settings.meta_access_token
        if (
            token is None
            or not token.get_secret_value().strip()
            or self._settings.meta_ad_account_id is None
        ):
            raise SyncServiceError(
                "Meta synchronization is not configured.",
                code="meta_not_configured",
            )

    def _start_run(
        self, date_start: date, date_stop: date, started_at: datetime
    ) -> int:
        with self._session_factory.begin() as session:
            sync_run = SyncRun(
                started_at=started_at,
                status=SyncStatus.RUNNING,
                date_start=date_start,
                date_stop=date_stop,
                campaign_count=0,
                record_count=0,
            )
            session.add(sync_run)
            session.flush()
            return sync_run.id

    def _select_campaigns(
        self, active_only: bool, requested_campaign_id: str | None
    ) -> list[MetaCampaign]:
        returned = self._meta_client.list_campaigns(active_only=active_only)
        selected: dict[str, MetaCampaign] = {}
        for campaign in returned:
            if (
                requested_campaign_id is None
                or campaign.meta_campaign_id == requested_campaign_id
            ):
                selected[campaign.meta_campaign_id] = campaign
        return list(selected.values())

    def _select_insights(
        self,
        campaigns: list[MetaCampaign],
        date_start: date,
        date_stop: date,
    ) -> list[MetaInsight]:
        if not campaigns:
            return []
        selected_campaign_ids = {
            campaign.meta_campaign_id for campaign in campaigns
        }
        unique: dict[tuple[str, date, date], MetaInsight] = {}
        for insight in self._meta_client.get_insights(date_start, date_stop):
            if insight.meta_campaign_id not in selected_campaign_ids:
                continue
            if insight.date_start < date_start or insight.date_stop > date_stop:
                raise SyncServiceError(_FAILED_MESSAGE, code="sync_failed")
            key = (
                insight.meta_campaign_id,
                insight.date_start,
                insight.date_stop,
            )
            unique[key] = insight
        return list(unique.values())

    def _persist_data(
        self,
        campaigns: list[MetaCampaign],
        insights: list[MetaInsight],
        synced_at: datetime,
    ) -> None:
        with self._session_factory.begin() as session:
            local_campaigns: dict[str, Campaign] = {}
            for meta_campaign in campaigns:
                campaign = session.scalar(
                    select(Campaign).where(
                        Campaign.meta_campaign_id == meta_campaign.meta_campaign_id
                    )
                )
                if campaign is None:
                    campaign = Campaign(meta_campaign_id=meta_campaign.meta_campaign_id)
                    session.add(campaign)
                campaign.name = meta_campaign.name
                campaign.status = meta_campaign.status
                campaign.effective_status = meta_campaign.effective_status
                campaign.objective = meta_campaign.objective
                campaign.start_time = _parse_meta_datetime(meta_campaign.start_time)
                campaign.stop_time = _parse_meta_datetime(meta_campaign.stop_time)
                campaign.last_synced_at = synced_at
                local_campaigns[meta_campaign.meta_campaign_id] = campaign

            session.flush()
            for meta_insight in insights:
                campaign = local_campaigns[meta_insight.meta_campaign_id]
                insight = session.scalar(
                    select(CampaignInsight).where(
                        CampaignInsight.campaign_id == campaign.id,
                        CampaignInsight.date_start == meta_insight.date_start,
                        CampaignInsight.date_stop == meta_insight.date_stop,
                    )
                )
                if insight is None:
                    insight = CampaignInsight(
                        campaign_id=campaign.id,
                        date_start=meta_insight.date_start,
                        date_stop=meta_insight.date_stop,
                    )
                    session.add(insight)
                insight.spend = meta_insight.spend
                insight.reach = meta_insight.reach
                insight.impressions = meta_insight.impressions
                insight.clicks = meta_insight.clicks
                insight.inline_link_clicks = meta_insight.inline_link_clicks
                insight.leads = meta_insight.leads
                insight.frequency = meta_insight.frequency
                insight.meta_ctr = meta_insight.meta_ctr
                insight.meta_cpc = meta_insight.meta_cpc
                insight.meta_cpm = meta_insight.meta_cpm
                insight.raw_actions = meta_insight.raw_actions
                insight.raw_cost_per_action_type = (
                    meta_insight.raw_cost_per_action_type
                )
                insight.raw_response = meta_insight.raw_response
                insight.synced_at = synced_at

    def _finish_run(
        self,
        sync_run_id: int,
        status: SyncStatus,
        finished_at: datetime,
        *,
        campaign_count: int,
        record_count: int,
    ) -> None:
        with self._session_factory.begin() as session:
            sync_run = session.get(SyncRun, sync_run_id)
            if sync_run is None:
                raise RuntimeError("sync run unavailable")
            sync_run.status = status
            sync_run.finished_at = finished_at
            sync_run.campaign_count = campaign_count
            sync_run.record_count = record_count
            sync_run.error_message = None if status is SyncStatus.SUCCESS else _FAILED_MESSAGE


def _parse_meta_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise SyncServiceError(_FAILED_MESSAGE, code="sync_failed") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SyncServiceError(_FAILED_MESSAGE, code="sync_failed")
    return parsed.astimezone(UTC)
