"""SQLAlchemy entities persisted by the Meta KPI Calculator."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum as PythonEnum
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from meta_kpi_calc.db.base import Base


class CampaignBrand(str, PythonEnum):
    RCTEC = "RCTEC"
    FECAF = "FECAF"
    CURSO_COM_BOLSA = "CURSO_COM_BOLSA"
    NAO_CLASSIFICADA = "NAO_CLASSIFICADA"


class SyncStatus(str, PythonEnum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


def _enum_values(enum_class: type[PythonEnum]) -> list[str]:
    return [member.value for member in enum_class]


class Campaign(Base):
    __tablename__ = "campaigns"
    __table_args__ = (
        UniqueConstraint("meta_campaign_id", name="uq_campaigns_meta_campaign_id"),
        CheckConstraint(
            "length(trim(meta_campaign_id)) > 0",
            name="ck_campaigns_meta_campaign_id_not_blank",
        ),
        CheckConstraint(
            "length(trim(name)) > 0",
            name="ck_campaigns_name_not_blank",
        ),
        CheckConstraint(
            "stop_time IS NULL OR start_time IS NULL OR stop_time >= start_time",
            name="ck_campaigns_time_range",
        ),
        CheckConstraint(
            "brand IN ('RCTEC', 'FECAF', 'CURSO_COM_BOLSA', 'NAO_CLASSIFICADA')",
            name="ck_campaigns_brand",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meta_campaign_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str | None] = mapped_column(String(32))
    effective_status: Mapped[str | None] = mapped_column(String(32))
    objective: Mapped[str | None] = mapped_column(String(64))
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stop_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    brand: Mapped[CampaignBrand] = mapped_column(
        Enum(
            CampaignBrand,
            name="campaign_brand",
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=CampaignBrand.NAO_CLASSIFICADA,
        server_default=CampaignBrand.NAO_CLASSIFICADA.value,
    )
    course: Mapped[str | None] = mapped_column(String(255))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    insights: Mapped[list[CampaignInsight]] = relationship(back_populates="campaign")
    enrollments: Mapped[list[EnrollmentRecord]] = relationship(
        back_populates="campaign"
    )


class CampaignInsight(Base):
    __tablename__ = "campaign_insights"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id",
            "date_start",
            "date_stop",
            name="uq_campaign_insights_campaign_dates",
        ),
        CheckConstraint("date_stop >= date_start", name="ck_campaign_insights_date_range"),
        CheckConstraint("spend >= 0", name="ck_campaign_insights_spend_nonnegative"),
        CheckConstraint("reach >= 0", name="ck_campaign_insights_reach_nonnegative"),
        CheckConstraint(
            "impressions >= 0", name="ck_campaign_insights_impressions_nonnegative"
        ),
        CheckConstraint("clicks >= 0", name="ck_campaign_insights_clicks_nonnegative"),
        CheckConstraint(
            "inline_link_clicks >= 0",
            name="ck_campaign_insights_inline_link_clicks_nonnegative",
        ),
        CheckConstraint("leads >= 0", name="ck_campaign_insights_leads_nonnegative"),
        CheckConstraint(
            "frequency IS NULL OR frequency >= 0",
            name="ck_campaign_insights_frequency_nonnegative",
        ),
        CheckConstraint(
            "meta_ctr IS NULL OR meta_ctr >= 0",
            name="ck_campaign_insights_meta_ctr_nonnegative",
        ),
        CheckConstraint(
            "meta_cpc IS NULL OR meta_cpc >= 0",
            name="ck_campaign_insights_meta_cpc_nonnegative",
        ),
        CheckConstraint(
            "meta_cpm IS NULL OR meta_cpm >= 0",
            name="ck_campaign_insights_meta_cpm_nonnegative",
        ),
        Index("ix_campaign_insights_campaign_id", "campaign_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="RESTRICT"), nullable=False
    )
    date_start: Mapped[date] = mapped_column(Date, nullable=False)
    date_stop: Mapped[date] = mapped_column(Date, nullable=False)
    spend: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0.00"), server_default="0"
    )
    reach: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    impressions: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    clicks: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    inline_link_clicks: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    leads: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    frequency: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    meta_ctr: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    meta_cpc: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    meta_cpm: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    raw_actions: Mapped[Any | None] = mapped_column(JSON)
    raw_cost_per_action_type: Mapped[Any | None] = mapped_column(JSON)
    raw_response: Mapped[Any | None] = mapped_column(JSON)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )

    campaign: Mapped[Campaign] = relationship(back_populates="insights")


class EnrollmentRecord(Base):
    __tablename__ = "enrollment_records"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id",
            "reference_date",
            "course",
            name="uq_enrollment_records_campaign_date_course",
        ),
        CheckConstraint(
            "length(trim(course)) > 0", name="ck_enrollment_records_course_not_blank"
        ),
        CheckConstraint(
            "contracted_enrollments >= 0",
            name="ck_enrollment_records_contracted_nonnegative",
        ),
        CheckConstraint(
            "paying_enrollments >= 0",
            name="ck_enrollment_records_paying_nonnegative",
        ),
        CheckConstraint(
            "cancellations >= 0", name="ck_enrollment_records_cancellations_nonnegative"
        ),
        CheckConstraint(
            "expected_revenue >= 0",
            name="ck_enrollment_records_expected_revenue_nonnegative",
        ),
        CheckConstraint(
            "received_revenue >= 0",
            name="ck_enrollment_records_received_revenue_nonnegative",
        ),
        CheckConstraint(
            "contribution_margin IS NULL OR contribution_margin >= 0",
            name="ck_enrollment_records_contribution_margin_nonnegative",
        ),
        Index("ix_enrollment_records_campaign_id", "campaign_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="RESTRICT"), nullable=False
    )
    reference_date: Mapped[date] = mapped_column(Date, nullable=False)
    course: Mapped[str] = mapped_column(String(255), nullable=False)
    contracted_enrollments: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    paying_enrollments: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    cancellations: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    expected_revenue: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0.00"), server_default="0"
    )
    received_revenue: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0.00"), server_default="0"
    )
    contribution_margin: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    campaign: Mapped[Campaign] = relationship(back_populates="enrollments")

    @validates("course")
    def normalize_course(self, _key: str, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("course must not be blank")
        return normalized


class SyncRun(Base):
    __tablename__ = "sync_runs"
    __table_args__ = (
        CheckConstraint("date_stop >= date_start", name="ck_sync_runs_date_range"),
        CheckConstraint(
            "campaign_count >= 0", name="ck_sync_runs_campaign_count_nonnegative"
        ),
        CheckConstraint(
            "record_count >= 0", name="ck_sync_runs_record_count_nonnegative"
        ),
        CheckConstraint(
            "status IN ('RUNNING', 'SUCCESS', 'FAILED')",
            name="ck_sync_runs_status",
        ),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="ck_sync_runs_finished_after_started",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[SyncStatus] = mapped_column(
        Enum(
            SyncStatus,
            name="sync_status",
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=SyncStatus.RUNNING,
        server_default=SyncStatus.RUNNING.value,
    )
    date_start: Mapped[date] = mapped_column(Date, nullable=False)
    date_stop: Mapped[date] = mapped_column(Date, nullable=False)
    campaign_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    record_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    error_message: Mapped[str | None] = mapped_column(Text)
