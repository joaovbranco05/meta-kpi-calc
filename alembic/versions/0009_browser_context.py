"""Fence login callbacks and sessions by browser context."""

import sqlalchemy as sa

from alembic import op

revision = "0009_browser_context"
down_revision = "0008_oidc_flows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "browser_contexts",
        sa.Column("digest", sa.String(64), primary_key=True),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute("DELETE FROM oidc_flows")
    op.add_column("oidc_flows", sa.Column("generation", sa.Integer(), nullable=False))
    op.execute(
        "ALTER TABLE app_sessions ADD COLUMN browser_digest VARCHAR(64) "
        "REFERENCES browser_contexts(digest)"
    )
    op.create_index("ix_app_sessions_browser_digest", "app_sessions", ["browser_digest"])
    op.execute("UPDATE app_sessions SET revoked_at = CURRENT_TIMESTAMP WHERE revoked_at IS NULL")


def downgrade() -> None:
    op.execute("DELETE FROM oidc_flows")
    op.execute("DELETE FROM app_sessions WHERE browser_digest IS NOT NULL")
    op.drop_index("ix_app_sessions_browser_digest", table_name="app_sessions")
    op.drop_column("app_sessions", "browser_digest")
    op.drop_column("oidc_flows", "generation")
    op.drop_table("browser_contexts")
