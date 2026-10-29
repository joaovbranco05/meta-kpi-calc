"""Add durable Lead Ads inbox and reconciliation metadata.

Revision ID: 0006_lead_ads_inbox
Revises: 0005_crm_leads
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_lead_ads_inbox"
down_revision = "0005_crm_leads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("meta_page_id", sa.String(64), nullable=True))
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dedup_key", sa.String(160), nullable=False),
        sa.Column("meta_lead_id", sa.String(64), nullable=False),
        sa.Column("meta_page_id", sa.String(64), nullable=False),
        sa.Column("meta_form_id", sa.String(64)),
        sa.Column("meta_ad_id", sa.String(64)),
        sa.Column("source", sa.String(32), nullable=False, server_default="WEBHOOK"),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unmapped_fields", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("lease_token", sa.String(64)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(32)),
        sa.UniqueConstraint("dedup_key", name="uq_webhook_events_dedup_key"),
        sa.CheckConstraint("status IN ('PENDING','PROCESSING','COMPLETED','RETRY','FAILED')", name="ck_webhook_events_status"),
        sa.CheckConstraint("attempts >= 0 AND unmapped_fields >= 0", name="ck_webhook_events_counts"),
        sa.CheckConstraint("source = 'WEBHOOK'", name="ck_webhook_events_source"),
        sa.CheckConstraint("(status = 'PROCESSING' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR (status != 'PROCESSING' AND lease_token IS NULL AND lease_expires_at IS NULL)", name="ck_webhook_events_lease"),
    )
    op.create_index("ix_webhook_events_due", "webhook_events", ["status", "next_attempt_at"])
    op.create_index("ix_webhook_events_lease", "webhook_events", ["lease_expires_at"])
    op.create_table(
        "lead_reconciliation_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("meta_page_id", sa.String(64), nullable=False),
        sa.Column("meta_form_id", sa.String(64), nullable=False),
        sa.Column("completed_until", sa.DateTime(timezone=True)),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_result", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("processed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unmapped_fields", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(32)),
        sa.Column("lease_token", sa.String(64)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("meta_page_id", "meta_form_id", name="uq_lead_reconciliation_source"),
        sa.CheckConstraint("last_result IN ('PENDING','PROCESSING','COMPLETED','FAILED')", name="ck_lead_reconciliation_result"),
        sa.CheckConstraint("(last_result = 'PROCESSING' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR (last_result != 'PROCESSING' AND lease_token IS NULL AND lease_expires_at IS NULL)", name="ck_lead_reconciliation_lease"),
        sa.CheckConstraint("processed_count >= 0 AND unmapped_fields >= 0", name="ck_lead_reconciliation_counts"),
    )


def downgrade() -> None:
    op.drop_table("lead_reconciliation_states")
    op.drop_index("ix_webhook_events_lease", table_name="webhook_events")
    op.drop_index("ix_webhook_events_due", table_name="webhook_events")
    op.drop_table("webhook_events")
    op.drop_column("leads", "meta_page_id")
