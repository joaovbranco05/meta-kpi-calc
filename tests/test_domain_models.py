from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import delete, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from meta_kpi_calc.core.config import Settings
from meta_kpi_calc.db.models import (
    Campaign,
    CampaignBrand,
    CampaignInsight,
    EnrollmentRecord,
    SyncRun,
)
from meta_kpi_calc.db.session import Database


def add_campaign(session: Session, meta_id: str = "campaign-1") -> Campaign:
    campaign = Campaign(meta_campaign_id=meta_id, name="Campaign")
    session.add(campaign)
    session.flush()
    return campaign


def test_campaign_defaults_and_nullable_course(
    migrated_database: tuple[Settings, Database],
) -> None:
    _, database = migrated_database
    with database.session_factory.begin() as session:
        campaign = add_campaign(session)
        assert campaign.brand is CampaignBrand.NAO_CLASSIFICADA
        assert campaign.course is None


def test_insight_preserves_decimal_and_json(
    migrated_database: tuple[Settings, Database],
) -> None:
    _, database = migrated_database
    with database.session_factory.begin() as session:
        campaign = add_campaign(session)
        session.add(
            CampaignInsight(
                campaign_id=campaign.id,
                date_start=date(2026, 9, 1),
                date_stop=date(2026, 9, 1),
                spend=Decimal("123.45"),
                qualified_leads=2,
                frequency=Decimal("1.234567"),
                raw_actions=[{"action_type": "lead", "value": "2"}],
                raw_response={"source": "test"},
                synced_at=datetime.now(timezone.utc),
            )
        )

    with database.session_factory() as session:
        insight = session.scalar(select(CampaignInsight))
        assert insight is not None
        assert insight.spend == Decimal("123.45")
        assert insight.frequency == Decimal("1.234567")
        assert insight.qualified_leads == 2
        assert insight.raw_actions == [{"action_type": "lead", "value": "2"}]
        assert insight.raw_response == {"source": "test"}


def test_qualified_leads_is_nullable_and_rejects_negative_values(
    migrated_database: tuple[Settings, Database],
) -> None:
    _, database = migrated_database
    with database.session_factory.begin() as session:
        campaign = add_campaign(session)
        session.add(
            CampaignInsight(
                campaign_id=campaign.id,
                date_start=date(2026, 9, 1),
                date_stop=date(2026, 9, 1),
                qualified_leads=None,
            )
        )

    with database.session_factory() as session:
        insight = session.scalar(select(CampaignInsight))
        assert insight is not None
        assert insight.qualified_leads is None

    with pytest.raises(IntegrityError):
        with database.session_factory.begin() as session:
            campaign = add_campaign(session, "negative-qualified")
            session.add(
                CampaignInsight(
                    campaign_id=campaign.id,
                    date_start=date(2026, 9, 2),
                    date_stop=date(2026, 9, 2),
                    qualified_leads=-1,
                )
            )


def test_natural_keys_are_unique(
    migrated_database: tuple[Settings, Database],
) -> None:
    _, database = migrated_database
    with database.session_factory.begin() as session:
        add_campaign(session, "same-id")

    with pytest.raises(IntegrityError):
        with database.session_factory.begin() as session:
            session.add(Campaign(meta_campaign_id="same-id", name="Duplicate"))

    with database.session_factory.begin() as session:
        campaign = session.scalar(
            select(Campaign).where(Campaign.meta_campaign_id == "same-id")
        )
        assert campaign is not None
        insight_values = {
            "campaign_id": campaign.id,
            "date_start": date(2026, 9, 1),
            "date_stop": date(2026, 9, 1),
            "synced_at": datetime.now(timezone.utc),
        }
        enrollment_values = {
            "campaign_id": campaign.id,
            "reference_date": date(2026, 9, 1),
            "course": "Course",
        }
        session.add(CampaignInsight(**insight_values))
        session.add(EnrollmentRecord(**enrollment_values))

    with pytest.raises(IntegrityError):
        with database.session_factory.begin() as session:
            session.add(CampaignInsight(**insight_values))

    with pytest.raises(IntegrityError):
        with database.session_factory.begin() as session:
            session.add(EnrollmentRecord(**enrollment_values))


def test_foreign_key_restricts_campaign_delete(
    migrated_database: tuple[Settings, Database],
) -> None:
    _, database = migrated_database
    with database.session_factory.begin() as session:
        campaign = add_campaign(session)
        campaign_id = campaign.id
        session.add(
            CampaignInsight(
                campaign_id=campaign_id,
                date_start=date(2026, 9, 1),
                date_stop=date(2026, 9, 1),
                synced_at=datetime.now(timezone.utc),
            )
        )

    with pytest.raises(IntegrityError):
        with database.session_factory.begin() as session:
            session.execute(delete(Campaign).where(Campaign.id == campaign_id))


@pytest.mark.parametrize(
    ("model", "values"),
    [
        (
            CampaignInsight,
            {
                "date_start": date(2026, 9, 2),
                "date_stop": date(2026, 9, 1),
                "synced_at": datetime.now(timezone.utc),
            },
        ),
        (
            CampaignInsight,
            {
                "date_start": date(2026, 9, 1),
                "date_stop": date(2026, 9, 1),
                "leads": -1,
                "synced_at": datetime.now(timezone.utc),
            },
        ),
        (
            EnrollmentRecord,
            {
                "reference_date": date(2026, 9, 1),
                "course": "Course",
                "received_revenue": Decimal("-0.01"),
            },
        ),
    ],
)
def test_database_rejects_invalid_ranges_and_negative_values(
    migrated_database: tuple[Settings, Database],
    model: type[object],
    values: dict[str, object],
) -> None:
    _, database = migrated_database
    with pytest.raises(IntegrityError):
        with database.session_factory.begin() as session:
            campaign = add_campaign(session)
            session.add(model(campaign_id=campaign.id, **values))


def test_sync_run_rejects_inverted_period(
    migrated_database: tuple[Settings, Database],
) -> None:
    _, database = migrated_database
    with pytest.raises(IntegrityError):
        with database.session_factory.begin() as session:
            session.add(
                SyncRun(
                    started_at=datetime.now(timezone.utc),
                    date_start=date(2026, 9, 2),
                    date_stop=date(2026, 9, 1),
                )
            )


def test_database_supplies_sync_timestamps(
    migrated_database: tuple[Settings, Database],
) -> None:
    _, database = migrated_database
    with database.session_factory.begin() as session:
        campaign = add_campaign(session)
        insight = CampaignInsight(
            campaign_id=campaign.id,
            date_start=date(2026, 9, 1),
            date_stop=date(2026, 9, 1),
        )
        sync_run = SyncRun(
            date_start=date(2026, 9, 1),
            date_stop=date(2026, 9, 1),
        )
        session.add_all([insight, sync_run])
        session.flush()
        assert insight.synced_at is not None
        assert sync_run.started_at is not None


def test_sync_run_rejects_finish_before_start(
    migrated_database: tuple[Settings, Database],
) -> None:
    _, database = migrated_database
    with pytest.raises(IntegrityError):
        with database.session_factory.begin() as session:
            session.add(
                SyncRun(
                    started_at=datetime(2026, 9, 1, 12, tzinfo=timezone.utc),
                    finished_at=datetime(2026, 9, 1, 11, tzinfo=timezone.utc),
                    date_start=date(2026, 9, 1),
                    date_stop=date(2026, 9, 1),
                )
            )


def test_enrollment_course_is_trimmed_and_blank_is_rejected(
    migrated_database: tuple[Settings, Database],
) -> None:
    _, database = migrated_database
    with database.session_factory.begin() as session:
        campaign = add_campaign(session)
        enrollment = EnrollmentRecord(
            campaign_id=campaign.id,
            reference_date=date(2026, 9, 1),
            course="  Nursing  ",
        )
        session.add(enrollment)
        assert enrollment.course == "Nursing"

    with pytest.raises(ValueError, match="course must not be blank"):
        EnrollmentRecord(
            campaign_id=1,
            reference_date=date(2026, 9, 1),
            course="   ",
        )

    with pytest.raises(IntegrityError):
        with database.session_factory.begin() as session:
            session.execute(
                insert(EnrollmentRecord).values(
                    campaign_id=campaign.id,
                    reference_date=date(2026, 9, 2),
                    course="   ",
                )
            )


def test_cancellations_may_exceed_contracted_enrollments(
    migrated_database: tuple[Settings, Database],
) -> None:
    _, database = migrated_database
    with database.session_factory.begin() as session:
        campaign = add_campaign(session)
        enrollment = EnrollmentRecord(
            campaign_id=campaign.id,
            reference_date=date(2026, 9, 1),
            course="Administration",
            contracted_enrollments=1,
            cancellations=2,
        )
        session.add(enrollment)
        session.flush()
        assert enrollment.id is not None
