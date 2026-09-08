from datetime import UTC, date, datetime
from unittest.mock import Mock

import pytest
from apscheduler.schedulers.base import STATE_STOPPED
from pydantic import SecretStr

from meta_kpi_calc.core.config import Settings
from meta_kpi_calc.services.scheduler import create_scheduler
from meta_kpi_calc.services.sync_service import SyncService, SyncServiceError


def settings(tmp_path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "demo_mode": False,
        "database_url": f"sqlite:///{tmp_path / 'real.db'}",
        "demo_database_url": f"sqlite:///{tmp_path / 'demo.db'}",
        "meta_access_token": SecretStr("scheduler-token"),
        "meta_ad_account_id": "123",
        "scheduler_enabled": True,
        "sync_interval_minutes": 15,
        "sync_lookback_days": 7,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_disabled_scheduler_returns_none_without_validating_meta(tmp_path) -> None:
    config = settings(
        tmp_path,
        scheduler_enabled=False,
        demo_mode=True,
        meta_access_token=None,
        meta_ad_account_id=None,
    )

    assert create_scheduler(config, Mock(spec=SyncService)) is None


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"demo_mode": True}, "demo_mode"),
        ({"meta_access_token": None}, "meta_not_configured"),
        ({"meta_access_token": SecretStr("")}, "meta_not_configured"),
        ({"meta_ad_account_id": None}, "meta_not_configured"),
    ],
)
def test_enabled_scheduler_rejects_invalid_runtime_configuration(
    tmp_path, overrides: dict[str, object], code: str
) -> None:
    with pytest.raises(SyncServiceError) as captured:
        create_scheduler(
            settings(tmp_path, **overrides),
            Mock(spec=SyncService),
        )

    assert captured.value.code == code
    assert captured.value.sync_run_id is None


def test_enabled_scheduler_registers_one_stopped_interval_job(tmp_path) -> None:
    config = settings(tmp_path)
    service = Mock(spec=SyncService)
    service.today.return_value = date(2026, 9, 7)

    scheduler = create_scheduler(config, service)

    assert scheduler is not None
    assert scheduler.state == STATE_STOPPED
    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    job = jobs[0]
    assert job.id == "meta-sync"
    assert job.max_instances == 1
    assert job.coalesce is True
    assert job.trigger.interval.total_seconds() == 15 * 60
    assert str(scheduler.timezone) == "America/Sao_Paulo"

    job.func()
    service.today.assert_called_once_with()
    service.run_sync.assert_called_once_with(
        date(2026, 9, 1),
        date(2026, 9, 7),
        active_only=True,
    )
    assert scheduler.state == STATE_STOPPED
