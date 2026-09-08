"""Validated settings with deterministic SQLite paths."""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, HttpUrl, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def normalize_meta_ad_account_id(value: str) -> str:
    normalized = value.strip()
    numeric_id = normalized[4:] if normalized.startswith("act_") else normalized
    if not numeric_id.isdigit():
        raise ValueError(
            "META_AD_ACCOUNT_ID must contain digits, optionally prefixed by act_"
        )
    return f"act_{numeric_id}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Meta KPI Calculator"
    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = Field(default=8000, ge=1, le=65535)
    app_timezone: str = "America/Sao_Paulo"
    default_currency: str = "BRL"
    log_level: str = "INFO"

    demo_mode: bool = True
    database_url: str = "sqlite:///./data/meta_kpi.db"
    demo_database_url: str = "sqlite:///./data/meta_kpi_demo.db"
    sqlite_busy_timeout_ms: int = Field(default=5000, gt=0)

    meta_access_token: SecretStr | None = None
    meta_ad_account_id: str | None = None
    meta_api_version: str = "v26.0"
    meta_lead_action_types: list[str] = Field(
        default_factory=lambda: ["lead", "onsite_conversion.lead_grouped"]
    )

    scheduler_enabled: bool = False
    sync_interval_minutes: int = Field(default=60, gt=0)
    sync_lookback_days: int = Field(default=7, ge=1)
    max_sync_days: int = Field(default=31, ge=1, le=31)
    api_base_url: HttpUrl = HttpUrl("http://127.0.0.1:8000")

    @field_validator("app_timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("APP_TIMEZONE must be a valid IANA timezone") from exc
        return value

    @field_validator("database_url", "demo_database_url")
    @classmethod
    def validate_sqlite_url(cls, value: str) -> str:
        url = make_url(value)
        if url.drivername != "sqlite" or not url.database:
            raise ValueError("Database URLs must use SQLite and include a database path")
        return value

    @field_validator("meta_ad_account_id", mode="before")
    @classmethod
    def normalize_meta_ad_account_id(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            return None
        return normalize_meta_ad_account_id(normalized)

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            raise ValueError("LOG_LEVEL is invalid")
        return normalized

    @model_validator(mode="after")
    def validate_relationships(self) -> "Settings":
        if self.sync_lookback_days > self.max_sync_days:
            raise ValueError("SYNC_LOOKBACK_DAYS cannot exceed MAX_SYNC_DAYS")
        if self.resolved_database_url == self.resolved_demo_database_url:
            raise ValueError("Demo and real databases must use different files")
        return self

    @staticmethod
    def _resolve_sqlite_url(value: str) -> str:
        url = make_url(value)
        database = url.database
        if database == ":memory:":
            return value
        path = Path(database)
        if not path.is_absolute():
            path = (PROJECT_ROOT / path).resolve()
        return URL.create("sqlite", database=str(path)).render_as_string(
            hide_password=False
        )

    @property
    def resolved_database_url(self) -> str:
        return self._resolve_sqlite_url(self.database_url)

    @property
    def resolved_demo_database_url(self) -> str:
        return self._resolve_sqlite_url(self.demo_database_url)

    @property
    def active_database_url(self) -> str:
        return (
            self.resolved_demo_database_url
            if self.demo_mode
            else self.resolved_database_url
        )

    @property
    def mode(self) -> Literal["demo", "real"]:
        return "demo" if self.demo_mode else "real"


@lru_cache
def get_settings() -> Settings:
    return Settings()
