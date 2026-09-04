"""Deterministic, idempotent data seed for the isolated demo database."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select

from meta_kpi_calc.core.config import Settings
from meta_kpi_calc.db.models import (
    Campaign,
    CampaignBrand,
    CampaignInsight,
    EnrollmentRecord,
)
from meta_kpi_calc.db.session import Database

DEMO_START_DATE = date(2026, 8, 25)
DEMO_SYNCED_AT = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)

DEMO_CAMPAIGNS = (
    {
        "meta_campaign_id": "demo_rctec_001",
        "name": "[DEMO] RCTEC — Técnico em Enfermagem",
        "brand": CampaignBrand.RCTEC,
        "course": "Técnico em Enfermagem",
        "daily_spend": Decimal("125.50"),
    },
    {
        "meta_campaign_id": "demo_fecaf_001",
        "name": "[DEMO] FECAF — Administração",
        "brand": CampaignBrand.FECAF,
        "course": "Administração",
        "daily_spend": Decimal("98.75"),
    },
    {
        "meta_campaign_id": "demo_bolsa_001",
        "name": "[DEMO] Curso com Bolsa — Pedagogia",
        "brand": CampaignBrand.CURSO_COM_BOLSA,
        "course": "Pedagogia",
        "daily_spend": Decimal("76.25"),
    },
)


def seed_demo(settings: Settings) -> dict[str, int]:
    """Insert or update the fixed demo dataset in one transaction."""
    if not settings.demo_mode:
        raise ValueError("demo seed requires DEMO_MODE=true")

    database = Database(settings)
    try:
        with database.session_factory.begin() as session:
            for campaign_number, values in enumerate(DEMO_CAMPAIGNS, start=1):
                campaign = session.scalar(
                    select(Campaign).where(
                        Campaign.meta_campaign_id == values["meta_campaign_id"]
                    )
                )
                if campaign is None:
                    campaign = Campaign(
                        meta_campaign_id=values["meta_campaign_id"],
                        name=values["name"],
                    )
                    session.add(campaign)

                campaign.name = values["name"]
                campaign.status = "ACTIVE"
                campaign.effective_status = "ACTIVE"
                campaign.objective = "OUTCOME_LEADS"
                campaign.brand = values["brand"]
                campaign.course = values["course"]
                campaign.last_synced_at = DEMO_SYNCED_AT
                session.flush()

                for day_offset in range(7):
                    insight_date = DEMO_START_DATE + timedelta(days=day_offset)
                    insight = session.scalar(
                        select(CampaignInsight).where(
                            CampaignInsight.campaign_id == campaign.id,
                            CampaignInsight.date_start == insight_date,
                            CampaignInsight.date_stop == insight_date,
                        )
                    )
                    if insight is None:
                        insight = CampaignInsight(
                            campaign_id=campaign.id,
                            date_start=insight_date,
                            date_stop=insight_date,
                            synced_at=DEMO_SYNCED_AT,
                        )
                        session.add(insight)

                    impressions = 1000 + campaign_number * 100 + day_offset * 25
                    clicks = 40 + campaign_number * 5 + day_offset
                    insight.spend = values["daily_spend"] + Decimal(day_offset)
                    insight.reach = 800 + campaign_number * 75 + day_offset * 20
                    insight.impressions = impressions
                    insight.clicks = clicks
                    insight.inline_link_clicks = clicks - 5
                    insight.leads = 0 if day_offset == 0 else campaign_number + day_offset
                    insight.frequency = Decimal("1.250000")
                    insight.meta_ctr = (
                        Decimal(clicks) / Decimal(impressions) * Decimal("100")
                    ).quantize(Decimal("0.000001"))
                    insight.meta_cpc = (insight.spend / Decimal(clicks)).quantize(
                        Decimal("0.000001")
                    )
                    insight.meta_cpm = (
                        insight.spend / Decimal(impressions) * Decimal("1000")
                    ).quantize(Decimal("0.000001"))
                    insight.raw_actions = [
                        {"action_type": "lead", "value": str(insight.leads)}
                    ]
                    insight.raw_cost_per_action_type = []
                    insight.raw_response = {
                        "demo": True,
                        "campaign": values["meta_campaign_id"],
                        "date": insight_date.isoformat(),
                    }
                    insight.synced_at = DEMO_SYNCED_AT

                enrollment = session.scalar(
                    select(EnrollmentRecord).where(
                        EnrollmentRecord.campaign_id == campaign.id,
                        EnrollmentRecord.reference_date == DEMO_START_DATE,
                        EnrollmentRecord.course == values["course"],
                    )
                )
                if enrollment is None:
                    enrollment = EnrollmentRecord(
                        campaign_id=campaign.id,
                        reference_date=DEMO_START_DATE,
                        course=values["course"],
                    )
                    session.add(enrollment)

                if campaign_number == 1:
                    enrollment.contracted_enrollments = 0
                    enrollment.paying_enrollments = 0
                    enrollment.cancellations = 0
                    enrollment.expected_revenue = Decimal("0.00")
                    enrollment.received_revenue = Decimal("0.00")
                    enrollment.contribution_margin = Decimal("0.00")
                else:
                    enrollment.contracted_enrollments = campaign_number + 1
                    enrollment.paying_enrollments = campaign_number
                    enrollment.cancellations = campaign_number - 1
                    enrollment.expected_revenue = Decimal("4500.00") * campaign_number
                    enrollment.received_revenue = Decimal("3000.00") * campaign_number
                    enrollment.contribution_margin = Decimal("1500.00") * campaign_number
                enrollment.notes = "Dados fictícios para demonstração"

            session.flush()
            campaign_count = session.scalar(select(func.count(Campaign.id))) or 0
            insight_count = session.scalar(select(func.count(CampaignInsight.id))) or 0
            enrollment_count = (
                session.scalar(select(func.count(EnrollmentRecord.id))) or 0
            )
        return {
            "campaigns": campaign_count,
            "insights": insight_count,
            "enrollments": enrollment_count,
        }
    finally:
        database.engine.dispose()


def main() -> None:
    counts = seed_demo(Settings())
    print(
        "Demo seed complete: "
        f"{counts['campaigns']} campaigns, "
        f"{counts['insights']} insights, "
        f"{counts['enrollments']} enrollments"
    )


if __name__ == "__main__":
    main()
