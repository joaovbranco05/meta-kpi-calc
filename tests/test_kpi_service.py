from dataclasses import fields
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from meta_kpi_calc.core.config import Settings
from meta_kpi_calc.db.models import (
    Campaign,
    CampaignBrand,
    CampaignInsight,
    EnrollmentRecord,
)
from meta_kpi_calc.db.session import Database
from meta_kpi_calc.services.kpi_service import (
    CalculatedKpis,
    KpiTotals,
    calculate_kpis,
    summarize_kpis,
)

DAY_1 = date(2026, 9, 1)
DAY_2 = date(2026, 9, 2)


def make_totals(**overrides: object) -> KpiTotals:
    values: dict[str, object] = {
        "spend": Decimal("12.00"),
        "reach": 80,
        "impressions": 90,
        "clicks": 8,
        "inline_link_clicks": 6,
        "leads": 3,
        "contracted_enrollments": 2,
        "paying_enrollments": 1,
        "cancellations": 0,
        "expected_revenue": Decimal("30.00"),
        "received_revenue": Decimal("24.00"),
        "meta_ctr": None,
        "meta_cpc": None,
        "meta_cpm": None,
        "frequency": None,
        "insight_count": 1,
        "qualified_leads": 2,
    }
    values.update(overrides)
    return KpiTotals(**values)  # type: ignore[arg-type]


def add_campaign(
    session: Session,
    meta_id: str,
    *,
    brand: CampaignBrand = CampaignBrand.RCTEC,
    course: str | None = "Nursing",
) -> Campaign:
    campaign = Campaign(
        meta_campaign_id=meta_id,
        name=f"Campaign {meta_id}",
        brand=brand,
        course=course,
    )
    session.add(campaign)
    session.flush()
    return campaign


def add_insight(
    session: Session,
    campaign: Campaign,
    insight_date: date,
    *,
    spend: str,
    impressions: int,
    link_clicks: int,
    leads: int,
    qualified_leads: int | None = 0,
) -> None:
    session.add(
        CampaignInsight(
            campaign_id=campaign.id,
            date_start=insight_date,
            date_stop=insight_date,
            spend=Decimal(spend),
            reach=70,
            impressions=impressions,
            clicks=link_clicks + 2,
            inline_link_clicks=link_clicks,
            leads=leads,
            qualified_leads=qualified_leads,
            frequency=Decimal("1.250000"),
            meta_ctr=Decimal("7.500000"),
            meta_cpc=Decimal("1.600000"),
            meta_cpm=Decimal("120.000000"),
            synced_at=datetime.now(timezone.utc),
        )
    )


def add_enrollment(
    session: Session,
    campaign: Campaign,
    reference_date: date,
    *,
    course: str = "Nursing",
    contracted: int = 1,
    paying: int = 1,
    expected: str = "20.00",
    received: str = "15.00",
    cancellations: int = 1,
    contribution_margin: str | None = None,
) -> None:
    session.add(
        EnrollmentRecord(
            campaign_id=campaign.id,
            reference_date=reference_date,
            course=course,
            contracted_enrollments=contracted,
            paying_enrollments=paying,
            cancellations=cancellations,
            expected_revenue=Decimal(expected),
            received_revenue=Decimal(received),
            contribution_margin=(
                Decimal(contribution_margin)
                if contribution_margin is not None
                else None
            ),
        )
    )


def test_calculate_kpis_covers_all_formulas() -> None:
    kpis = calculate_kpis(make_totals())

    assert kpis.calculated_ctr == Decimal("6.666667")
    assert kpis.calculated_cpc == Decimal("2.000000")
    assert kpis.calculated_cpm == Decimal("133.333333")
    assert kpis.cpl == Decimal("4.000000")
    assert kpis.contractual_conversion == Decimal("66.666667")
    assert kpis.financial_conversion == Decimal("33.333333")
    assert kpis.contractual_cac == Decimal("6.000000")
    assert kpis.financial_cac == Decimal("12.000000")
    assert kpis.expected_roas == Decimal("2.500000")
    assert kpis.received_roas == Decimal("2.000000")
    assert kpis.received_advertising_roi == Decimal("100.000000")
    assert kpis.qualification_rate == Decimal("66.666667")
    assert kpis.cpql == Decimal("6.000000")
    assert kpis.contract_to_paying_conversion == Decimal("50.000000")
    assert kpis.cancellation_rate == Decimal("0.000000")
    assert kpis.net_enrollments == 2
    assert kpis.net_cac == Decimal("6.000000")
    assert kpis.expected_revenue_per_paying_enrollment == Decimal("30.000000")
    assert kpis.received_revenue_per_paying_enrollment == Decimal("24.000000")
    assert all(
        value is None or isinstance(value, Decimal)
        for name, value in vars(kpis).items()
        if name != "net_enrollments"
    )


def test_calculate_kpis_returns_none_for_every_zero_denominator() -> None:
    kpis = calculate_kpis(
        make_totals(
            spend=Decimal("0.00"),
            impressions=0,
            inline_link_clicks=0,
            leads=0,
            contracted_enrollments=0,
            paying_enrollments=0,
            qualified_leads=0,
        )
    )

    assert kpis.net_enrollments == 0
    assert all(
        getattr(kpis, field.name) is None
        for field in fields(kpis)
        if field.name != "net_enrollments"
    )


def test_rounds_half_up_to_six_places_without_intermediate_rounding() -> None:
    kpis = calculate_kpis(
        make_totals(
            spend=Decimal("1.00"),
            impressions=3,
            inline_link_clicks=3,
            leads=3,
            contracted_enrollments=3,
            paying_enrollments=3,
            expected_revenue=Decimal("1.00"),
            received_revenue=Decimal("1.00"),
        )
    )

    assert kpis.calculated_cpm == Decimal("333.333333")
    assert kpis.cpl == Decimal("0.333333")
    assert kpis.calculated_cpc == Decimal("0.333333")

    tie = calculate_kpis(make_totals(spend=Decimal("1.00"), leads=2_000_000))
    assert tie.cpl == Decimal("0.000001")


def test_new_kpis_preserve_unknown_and_non_positive_denominators() -> None:
    unknown = calculate_kpis(make_totals(qualified_leads=None))
    assert unknown.qualification_rate is None
    assert unknown.cpql is None

    no_net_enrollments = calculate_kpis(
        make_totals(
            contracted_enrollments=2,
            paying_enrollments=0,
            cancellations=2,
            qualified_leads=0,
        )
    )
    assert no_net_enrollments.qualification_rate == Decimal("0.000000")
    assert no_net_enrollments.cpql is None
    assert no_net_enrollments.contract_to_paying_conversion == Decimal("0.000000")
    assert no_net_enrollments.cancellation_rate == Decimal("100.000000")
    assert no_net_enrollments.net_enrollments == 0
    assert no_net_enrollments.net_cac is None
    assert no_net_enrollments.expected_revenue_per_paying_enrollment is None
    assert no_net_enrollments.received_revenue_per_paying_enrollment is None

    negative_net = calculate_kpis(
        make_totals(contracted_enrollments=1, cancellations=2)
    )
    assert negative_net.cancellation_rate == Decimal("200.000000")
    assert negative_net.net_enrollments == -1
    assert negative_net.net_cac is None

    no_contracts = calculate_kpis(
        make_totals(
            contracted_enrollments=0,
            paying_enrollments=2,
            cancellations=1,
        )
    )
    assert no_contracts.contract_to_paying_conversion is None
    assert no_contracts.cancellation_rate is None
    assert no_contracts.net_enrollments == -1
    assert no_contracts.net_cac is None

    no_spend = calculate_kpis(make_totals(spend=Decimal("0.00")))
    assert no_spend.cpql == Decimal("0.000000")
    assert no_spend.net_cac == Decimal("0.000000")
    assert no_spend.expected_roas is None
    assert no_spend.received_roas is None
    assert no_spend.received_advertising_roi is None


def test_new_kpis_round_half_up_without_floats() -> None:
    kpis = calculate_kpis(
        make_totals(
            spend=Decimal("1.00"),
            leads=6,
            qualified_leads=3,
            contracted_enrollments=6,
            paying_enrollments=3,
            cancellations=3,
            expected_revenue=Decimal("1.00"),
            received_revenue=Decimal("2.00"),
        )
    )

    assert kpis.cpql == Decimal("0.333333")
    assert kpis.expected_revenue_per_paying_enrollment == Decimal("0.333333")
    assert kpis.received_revenue_per_paying_enrollment == Decimal("0.666667")
    assert all(
        value is None or isinstance(value, (Decimal, int))
        for value in vars(kpis).values()
    )


def test_single_insight_preserves_meta_metrics_and_keeps_calculated_distinct(
    migrated_database: tuple[Settings, Database],
) -> None:
    _, database = migrated_database
    with database.session_factory.begin() as session:
        campaign = add_campaign(session, "single")
        add_insight(
            session,
            campaign,
            DAY_1,
            spend="12.00",
            impressions=100,
            link_clicks=10,
            leads=2,
        )

    with database.session_factory() as session:
        summary = summarize_kpis(session, DAY_1, DAY_1)

    assert summary.totals.reach == 70
    assert summary.totals.frequency == Decimal("1.250000")
    assert summary.totals.meta_ctr == Decimal("7.500000")
    assert summary.totals.meta_cpc == Decimal("1.600000")
    assert summary.totals.meta_cpm == Decimal("120.000000")
    assert summary.kpis.calculated_ctr == Decimal("10.000000")
    assert summary.kpis.calculated_cpc == Decimal("1.200000")
    assert summary.warnings == ()


def test_multiple_insights_sum_only_additive_metrics_and_warn_once(
    migrated_database: tuple[Settings, Database],
) -> None:
    _, database = migrated_database
    with database.session_factory.begin() as session:
        campaign = add_campaign(session, "multiple")
        add_insight(
            session,
            campaign,
            DAY_1,
            spend="10.10",
            impressions=100,
            link_clicks=8,
            leads=2,
            qualified_leads=1,
        )
        add_insight(
            session,
            campaign,
            DAY_2,
            spend="20.20",
            impressions=200,
            link_clicks=12,
            leads=3,
            qualified_leads=2,
        )

    with database.session_factory() as session:
        summary = summarize_kpis(session, DAY_1, DAY_2)

    assert summary.totals.spend == Decimal("30.30")
    assert summary.totals.impressions == 300
    assert summary.totals.clicks == 24
    assert summary.totals.inline_link_clicks == 20
    assert summary.totals.leads == 5
    assert summary.totals.qualified_leads == 3
    assert summary.totals.insight_count == 2
    assert summary.totals.reach is None
    assert summary.totals.frequency is None
    assert summary.totals.meta_ctr is None
    assert summary.totals.meta_cpc is None
    assert summary.totals.meta_cpm is None
    assert [warning.code for warning in summary.warnings] == [
        "NON_ADDITIVE_METRICS_OMITTED"
    ]
    assert summary.kpis.calculated_ctr == Decimal("6.666667")
    assert summary.kpis.qualification_rate == Decimal("60.000000")
    assert summary.kpis.cpql == Decimal("10.100000")


def test_insights_and_enrollments_are_not_multiplied_by_raw_join(
    migrated_database: tuple[Settings, Database],
) -> None:
    _, database = migrated_database
    with database.session_factory.begin() as session:
        campaign = add_campaign(session, "no-cartesian")
        add_insight(
            session,
            campaign,
            DAY_1,
            spend="10.00",
            impressions=100,
            link_clicks=5,
            leads=2,
        )
        add_insight(
            session,
            campaign,
            DAY_2,
            spend="20.00",
            impressions=200,
            link_clicks=10,
            leads=3,
        )
        add_enrollment(
            session,
            campaign,
            DAY_1,
            contracted=1,
            paying=1,
            expected="100.00",
            received="80.00",
        )
        add_enrollment(
            session,
            campaign,
            DAY_2,
            course="Medicine",
            contracted=2,
            paying=1,
            expected="200.00",
            received="120.00",
        )

    with database.session_factory() as session:
        summary = summarize_kpis(session, DAY_1, DAY_2)

    assert summary.totals.spend == Decimal("30.00")
    assert summary.totals.leads == 5
    assert summary.totals.contracted_enrollments == 3
    assert summary.totals.paying_enrollments == 2
    assert summary.totals.cancellations == 2
    assert summary.totals.expected_revenue == Decimal("300.00")
    assert summary.totals.received_revenue == Decimal("200.00")


def test_period_campaign_and_brand_filters_are_inclusive_and_conjunctive(
    migrated_database: tuple[Settings, Database],
) -> None:
    _, database = migrated_database
    with database.session_factory.begin() as session:
        rctec = add_campaign(session, "rctec", brand=CampaignBrand.RCTEC)
        fecaf = add_campaign(session, "fecaf", brand=CampaignBrand.FECAF)
        add_insight(
            session,
            rctec,
            DAY_1,
            spend="10.00",
            impressions=100,
            link_clicks=5,
            leads=2,
        )
        add_insight(
            session,
            rctec,
            DAY_2,
            spend="20.00",
            impressions=200,
            link_clicks=10,
            leads=3,
        )
        add_insight(
            session,
            fecaf,
            DAY_2,
            spend="40.00",
            impressions=400,
            link_clicks=20,
            leads=4,
        )
        add_enrollment(session, rctec, DAY_1)
        add_enrollment(session, rctec, DAY_2, course="Nursing 2")
        add_enrollment(session, fecaf, DAY_2, course="Business")
        rctec_id = rctec.id

    with database.session_factory() as session:
        day_one = summarize_kpis(session, DAY_1, DAY_1)
        filtered = summarize_kpis(
            session,
            DAY_1,
            DAY_2,
            campaign_id=rctec_id,
            brand=CampaignBrand.RCTEC,
        )
        excluded = summarize_kpis(
            session,
            DAY_1,
            DAY_2,
            campaign_id=rctec_id,
            brand=CampaignBrand.FECAF,
        )

    assert day_one.totals.spend == Decimal("10.00")
    assert day_one.totals.contracted_enrollments == 1
    assert filtered.totals.spend == Decimal("30.00")
    assert filtered.totals.contracted_enrollments == 2
    assert excluded.totals.insight_count == 0
    assert excluded.totals.contracted_enrollments == 0


def test_insight_must_be_fully_contained_in_period(
    migrated_database: tuple[Settings, Database],
) -> None:
    _, database = migrated_database
    with database.session_factory.begin() as session:
        campaign = add_campaign(session, "multi-day")
        session.add(
            CampaignInsight(
                campaign_id=campaign.id,
                date_start=DAY_1,
                date_stop=DAY_2,
                spend=Decimal("30.00"),
                synced_at=datetime.now(timezone.utc),
            )
        )

    with database.session_factory() as session:
        partial_period = summarize_kpis(session, DAY_1, DAY_1)
        full_period = summarize_kpis(session, DAY_1, DAY_2)

    assert partial_period.totals.insight_count == 0
    assert full_period.totals.insight_count == 1
    assert full_period.totals.spend == Decimal("30.00")


def test_inverted_period_fails_before_query(
    migrated_database: tuple[Settings, Database],
) -> None:
    _, database = migrated_database
    with database.session_factory() as session:
        with pytest.raises(ValueError, match="date_start"):
            summarize_kpis(session, DAY_2, DAY_1)


def test_course_mismatches_are_contextual_deduplicated_and_sorted(
    migrated_database: tuple[Settings, Database],
) -> None:
    _, database = migrated_database
    with database.session_factory.begin() as session:
        without_course = add_campaign(session, "none-course", course=None)
        matching = add_campaign(session, "matching", course="Nursing")
        second_mismatch = add_campaign(session, "law-campaign", course="Law")
        add_enrollment(
            session, second_mismatch, DAY_1, course="Business", received="10.00"
        )
        add_enrollment(
            session, without_course, DAY_1, course="Medicine", received="10.00"
        )
        add_enrollment(
            session, without_course, DAY_2, course="Medicine", received="20.00"
        )
        add_enrollment(
            session, matching, DAY_1, course="Nursing", received="30.00"
        )
        without_course_id = without_course.id
        second_mismatch_id = second_mismatch.id

    with database.session_factory() as session:
        summary = summarize_kpis(session, DAY_1, DAY_2)

    assert summary.totals.received_revenue == Decimal("70.00")
    assert [
        (warning.campaign_id, warning.enrollment_course)
        for warning in summary.warnings
    ] == [
        (without_course_id, "Medicine"),
        (second_mismatch_id, "Business"),
    ]
    first_warning = summary.warnings[0]
    assert first_warning.code == "COURSE_MISMATCH"
    assert first_warning.meta_campaign_id == "none-course"
    assert first_warning.campaign_course is None


def test_empty_database_returns_typed_zeros_and_none(
    migrated_database: tuple[Settings, Database],
) -> None:
    _, database = migrated_database
    with database.session_factory() as session:
        summary = summarize_kpis(session, DAY_1, DAY_2)

    assert summary.totals.spend == Decimal("0.00")
    assert summary.totals.expected_revenue == Decimal("0.00")
    assert summary.totals.received_revenue == Decimal("0.00")
    assert summary.totals.impressions == 0
    assert summary.totals.leads == 0
    assert summary.totals.qualified_leads is None
    assert summary.totals.contracted_enrollments == 0
    assert summary.totals.insight_count == 0
    assert summary.totals.reach is None
    assert summary.totals.frequency is None
    assert summary.kpis.net_enrollments == 0
    assert all(
        value is None
        for name, value in vars(summary.kpis).items()
        if name != "net_enrollments"
    )
    assert summary.warnings == ()


def test_incomplete_qualified_leads_are_not_partially_aggregated(
    migrated_database: tuple[Settings, Database],
) -> None:
    _, database = migrated_database
    with database.session_factory.begin() as session:
        campaign = add_campaign(session, "qualified-incomplete")
        add_insight(
            session,
            campaign,
            DAY_1,
            spend="10.00",
            impressions=100,
            link_clicks=5,
            leads=4,
            qualified_leads=2,
        )
        add_insight(
            session,
            campaign,
            DAY_2,
            spend="20.00",
            impressions=200,
            link_clicks=10,
            leads=6,
            qualified_leads=None,
        )

    with database.session_factory() as session:
        summary = summarize_kpis(session, DAY_1, DAY_2)

    assert summary.totals.leads == 10
    assert summary.totals.qualified_leads is None
    assert summary.kpis.qualification_rate is None
    assert summary.kpis.cpql is None
    assert [warning.code for warning in summary.warnings] == [
        "NON_ADDITIVE_METRICS_OMITTED",
        "QUALIFIED_LEADS_INCOMPLETE",
    ]


def test_all_unknown_qualified_leads_emit_one_incomplete_warning(
    migrated_database: tuple[Settings, Database],
) -> None:
    _, database = migrated_database
    with database.session_factory.begin() as session:
        campaign = add_campaign(session, "qualified-unknown")
        add_insight(
            session,
            campaign,
            DAY_1,
            spend="10.00",
            impressions=100,
            link_clicks=5,
            leads=4,
            qualified_leads=None,
        )

    with database.session_factory() as session:
        summary = summarize_kpis(session, DAY_1, DAY_1)

    assert summary.totals.qualified_leads is None
    assert [warning.code for warning in summary.warnings] == [
        "QUALIFIED_LEADS_INCOMPLETE"
    ]


def test_domain_inconsistencies_warn_with_record_context_without_clamping(
    migrated_database: tuple[Settings, Database],
) -> None:
    _, database = migrated_database
    with database.session_factory.begin() as session:
        campaign = add_campaign(session, "inconsistent")
        add_insight(
            session,
            campaign,
            DAY_1,
            spend="12.00",
            impressions=100,
            link_clicks=5,
            leads=2,
            qualified_leads=3,
        )
        add_enrollment(
            session,
            campaign,
            DAY_1,
            contracted=1,
            paying=3,
            cancellations=2,
            contribution_margin="999.00",
        )
        campaign_id = campaign.id

    with database.session_factory() as session:
        summary = summarize_kpis(session, DAY_1, DAY_1)

    assert summary.totals.qualified_leads == 3
    assert summary.kpis.qualification_rate == Decimal("150.000000")
    assert summary.kpis.contract_to_paying_conversion == Decimal("300.000000")
    assert summary.kpis.cancellation_rate == Decimal("200.000000")
    assert summary.kpis.net_enrollments == -1
    assert summary.kpis.net_cac is None
    assert [warning.code for warning in summary.warnings] == [
        "QUALIFIED_LEADS_EXCEED_LEADS",
        "CANCELLATIONS_EXCEED_CONTRACTED",
        "PAYING_EXCEEDS_CONTRACTED",
    ]
    qualified_warning, cancellation_warning, paying_warning = summary.warnings
    assert qualified_warning.insight_id is not None
    assert qualified_warning.campaign_id == campaign_id
    assert qualified_warning.meta_campaign_id == "inconsistent"
    assert qualified_warning.date_start == DAY_1
    assert qualified_warning.date_stop == DAY_1
    for warning in (cancellation_warning, paying_warning):
        assert warning.enrollment_record_id is not None
        assert warning.campaign_id == campaign_id
        assert warning.meta_campaign_id == "inconsistent"
        assert warning.reference_date == DAY_1
        assert warning.enrollment_course == "Nursing"


def test_contribution_margin_is_not_interpreted_as_a_total_or_kpi() -> None:
    assert "contribution_margin" not in {field.name for field in fields(KpiTotals)}
    assert not any(
        field.name.startswith("contribution_margin") for field in fields(CalculatedKpis)
    )
