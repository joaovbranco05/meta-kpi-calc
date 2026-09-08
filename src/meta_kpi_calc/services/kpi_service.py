"""Pure KPI calculations and read-only database aggregation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from meta_kpi_calc.db.models import (
    Campaign,
    CampaignBrand,
    CampaignInsight,
    EnrollmentRecord,
)
from meta_kpi_calc.services.report_filters import ReportFilters

KPI_PRECISION = Decimal("0.000001")
ZERO_MONEY = Decimal("0.00")


@dataclass(frozen=True)
class KpiTotals:
    spend: Decimal
    reach: int | None
    impressions: int
    clicks: int
    inline_link_clicks: int
    leads: int
    contracted_enrollments: int
    paying_enrollments: int
    cancellations: int
    expected_revenue: Decimal
    received_revenue: Decimal
    meta_ctr: Decimal | None
    meta_cpc: Decimal | None
    meta_cpm: Decimal | None
    frequency: Decimal | None
    insight_count: int
    qualified_leads: int | None = None


@dataclass(frozen=True)
class CalculatedKpis:
    calculated_ctr: Decimal | None
    calculated_cpc: Decimal | None
    calculated_cpm: Decimal | None
    cpl: Decimal | None
    contractual_conversion: Decimal | None
    financial_conversion: Decimal | None
    contractual_cac: Decimal | None
    financial_cac: Decimal | None
    expected_roas: Decimal | None
    received_roas: Decimal | None
    received_advertising_roi: Decimal | None
    qualification_rate: Decimal | None
    cpql: Decimal | None
    contract_to_paying_conversion: Decimal | None
    cancellation_rate: Decimal | None
    net_enrollments: int
    net_cac: Decimal | None
    expected_revenue_per_paying_enrollment: Decimal | None
    received_revenue_per_paying_enrollment: Decimal | None


@dataclass(frozen=True)
class KpiWarning:
    code: str
    message: str
    campaign_id: int | None = None
    meta_campaign_id: str | None = None
    campaign_course: str | None = None
    enrollment_course: str | None = None
    insight_id: int | None = None
    enrollment_record_id: int | None = None
    date_start: date | None = None
    date_stop: date | None = None
    reference_date: date | None = None


@dataclass(frozen=True)
class KpiSummary:
    date_start: date
    date_stop: date
    totals: KpiTotals
    kpis: CalculatedKpis
    warnings: tuple[KpiWarning, ...]


def _ratio(
    numerator: Decimal | int,
    denominator: Decimal | int,
    multiplier: Decimal = Decimal("1"),
) -> Decimal | None:
    if denominator == 0:
        return None
    value = Decimal(numerator) / Decimal(denominator) * multiplier
    return value.quantize(KPI_PRECISION, rounding=ROUND_HALF_UP)


def calculate_kpis(totals: KpiTotals) -> CalculatedKpis:
    """Calculate derived metrics without performing I/O or using floats."""
    percent = Decimal("100")
    thousand = Decimal("1000")
    net_enrollments = totals.contracted_enrollments - totals.cancellations
    return CalculatedKpis(
        calculated_ctr=_ratio(
            totals.inline_link_clicks, totals.impressions, percent
        ),
        calculated_cpc=_ratio(totals.spend, totals.inline_link_clicks),
        calculated_cpm=_ratio(totals.spend, totals.impressions, thousand),
        cpl=_ratio(totals.spend, totals.leads),
        contractual_conversion=_ratio(
            totals.contracted_enrollments, totals.leads, percent
        ),
        financial_conversion=_ratio(
            totals.paying_enrollments, totals.leads, percent
        ),
        contractual_cac=_ratio(totals.spend, totals.contracted_enrollments),
        financial_cac=_ratio(totals.spend, totals.paying_enrollments),
        expected_roas=_ratio(totals.expected_revenue, totals.spend),
        received_roas=_ratio(totals.received_revenue, totals.spend),
        received_advertising_roi=_ratio(
            totals.received_revenue - totals.spend, totals.spend, percent
        ),
        qualification_rate=(
            None
            if totals.qualified_leads is None
            else _ratio(totals.qualified_leads, totals.leads, percent)
        ),
        cpql=(
            None
            if totals.qualified_leads is None
            else _ratio(totals.spend, totals.qualified_leads)
        ),
        contract_to_paying_conversion=_ratio(
            totals.paying_enrollments, totals.contracted_enrollments, percent
        ),
        cancellation_rate=_ratio(
            totals.cancellations, totals.contracted_enrollments, percent
        ),
        net_enrollments=net_enrollments,
        net_cac=(
            _ratio(totals.spend, net_enrollments)
            if net_enrollments > 0
            else None
        ),
        expected_revenue_per_paying_enrollment=_ratio(
            totals.expected_revenue, totals.paying_enrollments
        ),
        received_revenue_per_paying_enrollment=_ratio(
            totals.received_revenue, totals.paying_enrollments
        ),
    )


def summarize_kpis(
    session: Session,
    date_start: date,
    date_stop: date,
    *,
    campaign_id: int | None = None,
    brand: CampaignBrand | None = None,
    course: str | None = None,
    effective_status: str | None = None,
) -> KpiSummary:
    """Aggregate additive fields for an inclusive period and calculate KPIs."""
    if date_start > date_stop:
        raise ValueError("date_start must be on or before date_stop")

    filters = ReportFilters(
        date_start=date_start,
        date_stop=date_stop,
        campaign_id=campaign_id,
        brand=brand,
        course=course,
        effective_status=effective_status,
    )
    campaign_filters = filters.campaign_predicates()
    insight_row = session.execute(
        select(
            func.count(CampaignInsight.id),
            func.sum(CampaignInsight.spend),
            func.sum(CampaignInsight.impressions),
            func.sum(CampaignInsight.clicks),
            func.sum(CampaignInsight.inline_link_clicks),
            func.sum(CampaignInsight.leads),
            func.count(CampaignInsight.qualified_leads),
            func.sum(CampaignInsight.qualified_leads),
            func.max(CampaignInsight.reach),
            func.max(CampaignInsight.frequency),
            func.max(CampaignInsight.meta_ctr),
            func.max(CampaignInsight.meta_cpc),
            func.max(CampaignInsight.meta_cpm),
        )
        .join(Campaign, Campaign.id == CampaignInsight.campaign_id)
        .where(
            CampaignInsight.date_start >= date_start,
            CampaignInsight.date_stop <= date_stop,
            *campaign_filters,
        )
    ).one()

    enrollment_row = session.execute(
        select(
            func.sum(EnrollmentRecord.contracted_enrollments),
            func.sum(EnrollmentRecord.paying_enrollments),
            func.sum(EnrollmentRecord.cancellations),
            func.sum(EnrollmentRecord.expected_revenue),
            func.sum(EnrollmentRecord.received_revenue),
        )
        .join(Campaign, Campaign.id == EnrollmentRecord.campaign_id)
        .where(
            EnrollmentRecord.reference_date.between(date_start, date_stop),
            *campaign_filters,
        )
    ).one()

    insight_count = int(insight_row[0])
    qualified_leads_count = int(insight_row[6])
    has_single_insight = insight_count == 1
    totals = KpiTotals(
        spend=insight_row[1] if insight_row[1] is not None else ZERO_MONEY,
        reach=int(insight_row[8]) if has_single_insight else None,
        impressions=int(insight_row[2] or 0),
        clicks=int(insight_row[3] or 0),
        inline_link_clicks=int(insight_row[4] or 0),
        leads=int(insight_row[5] or 0),
        contracted_enrollments=int(enrollment_row[0] or 0),
        paying_enrollments=int(enrollment_row[1] or 0),
        cancellations=int(enrollment_row[2] or 0),
        expected_revenue=(
            enrollment_row[3] if enrollment_row[3] is not None else ZERO_MONEY
        ),
        received_revenue=(
            enrollment_row[4] if enrollment_row[4] is not None else ZERO_MONEY
        ),
        meta_ctr=insight_row[10] if has_single_insight else None,
        meta_cpc=insight_row[11] if has_single_insight else None,
        meta_cpm=insight_row[12] if has_single_insight else None,
        frequency=insight_row[9] if has_single_insight else None,
        insight_count=insight_count,
        qualified_leads=(
            int(insight_row[7])
            if insight_count > 0 and qualified_leads_count == insight_count
            else None
        ),
    )

    warnings: list[KpiWarning] = []
    if insight_count > 1:
        warnings.append(
            KpiWarning(
                code="NON_ADDITIVE_METRICS_OMITTED",
                message=(
                    "Reach, frequency, and Meta-provided CTR/CPC/CPM are omitted "
                    "because they are not additive across multiple insight rows."
                ),
            )
        )

    if insight_count > 0 and qualified_leads_count < insight_count:
        warnings.append(
            KpiWarning(
                code="QUALIFIED_LEADS_INCOMPLETE",
                message=(
                    "Qualified leads are omitted because some selected insight "
                    "rows do not contain this measurement."
                ),
            )
        )

    qualified_lead_violations = session.execute(
        select(
            CampaignInsight.id,
            Campaign.id,
            Campaign.meta_campaign_id,
            CampaignInsight.date_start,
            CampaignInsight.date_stop,
        )
        .join(Campaign, Campaign.id == CampaignInsight.campaign_id)
        .where(
            CampaignInsight.date_start >= date_start,
            CampaignInsight.date_stop <= date_stop,
            CampaignInsight.qualified_leads > CampaignInsight.leads,
            *campaign_filters,
        )
        .order_by(CampaignInsight.date_start, CampaignInsight.id)
    ).all()
    warnings.extend(
        KpiWarning(
            code="QUALIFIED_LEADS_EXCEED_LEADS",
            message="Qualified leads exceed leads in this insight row.",
            insight_id=row[0],
            campaign_id=row[1],
            meta_campaign_id=row[2],
            date_start=row[3],
            date_stop=row[4],
        )
        for row in qualified_lead_violations
    )

    enrollment_violations = session.execute(
        select(
            EnrollmentRecord.id,
            Campaign.id,
            Campaign.meta_campaign_id,
            EnrollmentRecord.reference_date,
            EnrollmentRecord.course,
            EnrollmentRecord.cancellations,
            EnrollmentRecord.paying_enrollments,
            EnrollmentRecord.contracted_enrollments,
        )
        .join(Campaign, Campaign.id == EnrollmentRecord.campaign_id)
        .where(
            EnrollmentRecord.reference_date.between(date_start, date_stop),
            (
                (
                    EnrollmentRecord.cancellations
                    > EnrollmentRecord.contracted_enrollments
                )
                | (
                    EnrollmentRecord.paying_enrollments
                    > EnrollmentRecord.contracted_enrollments
                )
            ),
            *campaign_filters,
        )
        .order_by(EnrollmentRecord.reference_date, EnrollmentRecord.id)
    ).all()
    for row in enrollment_violations:
        warning_context = {
            "enrollment_record_id": row[0],
            "campaign_id": row[1],
            "meta_campaign_id": row[2],
            "reference_date": row[3],
            "enrollment_course": row[4],
        }
        if row[5] > row[7]:
            warnings.append(
                KpiWarning(
                    code="CANCELLATIONS_EXCEED_CONTRACTED",
                    message=(
                        "Cancellations exceed contracted enrollments in this record."
                    ),
                    **warning_context,
                )
            )
        if row[6] > row[7]:
            warnings.append(
                KpiWarning(
                    code="PAYING_EXCEEDS_CONTRACTED",
                    message=(
                        "Paying enrollments exceed contracted enrollments in this record."
                    ),
                    **warning_context,
                )
            )

    mismatches = session.execute(
        select(
            Campaign.id,
            Campaign.meta_campaign_id,
            Campaign.course,
            EnrollmentRecord.course,
        )
        .join(EnrollmentRecord, EnrollmentRecord.campaign_id == Campaign.id)
        .where(
            EnrollmentRecord.reference_date.between(date_start, date_stop),
            (Campaign.course.is_(None)) | (Campaign.course != EnrollmentRecord.course),
            *campaign_filters,
        )
        .distinct()
        .order_by(Campaign.id, EnrollmentRecord.course)
    ).all()
    warnings.extend(
        KpiWarning(
            code="COURSE_MISMATCH",
            message="Enrollment course differs from the campaign course.",
            campaign_id=row[0],
            meta_campaign_id=row[1],
            campaign_course=row[2],
            enrollment_course=row[3],
        )
        for row in mismatches
    )

    return KpiSummary(
        date_start=date_start,
        date_stop=date_stop,
        totals=totals,
        kpis=calculate_kpis(totals),
        warnings=tuple(warnings),
    )
