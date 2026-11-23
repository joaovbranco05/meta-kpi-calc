"""CRM routes scoped to the authenticated operator."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from meta_kpi_calc.auth.admin import lock_user_management
from meta_kpi_calc.auth.dependencies import CurrentAdmin, CurrentUser, SessionDependency
from meta_kpi_calc.auth.models import AdminAudit, AppUser
from meta_kpi_calc.crm.ingestion import add_lead_activity, change_lead_status
from meta_kpi_calc.crm.models import (
    Lead,
    LeadActivity,
    LeadActivityActor,
    LeadActivityType,
    LeadStatus,
)
from meta_kpi_calc.crm.queries import get_lead as load_lead
from meta_kpi_calc.crm.queries import list_lead_activities
from meta_kpi_calc.crm.queries import list_leads as query_leads

router = APIRouter(prefix="/api/crm", tags=["CRM"])


class CRMModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class LeadResponse(CRMModel):
    id: int
    meta_lead_id: str
    full_name: str | None
    phone_number: str | None
    email: str | None
    city: str | None
    state: str | None
    meta_created_time: datetime | None
    meta_page_id: str | None
    meta_campaign_id: str | None
    meta_campaign_name: str | None
    meta_adset_id: str | None
    meta_adset_name: str | None
    meta_ad_id: str | None
    meta_ad_name: str | None
    meta_form_id: str | None
    meta_form_name: str | None
    is_organic: bool | None
    platform: str | None
    source_status: str | None
    source: str
    course: str | None
    campaign_id: int | None
    assigned_user_id: int | None
    assigned_user_display_name: str | None
    commercial_status: LeadStatus
    last_contact_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ActivityResponse(CRMModel):
    id: int
    lead_id: int
    activity_type: LeadActivityType
    actor_type: LeadActivityActor
    actor_id: str | None
    actor_user_id: int | None
    actor_display_name: str | None
    previous_status: LeadStatus | None
    new_status: LeadStatus | None
    note: str | None
    changed_fields: str | None
    created_at: datetime


class Page(CRMModel):
    items: list[LeadResponse]
    total: int
    offset: int
    limit: int


class StatusPatch(CRMModel):
    commercial_status: LeadStatus


class ActivityCreate(CRMModel):
    activity_type: LeadActivityType
    note: str | None = Field(default=None, max_length=4000)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("note cannot be blank")
        return value

    @model_validator(mode="after")
    def note_required_for_note_activity(self) -> "ActivityCreate":
        if self.activity_type == LeadActivityType.NOTE and self.note is None:
            raise ValueError("note is required")
        if self.activity_type in {LeadActivityType.IMPORTED, LeadActivityType.STATUS_CHANGED, LeadActivityType.SOURCE_CORRECTED}:
            raise ValueError("activity type is not available")
        return self


def _not_found() -> None:
    raise HTTPException(status_code=404, detail={"code": "lead_not_found", "message": "Lead was not found."})


def _scoped_lead(
    session: SessionDependency, lead_id: int, user: AppUser, *, writing: bool = False
) -> Lead:
    if writing:
        # Take the lead write lock and check ownership atomically with acquisition.
        claim = update(Lead).where(Lead.id == lead_id)
        if user.role == "usuario":
            claim = claim.where(Lead.assigned_user_id == user.id)
        if session.scalar(claim.values(updated_at=Lead.updated_at).returning(Lead.id)) is None:
            _not_found()
    lead = load_lead(session, lead_id)
    if lead is None or (user.role == "usuario" and lead.assigned_user_id != user.id):
        _not_found()
    return lead


@router.get("/leads", response_model=Page)
def list_leads(
    session: SessionDependency,
    user: CurrentUser,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    commercial_status: LeadStatus | None = None,
    campaign_id: Annotated[int | None, Query(gt=0)] = None,
    query: Annotated[str | None, Query(max_length=128)] = None,
    unassigned: bool = False,
) -> Page:
    if unassigned and user.role != "admin":
        raise HTTPException(403, "Administrator permission required")
    if query:
        query = query.strip()
    leads, total = query_leads(
        session,
        offset=offset,
        limit=limit,
        commercial_status=commercial_status,
        campaign_id=campaign_id,
        query=query,
        assigned_user_id=user.id if user.role == "usuario" else None,
        unassigned=unassigned,
    )
    return Page(items=[LeadResponse.model_validate(lead, from_attributes=True) for lead in leads], total=total, offset=offset, limit=limit)


@router.get("/leads/{lead_id}", response_model=LeadResponse)
def get_lead(lead_id: int, session: SessionDependency, user: CurrentUser) -> LeadResponse:
    lead = _scoped_lead(session, lead_id, user)
    return LeadResponse.model_validate(lead, from_attributes=True)


@router.patch("/leads/{lead_id}/status", response_model=LeadResponse)
def patch_lead_status(lead_id: int, payload: StatusPatch, session: SessionDependency, user: CurrentUser) -> LeadResponse:
    lead = _scoped_lead(session, lead_id, user, writing=True)
    try:
        change_lead_status(session, lead, payload.commercial_status, actor_user_id=user.id)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return LeadResponse.model_validate(lead, from_attributes=True)


@router.get("/leads/{lead_id}/activities", response_model=list[ActivityResponse])
def list_activities(lead_id: int, session: SessionDependency, user: CurrentUser) -> list[ActivityResponse]:
    rows = list_lead_activities(
        session, lead_id, assigned_user_id=user.id if user.role == "usuario" else None
    )
    if rows is None:
        _not_found()
    return [ActivityResponse.model_validate(row, from_attributes=True) for row in rows]


@router.post("/leads/{lead_id}/activities", response_model=ActivityResponse, status_code=status.HTTP_201_CREATED)
def create_activity(
    lead_id: int, payload: ActivityCreate, session: SessionDependency, user: CurrentUser,
    operation_id: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> ActivityResponse:
    lead = _scoped_lead(session, lead_id, user, writing=True)
    key = str(operation_id)
    lookup = select(LeadActivity).where(LeadActivity.idempotency_key == key)
    activity = session.scalar(lookup)
    if activity is None:
        try:
            with session.begin_nested():
                activity = add_lead_activity(
                    session, lead, payload.activity_type, payload.note,
                    actor_user_id=user.id, idempotency_key=key,
                )
        except IntegrityError:
            # A competing request on a different lead can race the lookup.
            # The unique index decides the winner without releasing our lead lock.
            activity = session.scalar(lookup)
            if activity is None:
                raise

    if (activity.lead_id, activity.actor_user_id, activity.activity_type, activity.note) != (
        lead_id, user.id, payload.activity_type, payload.note,
    ):
        raise HTTPException(409, "Idempotency key already used")
    result = ActivityResponse.model_validate(activity, from_attributes=True)
    session.commit()
    return result


class AssignmentPatch(CRMModel):
    assigned_user_id: int | None = Field(gt=0)
    expected_assigned_user_id: int | None = Field(default=None, gt=0)


@router.patch("/leads/{lead_id}/assignment", response_model=LeadResponse)
def assign_lead(
    lead_id: int, payload: AssignmentPatch, session: SessionDependency, admin: CurrentAdmin
) -> LeadResponse:
    lock_user_management(session, admin)
    lead = _scoped_lead(session, lead_id, admin, writing=True)
    previous = lead.assigned_user_id
    if "expected_assigned_user_id" in payload.model_fields_set and previous != payload.expected_assigned_user_id:
        raise HTTPException(409, "Lead assignment changed")
    target_id = payload.assigned_user_id
    target = None
    if target_id is not None:
        target = session.get(AppUser, target_id)
        if target is None or not target.active:
            raise HTTPException(404, "Active assignee not found")
    if previous != target_id:
        lead.assigned_user = target
        session.add(AdminAudit(
            actor_user_id=admin.id, target_user_id=target_id, lead_id=lead.id,
            action="lead_assigned",
            previous_value=str(previous) if previous is not None else None,
            new_value=str(target_id) if target_id is not None else None,
        ))
    session.flush()
    result = LeadResponse.model_validate(lead)
    session.commit()
    return result
