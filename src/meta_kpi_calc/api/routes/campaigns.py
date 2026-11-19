"""Campaign and campaign insight endpoints."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from meta_kpi_calc.api.dependencies import get_session
from meta_kpi_calc.api.schemas import (
    CampaignResponse,
    ClassificationPatch,
    InsightResponse,
    Page,
)
from meta_kpi_calc.db.models import Campaign, CampaignBrand, CampaignInsight
from meta_kpi_calc.api.routes._shared import (
    SessionDependency,
    Offset,
    Limit,
    _error,
    _campaign_response,
    _insight_response,
    _validate_period,
)

router = APIRouter()


@router.get("/campaigns", response_model=Page[CampaignResponse])
def list_campaigns(
    session: SessionDependency,
    brand: CampaignBrand | None = None,
    effective_status: str | None = None,
    campaign_id: int | None = None,
    course: str | None = None,
    meta_campaign_id: str | None = None,
    date_start: date | None = None,
    date_stop: date | None = None,
    offset: Offset = 0,
    limit: Limit = 50,
) -> Page[CampaignResponse]:
    from meta_kpi_calc.services.report_filters import ReportFilters

    _validate_period(date_start, date_stop)
    if course is not None:
        course = course.strip()
        if not course:
            _error(422, "validation_error", "Request validation failed.")
    if effective_status is not None:
        effective_status = effective_status.strip()
        if not effective_status:
            _error(422, "validation_error", "Request validation failed.")
    report_filters = ReportFilters(
        date_start=date_start,
        date_stop=date_stop,
        brand=brand,
        campaign_id=campaign_id,
        course=course,
        effective_status=effective_status,
    )
    filters = []
    if meta_campaign_id is not None:
        filters.append(Campaign.meta_campaign_id == meta_campaign_id)
    filters.extend(report_filters.campaign_predicates())
    total = session.scalar(select(func.count(Campaign.id)).where(*filters)) or 0
    campaigns = session.scalars(
        select(Campaign).where(*filters).order_by(Campaign.id).offset(offset).limit(limit)
    ).all()
    return Page(
        items=[_campaign_response(campaign) for campaign in campaigns],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/campaigns/{campaign_id}", response_model=CampaignResponse)
def get_campaign(campaign_id: int, session: SessionDependency) -> CampaignResponse:
    campaign = session.get(Campaign, campaign_id)
    if campaign is None:
        _error(404, "campaign_not_found", "Campaign was not found.")
    return _campaign_response(campaign)


@router.patch(
    "/campaigns/{campaign_id}/classification", response_model=CampaignResponse
)
def classify_campaign(
    campaign_id: int,
    payload: ClassificationPatch,
    session: SessionDependency,
) -> CampaignResponse:
    with session.begin():
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            _error(404, "campaign_not_found", "Campaign was not found.")
        if "brand" in payload.model_fields_set:
            campaign.brand = payload.brand
        if "course" in payload.model_fields_set:
            campaign.course = payload.course
        session.flush()
        response = _campaign_response(campaign)
    return response


@router.get(
    "/campaigns/{campaign_id}/insights", response_model=Page[InsightResponse]
)
def list_campaign_insights(
    campaign_id: int,
    session: SessionDependency,
    date_start: date | None = None,
    date_stop: date | None = None,
    offset: Offset = 0,
    limit: Limit = 50,
) -> Page[InsightResponse]:
    campaign = session.get(Campaign, campaign_id)
    if campaign is None:
        _error(404, "campaign_not_found", "Campaign was not found.")
    _validate_period(date_start, date_stop)
    filters = [CampaignInsight.campaign_id == campaign_id]
    if date_start is not None and date_stop is not None:
        filters.extend(
            [
                CampaignInsight.date_start >= date_start,
                CampaignInsight.date_stop <= date_stop,
            ]
        )
    total = session.scalar(select(func.count(CampaignInsight.id)).where(*filters)) or 0
    insights = session.scalars(
        select(CampaignInsight)
        .where(*filters)
        .order_by(CampaignInsight.date_start, CampaignInsight.id)
        .offset(offset)
        .limit(limit)
    ).all()
    return Page(
        items=[_insight_response(item, campaign.meta_campaign_id) for item in insights],
        total=total,
        offset=offset,
        limit=limit,
    )
