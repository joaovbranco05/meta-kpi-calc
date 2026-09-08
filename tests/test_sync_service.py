from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from threading import Event, Thread
from unittest.mock import Mock

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import func, select

from meta_kpi_calc.core.config import Settings
from meta_kpi_calc.db.models import (
    Campaign,
    CampaignBrand,
    CampaignInsight,
    SyncRun,
    SyncStatus,
)
from meta_kpi_calc.db.session import Database
from meta_kpi_calc.services.meta_client import (
    MetaCampaign,
    MetaClient,
    MetaClientError,
    MetaInsight,
)
from meta_kpi_calc.services.sync_service import SyncService, SyncServiceError

TODAY = date(2026, 9, 7)
YESTERDAY = date(2026, 9, 6)
NOW = datetime(2026, 9, 7, 15, 0, tzinfo=UTC)
TOKEN = "sync-token-sentinel"


def real_settings(settings: Settings, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "demo_mode": False,
        "database_url": settings.database_url,
        "demo_database_url": settings.demo_database_url,
        "meta_access_token": SecretStr(TOKEN),
        "meta_ad_account_id": "act_123",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def meta_campaign(
    campaign_id: str = "campaign-1",
    *,
    name: str = "Campaign 1",
    effective_status: str = "ACTIVE",
    start_time: str | None = "2026-09-01T08:00:00-03:00",
    stop_time: str | None = None,
) -> MetaCampaign:
    return MetaCampaign(
        meta_campaign_id=campaign_id,
        name=name,
        status="ACTIVE",
        effective_status=effective_status,
        objective="OUTCOME_LEADS",
        start_time=start_time,
        stop_time=stop_time,
    )


def meta_insight(
    campaign_id: str = "campaign-1",
    *,
    insight_date: date = YESTERDAY,
    spend: str = "12.34",
    leads: int = 2,
) -> MetaInsight:
    return MetaInsight(
        account_id="123",
        account_name="Test account",
        meta_campaign_id=campaign_id,
        campaign_name="Campaign 1",
        date_start=insight_date,
        date_stop=insight_date,
        spend=Decimal(spend),
        reach=100,
        impressions=120,
        clicks=11,
        inline_link_clicks=8,
        leads=leads,
        frequency=Decimal("1.200000"),
        meta_ctr=Decimal("6.666667"),
        meta_cpc=Decimal("1.542500"),
        meta_cpm=Decimal("102.833333"),
        raw_actions=[{"action_type": "lead", "value": str(leads)}],
        raw_cost_per_action_type=[],
        raw_response={"campaign_id": campaign_id},
    )


def meta_mock(
    campaigns: list[MetaCampaign] | None = None,
    insights: list[MetaInsight] | None = None,
) -> Mock:
    client = Mock(spec=MetaClient)
    client.list_campaigns.return_value = campaigns or []
    client.get_insights.return_value = insights or []
    return client


def make_service(
    settings: Settings,
    database: Database,
    client: Mock,
    *,
    now: object = lambda: NOW,
    lock: object = None,
) -> SyncService:
    kwargs = {"now": now}
    if lock is not None:
        kwargs["lock"] = lock
    return SyncService(
        settings,
        database.session_factory,
        client,
        **kwargs,  # type: ignore[arg-type]
    )


def sync_run_count(database: Database) -> int:
    with database.session_factory() as session:
        return session.scalar(select(func.count(SyncRun.id))) or 0


@pytest.mark.parametrize(
    ("start", "stop", "code"),
    [
        (TODAY, YESTERDAY, "invalid_date_range"),
        (date(2026, 8, 7), TODAY, "invalid_date_range"),
        (datetime(2026, 9, 7, tzinfo=UTC), TODAY, "invalid_date_range"),
        (YESTERDAY, datetime(2026, 9, 7, tzinfo=UTC), "invalid_date_range"),
        (YESTERDAY, date(2026, 9, 8), "future_date"),
    ],
)
def test_invalid_dates_fail_before_database_or_meta(
    migrated_database: tuple[Settings, Database],
    start: date,
    stop: date,
    code: str,
) -> None:
    base_settings, database = migrated_database
    client = meta_mock()
    service = make_service(real_settings(base_settings), database, client)

    with pytest.raises(SyncServiceError) as captured:
        service.run_sync(start, stop)

    assert captured.value.code == code
    assert captured.value.sync_run_id is None
    assert sync_run_count(database) == 0
    client.list_campaigns.assert_not_called()


def test_configured_smaller_window_and_filter_validation_fail_before_io(
    migrated_database: tuple[Settings, Database],
) -> None:
    base_settings, database = migrated_database
    client = meta_mock()
    settings = real_settings(base_settings, max_sync_days=2, sync_lookback_days=2)
    service = make_service(settings, database, client)

    with pytest.raises(SyncServiceError) as too_wide:
        service.run_sync(date(2026, 9, 5), TODAY)
    assert too_wide.value.code == "invalid_date_range"

    for campaign_filter in ("", "   ", 123):
        with pytest.raises(SyncServiceError) as invalid_filter:
            service.run_sync(
                YESTERDAY,
                TODAY,
                meta_campaign_id=campaign_filter,  # type: ignore[arg-type]
            )
        assert invalid_filter.value.code == "invalid_campaign_filter"

    assert sync_run_count(database) == 0
    client.list_campaigns.assert_not_called()


def test_timezone_clock_today_partial_and_yesterday_complete(
    migrated_database: tuple[Settings, Database],
) -> None:
    base_settings, database = migrated_database
    settings = real_settings(base_settings)
    client = meta_mock()
    service = make_service(settings, database, client)

    today_result = service.run_sync(TODAY, TODAY)
    yesterday_result = service.run_sync(YESTERDAY, YESTERDAY)

    assert today_result.is_partial is True
    assert yesterday_result.is_partial is False

    sao_paulo_yesterday = datetime(2026, 9, 7, 1, 0, tzinfo=UTC)
    future_service = make_service(
        settings, database, client, now=lambda: sao_paulo_yesterday
    )
    with pytest.raises(SyncServiceError) as captured:
        future_service.run_sync(TODAY, TODAY)
    assert captured.value.code == "future_date"


def test_naive_clock_demo_and_missing_credentials_do_not_touch_db_or_meta(
    migrated_database: tuple[Settings, Database],
) -> None:
    base_settings, database = migrated_database
    client = meta_mock()
    naive = make_service(
        real_settings(base_settings),
        database,
        client,
        now=lambda: datetime(2026, 9, 7, 12),
    )
    with pytest.raises(SyncServiceError) as clock_error:
        naive.run_sync(TODAY, TODAY)
    assert clock_error.value.code == "invalid_date_range"

    demo = make_service(base_settings, database, client)
    with pytest.raises(SyncServiceError) as demo_error:
        demo.run_sync(TODAY, TODAY)
    assert demo_error.value.code == "demo_mode"

    for overrides in (
        {"meta_access_token": None},
        {"meta_access_token": SecretStr("")},
        {"meta_ad_account_id": None},
    ):
        service = make_service(
            real_settings(base_settings, **overrides), database, client
        )
        with pytest.raises(SyncServiceError) as config_error:
            service.run_sync(TODAY, TODAY)
        assert config_error.value.code == "meta_not_configured"

    assert sync_run_count(database) == 0
    client.list_campaigns.assert_not_called()


def test_settings_reject_more_than_31_sync_days(tmp_path) -> None:
    with pytest.raises(ValidationError, match="less than or equal to 31"):
        Settings(
            _env_file=None,
            database_url=f"sqlite:///{tmp_path / 'real.db'}",
            demo_database_url=f"sqlite:///{tmp_path / 'demo.db'}",
            max_sync_days=32,
        )


def test_full_31_day_window_is_accepted(
    migrated_database: tuple[Settings, Database],
) -> None:
    base_settings, database = migrated_database
    client = meta_mock()
    service = make_service(real_settings(base_settings), database, client)

    result = service.run_sync(date(2026, 8, 8), TODAY)

    assert result.status is SyncStatus.SUCCESS
    client.list_campaigns.assert_called_once_with(active_only=True)


def test_empty_campaign_result_skips_insights_and_finishes_successfully(
    migrated_database: tuple[Settings, Database],
) -> None:
    base_settings, database = migrated_database
    client = meta_mock()
    service = make_service(real_settings(base_settings), database, client)

    result = service.run_sync(YESTERDAY, YESTERDAY, active_only=False)

    assert result.status is SyncStatus.SUCCESS
    assert result.campaign_count == 0
    assert result.record_count == 0
    client.list_campaigns.assert_called_once_with(active_only=False)
    client.get_insights.assert_not_called()
    with database.session_factory() as session:
        run = session.get(SyncRun, result.sync_run_id)
        assert run is not None
        assert run.status is SyncStatus.SUCCESS
        assert run.finished_at is not None
        assert run.campaign_count == 0
        assert run.record_count == 0
        assert run.error_message is None


def test_filters_are_conjunctive_and_only_selected_insights_are_persisted(
    migrated_database: tuple[Settings, Database],
) -> None:
    base_settings, database = migrated_database
    active = meta_campaign("active")
    other = meta_campaign("other")
    client = meta_mock(
        [active, other],
        [meta_insight("active"), meta_insight("other")],
    )
    service = make_service(real_settings(base_settings), database, client)

    result = service.run_sync(
        YESTERDAY,
        YESTERDAY,
        active_only=True,
        meta_campaign_id=" active ",
    )

    assert result.campaign_count == 1
    assert result.record_count == 1
    client.list_campaigns.assert_called_once_with(active_only=True)
    client.get_insights.assert_called_once_with(YESTERDAY, YESTERDAY)
    with database.session_factory() as session:
        assert session.scalar(select(func.count(Campaign.id))) == 1
        campaign = session.scalar(select(Campaign))
        assert campaign is not None
        assert campaign.meta_campaign_id == "active"
        assert session.scalar(select(func.count(CampaignInsight.id))) == 1


def test_upsert_is_idempotent_updates_meta_and_preserves_manual_fields(
    migrated_database: tuple[Settings, Database],
) -> None:
    base_settings, database = migrated_database
    client = meta_mock(
        [meta_campaign()],
        [meta_insight(spend="12.34", leads=2)],
    )
    service = make_service(real_settings(base_settings), database, client)

    first = service.run_sync(YESTERDAY, YESTERDAY)
    with database.session_factory.begin() as session:
        campaign = session.scalar(select(Campaign))
        insight = session.scalar(select(CampaignInsight))
        assert campaign is not None and insight is not None
        campaign.brand = CampaignBrand.FECAF
        campaign.course = "Administration"
        insight.qualified_leads = 1

    client.list_campaigns.return_value = [
        meta_campaign(name="Campaign updated")
    ]
    client.get_insights.return_value = [meta_insight(spend="20.50", leads=5)]
    second = service.run_sync(YESTERDAY, YESTERDAY)

    assert first.sync_run_id != second.sync_run_id
    with database.session_factory() as session:
        assert session.scalar(select(func.count(Campaign.id))) == 1
        assert session.scalar(select(func.count(CampaignInsight.id))) == 1
        assert session.scalar(select(func.count(SyncRun.id))) == 2
        campaign = session.scalar(select(Campaign))
        insight = session.scalar(select(CampaignInsight))
        assert campaign is not None and insight is not None
        assert campaign.name == "Campaign updated"
        assert campaign.brand is CampaignBrand.FECAF
        assert campaign.course == "Administration"
        # SQLite returns DateTime values naive, so the stored clock is normalized UTC.
        assert campaign.start_time == datetime(2026, 9, 1, 11, 0)
        assert campaign.last_synced_at is not None
        assert insight.spend == Decimal("20.50")
        assert insight.leads == 5
        assert insight.qualified_leads == 1
        assert insight.frequency == Decimal("1.200000")
        assert insight.meta_ctr == Decimal("6.666667")
        assert insight.meta_cpc == Decimal("1.542500")
        assert insight.meta_cpm == Decimal("102.833333")
        assert insight.raw_actions == [{"action_type": "lead", "value": "5"}]
        assert insight.raw_cost_per_action_type == []
        assert insight.raw_response == {"campaign_id": "campaign-1"}
        assert insight.synced_at is not None


def test_new_insight_keeps_qualified_leads_unknown(
    migrated_database: tuple[Settings, Database],
) -> None:
    base_settings, database = migrated_database
    client = meta_mock([meta_campaign()], [meta_insight()])
    service = make_service(real_settings(base_settings), database, client)

    service.run_sync(YESTERDAY, YESTERDAY)

    with database.session_factory() as session:
        insight = session.scalar(select(CampaignInsight))
        assert insight is not None
        assert insight.qualified_leads is None


def test_campaign_datetimes_are_compared_as_utc_instants(
    migrated_database: tuple[Settings, Database],
) -> None:
    base_settings, database = migrated_database
    campaign = meta_campaign(
        start_time="2026-09-01T10:00:00+02:00",
        stop_time="2026-09-01T09:00:00+00:00",
    )
    service = make_service(
        real_settings(base_settings), database, meta_mock([campaign], [])
    )

    service.run_sync(YESTERDAY, YESTERDAY)

    with database.session_factory() as session:
        persisted = session.scalar(select(Campaign))
        assert persisted is not None
        assert persisted.start_time == datetime(2026, 9, 1, 8, 0)
        assert persisted.stop_time == datetime(2026, 9, 1, 9, 0)


def test_duplicate_rows_are_last_wins_and_counts_are_unique(
    migrated_database: tuple[Settings, Database],
) -> None:
    base_settings, database = migrated_database
    client = meta_mock(
        [meta_campaign(name="First"), meta_campaign(name="Last")],
        [meta_insight(spend="1.00"), meta_insight(spend="9.00")],
    )
    service = make_service(real_settings(base_settings), database, client)

    result = service.run_sync(YESTERDAY, YESTERDAY)

    assert result.campaign_count == 1
    assert result.record_count == 1
    with database.session_factory() as session:
        campaign = session.scalar(select(Campaign))
        insight = session.scalar(select(CampaignInsight))
        assert campaign is not None and campaign.name == "Last"
        assert insight is not None and insight.spend == Decimal("9.00")


def test_out_of_window_insight_fails_without_persisting_data(
    migrated_database: tuple[Settings, Database],
) -> None:
    base_settings, database = migrated_database
    outside = meta_insight(insight_date=date(2026, 9, 5))
    client = meta_mock([meta_campaign()], [outside])
    service = make_service(real_settings(base_settings), database, client)

    with pytest.raises(SyncServiceError) as captured:
        service.run_sync(YESTERDAY, YESTERDAY)

    assert captured.value.code == "sync_failed"
    assert captured.value.sync_run_id is not None
    with database.session_factory() as session:
        assert session.scalar(select(func.count(Campaign.id))) == 0
        assert session.scalar(select(func.count(CampaignInsight.id))) == 0
        run = session.get(SyncRun, captured.value.sync_run_id)
        assert run is not None
        assert run.status is SyncStatus.FAILED
        assert run.campaign_count == 0
        assert run.record_count == 0
        assert run.error_message == "Meta synchronization failed."


def test_meta_failure_is_sanitized_and_leaves_only_failed_run(
    migrated_database: tuple[Settings, Database],
) -> None:
    base_settings, database = migrated_database
    client = meta_mock()
    client.list_campaigns.side_effect = MetaClientError(
        f"private {TOKEN} https://secret.invalid/?after=cursor"
    )
    failed_at = datetime(2026, 9, 7, 15, 1, tzinfo=UTC)
    clock = iter([NOW, failed_at])
    service = make_service(
        real_settings(base_settings), database, client, now=lambda: next(clock)
    )

    with pytest.raises(SyncServiceError) as captured:
        service.run_sync(YESTERDAY, YESTERDAY)

    rendered = str(captured.value) + repr(captured.value)
    assert captured.value.code == "sync_failed"
    assert captured.value.sync_run_id is not None
    assert TOKEN not in rendered
    assert "secret.invalid" not in rendered
    with database.session_factory() as session:
        assert session.scalar(select(func.count(Campaign.id))) == 0
        assert session.scalar(select(func.count(CampaignInsight.id))) == 0
        run = session.get(SyncRun, captured.value.sync_run_id)
        assert run is not None
        assert run.status is SyncStatus.FAILED
        assert run.finished_at == failed_at.replace(tzinfo=None)
        assert run.finished_at >= run.started_at
        assert run.error_message == "Meta synchronization failed."
        assert TOKEN not in repr(run.error_message)


@pytest.mark.parametrize(
    "invalid_time",
    ["invalid-time", "2026-09-01T08:00:00"],
)
def test_invalid_campaign_datetime_rolls_back_entire_data_transaction(
    migrated_database: tuple[Settings, Database],
    invalid_time: str,
) -> None:
    base_settings, database = migrated_database
    client = meta_mock(
        [meta_campaign("valid"), meta_campaign("invalid", start_time=invalid_time)],
        [],
    )
    service = make_service(real_settings(base_settings), database, client)

    with pytest.raises(SyncServiceError) as captured:
        service.run_sync(YESTERDAY, YESTERDAY)

    assert captured.value.code == "sync_failed"
    with database.session_factory() as session:
        assert session.scalar(select(func.count(Campaign.id))) == 0
        run = session.get(SyncRun, captured.value.sync_run_id)
        assert run is not None and run.status is SyncStatus.FAILED


def test_unserializable_last_insight_rolls_back_all_data(
    migrated_database: tuple[Settings, Database],
) -> None:
    base_settings, database = migrated_database
    first = meta_insight(insight_date=date(2026, 9, 5))
    invalid_last = replace(
        meta_insight(insight_date=YESTERDAY), raw_response={"bad": object()}
    )
    client = meta_mock([meta_campaign()], [first, invalid_last])
    service = make_service(real_settings(base_settings), database, client)

    with pytest.raises(SyncServiceError) as captured:
        service.run_sync(date(2026, 9, 5), YESTERDAY)

    assert captured.value.code == "sync_failed"
    assert str(captured.value) == "Meta synchronization failed."
    with database.session_factory() as session:
        assert session.scalar(select(func.count(Campaign.id))) == 0
        assert session.scalar(select(func.count(CampaignInsight.id))) == 0
        run = session.get(SyncRun, captured.value.sync_run_id)
        assert run is not None
        assert run.status is SyncStatus.FAILED
        assert run.error_message == "Meta synchronization failed."


def test_global_lock_blocks_other_instances_and_releases_after_success(
    migrated_database: tuple[Settings, Database],
) -> None:
    base_settings, database = migrated_database
    entered = Event()
    release = Event()
    first_client = meta_mock()

    def blocking_campaigns(*, active_only: bool) -> list[MetaCampaign]:
        assert active_only is True
        entered.set()
        assert release.wait(timeout=5)
        return []

    first_client.list_campaigns.side_effect = blocking_campaigns
    first_service = make_service(real_settings(base_settings), database, first_client)
    second_client = meta_mock()
    second_service = make_service(real_settings(base_settings), database, second_client)
    thread_errors: list[Exception] = []

    def run_first() -> None:
        try:
            first_service.run_sync(YESTERDAY, YESTERDAY)
        except Exception as exc:  # pragma: no cover - assertion reports the value
            thread_errors.append(exc)

    thread = Thread(target=run_first)
    thread.start()
    assert entered.wait(timeout=5)
    try:
        with pytest.raises(SyncServiceError) as captured:
            second_service.run_sync(YESTERDAY, YESTERDAY)
        assert captured.value.code == "sync_in_progress"
        assert captured.value.sync_run_id is None
        second_client.list_campaigns.assert_not_called()
        assert sync_run_count(database) == 1
    finally:
        release.set()
        thread.join(timeout=5)

    assert thread_errors == []
    assert thread.is_alive() is False
    assert sync_run_count(database) == 1
    second_service.run_sync(YESTERDAY, YESTERDAY)
    assert sync_run_count(database) == 2


def test_lock_releases_after_failure(
    migrated_database: tuple[Settings, Database],
) -> None:
    base_settings, database = migrated_database
    client = meta_mock()
    client.list_campaigns.side_effect = [RuntimeError("private"), []]
    service = make_service(real_settings(base_settings), database, client)

    with pytest.raises(SyncServiceError):
        service.run_sync(YESTERDAY, YESTERDAY)
    result = service.run_sync(YESTERDAY, YESTERDAY)

    assert result.status is SyncStatus.SUCCESS
    assert sync_run_count(database) == 2
