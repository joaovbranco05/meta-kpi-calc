"""Public request and response contracts for the local REST API."""

from datetime import date, datetime
from decimal import Decimal
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from meta_kpi_calc.db.models import CampaignBrand, SyncStatus


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AccountResponse(ApiModel):
    account_id: str
    account_name: str
    currency: str
    timezone_name: str
    account_status: int | str


class ConnectionResponse(ApiModel):
    mode: str
    configured: bool
    connected: bool
    account: AccountResponse | None


class SyncRequest(ApiModel):
    date_start: date
    date_stop: date
    active_only: bool = Field(default=True, strict=True)
    meta_campaign_id: str | None = None


class SyncResponse(ApiModel):
    sync_run_id: int
    status: SyncStatus
    date_start: date
    date_stop: date
    campaign_count: int
    record_count: int
    is_partial: bool


class CampaignResponse(ApiModel):
    id: int
    meta_campaign_id: str
    name: str
    status: str | None
    effective_status: str | None
    objective: str | None
    start_time: datetime | None
    stop_time: datetime | None
    brand: CampaignBrand
    course: str | None
    last_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ClassificationPatch(ApiModel):
    brand: CampaignBrand | None = None
    course: str | None = None

    @field_validator("brand")
    @classmethod
    def reject_null_brand(cls, value: CampaignBrand | None) -> CampaignBrand:
        if value is None:
            raise ValueError("brand cannot be null")
        return value

    @field_validator("course")
    @classmethod
    def normalize_course(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("course cannot be blank")
        return normalized

    @model_validator(mode="after")
    def require_change(self) -> "ClassificationPatch":
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        return self


class InsightResponse(ApiModel):
    id: int
    campaign_id: int
    meta_campaign_id: str
    date_start: date
    date_stop: date
    spend: Decimal
    reach: int
    impressions: int
    clicks: int
    inline_link_clicks: int
    leads: int
    qualified_leads: int | None
    frequency: Decimal | None
    meta_ctr: Decimal | None
    meta_cpc: Decimal | None
    meta_cpm: Decimal | None
    synced_at: datetime


class EnrollmentWrite(ApiModel):
    campaign_id: int = Field(strict=True)
    reference_date: date
    course: str
    contracted_enrollments: int = Field(strict=True, ge=0)
    paying_enrollments: int = Field(strict=True, ge=0)
    cancellations: int = Field(strict=True, ge=0)
    expected_revenue: Decimal = Field(ge=0, allow_inf_nan=False)
    received_revenue: Decimal = Field(ge=0, allow_inf_nan=False)
    contribution_margin: Decimal | None = Field(ge=0, allow_inf_nan=False)
    notes: str | None

    @field_validator(
        "expected_revenue", "received_revenue", "contribution_margin", mode="before"
    )
    @classmethod
    def reject_boolean_money(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("money cannot be boolean")
        return value

    @field_validator("course")
    @classmethod
    def normalize_course(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("course cannot be blank")
        return normalized


class EnrollmentResponse(EnrollmentWrite):
    id: int
    meta_campaign_id: str
    created_at: datetime
    updated_at: datetime


class DashboardFiltersResponse(ApiModel):
    date_start: date
    date_stop: date
    brand: CampaignBrand | None
    campaign_id: int | None
    course: str | None
    effective_status: str | None


class KpiTotalsResponse(ApiModel):
    spend: Decimal
    reach: int | None
    impressions: int
    clicks: int
    inline_link_clicks: int
    leads: int
    qualified_leads: int | None
    contracted_enrollments: int
    paying_enrollments: int
    cancellations: int
    expected_revenue: Decimal
    received_revenue: Decimal
    meta_ctr: Decimal | None
    meta_cpc: Decimal | None
    meta_cpm: Decimal | None
    frequency: Decimal | None
    insight_count: int


class CalculatedKpisResponse(ApiModel):
    calculated_ctr: Decimal | None
    calculated_cpc: Decimal | None
    calculated_cpm: Decimal | None
    cpl: Decimal | None
    contractual_conversion: Decimal | None
    financial_conversion: Decimal | None
    contractual_cac: Decimal | None
    financial_cac: Decimal | None
    expected_roas: Decimal | None
    received_roas: Decimal | None
    received_advertising_roi: Decimal | None
    qualification_rate: Decimal | None
    cpql: Decimal | None
    contract_to_paying_conversion: Decimal | None
    cancellation_rate: Decimal | None
    net_enrollments: int
    net_cac: Decimal | None
    expected_revenue_per_paying_enrollment: Decimal | None
    received_revenue_per_paying_enrollment: Decimal | None


class KpiWarningResponse(ApiModel):
    code: str
    message: str
    campaign_id: int | None
    meta_campaign_id: str | None
    campaign_course: str | None
    enrollment_course: str | None
    insight_id: int | None
    enrollment_record_id: int | None
    date_start: date | None
    date_stop: date | None
    reference_date: date | None


class DashboardSummaryResponse(ApiModel):
    filters: DashboardFiltersResponse
    totals: KpiTotalsResponse
    kpis: CalculatedKpisResponse
    warnings: list[KpiWarningResponse]


Item = TypeVar("Item")


class Page(ApiModel, Generic[Item]):
    items: list[Item]
    total: int
    offset: int
    limit: int
