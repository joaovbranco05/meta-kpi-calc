"""Durable technical metadata, deliberately excluding webhook/Graph payloads."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from meta_kpi_calc.db.base import Base


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    __table_args__ = (
        UniqueConstraint("dedup_key", name="uq_webhook_events_dedup_key"),
        CheckConstraint("status IN ('PENDING','PROCESSING','COMPLETED','RETRY','FAILED')", name="ck_webhook_events_status"),
        CheckConstraint("attempts >= 0 AND unmapped_fields >= 0", name="ck_webhook_events_counts"),
        CheckConstraint("source = 'WEBHOOK'", name="ck_webhook_events_source"),
        CheckConstraint("(status = 'PROCESSING' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR (status != 'PROCESSING' AND lease_token IS NULL AND lease_expires_at IS NULL)", name="ck_webhook_events_lease"),
        Index("ix_webhook_events_due", "status", "next_attempt_at"),
        Index("ix_webhook_events_lease", "lease_expires_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dedup_key: Mapped[str] = mapped_column(String(160), nullable=False)
    meta_lead_id: Mapped[str] = mapped_column(String(64), nullable=False)
    meta_page_id: Mapped[str] = mapped_column(String(64), nullable=False)
    meta_form_id: Mapped[str | None] = mapped_column(String(64))
    meta_ad_id: Mapped[str | None] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(32), nullable=False, server_default="WEBHOOK")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    unmapped_fields: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.current_timestamp())
    lease_token: Mapped[str | None] = mapped_column(String(64))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.current_timestamp())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(32))


class ReconciliationState(Base):
    __tablename__ = "lead_reconciliation_states"
    __table_args__ = (
        UniqueConstraint("meta_page_id", "meta_form_id", name="uq_lead_reconciliation_source"),
        CheckConstraint("last_result IN ('PENDING','PROCESSING','COMPLETED','FAILED')", name="ck_lead_reconciliation_result"),
        CheckConstraint("(last_result = 'PROCESSING' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR (last_result != 'PROCESSING' AND lease_token IS NULL AND lease_expires_at IS NULL)", name="ck_lead_reconciliation_lease"),
        CheckConstraint("processed_count >= 0 AND unmapped_fields >= 0", name="ck_lead_reconciliation_counts"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meta_page_id: Mapped[str] = mapped_column(String(64), nullable=False)
    meta_form_id: Mapped[str] = mapped_column(String(64), nullable=False)
    completed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_result: Mapped[str] = mapped_column(String(16), nullable=False, server_default="PENDING")
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    unmapped_fields: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(32))
    lease_token: Mapped[str | None] = mapped_column(String(64))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
