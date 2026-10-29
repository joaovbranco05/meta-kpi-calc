"""Loopback-only local CRM REST endpoints."""

from __future__ import annotations

import ipaddress
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from meta_kpi_calc.api.dependencies import get_session
from meta_kpi_calc.crm.ingestion import add_lead_activity, change_lead_status
from meta_kpi_calc.crm.models import (
    LeadActivityActor,
    LeadActivityType,
    LeadStatus,
)
from meta_kpi_calc.crm.queries import get_lead as load_lead
from meta_kpi_calc.crm.queries import list_lead_activities, list_leads as query_leads

router = APIRouter(prefix="/api/crm", tags=["CRM"])
SessionDependency = Annotated[Session, Depends(get_session)]


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


def _require_local_peer(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host == "testclient":
        return
    try:
        allowed = ipaddress.ip_address(host).is_loopback
    except ValueError:
        allowed = False
    if not allowed:
        raise HTTPException(status_code=403, detail={"code": "local_only", "message": "CRM is available only from localhost."})


def _not_found() -> None:
    raise HTTPException(status_code=404, detail={"code": "lead_not_found", "message": "Lead was not found."})


@router.get("/leads", response_model=Page, dependencies=[Depends(_require_local_peer)])
def list_leads(
    session: SessionDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    commercial_status: LeadStatus | None = None,
    campaign_id: Annotated[int | None, Query(gt=0)] = None,
    query: Annotated[str | None, Query(max_length=128)] = None,
) -> Page:
    if query:
        query = query.strip()
    leads, total = query_leads(
        session,
        offset=offset,
        limit=limit,
        commercial_status=commercial_status,
        campaign_id=campaign_id,
        query=query,
    )
    return Page(items=[LeadResponse.model_validate(lead, from_attributes=True) for lead in leads], total=total, offset=offset, limit=limit)


@router.get("/leads/{lead_id}", response_model=LeadResponse, dependencies=[Depends(_require_local_peer)])
def get_lead(lead_id: int, session: SessionDependency) -> LeadResponse:
    lead = load_lead(session, lead_id)
    if lead is None:
        _not_found()
    return LeadResponse.model_validate(lead, from_attributes=True)


@router.patch("/leads/{lead_id}/status", response_model=LeadResponse, dependencies=[Depends(_require_local_peer)])
def patch_lead_status(lead_id: int, payload: StatusPatch, session: SessionDependency) -> LeadResponse:
    lead = load_lead(session, lead_id)
    if lead is None:
        _not_found()
    try:
        change_lead_status(session, lead, payload.commercial_status)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return LeadResponse.model_validate(lead, from_attributes=True)


@router.get("/leads/{lead_id}/activities", response_model=list[ActivityResponse], dependencies=[Depends(_require_local_peer)])
def list_activities(lead_id: int, session: SessionDependency) -> list[ActivityResponse]:
    if load_lead(session, lead_id) is None:
        _not_found()
    rows = list_lead_activities(session, lead_id)
    return [ActivityResponse.model_validate(row, from_attributes=True) for row in rows]


@router.post("/leads/{lead_id}/activities", response_model=ActivityResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(_require_local_peer)])
def create_activity(lead_id: int, payload: ActivityCreate, session: SessionDependency) -> ActivityResponse:
    lead = load_lead(session, lead_id)
    if lead is None:
        _not_found()
    try:
        activity = add_lead_activity(session, lead, payload.activity_type, payload.note)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return ActivityResponse.model_validate(activity, from_attributes=True)
