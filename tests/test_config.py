from pathlib import Path

import pytest
from pydantic import ValidationError

from meta_kpi_calc.core.config import PROJECT_ROOT, Settings


def make_settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": f"sqlite:///{tmp_path / 'real.db'}",
        "demo_database_url": f"sqlite:///{tmp_path / 'demo.db'}",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_defaults_are_safe_and_demo_uses_separate_database(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)

    assert settings.mode == "demo"
    assert settings.scheduler_enabled is False
    assert settings.meta_access_token is None
    assert settings.active_database_url == settings.resolved_demo_database_url
    assert settings.resolved_database_url != settings.resolved_demo_database_url


def test_relative_database_paths_are_resolved_from_project_root() -> None:
    settings = Settings(
        _env_file=None,
        database_url="sqlite:///./custom/real.db",
        demo_database_url="sqlite:///./custom/demo.db",
    )

    assert str(PROJECT_ROOT / "custom" / "demo.db") in settings.active_database_url


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"app_timezone": "Invalid/Timezone"}, "APP_TIMEZONE"),
        ({"sync_lookback_days": 32, "max_sync_days": 31}, "SYNC_LOOKBACK_DAYS"),
        ({"database_url": "postgresql://localhost/db"}, "SQLite"),
    ],
)
def test_invalid_settings_are_rejected(
    tmp_path: Path, overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        make_settings(tmp_path, **overrides)


def test_demo_and_real_database_cannot_be_the_same(tmp_path: Path) -> None:
    same = f"sqlite:///{tmp_path / 'same.db'}"
    with pytest.raises(ValidationError, match="different files"):
        Settings(_env_file=None, database_url=same, demo_database_url=same)


@pytest.mark.parametrize(
    ("provided", "expected"),
    [("123456", "act_123456"), (" act_123456 ", "act_123456"), ("", None)],
)
def test_meta_ad_account_id_is_normalized(
    tmp_path: Path, provided: str, expected: str | None
) -> None:
    settings = make_settings(tmp_path, meta_ad_account_id=provided)
    assert settings.meta_ad_account_id == expected


@pytest.mark.parametrize("provided", ["abc", "act_act_123", "act_12x"])
def test_invalid_meta_ad_account_id_is_rejected(
    tmp_path: Path, provided: str
) -> None:
    with pytest.raises(ValidationError, match="META_AD_ACCOUNT_ID"):
        make_settings(tmp_path, meta_ad_account_id=provided)
