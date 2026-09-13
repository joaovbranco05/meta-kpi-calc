"""Local REST endpoints over the existing domain services and models."""

import logging
from csv import DictWriter
from datetime import date, datetime, time, timezone
from io import BytesIO, StringIO
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from meta_kpi_calc.api.dependencies import get_session
from meta_kpi_calc.api.schemas import (
    AccountResponse,
    CalculatedKpisResponse,
    CampaignResponse,
    CampaignComparisonResponse,
    ClassificationPatch,
    CommercialClosureResponse,
    CommercialClosureWrite,
    CommercialCoverageResponse,
    ConnectionResponse,
    DashboardFiltersResponse,
    DashboardDefaultPeriodResponse,
    DashboardSummaryResponse,
    EnrollmentResponse,
    EnrollmentWrite,
    InsightResponse,
    KpiTotalsResponse,
    KpiWarningResponse,
    Page,
    SyncRequest,
    SyncResponse,
    SyncStatusResponse,
)
from meta_kpi_calc.db.models import (
    Campaign,
    CampaignBrand,
    CampaignInsight,
    CommercialClosure,
    EnrollmentRecord,
    SyncRun,
    SyncStatus,
)
from meta_kpi_calc.services.meta_client import MetaClientError
from meta_kpi_calc.services.kpi_service import summarize_kpis
from meta_kpi_calc.services.report_filters import ReportFilters
from meta_kpi_calc.services.report_service import (
    report_campaigns,
    report_enrollments,
    report_insights,
)
from meta_kpi_calc.services.sync_service import SyncServiceError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")
SessionDependency = Annotated[Session, Depends(get_session)]
Offset = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=100)]


def _error(status_code: int, code: str, message: str, **detail: object) -> None:
    raise HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, **detail},
    )


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


def _validate_period(date_start: date | None, date_stop: date | None) -> None:
    if (date_start is None) != (date_stop is None) or (
        date_start is not None and date_stop is not None and date_start > date_stop
    ):
        _error(422, "validation_error", "Request validation failed.")


def _report_filters(
    date_start: date,
    date_stop: date,
    brand: CampaignBrand | None,
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


def _dashboard_summary(
    session: Session, filters: ReportFilters
) -> DashboardSummaryResponse:
    summary = summarize_kpis(
        session,
        filters.date_start,
        filters.date_stop,
        campaign_id=filters.campaign_id,
        brand=filters.brand,
        course=filters.course,
        effective_status=filters.effective_status,
    )
    last_media_sync_at = session.scalar(
        select(func.max(CampaignInsight.synced_at))
        .join(Campaign, Campaign.id == CampaignInsight.campaign_id)
        .where(
            CampaignInsight.date_start >= filters.date_start,
            CampaignInsight.date_stop <= filters.date_stop,
            *filters.campaign_predicates(),
        )
    )
    return DashboardSummaryResponse(
        filters=DashboardFiltersResponse(**vars(filters)),
        totals=KpiTotalsResponse(**vars(summary.totals)),
        kpis=CalculatedKpisResponse(**vars(summary.kpis)),
        commercial_coverage=CommercialCoverageResponse(
            **vars(summary.commercial_coverage)
        ),
        warnings=[KpiWarningResponse(**vars(warning)) for warning in summary.warnings],
        last_media_sync_at=last_media_sync_at,
    )


def _campaign_comparison(
    session: Session, filters: ReportFilters
) -> list[CampaignComparisonResponse]:
    """Return the same KPI aggregation for each campaign in the current scope."""
    campaigns = sorted(
        report_campaigns(session, filters), key=lambda campaign: (campaign.name, campaign.id)
    )
    rows: list[CampaignComparisonResponse] = []
    for campaign in campaigns:
        summary = summarize_kpis(
            session,
            filters.date_start,
            filters.date_stop,
            campaign_id=campaign.id,
            brand=filters.brand,
            course=filters.course,
            effective_status=filters.effective_status,
        )
        rows.append(
            CampaignComparisonResponse(
                id=campaign.id,
                meta_campaign_id=campaign.meta_campaign_id,
                name=campaign.name,
                brand=campaign.brand,
                course=campaign.course,
                effective_status=campaign.effective_status,
                spend=summary.totals.spend,
                leads=summary.totals.leads,
                contracted_enrollments=summary.totals.contracted_enrollments,
                paying_enrollments=summary.totals.paying_enrollments,
                financial_cac=summary.kpis.financial_cac,
                received_revenue=summary.totals.received_revenue,
                commercial_coverage=CommercialCoverageResponse(
                    **vars(summary.commercial_coverage)
                ),
            )
        )
    return rows


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


def _export_rows(
    session: Session, filters: ReportFilters
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    insight_rows = [
        _insight_response(insight, campaign.meta_campaign_id).model_dump()
        for insight, campaign in report_insights(session, filters)
    ]
    enrollment_rows = [
        _enrollment_response(enrollment, campaign.meta_campaign_id).model_dump()
        for enrollment, campaign in report_enrollments(session, filters)
    ]
    campaign_rows = [
        _campaign_response(campaign).model_dump()
        for campaign in report_campaigns(session, filters)
    ]
    return insight_rows, enrollment_rows, campaign_rows


def _meta_configured(request: Request) -> bool:
    settings = request.app.state.settings
    token = settings.meta_access_token
    return bool(
        token is not None
        and token.get_secret_value().strip()
        and settings.meta_ad_account_id is not None
    )


@router.get("/meta/connection", response_model=ConnectionResponse)
def meta_connection(request: Request) -> ConnectionResponse:
    settings = request.app.state.settings
    configured = _meta_configured(request)
    if settings.demo_mode or not configured:
        return ConnectionResponse(
            mode=settings.mode,
            configured=configured,
            connected=False,
            account=None,
        )
    try:
        account = request.app.state.meta_client.get_account()
    except MetaClientError:
        logger.warning("Meta connection check failed")
        _error(502, "meta_connection_failed", "Meta connection check failed.")
    return ConnectionResponse(
        mode=settings.mode,
        configured=True,
        connected=True,
        account=AccountResponse(**vars(account)),
    )


@router.post("/meta/sync", response_model=SyncResponse)
def sync_meta(payload: SyncRequest, request: Request) -> SyncResponse:
    service = request.app.state.sync_service
    if service is None:
        _error(503, "meta_sync_unavailable", "Meta synchronization is unavailable.")
    try:
        result = service.run_sync(
            payload.date_start,
            payload.date_stop,
            active_only=payload.active_only,
            meta_campaign_id=payload.meta_campaign_id,
        )
    except SyncServiceError as exc:
        if exc.code == "sync_in_progress":
            _error(409, "sync_in_progress", "A synchronization is already in progress.")
        if exc.code in {"demo_mode", "meta_not_configured"}:
            _error(503, "meta_sync_unavailable", "Meta synchronization is unavailable.")
        if exc.code in {
            "invalid_date_range",
            "future_date",
            "invalid_campaign_filter",
        }:
            _error(422, exc.code, "Synchronization request is invalid.")
        detail = {"sync_run_id": exc.sync_run_id} if exc.sync_run_id is not None else {}
        _error(502, "meta_sync_failed", "Meta synchronization failed.", **detail)
    return SyncResponse(**vars(result))


@router.get("/meta/sync/status", response_model=SyncStatusResponse)
def sync_status(session: SessionDependency) -> SyncStatusResponse:
    """Read the latest persisted synchronization state without calling Meta."""
    run = session.scalar(
        select(SyncRun).order_by(SyncRun.started_at.desc(), SyncRun.id.desc())
    )
    if run is None:
        return SyncStatusResponse(
            state="not_confirmed",
            started_at=None,
            finished_at=None,
            date_start=None,
            date_stop=None,
        )
    state = {
        SyncStatus.RUNNING: "running",
        SyncStatus.SUCCESS: "completed",
        SyncStatus.FAILED: "failed",
    }[run.status]
    return SyncStatusResponse(
        state=state,
        started_at=run.started_at,
        finished_at=run.finished_at,
        date_start=run.date_start,
        date_stop=run.date_stop,
    )


@router.get("/dashboard/default-period", response_model=DashboardDefaultPeriodResponse)
def dashboard_default_period(session: SessionDependency) -> DashboardDefaultPeriodResponse:
    date_start, date_stop = session.execute(
        select(func.min(CampaignInsight.date_start), func.max(CampaignInsight.date_stop))
    ).one()
    return DashboardDefaultPeriodResponse(date_start=date_start, date_stop=date_stop)


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


def _enrollment_duplicate(
    session: Session,
    payload: EnrollmentWrite,
    *,
    excluding_id: int | None = None,
) -> int | None:
    query = select(EnrollmentRecord.id).where(
        EnrollmentRecord.campaign_id == payload.campaign_id,
        EnrollmentRecord.reference_date == payload.reference_date,
        EnrollmentRecord.course == payload.course,
    )
    if excluding_id is not None:
        query = query.where(EnrollmentRecord.id != excluding_id)
    return session.scalar(query)


def _apply_enrollment(
    enrollment: EnrollmentRecord, payload: EnrollmentWrite
) -> None:
    for field, value in payload.model_dump().items():
        setattr(enrollment, field, value)


@router.post(
    "/enrollments", response_model=EnrollmentResponse, status_code=status.HTTP_201_CREATED
)
def create_enrollment(
    payload: EnrollmentWrite, session: SessionDependency
) -> EnrollmentResponse:
    try:
        with session.begin():
            campaign = session.get(Campaign, payload.campaign_id)
            if campaign is None:
                _error(404, "campaign_not_found", "Campaign was not found.")
            duplicate_id = _enrollment_duplicate(session, payload)
            if duplicate_id is not None:
                _error(
                    409,
                    "duplicate_enrollment",
                    "Enrollment already exists; use PUT to update it.",
                    record_id=duplicate_id,
                )
            enrollment = EnrollmentRecord(**payload.model_dump())
            session.add(enrollment)
            session.flush()
            response = _enrollment_response(enrollment, campaign.meta_campaign_id)
        return response
    except IntegrityError:
        _error(
            409,
            "duplicate_enrollment",
            "Enrollment already exists; use PUT to update it.",
        )


@router.get("/enrollments", response_model=Page[EnrollmentResponse])
def list_enrollments(
    session: SessionDependency,
    campaign_id: int | None = None,
    brand: CampaignBrand | None = None,
    course: str | None = None,
    effective_status: str | None = None,
    date_start: date | None = None,
    date_stop: date | None = None,
    offset: Offset = 0,
    limit: Limit = 50,
) -> Page[EnrollmentResponse]:
    _validate_period(date_start, date_stop)
    if course is not None:
        course = course.strip()
        if not course:
            _error(422, "validation_error", "Request validation failed.")
    if effective_status is not None:
        effective_status = effective_status.strip()
        if not effective_status:
            _error(422, "validation_error", "Request validation failed.")
    filters = []
    if campaign_id is not None:
        filters.append(EnrollmentRecord.campaign_id == campaign_id)
    if brand is not None:
        filters.append(Campaign.brand == brand)
    if course is not None:
        filters.append(EnrollmentRecord.course == course)
    if effective_status is not None:
        filters.append(Campaign.effective_status == effective_status)
    if date_start is not None and date_stop is not None:
        filters.append(EnrollmentRecord.reference_date.between(date_start, date_stop))
    base = select(EnrollmentRecord, Campaign.meta_campaign_id).join(
        Campaign, Campaign.id == EnrollmentRecord.campaign_id
    ).where(*filters)
    total = session.scalar(
        select(func.count(EnrollmentRecord.id))
        .join(Campaign, Campaign.id == EnrollmentRecord.campaign_id)
        .where(*filters)
    ) or 0
    rows = session.execute(
        base.order_by(EnrollmentRecord.id).offset(offset).limit(limit)
    ).all()
    return Page(
        items=[_enrollment_response(item, meta_id) for item, meta_id in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.put(
    "/commercial-closures/{campaign_id}/{reference_date}",
    response_model=CommercialClosureResponse,
)
def replace_commercial_closure(
    campaign_id: int,
    reference_date: date,
    payload: CommercialClosureWrite,
    session: SessionDependency,
) -> CommercialClosureResponse:
    try:
        with session.begin():
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                _error(404, "campaign_not_found", "Campaign was not found.")
            closure = session.scalar(
                select(CommercialClosure).where(
                    CommercialClosure.campaign_id == campaign_id,
                    CommercialClosure.reference_date == reference_date,
                )
            )
            if closure is None:
                closure = CommercialClosure(
                    campaign_id=campaign_id,
                    reference_date=reference_date,
                    status=payload.status,
                )
                session.add(closure)
            else:
                closure.status = payload.status
            session.flush()
            response = _commercial_closure_response(closure, campaign.meta_campaign_id)
        return response
    except IntegrityError:
        closure = session.scalar(
            select(CommercialClosure).where(
                CommercialClosure.campaign_id == campaign_id,
                CommercialClosure.reference_date == reference_date,
            )
        )
        if closure is None:
            raise
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise
        return _commercial_closure_response(closure, campaign.meta_campaign_id)


@router.put("/enrollments/{record_id}", response_model=EnrollmentResponse)
def replace_enrollment(
    record_id: int,
    payload: EnrollmentWrite,
    session: SessionDependency,
) -> EnrollmentResponse:
    try:
        with session.begin():
            enrollment = session.get(EnrollmentRecord, record_id)
            if enrollment is None:
                _error(404, "enrollment_not_found", "Enrollment was not found.")
            campaign = session.get(Campaign, payload.campaign_id)
            if campaign is None:
                _error(404, "campaign_not_found", "Campaign was not found.")
            duplicate_id = _enrollment_duplicate(
                session, payload, excluding_id=record_id
            )
            if duplicate_id is not None:
                _error(
                    409,
                    "duplicate_enrollment",
                    "Enrollment already exists.",
                    record_id=duplicate_id,
                )
            _apply_enrollment(enrollment, payload)
            session.flush()
            response = _enrollment_response(enrollment, campaign.meta_campaign_id)
        return response
    except IntegrityError:
        _error(409, "duplicate_enrollment", "Enrollment already exists.")


@router.get("/dashboard/summary", response_model=DashboardSummaryResponse)
def dashboard_summary(
    session: SessionDependency,
    date_start: date,
    date_stop: date,
    brand: CampaignBrand | None = None,
    campaign_id: int | None = None,
    course: str | None = None,
    effective_status: str | None = None,
) -> DashboardSummaryResponse:
    filters = _report_filters(
        date_start,
        date_stop,
        brand,
        campaign_id,
        course,
        effective_status,
    )
    return _dashboard_summary(session, filters)


@router.get(
    "/dashboard/campaign-comparison",
    response_model=list[CampaignComparisonResponse],
)
def dashboard_campaign_comparison(
    session: SessionDependency,
    date_start: date,
    date_stop: date,
    brand: CampaignBrand | None = None,
    campaign_id: int | None = None,
    course: str | None = None,
    effective_status: str | None = None,
) -> list[CampaignComparisonResponse]:
    filters = _report_filters(
        date_start,
        date_stop,
        brand,
        campaign_id,
        course,
        effective_status,
    )
    return _campaign_comparison(session, filters)


@router.get("/export")
def export_report(
    session: SessionDependency,
    date_start: date,
    date_stop: date,
    format: Annotated[str, Query(pattern="^(csv|xlsx)$")],
    dataset: Annotated[str, Query(pattern="^(performance|enrollments)$")],
    brand: CampaignBrand | None = None,
    campaign_id: int | None = None,
    course: str | None = None,
    effective_status: str | None = None,
) -> Response:
    filters = _report_filters(
        date_start,
        date_stop,
        brand,
        campaign_id,
        course,
        effective_status,
    )
    insights, enrollments, _campaigns = _export_rows(session, filters)
    if format == "csv":
        rows = insights if dataset == "performance" else enrollments
        output = StringIO(newline="")
        headers = list(rows[0]) if rows else (
            list(InsightResponse.model_fields)
            if dataset == "performance"
            else list(EnrollmentResponse.model_fields)
        )
        writer = DictWriter(output, fieldnames=headers)
        writer.writeheader()
        writer.writerows(
            {
                key: _safe_export_value(value)
                for key, value in row.items()
            }
            for row in rows
        )
        filename = f"meta-kpi-{dataset}.csv"
        return Response(
            content=output.getvalue().encode("utf-8-sig"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    summary = _dashboard_summary(session, filters).model_dump()
    comparison_rows = []
    for item in _campaign_comparison(session, filters):
        row = item.model_dump()
        coverage = row.pop("commercial_coverage")
        assert isinstance(coverage, dict)
        comparison_rows.append(
            {
                **row,
                "commercial_coverage_status": coverage["status"],
                "commercial_coverage_expected_units": coverage["expected_units"],
                "commercial_coverage_unknown_units": coverage["unknown_units"],
                "commercial_coverage_partial_units": coverage["partial_units"],
                "commercial_coverage_complete_units": coverage["complete_units"],
            }
        )
    workbook = Workbook()
    workbook.remove(workbook.active)
    summary_rows = [
        {"section": "filters", **summary["filters"]},
        {"section": "totals", **summary["totals"]},
        {"section": "kpis", **summary["kpis"]},
        {"section": "commercial_coverage", **summary["commercial_coverage"]},
        *[{"section": "warning", **warning} for warning in summary["warnings"]],
    ]
    _write_sheet(workbook, "Resumo", summary_rows)
    _write_sheet(workbook, "Diário", insights)
    _write_sheet(workbook, "Matrículas", enrollments)
    _write_sheet(workbook, "Campanhas", comparison_rows)
    output = BytesIO()
    workbook.save(output)
    return Response(
        content=output.getvalue(),
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": 'attachment; filename="meta-kpi-report.xlsx"'
        },
    )
