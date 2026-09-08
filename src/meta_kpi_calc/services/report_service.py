"""Read-only report rows derived from the same dashboard filter scope."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from meta_kpi_calc.db.models import Campaign, CampaignInsight, EnrollmentRecord
from meta_kpi_calc.services.report_filters import ReportFilters


def report_campaigns(session: Session, filters: ReportFilters) -> list[Campaign]:
    return list(
        session.scalars(
            select(Campaign)
            .where(*filters.campaign_predicates())
            .order_by(Campaign.id)
        )
    )


def report_insights(
    session: Session, filters: ReportFilters
) -> list[tuple[CampaignInsight, Campaign]]:
    return list(
        session.execute(
            select(CampaignInsight, Campaign)
            .join(Campaign, Campaign.id == CampaignInsight.campaign_id)
            .where(
                CampaignInsight.date_start >= filters.date_start,
                CampaignInsight.date_stop <= filters.date_stop,
                *filters.campaign_predicates(),
            )
            .order_by(CampaignInsight.date_start, CampaignInsight.id)
        )
    )


def report_enrollments(
    session: Session, filters: ReportFilters
) -> list[tuple[EnrollmentRecord, Campaign]]:
    return list(
        session.execute(
            select(EnrollmentRecord, Campaign)
            .join(Campaign, Campaign.id == EnrollmentRecord.campaign_id)
            .where(
                EnrollmentRecord.reference_date.between(
                    filters.date_start, filters.date_stop
                ),
                *filters.campaign_predicates(),
            )
            .order_by(EnrollmentRecord.reference_date, EnrollmentRecord.id)
        )
    )
