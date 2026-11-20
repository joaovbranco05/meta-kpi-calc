"""Store short-lived single-use OIDC transactions."""

import sqlalchemy as sa

from alembic import op

revision = "0008_oidc_flows"
down_revision = "0007_crm_authorization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_users", sa.Column("auth_changed_at", sa.DateTime(timezone=True)))
    op.create_table(
        "oidc_flows",
        sa.Column("state_digest", sa.String(64), primary_key=True),
        sa.Column("browser_digest", sa.String(64), nullable=False),
        sa.Column("verifier", sa.String(43), nullable=False),
        sa.Column("nonce", sa.String(43), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_oidc_flows_expires_at", "oidc_flows", ["expires_at"])


def downgrade() -> None:
    op.drop_table("oidc_flows")
    op.drop_column("app_users", "auth_changed_at")
