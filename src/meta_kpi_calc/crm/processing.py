"""Explicit one-shot inbox worker; no HTTP while a database transaction is open."""

from collections.abc import Callable
from datetime import datetime

from sqlalchemy import func, select

from meta_kpi_calc.core.config import Settings
from meta_kpi_calc.crm.inbox import claim_event, complete_event, fail_event, utcnow
from meta_kpi_calc.crm.ingestion import ingest_lead
from meta_kpi_calc.crm.lead_ads_client import LeadAdsError, MetaLeadAdsClient, meta_id
from meta_kpi_calc.crm.models import Lead
from meta_kpi_calc.crm.normalizer import normalize_lead


def fetch_single_lead(factory, client: MetaLeadAdsClient, settings: Settings, *, lead_id: str) -> dict:
    """Fetch exactly one requested lead and ingest it only through its authorized form."""
    requested_id = meta_id(lead_id)
    payload = client.get_lead(requested_id)
    form_id = meta_id(payload.get("form_id"))
    page_id = settings.lead_ads_authorized_sources.get(form_id)
    if page_id is None or page_id not in settings.lead_ads_allowed_page_ids:
        raise LeadAdsError("source_not_allowed")

    normalized = normalize_lead(
        payload, page_id=page_id, form_id=form_id, lead_id=requested_id
    )
    with factory.begin() as session:
        before = session.scalar(select(func.count(Lead.id))) or 0
        ingested = ingest_lead(session, normalized.submission)
        after = session.scalar(select(func.count(Lead.id))) or 0

    history_created = ingested.created or bool(ingested.changed_fields)
    return {
        "outcome": "created" if ingested.created else "already_existed",
        "history_created": history_created,
        "activity_type": "IMPORTED" if ingested.created else (
            "SOURCE_CORRECTED" if ingested.changed_fields else None
        ),
        "changed_fields": list(ingested.changed_fields),
        "unmapped_fields": normalized.unmapped_fields,
        "lead_count_before": before,
        "lead_count_after": after,
        "lead_count_delta": after - before,
    }


def process_events(factory, client: MetaLeadAdsClient, settings: Settings, *,
                   max_events: int = 100, clock: Callable[[], datetime] = utcnow,
                   should_stop: Callable[[], bool] = lambda: False) -> dict[str, int]:
    if not 1 <= max_events <= 10000:
        raise ValueError("Worker limit is invalid.")
    counts = {"claimed": 0, "completed": 0, "failed_or_retry": 0, "lease_lost": 0, "unmapped_fields": 0}
    for _ in range(max_events):
        if should_stop():
            break
        with factory.begin() as session:
            claim = claim_event(session, settings, clock())
        if claim is None:
            break
        counts["claimed"] += 1
        try:
            source_is_allowed = (
                claim.event.page_id in settings.lead_ads_allowed_page_ids
                and claim.event.form_id is not None
                and settings.lead_ads_authorized_sources.get(claim.event.form_id)
                == claim.event.page_id
            )
            if not source_is_allowed:
                raise LeadAdsError("source_not_allowed")
            payload = client.get_lead(claim.event.lead_id)
            normalized = normalize_lead(payload, page_id=claim.event.page_id,
                                        form_id=claim.event.form_id, lead_id=claim.event.lead_id,
                                        ad_id=claim.event.ad_id)
        except LeadAdsError as error:
            with factory.begin() as session:
                applied = fail_event(session, claim, error, settings, clock())
            counts["failed_or_retry" if applied else "lease_lost"] += 1
            continue
        with factory.begin() as session:
            applied = complete_event(session, claim, normalized, clock())
        counts["completed" if applied else "lease_lost"] += 1
        if applied:
            counts["unmapped_fields"] += normalized.unmapped_fields
    return counts
