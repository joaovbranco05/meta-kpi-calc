from pathlib import Path

import pytest
from sqlalchemy import func, select

from meta_kpi_calc.core.config import Settings
from meta_kpi_calc.db.models import Campaign, CampaignInsight, EnrollmentRecord
from meta_kpi_calc.db.session import Database
from meta_kpi_calc.services.demo_seed import DEMO_CAMPAIGNS, seed_demo


def test_demo_seed_is_deterministic_and_idempotent(
    migrated_database: tuple[Settings, Database],
) -> None:
    settings, database = migrated_database

    first_counts = seed_demo(settings)
    second_counts = seed_demo(settings)

    assert first_counts == second_counts == {
        "campaigns": 3,
        "insights": 21,
        "enrollments": 3,
    }
    with database.session_factory() as session:
        campaigns = session.scalars(select(Campaign).order_by(Campaign.id)).all()
        insight_keys = session.execute(
            select(
                CampaignInsight.campaign_id,
                CampaignInsight.date_start,
                CampaignInsight.date_stop,
            )
        ).all()
        enrollment_keys = session.execute(
            select(
                EnrollmentRecord.campaign_id,
                EnrollmentRecord.reference_date,
                EnrollmentRecord.course,
            )
        ).all()
        zero_leads = session.scalar(
            select(func.count(CampaignInsight.id)).where(CampaignInsight.leads == 0)
        )
        zero_enrollments = session.scalar(
            select(func.count(EnrollmentRecord.id)).where(
                EnrollmentRecord.contracted_enrollments == 0,
                EnrollmentRecord.paying_enrollments == 0,
            )
        )

    assert {campaign.meta_campaign_id for campaign in campaigns} == {
        values["meta_campaign_id"] for values in DEMO_CAMPAIGNS
    }
    assert all(campaign.name.startswith("[DEMO]") for campaign in campaigns)
    assert len(insight_keys) == len(set(insight_keys)) == 21
    assert len(enrollment_keys) == len(set(enrollment_keys)) == 3
    assert zero_leads == 3
    assert zero_enrollments == 1


def test_demo_seed_refuses_real_mode_without_creating_database(tmp_path: Path) -> None:
    real_path = tmp_path / "real.db"
    settings = Settings(
        _env_file=None,
        demo_mode=False,
        database_url=f"sqlite:///{real_path}",
        demo_database_url=f"sqlite:///{tmp_path / 'demo.db'}",
    )

    with pytest.raises(ValueError, match="DEMO_MODE=true"):
        seed_demo(settings)

    assert not real_path.exists()
