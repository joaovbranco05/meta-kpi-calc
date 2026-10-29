"""Short, fenced database transactions for the Lead Ads inbox."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from meta_kpi_calc.core.config import Settings
from meta_kpi_calc.crm.ingestion import ingest_lead
from meta_kpi_calc.crm.inbox_models import WebhookEvent
from meta_kpi_calc.crm.lead_ads_client import LeadAdsError
from meta_kpi_calc.crm.normalizer import NormalizedLead


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class EventInput:
    lead_id: str
    page_id: str
    form_id: str | None = None
    ad_id: str | None = None


@dataclass(frozen=True)
class ClaimedEvent:
    id: int
    token: str
    event: EventInput
    attempts: int


def enqueue_events(session: Session, events: list[EventInput]) -> None:
    for event in events:
        session.execute(insert(WebhookEvent).values(
            dedup_key=f"meta:leadgen:{event.page_id}:{event.lead_id}",
            meta_lead_id=event.lead_id, meta_page_id=event.page_id,
            meta_form_id=event.form_id, meta_ad_id=event.ad_id,
        ).on_conflict_do_nothing(index_elements=[WebhookEvent.dedup_key]))


def _eligible(now: datetime):
    return or_(
        and_(WebhookEvent.status.in_(("PENDING", "RETRY")), WebhookEvent.next_attempt_at <= now),
        and_(WebhookEvent.status == "PROCESSING", WebhookEvent.lease_expires_at <= now),
    )


def claim_event(session: Session, settings: Settings, now: datetime) -> ClaimedEvent | None:
    """A single UPDATE/subquery is the claim, not a check-then-write sequence."""
    session.execute(update(WebhookEvent).where(
        _eligible(now), WebhookEvent.attempts >= settings.lead_ads_max_attempts,
    ).values(status="FAILED", lease_token=None, lease_expires_at=None,
             error_code="attempts_exhausted", updated_at=now))
    candidate = select(WebhookEvent.id).where(
        _eligible(now), WebhookEvent.attempts < settings.lead_ads_max_attempts,
    ).order_by(WebhookEvent.received_at, WebhookEvent.id).limit(1).scalar_subquery()
    token = uuid4().hex
    row = session.execute(update(WebhookEvent).where(
        WebhookEvent.id == candidate, _eligible(now),
        WebhookEvent.attempts < settings.lead_ads_max_attempts,
    ).values(status="PROCESSING", attempts=WebhookEvent.attempts + 1,
             lease_token=token, lease_expires_at=now + timedelta(seconds=settings.lead_ads_lease_seconds),
             updated_at=now, error_code=None).returning(WebhookEvent)).scalar_one_or_none()
    if row is None:
        return None
    return ClaimedEvent(row.id, token, EventInput(row.meta_lead_id, row.meta_page_id,
                                                row.meta_form_id, row.meta_ad_id), row.attempts)


def _fence(claim: ClaimedEvent, now: datetime):
    return and_(WebhookEvent.id == claim.id, WebhookEvent.status == "PROCESSING",
                WebhookEvent.lease_token == claim.token, WebhookEvent.lease_expires_at > now)


def complete_event(session: Session, claim: ClaimedEvent, normalized: NormalizedLead,
                   now: datetime) -> bool:
    updated = session.execute(update(WebhookEvent).where(_fence(claim, now)).values(
        status="COMPLETED", completed_at=now, updated_at=now, error_code=None,
        lease_token=None, lease_expires_at=None, unmapped_fields=normalized.unmapped_fields,
    )).rowcount
    if not updated:
        return False
    # This UPDATE acquired the SQLite write lock; ingestion and completion commit together.
    ingest_lead(session, normalized.submission)
    return True


def fail_event(session: Session, claim: ClaimedEvent, error: LeadAdsError,
               settings: Settings, now: datetime) -> bool:
    retry = error.transient and claim.attempts < settings.lead_ads_max_attempts
    delay = min(settings.lead_ads_retry_max_seconds, max(
        settings.lead_ads_retry_base_seconds * (2 ** (claim.attempts - 1)), error.retry_after))
    return bool(session.execute(update(WebhookEvent).where(_fence(claim, now)).values(
        status="RETRY" if retry else "FAILED", error_code=error.code,
        next_attempt_at=now + timedelta(seconds=delay), updated_at=now,
        lease_token=None, lease_expires_at=None,
    )).rowcount)
