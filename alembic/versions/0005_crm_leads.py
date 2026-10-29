"""Add individual CRM leads and append-only activities.

Revision ID: 0005_crm_leads
Revises: 0004_commercial_closures
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_crm_leads"
down_revision = "0004_commercial_closures"
branch_labels = None
depends_on = None

LEAD_STATUSES = "'NEW', 'CONTACTED', 'INTERESTED', 'ENROLLED', 'NO_RESPONSE', 'LOST'"


def upgrade() -> None:
    op.create_table(
        "leads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meta_lead_id", sa.String(length=64), nullable=False),
        sa.Column("full_name", sa.String(length=255)),
        sa.Column("phone_number", sa.String(length=64)),
        sa.Column("email", sa.String(length=320)),
        sa.Column("city", sa.String(length=255)),
        sa.Column("state", sa.String(length=128)),
        sa.Column("meta_created_time", sa.DateTime(timezone=True)),
        sa.Column("meta_campaign_id", sa.String(length=64)),
        sa.Column("meta_campaign_name", sa.String(length=255)),
        sa.Column("meta_adset_id", sa.String(length=64)),
        sa.Column("meta_adset_name", sa.String(length=255)),
        sa.Column("meta_ad_id", sa.String(length=64)),
        sa.Column("meta_ad_name", sa.String(length=255)),
        sa.Column("meta_form_id", sa.String(length=64)),
        sa.Column("meta_form_name", sa.String(length=255)),
        sa.Column("source_status", sa.String(length=64)),
        sa.Column("is_organic", sa.Boolean()),
        sa.Column("platform", sa.String(length=64)),
        sa.Column("source", sa.String(length=64), nullable=False, server_default="META_LEAD_ADS"),
        sa.Column("course", sa.String(length=255)),
        sa.Column("campaign_id", sa.Integer()),
        sa.Column(
            "commercial_status",
            sa.Enum("NEW", "CONTACTED", "INTERESTED", "ENROLLED", "NO_RESPONSE", "LOST",
                    name="lead_status", native_enum=False, create_constraint=False),
            nullable=False,
            server_default="NEW",
        ),
        sa.Column("last_contact_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("length(trim(meta_lead_id)) > 0", name="ck_leads_meta_lead_id_not_blank"),
        sa.CheckConstraint(f"commercial_status IN ({LEAD_STATUSES})", name="ck_leads_commercial_status"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], name="fk_leads_campaign_id_campaigns", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_leads"),
        sa.UniqueConstraint("meta_lead_id", name="uq_leads_meta_lead_id"),
    )
    op.create_index("ix_leads_commercial_status", "leads", ["commercial_status"])
    op.create_index("ix_leads_meta_created_time", "leads", ["meta_created_time"])
    op.create_index("ix_leads_campaign_id", "leads", ["campaign_id"])

    op.create_table(
        "lead_activities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("activity_type", sa.Enum("IMPORTED", "STATUS_CHANGED", "NOTE", "CONTACT_ATTEMPTED", "CONTACT_MADE", "SOURCE_CORRECTED", name="lead_activity_type", native_enum=False, create_constraint=False), nullable=False),
        sa.Column("actor_type", sa.Enum("SYSTEM_IMPORT", "LOCAL_OPERATOR", name="lead_activity_actor", native_enum=False, create_constraint=False), nullable=False),
        sa.Column("actor_id", sa.String(length=128)),
        sa.Column("previous_status", sa.Enum("NEW", "CONTACTED", "INTERESTED", "ENROLLED", "NO_RESPONSE", "LOST", name="lead_previous_status", native_enum=False, create_constraint=False)),
        sa.Column("new_status", sa.Enum("NEW", "CONTACTED", "INTERESTED", "ENROLLED", "NO_RESPONSE", "LOST", name="lead_new_status", native_enum=False, create_constraint=False)),
        sa.Column("note", sa.Text()),
        sa.Column("changed_fields", sa.String(length=512)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("activity_type IN ('IMPORTED', 'STATUS_CHANGED', 'NOTE', 'CONTACT_ATTEMPTED', 'CONTACT_MADE', 'SOURCE_CORRECTED')", name="ck_lead_activities_type"),
        sa.CheckConstraint("actor_type IN ('SYSTEM_IMPORT', 'LOCAL_OPERATOR')", name="ck_lead_activities_actor"),
        sa.CheckConstraint(f"previous_status IS NULL OR previous_status IN ({LEAD_STATUSES})", name="ck_lead_activities_previous_status"),
        sa.CheckConstraint(f"new_status IS NULL OR new_status IN ({LEAD_STATUSES})", name="ck_lead_activities_new_status"),
        sa.CheckConstraint("(activity_type = 'STATUS_CHANGED' AND previous_status IS NOT NULL AND new_status IS NOT NULL) OR (activity_type != 'STATUS_CHANGED' AND previous_status IS NULL AND new_status IS NULL)", name="ck_lead_activities_status_payload"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], name="fk_lead_activities_lead_id_leads", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_lead_activities"),
    )
    op.create_index("ix_lead_activities_lead_created", "lead_activities", ["lead_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_lead_activities_lead_created", table_name="lead_activities")
    op.drop_table("lead_activities")
    op.drop_index("ix_leads_campaign_id", table_name="leads")
    op.drop_index("ix_leads_meta_created_time", table_name="leads")
    op.drop_index("ix_leads_commercial_status", table_name="leads")
    op.drop_table("leads")
