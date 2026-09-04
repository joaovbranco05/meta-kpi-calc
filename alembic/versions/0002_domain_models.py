"""Create campaign, insight, enrollment, and sync-run tables.

Revision ID: 0002_domain_models
Revises: 0001_baseline
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_domain_models"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meta_campaign_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("effective_status", sa.String(length=32), nullable=True),
        sa.Column("objective", sa.String(length=64), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stop_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "brand",
            sa.Enum(
                "RCTEC",
                "FECAF",
                "CURSO_COM_BOLSA",
                "NAO_CLASSIFICADA",
                name="ck_campaigns_brand",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="NAO_CLASSIFICADA",
            nullable=False,
        ),
        sa.Column("course", sa.String(length=255), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(trim(meta_campaign_id)) > 0",
            name="ck_campaigns_meta_campaign_id_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(name)) > 0", name="ck_campaigns_name_not_blank"
        ),
        sa.CheckConstraint(
            "stop_time IS NULL OR start_time IS NULL OR stop_time >= start_time",
            name="ck_campaigns_time_range",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_campaigns"),
        sa.UniqueConstraint(
            "meta_campaign_id", name="uq_campaigns_meta_campaign_id"
        ),
    )

    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "RUNNING",
                "SUCCESS",
                "FAILED",
                name="ck_sync_runs_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="RUNNING",
            nullable=False,
        ),
        sa.Column("date_start", sa.Date(), nullable=False),
        sa.Column("date_stop", sa.Date(), nullable=False),
        sa.Column("campaign_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("record_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "campaign_count >= 0", name="ck_sync_runs_campaign_count_nonnegative"
        ),
        sa.CheckConstraint(
            "record_count >= 0", name="ck_sync_runs_record_count_nonnegative"
        ),
        sa.CheckConstraint(
            "date_stop >= date_start", name="ck_sync_runs_date_range"
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="ck_sync_runs_finished_after_started",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sync_runs"),
    )

    op.create_table(
        "campaign_insights",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("date_start", sa.Date(), nullable=False),
        sa.Column("date_stop", sa.Date(), nullable=False),
        sa.Column("spend", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False),
        sa.Column("reach", sa.Integer(), server_default="0", nullable=False),
        sa.Column("impressions", sa.Integer(), server_default="0", nullable=False),
        sa.Column("clicks", sa.Integer(), server_default="0", nullable=False),
        sa.Column("inline_link_clicks", sa.Integer(), server_default="0", nullable=False),
        sa.Column("leads", sa.Integer(), server_default="0", nullable=False),
        sa.Column("frequency", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("meta_ctr", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("meta_cpc", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("meta_cpm", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("raw_actions", sa.JSON(), nullable=True),
        sa.Column("raw_cost_per_action_type", sa.JSON(), nullable=True),
        sa.Column("raw_response", sa.JSON(), nullable=True),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "date_stop >= date_start", name="ck_campaign_insights_date_range"
        ),
        sa.CheckConstraint("spend >= 0", name="ck_campaign_insights_spend_nonnegative"),
        sa.CheckConstraint("reach >= 0", name="ck_campaign_insights_reach_nonnegative"),
        sa.CheckConstraint(
            "impressions >= 0", name="ck_campaign_insights_impressions_nonnegative"
        ),
        sa.CheckConstraint("clicks >= 0", name="ck_campaign_insights_clicks_nonnegative"),
        sa.CheckConstraint(
            "inline_link_clicks >= 0",
            name="ck_campaign_insights_inline_link_clicks_nonnegative",
        ),
        sa.CheckConstraint("leads >= 0", name="ck_campaign_insights_leads_nonnegative"),
        sa.CheckConstraint(
            "frequency IS NULL OR frequency >= 0",
            name="ck_campaign_insights_frequency_nonnegative",
        ),
        sa.CheckConstraint(
            "meta_ctr IS NULL OR meta_ctr >= 0",
            name="ck_campaign_insights_meta_ctr_nonnegative",
        ),
        sa.CheckConstraint(
            "meta_cpc IS NULL OR meta_cpc >= 0",
            name="ck_campaign_insights_meta_cpc_nonnegative",
        ),
        sa.CheckConstraint(
            "meta_cpm IS NULL OR meta_cpm >= 0",
            name="ck_campaign_insights_meta_cpm_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name="fk_campaign_insights_campaign_id_campaigns",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_campaign_insights"),
        sa.UniqueConstraint(
            "campaign_id",
            "date_start",
            "date_stop",
            name="uq_campaign_insights_campaign_dates",
        ),
    )
    op.create_index(
        "ix_campaign_insights_campaign_id",
        "campaign_insights",
        ["campaign_id"],
        unique=False,
    )

    op.create_table(
        "enrollment_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("reference_date", sa.Date(), nullable=False),
        sa.Column("course", sa.String(length=255), nullable=False),
        sa.Column("contracted_enrollments", sa.Integer(), server_default="0", nullable=False),
        sa.Column("paying_enrollments", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cancellations", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "expected_revenue",
            sa.Numeric(precision=14, scale=2),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "received_revenue",
            sa.Numeric(precision=14, scale=2),
            server_default="0",
            nullable=False,
        ),
        sa.Column("contribution_margin", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(trim(course)) > 0", name="ck_enrollment_records_course_not_blank"
        ),
        sa.CheckConstraint(
            "contracted_enrollments >= 0",
            name="ck_enrollment_records_contracted_nonnegative",
        ),
        sa.CheckConstraint(
            "paying_enrollments >= 0",
            name="ck_enrollment_records_paying_nonnegative",
        ),
        sa.CheckConstraint(
            "cancellations >= 0", name="ck_enrollment_records_cancellations_nonnegative"
        ),
        sa.CheckConstraint(
            "expected_revenue >= 0",
            name="ck_enrollment_records_expected_revenue_nonnegative",
        ),
        sa.CheckConstraint(
            "received_revenue >= 0",
            name="ck_enrollment_records_received_revenue_nonnegative",
        ),
        sa.CheckConstraint(
            "contribution_margin IS NULL OR contribution_margin >= 0",
            name="ck_enrollment_records_contribution_margin_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name="fk_enrollment_records_campaign_id_campaigns",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_enrollment_records"),
        sa.UniqueConstraint(
            "campaign_id",
            "reference_date",
            "course",
            name="uq_enrollment_records_campaign_date_course",
        ),
    )
    op.create_index(
        "ix_enrollment_records_campaign_id",
        "enrollment_records",
        ["campaign_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_enrollment_records_campaign_id", table_name="enrollment_records"
    )
    op.drop_table("enrollment_records")
    op.drop_index(
        "ix_campaign_insights_campaign_id", table_name="campaign_insights"
    )
    op.drop_table("campaign_insights")
    op.drop_table("sync_runs")
    op.drop_table("campaigns")
