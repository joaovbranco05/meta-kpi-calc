"""Add explicit commercial closure states for daily campaign data.

Revision ID: 0004_commercial_closures
Revises: 0003_qualified_leads
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_commercial_closures"
down_revision = "0003_qualified_leads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "commercial_closures",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("reference_date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PARTIAL",
                "COMPLETE",
                name="commercial_closure_status",
                native_enum=False,
                create_constraint=False,
            ),
            nullable=False,
        ),
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
            "status IN ('PARTIAL', 'COMPLETE')",
            name="ck_commercial_closures_status",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name="fk_commercial_closures_campaign_id_campaigns",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_commercial_closures"),
        sa.UniqueConstraint(
            "campaign_id",
            "reference_date",
            name="uq_commercial_closures_campaign_date",
        ),
    )
    op.create_index(
        "ix_commercial_closures_campaign_id",
        "commercial_closures",
        ["campaign_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_commercial_closures_campaign_id", table_name="commercial_closures")
    op.drop_table("commercial_closures")
