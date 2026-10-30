"""Validated settings for SQLite and PostgreSQL databases."""

import re
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
        hide_input_in_errors=True,
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

    # Independent credentials: Ads credentials never authorize Lead Ads implicitly.
    lead_ads_enabled: bool = False
    lead_ads_api_version: str | None = None
    lead_ads_access_token: SecretStr | None = None
    lead_ads_app_secret: SecretStr | None = None
    lead_ads_verify_token: SecretStr | None = None
    lead_ads_diagnostic_log_path: Path | None = None
    lead_ads_allowed_page_ids: list[str] = Field(default_factory=list)
    lead_ads_authorized_sources: dict[str, str] = Field(default_factory=dict)
    lead_ads_body_max_bytes: int = Field(default=262144, ge=1024, le=1048576)
    lead_ads_max_pages: int = Field(default=100, ge=1, le=1000)
    lead_ads_page_size: int = Field(default=100, ge=1, le=1000)
    lead_ads_max_attempts: int = Field(default=5, ge=1, le=20)
    lead_ads_lease_seconds: int = Field(default=120, ge=30, le=3600)
    lead_ads_retry_base_seconds: int = Field(default=30, ge=1, le=3600)
    lead_ads_retry_max_seconds: int = Field(default=3600, ge=1, le=86400)
    lead_ads_overlap_seconds: int = Field(default=300, ge=0, le=86400)
    lead_ads_scan_max_days: int = Field(default=31, ge=1, le=365)

    scheduler_enabled: bool = False
    sync_interval_minutes: int = Field(default=60, gt=0)
    sync_lookback_days: int = Field(default=7, ge=1)
    max_sync_days: int = Field(default=31, ge=1, le=31)
    api_base_url: HttpUrl = HttpUrl("http://127.0.0.1:8000")

    @field_validator("lead_ads_api_version")
    @classmethod
    def validate_lead_ads_version(cls, value: str | None) -> str | None:
        if value is not None and re.fullmatch(r"v[0-9]+\.[0-9]+", value) is None:
            raise ValueError("Lead Ads API version is invalid")
        return value

    @field_validator("lead_ads_allowed_page_ids", "lead_ads_authorized_sources")
    @classmethod
    def validate_lead_ads_ids(cls, value: list[str] | dict[str, str]):
        ids = list(value) + (list(value.values()) if isinstance(value, dict) else [])
        if any(re.fullmatch(r"[0-9]{1,64}", item) is None for item in ids):
            raise ValueError("Lead Ads source IDs are invalid")
        return value

    @property
    def lead_ads_ingress_ready(self) -> bool:
        return bool(self.lead_ads_enabled and not self.demo_mode and self.lead_ads_allowed_page_ids
                    and self.lead_ads_authorized_sources and all(
            value is not None and value.get_secret_value().strip()
            for value in (self.lead_ads_app_secret, self.lead_ads_verify_token)
        ))

    @property
    def lead_ads_graph_ready(self) -> bool:
        return bool(self.lead_ads_enabled and self.lead_ads_api_version and
                    self.lead_ads_access_token and self.lead_ads_access_token.get_secret_value().strip())

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
    def validate_database_url(cls, value: str) -> str:
        try:
            url = make_url(value)
        except Exception:
            raise ValueError("Invalid database URL") from None
        if url.drivername not in {"sqlite", "postgresql", "postgresql+psycopg"} or not url.database:
            raise ValueError("Database URLs must use SQLite or PostgreSQL and include a database name")
        if url.drivername.startswith("postgresql") and not url.host:
            raise ValueError("PostgreSQL URLs must include a host")
        if url.drivername == "postgresql":
            url = url.set(drivername="postgresql+psycopg")
        return url.render_as_string(hide_password=False)

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
        if self.lead_ads_retry_base_seconds > self.lead_ads_retry_max_seconds:
            raise ValueError("Lead Ads retry policy is invalid")
        if any(page not in self.lead_ads_allowed_page_ids for page in self.lead_ads_authorized_sources.values()):
            raise ValueError("Lead Ads reconciliation sources must use allowed pages")
        if self.sync_lookback_days > self.max_sync_days:
            raise ValueError("SYNC_LOOKBACK_DAYS cannot exceed MAX_SYNC_DAYS")
        if self._database_identity(self.resolved_database_url) == self._database_identity(self.resolved_demo_database_url):
            raise ValueError("Demo and real databases must be different")
        return self

    @staticmethod
    def _resolve_sqlite_url(value: str) -> str:
        url = make_url(value)
        if url.get_backend_name() != "sqlite":
            return value
        database = url.database
        if database == ":memory:":
            return value
        path = Path(database)
        if not path.is_absolute():
            path = (PROJECT_ROOT / path).resolve()
        return URL.create("sqlite", database=str(path)).render_as_string(
            hide_password=False
        )

    @staticmethod
    def _database_identity(value: str) -> tuple:
        url = make_url(value)
        if url.get_backend_name() == "sqlite":
            return ("sqlite", url.database)
        return ("postgresql", (url.host or "").lower(), url.port or 5432, url.database)

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
