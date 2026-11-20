"""Administrator-only account provisioning and lifecycle operations."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError

from meta_kpi_calc.auth.dependencies import CurrentAdmin, SessionDependency
from meta_kpi_calc.auth.models import AdminAudit, AppSession, AppUser

router = APIRouter(prefix="/api/admin/users", tags=["Admin"])
Role = Literal["admin", "usuario"]


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    issuer: str = Field(min_length=1, max_length=255)
    subject: str = Field(min_length=1, max_length=255)
    role: Role


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Role
    active: bool


class UserView(UserCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    active: bool


def lock_user_management(session: SessionDependency, admin: AppUser) -> None:
    """Serialize account mutations and recheck the acting administrator under the lock."""
    if session.get_bind().dialect.name == "postgresql":
        if session.connection().get_isolation_level() != "READ COMMITTED":
            raise HTTPException(503, "Administrative transaction isolation unavailable")
        session.execute(text("SELECT pg_advisory_xact_lock(718503120464)"))
    else:
        # SQLite serializes writers. Start a write transaction without touching a row.
        session.execute(update(AppUser).where(AppUser.id.is_(None)).values(active=False))
    session.refresh(admin)
    if not admin.active:
        raise HTTPException(401, "Authentication required")
    if admin.role != "admin":
        raise HTTPException(403, "Administrator permission required")


@router.get("")
def list_users(session: SessionDependency, _admin: CurrentAdmin) -> list[UserView]:
    return [
        UserView.model_validate(user)
        for user in session.scalars(select(AppUser).order_by(AppUser.id))
    ]


@router.post("", status_code=201)
def create_user(payload: UserCreate, session: SessionDependency, admin: CurrentAdmin) -> UserView:
    lock_user_management(session, admin)
    user = AppUser(**payload.model_dump(), active=True)
    try:
        session.add(user)
        session.flush()
        session.add(
            AdminAudit(
                actor_user_id=admin.id,
                target_user_id=user.id,
                action="user_created",
                new_value=user.role,
            )
        )
        result = UserView.model_validate(user)
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "Identity already registered") from None
    return result


@router.put("/{user_id}")
def update_user(
    user_id: int, payload: UserUpdate, session: SessionDependency, admin: CurrentAdmin
) -> UserView:
    lock_user_management(session, admin)
    user = session.get(AppUser, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    if user.active and user.role == "admin" and (not payload.active or payload.role != "admin"):
        count = session.scalar(
            select(func.count())
            .select_from(AppUser)
            .where(AppUser.active.is_(True), AppUser.role == "admin")
        )
        if count == 1:
            raise HTTPException(409, "At least one active administrator is required")
    before = f"{user.role}:{user.active}"
    after = f"{payload.role}:{payload.active}"
    if before != after:
        revoke_sessions = user.role != payload.role or not payload.active
        user.role, user.active = payload.role, payload.active
        if revoke_sessions:
            session.execute(
                update(AppSession)
                .where(AppSession.user_id == user.id, AppSession.revoked_at.is_(None))
                .values(revoked_at=datetime.now(UTC))
            )
        session.add(
            AdminAudit(
                actor_user_id=admin.id,
                target_user_id=user.id,
                action="user_updated",
                previous_value=before,
                new_value=after,
            )
        )
    result = UserView.model_validate(user)
    session.commit()
    return result
