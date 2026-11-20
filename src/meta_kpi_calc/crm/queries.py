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
    assigned_user_id: int | None = None,
    unassigned: bool = False,
) -> tuple[list[Lead], int]:
    predicates = []
    if assigned_user_id is not None:
        predicates.append(Lead.assigned_user_id == assigned_user_id)
    if unassigned:
        predicates.append(Lead.assigned_user_id.is_(None))
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


def list_lead_activities(
    session: Session, lead_id: int, *, assigned_user_id: int | None = None
) -> list[LeadActivity] | None:
    # The outer join distinguishes an authorized lead without history from an
    # inaccessible lead, using the same database snapshot for scope and data.
    statement = (
        select(Lead.id, LeadActivity)
        .outerjoin(LeadActivity, LeadActivity.lead_id == Lead.id)
        .where(Lead.id == lead_id)
        .order_by(LeadActivity.created_at, LeadActivity.id)
    )
    if assigned_user_id is not None:
        statement = statement.where(Lead.assigned_user_id == assigned_user_id)
    rows = session.execute(statement).all()
    if not rows:
        return None
    return [activity for _, activity in rows if activity is not None]
