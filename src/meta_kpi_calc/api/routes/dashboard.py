"""Dashboard summary, campaign comparison and data export endpoints."""

from csv import DictWriter
from datetime import date
from io import BytesIO, StringIO
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import Response
from openpyxl import Workbook
from sqlalchemy import func, select

from meta_kpi_calc.api.dependencies import get_session
from meta_kpi_calc.api.schemas import (
    CalculatedKpisResponse,
    CampaignComparisonResponse,
    CommercialCoverageResponse,
    DashboardDefaultPeriodResponse,
    DashboardFiltersResponse,
    DashboardSummaryResponse,
    DetailedCampaignComparisonResponse,
    EnrollmentResponse,
    InsightResponse,
    KpiTotalsResponse,
    KpiWarningResponse,
)
from meta_kpi_calc.db.models import Campaign, CampaignBrand, CampaignInsight
from meta_kpi_calc.api.routes._shared import (
    SessionDependency,
    _error,
    _campaign_response,
    _enrollment_response,
    _insight_response,
    _report_filters,
    _safe_export_value,
    _validate_campaign_selection,
    _write_sheet,
)
from meta_kpi_calc.services.kpi_service import summarize_kpis
from meta_kpi_calc.services.report_filters import ReportFilters
from meta_kpi_calc.services.report_service import (
    report_campaigns,
    report_enrollments,
    report_insights,
)

router = APIRouter()


def _dashboard_summary(
    session, filters: ReportFilters
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
    session, filters: ReportFilters
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


def _detailed_campaign_comparison(
    session, filters: ReportFilters, campaign_ids: list[int]
) -> list[DetailedCampaignComparisonResponse]:
    """Return complete, independently calculated metrics in requested order."""
    campaigns = session.scalars(
        select(Campaign).where(
            Campaign.id.in_(campaign_ids), *filters.campaign_predicates()
        )
    ).all()
    by_id = {campaign.id: campaign for campaign in campaigns}
    missing = [campaign_id for campaign_id in campaign_ids if campaign_id not in by_id]
    if missing:
        _error(
            422,
            "invalid_campaign_selection",
            "Every selected campaign must be inside the active scope.",
            campaign_ids=missing,
        )

    rows: list[DetailedCampaignComparisonResponse] = []
    for campaign_id in campaign_ids:
        campaign = by_id[campaign_id]
        summary = summarize_kpis(
            session,
            filters.date_start,
            filters.date_stop,
            campaign_id=campaign.id,
            brand=filters.brand,
            course=filters.course,
            effective_status=filters.effective_status,
        )
        last_media_sync_at = session.scalar(
            select(func.max(CampaignInsight.synced_at))
            .where(
                CampaignInsight.campaign_id == campaign.id,
                CampaignInsight.date_start >= filters.date_start,
                CampaignInsight.date_stop <= filters.date_stop,
            )
        )
        rows.append(
            DetailedCampaignComparisonResponse(
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
                contribution_margin=None,
                totals=KpiTotalsResponse(**vars(summary.totals)),
                kpis=CalculatedKpisResponse(**vars(summary.kpis)),
                warnings=[
                    KpiWarningResponse(**vars(warning))
                    for warning in summary.warnings
                ],
                last_media_sync_at=last_media_sync_at,
                commercial_coverage=CommercialCoverageResponse(
                    **vars(summary.commercial_coverage)
                ),
            )
        )
    return rows


def _export_rows(
    session, filters: ReportFilters
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


@router.get("/dashboard/default-period", response_model=DashboardDefaultPeriodResponse)
def dashboard_default_period(session: SessionDependency) -> DashboardDefaultPeriodResponse:
    date_start, date_stop = session.execute(
        select(func.min(CampaignInsight.date_start), func.max(CampaignInsight.date_stop))
    ).one()
    return DashboardDefaultPeriodResponse(date_start=date_start, date_stop=date_stop)


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


@router.get(
    "/dashboard/campaign-comparison/detail",
    response_model=list[DetailedCampaignComparisonResponse],
)
def dashboard_campaign_comparison_detail(
    session: SessionDependency,
    date_start: date,
    date_stop: date,
    campaign_ids: Annotated[list[int] | None, Query()] = None,
    brand: CampaignBrand | None = None,
    campaign_id: int | None = None,
    course: str | None = None,
    effective_status: str | None = None,
) -> list[DetailedCampaignComparisonResponse]:
    selected = _validate_campaign_selection(campaign_ids, campaign_id)
    filters = _report_filters(
        date_start,
        date_stop,
        brand,
        None,
        course,
        effective_status,
    )
    return _detailed_campaign_comparison(session, filters, selected)


@router.get("/dashboard/campaign-comparison/export")
def export_campaign_comparison(
    session: SessionDependency,
    date_start: date,
    date_stop: date,
    campaign_ids: Annotated[list[int] | None, Query()] = None,
    brand: CampaignBrand | None = None,
    campaign_id: int | None = None,
    course: str | None = None,
    effective_status: str | None = None,
) -> Response:
    selected = _validate_campaign_selection(campaign_ids, campaign_id)
    filters = _report_filters(
        date_start,
        date_stop,
        brand,
        None,
        course,
        effective_status,
    )
    rows = [item.model_dump() for item in _detailed_campaign_comparison(session, filters, selected)]
    flattened: list[dict[str, object]] = []
    for row in rows:
        totals = row.pop("totals")
        kpis = row.pop("kpis")
        warnings = row.pop("warnings")
        coverage = row.pop("commercial_coverage")
        assert isinstance(totals, dict)
        assert isinstance(kpis, dict)
        assert isinstance(coverage, dict)
        row.update({f"total_{key}": value for key, value in totals.items()})
        row.update({f"kpi_{key}": value for key, value in kpis.items()})
        row.update({f"coverage_{key}": value for key, value in coverage.items()})
        row["warning_count"] = len(warnings) if isinstance(warnings, list) else 0
        row["warning_codes"] = (
            "; ".join(
                str(warning.get("code", ""))
                for warning in warnings
                if isinstance(warning, dict) and warning.get("code")
            )
            if isinstance(warnings, list)
            else ""
        )
        row["warning_messages"] = (
            "; ".join(
                str(warning.get("message", ""))
                for warning in warnings
                if isinstance(warning, dict) and warning.get("message")
            )
            if isinstance(warnings, list)
            else ""
        )
        row["contribution_margin"] = "Não agregada neste recorte"
        flattened.append(row)
    workbook = Workbook()
    workbook.remove(workbook.active)
    _write_sheet(workbook, "Comparação", flattened)
    output = BytesIO()
    workbook.save(output)
    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="meta-kpi-comparacao.xlsx"'
        },
    )


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
