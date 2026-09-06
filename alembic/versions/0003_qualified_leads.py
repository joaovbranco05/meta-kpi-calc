"""Add qualified leads to campaign insights.

Revision ID: 0003_qualified_leads
Revises: 0002_domain_models
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_qualified_leads"
down_revision = "0002_domain_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("campaign_insights") as batch_op:
        batch_op.add_column(sa.Column("qualified_leads", sa.Integer(), nullable=True))
        batch_op.create_check_constraint(
            "ck_campaign_insights_qualified_leads_nonnegative",
            "qualified_leads IS NULL OR qualified_leads >= 0",
        )


def downgrade() -> None:
    with op.batch_alter_table("campaign_insights") as batch_op:
        batch_op.drop_constraint(
            "ck_campaign_insights_qualified_leads_nonnegative", type_="check"
        )
        batch_op.drop_column("qualified_leads")
