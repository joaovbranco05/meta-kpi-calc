"""CRM lead and activity persistence models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum as PythonEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from meta_kpi_calc.db.base import Base


def _enum_values(enum_class: type[PythonEnum]) -> list[str]:
    return [member.value for member in enum_class]


class LeadStatus(str, PythonEnum):
    NEW = "NEW"
    CONTACTED = "CONTACTED"
    INTERESTED = "INTERESTED"
    ENROLLED = "ENROLLED"
    NO_RESPONSE = "NO_RESPONSE"
    LOST = "LOST"


class LeadActivityType(str, PythonEnum):
    IMPORTED = "IMPORTED"
    STATUS_CHANGED = "STATUS_CHANGED"
    NOTE = "NOTE"
    CONTACT_ATTEMPTED = "CONTACT_ATTEMPTED"
    CONTACT_MADE = "CONTACT_MADE"
    SOURCE_CORRECTED = "SOURCE_CORRECTED"


class LeadActivityActor(str, PythonEnum):
    SYSTEM_IMPORT = "SYSTEM_IMPORT"
    LOCAL_OPERATOR = "LOCAL_OPERATOR"


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("meta_lead_id", name="uq_leads_meta_lead_id"),
        CheckConstraint("length(trim(meta_lead_id)) > 0", name="ck_leads_meta_lead_id_not_blank"),
        CheckConstraint(
            "commercial_status IN ('NEW', 'CONTACTED', 'INTERESTED', 'ENROLLED', 'NO_RESPONSE', 'LOST')",
            name="ck_leads_commercial_status",
        ),
        Index("ix_leads_commercial_status", "commercial_status"),
        Index("ix_leads_meta_created_time", "meta_created_time"),
        Index("ix_leads_campaign_id", "campaign_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meta_lead_id: Mapped[str] = mapped_column(String(64), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255))
    phone_number: Mapped[str | None] = mapped_column(String(64))
    email: Mapped[str | None] = mapped_column(String(320))
    city: Mapped[str | None] = mapped_column(String(255))
    state: Mapped[str | None] = mapped_column(String(128))
    meta_created_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meta_page_id: Mapped[str | None] = mapped_column(String(64))
    meta_campaign_id: Mapped[str | None] = mapped_column(String(64))
    meta_campaign_name: Mapped[str | None] = mapped_column(String(255))
    meta_adset_id: Mapped[str | None] = mapped_column(String(64))
    meta_adset_name: Mapped[str | None] = mapped_column(String(255))
    meta_ad_id: Mapped[str | None] = mapped_column(String(64))
    meta_ad_name: Mapped[str | None] = mapped_column(String(255))
    meta_form_id: Mapped[str | None] = mapped_column(String(64))
    meta_form_name: Mapped[str | None] = mapped_column(String(255))
    source_status: Mapped[str | None] = mapped_column(String(64))
    is_organic: Mapped[bool | None] = mapped_column(nullable=True)
    platform: Mapped[str | None] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(64), nullable=False, server_default="META_LEAD_ADS")
    course: Mapped[str | None] = mapped_column(String(255))
    campaign_id: Mapped[int | None] = mapped_column(
        ForeignKey("campaigns.id", ondelete="RESTRICT"), nullable=True
    )
    commercial_status: Mapped[LeadStatus] = mapped_column(
        Enum(LeadStatus, name="lead_status", native_enum=False, create_constraint=False,
             validate_strings=True, values_callable=_enum_values),
        nullable=False,
        default=LeadStatus.NEW,
        server_default=LeadStatus.NEW.value,
    )
    last_contact_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    campaign = relationship("Campaign", backref="leads")
    activities: Mapped[list[LeadActivity]] = relationship(
        back_populates="lead", order_by="LeadActivity.created_at, LeadActivity.id"
    )


class LeadActivity(Base):
    __tablename__ = "lead_activities"
    __table_args__ = (
        CheckConstraint(
            "activity_type IN ('IMPORTED', 'STATUS_CHANGED', 'NOTE', 'CONTACT_ATTEMPTED', 'CONTACT_MADE', 'SOURCE_CORRECTED')",
            name="ck_lead_activities_type",
        ),
        CheckConstraint("actor_type IN ('SYSTEM_IMPORT', 'LOCAL_OPERATOR')", name="ck_lead_activities_actor"),
        CheckConstraint(
            "previous_status IS NULL OR previous_status IN ('NEW', 'CONTACTED', 'INTERESTED', 'ENROLLED', 'NO_RESPONSE', 'LOST')",
            name="ck_lead_activities_previous_status",
        ),
        CheckConstraint(
            "new_status IS NULL OR new_status IN ('NEW', 'CONTACTED', 'INTERESTED', 'ENROLLED', 'NO_RESPONSE', 'LOST')",
            name="ck_lead_activities_new_status",
        ),
        CheckConstraint(
            "(activity_type = 'STATUS_CHANGED' AND previous_status IS NOT NULL AND new_status IS NOT NULL) "
            "OR (activity_type != 'STATUS_CHANGED' AND previous_status IS NULL AND new_status IS NULL)",
            name="ck_lead_activities_status_payload",
        ),
        Index("ix_lead_activities_lead_created", "lead_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(
        ForeignKey("leads.id", ondelete="RESTRICT"), nullable=False
    )
    activity_type: Mapped[LeadActivityType] = mapped_column(
        Enum(LeadActivityType, name="lead_activity_type", native_enum=False,
             create_constraint=False, validate_strings=True, values_callable=_enum_values),
        nullable=False,
    )
    actor_type: Mapped[LeadActivityActor] = mapped_column(
        Enum(LeadActivityActor, name="lead_activity_actor", native_enum=False,
             create_constraint=False, validate_strings=True, values_callable=_enum_values),
        nullable=False,
    )
    actor_id: Mapped[str | None] = mapped_column(String(128))
    previous_status: Mapped[LeadStatus | None] = mapped_column(
        Enum(LeadStatus, name="lead_previous_status", native_enum=False,
             create_constraint=False, validate_strings=True, values_callable=_enum_values)
    )
    new_status: Mapped[LeadStatus | None] = mapped_column(
        Enum(LeadStatus, name="lead_new_status", native_enum=False,
             create_constraint=False, validate_strings=True, values_callable=_enum_values)
    )
    note: Mapped[str | None] = mapped_column(Text)
    changed_fields: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )

    lead: Mapped[Lead] = relationship(back_populates="activities")
