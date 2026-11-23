"""Administrator-only account provisioning and lifecycle operations."""

from datetime import UTC, datetime
from typing import Literal
from unicodedata import category

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
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
    display_name: str | None = None


class AssigneeView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: Role
    display_name: str | None


class DisplayNamePatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    display_name: str | None = Field(min_length=1, max_length=64)

    @field_validator("display_name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is not None and (
            not any(char.isalnum() for char in value)
            or any(category(char)[0] == "C" or char in "\u2028\u2029" for char in value)
        ):
            raise ValueError("Invalid display name")
        return value


def account_clock(session: SessionDependency) -> datetime:
    if session.get_bind().dialect.name == "postgresql":
        return session.scalar(select(func.clock_timestamp()))
    return datetime.now(UTC)


def lock_accounts(session: SessionDependency) -> None:
    """Serialize account changes and session issuance."""
    if session.get_bind().dialect.name == "postgresql":
        if session.connection().get_isolation_level() != "READ COMMITTED":
            raise HTTPException(503, "Administrative transaction isolation unavailable")
        session.execute(text("SELECT pg_advisory_xact_lock(718503120464)"))
    else:
        # SQLite serializes writers. Start a write transaction without touching a row.
        session.execute(update(AppUser).where(AppUser.id.is_(None)).values(active=False))


def lock_user_management(session: SessionDependency, admin: AppUser) -> None:
    lock_accounts(session)
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


@router.get("/assignees", response_model=list[AssigneeView])
def list_assignees(session: SessionDependency, _admin: CurrentAdmin) -> list[AssigneeView]:
    # Match the assignment policy: all active accounts, including administrators.
    rows = session.execute(
        select(AppUser.id, AppUser.role, AppUser.display_name)
        .where(AppUser.active.is_(True))
        .order_by(AppUser.display_name.asc().nulls_last(), AppUser.id)
    )
    return [AssigneeView.model_validate(row) for row in rows]


@router.patch("/{user_id}/display-name", response_model=AssigneeView)
def update_display_name(
    user_id: int, payload: DisplayNamePatch, session: SessionDependency, admin: CurrentAdmin,
) -> AssigneeView:
    lock_user_management(session, admin)
    user = session.get(AppUser, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    if user.display_name != payload.display_name:
        session.add(AdminAudit(
            actor_user_id=admin.id, target_user_id=user.id, action="display_name_updated",
            previous_value=user.display_name, new_value=payload.display_name,
        ))
        user.display_name = payload.display_name
    result = AssigneeView.model_validate(user)
    session.commit()
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
        user.auth_changed_at = account_clock(session)
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
