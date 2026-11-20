"""Internal identities, revocable sessions and administrative audit records."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from meta_kpi_calc.db.base import Base


class AppUser(Base):
    __tablename__ = "app_users"
    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_app_users_identity"),
        CheckConstraint("role IN ('admin', 'usuario')", name="ck_app_users_role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    issuer: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))
    active: Mapped[bool] = mapped_column(Boolean)
    auth_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AppSession(Base):
    __tablename__ = "app_sessions"

    token_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdminAudit(Base):
    __tablename__ = "admin_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("app_users.id"))
    target_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_users.id"))
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"))
    action: Mapped[str] = mapped_column(String(32))
    previous_value: Mapped[str | None] = mapped_column(String(64))
    new_value: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp()
    )


class OIDCFlow(Base):
    __tablename__ = "oidc_flows"

    state_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    browser_digest: Mapped[str] = mapped_column(String(64))
    verifier: Mapped[str] = mapped_column(String(43))
    nonce: Mapped[str] = mapped_column(String(43))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
