"""Authorized form scans with local UTC filtering and fenced durable checkpoints."""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import or_, update

from meta_kpi_calc.core.config import Settings
from meta_kpi_calc.db.upsert import insert_for_session
from meta_kpi_calc.crm.ingestion import ingest_lead
from meta_kpi_calc.crm.inbox import utcnow
from meta_kpi_calc.crm.inbox_models import ReconciliationState
from meta_kpi_calc.crm.lead_ads_client import LeadAdsError, MetaLeadAdsClient, meta_id
from meta_kpi_calc.crm.normalizer import normalize_lead


def _aware(value: datetime) -> datetime:
    """Persisted SQLite timestamps in this technical schema are UTC by contract."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _input_time(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise LeadAdsError("invalid_window")
    return value.astimezone(timezone.utc)


def reconcile_form(factory, client: MetaLeadAdsClient, settings: Settings, *,
                   form_id: str, start: datetime | None = None, end: datetime | None = None,
                   clock: Callable[[], datetime] = utcnow) -> dict[str, int]:
    form_id = meta_id(form_id)
    page_id = settings.lead_ads_authorized_sources.get(form_id)
    if page_id is None or page_id not in settings.lead_ads_allowed_page_ids:
        raise LeadAdsError("source_not_allowed")
    now = _input_time(clock())
    until = _input_time(end) if end is not None else now
    if until > now:
        raise LeadAdsError("invalid_window")
    explicit_start = _input_time(start) if start is not None else None
    token = uuid4().hex
    with factory.begin() as session:
        session.execute(insert_for_session(session, ReconciliationState).values(
            meta_page_id=page_id, meta_form_id=form_id,
        ).on_conflict_do_nothing(index_elements=[ReconciliationState.meta_page_id, ReconciliationState.meta_form_id]))
        row = session.execute(update(ReconciliationState).where(
            ReconciliationState.meta_page_id == page_id, ReconciliationState.meta_form_id == form_id,
            or_(ReconciliationState.lease_token.is_(None), ReconciliationState.lease_expires_at <= now),
        ).values(last_result="PROCESSING", lease_token=token,
                 lease_expires_at=now + timedelta(seconds=settings.lead_ads_lease_seconds),
                 last_run_at=now, processed_count=0, unmapped_fields=0, error_code=None,
        ).returning(ReconciliationState)).scalar_one_or_none()
        if row is None:
            raise LeadAdsError("reconciliation_in_progress")
        state_id = row.id
        previous = _aware(row.completed_until) if row.completed_until is not None else None
        since = explicit_start if explicit_start is not None else previous
        gap = (previous is not None and explicit_start is not None and
               explicit_start > previous + timedelta(seconds=settings.lead_ads_overlap_seconds))
        if since is None or since > until or gap or until - since > timedelta(days=settings.lead_ads_scan_max_days):
            # Invalid first scan must not leave a lease; the transaction rolls back.
            raise LeadAdsError("invalid_window")
    lower = since - timedelta(seconds=settings.lead_ads_overlap_seconds)
    counts = {"processed": 0, "created": 0, "unmapped_fields": 0, "pages": 0}

    def fenced(at: datetime):
        return (ReconciliationState.id == state_id,
                ReconciliationState.last_result == "PROCESSING",
                ReconciliationState.lease_token == token,
                ReconciliationState.lease_expires_at > at)

    try:
        for page in client.iter_form_lead_pages(form_id):
            # Client generator performs HTTP outside any Session/transaction.
            normalized = [normalize_lead(item, page_id=page_id, form_id=form_id) for item in page]
            at = _input_time(clock())
            with factory.begin() as session:
                refreshed = session.execute(update(ReconciliationState).where(*fenced(at)).values(
                    lease_expires_at=at + timedelta(seconds=settings.lead_ads_lease_seconds),
                )).rowcount
                if not refreshed:
                    raise LeadAdsError("lease_lost")
                for item in normalized:
                    timestamp = item.submission.values["meta_created_time"]
                    if lower <= timestamp <= until:
                        result = ingest_lead(session, item.submission)
                        counts["processed"] += 1
                        counts["created"] += int(result.created)
                        counts["unmapped_fields"] += item.unmapped_fields
                session.execute(update(ReconciliationState).where(*fenced(at)).values(
                    processed_count=counts["processed"], unmapped_fields=counts["unmapped_fields"],
                ))
            counts["pages"] += 1
        at = _input_time(clock())
        with factory.begin() as session:
            updated = session.execute(update(ReconciliationState).where(*fenced(at)).values(
                completed_until=max(until, previous) if previous else until,
                last_result="COMPLETED", last_success_at=at,
                lease_token=None, lease_expires_at=None, error_code=None,
            )).rowcount
            if not updated:
                raise LeadAdsError("lease_lost")
        return counts
    except LeadAdsError as error:
        with factory.begin() as session:
            session.execute(update(ReconciliationState).where(*fenced(_input_time(clock()))).values(
                last_result="FAILED", error_code=error.code, lease_token=None, lease_expires_at=None,
            ))
        raise
    # Database failures deliberately propagate. The lease expires and restart replays
    # committed pages, while completed_until remains unchanged.
