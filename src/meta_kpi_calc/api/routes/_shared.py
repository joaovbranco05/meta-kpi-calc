"""Shared helpers, type aliases and response builders for REST route modules."""

from datetime import date
from typing import Annotated

from fastapi import Depends, HTTPException, Query
from openpyxl import Workbook
from sqlalchemy.orm import Session

from meta_kpi_calc.api.dependencies import get_session
from meta_kpi_calc.api.schemas import (
    CampaignResponse,
    CommercialClosureResponse,
    EnrollmentResponse,
    InsightResponse,
)
from meta_kpi_calc.db.models import (
    Campaign,
    CampaignInsight,
    CommercialClosure,
    EnrollmentRecord,
)
from meta_kpi_calc.services.report_filters import ReportFilters

# ---------------------------------------------------------------------------
# Common FastAPI dependency type aliases
# ---------------------------------------------------------------------------

SessionDependency = Annotated[Session, Depends(get_session)]
Offset = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=100)]


# ---------------------------------------------------------------------------
# Error helper
# ---------------------------------------------------------------------------

def _error(status_code: int, code: str, message: str, **detail: object) -> None:
    raise HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, **detail},
    )


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------

def _campaign_response(campaign: Campaign) -> CampaignResponse:
    return CampaignResponse(
        id=campaign.id,
        meta_campaign_id=campaign.meta_campaign_id,
        name=campaign.name,
        status=campaign.status,
        effective_status=campaign.effective_status,
        objective=campaign.objective,
        start_time=campaign.start_time,
        stop_time=campaign.stop_time,
        brand=campaign.brand,
        course=campaign.course,
        last_synced_at=campaign.last_synced_at,
        created_at=campaign.created_at,
        updated_at=campaign.updated_at,
    )


def _insight_response(
    insight: CampaignInsight, meta_campaign_id: str
) -> InsightResponse:
    return InsightResponse(
        id=insight.id,
        campaign_id=insight.campaign_id,
        meta_campaign_id=meta_campaign_id,
        date_start=insight.date_start,
        date_stop=insight.date_stop,
        spend=insight.spend,
        reach=insight.reach,
        impressions=insight.impressions,
        clicks=insight.clicks,
        inline_link_clicks=insight.inline_link_clicks,
        leads=insight.leads,
        qualified_leads=insight.qualified_leads,
        frequency=insight.frequency,
        meta_ctr=insight.meta_ctr,
        meta_cpc=insight.meta_cpc,
        meta_cpm=insight.meta_cpm,
        synced_at=insight.synced_at,
    )


def _enrollment_response(
    enrollment: EnrollmentRecord, meta_campaign_id: str
) -> EnrollmentResponse:
    return EnrollmentResponse(
        id=enrollment.id,
        campaign_id=enrollment.campaign_id,
        meta_campaign_id=meta_campaign_id,
        reference_date=enrollment.reference_date,
        course=enrollment.course,
        contracted_enrollments=enrollment.contracted_enrollments,
        paying_enrollments=enrollment.paying_enrollments,
        cancellations=enrollment.cancellations,
        expected_revenue=enrollment.expected_revenue,
        received_revenue=enrollment.received_revenue,
        contribution_margin=enrollment.contribution_margin,
        notes=enrollment.notes,
        created_at=enrollment.created_at,
        updated_at=enrollment.updated_at,
    )


def _commercial_closure_response(
    closure: CommercialClosure, meta_campaign_id: str
) -> CommercialClosureResponse:
    return CommercialClosureResponse(
        campaign_id=closure.campaign_id,
        meta_campaign_id=meta_campaign_id,
        reference_date=closure.reference_date,
        status=closure.status,
        created_at=closure.created_at,
        updated_at=closure.updated_at,
    )


# ---------------------------------------------------------------------------
# Filter and validation helpers
# ---------------------------------------------------------------------------

def _validate_period(date_start: date | None, date_stop: date | None) -> None:
    if (date_start is None) != (date_stop is None) or (
        date_start is not None and date_stop is not None and date_start > date_stop
    ):
        _error(422, "validation_error", "Request validation failed.")


def _report_filters(
    date_start: date,
    date_stop: date,
    brand,
    campaign_id: int | None,
    course: str | None,
    effective_status: str | None,
) -> ReportFilters:
    _validate_period(date_start, date_stop)
    if course is not None:
        course = course.strip()
        if not course:
            _error(422, "validation_error", "Request validation failed.")
    if effective_status is not None:
        effective_status = effective_status.strip()
        if not effective_status:
            _error(422, "validation_error", "Request validation failed.")
    return ReportFilters(
        date_start=date_start,
        date_stop=date_stop,
        brand=brand,
        campaign_id=campaign_id,
        course=course,
        effective_status=effective_status,
    )


def _validate_campaign_selection(
    campaign_ids: list[int] | None, campaign_id: int | None
) -> list[int]:
    if campaign_id is not None:
        _error(
            422,
            "invalid_campaign_selection",
            "Use campaign_ids for a multi-campaign comparison.",
        )
    selected = campaign_ids or []
    if len(selected) < 2 or len(set(selected)) != len(selected):
        _error(
            422,
            "invalid_campaign_selection",
            "Select at least two different campaigns.",
        )
    return selected


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def _safe_export_value(value: object) -> object:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return f"'{value}"
    return value


def _write_sheet(workbook: Workbook, title: str, rows: list[dict[str, object]]) -> None:
    sheet = workbook.create_sheet(title)
    if not rows:
        return
    headers = list(dict.fromkeys(key for row in rows for key in row))
    sheet.append(headers)
    for row in rows:
        sheet.append([_safe_export_value(row.get(header)) for header in headers])
