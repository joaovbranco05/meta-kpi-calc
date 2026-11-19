"""Add internal users, sessions, lead ownership and audit records."""

import sqlalchemy as sa

from alembic import op

revision = "0007_crm_authorization"
down_revision = "0006_lead_ads_inbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("issuer", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("active", sa.Boolean, nullable=False),
        sa.UniqueConstraint("issuer", "subject", name="uq_app_users_identity"),
        sa.CheckConstraint("role IN ('admin', 'usuario')", name="ck_app_users_role"),
    )
    op.create_table(
        "app_sessions",
        sa.Column("token_digest", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("app_users.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_app_sessions_user_id", "app_sessions", ["user_id"])
    op.create_table(
        "admin_audit",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("actor_user_id", sa.Integer, sa.ForeignKey("app_users.id"), nullable=False),
        sa.Column("target_user_id", sa.Integer, sa.ForeignKey("app_users.id")),
        sa.Column("lead_id", sa.Integer, sa.ForeignKey("leads.id")),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("previous_value", sa.String(64)),
        sa.Column("new_value", sa.String(64)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
    )
    # Inline nullable references let SQLite preserve the original tables and rows.
    op.execute("ALTER TABLE leads ADD COLUMN assigned_user_id INTEGER REFERENCES app_users(id)")
    op.execute(
        "ALTER TABLE lead_activities ADD COLUMN actor_user_id INTEGER REFERENCES app_users(id)"
    )
    op.create_index("ix_leads_assigned_user_id", "leads", ["assigned_user_id"])


def downgrade() -> None:
    op.drop_index("ix_leads_assigned_user_id", table_name="leads")
    op.drop_column("lead_activities", "actor_user_id")
    op.drop_column("leads", "assigned_user_id")
    op.drop_table("admin_audit")
    op.drop_table("app_sessions")
    op.drop_table("app_users")
