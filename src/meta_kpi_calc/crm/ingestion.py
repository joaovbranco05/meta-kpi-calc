"""Idempotent CRM lead ingestion and commercial activity services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from meta_kpi_calc.db.models import Campaign
from meta_kpi_calc.crm.models import (
    Lead,
    LeadActivity,
    LeadActivityActor,
    LeadActivityType,
    LeadStatus,
)


@dataclass(frozen=True)
class LeadSubmission:
    meta_lead_id: str
    values: dict[str, Any]


@dataclass(frozen=True)
class IngestResult:
    lead: Lead
    created: bool
    changed_fields: tuple[str, ...] = ()


SOURCE_FIELDS = (
    "full_name", "phone_number", "email", "city", "state", "meta_created_time",
    "meta_page_id", "meta_campaign_id", "meta_campaign_name", "meta_adset_id", "meta_adset_name",
    "meta_ad_id", "meta_ad_name", "meta_form_id", "meta_form_name", "source_status",
    "is_organic", "platform", "source",
)


def ingest_lead(session: Session, submission: LeadSubmission) -> IngestResult:
    """Insert once; on replay update only supplied source fields, preserving CRM state."""
    values = {key: value for key, value in submission.values.items() if key in SOURCE_FIELDS}
    values["meta_lead_id"] = submission.meta_lead_id
    meta_campaign_id = values.get("meta_campaign_id")
    campaign = None
    if meta_campaign_id:
        campaign = session.scalar(
            select(Campaign).where(Campaign.meta_campaign_id == meta_campaign_id)
        )
    if campaign is not None:
        values["campaign_id"] = campaign.id

    now = datetime.now(timezone.utc)
    stmt = sqlite_insert(Lead).values(**values).on_conflict_do_nothing(
        index_elements=[Lead.meta_lead_id]
    ).returning(Lead.id)
    inserted_id = session.scalar(stmt)
    if inserted_id is not None:
        session.flush()
        lead = session.get(Lead, inserted_id)
        assert lead is not None
        session.add(LeadActivity(
            lead_id=lead.id,
            activity_type=LeadActivityType.IMPORTED,
            actor_type=LeadActivityActor.SYSTEM_IMPORT,
        ))
        session.flush()
        return IngestResult(lead, True)

    lead = session.scalar(select(Lead).where(Lead.meta_lead_id == submission.meta_lead_id))
    if lead is None:
        # A concurrent delete is prohibited by the CRM and does not justify a silent insert retry.
        raise RuntimeError("Lead conflict could not be resolved.")
    changed: list[str] = []
    for field in SOURCE_FIELDS:
        value = values.get(field)
        current = getattr(lead, field)
        if field == "meta_created_time" and current is not None and value is not None:
            # SQLite reads timezone-aware columns as naive. Both ingestion sources
            # write UTC; compare instants so an identical replay creates no activity.
            current = current.replace(tzinfo=timezone.utc) if current.tzinfo is None else current.astimezone(timezone.utc)
            value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        if value is not None and current != value:
            setattr(lead, field, value)
            changed.append(field)
    if campaign is not None and lead.campaign_id != campaign.id:
        lead.campaign_id = campaign.id
        changed.append("campaign_id")
    if changed:
        lead.updated_at = now
        session.add(LeadActivity(
            lead_id=lead.id,
            activity_type=LeadActivityType.SOURCE_CORRECTED,
            actor_type=LeadActivityActor.SYSTEM_IMPORT,
            changed_fields=",".join(sorted(changed)),
        ))
    session.flush()
    return IngestResult(lead, False, tuple(sorted(changed)))


def change_lead_status(
    session: Session, lead: Lead, new_status: LeadStatus, *, actor_id: str | None = None
) -> Lead:
    if lead.commercial_status == new_status:
        return lead
    previous = lead.commercial_status
    lead.commercial_status = new_status
    session.add(LeadActivity(
        lead_id=lead.id,
        activity_type=LeadActivityType.STATUS_CHANGED,
        actor_type=LeadActivityActor.LOCAL_OPERATOR,
        actor_id=actor_id,
        previous_status=previous,
        new_status=new_status,
    ))
    session.flush()
    return lead


def add_lead_activity(
    session: Session,
    lead: Lead,
    activity_type: LeadActivityType,
    note: str | None,
) -> LeadActivity:
    if activity_type not in {
        LeadActivityType.NOTE,
        LeadActivityType.CONTACT_ATTEMPTED,
        LeadActivityType.CONTACT_MADE,
    }:
        raise ValueError("Activity type is not available to local operators.")
    activity = LeadActivity(
        lead_id=lead.id,
        activity_type=activity_type,
        actor_type=LeadActivityActor.LOCAL_OPERATOR,
        note=note,
    )
    session.add(activity)
    if activity_type == LeadActivityType.CONTACT_MADE:
        lead.last_contact_at = datetime.now(timezone.utc)
    session.flush()
    return activity
