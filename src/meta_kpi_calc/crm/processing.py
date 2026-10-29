"""Explicit one-shot inbox worker; no HTTP while a database transaction is open."""

from collections.abc import Callable
from datetime import datetime

from meta_kpi_calc.core.config import Settings
from meta_kpi_calc.crm.inbox import claim_event, complete_event, fail_event, utcnow
from meta_kpi_calc.crm.lead_ads_client import LeadAdsError, MetaLeadAdsClient
from meta_kpi_calc.crm.normalizer import normalize_lead


def process_events(factory, client: MetaLeadAdsClient, settings: Settings, *,
                   max_events: int = 100, clock: Callable[[], datetime] = utcnow) -> dict[str, int]:
    if not 1 <= max_events <= 10000:
        raise ValueError("Worker limit is invalid.")
    counts = {"claimed": 0, "completed": 0, "failed_or_retry": 0, "lease_lost": 0, "unmapped_fields": 0}
    for _ in range(max_events):
        with factory.begin() as session:
            claim = claim_event(session, settings, clock())
        if claim is None:
            break
        counts["claimed"] += 1
        try:
            if claim.event.page_id not in settings.lead_ads_allowed_page_ids:
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
