"""Read-only lead list, detail, and activity queries."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from meta_kpi_calc.crm.models import Lead, LeadActivity, LeadStatus


def list_leads(
    session: Session,
    *,
    offset: int,
    limit: int,
    commercial_status: LeadStatus | None = None,
    campaign_id: int | None = None,
    query: str | None = None,
) -> tuple[list[Lead], int]:
    predicates = []
    if commercial_status is not None:
        predicates.append(Lead.commercial_status == commercial_status)
    if campaign_id is not None:
        predicates.append(Lead.campaign_id == campaign_id)
    if query:
        pattern = f"%{query}%"
        predicates.append(
            (Lead.full_name.ilike(pattern))
            | (Lead.email.ilike(pattern))
            | (Lead.phone_number.ilike(pattern))
            | (Lead.meta_lead_id == query)
        )
    total = session.scalar(select(func.count(Lead.id)).where(*predicates)) or 0
    items = session.scalars(
        select(Lead)
        .where(*predicates)
        .order_by(Lead.created_at.desc(), Lead.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return items, total


def get_lead(session: Session, lead_id: int) -> Lead | None:
    return session.get(Lead, lead_id)


def list_lead_activities(session: Session, lead_id: int) -> list[LeadActivity]:
    return session.scalars(
        select(LeadActivity)
        .where(LeadActivity.lead_id == lead_id)
        .order_by(LeadActivity.created_at, LeadActivity.id)
    ).all()
