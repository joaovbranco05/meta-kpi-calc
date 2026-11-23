"""Persist an operation key alongside each new commercial activity."""

import sqlalchemy as sa

from alembic import op

revision = "0011_activity_idempotency"
down_revision = "0010_user_display_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lead_activities", sa.Column("idempotency_key", sa.String(36), nullable=True))
    op.create_index(
        "uq_lead_activity_operation", "lead_activities", ["idempotency_key"], unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_lead_activity_operation", table_name="lead_activities")
    op.drop_column("lead_activities", "idempotency_key")
