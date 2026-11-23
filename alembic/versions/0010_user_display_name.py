"""Add an optional operational label to internal accounts."""

import sqlalchemy as sa

from alembic import op

revision = "0010_user_display_name"
down_revision = "0009_browser_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_users", sa.Column("display_name", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("app_users", "display_name")
